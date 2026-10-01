import hashlib
import json
import uuid

from fastapi import HTTPException
import regex
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import (
    comment_error, lock_active_user, lock_content, require_participation, require_readable_content,
)
from api.comments.read import effective_spoiler, get_readable_comment, mention_candidates_query
from api.comments.schemas import CommentCreateRequest, CommentWriteRequest
from api.core.rate_limit import check_rate_limit
from api.db.models import (
    Comment, CommentMention, CommentMute, CommentNotificationPreference, CommentSticker, Content, ContentVisibility,
    Notification, User,
)


async def validate_write(
    db: AsyncSession, content: Content, user_id: uuid.UUID, payload: CommentWriteRequest,
    existing: Comment | None = None,
) -> list[uuid.UUID]:
    if not payload.body.strip() and payload.sticker_id is None:
        raise comment_error(422, "COMMENT_EMPTY", "본문 또는 스티커를 입력해 주세요.")
    for index, _ in enumerate(regex.finditer(r"\X", payload.body), start=1):
        if index > 1000:
            raise comment_error(422, "COMMENT_TEXT_TOO_LONG", "댓글은 1,000자까지 입력할 수 있습니다.")
    if payload.sticker_id is not None:
        sticker = await db.get(CommentSticker, payload.sticker_id)
        if sticker is None or (not sticker.is_selectable and (existing is None or existing.sticker_id != sticker.id)):
            raise comment_error(422, "COMMENT_STICKER_INVALID", "선택할 수 없는 스티커입니다.")
    mentions = list(dict.fromkeys(payload.mention_user_ids))
    if len(mentions) > 3:
        raise comment_error(422, "COMMENT_MENTION_INVALID", "멘션은 서로 다른 3명까지 선택할 수 있습니다.")
    if existing is not None and content.visibility == ContentVisibility.PRIVATE:
        previous = set((await db.scalars(select(CommentMention.user_id).where(
            CommentMention.comment_id == existing.id
        ))).all())
        if not set(mentions).issubset(previous):
            raise comment_error(403, "COMMENT_PARTICIPATION_UNAVAILABLE", "비공개 작품에는 새 멘션을 추가할 수 없습니다.")
        return mentions
    if mentions:
        available = set((await db.scalars(mention_candidates_query(content, user_id).with_only_columns(User.id)
                                         .where(User.id.in_(mentions)))).all())
        if set(mentions) != available:
            raise comment_error(422, "COMMENT_MENTION_INVALID", "이 작품에서 선택할 수 없는 멘션 대상입니다.")
    return mentions


async def _creation_notifications(
    db: AsyncSession, content: Content, comment: Comment, target: Comment | None, mentions: list[uuid.UUID]
) -> None:
    events: list[tuple[uuid.UUID, str]] = []
    if target is not None:
        events.append((target.author_user_id, "comment-reply"))
    events.extend((user_id, "comment-mention") for user_id in mentions)
    if target is None:
        events.append((content.creator_user_id, "comment-created"))
    recipients = {user_id for user_id, _ in events if user_id != comment.author_user_id}
    if not recipients:
        return
    active = set((await db.scalars(select(User.id).where(
        User.id.in_(recipients), User.deleted_at.is_(None), User.suspended_at.is_(None)
    ))).all())
    muted = set((await db.scalars(select(CommentMute.viewer_user_id).where(
        CommentMute.viewer_user_id.in_(recipients), CommentMute.target_user_id == comment.author_user_id
    ))).all())
    preferences = {p.user_id: p for p in (await db.scalars(select(CommentNotificationPreference).where(
        CommentNotificationPreference.user_id.in_(recipients)
    ))).all()}
    chosen: dict[uuid.UUID, str] = {}
    for user_id, event in events:
        if user_id not in active or user_id in muted:
            continue
        preference = preferences.get(user_id)
        enabled = preference is None or (
            preference.reply if event == "comment-reply" else
            preference.mention if event == "comment-mention" else preference.new_comment
        )
        if enabled:
            chosen.setdefault(user_id, event)
    db.add_all([Notification(
        user_id=user_id, type=event, content_id=content.id, comment_id=comment.id,
        actor_user_id=comment.author_user_id,
    ) for user_id, event in chosen.items()])


async def create_comment(
    db: AsyncSession, content_id: uuid.UUID, user_id: uuid.UUID, payload: CommentCreateRequest
) -> tuple[Content, Comment, bool]:
    await lock_active_user(db, user_id)
    fingerprint = hashlib.sha256(json.dumps({
        "contentId": str(content_id), **payload.model_dump(mode="json"),
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    existing = await db.scalar(select(Comment).where(
        Comment.author_user_id == user_id, Comment.request_id == payload.request_id
    ))
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise comment_error(409, "COMMENT_REQUEST_CONFLICT", "동일 요청 ID로 다른 댓글을 전송할 수 없습니다.")
        content = await lock_content(db, content_id)
        require_readable_content(content, user_id)
        await db.commit()
        return content, existing, False
    retry_after = await check_rate_limit("comment-create", str(user_id), 5, window_seconds=60)
    if retry_after:
        raise HTTPException(status_code=429, detail={
            "code": "COMMENT_RATE_LIMITED", "message": "잠시 후 다시 작성해 주세요.",
            "retryAfterSeconds": retry_after,
        }, headers={"Retry-After": str(retry_after)})
    content = await lock_content(db, content_id)
    require_readable_content(content, user_id)
    require_participation(content)
    if not content.comments_enabled:
        raise comment_error(403, "COMMENTS_PAUSED", "작가가 새 댓글 작성을 중지했습니다.")
    mentions = await validate_write(db, content, user_id, payload)
    root: Comment | None = None
    target: Comment | None = None
    if (payload.root_comment_id is None) != (payload.reply_to_comment_id is None):
        raise comment_error(422, "COMMENT_REPLY_TARGET_INVALID", "답글의 스레드와 대상을 함께 지정해 주세요.")
    if payload.root_comment_id is not None and payload.reply_to_comment_id is not None:
        rows = {c.id: c for c in (await db.scalars(select(Comment).where(
            Comment.id.in_([payload.root_comment_id, payload.reply_to_comment_id])
        ).order_by(Comment.id).with_for_update().execution_options(populate_existing=True))).all()}
        root, target = rows.get(payload.root_comment_id), rows.get(payload.reply_to_comment_id)
        if (
            root is None or target is None or root.content_id != content_id or target.content_id != content_id
            or root.root_comment_id is not None
            or (target.id != root.id and target.root_comment_id != root.id)
        ):
            raise comment_error(422, "COMMENT_REPLY_TARGET_INVALID", "답글 대상과 스레드가 일치하지 않습니다.")
        if target.deleted_at is not None:
            raise comment_error(409, "COMMENT_DELETED", "삭제된 댓글에 직접 답할 수 없습니다.")
        await get_readable_comment(db, content, target.id, user_id)
    related = {c.id: c for c in (root, target) if c is not None}
    inherited = any(effective_spoiler(c, related) for c in related.values())
    comment = Comment(
        content_id=content_id, author_user_id=user_id, body=payload.body, sticker_id=payload.sticker_id,
        is_spoiler=payload.is_spoiler, inherited_spoiler=inherited,
        request_id=payload.request_id, request_fingerprint=fingerprint,
        root_comment_id=payload.root_comment_id, reply_to_comment_id=payload.reply_to_comment_id,
    )
    db.add(comment)
    await db.flush()
    db.add_all([CommentMention(comment_id=comment.id, user_id=mentioned) for mentioned in mentions])
    await _creation_notifications(db, content, comment, target, mentions)
    await db.commit()
    return content, comment, True
