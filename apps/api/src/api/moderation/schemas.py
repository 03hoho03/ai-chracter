import uuid
from datetime import date, datetime

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.content import ContentType, ModerationStatus
from api.db.models.moderation import (
    AppealStatus,
    AppealTargetKind,
    AppealVerdict,
    ModerationActionType,
    ReportReasonCategory,
    ReportStatus,
)


class NotificationResponse(CamelModel):
    id: uuid.UUID
    type: str
    content_id: uuid.UUID | None
    action_id: uuid.UUID | None
    # 조치 통지 3종(moderation-action/user-warned/user-suspended)은 계속 채우지만,
    # 공지·문의답변은 인용할 사유가 없어 nullable이다(tasks/techspec.md §3-3).
    reason_category: str | None
    admin_comment: str | None
    created_at: datetime
    read: bool


class AppealCreateRequest(CamelModel):
    target_kind: AppealTargetKind
    target_id: uuid.UUID
    reason_text: str = Field(min_length=1)


class AppealResponse(CamelModel):
    appeal_id: uuid.UUID
    status: AppealStatus


class AdminReportListItem(CamelModel):
    id: uuid.UUID
    reason_category: ReportReasonCategory
    content_id: uuid.UUID
    content_type: ContentType
    content_name: str
    status: ReportStatus
    created_at: datetime


class AdminReportListResponse(CamelModel):
    items: list[AdminReportListItem]
    page: int
    total_pages: int
    total_count: int


class AdminReportContentDetail(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_url: str | None
    detail_description: str
    prompt: str | None
    moderation_status: ModerationStatus


class AdminReportDetailResponse(CamelModel):
    id: uuid.UUID
    reason_category: ReportReasonCategory
    reporter_user_id: uuid.UUID
    status: ReportStatus
    created_at: datetime
    resolved_by_admin_id: uuid.UUID | None
    resolved_at: datetime | None
    content: AdminReportContentDetail


class ReportActionRequest(CamelModel):
    action: ModerationActionType
    admin_comment: str | None = None


class AdminAppealListItem(CamelModel):
    id: uuid.UUID
    target_kind: AppealTargetKind
    reason_text: str
    status: AppealStatus
    verdict: AppealVerdict | None
    created_at: datetime
    resolved_at: datetime | None


class AdminAppealListResponse(CamelModel):
    items: list[AdminAppealListItem]
    page: int
    total_pages: int
    total_count: int


class AppealResolveRequest(CamelModel):
    verdict: AppealVerdict


class UsageMetricsTrendPoint(CamelModel):
    date: date
    message_count: int


class UsageMetricsResponse(CamelModel):
    daily_average_per_user: float
    monthly_average_per_user: float
    trend: list[UsageMetricsTrendPoint]
