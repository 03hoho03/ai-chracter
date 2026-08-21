import base64
import json
import mimetypes
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import and_, any_, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.content.publish import (
    PublishFilterResult,
    build_character_publish_filter_prompt,
    build_story_publish_filter_prompt,
    validate_character_publish,
    validate_story_publish,
)
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
    ContentPublishResponse,
    ContentSummary,
    ContentVersionSummary,
    ContentVisibilityUpdateRequest,
    DraftSummary,
    EndingDraftItem,
    EndingRuleDraftItem,
    EndingRuleGroupDraftItem,
    EndingRuleListDraftItem,
    ExampleDialogueItem,
    GenreResponse,
    KeywordNoteDraftItem,
    ReportRequest,
    ShortcutDraftItem,
    StartingSetupDraftItem,
    StartingSetupSummary,
    StatDefDraftItem,
    StoryDraftPayload,
    StoryDraftResponse,
    UpdateProfileRequest,
    UserProfileResponse,
    VisibilityFilter,
)
from api.content.view_count import resolve_viewer_key, try_mark_viewed
from api.core.s3 import build_thumbnail_key, download_object, generate_presigned_get_url
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
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    KeywordNote,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.session import get_db_session, get_session_factory
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
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
    """한 번도 발행된 적 없는 콘텐츠의 초안만 돌려준다 (US-002).

    발행하면 다음 편집을 위한 초안 버전이 자동 복제되므로(`_publish_character_content` /
    `_publish_story_content` 끝부분) 발행작에도 항상 미발행 `content_version` 행이 딸려 있다.
    `published_at IS NULL`만으로 거르면 발행작이 전부 초안으로 섞여 나온다 — 그래서 콘텐츠
    단위로 `current_published_version_id IS NULL`을 함께 본다.
    """
    contents = (
        await db.scalars(
            select(Content).where(
                Content.creator_user_id == user_id,
                Content.current_published_version_id.is_(None),
            )
        )
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
                thumbnail_url=await _resolve_thumbnail_url(db, detail.thumbnail_asset_id),
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
                thumbnail_url=await _resolve_thumbnail_url(db, detail.thumbnail_asset_id),
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


async def _resolve_thumbnail_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """Signs the `_thumb.webp` variant instead of the original — list/card slots never
    need full resolution, and every READY image asset is guaranteed to have this
    variant (generated at creation since US-004~006, backfilled for older assets by
    `scripts/backfill_thumbnails.py`), so the key is derived without an existence check.
    Detail views (`get_content_detail`) keep `_resolve_asset_url`."""
    if asset_id is None:
        return None
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return None
    return await run_in_threadpool(
        generate_presigned_get_url, build_thumbnail_key(asset.storage_key)
    )


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
        profile_image_url=await _resolve_thumbnail_url(db, user.profile_image_asset_id),
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
        profile_image_url=await _resolve_thumbnail_url(db, user.profile_image_asset_id),
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

    query = (
        select(Content, ContentVersion)
        .join(ContentVersion, ContentVersion.id == Content.current_published_version_id)
        .where(Content.creator_user_id == id, Content.type == type)
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

    # Deterministic order: newest publish first, id as the tiebreaker.
    rows = (
        await db.execute(query.order_by(ContentVersion.published_at.desc(), Content.id.desc()))
    ).all()
    if not rows:
        return []

    published_version_ids = [version.id for _, version in rows]
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
    for content, version in rows:
        detail = details.get(version.id)
        if detail is None:
            continue
        # Published content's thumbnail is guaranteed set by publish validation (US-083);
        # only drafts (character.py's CharacterVersionDetail docstring) can have it unset.
        assert detail.thumbnail_asset_id is not None
        assert version.published_at is not None
        summaries.append(
            ContentSummary(
                id=content.id,
                type=content.type,
                name=detail.name,
                thumbnail_asset_id=detail.thumbnail_asset_id,
                thumbnail_url=await _resolve_thumbnail_url(db, detail.thumbnail_asset_id),
                view_count=content.view_count,
                chat_count=content.chat_count,
                like_count=content.like_count,
                visibility=content.visibility,
                moderation_status=content.moderation_status,
                updated_at=version.published_at,
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
    """techspec-backend-content.md §1.2. The new detail row is genuinely empty (see
    character.py/story.py docstrings) — text columns get `""`, `thumbnail_asset_id` stays
    unset until an image is uploaded. type='story' creates no child rows (starting_setups
    etc.) yet — those are added via `PATCH /contents/{id}/draft`."""
    content_type = ContentType.CHARACTER if payload.type == "character" else ContentType.STORY
    content = Content(
        type=content_type,
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

    if content_type == ContentType.CHARACTER:
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
    else:
        db.add(
            StoryVersionDetail(
                content_version_id=version.id,
                name="",
                one_liner="",
                prompt_template=StoryPromptTemplate.BASIC,
            )
        )
    await db.commit()

    return ContentCreateResponse(content_id=content.id)


async def _get_owned_draft_version(
    db: AsyncSession, content_id: uuid.UUID, user_id: uuid.UUID, allowed_types: tuple[ContentType, ...]
) -> tuple[Content, ContentVersion]:
    """404/403 gate shared by the draft read/write endpoints below (same content_version
    existence + creator-ownership check `register_situational_image`, US-071, established
    for content_version_id-scoped child resources)."""
    content = await db.get(Content, content_id)
    if content is None or content.type not in allowed_types:
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
    return content, version


async def _character_draft_response(
    db: AsyncSession, content: Content, version: ContentVersion
) -> CharacterDraftResponse:
    detail = await db.get(CharacterVersionDetail, version.id)
    assert detail is not None

    images = (
        await db.scalars(
            select(SituationalImage)
            .where(SituationalImage.content_version_id == version.id)
            .order_by(SituationalImage.order)
        )
    ).all()

    return CharacterDraftResponse(
        id=content.id,
        content_version_id=version.id,
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
        description=version.detail_description,
        genre_id=content.genre_id,
        target=content.target,
        hashtags=content.hashtags,
        visibility=content.visibility,
    )


async def _ending_rule_draft_items(db: AsyncSession, ending_id: uuid.UUID) -> list[EndingRuleListDraftItem]:
    """Mirrors `chat/router.py`'s `_ending_rule_items` — `ending_rules`(top-level) and
    `ending_rule_groups` share one `order` sequence (techspec-db-schema.md §5), reconstructed
    here as the same `kind`-discriminated tree so the draft response round-trips through
    `PATCH` unchanged. Not imported from `chat/schemas.py`/`chat/router.py` directly — same
    "duplicate the small helper, don't cross-import router files" convention as
    `_resolve_asset_url`."""
    top_rules = (await db.scalars(select(EndingRule).where(EndingRule.ending_id == ending_id))).all()
    groups = (await db.scalars(select(EndingRuleGroup).where(EndingRuleGroup.ending_id == ending_id))).all()

    items: list[tuple[int, EndingRuleListDraftItem]] = [
        (
            rule.order,
            EndingRuleDraftItem(
                id=rule.entity_id,
                stat_id=rule.stat_def_entity_id,
                operator=rule.operator,
                threshold=float(rule.threshold),
                next_op=rule.next_op,
            ),
        )
        for rule in top_rules
    ]
    for group in groups:
        nested = (
            await db.scalars(
                select(EndingRule).where(EndingRule.rule_group_id == group.id).order_by(EndingRule.order)
            )
        ).all()
        items.append(
            (
                group.order,
                EndingRuleGroupDraftItem(
                    id=group.entity_id,
                    next_op=group.next_op,
                    rules=[
                        EndingRuleDraftItem(
                            id=r.entity_id,
                            stat_id=r.stat_def_entity_id,
                            operator=r.operator,
                            threshold=float(r.threshold),
                            next_op=r.next_op,
                        )
                        for r in nested
                    ],
                ),
            )
        )
    items.sort(key=lambda pair: pair[0])
    return [item for _, item in items]


async def _story_draft_response(
    db: AsyncSession, content: Content, version: ContentVersion
) -> StoryDraftResponse:
    detail = await db.get(StoryVersionDetail, version.id)
    assert detail is not None

    setups = (
        await db.scalars(
            select(StartingSetup)
            .where(StartingSetup.content_version_id == version.id)
            .order_by(StartingSetup.order)
        )
    ).all()
    setup_entity_id_by_physical_id = {setup.id: setup.entity_id for setup in setups}

    starting_setups: list[StartingSetupDraftItem] = []
    for setup in setups:
        stat_defs = (
            await db.scalars(
                select(StatDef).where(StatDef.starting_setup_id == setup.id).order_by(StatDef.order)
            )
        ).all()
        endings = (
            await db.scalars(
                select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order)
            )
        ).all()
        starting_setups.append(
            StartingSetupDraftItem(
                id=setup.entity_id,
                name=setup.name,
                prologue=setup.prologue,
                opening_message=setup.opening_message,
                playguide=setup.playguide,
                suggested_replies=setup.suggested_replies or [],
                stat_defs=[
                    StatDefDraftItem(
                        id=stat_def.entity_id,
                        name=stat_def.name,
                        icon=stat_def.icon,
                        color=stat_def.color,
                        min_value=stat_def.min_value,
                        max_value=stat_def.max_value,
                        initial_value=stat_def.initial_value,
                        unit=stat_def.unit,
                        description=stat_def.description,
                        per_turn_delta=stat_def.per_turn_delta,
                    )
                    for stat_def in stat_defs
                ],
                endings=[
                    EndingDraftItem(
                        id=ending.entity_id,
                        name=ending.name,
                        turn_count_gate=ending.turn_count_gate,
                        judgment_prompt=ending.judgment_prompt,
                        epilogue=ending.epilogue,
                        hint=ending.hint,
                        stat_rules=await _ending_rule_draft_items(db, ending.id),
                    )
                    for ending in endings
                ],
            )
        )

    keyword_notes = (
        await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == version.id))
    ).all()
    shortcuts = (
        await db.scalars(select(Shortcut).where(Shortcut.content_version_id == version.id))
    ).all()

    return StoryDraftResponse(
        id=content.id,
        name=detail.name,
        one_liner=detail.one_liner,
        thumbnail_asset_id=detail.thumbnail_asset_id,
        prompt_template=detail.prompt_template,
        setting_text=detail.setting_text,
        development_example=detail.development_example,
        custom_prompt=detail.custom_prompt,
        starting_setups=starting_setups,
        keyword_notes=[
            KeywordNoteDraftItem(
                id=note.entity_id,
                info_text=note.info_text,
                trigger_keywords=note.trigger_keywords,
                starting_setup_id=(
                    setup_entity_id_by_physical_id.get(note.starting_setup_id)
                    if note.starting_setup_id is not None
                    else None
                ),
            )
            for note in keyword_notes
        ],
        shortcuts=[
            ShortcutDraftItem(id=s.entity_id, name=s.name, description=s.description, prompt=s.prompt)
            for s in shortcuts
        ],
        description=version.detail_description,
        genre_id=content.genre_id,
        target=content.target,
        hashtags=content.hashtags,
        visibility=content.visibility,
    )


@router.get("/contents/{id}/draft")
async def get_content_draft(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CharacterDraftResponse | StoryDraftResponse:
    content, version = await _get_owned_draft_version(
        db, id, user_id, (ContentType.CHARACTER, ContentType.STORY)
    )
    if content.type == ContentType.CHARACTER:
        return await _character_draft_response(db, content, version)
    return await _story_draft_response(db, content, version)


async def _update_character_draft(
    db: AsyncSession, content: Content, version: ContentVersion, payload: CharacterDraftPayload
) -> None:
    detail = await db.get(CharacterVersionDetail, version.id)
    assert detail is not None
    detail.name = payload.name
    detail.one_liner = payload.one_liner
    detail.thumbnail_asset_id = payload.thumbnail_asset_id
    detail.intro = payload.intro
    detail.example_dialogues = [item.model_dump(by_alias=True) for item in payload.example_dialogues]
    detail.character_prompt = payload.character_prompt
    detail.playguide = payload.playguide
    version.detail_description = payload.description
    content.genre_id = payload.genre_id
    content.target = payload.target
    content.hashtags = payload.hashtags
    content.visibility = payload.visibility

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


async def _delete_ending_subtree(db: AsyncSession, ending: Ending) -> None:
    """Deletes children before the parent, with explicit flushes between tiers — these
    FKs have no ON DELETE CASCADE and (per apps/api/CLAUDE.md's seeding-script gotcha)
    the ORM won't infer cross-table delete order on its own for plain FK columns with no
    `relationship()` declared, so relying on flush-time ordering alone is unsafe."""
    groups = (await db.scalars(select(EndingRuleGroup).where(EndingRuleGroup.ending_id == ending.id))).all()
    for group in groups:
        nested_rules = (
            await db.scalars(select(EndingRule).where(EndingRule.rule_group_id == group.id))
        ).all()
        for rule in nested_rules:
            await db.delete(rule)
        await db.flush()
        await db.delete(group)
    top_rules = (await db.scalars(select(EndingRule).where(EndingRule.ending_id == ending.id))).all()
    for rule in top_rules:
        await db.delete(rule)
    await db.flush()
    await db.delete(ending)


async def _delete_starting_setup_subtree(db: AsyncSession, setup: StartingSetup) -> None:
    stat_defs = (await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))).all()
    for stat_def in stat_defs:
        await db.delete(stat_def)
    endings = (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id))).all()
    for ending in endings:
        await _delete_ending_subtree(db, ending)
    await db.flush()
    await db.delete(setup)


async def _reconcile_ending_rules(
    db: AsyncSession, ending_id: uuid.UUID, items: list[EndingRuleListDraftItem]
) -> None:
    """entity_id 기준 업서트, `order`는 §1.5 규칙과 동일하게 `ending_rules`(top-level)와
    `ending_rule_groups`가 공유하는 하나의 시퀀스(= `items`의 배열 인덱스)."""
    existing_groups = {
        g.entity_id: g
        for g in (await db.scalars(select(EndingRuleGroup).where(EndingRuleGroup.ending_id == ending_id))).all()
    }
    existing_top_rules = {
        r.entity_id: r
        for r in (await db.scalars(select(EndingRule).where(EndingRule.ending_id == ending_id))).all()
    }
    incoming_group_ids = {item.id for item in items if isinstance(item, EndingRuleGroupDraftItem)}
    incoming_top_rule_ids = {item.id for item in items if isinstance(item, EndingRuleDraftItem)}

    for group_entity_id, existing_group in existing_groups.items():
        if group_entity_id not in incoming_group_ids:
            nested_rules_to_delete = (
                await db.scalars(select(EndingRule).where(EndingRule.rule_group_id == existing_group.id))
            ).all()
            for nested_rule_to_delete in nested_rules_to_delete:
                await db.delete(nested_rule_to_delete)
            await db.flush()
            await db.delete(existing_group)
    for top_rule_entity_id, existing_top_rule in existing_top_rules.items():
        if top_rule_entity_id not in incoming_top_rule_ids:
            await db.delete(existing_top_rule)

    for order, item in enumerate(items):
        if isinstance(item, EndingRuleDraftItem):
            top_rule = existing_top_rules.get(item.id)
            if top_rule is None:
                top_rule = EndingRule(entity_id=item.id, ending_id=ending_id)
                db.add(top_rule)
            top_rule.stat_def_entity_id = item.stat_id
            top_rule.operator = item.operator
            top_rule.threshold = Decimal(str(item.threshold))
            top_rule.next_op = item.next_op
            top_rule.order = order
            continue

        group = existing_groups.get(item.id)
        if group is None:
            group = EndingRuleGroup(entity_id=item.id, ending_id=ending_id)
            db.add(group)
        group.next_op = item.next_op
        group.order = order
        await db.flush()

        existing_nested_rules = {
            r.entity_id: r
            for r in (await db.scalars(select(EndingRule).where(EndingRule.rule_group_id == group.id))).all()
        }
        incoming_nested_ids = {rule_item.id for rule_item in item.rules}
        for nested_entity_id, existing_nested_rule in existing_nested_rules.items():
            if nested_entity_id not in incoming_nested_ids:
                await db.delete(existing_nested_rule)
        for nested_order, rule_item in enumerate(item.rules):
            nested_rule = existing_nested_rules.get(rule_item.id)
            if nested_rule is None:
                nested_rule = EndingRule(entity_id=rule_item.id, rule_group_id=group.id)
                db.add(nested_rule)
            nested_rule.stat_def_entity_id = rule_item.stat_id
            nested_rule.operator = rule_item.operator
            nested_rule.threshold = Decimal(str(rule_item.threshold))
            nested_rule.next_op = rule_item.next_op
            nested_rule.order = nested_order


async def _update_story_draft(
    db: AsyncSession, content: Content, version: ContentVersion, payload: StoryDraftPayload
) -> None:
    """techspec-backend-content.md §1.2, techspec-db-schema.md §1 원칙 1·2·4·§5. Autosave: no
    business validation — every child resource is upserted by entity_id (array index ->
    `order` column where applicable), removed entity_ids are deleted (children-first, since
    these FKs have no ON DELETE CASCADE), and `keywordNotes[].startingSetupId` (entity_id) is
    mapped to the physical `starting_setups.id` FK column."""
    detail = await db.get(StoryVersionDetail, version.id)
    assert detail is not None
    detail.name = payload.name
    detail.one_liner = payload.one_liner
    detail.thumbnail_asset_id = payload.thumbnail_asset_id
    detail.prompt_template = payload.prompt_template
    detail.setting_text = payload.setting_text
    detail.development_example = payload.development_example
    detail.custom_prompt = payload.custom_prompt
    version.detail_description = payload.description
    content.genre_id = payload.genre_id
    content.target = payload.target
    content.hashtags = payload.hashtags
    content.visibility = payload.visibility

    existing_setups = {
        s.entity_id: s
        for s in (
            await db.scalars(select(StartingSetup).where(StartingSetup.content_version_id == version.id))
        ).all()
    }
    incoming_setups = {item.id: item for item in payload.starting_setups}

    for setup_entity_id, existing_setup in existing_setups.items():
        if setup_entity_id not in incoming_setups:
            await _delete_starting_setup_subtree(db, existing_setup)

    for setup_item in payload.starting_setups:
        kept_setup = existing_setups.get(setup_item.id)
        if kept_setup is None:
            continue
        existing_stat_defs_for_prune = {
            sd.entity_id: sd
            for sd in (
                await db.scalars(select(StatDef).where(StatDef.starting_setup_id == kept_setup.id))
            ).all()
        }
        incoming_stat_def_ids = {sd.id for sd in setup_item.stat_defs}
        for stat_entity_id, stat_def_to_prune in existing_stat_defs_for_prune.items():
            if stat_entity_id not in incoming_stat_def_ids:
                await db.delete(stat_def_to_prune)

        existing_endings_for_prune = {
            e.entity_id: e
            for e in (
                await db.scalars(select(Ending).where(Ending.starting_setup_id == kept_setup.id))
            ).all()
        }
        incoming_ending_ids = {e.id for e in setup_item.endings}
        for ending_entity_id, ending_to_prune in existing_endings_for_prune.items():
            if ending_entity_id not in incoming_ending_ids:
                await _delete_ending_subtree(db, ending_to_prune)

    setup_physical_id: dict[uuid.UUID, uuid.UUID] = {}
    for order, setup_item in enumerate(payload.starting_setups):
        setup = existing_setups.get(setup_item.id)
        if setup is None:
            setup = StartingSetup(entity_id=setup_item.id, content_version_id=version.id)
            db.add(setup)
        setup.name = setup_item.name
        setup.prologue = setup_item.prologue
        setup.opening_message = setup_item.opening_message
        setup.playguide = setup_item.playguide
        setup.suggested_replies = setup_item.suggested_replies
        setup.order = order
        await db.flush()
        setup_physical_id[setup_item.id] = setup.id

        existing_stat_defs = {
            sd.entity_id: sd
            for sd in (await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))).all()
        }
        for stat_order, stat_item in enumerate(setup_item.stat_defs):
            stat_def = existing_stat_defs.get(stat_item.id)
            if stat_def is None:
                stat_def = StatDef(entity_id=stat_item.id, starting_setup_id=setup.id)
                db.add(stat_def)
            stat_def.name = stat_item.name
            stat_def.icon = stat_item.icon
            stat_def.color = stat_item.color
            stat_def.min_value = stat_item.min_value
            stat_def.max_value = stat_item.max_value
            stat_def.initial_value = stat_item.initial_value
            stat_def.unit = stat_item.unit
            stat_def.description = stat_item.description
            stat_def.per_turn_delta = stat_item.per_turn_delta
            stat_def.order = stat_order

        existing_endings = {
            e.entity_id: e
            for e in (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id))).all()
        }
        for ending_order, ending_item in enumerate(setup_item.endings):
            ending = existing_endings.get(ending_item.id)
            if ending is None:
                ending = Ending(entity_id=ending_item.id, starting_setup_id=setup.id)
                db.add(ending)
            ending.name = ending_item.name
            ending.turn_count_gate = ending_item.turn_count_gate
            ending.judgment_prompt = ending_item.judgment_prompt
            ending.epilogue = ending_item.epilogue
            ending.hint = ending_item.hint
            ending.order = ending_order
            await db.flush()
            await _reconcile_ending_rules(db, ending.id, ending_item.stat_rules)

    existing_notes = {
        n.entity_id: n
        for n in (
            await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == version.id))
        ).all()
    }
    incoming_note_ids = {note_item.id for note_item in payload.keyword_notes}
    for note_entity_id, note_to_prune in existing_notes.items():
        if note_entity_id not in incoming_note_ids:
            await db.delete(note_to_prune)
    for note_item in payload.keyword_notes:
        note = existing_notes.get(note_item.id)
        if note is None:
            note = KeywordNote(entity_id=note_item.id, content_version_id=version.id)
            db.add(note)
        note.info_text = note_item.info_text
        note.trigger_keywords = note_item.trigger_keywords
        note.starting_setup_id = (
            setup_physical_id.get(note_item.starting_setup_id)
            if note_item.starting_setup_id is not None
            else None
        )

    existing_shortcuts = {
        s.entity_id: s
        for s in (
            await db.scalars(select(Shortcut).where(Shortcut.content_version_id == version.id))
        ).all()
    }
    incoming_shortcut_ids = {shortcut_item.id for shortcut_item in payload.shortcuts}
    for shortcut_entity_id, shortcut_to_prune in existing_shortcuts.items():
        if shortcut_entity_id not in incoming_shortcut_ids:
            await db.delete(shortcut_to_prune)
    for shortcut_item in payload.shortcuts:
        shortcut = existing_shortcuts.get(shortcut_item.id)
        if shortcut is None:
            shortcut = Shortcut(entity_id=shortcut_item.id, content_version_id=version.id)
            db.add(shortcut)
        shortcut.name = shortcut_item.name
        shortcut.description = shortcut_item.description
        shortcut.prompt = shortcut_item.prompt


@router.patch("/contents/{id}/draft")
async def update_content_draft(
    id: uuid.UUID,
    payload: CharacterDraftPayload | StoryDraftPayload,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CharacterDraftResponse | StoryDraftResponse:
    """techspec-backend-content.md §1.2, techspec-db-schema.md §1 원칙 1·2·4. Autosave: no
    business validation (publish is where that happens) — the version-detail row is
    overwritten wholesale and every child resource is upserted by entity_id. `registration`-tab
    fields (description/genreId/target/hashtags/visibility) live on Content/ContentVersion
    directly rather than the per-type detail table, since they're shared across versions,
    not per-version snapshot data (techspec-db-schema.md §3)."""
    content, version = await _get_owned_draft_version(
        db, id, user_id, (ContentType.CHARACTER, ContentType.STORY)
    )

    if isinstance(payload, CharacterDraftPayload):
        if content.type != ContentType.CHARACTER:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Payload does not match content type"
            )
        await _update_character_draft(db, content, version, payload)
        await db.commit()
        return await _character_draft_response(db, content, version)

    if content.type != ContentType.STORY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Payload does not match content type"
        )
    await _update_story_draft(db, content, version, payload)
    await db.commit()
    return await _story_draft_response(db, content, version)


async def _load_publish_filter_images(
    db: AsyncSession, detail: CharacterVersionDetail, version_id: uuid.UUID
) -> list[tuple[bytes, str]]:
    """썸네일(대표이미지) + 이 버전에 등록된 상황별 이미지 원본을 전부 내려받아
    (바이트, MIME 타입) 쌍으로 반환한다 — LLMClient.generate_structured()의 멀티모달
    images 인자로 그대로 전달된다. 이미지 원본이 아직 없는 상황별 이미지 슬롯은
    건너뛴다(situationalImageSchema의 image가 nullable이라 발행 필수 항목이 아님)."""
    asset_ids: list[uuid.UUID] = []
    if detail.thumbnail_asset_id is not None:
        asset_ids.append(detail.thumbnail_asset_id)

    situational_images = (
        await db.scalars(
            select(SituationalImage).where(SituationalImage.content_version_id == version_id)
        )
    ).all()
    asset_ids.extend(
        image.image_asset_id for image in situational_images if image.image_asset_id is not None
    )

    images: list[tuple[bytes, str]] = []
    for asset_id in asset_ids:
        asset = await db.get(Asset, asset_id)
        assert asset is not None
        data = await run_in_threadpool(download_object, asset.storage_key)
        mime_type, _ = mimetypes.guess_type(asset.storage_key)
        images.append((data, mime_type or "application/octet-stream"))
    return images


@router.post("/contents/{id}/publish")
async def publish_content(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> ContentPublishResponse:
    """techspec-backend-content.md §1.2/§1.3, §2, techspec-db-schema.md §3 (US-083 character,
    US-085 story)."""
    content, version = await _get_owned_draft_version(
        db, id, user_id, (ContentType.CHARACTER, ContentType.STORY)
    )
    if content.type == ContentType.CHARACTER:
        return await _publish_character_content(db, content, version, llm_client)
    return await _publish_story_content(db, content, version, llm_client)


async def _publish_character_content(
    db: AsyncSession, content: Content, version: ContentVersion, llm_client: LLMClient
) -> ContentPublishResponse:
    detail = await db.get(CharacterVersionDetail, version.id)
    assert detail is not None

    missing_fields = validate_character_publish(content, version, detail)
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"missingFields": missing_fields}
        )

    filter_images = await _load_publish_filter_images(db, detail, version.id)
    filter_prompt = build_character_publish_filter_prompt(
        name=detail.name,
        one_liner=detail.one_liner,
        intro=detail.intro,
        example_dialogues=detail.example_dialogues,
        character_prompt=detail.character_prompt,
        detail_description=version.detail_description,
    )
    filter_result = await llm_client.generate_structured(
        filter_prompt, PublishFilterResult, images=filter_images
    )
    if not filter_result.passed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": filter_result.reason or "발행 심사를 통과하지 못했습니다."},
        )

    situational_images = (
        await db.scalars(
            select(SituationalImage).where(SituationalImage.content_version_id == version.id)
        )
    ).all()

    latest_version_number = await db.scalar(
        select(func.max(ContentVersion.version_number)).where(ContentVersion.content_id == content.id)
    )
    version.version_number = (latest_version_number or 0) + 1
    version.published_at = datetime.now(UTC)

    new_version = ContentVersion(content_id=content.id, detail_description=version.detail_description)
    db.add(new_version)
    await db.flush()

    db.add(
        CharacterVersionDetail(
            content_version_id=new_version.id,
            name=detail.name,
            one_liner=detail.one_liner,
            thumbnail_asset_id=detail.thumbnail_asset_id,
            intro=detail.intro,
            example_dialogues=detail.example_dialogues,
            character_prompt=detail.character_prompt,
            playguide=detail.playguide,
        )
    )
    for image in situational_images:
        db.add(
            SituationalImage(
                entity_id=image.entity_id,
                content_version_id=new_version.id,
                image_asset_id=image.image_asset_id,
                blurred_asset_id=image.blurred_asset_id,
                trigger_condition=image.trigger_condition,
                order=image.order,
            )
        )

    content.current_published_version_id = version.id
    await db.commit()

    assert version.version_number is not None
    return ContentPublishResponse(content_id=content.id, version_number=version.version_number)


async def _load_story_publish_filter_images(
    db: AsyncSession, detail: StoryVersionDetail
) -> list[tuple[bytes, str]]:
    """스토리는 상황별 이미지 개념이 없어(techspec-db-schema.md §5) 대표 이미지 하나만 첨부한다 —
    캐릭터의 `_load_publish_filter_images`와 같은 (바이트, MIME 타입) 쌍 형태로 반환한다."""
    if detail.thumbnail_asset_id is None:
        return []
    asset = await db.get(Asset, detail.thumbnail_asset_id)
    assert asset is not None
    data = await run_in_threadpool(download_object, asset.storage_key)
    mime_type, _ = mimetypes.guess_type(asset.storage_key)
    return [(data, mime_type or "application/octet-stream")]


async def _clone_ending_rules(db: AsyncSession, old_ending_id: uuid.UUID, new_ending_id: uuid.UUID) -> None:
    """Publish-time deep copy of one ending's rule tree onto its freshly-cloned sibling — same
    tree shape as `_reconcile_ending_rules` but duplicates rather than upserts (a republish clone
    always starts from an empty `new_ending_id`, techspec-db-schema.md §3)."""
    top_rules = (
        await db.scalars(select(EndingRule).where(EndingRule.ending_id == old_ending_id))
    ).all()
    for rule in top_rules:
        db.add(
            EndingRule(
                entity_id=rule.entity_id,
                ending_id=new_ending_id,
                stat_def_entity_id=rule.stat_def_entity_id,
                operator=rule.operator,
                threshold=rule.threshold,
                next_op=rule.next_op,
                order=rule.order,
            )
        )

    groups = (
        await db.scalars(select(EndingRuleGroup).where(EndingRuleGroup.ending_id == old_ending_id))
    ).all()
    for group in groups:
        new_group = EndingRuleGroup(
            entity_id=group.entity_id, ending_id=new_ending_id, next_op=group.next_op, order=group.order
        )
        db.add(new_group)
        await db.flush()

        nested_rules = (
            await db.scalars(select(EndingRule).where(EndingRule.rule_group_id == group.id))
        ).all()
        for nested_rule in nested_rules:
            db.add(
                EndingRule(
                    entity_id=nested_rule.entity_id,
                    rule_group_id=new_group.id,
                    stat_def_entity_id=nested_rule.stat_def_entity_id,
                    operator=nested_rule.operator,
                    threshold=nested_rule.threshold,
                    next_op=nested_rule.next_op,
                    order=nested_rule.order,
                )
            )


async def _publish_story_content(
    db: AsyncSession, content: Content, version: ContentVersion, llm_client: LLMClient
) -> ContentPublishResponse:
    detail = await db.get(StoryVersionDetail, version.id)
    assert detail is not None

    starting_setups = (
        await db.scalars(
            select(StartingSetup)
            .where(StartingSetup.content_version_id == version.id)
            .order_by(StartingSetup.order)
        )
    ).all()
    endings_by_setup_id: dict[uuid.UUID, Sequence[Ending]] = {}
    for setup in starting_setups:
        endings_by_setup_id[setup.id] = (
            await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id))
        ).all()

    missing_fields = validate_story_publish(content, version, detail, starting_setups, endings_by_setup_id)
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"missingFields": missing_fields}
        )

    filter_images = await _load_story_publish_filter_images(db, detail)
    filter_prompt = build_story_publish_filter_prompt(
        name=detail.name,
        one_liner=detail.one_liner,
        setting_text=detail.setting_text,
        development_example=detail.development_example,
        custom_prompt=detail.custom_prompt,
        detail_description=version.detail_description,
        starting_setups=starting_setups,
    )
    filter_result = await llm_client.generate_structured(
        filter_prompt, PublishFilterResult, images=filter_images
    )
    if not filter_result.passed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": filter_result.reason or "발행 심사를 통과하지 못했습니다."},
        )

    keyword_notes = (
        await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == version.id))
    ).all()
    shortcuts = (
        await db.scalars(select(Shortcut).where(Shortcut.content_version_id == version.id))
    ).all()

    latest_version_number = await db.scalar(
        select(func.max(ContentVersion.version_number)).where(ContentVersion.content_id == content.id)
    )
    version.version_number = (latest_version_number or 0) + 1
    version.published_at = datetime.now(UTC)

    new_version = ContentVersion(content_id=content.id, detail_description=version.detail_description)
    db.add(new_version)
    await db.flush()

    db.add(
        StoryVersionDetail(
            content_version_id=new_version.id,
            name=detail.name,
            one_liner=detail.one_liner,
            thumbnail_asset_id=detail.thumbnail_asset_id,
            prompt_template=detail.prompt_template,
            setting_text=detail.setting_text,
            development_example=detail.development_example,
            custom_prompt=detail.custom_prompt,
        )
    )

    old_setup_entity_id_by_physical_id = {setup.id: setup.entity_id for setup in starting_setups}
    new_setup_physical_id_by_entity_id: dict[uuid.UUID, uuid.UUID] = {}

    for setup in starting_setups:
        new_setup = StartingSetup(
            entity_id=setup.entity_id,
            content_version_id=new_version.id,
            name=setup.name,
            prologue=setup.prologue,
            opening_message=setup.opening_message,
            playguide=setup.playguide,
            suggested_replies=setup.suggested_replies,
            order=setup.order,
        )
        db.add(new_setup)
        await db.flush()
        new_setup_physical_id_by_entity_id[setup.entity_id] = new_setup.id

        stat_defs = (
            await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))
        ).all()
        for stat_def in stat_defs:
            db.add(
                StatDef(
                    entity_id=stat_def.entity_id,
                    starting_setup_id=new_setup.id,
                    name=stat_def.name,
                    icon=stat_def.icon,
                    color=stat_def.color,
                    min_value=stat_def.min_value,
                    max_value=stat_def.max_value,
                    initial_value=stat_def.initial_value,
                    unit=stat_def.unit,
                    description=stat_def.description,
                    per_turn_delta=stat_def.per_turn_delta,
                    order=stat_def.order,
                )
            )

        for ending in endings_by_setup_id[setup.id]:
            new_ending = Ending(
                entity_id=ending.entity_id,
                starting_setup_id=new_setup.id,
                name=ending.name,
                turn_count_gate=ending.turn_count_gate,
                judgment_prompt=ending.judgment_prompt,
                epilogue=ending.epilogue,
                hint=ending.hint,
                order=ending.order,
            )
            db.add(new_ending)
            await db.flush()
            await _clone_ending_rules(db, ending.id, new_ending.id)

    for note in keyword_notes:
        new_starting_setup_id = None
        if note.starting_setup_id is not None:
            old_entity_id = old_setup_entity_id_by_physical_id[note.starting_setup_id]
            new_starting_setup_id = new_setup_physical_id_by_entity_id[old_entity_id]
        db.add(
            KeywordNote(
                entity_id=note.entity_id,
                content_version_id=new_version.id,
                starting_setup_id=new_starting_setup_id,
                info_text=note.info_text,
                trigger_keywords=note.trigger_keywords,
            )
        )

    for shortcut in shortcuts:
        db.add(
            Shortcut(
                entity_id=shortcut.entity_id,
                content_version_id=new_version.id,
                name=shortcut.name,
                description=shortcut.description,
                prompt=shortcut.prompt,
            )
        )

    content.current_published_version_id = version.id
    await db.commit()

    assert version.version_number is not None
    return ContentPublishResponse(content_id=content.id, version_number=version.version_number)


@router.patch("/contents/{id}/visibility", status_code=status.HTTP_204_NO_CONTENT)
async def update_content_visibility(
    id: uuid.UUID,
    body: ContentVisibilityUpdateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """techspec-backend-content.md §1.2, US-086 (FR-67) — the only content state-change
    endpoint; there is no delete API. Writes `Content.visibility` directly regardless of
    draft/publish state, so the existing `Content.visibility == PUBLIC` filter already used
    by home/search/other-profile discovery queries excludes it immediately, matching
    techspec-content-versioning.md §1's `canDiscoverPublicly`."""
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    if content.creator_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the content owner")

    content.visibility = body.visibility
    await db.commit()


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
            thumbnail_url=await _resolve_thumbnail_url(db, thumbnail_asset_id),
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


async def _count_view(
    session_factory: async_sessionmaker[AsyncSession], content_id: uuid.UUID, viewer_key: str
) -> None:
    """Background task: 24h Redis dedup, then let the DB do the increment atomically.

    Opens its own session — the request-scoped `Depends(get_db_session)` is already
    closed by the time background tasks run (same pattern as api/images/router.py).
    The increment is a relative SQL UPDATE, not read-modify-write in Python, so
    concurrent views never lose counts (FR-8).
    """
    if not await try_mark_viewed(content_id, viewer_key):
        return
    async with session_factory() as session:
        await session.execute(
            update(Content).where(Content.id == content_id).values(view_count=Content.view_count + 1)
        )
        await session.commit()


@router.get("/contents/{id}")
async def get_content_detail(
    id: uuid.UUID,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    viewer_user_id: uuid.UUID | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
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

    access_status = _resolve_access_status(content.visibility, content.moderation_status)
    is_owner = viewer_user_id is not None and viewer_user_id == content.creator_user_id
    # Count only views the FE will actually render for someone else — exactly
    # `canViewDetailPage` (accessible AND public-or-owner) minus the owner.
    if (
        access_status.kind == "accessible"
        and content.visibility == ContentVisibility.PUBLIC
        and not is_owner
    ):
        # Viewer key resolution stays in the handler: baking the guest cookie
        # needs the response object, which background tasks don't have.
        viewer_key = resolve_viewer_key(request, response, viewer_user_id)
        background_tasks.add_task(_count_view, session_factory, id, viewer_key)

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
        access_status=access_status,
        is_owner=is_owner,
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
