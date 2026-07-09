import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.admin.dependencies import get_current_admin_id
from api.core.s3 import generate_presigned_get_url
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatRoom
from api.db.models.content import Content, ContentType, ContentVersion, ModerationStatus
from api.db.models.media import Asset
from api.db.models.moderation import (
    Appeal,
    AppealStatus,
    AppealTargetKind,
    AppealVerdict,
    ModerationAction,
    ModerationActionType,
    Notification,
    Report,
    ReportStatus,
)
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail
from api.db.session import get_db_session
from api.moderation.schemas import (
    AdminAppealListItem,
    AdminAppealListResponse,
    AdminReportContentDetail,
    AdminReportDetailResponse,
    AdminReportListItem,
    AdminReportListResponse,
    AppealCreateRequest,
    AppealResolveRequest,
    AppealResponse,
    NotificationResponse,
    ReportActionRequest,
)
from api.session.dependencies import get_current_user_id

router = APIRouter(tags=["moderation"])

ADMIN_REPORT_PAGE_SIZE = 20
ADMIN_APPEAL_PAGE_SIZE = 20


def _to_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        type=notification.type,
        content_id=notification.content_id,
        action_id=notification.action_id,
        reason_category=notification.reason_category,
        admin_comment=notification.admin_comment,
        created_at=notification.created_at,
        read=notification.read,
    )


@router.get("/notifications")
async def list_my_notifications(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[NotificationResponse]:
    notifications = (
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
        )
    ).all()
    return [_to_response(notification) for notification in notifications]


@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationResponse:
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not the notification owner"
        )

    notification.read = True
    await db.commit()

    return _to_response(notification)


@router.post("/appeals", status_code=status.HTTP_201_CREATED)
async def create_appeal(
    body: AppealCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> AppealResponse:
    """techspec-backend-admin-moderation.md §1/§3. `target_kind='publish-rejection'`일 때
    `target_id`는 별도 발행거부 이력 엔티티 없이 대상 contentId 그대로다."""
    appeal = Appeal(
        user_id=user_id,
        target_kind=body.target_kind,
        target_id=body.target_id,
        reason_text=body.reason_text,
        status=AppealStatus.PENDING,
    )
    db.add(appeal)
    await db.commit()

    return AppealResponse(appeal_id=appeal.id, status=appeal.status)


async def _resolve_asset_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """Same shape as content/router.py's private helper of the same name — not imported
    across router files by this codebase's convention (apps/api/CLAUDE.md)."""
    if asset_id is None:
        return None
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return None
    return await run_in_threadpool(generate_presigned_get_url, asset.storage_key)


async def _admin_report_list_items(
    db: AsyncSession, reports: Sequence[Report]
) -> list[AdminReportListItem]:
    """Bulk-fetches each report's target content name, split by type (character/story
    details live in separate tables) — same query+dict-matching shape as `list_my_drafts`
    (content/router.py, US-025) rather than a per-row correlated query."""
    contents = {
        content.id: content
        for content in (
            await db.scalars(
                select(Content).where(Content.id.in_(report.content_id for report in reports))
            )
        ).all()
    }

    character_version_ids = [
        content.current_published_version_id
        for content in contents.values()
        if content.type == ContentType.CHARACTER and content.current_published_version_id is not None
    ]
    story_version_ids = [
        content.current_published_version_id
        for content in contents.values()
        if content.type == ContentType.STORY and content.current_published_version_id is not None
    ]
    names_by_version_id: dict[uuid.UUID, str] = {}
    if character_version_ids:
        for detail in (
            await db.scalars(
                select(CharacterVersionDetail).where(
                    CharacterVersionDetail.content_version_id.in_(character_version_ids)
                )
            )
        ).all():
            names_by_version_id[detail.content_version_id] = detail.name
    if story_version_ids:
        for story_detail in (
            await db.scalars(
                select(StoryVersionDetail).where(
                    StoryVersionDetail.content_version_id.in_(story_version_ids)
                )
            )
        ).all():
            names_by_version_id[story_detail.content_version_id] = story_detail.name

    items: list[AdminReportListItem] = []
    for report in reports:
        content = contents[report.content_id]
        version_id = content.current_published_version_id
        items.append(
            AdminReportListItem(
                id=report.id,
                reason_category=report.reason_category,
                content_id=report.content_id,
                content_type=content.type,
                content_name=names_by_version_id.get(version_id, "") if version_id else "",
                status=report.status,
                created_at=report.created_at,
            )
        )
    return items


@router.get("/admin/reports")
async def list_admin_reports(
    page: int = Query(1, ge=1),
    status_filter: ReportStatus | None = Query(None, alias="status"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminReportListResponse:
    """techspec-backend-admin-moderation.md §1, techspec-admin.md §1 — traditional
    (offset) pagination, unlike the cursor pagination `GET /contents` uses, since
    admin review work benefits from jumping to a specific page number."""
    filters = [Report.status == status_filter] if status_filter is not None else []

    total_count = await db.scalar(select(func.count()).select_from(Report).where(*filters))
    total_count = total_count or 0
    total_pages = -(-total_count // ADMIN_REPORT_PAGE_SIZE) if total_count else 0

    reports = (
        await db.scalars(
            select(Report)
            .where(*filters)
            .order_by(Report.created_at.desc())
            .offset((page - 1) * ADMIN_REPORT_PAGE_SIZE)
            .limit(ADMIN_REPORT_PAGE_SIZE)
        )
    ).all()

    return AdminReportListResponse(
        items=await _admin_report_list_items(db, reports),
        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )


async def _admin_report_content_detail(db: AsyncSession, content: Content) -> AdminReportContentDetail:
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

    return AdminReportContentDetail(
        id=content.id,
        type=content.type,
        name=name,
        thumbnail_url=await _resolve_asset_url(db, thumbnail_asset_id),
        detail_description=detail_description,
        prompt=prompt,
        moderation_status=content.moderation_status,
    )


@router.get("/admin/reports/{report_id}")
async def get_admin_report_detail(
    report_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminReportDetailResponse:
    """techspec-backend-admin-moderation.md §1. `reports.content_id` is a plain FK to an
    existing `contents` row (rows are never hard-deleted, only moderation_status-flagged),
    so the target content is always found."""
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    content = await db.get(Content, report.content_id)
    assert content is not None

    return AdminReportDetailResponse(
        id=report.id,
        reason_category=report.reason_category,
        reporter_user_id=report.reporter_user_id,
        status=report.status,
        created_at=report.created_at,
        resolved_by_admin_id=report.resolved_by_admin_id,
        resolved_at=report.resolved_at,
        content=await _admin_report_content_detail(db, content),
    )


async def upgrade_content_chat_rooms_to_latest_version(db: AsyncSession, content: Content) -> None:
    """techspec-content-versioning.md §4. Sync bulk-migrates every chat room referencing
    this content to its latest published version, flipping `version_auto_upgraded` so the
    FE can show the upgrade banner (`chat/router.py`'s `acknowledge-version-upgrade`
    consumes that flag) — all within the caller's own transaction, no background job.
    Exported (not prefixed `_`) since `POST /admin/appeals/{id}/resolve` (US-123) reuses
    this exact path for `verdict='accepted'` on a `target_kind='moderation-action'` appeal."""
    if content.current_published_version_id is None:
        return
    await db.execute(
        update(ChatRoom)
        .where(ChatRoom.content_id == content.id)
        .values(content_version_id=content.current_published_version_id, version_auto_upgraded=True)
    )


@router.post("/admin/reports/{report_id}/action")
async def act_on_report(
    report_id: uuid.UUID,
    body: ReportActionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminReportDetailResponse:
    """techspec-backend-admin-moderation.md §2."""
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    content = await db.get(Content, report.content_id)
    assert content is not None

    if (
        body.action == ModerationActionType.LIFT_RESTRICTION
        and content.moderation_status != ModerationStatus.RESTRICTED
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lift-restriction is only allowed on restricted content",
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
        db.add(
            Notification(
                user_id=content.creator_user_id,
                content_id=content.id,
                action_id=action_row.id,
                reason_category=report.reason_category.value,
                admin_comment=body.admin_comment or "",
            )
        )

    report.status = (
        ReportStatus.REJECTED if body.action == ModerationActionType.REJECT else ReportStatus.RESOLVED
    )
    report.resolved_by_admin_id = admin_id
    report.resolved_at = datetime.now(UTC)

    await db.commit()

    return AdminReportDetailResponse(
        id=report.id,
        reason_category=report.reason_category,
        reporter_user_id=report.reporter_user_id,
        status=report.status,
        created_at=report.created_at,
        resolved_by_admin_id=report.resolved_by_admin_id,
        resolved_at=report.resolved_at,
        content=await _admin_report_content_detail(db, content),
    )


def _to_admin_appeal_list_item(appeal: Appeal) -> AdminAppealListItem:
    return AdminAppealListItem(
        id=appeal.id,
        target_kind=appeal.target_kind,
        reason_text=appeal.reason_text,
        status=appeal.status,
        verdict=appeal.verdict,
        created_at=appeal.created_at,
        resolved_at=appeal.resolved_at,
    )


@router.get("/admin/appeals")
async def list_admin_appeals(
    page: int = Query(1, ge=1),
    status_filter: AppealStatus | None = Query(None, alias="status"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminAppealListResponse:
    """techspec-backend-admin-moderation.md §1/§3. No separate detail endpoint — unlike
    reports, an appeal's full reason text lives on the same row, so the list item already
    carries everything the review screen needs (techspec-admin.md §2 only defines
    useAppealListQuery/useResolveAppealMutation, no detail query)."""
    filters = [Appeal.status == status_filter] if status_filter is not None else []

    total_count = await db.scalar(select(func.count()).select_from(Appeal).where(*filters))
    total_count = total_count or 0
    total_pages = -(-total_count // ADMIN_APPEAL_PAGE_SIZE) if total_count else 0

    appeals = (
        await db.scalars(
            select(Appeal)
            .where(*filters)
            .order_by(Appeal.created_at.desc())
            .offset((page - 1) * ADMIN_APPEAL_PAGE_SIZE)
            .limit(ADMIN_APPEAL_PAGE_SIZE)
        )
    ).all()

    return AdminAppealListResponse(
        items=[_to_admin_appeal_list_item(appeal) for appeal in appeals],
        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )


@router.post("/admin/appeals/{appeal_id}/resolve")
async def resolve_appeal(
    appeal_id: uuid.UUID,
    body: AppealResolveRequest,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminAppealListItem:
    """techspec-backend-admin-moderation.md §3. `accepted` on a `moderation-action` appeal
    reuses the exact lift-restriction path (`upgrade_content_chat_rooms_to_latest_version`)
    that `act_on_report` exports for this purpose. `publish-rejection` appeals have no
    persisted content-side state to revert (AC4), so `accepted` there is a no-op beyond the
    appeal's own status/verdict."""
    appeal = await db.get(Appeal, appeal_id)
    if appeal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found")
    if appeal.status != AppealStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Appeal already resolved"
        )

    if body.verdict == AppealVerdict.ACCEPTED and appeal.target_kind == AppealTargetKind.MODERATION_ACTION:
        action = await db.get(ModerationAction, appeal.target_id)
        if action is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found"
            )
        content = await db.get(Content, action.content_id)
        assert content is not None

        content.moderation_status = ModerationStatus.NORMAL
        await upgrade_content_chat_rooms_to_latest_version(db, content)

    appeal.status = AppealStatus.RESOLVED
    appeal.verdict = body.verdict
    appeal.resolved_at = datetime.now(UTC)

    await db.commit()

    return _to_admin_appeal_list_item(appeal)
