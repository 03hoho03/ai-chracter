import base64
import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, any_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.content.schemas import (
    ContentListItem,
    ContentListResponse,
    ContentSummary,
    DraftSummary,
    GenreResponse,
    UpdateProfileRequest,
    UserProfileResponse,
    VisibilityFilter,
)
from api.core.s3 import generate_presigned_get_url
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetStatus
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id, get_current_user_id_optional

router = APIRouter(tags=["content"])

ContentListSort = Literal["latest", "popular", "genre"]

CONTENT_LIST_PAGE_SIZE = 20


@router.get("/me/drafts")
async def list_my_drafts(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[DraftSummary]:
    contents = (
        await db.scalars(select(Content).where(Content.creator_user_id == user_id))
    ).all()
    if not contents:
        return []

    # Newest-first, so the first version seen per content_id is its latest draft.
    draft_versions = (
        await db.scalars(
            select(ContentVersion)
            .where(
                ContentVersion.content_id.in_(content.id for content in contents),
                ContentVersion.published_at.is_(None),
            )
            .order_by(ContentVersion.created_at.desc())
        )
    ).all()
    latest_draft_by_content: dict[uuid.UUID, ContentVersion] = {}
    for version in draft_versions:
        latest_draft_by_content.setdefault(version.content_id, version)

    character_version_ids = [
        latest_draft_by_content[content.id].id
        for content in contents
        if content.type == ContentType.CHARACTER and content.id in latest_draft_by_content
    ]
    story_version_ids = [
        latest_draft_by_content[content.id].id
        for content in contents
        if content.type == ContentType.STORY and content.id in latest_draft_by_content
    ]

    character_details = {
        detail.content_version_id: detail
        for detail in (
            await db.scalars(
                select(CharacterVersionDetail).where(
                    CharacterVersionDetail.content_version_id.in_(character_version_ids)
                )
            )
        ).all()
    }
    story_details = {
        detail.content_version_id: detail
        for detail in (
            await db.scalars(
                select(StoryVersionDetail).where(
                    StoryVersionDetail.content_version_id.in_(story_version_ids)
                )
            )
        ).all()
    }

    drafts: list[DraftSummary] = []
    for content in contents:
        draft_version = latest_draft_by_content.get(content.id)
        if draft_version is None:
            continue

        detail: CharacterVersionDetail | StoryVersionDetail | None
        if content.type == ContentType.CHARACTER:
            detail = character_details.get(draft_version.id)
        else:
            detail = story_details.get(draft_version.id)
        if detail is None:
            continue

        drafts.append(
            DraftSummary(
                id=content.id,
                type=content.type,
                name=detail.name,
                thumbnail_asset_id=detail.thumbnail_asset_id,
                updated_at=content.updated_at,
            )
        )

    drafts.sort(key=lambda draft: draft.updated_at, reverse=True)
    return drafts


async def _resolve_asset_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """No presigned-GET/public-read path exists for assets yet, so a renderable
    URL is signed on demand from the stored object key each time it's needed
    (apps/web/CLAUDE.md US-034 gap, resolved for profile images in US-035 and
    reused here for content thumbnails)."""
    if asset_id is None:
        return None
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return None
    return await run_in_threadpool(generate_presigned_get_url, asset.storage_key)


@router.get("/users/{id}/profile")
async def get_user_profile(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> UserProfileResponse:
    user = await db.get(User, id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return UserProfileResponse(
        nickname=user.nickname,
        bio=user.bio,
        profile_image_asset_id=user.profile_image_asset_id,
        profile_image_url=await _resolve_asset_url(db, user.profile_image_asset_id),
    )


@router.patch("/me/profile")
async def update_my_profile(
    payload: UpdateProfileRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> UserProfileResponse:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if payload.profile_image_asset_id is not None:
        asset = await db.get(Asset, payload.profile_image_asset_id)
        if (
            asset is None
            or asset.owner_user_id != user_id
            or asset.status != AssetStatus.READY
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid profile image asset"
            )

    user.nickname = payload.nickname
    user.bio = payload.bio
    user.profile_image_asset_id = payload.profile_image_asset_id
    await db.commit()

    return UserProfileResponse(
        nickname=user.nickname,
        bio=user.bio,
        profile_image_asset_id=user.profile_image_asset_id,
        profile_image_url=await _resolve_asset_url(db, user.profile_image_asset_id),
    )


@router.get("/users/{id}/contents")
async def list_user_contents(
    id: uuid.UUID,
    type: ContentType,
    visibility: VisibilityFilter | None = None,
    viewer_user_id: uuid.UUID | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db_session),
) -> list[ContentSummary]:
    is_owner = viewer_user_id is not None and viewer_user_id == id

    query = select(Content).where(
        Content.creator_user_id == id,
        Content.type == type,
        Content.current_published_version_id.is_not(None),
    )
    if is_owner:
        effective_visibility = visibility or "all"
        if effective_visibility == "all":
            query = query.where(Content.moderation_status != ModerationStatus.DELETED)
        else:
            query = query.where(
                Content.visibility == ContentVisibility(effective_visibility),
                Content.moderation_status == ModerationStatus.NORMAL,
            )
    else:
        query = query.where(
            Content.visibility == ContentVisibility.PUBLIC,
            Content.moderation_status == ModerationStatus.NORMAL,
        )

    contents = (await db.scalars(query)).all()
    if not contents:
        return []

    published_version_ids = [
        content.current_published_version_id
        for content in contents
        if content.current_published_version_id is not None
    ]
    if type == ContentType.CHARACTER:
        details: dict[uuid.UUID, CharacterVersionDetail | StoryVersionDetail] = {
            detail.content_version_id: detail
            for detail in (
                await db.scalars(
                    select(CharacterVersionDetail).where(
                        CharacterVersionDetail.content_version_id.in_(published_version_ids)
                    )
                )
            ).all()
        }
    else:
        details = {
            detail.content_version_id: detail
            for detail in (
                await db.scalars(
                    select(StoryVersionDetail).where(
                        StoryVersionDetail.content_version_id.in_(published_version_ids)
                    )
                )
            ).all()
        }

    summaries: list[ContentSummary] = []
    for content in contents:
        version_id = content.current_published_version_id
        if version_id is None:
            continue
        detail = details.get(version_id)
        if detail is None:
            continue
        summaries.append(
            ContentSummary(
                id=content.id,
                type=content.type,
                name=detail.name,
                thumbnail_asset_id=detail.thumbnail_asset_id,
                thumbnail_url=await _resolve_asset_url(db, detail.thumbnail_asset_id),
                view_count=content.view_count,
                visibility=content.visibility,
                moderation_status=content.moderation_status,
            )
        )
    return summaries


@router.get("/genres")
async def list_genres(db: AsyncSession = Depends(get_db_session)) -> list[GenreResponse]:
    genres = (await db.scalars(select(Genre).order_by(Genre.sort_order))).all()
    return [GenreResponse(id=genre.id, name=genre.name, sort_order=genre.sort_order) for genre in genres]


def _detail_model(content_type: ContentType) -> type[CharacterVersionDetail] | type[StoryVersionDetail]:
    return CharacterVersionDetail if content_type == ContentType.CHARACTER else StoryVersionDetail


def _encode_cursor(parts: list[str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(parts).encode()).decode()


def _decode_cursor(cursor: str) -> list[str]:
    decoded: list[str] = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return decoded


@router.get("/contents")
async def list_contents(
    type: ContentType,
    sort: ContentListSort = "latest",
    genre: uuid.UUID | None = None,
    creator: uuid.UUID | None = None,
    hashtag: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> ContentListResponse:
    """techspec-backend-content.md §1.1, techspec-home-discovery.md §1~2.

    `sort=popular` prioritizes chat_count over like_count/view_count by ordering on
    all three columns lexicographically (chat_count first) instead of a single
    weighted score, so chat_count strictly dominates ties by construction — the
    actual weighted-score formula is still a PRD-level open question for later
    tuning. `sort=genre` orders by the genre master's sort_order.
    """
    detail_model = _detail_model(type)

    query = (
        select(Content, detail_model.name, detail_model.thumbnail_asset_id, User.nickname, Genre.sort_order)
        .join(detail_model, detail_model.content_version_id == Content.current_published_version_id)
        .join(User, User.id == Content.creator_user_id)
        .join(Genre, Genre.id == Content.genre_id)
        .where(
            Content.type == type,
            Content.current_published_version_id.is_not(None),
            Content.visibility == ContentVisibility.PUBLIC,
            Content.moderation_status == ModerationStatus.NORMAL,
        )
    )

    if genre is not None:
        query = query.where(Content.genre_id == genre)
    if creator is not None:
        query = query.where(Content.creator_user_id == creator)
    if hashtag is not None:
        query = query.where(any_(Content.hashtags) == hashtag)
    if q is not None:
        query = query.join(ContentVersion, ContentVersion.id == Content.current_published_version_id).where(
            or_(
                detail_model.name.ilike(f"%{q}%"),
                detail_model.one_liner.ilike(f"%{q}%"),
                ContentVersion.detail_description.ilike(f"%{q}%"),
            )
        )

    if sort == "popular":
        query = query.order_by(
            Content.chat_count.desc(),
            Content.like_count.desc(),
            Content.view_count.desc(),
            Content.id.desc(),
        )
        if cursor is not None:
            chat_count, like_count, view_count, last_id = _decode_cursor(cursor)
            query = query.where(
                tuple_(Content.chat_count, Content.like_count, Content.view_count, Content.id)
                < (int(chat_count), int(like_count), int(view_count), uuid.UUID(last_id))
            )
    elif sort == "genre":
        query = query.order_by(Genre.sort_order.asc(), Content.created_at.desc(), Content.id.desc())
        if cursor is not None:
            sort_order, created_at, last_id = _decode_cursor(cursor)
            query = query.where(
                or_(
                    Genre.sort_order > int(sort_order),
                    and_(
                        Genre.sort_order == int(sort_order),
                        tuple_(Content.created_at, Content.id)
                        < (datetime.fromisoformat(created_at), uuid.UUID(last_id)),
                    ),
                )
            )
    else:
        query = query.order_by(Content.created_at.desc(), Content.id.desc())
        if cursor is not None:
            created_at, last_id = _decode_cursor(cursor)
            query = query.where(
                tuple_(Content.created_at, Content.id)
                < (datetime.fromisoformat(created_at), uuid.UUID(last_id))
            )

    rows = (await db.execute(query.limit(CONTENT_LIST_PAGE_SIZE + 1))).all()
    has_more = len(rows) > CONTENT_LIST_PAGE_SIZE
    page = rows[:CONTENT_LIST_PAGE_SIZE]

    items = [
        ContentListItem(
            id=content.id,
            type=content.type,
            name=name,
            thumbnail_url=await _resolve_asset_url(db, thumbnail_asset_id),
            view_count=content.view_count,
            creator_user_id=content.creator_user_id,
            creator_nickname=nickname,
        )
        for content, name, thumbnail_asset_id, nickname, _genre_sort_order in page
    ]

    next_cursor: str | None = None
    if has_more and page:
        last_content, _, _, _, last_genre_sort_order = page[-1]
        if sort == "popular":
            next_cursor = _encode_cursor(
                [
                    str(last_content.chat_count),
                    str(last_content.like_count),
                    str(last_content.view_count),
                    str(last_content.id),
                ]
            )
        elif sort == "genre":
            next_cursor = _encode_cursor(
                [str(last_genre_sort_order), last_content.created_at.isoformat(), str(last_content.id)]
            )
        else:
            next_cursor = _encode_cursor([last_content.created_at.isoformat(), str(last_content.id)])

    return ContentListResponse(items=items, next_cursor=next_cursor)
