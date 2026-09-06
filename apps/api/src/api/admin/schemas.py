import uuid
from datetime import date, datetime

from pydantic import EmailStr

from api.core.schema import CamelModel
from api.db.models.content import ContentType, ContentVisibility, ModerationStatus
from api.db.models.moderation import ModerationActionType, ReportReasonCategory, ReportStatus


class AdminLoginRequest(CamelModel):
    email: EmailStr
    password: str


class AdminMeResponse(CamelModel):
    id: uuid.UUID
    email: str


class AdminDashboardCountsResponse(CamelModel):
    total_users: int
    total_contents: int
    today_messages: int
    pending_reports: int


class AdminDashboardTrendPoint(CamelModel):
    date: date
    signups: int
    contents: int
    messages: int


class AdminDashboardPopularItem(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    chat_count: int
    view_count: int
    like_count: int


class AdminDashboardRecentUser(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str
    created_at: datetime


class AdminDashboardRecentContent(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    created_at: datetime


class AdminDashboardRecentReport(CamelModel):
    id: uuid.UUID
    reason_category: ReportReasonCategory
    content_id: uuid.UUID
    content_name: str
    status: ReportStatus
    created_at: datetime


class AdminDashboardActivityResponse(CamelModel):
    recent_users: list[AdminDashboardRecentUser]
    recent_contents: list[AdminDashboardRecentContent]
    recent_reports: list[AdminDashboardRecentReport]


class AdminContentListItem(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    visibility: ContentVisibility
    moderation_status: ModerationStatus
    view_count: int
    like_count: int
    chat_count: int
    created_at: datetime
    creator_user_id: uuid.UUID


class AdminContentListResponse(CamelModel):
    items: list[AdminContentListItem]
    page: int
    total_pages: int
    total_count: int


class AdminContentVersionItem(CamelModel):
    id: uuid.UUID
    version_number: int | None
    published_at: datetime | None
    created_at: datetime
    is_draft: bool
    name: str


class AdminContentCreator(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str


class AdminContentDetailResponse(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    visibility: ContentVisibility
    moderation_status: ModerationStatus
    view_count: int
    like_count: int
    chat_count: int
    created_at: datetime
    creator: AdminContentCreator
    prompt: str | None
    detail_description: str
    thumbnail_url: str | None
    has_unpublished_changes: bool
    versions: list[AdminContentVersionItem]


class AdminContentActionRequest(CamelModel):
    """`reason_category`는 `restrict`/`delete`에만 필수다(`api/admin/contents.py`의
    `act_on_content`가 조치별로 조건부 검증한다) — `lift-restriction`은 `Notification`을
    만들지 않아 신고 사유 카테고리를 강제할 근거가 없다."""

    action: ModerationActionType
    reason_category: ReportReasonCategory | None = None
    admin_comment: str | None = None
