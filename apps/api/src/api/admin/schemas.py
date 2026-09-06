import uuid
from datetime import date, datetime
from typing import Literal

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


class AdminUserListItem(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str
    created_at: datetime
    suspended_at: datetime | None
    content_count: int
    chat_room_count: int


class AdminUserListResponse(CamelModel):
    items: list[AdminUserListItem]
    page: int
    total_pages: int
    total_count: int


class AdminUserReportItem(CamelModel):
    id: uuid.UUID
    reason_category: ReportReasonCategory
    status: ReportStatus
    content_id: uuid.UUID
    content_name: str
    created_at: datetime


class AdminUserActionLogItem(CamelModel):
    id: uuid.UUID
    action_type: str
    target_content_id: uuid.UUID | None
    content_name: str | None
    reason_category: str | None
    reason_text: str
    created_at: datetime


class AdminUserChatRoomItem(CamelModel):
    id: uuid.UUID
    content_id: uuid.UUID
    content_name: str
    name: str | None
    turn_count: int
    message_count: int
    last_message_at: datetime | None
    created_at: datetime


class AdminUserDetailResponse(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str
    bio: str | None
    created_at: datetime
    suspended_at: datetime | None
    email_verified_at: datetime | None
    signup_method: Literal["google", "email"]
    content_count: int
    # 지금 정지하면 새로 이용제한(restricted)될 작품 수 — `content_count`(전체 작품 수)와
    # 달리 이미 restricted/deleted인 작품은 제외한다. `api/admin/users.py`의
    # `suspend_user()`가 실제로 UPDATE하는 조건과 정확히 같아야 한다.
    restrictable_content_count: int
    chat_room_count: int
    message_count: int
    last_active_at: datetime | None
    reports: list[AdminUserReportItem]
    action_logs: list[AdminUserActionLogItem]
    chat_rooms: list[AdminUserChatRoomItem]


class AdminUserWarnRequest(CamelModel):
    reason_category: ReportReasonCategory
    admin_comment: str | None = None


class AdminUserSuspendRequest(CamelModel):
    reason_category: ReportReasonCategory
    admin_comment: str | None = None


class AdminUserSuspendResponse(CamelModel):
    restricted_content_count: int


class AdminUserUnsuspendRequest(CamelModel):
    """`reason_category`가 없다 — 이 액션은 `Notification`을 만들지 않는다(unsuspend는
    알림 발송 대상이 아니라는 판단, `api/admin/users.py`의 `unsuspend_user` docstring
    참고). 대신 `admin_comment`가 필수다(비어 있으면 422, 2단계 `lift-restriction`과 같은
    규칙)."""

    admin_comment: str | None = None
