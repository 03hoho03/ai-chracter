import uuid
from datetime import datetime

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.content import ContentType, ModerationStatus
from api.db.models.moderation import (
    AppealStatus,
    AppealTargetKind,
    ModerationActionType,
    ReportReasonCategory,
    ReportStatus,
)


class NotificationResponse(CamelModel):
    id: uuid.UUID
    type: str
    content_id: uuid.UUID
    action_id: uuid.UUID
    reason_category: str
    admin_comment: str
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
