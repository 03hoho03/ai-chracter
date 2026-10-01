import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import HTTPException
import regex
from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql.elements import ColumnElement
from starlette.concurrency import run_in_threadpool

from api.comments.access import comment_error, require_readable_content
from api.comments.schemas import (
    AdminCommentCurrentResponse, CommentAuthorResponse, CommentDisplayState,
    CommentNotificationTargetResponse, CommentReplyTargetResponse, CommentResponse, CommentStickerResponse,
)
from api.core.config import settings
from api.core.s3 import build_thumbnail_key, generate_presigned_get_url
from api.db.models import (
    Asset, Comment, CommentLike, CommentMention, CommentMute, CommentSticker,
    Content, ContentVisibility, User,
)


def muted_user_ids(viewer_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return select(CommentMute.target_user_id).where(CommentMute.viewer_user_id == viewer_id)


def normal_comment_clause(
    viewer_id: uuid.UUID | None, row: type[Comment] | AliasedClass[Comment] = Comment
) -> ColumnElement[bool]:
    root = aliased(Comment)
    conditions = [
        row.deleted_at.is_(None), row.creator_hidden.is_(False), row.moderator_hidden.is_(False),
        exists(select(User.id).where(User.id == row.author_user_id, User.deleted_at.is_(None))),
        ~exists(select(root.id).where(root.id == row.root_comment_id,
                                      or_(root.creator_hidden.is_(True), root.moderator_hidden.is_(True)))),
    ]
    if viewer_id is not None:
        conditions.append(row.author_user_id.not_in(muted_user_ids(viewer_id)))
    return and_(*conditions)


def listed_root_clause(viewer_id: uuid.UUID | None) -> ColumnElement[bool]:
    reply = aliased(Comment)
    has_reply = exists(select(reply.id).where(reply.root_comment_id == Comment.id,
                                             normal_comment_clause(viewer_id, reply)))
    return and_(Comment.root_comment_id.is_(None), Comment.creator_hidden.is_(False),
                Comment.moderator_hidden.is_(False), or_(normal_comment_clause(viewer_id), has_reply))


def creator_hidden_management_clause() -> ColumnElement[bool]:
    return and_(Comment.creator_hidden.is_(True),
                or_(Comment.deleted_at.is_(None), Comment.root_comment_id.is_(None)))


def mention_candidates_query(content: Content, viewer_id: uuid.UUID) -> Select[tuple[User]]:
    participants = select(Comment.author_user_id).where(
        Comment.content_id == content.id, normal_comment_clause(viewer_id)
    )
    return select(User).where(
        User.deleted_at.is_(None), User.suspended_at.is_(None),
        User.id.not_in(muted_user_ids(viewer_id)),
        or_(User.id == content.creator_user_id, User.id.in_(participants)),
    )


async def get_readable_comment(
    db: AsyncSession, content: Content, comment_id: uuid.UUID, viewer_id: uuid.UUID | None
) -> Comment:
    require_readable_content(content, viewer_id)
    comment = await db.scalar(select(Comment).where(
        Comment.id == comment_id, Comment.content_id == content.id, normal_comment_clause(viewer_id)
    ))
    if comment is None:
        raise comment_error(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    return comment


def effective_spoiler(comment: Comment, related: Mapping[uuid.UUID, Comment]) -> bool:
    if comment.is_spoiler or comment.inherited_spoiler:
        return True
    for comment_id in (comment.root_comment_id, comment.reply_to_comment_id):
        parent = related.get(comment_id) if comment_id is not None else None
        if parent is not None and (parent.is_spoiler or parent.inherited_spoiler):
            return True
    return False


def sticker_response(sticker: CommentSticker) -> CommentStickerResponse:
    return CommentStickerResponse(
        id=sticker.id, name=sticker.name, alt=sticker.alt,
        image_url=f"{settings.frontend_base_url.rstrip('/')}/{sticker.image_path.lstrip('/')}",
        is_selectable=sticker.is_selectable,
    )


def comment_preview(body: str | None) -> str | None:
    return "".join(regex.findall(r"\X", body)[:120]) if body else None


async def serialize_authors(
    db: AsyncSession, users: list[User], creator_id: uuid.UUID | None
) -> dict[uuid.UUID, CommentAuthorResponse]:
    asset_ids = [u.profile_image_asset_id for u in users if u.profile_image_asset_id is not None and u.deleted_at is None]
    assets = {a.id: a for a in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()} if asset_ids else {}
    result: dict[uuid.UUID, CommentAuthorResponse] = {}
    for user in users:
        if user.deleted_at is not None:
            continue
        asset = assets.get(user.profile_image_asset_id) if user.profile_image_asset_id is not None else None
        url = await run_in_threadpool(generate_presigned_get_url, build_thumbnail_key(asset.storage_key)) if asset else None
        result[user.id] = CommentAuthorResponse(
            id=user.id, nickname=user.nickname or "사용자", profile_image_url=url, is_creator=user.id == creator_id,
        )
    return result


@dataclass
class _Projection:
    comments: dict[uuid.UUID, Comment]
    authors: dict[uuid.UUID, CommentAuthorResponse]
    mentions: dict[uuid.UUID, list[uuid.UUID]]
    stickers: dict[str, CommentStickerResponse]
    muted: set[uuid.UUID]
    likes: dict[uuid.UUID, int]
    liked: set[uuid.UUID]
    replies: dict[uuid.UUID, int]


async def _projection(
    db: AsyncSession, creator_id: uuid.UUID | None, comments: list[Comment], viewer_id: uuid.UUID | None
) -> _Projection:
    related_ids = {cid for c in comments for cid in (c.root_comment_id, c.reply_to_comment_id) if cid is not None}
    related = list((await db.scalars(select(Comment).where(Comment.id.in_(related_ids)))).all()) if related_ids else []
    all_comments = {c.id: c for c in [*related, *comments]}
    ids = list(all_comments)
    mentions: dict[uuid.UUID, list[uuid.UUID]] = {}
    for mention in (await db.scalars(select(CommentMention).where(CommentMention.comment_id.in_(ids)).order_by(CommentMention.user_id))).all():
        mentions.setdefault(mention.comment_id, []).append(mention.user_id)
    user_ids = {c.author_user_id for c in all_comments.values()} | {uid for users in mentions.values() for uid in users}
    users = list((await db.scalars(select(User).where(User.id.in_(user_ids)))).all())
    authors = await serialize_authors(db, users, creator_id)
    stickers = {s.id: sticker_response(s) for s in (await db.scalars(select(CommentSticker))).all()}
    muted = set((await db.scalars(muted_user_ids(viewer_id))).all()) if viewer_id is not None else set()
    like_rows = await db.execute(select(CommentLike.comment_id, func.count()).where(CommentLike.comment_id.in_(ids)).group_by(CommentLike.comment_id))
    likes = {cid: count for cid, count in like_rows}
    liked = set((await db.scalars(select(CommentLike.comment_id).where(CommentLike.comment_id.in_(ids), CommentLike.user_id == viewer_id))).all()) if viewer_id is not None else set()
    reply_rows = await db.execute(select(Comment.root_comment_id, func.count()).where(
        Comment.root_comment_id.in_(ids), normal_comment_clause(viewer_id)
    ).group_by(Comment.root_comment_id))
    replies = {cid: count for cid, count in reply_rows if cid is not None}
    return _Projection(all_comments, authors, mentions, stickers, muted, likes, liked, replies)


def _display_state(comment: Comment, projection: _Projection) -> CommentDisplayState:
    if comment.deleted_at is not None or comment.author_user_id not in projection.authors:
        return "deleted"
    root = projection.comments.get(comment.root_comment_id) if comment.root_comment_id is not None else None
    if comment.moderator_hidden or (root is not None and root.moderator_hidden):
        return "moderator-hidden"
    if comment.creator_hidden or (root is not None and root.creator_hidden):
        return "creator-hidden"
    if comment.author_user_id in projection.muted:
        return "muted"
    return "normal"


async def serialize_comments(
    db: AsyncSession, content: Content, comments: list[Comment], viewer_id: uuid.UUID | None
) -> list[CommentResponse]:
    projection = await _projection(db, content.creator_user_id, comments, viewer_id)
    authenticated = viewer_id is not None
    manages = authenticated and viewer_id == content.creator_user_id
    participates = authenticated and content.visibility != ContentVisibility.PRIVATE
    results: list[CommentResponse] = []
    for comment in comments:
        state = _display_state(comment, projection)
        normal = state == "normal"
        target = projection.comments.get(comment.reply_to_comment_id) if comment.reply_to_comment_id is not None else None
        reply_to = None
        if target is not None:
            target_state = _display_state(target, projection)
            spoiler = effective_spoiler(target, projection.comments)
            reply_to = CommentReplyTargetResponse(
                id=target.id, display_state=target_state,
                author=projection.authors.get(target.author_user_id) if normal and target_state == "normal" else None,
                body_preview=comment_preview(target.body) if normal and target_state == "normal" and not spoiler else None,
                effective_spoiler=spoiler,
            )
        results.append(CommentResponse(
            id=comment.id, content_id=comment.content_id, root_comment_id=comment.root_comment_id,
            reply_to_comment_id=comment.reply_to_comment_id, reply_to=reply_to,
            display_state=state, author=projection.authors.get(comment.author_user_id) if normal else None,
            body=comment.body if normal else None,
            sticker=projection.stickers.get(comment.sticker_id) if normal and comment.sticker_id is not None else None,
            mentions=[projection.authors[uid] for uid in projection.mentions.get(comment.id, [])
                      if uid in projection.authors and uid not in projection.muted] if normal else [],
            is_spoiler=comment.is_spoiler, inherited_spoiler=comment.inherited_spoiler,
            effective_spoiler=effective_spoiler(comment, projection.comments),
            created_at=comment.created_at, updated_at=comment.updated_at, is_edited=comment.updated_at is not None,
            like_count=projection.likes.get(comment.id, 0) if normal else 0,
            is_liked=comment.id in projection.liked if normal else False,
            reply_count=projection.replies.get(comment.id, 0) if comment.root_comment_id is None else 0,
            is_pinned=normal and content.pinned_comment_id == comment.id,
            creator_hidden=comment.creator_hidden, moderator_hidden=comment.moderator_hidden,
            can_reply=normal and participates and content.comments_enabled,
            can_edit=normal and viewer_id == comment.author_user_id,
            can_delete=authenticated and viewer_id == comment.author_user_id and comment.deleted_at is None,
            can_like=normal and participates,
            # Reporting one's own comment only adds noise to the moderation queue; delete is the author's tool.
            can_report=normal and authenticated and viewer_id != comment.author_user_id,
            can_pin=normal and manages and comment.root_comment_id is None,
            can_creator_hide=normal and manages,
            can_creator_restore=manages and comment.creator_hidden and (
                comment.deleted_at is None or comment.root_comment_id is None
            ),
        ))
    return results


async def serialize_admin_comments(
    db: AsyncSession, content: Content, comments: list[Comment]
) -> list[AdminCommentCurrentResponse]:
    projection = await _projection(db, content.creator_user_id, comments, None)
    results: list[AdminCommentCurrentResponse] = []
    for comment in comments:
        alive = comment.deleted_at is None and comment.author_user_id in projection.authors
        results.append(AdminCommentCurrentResponse(
            id=comment.id, content_id=comment.content_id, root_comment_id=comment.root_comment_id,
            reply_to_comment_id=comment.reply_to_comment_id,
            author=projection.authors.get(comment.author_user_id) if alive else None,
            body=comment.body if alive else None,
            sticker=projection.stickers.get(comment.sticker_id) if alive and comment.sticker_id is not None else None,
            mentions=[projection.authors[uid] for uid in projection.mentions.get(comment.id, []) if uid in projection.authors] if alive else [],
            is_spoiler=comment.is_spoiler, inherited_spoiler=comment.inherited_spoiler,
            effective_spoiler=effective_spoiler(comment, projection.comments),
            creator_hidden=comment.creator_hidden, moderator_hidden=comment.moderator_hidden,
            created_at=comment.created_at, updated_at=comment.updated_at, deleted_at=comment.deleted_at,
        ))
    return results


async def is_comment_actor_muted(
    db: AsyncSession, viewer_id: uuid.UUID, actor_id: uuid.UUID | None
) -> bool:
    return actor_id is not None and await db.get(CommentMute, (viewer_id, actor_id)) is not None


def _notification_target(
    content: Content, comment: Comment, projection: _Projection, viewer_id: uuid.UUID
) -> CommentNotificationTargetResponse:
    available = True
    try:
        require_readable_content(content, viewer_id)
    except HTTPException:
        available = False
    available = available and _display_state(comment, projection) == "normal"
    spoiler = effective_spoiler(comment, projection.comments)
    preview = available and not spoiler
    author = projection.authors.get(comment.author_user_id) if available else None
    sticker = projection.stickers.get(comment.sticker_id) if comment.sticker_id is not None else None
    return CommentNotificationTargetResponse(
        content_id=content.id, content_type=content.type, comment_id=comment.id,
        root_comment_id=comment.root_comment_id or comment.id,
        availability="available" if available else "unavailable", is_spoiler=spoiler,
        author=author.model_copy(update={"is_creator": author.id == content.creator_user_id}) if author is not None else None,
        body_preview=comment_preview(comment.body) if preview else None,
        sticker_name=sticker.name if preview and sticker is not None else None,
    )


async def notification_targets(
    db: AsyncSession, comments: list[Comment], viewer_id: uuid.UUID
) -> dict[uuid.UUID, CommentNotificationTargetResponse]:
    if not comments:
        return {}
    contents = {content.id: content for content in (await db.scalars(select(Content).where(
        Content.id.in_({comment.content_id for comment in comments})
    ))).all()}
    projection = await _projection(db, None, comments, viewer_id)
    return {comment.id: _notification_target(contents[comment.content_id], comment, projection, viewer_id)
            for comment in comments}


async def notification_target(
    db: AsyncSession, comment: Comment, viewer_id: uuid.UUID
) -> CommentNotificationTargetResponse:
    return (await notification_targets(db, [comment], viewer_id))[comment.id]
