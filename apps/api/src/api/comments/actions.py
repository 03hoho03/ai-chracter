import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import (
    comment_error, lock_active_user, lock_comment_context, lock_content, require_creator,
    require_participation, require_readable_content, require_unhide_allowed,
)
from api.comments.read import get_readable_comment, normal_comment_clause
from api.comments.schemas import (
    CommentLikeResponse, CommentNotificationPreferencesResponse,
    CommentNotificationPreferencesUpdateRequest, CommentUpdateRequest,
)
from api.comments.write import validate_write
from api.core.rate_limit import check_rate_limit
from api.db.models import (
    Comment, CommentLike, CommentMention, CommentMute, CommentNotificationPreference, Content, User,
)


def _require_author(comment: Comment, user_id: uuid.UUID) -> None:
    if comment.author_user_id != user_id:
        raise comment_error(403, "COMMENT_OWNER_REQUIRED", "댓글 작성자만 변경할 수 있습니다.")


def _require_alive(comment: Comment) -> None:
    if comment.deleted_at is not None:
        raise comment_error(409, "COMMENT_DELETED", "삭제된 댓글을 변경할 수 없습니다.")


async def update_comment(
    db: AsyncSession, comment_id: uuid.UUID, user_id: uuid.UUID, payload: CommentUpdateRequest
) -> tuple[Content, Comment]:
    await lock_active_user(db, user_id)
    retry_after = await check_rate_limit("comment-update", str(user_id), 10, window_seconds=60)
    if retry_after:
        raise HTTPException(status_code=429, detail={
            "code": "COMMENT_RATE_LIMITED", "message": "잠시 후 다시 수정해 주세요.",
            "retryAfterSeconds": retry_after,
        }, headers={"Retry-After": str(retry_after)})
    content, comment = await lock_comment_context(db, comment_id)
    require_readable_content(content, user_id)
    _require_author(comment, user_id)
    _require_alive(comment)
    await get_readable_comment(db, content, comment_id, user_id)
    mentions = await validate_write(db, content, user_id, payload, existing=comment)
    old_mentions = set((await db.scalars(select(CommentMention.user_id).where(
        CommentMention.comment_id == comment_id
    ))).all())
    changed = (comment.body, comment.sticker_id, comment.is_spoiler, old_mentions) != (
        payload.body, payload.sticker_id, payload.is_spoiler, set(mentions)
    )
    if changed:
        added_spoiler = payload.is_spoiler and not comment.is_spoiler
        comment.body, comment.sticker_id, comment.is_spoiler = payload.body, payload.sticker_id, payload.is_spoiler
        comment.updated_at = datetime.now(UTC)
        await db.execute(delete(CommentMention).where(CommentMention.comment_id == comment_id))
        db.add_all([CommentMention(comment_id=comment_id, user_id=mentioned) for mentioned in mentions])
        if added_spoiler:
            # 실제 답글 대상의 모든 후손에 보호를 남겨 삭제·개인 숨김 뒤에도 유지한다.
            if comment.root_comment_id is None:
                descendants = select(Comment.id).where(Comment.root_comment_id == comment_id)
            else:
                chain = select(Comment.id).where(Comment.reply_to_comment_id == comment_id).cte(recursive=True)
                chain = chain.union_all(select(Comment.id).join(chain, Comment.reply_to_comment_id == chain.c.id))
                descendants = select(chain.c.id)
            await db.execute(update(Comment).where(Comment.id.in_(descendants)).values(inherited_spoiler=True))
    await db.commit()
    return content, comment


async def delete_comment(db: AsyncSession, comment_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await lock_active_user(db, user_id)
    content, comment = await lock_comment_context(db, comment_id)
    require_readable_content(content, user_id)
    _require_author(comment, user_id)
    if comment.deleted_at is None:
        comment.body, comment.sticker_id, comment.deleted_at = None, None, datetime.now(UTC)
        await db.execute(delete(CommentMention).where(CommentMention.comment_id == comment_id))
        await db.execute(delete(CommentLike).where(CommentLike.comment_id == comment_id))
        if content.pinned_comment_id == comment_id:
            content.pinned_comment_id = None
    await db.commit()


async def set_like(
    db: AsyncSession, comment_id: uuid.UUID, user_id: uuid.UUID, liked: bool
) -> CommentLikeResponse:
    await lock_active_user(db, user_id)
    content, comment = await lock_comment_context(db, comment_id)
    require_readable_content(content, user_id)
    _require_alive(comment)
    await get_readable_comment(db, content, comment_id, user_id)
    require_participation(content)
    if liked:
        await db.execute(insert(CommentLike).values(comment_id=comment_id, user_id=user_id).on_conflict_do_nothing())
    else:
        await db.execute(delete(CommentLike).where(CommentLike.comment_id == comment_id, CommentLike.user_id == user_id))
    count = await db.scalar(select(func.count()).select_from(CommentLike).where(CommentLike.comment_id == comment_id))
    await db.commit()
    return CommentLikeResponse(comment_id=comment_id, like_count=count or 0, is_liked=liked)


async def manage_content(db: AsyncSession, content_id: uuid.UUID, user_id: uuid.UUID) -> Content:
    await lock_active_user(db, user_id)
    content = await lock_content(db, content_id)
    require_readable_content(content, user_id)
    require_creator(content, user_id)
    return content


async def set_pin(
    db: AsyncSession, content_id: uuid.UUID, user_id: uuid.UUID, comment_id: uuid.UUID | None
) -> tuple[Content, Comment | None]:
    content = await manage_content(db, content_id, user_id)
    comment = None
    if comment_id is not None:
        comment = await db.scalar(select(Comment).where(
            Comment.id == comment_id, Comment.content_id == content_id,
            Comment.root_comment_id.is_(None), normal_comment_clause(user_id),
        ).with_for_update())
        if comment is None:
            raise comment_error(422, "COMMENT_PIN_INVALID", "이 작품의 정상 원댓글만 고정할 수 있습니다.")
    content.pinned_comment_id = comment_id
    await db.commit()
    return content, comment


async def set_creator_hidden(
    db: AsyncSession, comment_id: uuid.UUID, user_id: uuid.UUID, hidden: bool
) -> None:
    await lock_active_user(db, user_id)
    content, comment = await lock_comment_context(db, comment_id)
    require_readable_content(content, user_id)
    require_creator(content, user_id)
    if hidden:
        _require_alive(comment)
    else:
        require_unhide_allowed(comment)
    comment.creator_hidden = hidden
    if hidden and content.pinned_comment_id == comment_id:
        content.pinned_comment_id = None
    await db.commit()


async def set_mute(db: AsyncSession, user_id: uuid.UUID, target_id: uuid.UUID, muted: bool) -> None:
    await lock_active_user(db, user_id)
    if target_id == user_id or await db.get(User, target_id) is None:
        raise comment_error(422, "COMMENT_MUTE_INVALID", "이 계정은 숨길 수 없습니다.")
    if muted:
        await db.execute(insert(CommentMute).values(viewer_user_id=user_id, target_user_id=target_id).on_conflict_do_nothing())
    else:
        await db.execute(delete(CommentMute).where(CommentMute.viewer_user_id == user_id, CommentMute.target_user_id == target_id))
    await db.commit()


def notification_preferences(preference: CommentNotificationPreference | None) -> CommentNotificationPreferencesResponse:
    return CommentNotificationPreferencesResponse(
        new_comment=preference.new_comment if preference is not None else True,
        reply=preference.reply if preference is not None else True,
        mention=preference.mention if preference is not None else True,
    )


async def set_notification_preferences(
    db: AsyncSession, user_id: uuid.UUID, payload: CommentNotificationPreferencesUpdateRequest
) -> CommentNotificationPreferencesResponse:
    await lock_active_user(db, user_id)
    values = payload.model_dump()
    await db.execute(insert(CommentNotificationPreference).values(user_id=user_id, **values)
                     .on_conflict_do_update(index_elements=[CommentNotificationPreference.user_id], set_=values))
    await db.commit()
    return CommentNotificationPreferencesResponse(**values)


async def lock_withdrawal_contents(db: AsyncSession, user_id: uuid.UUID) -> None:
    """고유 회원정보 변경으로 FK 잠금이 강화되기 전에 관련 작품을 모두 잠근다."""
    authored = select(Comment.content_id).where(Comment.author_user_id == user_id)
    liked = select(Comment.content_id).join(CommentLike, CommentLike.comment_id == Comment.id).where(CommentLike.user_id == user_id)
    await db.scalars(select(Content).where(or_(
        Content.creator_user_id == user_id, Content.id.in_(authored), Content.id.in_(liked)
    )).order_by(Content.id).with_for_update())


async def erase_user_comments(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    authored = select(Comment.id).where(Comment.author_user_id == user_id)
    await db.execute(delete(CommentMention).where(or_(CommentMention.comment_id.in_(authored), CommentMention.user_id == user_id)))
    await db.execute(delete(CommentLike).where(or_(CommentLike.comment_id.in_(authored), CommentLike.user_id == user_id)))
    await db.execute(update(Content).where(Content.pinned_comment_id.in_(authored)).values(pinned_comment_id=None))
    await db.execute(update(Comment).where(Comment.author_user_id == user_id).values(
        body=None, sticker_id=None, deleted_at=func.coalesce(Comment.deleted_at, now)
    ))
    await db.execute(delete(CommentMute).where(CommentMute.viewer_user_id == user_id))
    await db.execute(delete(CommentNotificationPreference).where(CommentNotificationPreference.user_id == user_id))
