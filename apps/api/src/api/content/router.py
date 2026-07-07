import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.content.schemas import (
    ContentSummary,
    DraftSummary,
    UpdateProfileRequest,
    UserProfileResponse,
    VisibilityFilter,
)
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentType, ContentVersion, ContentVisibility, ModerationStatus
from api.db.models.media import Asset, AssetStatus
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id, get_current_user_id_optional

router = APIRouter(tags=["content"])


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
                view_count=content.view_count,
                visibility=content.visibility,
                moderation_status=content.moderation_status,
            )
        )
    return summaries
