import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminContentActionRequest,
    AdminContentCreator,
    AdminContentDetailResponse,
    AdminContentListItem,
    AdminContentListResponse,
    AdminContentVersionItem,
)
from api.core.s3 import generate_presigned_get_url
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset
from api.db.models.moderation import ModerationAction, ModerationActionType, Notification
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail
from api.db.session import get_db_session
from api.moderation.router import upgrade_content_chat_rooms_to_latest_version

router = APIRouter(tags=["admin"])

ADMIN_CONTENT_PAGE_SIZE = 20


async def _resolve_asset_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """`moderation/router.py`와 같은 모양 — 파일 간 헬퍼 비공유 관례(apps/api/CLAUDE.md)에
    따라 이 파일에 복제한다."""
    if asset_id is None:
        return None
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return None
    return await run_in_threadpool(generate_presigned_get_url, asset.storage_key)


async def _content_names_by_version_id(
    db: AsyncSession, version_ids: list[uuid.UUID], content_type: ContentType
) -> dict[uuid.UUID, str]:
    """N+1 회피 벌크 조회 — `moderation/router.py`의 `_admin_report_list_items`와 같은
    패턴이지만 파일 간 헬퍼 비공유 관례에 따라 복제한다."""
    if not version_ids:
        return {}

    names_by_version_id: dict[uuid.UUID, str] = {}
    if content_type == ContentType.CHARACTER:
        for detail in (
            await db.scalars(
                select(CharacterVersionDetail).where(
                    CharacterVersionDetail.content_version_id.in_(version_ids)
                )
            )
        ).all():
            names_by_version_id[detail.content_version_id] = detail.name
    else:
        for story_detail in (
            await db.scalars(
                select(StoryVersionDetail).where(
                    StoryVersionDetail.content_version_id.in_(version_ids)
                )
            )
        ).all():
            names_by_version_id[story_detail.content_version_id] = story_detail.name
    return names_by_version_id


@router.get("/admin/contents")
async def list_admin_contents(
    page: int = Query(1, ge=1),
    type_filter: ContentType | None = Query(None, alias="type"),
    visibility_filter: ContentVisibility | None = Query(None, alias="visibility"),
    moderation_status_filter: ModerationStatus | None = Query(None, alias="moderationStatus"),
    q: str | None = Query(None),
    sort: Literal["recent", "views", "chats"] = Query("recent"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminContentListResponse:
    """techspec.md §4-2, goal-prompt.md 2단계. `q`는 작품 이름 ILIKE 부분일치인데 이름이
    `contents`가 아니라 `character_version_details`/`story_version_details`에 있어
    `current_published_version_id`로 두 테이블을 outer join한다 — 발행 버전이 없는
    (초안만 있는) 작품은 두 테이블 어디에도 안 걸려 `q` 필터가 있을 땐 자연히 빠지지만
    (이름이 없으니 맞는 동작), `q` 없이 목록을 볼 땐 outer join이라 그대로 나온다."""
    filters = []
    if type_filter is not None:
        filters.append(Content.type == type_filter)
    if visibility_filter is not None:
        filters.append(Content.visibility == visibility_filter)
    if moderation_status_filter is not None:
        filters.append(Content.moderation_status == moderation_status_filter)

    base_query = select(Content)
    count_query = select(func.count()).select_from(Content)
    if q:
        base_query = base_query.outerjoin(
            CharacterVersionDetail,
            CharacterVersionDetail.content_version_id == Content.current_published_version_id,
        ).outerjoin(
            StoryVersionDetail,
            StoryVersionDetail.content_version_id == Content.current_published_version_id,
        )
        count_query = count_query.outerjoin(
            CharacterVersionDetail,
            CharacterVersionDetail.content_version_id == Content.current_published_version_id,
        ).outerjoin(
            StoryVersionDetail,
            StoryVersionDetail.content_version_id == Content.current_published_version_id,
        )
        filters.append(
            or_(
                CharacterVersionDetail.name.ilike(f"%{q}%"),
                StoryVersionDetail.name.ilike(f"%{q}%"),
            )
        )

    base_query = base_query.where(*filters)
    count_query = count_query.where(*filters)

    total_count = (await db.scalar(count_query)) or 0
    total_pages = -(-total_count // ADMIN_CONTENT_PAGE_SIZE) if total_count else 0

    # 동점 시 순서가 흔들리면 offset 페이지네이션에서 행이 중복되거나 누락된다
    # (`api/admin/dashboard.py`의 `popular` tie-breaker와 같은 이유) — 셋 다 `id`까지 더해
    # 완전히 결정적으로 만든다.
    order: tuple[Any, ...]
    if sort == "views":
        order = (Content.view_count.desc(), Content.created_at.desc(), Content.id)
    elif sort == "chats":
        order = (Content.chat_count.desc(), Content.created_at.desc(), Content.id)
    else:
        order = (Content.created_at.desc(), Content.id)

    contents = (
        await db.scalars(
            base_query.order_by(*order)
            .offset((page - 1) * ADMIN_CONTENT_PAGE_SIZE)
            .limit(ADMIN_CONTENT_PAGE_SIZE)
        )
    ).all()

    character_version_ids = [
        content.current_published_version_id
        for content in contents
        if content.type == ContentType.CHARACTER and content.current_published_version_id is not None
    ]
    story_version_ids = [
        content.current_published_version_id
        for content in contents
        if content.type == ContentType.STORY and content.current_published_version_id is not None
    ]
    names_by_version_id: dict[uuid.UUID, str] = {
        **(await _content_names_by_version_id(db, character_version_ids, ContentType.CHARACTER)),
        **(await _content_names_by_version_id(db, story_version_ids, ContentType.STORY)),
    }

    items = [
        AdminContentListItem(
            id=content.id,
            type=content.type,
            name=(
                names_by_version_id.get(content.current_published_version_id, "")
                if content.current_published_version_id
                else ""
            ),
            visibility=content.visibility,
            moderation_status=content.moderation_status,
            view_count=content.view_count,
            like_count=content.like_count,
            chat_count=content.chat_count,
            created_at=content.created_at,
            creator_user_id=content.creator_user_id,
        )
        for content in contents
    ]

    return AdminContentListResponse(
        items=items, page=page, total_pages=total_pages, total_count=total_count
    )


async def _content_version_history(db: AsyncSession, content: Content) -> list[AdminContentVersionItem]:
    """그 콘텐츠의 버전 전부를 벌크로. 초안(`published_at IS NULL`)이 맨 위에 오도록
    `version_number DESC NULLS FIRST`, 동점 시 `created_at DESC`, `id`까지 결정적으로."""
    versions = (
        await db.scalars(
            select(ContentVersion)
            .where(ContentVersion.content_id == content.id)
            .order_by(
                ContentVersion.version_number.desc().nulls_first(),
                ContentVersion.created_at.desc(),
                ContentVersion.id,
            )
        )
    ).all()

    names_by_version_id = await _content_names_by_version_id(
        db, [version.id for version in versions], content.type
    )

    return [
        AdminContentVersionItem(
            id=version.id,
            version_number=version.version_number,
            published_at=version.published_at,
            created_at=version.created_at,
            is_draft=version.published_at is None,
            name=names_by_version_id.get(version.id, ""),
        )
        for version in versions
    ]


async def _build_content_detail_response(db: AsyncSession, content: Content) -> AdminContentDetailResponse:
    """`GET /admin/contents/{id}`와 `POST .../action` 응답이 공유하는 조립 로직. 프롬프트
    추출·썸네일 로직은 `moderation/router.py`의 `_admin_report_content_detail()`을 그대로
    복제했다(파일 간 헬퍼 비공유 관례)."""
    name = ""
    thumbnail_asset_id: uuid.UUID | None = None
    detail_description = ""
    prompt: str | None = None

    version_id = content.current_published_version_id
    if version_id is not None:
        version = await db.get(ContentVersion, version_id)
        if version is not None:
            detail_description = version.detail_description

        if content.type == ContentType.CHARACTER:
            character_detail = await db.get(CharacterVersionDetail, version_id)
            if character_detail is not None:
                name = character_detail.name
                thumbnail_asset_id = character_detail.thumbnail_asset_id
                prompt = character_detail.character_prompt
        else:
            story_detail = await db.get(StoryVersionDetail, version_id)
            if story_detail is not None:
                name = story_detail.name
                thumbnail_asset_id = story_detail.thumbnail_asset_id
                prompt = (
                    story_detail.custom_prompt
                    if story_detail.prompt_template == StoryPromptTemplate.CUSTOM
                    else story_detail.setting_text
                )

    creator = await db.get(User, content.creator_user_id)
    assert creator is not None  # FK, 하드삭제 없음 (apps/api/CLAUDE.md 소프트삭제 규약)

    return AdminContentDetailResponse(
        id=content.id,
        type=content.type,
        name=name,
        visibility=content.visibility,
        moderation_status=content.moderation_status,
        view_count=content.view_count,
        like_count=content.like_count,
        chat_count=content.chat_count,
        created_at=content.created_at,
        creator=AdminContentCreator(id=creator.id, email=creator.email, nickname=creator.nickname),
        prompt=prompt,
        detail_description=detail_description,
        thumbnail_url=await _resolve_asset_url(db, thumbnail_asset_id),
        has_unpublished_changes=content.has_unpublished_changes,
        versions=await _content_version_history(db, content),
    )


@router.get("/admin/contents/{content_id}")
async def get_admin_content_detail(
    content_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminContentDetailResponse:
    content = await db.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    return await _build_content_detail_response(db, content)


@router.post("/admin/contents/{content_id}/action")
async def act_on_content(
    content_id: uuid.UUID,
    body: AdminContentActionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminContentDetailResponse:
    """신고 없이 내리는 직접 조치. `reject`는 "신고를 반려한다"는 뜻이라, 애초에 신고가
    없는 직접 조치에는 반려할 대상이 없다 — 400으로 거절한다(goal-prompt.md 2단계).

    사유 요구가 조치마다 다르다: `restrict`/`delete`는 아래에서 `Notification`을
    만들고 그 `reason_category` 컬럼이 NOT NULL이므로(goal-prompt.md §3-1, techspec
    §1-2) 신고 사유 5종 중 하나가 필수다(없으면 422). 반면 `lift-restriction`은
    `Notification`을 전혀 만들지 않으므로 신고 사유 카테고리를 강제할 근거가 없다 —
    관리자가 의미 없는 값을 고르게 될 뿐이다. 대신 T-10(위험 조치 확인 다이얼로그 +
    사유 필수)을 만족시키는 건 `admin_comment`(자유 텍스트, `admin_action_logs.reason_text`
    로 그대로 남는다) 쪽이라 이걸 필수로 바꿨다(비어 있으면 422)."""
    if body.action == ModerationActionType.REJECT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reject only makes sense for a report; a direct action has no report to reject",
        )

    content = await db.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    if (
        body.action == ModerationActionType.LIFT_RESTRICTION
        and content.moderation_status != ModerationStatus.RESTRICTED
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lift-restriction is only allowed on restricted content",
        )

    if body.action in (ModerationActionType.RESTRICT, ModerationActionType.DELETE):
        if body.reason_category is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="reason_category is required for restrict/delete",
            )
    elif body.action == ModerationActionType.LIFT_RESTRICTION:
        if not (body.admin_comment or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="admin_comment is required for lift-restriction",
            )

    action_row = ModerationAction(content_id=content.id, admin_id=admin_id, action=body.action)
    db.add(action_row)
    await db.flush()

    if body.action == ModerationActionType.RESTRICT:
        content.moderation_status = ModerationStatus.RESTRICTED
    elif body.action == ModerationActionType.DELETE:
        content.moderation_status = ModerationStatus.DELETED
    elif body.action == ModerationActionType.LIFT_RESTRICTION:
        content.moderation_status = ModerationStatus.NORMAL
        await upgrade_content_chat_rooms_to_latest_version(db, content)

    if body.action in (ModerationActionType.RESTRICT, ModerationActionType.DELETE):
        assert body.reason_category is not None  # 위에서 422로 이미 검증됨
        db.add(
            Notification(
                user_id=content.creator_user_id,
                content_id=content.id,
                action_id=action_row.id,
                reason_category=body.reason_category.value,
                admin_comment=body.admin_comment or "",
            )
        )

    action_type_by_moderation_action = {
        ModerationActionType.RESTRICT: "content-restrict",
        ModerationActionType.DELETE: "content-delete",
        ModerationActionType.LIFT_RESTRICTION: "content-lift",
    }
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type=action_type_by_moderation_action[body.action],
        target_content_id=content.id,
        reason_category=body.reason_category.value if body.reason_category is not None else None,
        reason_text=body.admin_comment or "",
    )

    await db.commit()

    return await _build_content_detail_response(db, content)
