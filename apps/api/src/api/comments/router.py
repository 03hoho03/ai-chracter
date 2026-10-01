import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import comment_error, get_readable_content, require_creator
from api.comments.actions import (
    delete_comment, manage_content, notification_preferences, set_creator_hidden, set_like,
    set_mute, set_notification_preferences, set_pin, update_comment,
)
from api.comments.cursors import CommentCursor, decode_cursor, encode_cursor
from api.comments.read import (
    creator_hidden_management_clause, get_readable_comment, listed_root_clause,
    mention_candidates_query, normal_comment_clause,
    serialize_authors, serialize_comments, sticker_response,
)
from api.comments.schemas import (
    CommentCreateRequest, CommentHiddenListResponse, CommentListResponse, CommentLocationResponse,
    CommentMentionCandidatesResponse, CommentPageDirection, CommentRepliesResponse, CommentResponse,
    CommentSort, CommentStickerCatalogResponse,
    CommentLikeResponse, CommentMutesResponse, CommentNotificationPreferencesResponse,
    CommentNotificationPreferencesUpdateRequest, CommentPinRequest, CommentPinResponse,
    CommentSettingsResponse, CommentSettingsUpdateRequest, CommentUpdateRequest, CommentAuthorResponse,
)
from api.comments.write import create_comment
from api.db.models import (
    Comment, CommentLike, CommentMute, CommentNotificationPreference, CommentSticker, Content,
    ContentVisibility, User,
)
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.session.dependencies import get_current_user_id, get_current_user_id_optional

router = APIRouter(tags=["comments"])
me_router = APIRouter(tags=["comments"])
_PAGE_SIZE = 20


def _timestamp(cursor: CommentCursor) -> datetime:
    if cursor.created_at is None:
        raise comment_error(422, "COMMENT_CURSOR_INVALID", "댓글 페이지 정보가 올바르지 않습니다.")
    return cursor.created_at


@router.get("/comment-stickers")
async def get_stickers(db: AsyncSession = Depends(get_db_session)) -> CommentStickerCatalogResponse:
    stickers = list((await db.scalars(select(CommentSticker).order_by(CommentSticker.id))).all())
    return CommentStickerCatalogResponse(items=[sticker_response(sticker) for sticker in stickers])


@router.get("/contents/{content_id}/comments")
async def list_comments(
    content_id: uuid.UUID, sort: CommentSort = "latest", cursor: str | None = None,
    viewer_id: uuid.UUID | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db_session),
) -> CommentListResponse:
    content = await get_readable_content(db, content_id, viewer_id)
    pinned = await db.scalar(select(Comment).where(
        Comment.id == content.pinned_comment_id, Comment.content_id == content.id,
        Comment.root_comment_id.is_(None), normal_comment_clause(viewer_id),
    )) if content.pinned_comment_id is not None else None
    score = select(func.count(CommentLike.user_id)).where(CommentLike.comment_id == Comment.id).correlate(Comment).scalar_subquery()
    query = select(Comment, score.label("like_total")).where(Comment.content_id == content_id, listed_root_clause(viewer_id))
    if pinned is not None:
        query = query.where(Comment.id != pinned.id)
    if cursor is not None:
        decoded = decode_cursor(cursor, f"roots:{content_id}", sort=sort)
        query = query.where(
            tuple_(score, Comment.created_at, Comment.id) < (decoded.likes, _timestamp(decoded), decoded.id)
            if sort == "popular" else tuple_(Comment.created_at, Comment.id) < (_timestamp(decoded), decoded.id)
        )
    if sort == "popular":
        query = query.order_by(score.desc())
    rows = list((await db.execute(query.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(_PAGE_SIZE + 1))).all())
    page = rows[:_PAGE_SIZE]
    next_cursor = None
    if len(rows) > _PAGE_SIZE:
        last, likes = page[-1]
        next_cursor = encode_cursor(CommentCursor(scope=f"roots:{content_id}", sort=sort,
                                                 id=last.id, created_at=last.created_at, likes=likes))
    visible_count = await db.scalar(select(func.count()).select_from(Comment).where(
        Comment.content_id == content_id, normal_comment_clause(viewer_id)
    ))
    manages = viewer_id == content.creator_user_id
    hidden_count = await db.scalar(select(func.count()).select_from(Comment).where(
        Comment.content_id == content_id, creator_hidden_management_clause()
    )) if manages else None
    participates = viewer_id is not None and content.visibility != ContentVisibility.PRIVATE
    return CommentListResponse(
        content_id=content_id, content_type=content.type, creator_user_id=content.creator_user_id,
        comments_paused=not content.comments_enabled, can_read=True, can_participate=participates,
        can_create=participates and content.comments_enabled, can_manage=manages,
        visible_comment_count=visible_count or 0, hidden_comment_count=hidden_count,
        pinned_comment=(await serialize_comments(db, content, [pinned], viewer_id))[0] if pinned is not None else None,
        items=await serialize_comments(db, content, [comment for comment, _ in page], viewer_id),
        next_cursor=next_cursor,
    )


async def _listed_root(
    db: AsyncSession, content: Content, root_id: uuid.UUID, viewer_id: uuid.UUID | None
) -> Comment:
    root = await db.scalar(select(Comment).where(
        Comment.id == root_id, Comment.content_id == content.id, listed_root_clause(viewer_id)
    ))
    if root is None:
        raise comment_error(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    return root


async def _reply_response(
    db: AsyncSession, content: Content, root: Comment, rows: list[Comment], viewer_id: uuid.UUID | None
) -> CommentRepliesResponse:
    normal = normal_comment_clause(viewer_id)
    base = select(Comment.id).where(Comment.root_comment_id == root.id, normal)
    previous_cursor = next_cursor = None
    if rows:
        first, last = rows[0], rows[-1]
        if await db.scalar(base.where(tuple_(Comment.created_at, Comment.id) < (first.created_at, first.id)).exists().select()):
            previous_cursor = encode_cursor(CommentCursor(scope=f"replies:{root.id}", direction="before", id=first.id, created_at=first.created_at))
        if await db.scalar(base.where(tuple_(Comment.created_at, Comment.id) > (last.created_at, last.id)).exists().select()):
            next_cursor = encode_cursor(CommentCursor(scope=f"replies:{root.id}", id=last.id, created_at=last.created_at))
    count = await db.scalar(select(func.count()).select_from(Comment).where(Comment.root_comment_id == root.id, normal))
    return CommentRepliesResponse(root_comment_id=root.id, items=await serialize_comments(db, content, rows, viewer_id),
                                  previous_cursor=previous_cursor, next_cursor=next_cursor, visible_reply_count=count or 0)


@router.get("/contents/{content_id}/comments/{root_id}/replies")
async def list_replies(
    content_id: uuid.UUID, root_id: uuid.UUID, cursor: str | None = None,
    direction: CommentPageDirection = "after",
    viewer_id: uuid.UUID | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db_session),
) -> CommentRepliesResponse:
    content = await get_readable_content(db, content_id, viewer_id)
    root = await _listed_root(db, content, root_id, viewer_id)
    query = select(Comment).where(Comment.root_comment_id == root.id, normal_comment_clause(viewer_id))
    if cursor is not None:
        decoded = decode_cursor(cursor, f"replies:{root_id}", direction=direction)
        key = tuple_(Comment.created_at, Comment.id)
        query = query.where(key < (_timestamp(decoded), decoded.id) if direction == "before" else key > (_timestamp(decoded), decoded.id))
    elif direction == "before":
        raise comment_error(422, "COMMENT_CURSOR_INVALID", "이전 페이지 정보가 필요합니다.")
    query = query.order_by(Comment.created_at.desc(), Comment.id.desc()) if direction == "before" else query.order_by(Comment.created_at, Comment.id)
    rows = list((await db.scalars(query.limit(_PAGE_SIZE))).all())
    if direction == "before":
        rows.reverse()
    return await _reply_response(db, content, root, rows, viewer_id)


@router.get("/contents/{content_id}/comments/{comment_id}/location")
async def locate_comment(
    content_id: uuid.UUID, comment_id: uuid.UUID,
    viewer_id: uuid.UUID | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db_session),
) -> CommentLocationResponse:
    content = await get_readable_content(db, content_id, viewer_id)
    target = await get_readable_comment(db, content, comment_id, viewer_id)
    root = await _listed_root(db, content, target.root_comment_id or target.id, viewer_id)
    items = await serialize_comments(db, content, [root, target], viewer_id)
    replies = None
    if target.root_comment_id is not None:
        base = select(Comment).where(Comment.root_comment_id == root.id, normal_comment_clause(viewer_id))
        boundary = tuple_(Comment.created_at, Comment.id)
        rows = list((await db.scalars(base.where(boundary <= (target.created_at, target.id))
                                    .order_by(Comment.created_at.desc(), Comment.id.desc()).limit(_PAGE_SIZE))).all())
        rows.reverse()
        if len(rows) < _PAGE_SIZE:
            rows.extend((await db.scalars(base.where(boundary > (target.created_at, target.id))
                                         .order_by(Comment.created_at, Comment.id).limit(_PAGE_SIZE - len(rows)))).all())
        replies = await _reply_response(db, content, root, rows, viewer_id)
    return CommentLocationResponse(content_id=content_id, content_type=content.type, root=items[0], target=items[1], replies=replies)


@router.get("/contents/{content_id}/comments/hidden")
async def list_hidden_comments(
    content_id: uuid.UUID, cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db_session),
) -> CommentHiddenListResponse:
    content = await get_readable_content(db, content_id, user_id)
    require_creator(content, user_id)
    base = select(Comment).where(Comment.content_id == content_id, creator_hidden_management_clause())
    query = base
    if cursor is not None:
        decoded = decode_cursor(cursor, f"hidden:{content_id}")
        query = query.where(tuple_(Comment.created_at, Comment.id) < (_timestamp(decoded), decoded.id))
    rows = list((await db.scalars(query.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(_PAGE_SIZE + 1))).all())
    page = rows[:_PAGE_SIZE]
    next_cursor = encode_cursor(CommentCursor(scope=f"hidden:{content_id}", id=page[-1].id, created_at=page[-1].created_at)) if len(rows) > _PAGE_SIZE else None
    count = await db.scalar(select(func.count()).select_from(base.subquery()))
    return CommentHiddenListResponse(items=await serialize_comments(db, content, page, user_id), next_cursor=next_cursor, total_count=count or 0)


@router.get("/contents/{content_id}/comment-mention-candidates")
async def list_mention_candidates(
    content_id: uuid.UUID, q: str = "", cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db_session),
) -> CommentMentionCandidatesResponse:
    content = await get_readable_content(db, content_id, user_id)
    query = mention_candidates_query(content, user_id)
    if q:
        query = query.where(User.nickname.icontains(q, autoescape=True))
    scope = f"mentions:{content_id}:{q}"
    if cursor is not None:
        decoded = decode_cursor(cursor, scope, has_time=False)
        query = query.where(User.id > decoded.id)
    users = list((await db.scalars(query.order_by(User.id).limit(_PAGE_SIZE + 1))).all())
    page = users[:_PAGE_SIZE]
    authors = await serialize_authors(db, page, content.creator_user_id)
    next_cursor = encode_cursor(CommentCursor(scope=scope, id=page[-1].id)) if len(users) > _PAGE_SIZE else None
    return CommentMentionCandidatesResponse(items=[authors[user.id] for user in page], next_cursor=next_cursor)


@router.post("/contents/{content_id}/comments", status_code=201, dependencies=[Depends(require_legal_consent)])
async def post_comment(
    content_id: uuid.UUID, payload: CommentCreateRequest, response: Response,
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db_session),
) -> CommentResponse:
    content, comment, created = await create_comment(db, content_id, user_id, payload)
    response.status_code = 201 if created else 200
    return (await serialize_comments(db, content, [comment], user_id))[0]


@router.patch("/comments/{comment_id}", dependencies=[Depends(require_legal_consent)])
async def patch_comment(
    comment_id: uuid.UUID, payload: CommentUpdateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db_session),
) -> CommentResponse:
    content, comment = await update_comment(db, comment_id, user_id, payload)
    return (await serialize_comments(db, content, [comment], user_id))[0]


@router.delete("/comments/{comment_id}", status_code=204)
async def remove_comment(
    comment_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_comment(db, comment_id, user_id)


@router.put("/comments/{comment_id}/like")
async def like_comment(
    comment_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CommentLikeResponse:
    return await set_like(db, comment_id, user_id, True)


@router.delete("/comments/{comment_id}/like")
async def unlike_comment(
    comment_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CommentLikeResponse:
    return await set_like(db, comment_id, user_id, False)


@router.patch("/contents/{content_id}/comment-settings")
async def patch_comment_settings(
    content_id: uuid.UUID, payload: CommentSettingsUpdateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db_session),
) -> CommentSettingsResponse:
    content = await manage_content(db, content_id, user_id)
    content.comments_enabled = not payload.comments_paused
    await db.commit()
    return CommentSettingsResponse(content_id=content_id, comments_paused=payload.comments_paused)


@router.put("/contents/{content_id}/pinned-comment")
async def pin_comment(
    content_id: uuid.UUID, payload: CommentPinRequest,
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db_session),
) -> CommentPinResponse:
    content, comment = await set_pin(db, content_id, user_id, payload.comment_id)
    return CommentPinResponse(pinned_comment=(await serialize_comments(db, content, [comment], user_id))[0] if comment is not None else None)


@router.delete("/contents/{content_id}/pinned-comment")
async def unpin_comment(
    content_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CommentPinResponse:
    await set_pin(db, content_id, user_id, None)
    return CommentPinResponse(pinned_comment=None)


@router.put("/comments/{comment_id}/creator-hidden", status_code=204)
async def hide_creator_comment(
    comment_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await set_creator_hidden(db, comment_id, user_id, True)


@router.delete("/comments/{comment_id}/creator-hidden", status_code=204)
async def restore_creator_comment(
    comment_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await set_creator_hidden(db, comment_id, user_id, False)


@me_router.get("/me/comment-mutes")
async def list_comment_mutes(
    cursor: str | None = None, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CommentMutesResponse:
    scope = f"mutes:{user_id}"
    query = select(CommentMute, User).join(User, User.id == CommentMute.target_user_id).where(CommentMute.viewer_user_id == user_id)
    if cursor is not None:
        decoded = decode_cursor(cursor, scope)
        query = query.where(tuple_(CommentMute.created_at, CommentMute.target_user_id) < (_timestamp(decoded), decoded.id))
    rows = list((await db.execute(query.order_by(CommentMute.created_at.desc(), CommentMute.target_user_id.desc()).limit(_PAGE_SIZE + 1))).all())
    page = rows[:_PAGE_SIZE]
    authors = await serialize_authors(db, [user for _, user in page], None)
    items = [authors.get(user.id) or CommentAuthorResponse(id=user.id, nickname="탈퇴한 사용자", profile_image_url=None, is_creator=False) for _, user in page]
    last_mute = page[-1][0] if page else None
    next_cursor = encode_cursor(CommentCursor(scope=scope, id=last_mute.target_user_id, created_at=last_mute.created_at)) if len(rows) > _PAGE_SIZE and last_mute is not None else None
    return CommentMutesResponse(items=items, next_cursor=next_cursor)


@me_router.put("/me/comment-mutes/{target_id}", status_code=204)
async def mute_comment_user(
    target_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await set_mute(db, user_id, target_id, True)


@me_router.delete("/me/comment-mutes/{target_id}", status_code=204)
async def unmute_comment_user(
    target_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await set_mute(db, user_id, target_id, False)


@me_router.get("/me/comment-notification-preferences")
async def get_comment_notification_preferences(
    user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db_session),
) -> CommentNotificationPreferencesResponse:
    return notification_preferences(await db.get(CommentNotificationPreference, user_id))


@me_router.put("/me/comment-notification-preferences")
async def put_comment_notification_preferences(
    payload: CommentNotificationPreferencesUpdateRequest, user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CommentNotificationPreferencesResponse:
    return await set_notification_preferences(db, user_id, payload)
