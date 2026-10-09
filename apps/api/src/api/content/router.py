import asyncio
import base64
import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import any_, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.assets.blur import BlurredUpload, blurred_asset_row, upload_blurred_copy
from api.assets.image_processing import THUMBNAIL_CONTENT_TYPE, read_image_content_type
from api.chat.prompt_builder import load_active_prompt_set
from api.content.access import detail_model_for as _detail_model, is_open_to, select_publicly_listed
from api.content.media_book import MEDIA_BOOK_CELL_IMAGE_KINDS, normalize_texts, resolve_media_tag_images
from api.content.publish import (
    MediaBookFilterCell,
    PublishFilterResult,
    build_character_publish_filter_prompt,
    build_story_publish_filter_prompt,
    draft_dangling_situation_note_paths,
    draft_dangling_stat_rule_paths,
    setup_dangling_situation_note_paths,
    setup_dangling_priority_stat_paths,
    setup_dangling_stat_rule_paths,
    validate_character_publish,
    validate_story_publish,
)
from api.content.publish_filter_memo import PASSED_KEY_PREFIX, has_passed, remember_pass, screening_key
from api.content.schemas import (
    KEYWORD_NOTE_OPTION_FIELDS,
    RULE_LIST_ADAPTER,
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
    ContentSummaryListResponse,
    ContentVersionSummary,
    ContentVisibilityUpdateRequest,
    DevelopmentExampleItem,
    DraftListResponse,
    DraftSummary,
    EndingDraftItem,
    EndingRuleDraftItem,
    EndingRuleGroupDraftItem,
    EndingRuleListDraftItem,
    ExampleDialogueItem,
    GenreResponse,
    HomeCurationItem,
    HomeCurationResponse,
    KeywordNoteDraftItem,
    MediaBookAxisInput,
    MediaBookAxisItem,
    MediaBookCellDraftItem,
    MediaBookDraft,
    MediaBookPayload,
    MediaTagImage,
    ReportRequest,
    ShortcutDraftItem,
    SituationNoteDraftItem,
    StartingSetupDraftItem,
    StartingSetupSummary,
    StatDefDraftItem,
    StatRuleDraftItem,
    StoryDraftPayload,
    StoryDraftResponse,
    UpdateProfileRequest,
    UserProfileResponse,
    VisibilityFilter,
)
from api.content.view_count import resolve_viewer_key, try_mark_viewed
from api.core.config import settings
from api.core.constants import WITHDRAWN_USER_NICKNAME
from api.core.rate_limit_gate import enforce_publish_screen_limit
from api.core.s3 import build_display_key, build_thumbnail_key, download_object, generate_presigned_get_url
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Favorite,
    Genre,
    HomeCuration,
    Like,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetStatus
from api.db.models.moderation import Report, ReportStatus
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    KeywordNote,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    Shortcut,
    SituationNote,
    StartingSetup,
    StatDef,
    StatRule,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    structured_model,
)
from api.llm.dependencies import get_llm_client
from api.session.dependencies import get_current_user_id, get_current_user_id_optional

logger = logging.getLogger(__name__)

# 발행이 미디어 북 칸마다 하는 저장소 작업(심사에 실을 축소본 내려받기, 블러본 만들기)을 동시에 돌리는 칸 수.
# 공유 boto3 클라이언트의 기본 커넥션 풀(10개)보다 작게 둔다 — 넘기면 풀이 남는 연결을 버렸다가 다시 맺는다.
_MEDIA_BOOK_S3_CONCURRENCY = 8

router = APIRouter(tags=["content"])

ContentListSort = Literal["latest", "popular"]

CONTENT_LIST_PAGE_SIZE = 20
FAVORITES_PAGE_SIZE = 20
# `/my`·프로필의 작가 작품 그리드는 `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`라 24가 세 열 수
# 전부에 나누어떨어져 마지막 행이 꽉 찬다(20은 3열에서 빈칸 2개). 홈·즐겨찾기 목록은 그 그리드를
# 쓰지 않으므로 `CONTENT_LIST_PAGE_SIZE`(20)와 값을 공유하지 않고 별도 상수로 둔다.
CREATOR_CONTENT_PAGE_SIZE = 24


@router.get("/me/drafts")
async def list_my_drafts(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> DraftListResponse:
    """한 번도 발행된 적 없는 콘텐츠의 초안만 돌려준다.

    발행하면 다음 편집을 위한 초안 버전이 자동 복제되므로(`_write_character_publish` /
    `_write_story_publish` 끝부분) 발행작에도 항상 미발행 `content_version` 행이 딸려 있다.
    `published_at IS NULL`만으로 거르면 발행작이 전부 초안으로 섞여 나온다 — 그래서 콘텐츠
    단위로 `current_published_version_id IS NULL`을 함께 본다.

    커서 페이징의 정렬 키는 `Content.updated_at DESC, Content.id DESC`다. 초안에는
    `published_at`이 없어 `/users/{id}/contents`의 정렬 키를 쓸 수 없고, `ContentVersion`에는
    `updated_at`이 아예 없다 — 화면에 이미 노출 중인 `DraftSummary.updated_at`과 같은 컬럼을
    그대로 키로 쓴다. `Content.updated_at`은 `onupdate`가 없어 사실상 생성 시각으로 고정이라
    커서가 가리키는 행이 페이지 사이에 움직이지 않는다는 뜻이기도 하다.
    """
    content_query = (
        select(Content)
        .where(
            Content.creator_user_id == user_id,
            Content.current_published_version_id.is_(None),
        )
        .order_by(Content.updated_at.desc(), Content.id.desc())
    )
    if cursor is not None:
        updated_at, last_content_id = _decode_cursor(cursor)
        content_query = content_query.where(
            tuple_(Content.updated_at, Content.id)
            < (datetime.fromisoformat(updated_at), uuid.UUID(last_content_id))
        )

    rows = (await db.scalars(content_query.limit(CREATOR_CONTENT_PAGE_SIZE + 1))).all()
    has_more = len(rows) > CREATOR_CONTENT_PAGE_SIZE
    contents = rows[:CREATOR_CONTENT_PAGE_SIZE]
    if not contents:
        return DraftListResponse(items=[], next_cursor=None)

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

    # 커서는 항목이 아니라 **조회한 마지막 콘텐츠 행**에서 뽑는다 — 위 두 `continue`가 페이지 끝을
    # 잘라내도 다음 페이지가 그 행을 다시 읽지 않게 하기 위해서다(`/me/favorites`와 같은 규칙).
    next_cursor: str | None = None
    if has_more:
        last_content = contents[-1]
        next_cursor = _encode_cursor([last_content.updated_at.isoformat(), str(last_content.id)])

    return DraftListResponse(items=drafts, next_cursor=next_cursor)


@router.get("/me/favorites")
async def list_my_favorites(
    cursor: str | None = None,
    type: ContentType | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ContentListResponse:
    """Without `type`, mixes character/story
    types, so details are resolved per-type like `/me/drafts` rather than joined against
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
    if type is not None:
        query = query.where(Content.type == type)
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
                creator_nickname=creator_nickname
                if creator_nickname is not None
                else WITHDRAWN_USER_NICKNAME,
            )
        )

    next_cursor: str | None = None
    if has_more and page:
        last_favorited_at, last_content, _ = page[-1]
        next_cursor = _encode_cursor([last_favorited_at.isoformat(), str(last_content.id)])

    return ContentListResponse(items=items, next_cursor=next_cursor)


async def _resolve_display_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """상세 응답의 대표 이미지 주소 — 원본 대신 `_display.webp`(긴 변 1024 WebP) 변형을 서명한다. 이 주소를 받는
    자리(상세 히어로, 채팅방 헤더 아바타, 콘텐츠 링크 미리보기 이미지) 중 가장 흔한 데스크톱 상세 모달을 긴 변 1024 가
    2배 밀도로 덮는데, 시드 원본은 장당 1MB 안팎의 PNG 라 그대로 내보내면 같은 그림에 열 배 넘게 받는다. 이 변형도 썸네일처럼
    모든 READY 이미지 자산에 만들어지고(생성 시점, 그 전 자산은 `scripts/backfill_thumbnails.py` 로 소급) 키를 존재
    확인 없이 유도한다."""
    if asset_id is None:
        return None
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return None
    return await run_in_threadpool(generate_presigned_get_url, build_display_key(asset.storage_key))


async def _resolve_thumbnail_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """Signs the `_thumb.webp` variant instead of the original — list/card slots never
    need full resolution, and every READY image asset is guaranteed to have this
    variant (generated at creation, backfilled for older assets by
    `scripts/backfill_thumbnails.py`), so the key is derived without an existence check.
    The detail view draws the image larger and signs `_display.webp` instead (`_resolve_display_url`)."""
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

    # 위 조건문이 deleted_at is not None인 계정을 이미 배제했다 — nickname은 탈퇴(파기)
    # 시에만 None이 된다.
    assert user.nickname is not None
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
    cursor: str | None = None,
    viewer_user_id: uuid.UUID | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db_session),
) -> ContentSummaryListResponse:
    """커서 페이징. 정렬 키는 기존 `published_at DESC, id DESC` 그대로다 — 커서는 그
    두 값만 담으므로 `visibility` 등 WHERE 조건은 페이지마다 호출부가 다시 넘겨야 한다."""
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
    query = query.order_by(ContentVersion.published_at.desc(), Content.id.desc())
    if cursor is not None:
        published_at, last_content_id = _decode_cursor(cursor)
        query = query.where(
            tuple_(ContentVersion.published_at, Content.id)
            < (datetime.fromisoformat(published_at), uuid.UUID(last_content_id))
        )

    rows = (await db.execute(query.limit(CREATOR_CONTENT_PAGE_SIZE + 1))).all()
    has_more = len(rows) > CREATOR_CONTENT_PAGE_SIZE
    page = rows[:CREATOR_CONTENT_PAGE_SIZE]
    if not page:
        return ContentSummaryListResponse(items=[], next_cursor=None)

    published_version_ids = [version.id for _, version in page]
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
    for content, version in page:
        detail = details.get(version.id)
        if detail is None:
            continue
        # Published content's thumbnail is guaranteed set by publish validation;
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
                has_unpublished_changes=content.has_unpublished_changes,
                updated_at=version.published_at,
            )
        )

    # 커서는 항목이 아니라 조회한 마지막 **행**에서 뽑는다 — 위 `continue`가 페이지 끝을 잘라내도
    # 다음 페이지가 그 행을 다시 읽지 않게 하기 위해서다.
    next_cursor: str | None = None
    if has_more:
        last_content, last_version = page[-1]
        assert last_version.published_at is not None
        next_cursor = _encode_cursor(
            [last_version.published_at.isoformat(), str(last_content.id)]
        )

    return ContentSummaryListResponse(items=summaries, next_cursor=next_cursor)


@router.get("/genres")
async def list_genres(db: AsyncSession = Depends(get_db_session)) -> list[GenreResponse]:
    genres = (await db.scalars(select(Genre).order_by(Genre.sort_order))).all()
    return [GenreResponse(id=genre.id, name=genre.name, sort_order=genre.sort_order) for genre in genres]


@router.post(
    "/contents", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def create_content_draft(
    payload: ContentCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ContentCreateResponse:
    """The new detail row is genuinely empty (see
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
    existence + creator-ownership check `register_situational_image` established
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
        thumbnail_url=await _resolve_thumbnail_url(db, detail.thumbnail_asset_id),
        intro=detail.intro,
        example_dialogues=[
            ExampleDialogueItem.model_validate(item) for item in detail.example_dialogues
        ],
        character_prompt=detail.character_prompt,
        playguide=detail.playguide,
        default_user_name=detail.default_user_name,
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
    `ending_rule_groups` share one `order` sequence, reconstructed
    here as the same `kind`-discriminated tree so the draft response round-trips through
    `PATCH` unchanged. Not imported from `chat/schemas.py`/`chat/router.py` directly — same
    "duplicate the small helper, don't cross-import router files" convention as the
    `_resolve_asset_url` copies in the moderation/admin/inquiry routers."""
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


def _sign_thumbnail_urls(storage_keys: list[str]) -> list[str]:
    return [generate_presigned_get_url(build_thumbnail_key(key)) for key in storage_keys]


async def _media_book_draft(db: AsyncSession, version_id: uuid.UUID) -> MediaBookDraft:
    """칸은 인물 순서 → 장면 순서로 늘어놓는다(칸에는 자기 순서가 없다). 자동저장 응답마다 칸 50개가
    돌므로 자산은 한 번에 읽는다."""
    people = (
        await db.scalars(
            select(MediaBookPerson)
            .where(MediaBookPerson.content_version_id == version_id)
            .order_by(MediaBookPerson.order)
        )
    ).all()
    scenes = (
        await db.scalars(
            select(MediaBookScene)
            .where(MediaBookScene.content_version_id == version_id)
            .order_by(MediaBookScene.order)
        )
    ).all()
    cells = (await db.scalars(select(MediaBookCell).where(MediaBookCell.content_version_id == version_id))).all()

    person_rank = {person.entity_id: index for index, person in enumerate(people)}
    scene_rank = {scene.entity_id: index for index, scene in enumerate(scenes)}
    # 축이 없는 칸은 빼고 보낸다 — 칸 하나 때문에 초안 응답이 통째로 실패하면 빌더가 열리지 않아 화면에서
    # 고칠 길이 없다. 다음 미디어 북 저장이 페이로드에 없는 그 칸을 지운다.
    cells = sorted(
        (cell for cell in cells if cell.person_entity_id in person_rank and cell.scene_entity_id in scene_rank),
        key=lambda cell: (person_rank[cell.person_entity_id], scene_rank[cell.scene_entity_id]),
    )
    assets = (
        {
            asset.id: asset
            for asset in await db.scalars(
                select(Asset).where(Asset.id.in_({cell.image_asset_id for cell in cells}))
            )
        }
        if cells
        else {}
    )
    image_urls = await run_in_threadpool(
        _sign_thumbnail_urls, [assets[cell.image_asset_id].storage_key for cell in cells]
    )

    return MediaBookDraft(
        people=[MediaBookAxisItem(id=person.entity_id, name=person.name) for person in people],
        scenes=[MediaBookAxisItem(id=scene.entity_id, name=scene.name) for scene in scenes],
        cells=[
            MediaBookCellDraftItem(
                id=cell.entity_id,
                person_id=cell.person_entity_id,
                scene_id=cell.scene_entity_id,
                image_asset_id=cell.image_asset_id,
                situation_description=cell.situation_description,
                unlock_hint=cell.unlock_hint,
                exclude_from_chat=cell.exclude_from_chat,
                image_url=image_url,
                image_width=assets[cell.image_asset_id].width,
                image_height=assets[cell.image_asset_id].height,
            )
            for cell, image_url in zip(cells, image_urls, strict=True)
        ],
    )


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
        # 키워드북처럼 순서가 같은 행은 entity_id 로 줄 세운다(조건이 참인 노트가 이 순서로 실린다).
        situation_notes = (
            await db.scalars(
                select(SituationNote)
                .where(SituationNote.starting_setup_id == setup.id)
                .order_by(SituationNote.order, SituationNote.entity_id)
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
                        rules=[
                            StatRuleDraftItem(id=rule.entity_id, condition=rule.condition, delta=rule.delta)
                            for rule in (
                                await db.scalars(
                                    select(StatRule).where(StatRule.stat_def_id == stat_def.id).order_by(StatRule.order)
                                )
                            ).all()
                        ],
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
                        priority_stat_id=ending.priority_stat_def_entity_id,
                    )
                    for ending in endings
                ],
                situation_notes=[
                    SituationNoteDraftItem(
                        id=note.entity_id,
                        name=note.name,
                        info_text=note.info_text,
                        condition_rules=RULE_LIST_ADAPTER.validate_python(note.condition_rules),
                    )
                    for note in situation_notes
                ],
            )
        )

    # 노트 순서가 곧 우선순위(대화 한 턴에 위에서부터 실린다)라 화면에 보이는 순서가 저장된 순서와 같아야 한다.
    keyword_notes = (
        await db.scalars(
            select(KeywordNote)
            .where(KeywordNote.content_version_id == version.id)
            .order_by(KeywordNote.order, KeywordNote.entity_id)
        )
    ).all()
    shortcuts = (
        await db.scalars(select(Shortcut).where(Shortcut.content_version_id == version.id))
    ).all()

    return StoryDraftResponse(
        media_book=await _media_book_draft(db, version.id),
        id=content.id,
        name=detail.name,
        one_liner=detail.one_liner,
        thumbnail_asset_id=detail.thumbnail_asset_id,
        thumbnail_url=await _resolve_thumbnail_url(db, detail.thumbnail_asset_id),
        prompt_template=detail.prompt_template,
        setting_text=detail.setting_text,
        development_example=detail.development_example,
        custom_prompt=detail.custom_prompt,
        development_examples=[
            DevelopmentExampleItem.model_validate(item) for item in detail.development_examples
        ],
        user_goal=detail.user_goal,
        rules=detail.rules,
        default_user_name=detail.default_user_name,
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
                name=note.name,
                exclude_keywords=note.exclude_keywords,
                sticky_turns=note.sticky_turns,
                always_on=note.always_on,
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


async def _check_new_draft_thumbnail(
    db: AsyncSession, content: Content, current_asset_id: uuid.UUID | None, new_asset_id: uuid.UUID | None
) -> None:
    """새로 거는 대표 이미지는 작가 본인의 업로드 완료 원본이나 생성 이미지여야 한다(미디어 북 칸과 같은 조건 —
    빌더가 대표 이미지로 거는 것은 업로드한 원본과 갤러리의 생성 이미지 둘뿐이다). 남의 자산을 걸면 그 사람이
    자기 이미지를 못 지우고, 업로드가 끝나지 않은 자산은 최종 키에 객체가 없다.

    값이 그대로면 보지 않는다. 시드 작품의 대표 이미지는 시드 스크립트가 THUMBNAIL 종류로 직접 넣은 것이라 이
    조건을 못 넘는데, 빌더 자동저장은 그 값을 매번 다시 보낸다. 발행본으로 되돌리기도 서버가 값을 직접 옮기므로
    그 뒤의 자동저장은 같은 값을 다시 보낼 뿐이다.

    자동저장 라우트에서만 부른다. 시드 스크립트는 `_update_character_draft`·`_update_story_draft` 를 직접 불러 시드
    작가의 THUMBNAIL 자산을 처음 거는데, 그 경로는 이 검사 대상이 아니다."""
    if new_asset_id is None or new_asset_id == current_asset_id:
        return
    usable_asset_id = await db.scalar(
        select(Asset.id).where(
            Asset.id == new_asset_id,
            Asset.owner_user_id == content.creator_user_id,
            Asset.status == AssetStatus.READY,
            Asset.kind.in_(MEDIA_BOOK_CELL_IMAGE_KINDS),
        )
    )
    if usable_asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Thumbnail must be the creator's own ready upload or generated image",
        )


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
    # 안 보냈으면 저장된 값을 둔다 — 이 칸을 모르는 옛 화면의 자동저장이 작가가 넣은 이름을 지우지 않게.
    if "default_user_name" in payload.model_fields_set:
        detail.default_user_name = payload.default_user_name
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
            # 위에서 읽은 뒤 이미지 등록(`register_situational_image`)이 같은 항목을 먼저 만들었을 수
            # 있다. 그때는 그 행의 글·순서만 갱신하고 이미지 칸은 등록 쪽 값을 그대로 둔다.
            await db.execute(
                insert(SituationalImage)
                .values(
                    entity_id=item.id,
                    content_version_id=version.id,
                    trigger_condition=item.trigger_condition,
                    order=order,
                )
                .on_conflict_do_update(
                    constraint="ux_situational_images_version_entity",
                    set_={"trigger_condition": item.trigger_condition, "order": order},
                )
            )
            continue
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


async def _delete_stat_def(db: AsyncSession, stat_def: StatDef) -> None:
    """규칙을 먼저 지우고 스탯을 지운다. 규칙 FK 의 `ON DELETE CASCADE` 는 이 테이블을 모르는 옛 이미지를 위한 것이라
    (`StatRule` docstring) 새 코드는 형제 테이블처럼 자식을 직접 지운다."""
    for rule in (await db.scalars(select(StatRule).where(StatRule.stat_def_id == stat_def.id))).all():
        await db.delete(rule)
    await db.flush()
    await db.delete(stat_def)


async def _delete_starting_setup_subtree(db: AsyncSession, setup: StartingSetup) -> None:
    stat_defs = (await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))).all()
    for stat_def in stat_defs:
        await _delete_stat_def(db, stat_def)
    endings = (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id))).all()
    for ending in endings:
        await _delete_ending_subtree(db, ending)
    # 상황 노트는 시작설정을 물리 FK 로 가리키고 시작설정과 함께 사라진다. 저장 중 시작설정 제거·초안 삭제·편집 취소가
    # 모두 이 함수를 지나므로 여기 한 곳에서 지운다.
    situation_notes = (
        await db.scalars(select(SituationNote).where(SituationNote.starting_setup_id == setup.id))
    ).all()
    for situation_note in situation_notes:
        await db.delete(situation_note)
    await db.flush()
    await db.delete(setup)


async def _reconcile_ending_rules(
    db: AsyncSession, ending_id: uuid.UUID, items: list[EndingRuleListDraftItem]
) -> None:
    """entity_id 기준 업서트, `order`는 `ending_rules`(top-level)와
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


async def _reconcile_stat_rules(db: AsyncSession, stat_def_id: uuid.UUID, items: list[StatRuleDraftItem]) -> None:
    """entity_id 기준 업서트, `order` 는 `items` 의 배열 인덱스. 빠진 규칙은 지운다."""
    existing_rules = {
        rule.entity_id: rule
        for rule in (await db.scalars(select(StatRule).where(StatRule.stat_def_id == stat_def_id))).all()
    }
    incoming_rule_ids = {item.id for item in items}
    for rule_entity_id, existing_rule in existing_rules.items():
        if rule_entity_id not in incoming_rule_ids:
            await db.delete(existing_rule)
    for order, item in enumerate(items):
        rule = existing_rules.get(item.id)
        if rule is None:
            rule = StatRule(entity_id=item.id, stat_def_id=stat_def_id)
            db.add(rule)
        rule.condition = item.condition
        rule.delta = item.delta
        rule.order = order


# 두 탭이 서로 다른 새 칸으로 같은 빈 자리를 채운 경우의 409 code. 화면은 새로고침을 안내한다.
MEDIA_BOOK_CELL_POSITION_TAKEN = "MEDIA_BOOK_CELL_POSITION_TAKEN"


async def _upsert_media_book_axis(
    db: AsyncSession,
    model: type[MediaBookPerson] | type[MediaBookScene],
    constraint: str,
    version_id: uuid.UUID,
    existing: dict[uuid.UUID, MediaBookPerson] | dict[uuid.UUID, MediaBookScene],
    items: list[MediaBookAxisInput],
) -> None:
    new_rows: list[dict[str, object]] = []
    for order, item in enumerate(items):
        row = existing.get(item.id)
        if row is None:
            new_rows.append(
                {"id": uuid.uuid4(), "entity_id": item.id, "content_version_id": version_id, "name": item.name, "order": order}
            )
            continue
        row.name = item.name
        row.order = order
    if not new_rows:
        return
    # 위에서 읽은 뒤 겹친 다른 저장이 같은 새 축을 먼저 넣었을 수 있다 — 그 행을 이 저장 값으로 고친다.
    statement = insert(model).values(new_rows)
    await db.execute(
        statement.on_conflict_do_update(
            constraint=constraint, set_={"name": statement.excluded.name, "order": statement.excluded.order}
        )
    )


async def _update_media_book(
    db: AsyncSession, content: Content, version: ContentVersion, media_book: MediaBookPayload
) -> None:
    """칸·축을 페이로드에 맞춘다. 쓰기 순서가 정해져 있다 — 빠진 행 삭제(칸 → 축) → 기존 행 갱신 →
    새 행 insert. 칸 자리 UNIQUE 는 즉시 검사라 "칸 삭제 + 같은 자리 새 칸"을 한 저장에 담으면 insert 가
    먼저 나가는 순간 걸린다. 그림을 바꾸는 덮어쓰기는 같은 칸 entity_id 를 유지한다 — 노출 기록과 첫
    메시지에 저장된 칸 태그가 entity_id 로 칸을 가리킨다."""
    # 같은 초안의 미디어 북 저장을 줄 세운다. 잠금 없이 두 탭의 저장이 겹치면, 한쪽이 지운 축을 다른
    # 쪽은 아직 보이는 채 그 축에 새 칸을 넣어 축 없는 칸이 커밋된다. 잠금을 얻은 뒤의 읽기는 앞 저장의
    # 커밋을 본다. 키를 바꾸지 않는 잠금이라 이 버전을 가리키는 행의 insert 는 막지 않는다.
    await db.execute(
        select(ContentVersion.id).where(ContentVersion.id == version.id).with_for_update(key_share=True)
    )
    existing_people = {
        row.entity_id: row
        for row in (
            await db.scalars(select(MediaBookPerson).where(MediaBookPerson.content_version_id == version.id))
        ).all()
    }
    existing_scenes = {
        row.entity_id: row
        for row in (
            await db.scalars(select(MediaBookScene).where(MediaBookScene.content_version_id == version.id))
        ).all()
    }
    existing_cells = {
        row.entity_id: row
        for row in (
            await db.scalars(select(MediaBookCell).where(MediaBookCell.content_version_id == version.id))
        ).all()
    }

    # 빌더에는 칸을 옮기는 동작이 없다. 기존 칸 둘의 자리를 맞바꾸면 행을 하나씩 고치는 도중 같은
    # 자리가 둘이 되어 자리 UNIQUE 가 500 을 내므로, 기존 칸의 자리는 바꾸지 못하게 한다.
    for cell in media_book.cells:
        existing_cell = existing_cells.get(cell.id)
        if existing_cell is not None and (existing_cell.person_entity_id, existing_cell.scene_entity_id) != (
            cell.person_id,
            cell.scene_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="An existing media book cell cannot move to another position",
            )

    # 저장 요청자는 위 게이트가 작성자로 확인했다. 남의 자산을 걸면 그 사람이 자기 이미지를 못 지운다.
    image_asset_ids = {cell.image_asset_id for cell in media_book.cells}
    if image_asset_ids:
        usable_asset_ids = set(
            await db.scalars(
                select(Asset.id).where(
                    Asset.id.in_(image_asset_ids),
                    Asset.owner_user_id == content.creator_user_id,
                    Asset.status == AssetStatus.READY,
                    Asset.kind.in_(MEDIA_BOOK_CELL_IMAGE_KINDS),
                )
            )
        )
        if usable_asset_ids != image_asset_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Media book images must be the creator's own ready uploads or generated images",
            )

    incoming_cell_ids = {cell.id for cell in media_book.cells}
    for entity_id, existing_cell in existing_cells.items():
        if entity_id not in incoming_cell_ids:
            await db.delete(existing_cell)
    await db.flush()
    for existing_axis, incoming_axis in (
        (existing_people, media_book.people),
        (existing_scenes, media_book.scenes),
    ):
        incoming_axis_ids = {item.id for item in incoming_axis}
        for entity_id, existing_row in existing_axis.items():
            if entity_id not in incoming_axis_ids:
                await db.delete(existing_row)
    await db.flush()

    await _upsert_media_book_axis(
        db, MediaBookPerson, "ux_media_book_people_version_entity", version.id, existing_people, media_book.people
    )
    await _upsert_media_book_axis(
        db, MediaBookScene, "ux_media_book_scenes_version_entity", version.id, existing_scenes, media_book.scenes
    )

    new_cells: list[dict[str, object]] = []
    for cell in media_book.cells:
        existing_cell = existing_cells.get(cell.id)
        if existing_cell is None:
            new_cells.append(
                {
                    "id": uuid.uuid4(),
                    "entity_id": cell.id,
                    "content_version_id": version.id,
                    "person_entity_id": cell.person_id,
                    "scene_entity_id": cell.scene_id,
                    "image_asset_id": cell.image_asset_id,
                    "situation_description": cell.situation_description,
                    "unlock_hint": cell.unlock_hint,
                    "exclude_from_chat": cell.exclude_from_chat,
                }
            )
            continue
        # 블러본은 발행 때 칸 그림에서 만든다 — 그림이 바뀌면 옛 블러본은 다른 그림의 블러다.
        if existing_cell.image_asset_id != cell.image_asset_id:
            existing_cell.blurred_asset_id = None
        existing_cell.image_asset_id = cell.image_asset_id
        existing_cell.situation_description = cell.situation_description
        existing_cell.unlock_hint = cell.unlock_hint
        existing_cell.exclude_from_chat = cell.exclude_from_chat
    if not new_cells:
        return

    # 위에서 읽은 뒤 겹친 다른 저장이 같은 새 칸을 먼저 넣었으면 그 행을 이 저장 값으로 고친다(같은 칸).
    # 다른 새 칸이 같은 빈 자리를 먼저 차지했으면 둘 중 하나만 남을 수 있어 409 로 거절한다 — 화면이
    # 새로고침해 먼저 저장된 칸을 보게 한다. SAVEPOINT 안이라 거절해도 세션은 계속 쓸 수 있다.
    statement = insert(MediaBookCell).values(new_cells)
    excluded = statement.excluded
    try:
        async with db.begin_nested():
            await db.execute(
                statement.on_conflict_do_update(
                    constraint="ux_media_book_cells_version_entity",
                    set_={
                        "person_entity_id": excluded.person_entity_id,
                        "scene_entity_id": excluded.scene_entity_id,
                        "image_asset_id": excluded.image_asset_id,
                        "situation_description": excluded.situation_description,
                        "unlock_hint": excluded.unlock_hint,
                        "exclude_from_chat": excluded.exclude_from_chat,
                    },
                )
            )
    except IntegrityError as exc:
        if "ux_media_book_cells_version_person_scene" not in str(exc.orig):
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": MEDIA_BOOK_CELL_POSITION_TAKEN}
        ) from None


async def _update_story_draft(
    db: AsyncSession, content: Content, version: ContentVersion, payload: StoryDraftPayload
) -> None:
    """Autosave: no
    business validation — every child resource is upserted by entity_id (array index ->
    `order` column where applicable), removed entity_ids are deleted (children-first, since
    these FKs have no ON DELETE CASCADE), and `keywordNotes[].startingSetupId` (entity_id) is
    mapped to the physical `starting_setups.id` FK column.

    노트가 이 페이로드에 없는 시작설정을 가리키면 400 이다. 예전처럼 조용히 "스토리 전체"로 바꿔 저장하면 작가가
    고른 적용 범위가 말없이 넓어진다.

    엔딩 규칙이 같은 시작설정에 없는 스탯을 가리키면 422 `{"code": "ENDING_RULE_STAT_NOT_FOUND", "paths": [...]}` 이다
    (경로 꼴은 `setup_dangling_stat_rule_paths`). 그 엔딩은 영영 열리지 않는다. 엔딩의 우선 스탯이 그러면 같은 코드로
    `startingSetups[i].endings[j].priorityStatId` 경로를 알린다(`setup_dangling_priority_stat_paths`) — 그 엔딩은 우선
    스탯 비교에서 늘 빠진다. 이 검사는 페이로드만 보므로, 우선 스탯을 보내지 않아 기존 값을 그대로 둔 엔딩은 발행이 막는다.
    상황 노트의 조건이 그러면 422 `{"code": "SITUATION_NOTE_STAT_NOT_FOUND", "paths": [...]}`(경로 꼴은
    `setup_dangling_situation_note_paths`)이고, 둘 다 어긋났으면 엔딩 쪽을 먼저 알린다. 상황 노트는 시작설정이 `situation_notes` 를 보냈을 때만 맞춘다
    (`StartingSetupDraftItem` docstring). 스키마 validator 가 아니라 여기서
    막는 것은 같은 페이로드 모델을 미리보기 시작·Redis 의 미리보기 세션 복원도 쓰기 때문이다 — validator 로 두면 이미
    저장된 미리보기 세션의 다음 턴이 역직렬화에서 깨진다."""
    known_setup_ids = {setup_item.id for setup_item in payload.starting_setups}
    for note_index, note_item in enumerate(payload.keyword_notes):
        if note_item.starting_setup_id is not None and note_item.starting_setup_id not in known_setup_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "KEYWORD_NOTE_STARTING_SETUP_NOT_FOUND",
                    "index": note_index,
                    "label": note_item.name or next(iter(note_item.trigger_keywords), ""),
                },
            )
    dangling_stat_rule_paths = draft_dangling_stat_rule_paths(payload.starting_setups)
    if dangling_stat_rule_paths:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "ENDING_RULE_STAT_NOT_FOUND", "paths": dangling_stat_rule_paths},
        )
    dangling_situation_note_paths = draft_dangling_situation_note_paths(payload.starting_setups)
    if dangling_situation_note_paths:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "SITUATION_NOTE_STAT_NOT_FOUND", "paths": dangling_situation_note_paths},
        )

    detail = await db.get(StoryVersionDetail, version.id)
    assert detail is not None
    detail.name = payload.name
    detail.one_liner = payload.one_liner
    detail.thumbnail_asset_id = payload.thumbnail_asset_id
    detail.prompt_template = payload.prompt_template
    detail.setting_text = payload.setting_text
    # FE는 이 필드를 더 이상 보내지 않는다 — 안 보내면 구 컬럼(롤백
    # 안전망)을 그대로 둔다. 명시적 `null`은 여전히 지운다(model_fields_set으로 구분).
    if "development_example" in payload.model_fields_set:
        detail.development_example = payload.development_example
    detail.custom_prompt = payload.custom_prompt
    detail.development_examples = [
        item.model_dump(by_alias=True) for item in payload.development_examples
    ]
    detail.user_goal = payload.user_goal
    detail.rules = payload.rules
    # 캐릭터 쪽과 같은 이유로 보냈을 때만 쓴다.
    if "default_user_name" in payload.model_fields_set:
        detail.default_user_name = payload.default_user_name
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

    # 노트는 시작설정을 물리 FK 로 가리킨다. 지울 시작설정을 가리키는 노트는 시작설정 삭제보다 먼저 정리해 DB 에 내보내야
    # 한다 — 시작설정 삭제를 세션에 건 뒤에 오는 첫 조회(아래 남는 시작설정의 스탯 조회 등)의 autoflush 가 시작설정
    # DELETE 를 노트 갱신보다 먼저 내보내 FK 위반 500 이 된다. 빌더는 시작설정을 지우며 그 노트를 "스토리 전체"로 돌려
    # 보내지만, DB 의 노트 행은 이 저장이 끝나기 전까지 지울 시작설정을 가리킨다. 지금은 `_delete_starting_setup_subtree`
    # 의 첫 조회가 autoflush 로 같은 일을 해 주지만, 그 함수 안의 순서에 기대지 않으려고 직접 flush 한다. 노트의 나머지
    # 갱신(새 범위 대입)은 시작설정 upsert 뒤에 한다 — 새 시작설정의 물리 id 는 그때 생긴다.
    removed_setup_physical_ids = {
        setup.id for setup_entity_id, setup in existing_setups.items() if setup_entity_id not in incoming_setups
    }
    incoming_note_ids = {note_item.id for note_item in payload.keyword_notes}
    existing_notes: dict[uuid.UUID, KeywordNote] = {}
    for existing_note in (
        await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == version.id))
    ).all():
        if existing_note.entity_id not in incoming_note_ids:
            await db.delete(existing_note)
            continue
        if existing_note.starting_setup_id in removed_setup_physical_ids:
            existing_note.starting_setup_id = None
        existing_notes[existing_note.entity_id] = existing_note
    await db.flush()

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
                await _delete_stat_def(db, stat_def_to_prune)

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

        if "situation_notes" in setup_item.model_fields_set:
            incoming_situation_note_ids = {note_item.id for note_item in setup_item.situation_notes}
            for situation_note_to_prune in (
                await db.scalars(select(SituationNote).where(SituationNote.starting_setup_id == kept_setup.id))
            ).all():
                if situation_note_to_prune.entity_id not in incoming_situation_note_ids:
                    await db.delete(situation_note_to_prune)

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
            if "rules" in stat_item.model_fields_set:
                # 새 스탯의 물리 id 는 파이썬 쪽 기본값이라 flush 해야 채워진다.
                await db.flush()
                await _reconcile_stat_rules(db, stat_def.id, stat_item.rules)

        existing_endings = {
            e.entity_id: e
            for e in (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id))).all()
        }
        for ending_order, ending_item in enumerate(setup_item.endings):
            ending = existing_endings.get(ending_item.id)
            is_new_ending = ending is None
            if ending is None:
                ending = Ending(entity_id=ending_item.id, starting_setup_id=setup.id)
                db.add(ending)
            ending.name = ending_item.name
            ending.turn_count_gate = ending_item.turn_count_gate
            ending.judgment_prompt = ending_item.judgment_prompt
            ending.epilogue = ending_item.epilogue
            ending.hint = ending_item.hint
            ending.order = ending_order
            if is_new_ending or "priority_stat_id" in ending_item.model_fields_set:
                # 기존 엔딩에서 안 보낸 우선 스탯은 그대로 둔다(`EndingDraftItem` docstring).
                ending.priority_stat_def_entity_id = ending_item.priority_stat_id
            await db.flush()
            await _reconcile_ending_rules(db, ending.id, ending_item.stat_rules)

        if "situation_notes" in setup_item.model_fields_set:
            existing_situation_notes = {
                note.entity_id: note
                for note in (
                    await db.scalars(select(SituationNote).where(SituationNote.starting_setup_id == setup.id))
                ).all()
            }
            for situation_note_order, situation_note_item in enumerate(setup_item.situation_notes):
                situation_note = existing_situation_notes.get(situation_note_item.id)
                if situation_note is None:
                    situation_note = SituationNote(entity_id=situation_note_item.id, starting_setup_id=setup.id)
                    db.add(situation_note)
                situation_note.name = situation_note_item.name
                situation_note.info_text = situation_note_item.info_text
                situation_note.order = situation_note_order
                # 규칙에는 UUID·enum 이 있어 JSON 꼴로 바꿔야 JSONB 에 실린다.
                situation_note.condition_rules = [
                    rule_item.model_dump(mode="json") for rule_item in situation_note_item.condition_rules
                ]

    for note_order, note_item in enumerate(payload.keyword_notes):
        note = existing_notes.get(note_item.id)
        if note is None:
            note = KeywordNote(entity_id=note_item.id, content_version_id=version.id)
            db.add(note)
            # 새 노트는 안 보낸 옵션도 페이로드의 기본값으로 채운다.
            provided_options = KEYWORD_NOTE_OPTION_FIELDS
        else:
            # 기존 노트에서 안 보낸 옵션은 그대로 둔다(`KeywordNoteDraftInput` docstring).
            provided_options = KEYWORD_NOTE_OPTION_FIELDS & note_item.model_fields_set
        note.info_text = note_item.info_text
        note.trigger_keywords = note_item.trigger_keywords
        note.starting_setup_id = (
            setup_physical_id[note_item.starting_setup_id] if note_item.starting_setup_id is not None else None
        )
        note.order = note_order
        for option in provided_options:
            setattr(note, option, getattr(note_item, option))

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

    if payload.media_book is not None:
        await _update_media_book(db, content, version, payload.media_book)


@router.patch(
    "/contents/{id}/draft", dependencies=[Depends(require_legal_consent)]
)
async def update_content_draft(
    id: uuid.UUID,
    payload: CharacterDraftPayload | StoryDraftPayload,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CharacterDraftResponse | StoryDraftResponse:
    """Autosave: no
    business validation (publish is where that happens) — the version-detail row is
    overwritten wholesale and every child resource is upserted by entity_id. 미디어 북과 새로 거는 대표
    이미지는 저장 때 검사한다(422) — 틀린 채 저장되면 칸 자리·entity_id UNIQUE 가 500 을 내거나, 남의 이미지를
    걸어 그 사람의 이미지 삭제를 막는 것들이라 발행까지 미룰 수 없다. 키워드북도 길이·개수 상한과 빈·중복 키워드를
    저장 때 거절한다(422, `KeywordNoteDraftInput`) — 빌더가 같은 상한으로 입력을 먼저 막으므로 정상 입력으로는 닿지
    않는다. 노트가 페이로드에 없는 시작설정을 가리키면 400 이다. `registration`-tab
    fields (description/genreId/target/hashtags/visibility) live on Content/ContentVersion
    directly rather than the per-type detail table, since they're shared across versions,
    not per-version snapshot data."""
    content, version = await _get_owned_draft_version(
        db, id, user_id, (ContentType.CHARACTER, ContentType.STORY)
    )
    # 자동저장이 곧 "발행본과 달라진 편집분이 생겼다"이다. 아래 두 분기가 각자 끝에서 commit 하고
    # 페이로드/타입 불일치(422)는 commit 전에 raise 하므로, 여기 한 곳이 캐릭터·스토리 양쪽을 덮는다.
    content.has_unpublished_changes = True

    if isinstance(payload, CharacterDraftPayload):
        if content.type != ContentType.CHARACTER:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Payload does not match content type"
            )
        character_detail = await db.get(CharacterVersionDetail, version.id)
        assert character_detail is not None
        await _check_new_draft_thumbnail(db, content, character_detail.thumbnail_asset_id, payload.thumbnail_asset_id)
        await _update_character_draft(db, content, version, payload)
        await db.commit()
        return await _character_draft_response(db, content, version)

    if content.type != ContentType.STORY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Payload does not match content type"
        )
    story_detail = await db.get(StoryVersionDetail, version.id)
    assert story_detail is not None
    await _check_new_draft_thumbnail(db, content, story_detail.thumbnail_asset_id, payload.thumbnail_asset_id)
    await _update_story_draft(db, content, version, payload)
    await db.commit()
    return await _story_draft_response(db, content, version)


async def _delete_draft_children(db: AsyncSession, content_type: ContentType, version_id: uuid.UUID) -> None:
    """Deletes every child row hanging off a draft content_version, children-first with a
    flush between tiers (same reason as `_delete_ending_subtree`: these FKs have no ON
    DELETE CASCADE). `keyword_notes` go before `starting_setups` because
    `keyword_notes.starting_setup_id` is a physical FK, not an entity_id reference
    — `_delete_starting_setup_subtree` doesn't know about
    them since they're scoped to the version, not the setup."""
    if content_type == ContentType.CHARACTER:
        images = (
            await db.scalars(select(SituationalImage).where(SituationalImage.content_version_id == version_id))
        ).all()
        for image in images:
            await db.delete(image)
        await db.flush()
        return

    cells = (
        await db.scalars(select(MediaBookCell).where(MediaBookCell.content_version_id == version_id))
    ).all()
    for cell in cells:
        await db.delete(cell)
    people = (
        await db.scalars(select(MediaBookPerson).where(MediaBookPerson.content_version_id == version_id))
    ).all()
    for person in people:
        await db.delete(person)
    scenes = (
        await db.scalars(select(MediaBookScene).where(MediaBookScene.content_version_id == version_id))
    ).all()
    for scene in scenes:
        await db.delete(scene)

    notes = (
        await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == version_id))
    ).all()
    for note in notes:
        await db.delete(note)
    shortcuts = (
        await db.scalars(select(Shortcut).where(Shortcut.content_version_id == version_id))
    ).all()
    for shortcut in shortcuts:
        await db.delete(shortcut)
    await db.flush()

    setups = (
        await db.scalars(select(StartingSetup).where(StartingSetup.content_version_id == version_id))
    ).all()
    for setup in setups:
        await _delete_starting_setup_subtree(db, setup)
    await db.flush()


@router.delete(
    "/contents/{id}/draft", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_legal_consent)]
)
async def delete_content_draft(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Deletes a never-published content outright (draft version + content row).

    Deletable == exactly what `GET /me/drafts` returns: `current_published_version_id
    IS NULL`. Anything with publish history is refused with 409 — publishing auto-clones a
    fresh draft version, so a published work always has a draft row too, and throwing that
    away would delete the published work with it. Discarding *edits* to a published work is
    `POST /contents/{id}/draft/reset` instead. 발행작 완전 삭제는 정책상 없다.
    """
    content, version = await _get_owned_draft_version(
        db, id, user_id, (ContentType.CHARACTER, ContentType.STORY)
    )
    if content.current_published_version_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Published content cannot be deleted"
        )

    await _delete_draft_children(db, content.type, version.id)

    detail = await db.get(_detail_model(content.type), version.id)
    assert detail is not None
    await db.delete(detail)
    await db.flush()

    await db.delete(version)
    await db.flush()
    await db.delete(content)
    await db.commit()


async def _restore_draft_detail(
    db: AsyncSession, content_type: ContentType, published_version_id: uuid.UUID, draft_version_id: uuid.UUID
) -> None:
    """Overwrites the draft's `*_version_details` row in place from the published one.

    In place, not delete-and-reinsert: `content_version_id` is the table's primary key, so
    the draft row has to keep existing for `PATCH /contents/{id}/draft` to keep working."""
    if content_type == ContentType.CHARACTER:
        published_character = await db.get(CharacterVersionDetail, published_version_id)
        draft_character = await db.get(CharacterVersionDetail, draft_version_id)
        assert published_character is not None and draft_character is not None
        draft_character.name = published_character.name
        draft_character.one_liner = published_character.one_liner
        draft_character.thumbnail_asset_id = published_character.thumbnail_asset_id
        draft_character.intro = published_character.intro
        draft_character.example_dialogues = published_character.example_dialogues
        draft_character.character_prompt = published_character.character_prompt
        draft_character.playguide = published_character.playguide
        draft_character.default_user_name = published_character.default_user_name
        return

    published_story = await db.get(StoryVersionDetail, published_version_id)
    draft_story = await db.get(StoryVersionDetail, draft_version_id)
    assert published_story is not None and draft_story is not None
    draft_story.name = published_story.name
    draft_story.one_liner = published_story.one_liner
    draft_story.thumbnail_asset_id = published_story.thumbnail_asset_id
    draft_story.prompt_template = published_story.prompt_template
    draft_story.setting_text = published_story.setting_text
    draft_story.development_example = published_story.development_example
    draft_story.custom_prompt = published_story.custom_prompt
    draft_story.development_examples = published_story.development_examples
    draft_story.user_goal = published_story.user_goal
    draft_story.rules = published_story.rules
    draft_story.default_user_name = published_story.default_user_name


@router.post(
    "/contents/{id}/draft/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def reset_content_draft(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """편집 취소 — throws away in-progress edits by rewriting the draft version with
    the current published version's content. The published version itself is untouched.

    Deliberately not a delete: publishing auto-clones a draft version, and that clone is the
    row `PATCH /contents/{id}/draft` writes to — dropping it would 404 every later edit.
    `DELETE /contents/{id}/draft` is the opposite case and refuses this one with 409.

    No dirty check — resetting a draft that already matches the published version succeeds
    and simply rewrites identical rows.
    """
    content, draft_version = await _get_owned_draft_version(
        db, id, user_id, (ContentType.CHARACTER, ContentType.STORY)
    )
    if content.current_published_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content has no published version to reset to",
        )

    published_version = await db.get(ContentVersion, content.current_published_version_id)
    assert published_version is not None

    # 초안을 발행본으로 되돌리므로 미발행 편집분은 사라진다.
    content.has_unpublished_changes = False

    await _delete_draft_children(db, content.type, draft_version.id)

    draft_version.detail_description = published_version.detail_description
    await _restore_draft_detail(db, content.type, published_version.id, draft_version.id)

    if content.type == ContentType.CHARACTER:
        await _clone_character_children(db, published_version.id, draft_version.id)
    else:
        await _clone_story_children(db, published_version.id, draft_version.id)

    await db.commit()


def _download_original_for_screening(storage_key: str) -> tuple[bytes, str]:
    """Blocking network call — run via `run_in_threadpool`.

    원본과 그 MIME 타입. MIME 은 저장 키의 확장자가 아니라 바이트에서 읽는다 — 운영은 MIME 표에 `image/webp` 가
    없어 업로드 키에 확장자가 붙지 않으므로, 키로 짐작하면 그림이 형식 없는 바이트(`application/octet-stream`)로
    심사에 간다. 헤더만 읽어 디코드 비용은 없다."""
    data = download_object(storage_key)
    return data, read_image_content_type(data) or "application/octet-stream"


def _download_situational_image_for_screening(storage_key: str) -> tuple[bytes, str]:
    """Blocking network call — run via `run_in_threadpool`.

    상황 이미지는 축소본(`_thumb.webp`, 긴 변 512px)을 싣는다 — 원본(장당 수 MB)을 여러 장 받는 시간과 메모리를
    줄인다. 축소본이 **없을** 때만 원본으로 대신한다: READY 그림은 축소본을 갖는 것이 원칙이지만 그 원칙 이전에
    올라간 그림엔 없을 수 있고, 원본도 같은 그림이라 심사에서 빠지는 그림은 없다. 그 밖의 저장소 오류(권한·장애)는
    원본 읽기도 같이 실패할 수 있는 상황이라 대신하지 않고 그대로 올려 발행을 멈춘다.

    스토리 미디어 북 칸은 축소본을 못 읽으면 대신하지 않고 발행을 멈춘다 — 두 경로의 정책이 다르다."""
    try:
        return download_object(build_thumbnail_key(storage_key)), THUMBNAIL_CONTENT_TYPE
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey"):
            raise
    logger.warning("상황 이미지 축소본이 없어 원본으로 심사한다: %s", storage_key)
    return _download_original_for_screening(storage_key)


async def _storage_keys(db: AsyncSession, asset_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """자산 id → 저장 키. 발행은 읽기 구간에서 키만 모아 두고 커넥션을 돌려준 뒤에 내려받는다."""
    if not asset_ids:
        return {}
    rows = await db.execute(select(Asset.id, Asset.storage_key).where(Asset.id.in_(set(asset_ids))))
    return dict(rows.tuples().all())


async def _download_character_screening_images(
    thumbnail_key: str | None, situational_keys: Sequence[str]
) -> list[tuple[bytes, str]]:
    """썸네일(대표 이미지) 원본 + 이 버전의 상황 이미지 축소본을 받은 순서대로 내려받아 (바이트, MIME 타입) 쌍으로
    반환한다 — LLMClient.generate_structured()의 멀티모달 images 인자로 그대로 전달된다. 대표 이미지는 작품
    얼굴이라 원본 그대로 본다."""
    images: list[tuple[bytes, str]] = []
    if thumbnail_key is not None:
        images.append(await run_in_threadpool(_download_original_for_screening, thumbnail_key))
    for storage_key in situational_keys:
        images.append(await run_in_threadpool(_download_situational_image_for_screening, storage_key))
    return images


def _publish_conflict() -> HTTPException:
    """발행이 심사를 기다리는 동안 초안이 바뀌어 심사한 것을 그대로 발행할 수 없을 때의 응답. 문구는 화면이 가진다 —
    같은 문장을 서버에도 두면 한쪽만 고쳐진다."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "PUBLISH_CONFLICT"})


@dataclass(frozen=True)
class _PublishPlan:
    """발행 읽기 구간이 정한 것 — 외부 호출 구간이 이것만 보고 일하고, 쓰기 구간이 초안을 다시 읽어 비교한다."""

    # (대표 이미지 자산, 심사에 싣는 순서의 (항목 entity_id, 그림 자산)). 쓰기 구간에서 같아야 발행한다.
    screened: tuple[uuid.UUID | None, tuple[tuple[uuid.UUID, uuid.UUID], ...]]
    # 블러본을 만들 칸의 (entity_id, 그림 자산). 캐릭터는 비어 있다.
    cells_to_blur: tuple[tuple[uuid.UUID, uuid.UUID], ...]
    thumbnail_key: str | None
    # 심사 순서의 (항목 entity_id, 원본 저장 키).
    image_keys: list[tuple[uuid.UUID, str]]
    prompt: str


async def _lock_draft_for_publish(
    db: AsyncSession, content_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[Content, ContentVersion]:
    """발행 쓰기 구간의 시작. 작품 행을 잠가 같은 작품의 다른 발행·초안 쓰기와 줄을 세운 뒤, 읽기 구간에서 본 초안이
    아직 초안인지 본다. 다른 창이나 두 번 누른 발행이 그사이 먼저 끝났으면 그 초안은 이미 발행본이다 — 그대로 쓰면
    발행본 번호를 덮어쓰고 초안이 둘 생긴다. 잠금은 이 구간의 커밋까지만 쥔다(외부 호출이 없는 짧은 구간)."""
    content = await db.scalar(select(Content).where(Content.id == content_id).with_for_update())
    version = await db.scalar(
        select(ContentVersion).where(ContentVersion.id == version_id, ContentVersion.published_at.is_(None))
    )
    if content is None or version is None:
        raise _publish_conflict()
    return content, version


async def _screen_for_publish(
    db: AsyncSession,
    llm_client: LLMClient,
    *,
    call_site: Literal["publish_filter_character", "publish_filter_story"],
    content: Content,
    prompt_set: PromptSet,
    prompt: str,
    images: list[tuple[bytes, str]],
) -> None:
    """발행 심사. 통과하지 못하면 400 `{reason}` 을 던진다. 직전에 통과한 심사와 입력이 전부 같으면 LLM 을
    부르지 않는다(`content/publish_filter_memo.py`). 모델은 클라이언트가 실제로 고를 값과 같은 함수로
    구해야 심사 모델을 바꾼 뒤 옛 모델의 통과로 건너뛰지 않는다. 기본 모델은 `get_llm_client` 가 만드는 클라이언트가
    쓰는 `settings.gemini_model_name` 이다.

    작가당 시간당 심사 횟수 상한은 통과 기억을 본 **뒤**, LLM 을 부르기 직전에 센다 — 기억 적중은 호출이 없어
    비용도 없다. 심사 호출이 실패하면(Gemini 쿼터 429·타임아웃·응답 파싱 실패) 판정이 없으므로 발행하지 않고
    503 으로 알린다.

    호출자는 읽기를 마치고 커밋한 세션을 넘긴다. 상한 판정이 면제 여부를 DB 에서 읽어 트랜잭션을 다시 열므로, 심사를
    기다리기 전에 다시 커밋해 커넥션을 돌려준다."""
    model = structured_model(call_site, settings.gemini_model_name)
    memo_key = screening_key(
        content_id=content.id,
        prompt_set_id=prompt_set.id,
        model=model,
        prompt=prompt,
        images=images,
    )
    if await has_passed(memo_key):
        # 키 앞부분만 남긴다 — 입력을 되짚을 수 없고, 같은 작품의 재시도끼리 묶어 보기에는 충분하다.
        logger.warning(
            "publish_filter_skipped call_site=%s key=%s", call_site, memo_key.removeprefix(PASSED_KEY_PREFIX)[:12]
        )
        return
    await enforce_publish_screen_limit(content.creator_user_id, db)
    await db.commit()
    try:
        filter_result = await llm_client.generate_structured(
            prompt,
            PublishFilterResult,
            images=images,
            usage=LLMCallContext(call_site=call_site, user_id=content.creator_user_id, room_id=None),
        )
    except LLMPolicyViolationError as exc:
        # Gemini 가 자체 안전 기준으로 응답을 막으면 판정이 없다. 심사가 보는 것은 그림뿐이라 작가에게는 그림 때문에
        # 거부된 것이므로, 오류(500) 대신 이의제기할 수 있는 거부로 돌려준다. 막힌 범주는 알리지 않는다. 통과가
        # 아니므로 기억하지 않는다.
        logger.warning("publish_filter_blocked call_site=%s: %s", call_site, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": "첨부한 이미지 중 안전 기준에 걸리는 그림이 있어 발행할 수 없어요."},
        ) from exc
    except LLMClientError as exc:
        # 안전 차단(위)을 뺀 나머지 호출 실패다. 거부(`reason`)의 모양을 쓰면 화면이 이의제기로 안내하므로 다른
        # 모양으로 돌려준다. 통과가 아니므로 기억하지 않는다. 쿼터 소진은 태그를 갈라 승격해야 이벤트로 행동할 수 있다.
        logger.warning("publish_filter_unavailable call_site=%s: %s", call_site, exc)
        capture_dependency_failure(
            exc, dependency="gemini_rate_limit" if isinstance(exc, LLMRateLimitError) else "gemini"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PUBLISH_SCREENING_UNAVAILABLE",
                "message": "발행 심사를 지금 진행하지 못했어요. 잠시 뒤 다시 발행해 주세요.",
            },
        ) from exc
    if not filter_result.passed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": filter_result.reason or "발행 심사를 통과하지 못했습니다."},
        )
    await remember_pass(memo_key)


@router.post(
    "/contents/{id}/publish", dependencies=[Depends(require_legal_consent)]
)
async def publish_content(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> ContentPublishResponse:
    """Publish the draft of a character or story.

    세 구간으로 나눈다. 저장소에서 그림 수십 장을 받고 Gemini 심사를 기다리는 동안(수 초~십수 초) DB 트랜잭션을
    열어 두면 커넥션 하나를 통째로 쥐어 다른 요청이 풀을 기다리기 때문이다.

    1. 읽기: 따로 연 세션에서 소유·초안 확인, 발행 검증(400 은 여기서), 심사할 그림과 블러본을 만들 칸을 정하고 그
       세션을 닫는다. 요청 세션에 읽은 객체를 남기지 않는 것은 3 이 그 세션에서 같은 행을 다시 읽기 때문이다 — 남아
       있으면 커밋 뒤에도 옛 값을 들고 있어 다시 읽어도 옛 값이 나온다.
    2. 외부 호출: 그림 내려받기 → 심사 → (스토리) 칸 블러본 올리기. 트랜잭션 없음.
    3. 쓰기: 요청 세션의 짧은 트랜잭션에서 작품 행을 잠그고 초안을 다시 읽어, 아직 초안인지와 심사한 그림·블러 대상이
       그대로인지 본다. 다르면 409 `PUBLISH_CONFLICT` 이고 아무것도 쓰지 않는다. 같으면 발행한다.

    글만 바뀐 경우는 충돌로 치지 않는다 — 심사는 그림만 보고, 발행본에는 3 에서 다시 읽은 글이 실린다. 3 에서 검증을
    다시 돌리므로 그사이 필수 칸이 비면 400 이다. 충돌로 멈춘 발행이 이미 올린 블러본은 가리키는 행 없이 남는다."""
    # 인증 의존성이 요청 세션에 연 읽기 트랜잭션을 닫는다(롤백은 세션의 객체를 만료시켜 쓰지 않는다).
    await db.commit()
    async with session_factory() as read_db:
        content, version = await _get_owned_draft_version(
            read_db, id, user_id, (ContentType.CHARACTER, ContentType.STORY)
        )
        prompt_set, prompt_sections = await load_active_prompt_set(read_db, lane="publish_filter")
        if content.type == ContentType.CHARACTER:
            plan = await _plan_character_publish(read_db, content, version, prompt_sections)
        else:
            plan = await _plan_story_publish(read_db, content, version, prompt_sections)

    if content.type == ContentType.CHARACTER:
        filter_images = await _download_character_screening_images(
            plan.thumbnail_key, [storage_key for _, storage_key in plan.image_keys]
        )
    else:
        filter_images = await _download_story_screening_images(plan.thumbnail_key, plan.image_keys)
    await _screen_for_publish(
        db,
        llm_client,
        call_site="publish_filter_character" if content.type == ContentType.CHARACTER else "publish_filter_story",
        content=content,
        prompt_set=prompt_set,
        prompt=plan.prompt,
        images=filter_images,
    )
    image_keys = dict(plan.image_keys)
    blurs = await _upload_media_book_blurs([(cell_id, image_keys[cell_id]) for cell_id, _ in plan.cells_to_blur])

    locked_content, locked_version = await _lock_draft_for_publish(db, content.id, version.id)
    if content.type == ContentType.CHARACTER:
        return await _write_character_publish(db, locked_content, locked_version, plan)
    return await _write_story_publish(db, locked_content, locked_version, plan, blurs)


async def _clone_character_children(
    db: AsyncSession, src_version_id: uuid.UUID, dst_version_id: uuid.UUID
) -> None:
    """Copies a character version's child rows onto another version, `entity_id` and all.

    Runs in both directions: publish clones draft -> the fresh draft it opens for the next
    edit, 편집 취소(`reset_content_draft`) clones the published version -> the draft.
    `entity_id` must survive the copy — `character_image_exposures` joins on it, so a
    regenerated id would silently re-blur images the reader already unlocked."""
    images = (
        await db.scalars(
            select(SituationalImage).where(SituationalImage.content_version_id == src_version_id)
        )
    ).all()
    for image in images:
        db.add(
            SituationalImage(
                entity_id=image.entity_id,
                content_version_id=dst_version_id,
                image_asset_id=image.image_asset_id,
                blurred_asset_id=image.blurred_asset_id,
                trigger_condition=image.trigger_condition,
                order=image.order,
            )
        )


@dataclass(frozen=True)
class _CharacterPublishDraft:
    """발행 검증을 통과한 캐릭터 초안. 읽기 구간과 쓰기 구간이 같은 함수(`_load_character_publish_draft`)로 만든다."""

    detail: CharacterVersionDetail
    situational_images: Sequence[SituationalImage]

    def screened_images(self) -> tuple[uuid.UUID | None, tuple[tuple[uuid.UUID, uuid.UUID], ...]]:
        """심사에 싣는 그림 — 대표 이미지와, 그림이 걸린 상황 이미지(항목·그림)를 싣는 순서대로. 쓰기 구간에서 이 값이
        읽기 구간과 같아야 심사한 그림이 곧 발행되는 그림이다."""
        return self.detail.thumbnail_asset_id, tuple(
            (image.entity_id, image.image_asset_id)
            for image in self.situational_images
            if image.image_asset_id is not None
        )


async def _load_character_publish_draft(
    db: AsyncSession, content: Content, version: ContentVersion
) -> _CharacterPublishDraft:
    detail = await db.get(CharacterVersionDetail, version.id)
    assert detail is not None

    # 심사가 이 순서로 그림을 싣고 라벨 "상황 이미지 k" 를 붙인다. 순서가 흔들리면 같은 그림의 재발행이 지난
    # 통과를 못 쓰고, 라벨이 다른 그림을 가리킨다. 동률은 버전을 넘어 같은 `entity_id` 로 가른다 — 물리 `id` 는
    # 발행 복제 때마다 새로 뽑힌다.
    situational_images = (
        await db.scalars(
            select(SituationalImage)
            .where(SituationalImage.content_version_id == version.id)
            .order_by(SituationalImage.order, SituationalImage.entity_id)
        )
    ).all()
    missing_fields = validate_character_publish(content, version, detail, situational_images)
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"missingFields": missing_fields}
        )
    return _CharacterPublishDraft(detail=detail, situational_images=situational_images)


async def _plan_character_publish(
    db: AsyncSession, content: Content, version: ContentVersion, prompt_sections: list[PromptSection]
) -> _PublishPlan:
    draft = await _load_character_publish_draft(db, content, version)
    thumbnail_asset_id, situational = draft.screened_images()
    screened_asset_ids = (thumbnail_asset_id, *(image_id for _, image_id in situational))
    storage_keys = await _storage_keys(db, [image_id for image_id in screened_asset_ids if image_id is not None])
    return _PublishPlan(
        screened=draft.screened_images(),
        cells_to_blur=(),
        thumbnail_key=storage_keys[thumbnail_asset_id] if thumbnail_asset_id is not None else None,
        image_keys=[(entity_id, storage_keys[image_id]) for entity_id, image_id in situational],
        # 발행 검증이 이미지 없는 상황 이미지 행을 먼저 거부하므로 위 목록은 상황 이미지 전부다. 라벨 수는 실린 그림과
        # 같은 목록에서 센다 — 그래야 이미지 목록 줄과 실린 그림이 짝을 이룬다.
        prompt=build_character_publish_filter_prompt(
            sections=prompt_sections, situational_image_count=len(situational)
        ),
    )


async def _write_character_publish(
    db: AsyncSession, content: Content, version: ContentVersion, plan: _PublishPlan
) -> ContentPublishResponse:
    """발행 쓰기 구간(작품 행을 잠근 뒤). 심사한 그림이 그대로일 때만 쓰고 커밋한다."""
    draft = await _load_character_publish_draft(db, content, version)
    if draft.screened_images() != plan.screened:
        raise _publish_conflict()
    detail = draft.detail

    # 발행하면 이 초안이 곧 발행본이 되므로 미발행 편집분은 0이다.
    content.has_unpublished_changes = False
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
            default_user_name=detail.default_user_name,
        )
    )
    await _clone_character_children(db, version.id, new_version.id)

    content.current_published_version_id = version.id
    await db.commit()

    assert version.version_number is not None
    return ContentPublishResponse(content_id=content.id, version_number=version.version_number)


def _media_book_image_unavailable(cell_entity_id: uuid.UUID) -> HTTPException:
    """칸 그림을 저장소에서 읽지 못해 발행을 멈출 때의 응답. 어느 칸인지 알린다 — 심사 거부(`reason`)의 모양을
    쓰면 화면이 이의제기로 안내한다."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "MEDIA_BOOK_IMAGE_UNAVAILABLE",
            "cellId": str(cell_entity_id),
            "message": "미디어 북 칸 그림 하나를 처리하지 못했어요. 잠시 뒤 다시 발행하거나 그 칸 그림을 다시 올려 주세요.",
        },
    )


async def _download_story_screening_images(
    thumbnail_key: str | None, cells: Sequence[tuple[uuid.UUID, str]]
) -> list[tuple[bytes, str]]:
    """대표 이미지 원본과, 그 뒤로 미디어 북 칸마다 축소본(`_thumb.webp`, 긴 변 512px) 한 장씩을 캐릭터의
    `_download_character_screening_images`와 같은 (바이트, MIME 타입) 쌍으로 돌려준다. `cells` 는 (칸 entity_id, 원본
    저장 키)이고 받은 순서 그대로 싣는다 — 심사 프롬프트의 이미지 목록 라벨과 짝이 맞아야 한다. 원본(장당 수 MB)을
    50장 싣지 않으려고 축소본을 쓴다.

    축소본은 동시에 내려받는다(운영 저장소 왕복 50번을 줄로 세우면 발행이 그만큼 늦어진다). 칸 하나라도 못 읽으면
    심사 없이 발행을 멈춘다 — 그 칸을 빼고 심사하면 아무도 보지 않은 그림이 발행된다."""
    images: list[tuple[bytes, str]] = []
    if thumbnail_key is not None:
        images.append(await run_in_threadpool(_download_original_for_screening, thumbnail_key))
    if not cells:
        return images

    semaphore = asyncio.Semaphore(_MEDIA_BOOK_S3_CONCURRENCY)

    async def download_thumbnail(storage_key: str) -> bytes:
        async with semaphore:
            return await run_in_threadpool(download_object, build_thumbnail_key(storage_key))

    results = await asyncio.gather(
        *(download_thumbnail(storage_key) for _, storage_key in cells), return_exceptions=True
    )
    for (cell_entity_id, _), result in zip(cells, results, strict=True):
        if isinstance(result, (BotoCoreError, ClientError)):
            logger.warning("미디어 북 칸 %s 축소본을 읽지 못함 — 심사 없이 발행을 멈춘다: %s", cell_entity_id, result)
            capture_dependency_failure(result, dependency="s3")
            raise _media_book_image_unavailable(cell_entity_id) from result
        if isinstance(result, BaseException):
            raise result
        images.append((result, THUMBNAIL_CONTENT_TYPE))
    return images


async def _clone_ending_rules(db: AsyncSession, old_ending_id: uuid.UUID, new_ending_id: uuid.UUID) -> None:
    """Publish-time deep copy of one ending's rule tree onto its freshly-cloned sibling — same
    tree shape as `_reconcile_ending_rules` but duplicates rather than upserts (a republish clone
    always starts from an empty `new_ending_id`)."""
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


async def _clone_story_children(
    db: AsyncSession, src_version_id: uuid.UUID, dst_version_id: uuid.UUID
) -> None:
    """Copies a story version's whole child tree onto another version, `entity_id` and all.

    Same two directions as `_clone_character_children`: publish (draft -> next draft) and
    편집 취소(`reset_content_draft`, published -> draft). Preserving `entity_id` is
    what keeps `chat_room_stats`/`story_ending_unlocks` joined to the right stat/ending
    across versions.

    The one column that can't be copied as-is is `keyword_notes.starting_setup_id`: it's a
    physical FK, not an entity_id reference, so it goes through an `old -> entity_id -> new`
    remap. `ending_rules.stat_def_entity_id` is an entity_id reference and needs none. 스탯 규칙은 스탯을 물리 FK 로
    가리키므로 스탯마다 새 스탯 id 로 바로 복제한다. 상황 노트도 시작설정을 물리
    FK 로 가리키지만 시작설정 루프 안에서 새 시작설정 id 로 바로 복제한다. 그 조건(JSONB)의 스탯 참조는 entity_id 라
    값째 옮긴다."""
    setups = (
        await db.scalars(
            select(StartingSetup)
            .where(StartingSetup.content_version_id == src_version_id)
            .order_by(StartingSetup.order)
        )
    ).all()
    old_setup_entity_id_by_physical_id = {setup.id: setup.entity_id for setup in setups}
    new_setup_physical_id_by_entity_id: dict[uuid.UUID, uuid.UUID] = {}

    for setup in setups:
        new_setup = StartingSetup(
            entity_id=setup.entity_id,
            content_version_id=dst_version_id,
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
            new_stat_def = StatDef(
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
                change_direction=stat_def.change_direction,
                max_change_per_turn=stat_def.max_change_per_turn,
                order=stat_def.order,
            )
            db.add(new_stat_def)
            await db.flush()
            for rule in (await db.scalars(select(StatRule).where(StatRule.stat_def_id == stat_def.id))).all():
                db.add(
                    StatRule(
                        entity_id=rule.entity_id,
                        stat_def_id=new_stat_def.id,
                        condition=rule.condition,
                        delta=rule.delta,
                        order=rule.order,
                    )
                )

        endings = (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id))).all()
        for ending in endings:
            new_ending = Ending(
                entity_id=ending.entity_id,
                starting_setup_id=new_setup.id,
                name=ending.name,
                turn_count_gate=ending.turn_count_gate,
                judgment_prompt=ending.judgment_prompt,
                epilogue=ending.epilogue,
                hint=ending.hint,
                order=ending.order,
                priority_stat_def_entity_id=ending.priority_stat_def_entity_id,
            )
            db.add(new_ending)
            await db.flush()
            await _clone_ending_rules(db, ending.id, new_ending.id)

        situation_notes = (
            await db.scalars(select(SituationNote).where(SituationNote.starting_setup_id == setup.id))
        ).all()
        for situation_note in situation_notes:
            db.add(
                SituationNote(
                    entity_id=situation_note.entity_id,
                    starting_setup_id=new_setup.id,
                    name=situation_note.name,
                    info_text=situation_note.info_text,
                    order=situation_note.order,
                    condition_rules=situation_note.condition_rules,
                )
            )

    keyword_notes = (
        await db.scalars(
            select(KeywordNote)
            .where(KeywordNote.content_version_id == src_version_id)
            .order_by(KeywordNote.order, KeywordNote.entity_id)
        )
    ).all()
    for note in keyword_notes:
        new_starting_setup_id = None
        if note.starting_setup_id is not None:
            old_entity_id = old_setup_entity_id_by_physical_id[note.starting_setup_id]
            new_starting_setup_id = new_setup_physical_id_by_entity_id[old_entity_id]
        db.add(
            KeywordNote(
                entity_id=note.entity_id,
                content_version_id=dst_version_id,
                starting_setup_id=new_starting_setup_id,
                info_text=note.info_text,
                trigger_keywords=note.trigger_keywords,
                name=note.name,
                order=note.order,
                exclude_keywords=note.exclude_keywords,
                sticky_turns=note.sticky_turns,
                always_on=note.always_on,
            )
        )

    shortcuts = (
        await db.scalars(select(Shortcut).where(Shortcut.content_version_id == src_version_id))
    ).all()
    for shortcut in shortcuts:
        db.add(
            Shortcut(
                entity_id=shortcut.entity_id,
                content_version_id=dst_version_id,
                name=shortcut.name,
                description=shortcut.description,
                prompt=shortcut.prompt,
            )
        )

    # 칸의 블러본 id 도 그대로 옮긴다 — 그림이 안 바뀐 칸은 다음 발행이 블러본을 다시 만들지 않는다.
    people = (
        await db.scalars(select(MediaBookPerson).where(MediaBookPerson.content_version_id == src_version_id))
    ).all()
    for person in people:
        db.add(
            MediaBookPerson(
                entity_id=person.entity_id, content_version_id=dst_version_id, name=person.name, order=person.order
            )
        )
    scenes = (
        await db.scalars(select(MediaBookScene).where(MediaBookScene.content_version_id == src_version_id))
    ).all()
    for scene in scenes:
        db.add(
            MediaBookScene(
                entity_id=scene.entity_id, content_version_id=dst_version_id, name=scene.name, order=scene.order
            )
        )
    cells = (
        await db.scalars(select(MediaBookCell).where(MediaBookCell.content_version_id == src_version_id))
    ).all()
    for cell in cells:
        db.add(
            MediaBookCell(
                entity_id=cell.entity_id,
                content_version_id=dst_version_id,
                person_entity_id=cell.person_entity_id,
                scene_entity_id=cell.scene_entity_id,
                image_asset_id=cell.image_asset_id,
                blurred_asset_id=cell.blurred_asset_id,
                situation_description=cell.situation_description,
                unlock_hint=cell.unlock_hint,
                exclude_from_chat=cell.exclude_from_chat,
            )
        )


async def _upload_media_book_blurs(cells: Sequence[tuple[uuid.UUID, str]]) -> dict[uuid.UUID, BlurredUpload]:
    """블러본이 없는 칸(그림을 새로 걸었거나 바꾼 칸)마다 블러본을 만들어 올리고 칸 entity_id → 올린 블러본을
    돌려준다. `cells` 는 (칸 entity_id, 원본 저장 키)이고 배치표 순서(인물 → 장면)여야 한다 — 여러 칸이 실패하면 그
    순서로 가장 앞 칸을 알린다. 보관함은 아직 못 본 칸을 이 블러본으로 보여 준다. 앞 발행에서 만든 블러본은 복제로
    초안에 따라오고, 그림을 바꾸면 자동저장이 비운다.

    발행 심사를 통과한 뒤에 부른다 — 탈락할 발행이 S3 에 블러본을 올리면 가리키는 행 없이 남는다. 세션을 쓰지 않는다
    — 자산 행과 칸 갱신은 발행 쓰기 구간에서 `_attach_media_book_blurs` 가 한다.

    칸마다 원본 받기·블러·올리기를 동시에 돌린다(운영 저장소 왕복이 칸마다 붙어 줄로 세우면 50칸에 1분이 넘는다)."""
    if not cells:
        return {}
    semaphore = asyncio.Semaphore(_MEDIA_BOOK_S3_CONCURRENCY)

    async def blur(storage_key: str) -> BlurredUpload:
        async with semaphore:
            return await upload_blurred_copy(storage_key)

    # 하나가 실패해도 나머지를 끝까지 기다린다. 남은 칸을 취소해도 스레드에서 돌던 저장소 호출은 끝날 때까지
    # 멈추지 않고(기다리지 않고 응답하면 응답 뒤에도 돈다), 여러 칸이 깨졌을 때 어느 칸을 알릴지가 완료 타이밍에
    # 따라 달라진다. 그사이 다른 칸이 올린 블러본은 가리키는 행 없이 남는다(아무 응답도 서명하지 않는다).
    results = await asyncio.gather(*(blur(storage_key) for _, storage_key in cells), return_exceptions=True)
    uploads: dict[uuid.UUID, BlurredUpload] = {}
    for (cell_entity_id, _), result in zip(cells, results, strict=True):
        if isinstance(result, (BotoCoreError, ClientError, OSError, ValueError)):
            # 원본을 못 읽었거나(저장소에서 사라짐·연결 실패) 그림으로 풀지 못했다. 어느 칸인지 알려 발행을 멈춘다 —
            # 심사 거부(`reason`)의 모양을 쓰면 화면이 이의제기로 안내한다.
            logger.warning("미디어 북 칸 %s 블러본 생성 실패 — 발행을 멈춘다: %s", cell_entity_id, result)
            capture_dependency_failure(result, dependency="s3")
            raise _media_book_image_unavailable(cell_entity_id) from result
        if isinstance(result, BaseException):
            raise result
        uploads[cell_entity_id] = result
    return uploads


async def _attach_media_book_blurs(
    db: AsyncSession,
    cells: Sequence[MediaBookCell],
    uploads: dict[uuid.UUID, BlurredUpload],
    *,
    owner_user_id: uuid.UUID,
) -> None:
    """올린 블러본을 자산 행으로 만들고 블러본이 비어 있던 칸에 건다. 다음 초안 복제보다 앞이어야 새 블러본 id 가
    초안으로 넘어간다. 호출자가 블러 대상 칸이 올릴 때와 같음을 이미 확인했다."""
    pending = [cell for cell in cells if cell.blurred_asset_id is None]
    if not pending:
        return
    # 블러 자산 행이 칸이 가리킬 FK 대상이라 먼저 넣는다.
    db.add_all([blurred_asset_row(uploads[cell.entity_id], owner_user_id=owner_user_id) for cell in pending])
    await db.flush()
    for cell in pending:
        cell.blurred_asset_id = uploads[cell.entity_id].asset_id
    await db.flush()


@dataclass(frozen=True)
class _StoryPublishDraft:
    """발행 검증을 통과한 스토리 초안. 읽기 구간과 쓰기 구간이 같은 함수(`_load_story_publish_draft`)로 만든다."""

    detail: StoryVersionDetail
    # 배치표 순서(인물 → 장면). 심사 그림과 이미지 목록 라벨이 이 순서로 짝을 이룬다.
    ordered_cells: list[MediaBookCell]
    cell_labels: list[MediaBookFilterCell]

    def screened_images(self) -> tuple[uuid.UUID | None, tuple[tuple[uuid.UUID, uuid.UUID], ...]]:
        """심사에 싣는 그림 — 대표 이미지와 칸(칸·그림)을 싣는 순서대로. 쓰기 구간에서 이 값이 읽기 구간과 같아야
        심사한 그림이 곧 발행되는 그림이다."""
        return self.detail.thumbnail_asset_id, tuple(
            (cell.entity_id, cell.image_asset_id) for cell in self.ordered_cells
        )

    def cells_to_blur(self) -> tuple[tuple[uuid.UUID, uuid.UUID], ...]:
        """블러본이 없는 칸(칸·그림). 읽기 구간에서 이 칸들의 블러본을 올렸으므로 쓰기 구간에서도 같아야 건다."""
        return tuple(
            (cell.entity_id, cell.image_asset_id) for cell in self.ordered_cells if cell.blurred_asset_id is None
        )


async def _load_story_publish_draft(
    db: AsyncSession, content: Content, version: ContentVersion
) -> _StoryPublishDraft:
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

    people = (
        await db.scalars(
            select(MediaBookPerson)
            .where(MediaBookPerson.content_version_id == version.id)
            .order_by(MediaBookPerson.order)
        )
    ).all()
    scenes = (
        await db.scalars(
            select(MediaBookScene).where(MediaBookScene.content_version_id == version.id).order_by(MediaBookScene.order)
        )
    ).all()
    cells = (await db.scalars(select(MediaBookCell).where(MediaBookCell.content_version_id == version.id))).all()
    keyword_notes = (
        await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == version.id))
    ).all()
    dangling_stat_rule_paths: list[str] = []
    dangling_situation_note_paths: list[str] = []
    stat_defs: list[StatDef] = []
    stat_rules: list[StatRule] = []
    situation_notes: list[SituationNote] = []
    for setup_index, setup in enumerate(starting_setups):
        setup_stat_defs = (await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))).all()
        stat_defs += setup_stat_defs
        stat_rules += (
            await db.scalars(select(StatRule).where(StatRule.stat_def_id.in_([sd.id for sd in setup_stat_defs])))
        ).all()
        stat_ids = {stat_def.entity_id for stat_def in setup_stat_defs}
        endings_rules = [await _ending_rule_draft_items(db, ending.id) for ending in endings_by_setup_id[setup.id]]
        dangling_stat_rule_paths += setup_dangling_stat_rule_paths(setup_index, stat_ids, endings_rules)
        dangling_stat_rule_paths += setup_dangling_priority_stat_paths(
            setup_index, stat_ids, [ending.priority_stat_def_entity_id for ending in endings_by_setup_id[setup.id]]
        )
        setup_situation_notes = (
            await db.scalars(
                select(SituationNote)
                .where(SituationNote.starting_setup_id == setup.id)
                .order_by(SituationNote.order, SituationNote.entity_id)
            )
        ).all()
        situation_notes += setup_situation_notes
        dangling_situation_note_paths += setup_dangling_situation_note_paths(
            setup_index,
            stat_ids,
            [RULE_LIST_ADAPTER.validate_python(note.condition_rules) for note in setup_situation_notes],
        )

    missing_fields = validate_story_publish(
        content,
        version,
        detail,
        starting_setups,
        endings_by_setup_id,
        media_book_people=people,
        media_book_scenes=scenes,
        media_book_cells=cells,
        keyword_notes=keyword_notes,
        dangling_stat_rule_paths=dangling_stat_rule_paths,
        stat_defs=stat_defs,
        stat_rules=stat_rules,
        situation_notes=situation_notes,
        dangling_situation_note_paths=dangling_situation_note_paths,
    )
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"missingFields": missing_fields}
        )

    # 검증이 고아 칸을 막았으므로 칸마다 축이 있다. 심사 그림과 이미지 목록 라벨이 같은 축 순서(인물 → 장면)로 짝을 이룬다.
    person_by_id = {person.entity_id: (index, person.name) for index, person in enumerate(people)}
    scene_by_id = {scene.entity_id: (index, scene.name) for index, scene in enumerate(scenes)}
    ordered_cells = sorted(
        cells, key=lambda cell: (person_by_id[cell.person_entity_id][0], scene_by_id[cell.scene_entity_id][0])
    )

    return _StoryPublishDraft(
        detail=detail,
        ordered_cells=ordered_cells,
        cell_labels=[
            MediaBookFilterCell(
                person=person_by_id[cell.person_entity_id][1], scene=scene_by_id[cell.scene_entity_id][1]
            )
            for cell in ordered_cells
        ],
    )


async def _plan_story_publish(
    db: AsyncSession, content: Content, version: ContentVersion, prompt_sections: list[PromptSection]
) -> _PublishPlan:
    draft = await _load_story_publish_draft(db, content, version)
    thumbnail_asset_id = draft.detail.thumbnail_asset_id
    storage_keys = await _storage_keys(
        db,
        [
            *([thumbnail_asset_id] if thumbnail_asset_id is not None else []),
            *(cell.image_asset_id for cell in draft.ordered_cells),
        ],
    )
    return _PublishPlan(
        screened=draft.screened_images(),
        cells_to_blur=draft.cells_to_blur(),
        thumbnail_key=storage_keys[thumbnail_asset_id] if thumbnail_asset_id is not None else None,
        image_keys=[(cell.entity_id, storage_keys[cell.image_asset_id]) for cell in draft.ordered_cells],
        prompt=build_story_publish_filter_prompt(sections=prompt_sections, media_cells=draft.cell_labels),
    )


async def _write_story_publish(
    db: AsyncSession,
    content: Content,
    version: ContentVersion,
    plan: _PublishPlan,
    blurs: dict[uuid.UUID, BlurredUpload],
) -> ContentPublishResponse:
    """발행 쓰기 구간(작품 행을 잠근 뒤). 심사한 그림과 블러 대상 칸이 그대로일 때만 쓰고 커밋한다."""
    draft = await _load_story_publish_draft(db, content, version)
    if draft.screened_images() != plan.screened or draft.cells_to_blur() != plan.cells_to_blur:
        raise _publish_conflict()
    detail = draft.detail
    await _attach_media_book_blurs(db, draft.ordered_cells, blurs, owner_user_id=content.creator_user_id)

    # 발행하면 이 초안이 곧 발행본이 되므로 미발행 편집분은 0이다.
    content.has_unpublished_changes = False
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
            development_examples=detail.development_examples,
            user_goal=detail.user_goal,
            rules=detail.rules,
            default_user_name=detail.default_user_name,
        )
    )

    await _clone_story_children(db, version.id, new_version.id)

    content.current_published_version_id = version.id
    await db.commit()

    assert version.version_number is not None
    return ContentPublishResponse(content_id=content.id, version_number=version.version_number)


@router.patch(
    "/contents/{id}/visibility",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def update_content_visibility(
    id: uuid.UUID,
    body: ContentVisibilityUpdateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """The only content state-change
    endpoint; there is no delete API. Writes `Content.visibility` directly regardless of
    draft/publish state, so the existing `Content.visibility == PUBLIC` filter already used
    by home/search/other-profile discovery queries excludes it immediately, matching
    the FE's `canDiscoverPublicly`."""
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    if content.creator_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the content owner")

    content.visibility = body.visibility
    await db.commit()


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
    """`sort=popular` prioritizes chat_count over like_count/view_count by ordering on
    all three columns lexicographically (chat_count first) instead of a single
    weighted score, so chat_count strictly dominates ties by construction — the
    actual weighted-score formula is still a PRD-level open question for later
    tuning.
    """
    detail_model = _detail_model(type)

    query = select_publicly_listed(
        type, Content, detail_model.name, detail_model.thumbnail_asset_id, User.nickname
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
            creator_nickname=nickname if nickname is not None else WITHDRAWN_USER_NICKNAME,
        )
        for content, name, thumbnail_asset_id, nickname in page
    ]

    next_cursor: str | None = None
    if has_more and page:
        last_content = page[-1][0]
        if sort == "popular":
            next_cursor = _encode_cursor(
                [
                    str(last_content.chat_count),
                    str(last_content.like_count),
                    str(last_content.view_count),
                    str(last_content.id),
                ]
            )
        else:
            next_cursor = _encode_cursor([last_content.created_at.isoformat(), str(last_content.id)])

    return ContentListResponse(items=items, next_cursor=next_cursor)


@router.get("/home-curation")
async def get_home_curation(type: ContentType, db: AsyncSession = Depends(get_db_session)) -> HomeCurationResponse:
    """홈 첫 화면에 거는 그 유형의 운영자 지정작. 지정이 없거나, 지정 작품이 지금 공개 목록(`list_contents`)에
    실리지 않으면 `item` 이 null 이다 — 목록과 같은 `select_publicly_listed` 로 거르므로 이용제한·비공개가 되면 자동으로
    빠지고 제한이 풀리면 다시 보인다.

    홈 방문마다 불리므로 상세 GET 과 달리 조회수를 세지 않는다(요청·열람 키를 받지 않는다). 뷰어와 무관한
    응답이라 세션도 읽지 않는다. 경로가 `/contents/{id}` 아래가 아닌 이유는 그 경로의 uuid 칸에 먼저 잡히기
    때문이다."""
    detail_model = _detail_model(type)
    row = (
        await db.execute(
            select_publicly_listed(
                type,
                Content,
                detail_model.name,
                detail_model.one_liner,
                detail_model.default_user_name,
                detail_model.thumbnail_asset_id,
            )
            .join(HomeCuration, HomeCuration.content_id == Content.id)
            .where(HomeCuration.content_type == type)
        )
    ).one_or_none()
    if row is None:
        return HomeCurationResponse(item=None)

    content, name, one_liner, default_user_name, thumbnail_asset_id = row
    return HomeCurationResponse(
        item=HomeCurationItem(
            id=content.id,
            type=content.type,
            name=name,
            one_liner=one_liner,
            default_user_name=default_user_name,
            thumbnail_url=await _resolve_thumbnail_url(db, thumbnail_asset_id),
        )
    )


def _resolve_access_status(
    visibility: ContentVisibility, moderation_status: ModerationStatus
) -> ContentAccessStatus:
    """Mirrors the FE's `resolveAccessStatus` — kept as the
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

    자기 세션을 연다. 요청 세션(`Depends(get_db_session)`)은 아직 닫히지 않았지만(FastAPI 는 백그라운드 작업을 응답
    전송 뒤, 의존성 정리 전에 돈다) 이 핸들러가 커밋하지 않아 읽기 트랜잭션이 열린 채라, 그 세션에 쓰기를 얹지 않고
    짧은 쓰기 트랜잭션을 따로 둔다. 그래서 이 작업이 도는 동안 커넥션이 순간 둘이다.
    The increment is a relative SQL UPDATE, not read-modify-write in Python, so
    concurrent views never lose counts.
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
    """Access control is query-response-based, not a 403/404 gate here: any existing,
    published content returns 200 with `accessStatus`/`isOwner`, and `canViewDetailPage` on
    the FE decides whether to render it or an "unavailable" state instead. When the viewer
    may not see the content (`is_open_to` is false), the body — `detailDescription` and the
    story's `startingSetups` — is sent empty; name, one-liner, thumbnail and hashtags stay.
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
                detail_model.default_user_name,
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
    content, version, name, one_liner, default_user_name, thumbnail_asset_id, genre_name, creator_nickname = row
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
    detail_description = version.detail_description
    media_tag_images: dict[uuid.UUID, MediaTagImage] = {}
    if content.type == ContentType.STORY:
        setups = (
            await db.scalars(
                select(StartingSetup)
                .where(StartingSetup.content_version_id == version.id)
                .order_by(StartingSetup.order)
            )
        ).all()
        # 등록 설명·프롤로그의 미디어 북 태그를 이 발행본의 칸 id 형태로 바꾸고 그 칸 그림을 함께 싣는다.
        # 상세는 해금 기록이 아니지만, 작성자가 소개에 직접 넣은 그림이라 보여 준다. 다만 이 응답은 볼 수
        # 없는 작품에도 나가므로(화면이 "볼 수 없음"을 그린다) 그림 원본은 화면이 상세 본문을 그리는 경우 —
        # 이용 가능하고, 비공개면 작성자 본인 — 에만 서명한다. 웹의 `canViewDetailPage` 와 같은 조건이다.
        [detail_description, *prologues], referenced = await normalize_texts(
            db, version.id, [version.detail_description, *(setup.prologue for setup in setups)]
        )
        if is_open_to(content, viewer_user_id):
            media_tag_images = await resolve_media_tag_images(db, version.id, referenced)
        starting_setups = [
            StartingSetupSummary(id=setup.id, name=setup.name, prologue=prologue)
            for setup, prologue in zip(setups, prologues, strict=True)
        ]

    # 이 응답은 볼 수 없는 작품에도 200 으로 나가고 화면이 "볼 수 없음" 을 그린다. 본문(소개·시작설정·프롤로그)까지
    # 실으면 화면이 가려도 주소만 알면 읽히므로 비운다. 그 작품에 방이 있는 사용자도 예외가 아니다 — 이 목록을 쓰는
    # 곳은 상세 화면과 시작설정 변경 창뿐인데, 볼 수 없는 작품에서는 시작설정 변경(새 방)도 막힌다. 채팅방 헤더는
    # 이름·썸네일만 쓰므로 그대로 둔다.
    if not is_open_to(content, viewer_user_id):
        detail_description = ""
        if starting_setups is not None:
            starting_setups = []

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
        thumbnail_url=await _resolve_display_url(db, thumbnail_asset_id),
        creator_user_id=content.creator_user_id,
        creator_nickname=creator_nickname
        if creator_nickname is not None
        else WITHDRAWN_USER_NICKNAME,
        genre_id=content.genre_id,
        genre_name=genre_name,
        hashtags=content.hashtags,
        one_liner=one_liner,
        detail_description=detail_description,
        default_user_name=default_user_name,
        chat_count=content.chat_count,
        like_count=content.like_count,
        is_liked=is_liked,
        is_favorited=is_favorited,
        starting_setups=starting_setups,
        media_tag_images=media_tag_images,
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
    """History only, no version-switch action."""
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
    """Idempotent: a repeat like is a no-op
    rather than a second row/double increment (the FE does an
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
    """Not idempotent (unlike like/favorite):
    each call inserts a new pending report row, matching the
    reports table having no unique constraint on (reporter_user_id, content_id)."""
    content = await db.get(Content, id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    # A creator's report on their own work only adds noise to the moderation queue.
    if content.creator_user_id == user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot report own content")

    db.add(
        Report(
            reporter_user_id=user_id,
            content_id=id,
            reason_category=body.reason_category,
            status=ReportStatus.PENDING,
        )
    )
    await db.commit()
