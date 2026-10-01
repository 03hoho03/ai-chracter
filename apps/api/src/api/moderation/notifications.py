import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.comments.read import notification_targets
from api.db.models.comments import Comment, CommentMute
from api.db.models.inquiry import Inquiry
from api.db.models.moderation import Notification
from api.db.models.notice import Notice
from api.moderation.schemas import NotificationListResponse, NotificationResponse

COMMENT_NOTIFICATION_TYPES = ("comment-created", "comment-reply", "comment-mention")


def visible_notification_filter(user_id: uuid.UUID) -> ColumnElement[bool]:
    muted = exists(
        select(CommentMute.viewer_user_id).where(
            CommentMute.viewer_user_id == user_id, CommentMute.target_user_id == Notification.actor_user_id
        )
    )
    return and_(Notification.user_id == user_id, or_(Notification.type.not_in(COMMENT_NOTIFICATION_TYPES), ~muted))


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(visible_notification_filter(user_id), Notification.read.is_(False))
        )
    ) or 0


async def serialize_notifications(
    db: AsyncSession, notifications: Sequence[Notification], user_id: uuid.UUID
) -> list[NotificationResponse]:
    notice_ids = {item.notice_id for item in notifications if item.notice_id is not None}
    inquiry_ids = {item.inquiry_id for item in notifications if item.inquiry_id is not None}
    notices: dict[uuid.UUID, str] = (
        {
            identifier: title
            for identifier, title in (
                await db.execute(select(Notice.id, Notice.title).where(Notice.id.in_(notice_ids)))
            ).all()
        }
        if notice_ids
        else {}
    )
    inquiries: dict[uuid.UUID, str] = (
        {
            identifier: title
            for identifier, title in (
                await db.execute(select(Inquiry.id, Inquiry.title).where(Inquiry.id.in_(inquiry_ids)))
            ).all()
        }
        if inquiry_ids
        else {}
    )
    comment_ids = {item.comment_id for item in notifications if item.comment_id is not None}
    comments = (
        {item.id: item for item in (await db.scalars(select(Comment).where(Comment.id.in_(comment_ids)))).all()}
        if comment_ids
        else {}
    )
    targets = await notification_targets(db, list(comments.values()), user_id)
    items = []
    for notification in notifications:
        target = None
        title = (
            notices.get(notification.notice_id)
            if notification.notice_id
            else inquiries.get(notification.inquiry_id)
            if notification.inquiry_id
            else None
        )
        if notification.comment_id is not None:
            comment = comments.get(notification.comment_id)
            if comment is not None:
                target = targets[comment.id]
                title = "스포일러가 포함된 댓글 알림" if target.is_spoiler else "댓글 알림"
                if target.availability == "unavailable":
                    title = "현재 확인할 수 없는 댓글 알림"
        items.append(
            NotificationResponse(
                id=notification.id,
                type=notification.type,
                content_id=notification.content_id,
                action_id=notification.action_id,
                comment_action_id=notification.comment_action_id,
                notice_id=notification.notice_id,
                inquiry_id=notification.inquiry_id,
                title=title,
                reason_category=notification.reason_category,
                admin_comment=notification.admin_comment,
                created_at=notification.created_at,
                read=notification.read,
                comment=target,
            )
        )
    return items


def _cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(value.encode()))
        created = datetime.fromisoformat(data["createdAt"])
        identifier = uuid.UUID(data["id"])
        if created.tzinfo is None:
            raise ValueError("timezone required")
        return created, identifier
    except (ValueError, TypeError, KeyError, binascii.Error, UnicodeError) as error:
        raise HTTPException(status_code=422, detail="알림 조회 위치가 올바르지 않아요.") from error


async def notification_page(db: AsyncSession, user_id: uuid.UUID, cursor: str | None) -> NotificationListResponse:
    filters = [visible_notification_filter(user_id)]
    if cursor is not None:
        created, identifier = _cursor(cursor)
        filters.append(
            or_(
                Notification.created_at < created,
                and_(Notification.created_at == created, Notification.id < identifier),
            )
        )
    rows = list(
        (
            await db.scalars(
                select(Notification)
                .where(*filters)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(21)
            )
        ).all()
    )
    next_cursor = None
    if len(rows) > 20:
        last = rows[19]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({"createdAt": last.created_at.isoformat(), "id": str(last.id)}).encode()
        ).decode()
    return NotificationListResponse(
        items=await serialize_notifications(db, rows[:20], user_id),
        next_cursor=next_cursor,
        unread_count=await unread_count(db, user_id),
    )
