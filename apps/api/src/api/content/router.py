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
    CharacterDraftPayload,
    CharacterDraftResponse,
    CharacterSituationalImageItem,
    ContentAccessStatus,
    ContentCreateRequest,
    ContentCreateResponse,
    ContentDetailResponse,
    ContentListItem,
    ContentListResponse,
    ContentSummary,
    ContentVersionSummary,
    DraftSummary,
    ExampleDialogueItem,
    GenreResponse,
    ReportRequest,
    StartingSetupSummary,
    UpdateProfileRequest,
    UserProfileResponse,
    VisibilityFilter,
)
from api.core.s3 import generate_presigned_get_url
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Favorite,
    Genre,
    Like,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetStatus
from api.db.models.moderation import Report, ReportStatus
from api.db.models.story import StartingSetup, StoryVersionDetail
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id, get_current_user_id_optional

router = APIRouter(tags=["content"])

ContentListSort = Literal["latest", "popular", "genre"]

CONTENT_LIST_PAGE_SIZE = 20
FAVORITES_PAGE_SIZE = 20


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


@router.get("/me/favorites")
async def list_my_favorites(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ContentListResponse:
    """techspec-backend-content.md §1.1, US-039. Mixes character/story types (no `type`
    filter), so details are resolved per-type like `/me/drafts` rather than joined against
    a single `_detail_model`. Excludes moderation_status=deleted content (same precedent as
    `/users/{id}/contents`'s owner "all" filter) since that's the fully-hidden equivalent of
    non-existence; otherwise still shows the bookmark regardless of visibility/restriction."""
    query = (
        select(Favorite.created_at, Content, User.nickname)
        .join(Content, Content.id == Favorite.content_id)
        .join(User, User.id == Content.creator_user_id)
        .where(
            Favorite.user_id == user_id,
            Content.current_published_version_id.is_not(None),
            Content.moderation_status != ModerationStatus.DELETED,
        )
        .order_by(Favorite.created_at.desc(), Favorite.content_id.desc())
    )
    if cursor is not None:
        favorited_at, last_content_id = _decode_cursor(cursor)
        query = query.where(
            tuple_(Favorite.created_at, Favorite.content_id)
            < (datetime.fromisoformat(favorited_at), uuid.UUID(last_content_id))
        )

    rows = (await db.execute(query.limit(FAVORITES_PAGE_SIZE + 1))).all()
    has_more = len(rows) > FAVORITES_PAGE_SIZE
    page = rows[:FAVORITES_PAGE_SIZE]

    character_details = {
        detail.content_version_id: detail
        for detail in (
            await db.scalars(
                select(CharacterVersionDetail).where(
                    CharacterVersionDetail.content_version_id.in_(
                        content.current_published_version_id
                        for _, content, _ in page
                        if content.type == ContentType.CHARACTER
                    )
                )
            )
        ).all()
    }
    story_details = {
        detail.content_version_id: detail
        for detail in (
            await db.scalars(
                select(StoryVersionDetail).where(
                    StoryVersionDetail.content_version_id.in_(
                        content.current_published_version_id
                        for _, content, _ in page
                        if content.type == ContentType.STORY
                    )
                )
            )
        ).all()
    }

    items: list[ContentListItem] = []
    for _favorited_at, content, creator_nickname in page:
        detail: CharacterVersionDetail | StoryVersionDetail | None
        if content.type == ContentType.CHARACTER:
            detail = character_details.get(content.current_published_version_id)
        else:
            detail = story_details.get(content.current_published_version_id)
        if detail is None:
            continue
        items.append(
            ContentListItem(
                id=content.id,
                type=content.type,
                name=detail.name,
                thumbnail_url=await _resolve_asset_url(db, detail.thumbnail_asset_id),
                view_count=content.view_count,
                creator_user_id=content.creator_user_id,
                creator_nickname=creator_nickname,
            )
        )

    next_cursor: str | None = None
    if has_more and page:
        last_favorited_at, last_content, _ = page[-1]
        next_cursor = _encode_cursor([last_favorited_at.isoformat(), str(last_content.id)])

    return ContentListResponse(items=items, next_cursor=next_cursor)


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
        # Published content's thumbnail is guaranteed set by publish validation (US-083);
        # only drafts (character.py's CharacterVersionDetail docstring) can have it unset.
        assert detail.thumbnail_asset_id is not None
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


@router.post("/contents", status_code=status.HTTP_201_CREATED)
async def create_content_draft(
    payload: ContentCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ContentCreateResponse:
    """techspec-backend-content.md §1.2. `payload.type` is only ever `'character'` for
    now (US-084 widens the request schema and adds the `'story'` branch). The new
    character_version_details row is genuinely empty (character.py's docstring) — text
    columns get `""`, `thumbnail_asset_id` stays unset until an image is uploaded."""
    content = Content(
        type=ContentType.CHARACTER,
        creator_user_id=user_id,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()

    version = ContentVersion(content_id=content.id, detail_description="")
    db.add(version)
    await db.flush()

    db.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="",
            one_liner="",
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    )
    await db.commit()

    return ContentCreateResponse(content_id=content.id)


async def _get_owned_draft_version(
    db: AsyncSession, content_id: uuid.UUID, user_id: uuid.UUID
) -> ContentVersion:
    """404/403 gate shared by the draft read/write endpoints below (same content_version
    existence + creator-ownership check `register_situational_image`, US-071, established
    for content_version_id-scoped child resources)."""
    content = await db.get(Content, content_id)
    if content is None or content.type != ContentType.CHARACTER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    if content.creator_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the content owner")

    version = await db.scalar(
        select(ContentVersion).where(
            ContentVersion.content_id == content_id, ContentVersion.published_at.is_(None)
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return version


async def _character_draft_response(
    db: AsyncSession, content_id: uuid.UUID, version_id: uuid.UUID
) -> CharacterDraftResponse:
    detail = await db.get(CharacterVersionDetail, version_id)
    assert detail is not None

    images = (
        await db.scalars(
            select(SituationalImage)
            .where(SituationalImage.content_version_id == version_id)
            .order_by(SituationalImage.order)
        )
    ).all()

    return CharacterDraftResponse(
        id=content_id,
        name=detail.name,
        one_liner=detail.one_liner,
        thumbnail_asset_id=detail.thumbnail_asset_id,
        intro=detail.intro,
        example_dialogues=[
            ExampleDialogueItem.model_validate(item) for item in detail.example_dialogues
        ],
        character_prompt=detail.character_prompt,
        playguide=detail.playguide,
        situational_images=[
            CharacterSituationalImageItem(
                id=image.entity_id,
                image_asset_id=image.image_asset_id,
                trigger_condition=image.trigger_condition,
            )
            for image in images
        ],
    )


@router.get("/contents/{id}/draft")
async def get_content_draft(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CharacterDraftResponse:
    version = await _get_owned_draft_version(db, id, user_id)
    return await _character_draft_response(db, id, version.id)


@router.patch("/contents/{id}/draft")
async def update_content_draft(
    id: uuid.UUID,
    payload: CharacterDraftPayload,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CharacterDraftResponse:
    """techspec-backend-content.md §1.2, techspec-db-schema.md §1 원칙 1·2·4. Autosave: no
    business validation (US-083 publish is where that happens) — character_version_details
    is overwritten wholesale, situational_images is upserted by entity_id (array index ->
    order column), and entity_ids missing from the payload are deleted."""
    version = await _get_owned_draft_version(db, id, user_id)

    detail = await db.get(CharacterVersionDetail, version.id)
    assert detail is not None
    detail.name = payload.name
    detail.one_liner = payload.one_liner
    detail.thumbnail_asset_id = payload.thumbnail_asset_id
    detail.intro = payload.intro
    detail.example_dialogues = [item.model_dump(by_alias=True) for item in payload.example_dialogues]
    detail.character_prompt = payload.character_prompt
    detail.playguide = payload.playguide

    existing_images = {
        image.entity_id: image
        for image in (
            await db.scalars(
                select(SituationalImage).where(SituationalImage.content_version_id == version.id)
            )
        ).all()
    }
    incoming_entity_ids = {item.id for item in payload.situational_images}
    for entity_id, image in existing_images.items():
        if entity_id not in incoming_entity_ids:
            await db.delete(image)

    for order, item in enumerate(payload.situational_images):
        existing_image = existing_images.get(item.id)
        if existing_image is None:
            existing_image = SituationalImage(entity_id=item.id, content_version_id=version.id)
            db.add(existing_image)
        existing_image.trigger_condition = item.trigger_condition
        existing_image.order = order

    await db.commit()
    return await _character_draft_response(db, id, version.id)


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


def _resolve_access_status(
    visibility: ContentVisibility, moderation_status: ModerationStatus
) -> ContentAccessStatus:
    """Mirrors techspec-content-versioning.md §1's `resolveAccessStatus` — kept as the
    single source of truth for this rule on the BE side too."""
    if moderation_status == ModerationStatus.DELETED:
        return ContentAccessStatus(kind="deleted")
    if moderation_status == ModerationStatus.RESTRICTED:
        return ContentAccessStatus(kind="restricted")
    return ContentAccessStatus(kind="accessible", visibility=visibility)


@router.get("/contents/{id}")
async def get_content_detail(
    id: uuid.UUID,
    viewer_user_id: uuid.UUID | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db_session),
) -> ContentDetailResponse:
    """techspec-backend-content.md §1, techspec-content-versioning.md §1.

    Access control is query-response-based, not a 403/404 gate here: the full detail
    (including `accessStatus`/`isOwner`) is always returned for any existing, published
    content, and `techspec-content-detail.md` §2's `canViewDetailPage` on the FE decides
    whether to render it or an "unavailable" state instead.
    """
    peek = await db.get(Content, id)
    if peek is None or peek.current_published_version_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    detail_model = _detail_model(peek.type)
    row = (
        await db.execute(
            select(
                Content,
                ContentVersion,
                detail_model.name,
                detail_model.one_liner,
                detail_model.thumbnail_asset_id,
                Genre.name,
                User.nickname,
            )
            .join(ContentVersion, ContentVersion.id == Content.current_published_version_id)
            .join(detail_model, detail_model.content_version_id == ContentVersion.id)
            .join(Genre, Genre.id == Content.genre_id)
            .join(User, User.id == Content.creator_user_id)
            .where(Content.id == id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    content, version, name, one_liner, thumbnail_asset_id, genre_name, creator_nickname = row
    assert version.version_number is not None
    assert version.published_at is not None
    assert content.genre_id is not None

    starting_setups: list[StartingSetupSummary] | None = None
    if content.type == ContentType.STORY:
        setups = (
            await db.scalars(
                select(StartingSetup)
                .where(StartingSetup.content_version_id == version.id)
                .order_by(StartingSetup.order)
            )
        ).all()
        starting_setups = [
            StartingSetupSummary(id=setup.id, name=setup.name, prologue=setup.prologue)
            for setup in setups
        ]

    is_liked = False
    is_favorited = False
    if viewer_user_id is not None:
        is_liked = (
            await db.execute(
                select(Like).where(Like.user_id == viewer_user_id, Like.content_id == id)
            )
        ).scalar_one_or_none() is not None
        is_favorited = (
            await db.execute(
                select(Favorite).where(Favorite.user_id == viewer_user_id, Favorite.content_id == id)
            )
        ).scalar_one_or_none() is not None

    return ContentDetailResponse(
        id=content.id,
        type=content.type,
        name=name,
        thumbnail_url=await _resolve_asset_url(db, thumbnail_asset_id),
        creator_user_id=content.creator_user_id,
        creator_nickname=creator_nickname,
        genre_id=content.genre_id,
        genre_name=genre_name,
        hashtags=content.hashtags,
        one_liner=one_liner,
        detail_description=version.detail_description,
        chat_count=content.chat_count,
        like_count=content.like_count,
        is_liked=is_liked,
        is_favorited=is_favorited,
        starting_setups=starting_setups,
        version_number=version.version_number,
        updated_at=version.published_at,
        access_status=_resolve_access_status(content.visibility, content.moderation_status),
        is_owner=viewer_user_id is not None and viewer_user_id == content.creator_user_id,
    )


@router.get("/contents/{id}/versions")
async def list_content_versions(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> list[ContentVersionSummary]:
    """techspec-backend-content.md §1, US-017 — history only, no version-switch action."""
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    versions = (
        await db.scalars(
            select(ContentVersion)
            .where(ContentVersion.content_id == id, ContentVersion.published_at.is_not(None))
            .order_by(ContentVersion.version_number.desc())
        )
    ).all()

    summaries: list[ContentVersionSummary] = []
    for version in versions:
        assert version.version_number is not None
        assert version.published_at is not None
        summaries.append(
            ContentVersionSummary(version_number=version.version_number, published_at=version.published_at)
        )
    return summaries


@router.post("/contents/{id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def like_content(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """techspec-backend-content.md §1.1, US-039. Idempotent: a repeat like is a no-op
    rather than a second row/double increment (techspec-content-detail.md §4 does an FE
    optimistic update and never reads this response body, hence 204)."""
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    existing = (
        await db.execute(select(Like).where(Like.user_id == user_id, Like.content_id == id))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Like(user_id=user_id, content_id=id))
        content.like_count += 1
        await db.commit()


@router.delete("/contents/{id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_content(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    existing = (
        await db.execute(select(Like).where(Like.user_id == user_id, Like.content_id == id))
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        content.like_count -= 1
        await db.commit()


@router.post("/contents/{id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
async def favorite_content(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    existing = (
        await db.execute(select(Favorite).where(Favorite.user_id == user_id, Favorite.content_id == id))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Favorite(user_id=user_id, content_id=id))
        await db.commit()


@router.delete("/contents/{id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
async def unfavorite_content(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    existing = (
        await db.execute(select(Favorite).where(Favorite.user_id == user_id, Favorite.content_id == id))
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.commit()


@router.post("/contents/{id}/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_content(
    id: uuid.UUID,
    body: ReportRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """techspec-backend-content.md §1.1, US-040. Not idempotent (unlike like/favorite):
    each call inserts a new pending report row, matching techspec-db-schema.md §8's
    reports table having no unique constraint on (reporter_user_id, content_id)."""
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    db.add(
        Report(
            reporter_user_id=user_id,
            content_id=id,
            reason_category=body.reason_category,
            status=ReportStatus.PENDING,
        )
    )
    await db.commit()
