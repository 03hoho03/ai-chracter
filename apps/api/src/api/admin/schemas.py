import enum
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import EmailStr, Field

from api.core.schema import CamelModel
from api.db.models.chat import ChatMessageRole
from api.db.models.content import ContentType, ContentVisibility, ModerationStatus
from api.db.models.moderation import ModerationActionType, ReportReasonCategory, ReportStatus
from api.legal.schemas import LegalDocumentKind


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


class AdminLegalDraftItem(CamelModel):
    body_markdown: str
    created_at: datetime


class AdminLegalPublishedItem(CamelModel):
    version: str
    body_markdown: str
    published_at: datetime
    requires_reconsent: bool


class AdminLegalDocumentResponse(CamelModel):
    kind: LegalDocumentKind
    draft: AdminLegalDraftItem | None
    published: AdminLegalPublishedItem | None


class AdminLegalDraftUpsertRequest(CamelModel):
    body_markdown: str


class AdminLegalPublishRequest(CamelModel):
    """`version`은 zero-padded ISO 날짜(`YYYY-MM-DD`)로 강제한다 — `_reconsent_required`
    (`api/auth/router.py`)가 이 값을 문자열째로 비교해 재동의 필요 여부를 판정하고, 그
    비교가 시간순과 일치하려면 모든 버전이 같은 자릿수로 zero-padding돼 있어야 한다
    (그렇지 않으면 예: `"2026-9-6" < "2026-10-01"`이 문자열 비교로는 `False`가 되어
    재동의가 영원히 뜨지 않는다). 달력상 유효한 날짜인지(`2026-13-45` 등)는 검사하지
    않는다 — 자릿수 고정 포맷만 지키면 무효한 날짜라도 문자열 비교의 시간순 일치라는
    전제 자체는 깨지지 않으므로, 이 정규식만으로 방어 목적은 충분하다고 판단했다."""

    version: str = Field(min_length=1, pattern=r"^\d{4}-\d{2}-\d{2}$")
    requires_reconsent: bool


class AdminLegalVersionItem(CamelModel):
    version: str
    published_at: datetime
    requires_reconsent: bool


class AdminLegalVersionsResponse(CamelModel):
    items: list[AdminLegalVersionItem]


class ChatViewReasonCategory(str, enum.Enum):
    """techspec.md §4-5(TS-10). 기존 `ReportReasonCategory`(adult/copyright/hate/spam/other)와
    다른 전용 enum이다 — 채팅 열람 사유는 신고 사유와 결이 달라 재사용하지 않는다."""

    REPORT_INVESTIGATION = "report-investigation"
    APPEAL_REVIEW = "appeal-review"
    LEGAL_REQUEST = "legal-request"
    OTHER = "other"


class AdminChatRoomViewRequest(CamelModel):
    """`reason_text`는 공백만이면 422 — `admin/chat_view.py`가 `unsuspend_user`의
    `admin_comment` 검증 선례를 그대로 따라 수동으로 확인한다(둘 다 필수라 여기선
    optional로 두지 않는다)."""

    reason_category: ChatViewReasonCategory
    reason_text: str


class AdminChatMessageItem(CamelModel):
    id: uuid.UUID
    role: ChatMessageRole
    content: str
    created_at: datetime


class AdminChatMessagesResponse(CamelModel):
    """`POST .../view`(열람 시작)와 `GET .../messages`(더보기) 공용 응답 모양 — 둘 다
    같은 페이지+커서 구조다. 커서는 오파크 문자열이 아니라 `beforeCreatedAt`/`beforeId`
    평문 페어로 내려준다(techspec §4-5) — 더 불러올 게 없으면 둘 다 null."""

    items: list[AdminChatMessageItem]
    before_created_at: datetime | None
    before_id: uuid.UUID | None
