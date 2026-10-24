import enum
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, EmailStr, Field

from api.admin.prompt_semver import SectionChange, SemverLevel
from api.chat.prompt_builder import PromptLane
from api.chat.prompt_routing import RouteSource, SkipReason
from api.chat.prompt_stages import PromptStage, RoutingLane, StageKind
from api.core.schema import CamelModel
from api.db.models.chat import ChatMessageRole
from api.db.models.content import ContentType, ContentVisibility, DerivativeNovelsChoice, ModerationStatus
from api.db.models.creator_payout import (
    BankCode,
    CreatorPayoutApplicationStatus,
    CreatorPayoutConfirmationKind,
    CreatorPayoutStatus,
)
from api.db.models.moderation import (
    AdminActionType,
    ModerationActionType,
    ReportReasonCategory,
    ReportStatus,
)
from api.db.models.novel import NovelPublicationModerationStatus, NovelPublicationVisibility
from api.db.models.payment import PaymentStatus
from api.legal.schemas import LegalConsentUnit, LegalDocumentKind
from api.llm.call_policy import BackendId, LLMCallSite
from api.llm.chat_models import ChatRoomModelId, PromptSetModelId


class AdminLoginRequest(CamelModel):
    email: EmailStr
    password: str


class AdminMeResponse(CamelModel):
    id: uuid.UUID
    email: str
    # 노벨 공개 정책 스위치(`novel_public_policy_v2_enabled`)가 켜져 있는가. 노벨 이용제한·작품 조치의 확인 문구(산 사람에게
    # 환급되는가)가 이 값으로 갈린다 — 조치 화면마다 받는 응답이 달라, 운영 화면이 늘 읽는 이 응답에 둔다.
    novel_public_policy_v2_enabled: bool


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


class AdminDashboardCohortWeekPoint(CamelModel):
    week_offset: int
    retained_users: int
    retention_rate: float


class AdminDashboardCohort(CamelModel):
    cohort_week_start: date
    cohort_size: int
    weeks: list[AdminDashboardCohortWeekPoint]


class AdminDashboardGrowthResponse(CamelModel):
    """가입자 성장 지표. 새 수집 없이 기존 DB만 재구성한다.

    - `activation_rate`: 가입자→첫 대화 도달률(분모 `total_users`, 분자 `activated_users`).
    - `publish_rate`: 제작자→발행 완료율(분모 `total_users`, 분자
      `creators_with_published_content`).
    - `withdrawn_rate`/`creator_rate`는 근사가 아닌 정확한 수치.
    - `cohort_retention`: **근사다.** 로그인 이벤트가 DB에 없어(`last_login`류 필드 0건)
      '재방문'을 '가입 후 그 주에 `ChatMessage.role == USER`를 보냈는가'로 대체한다 —
      정확한 재방문율로 읽지 말 것.
    """

    total_users: int
    activated_users: int
    activation_rate: float
    creators_with_published_content: int
    publish_rate: float
    total_signups: int
    withdrawn_users: int
    withdrawn_rate: float
    users_with_content: int
    creator_rate: float
    cohort_retention: list[AdminDashboardCohort]


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


class AdminContentImage(CamelModel):
    """발행본 그림 하나. `image_url` 은 원본(블러본이 아니다), `thumbnail_url` 은 목록에 그릴 축소본이다."""

    label: str
    image_url: str
    thumbnail_url: str


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
    published_images: list[AdminContentImage]
    has_unpublished_changes: bool
    versions: list[AdminContentVersionItem]
    # 이 작품을 제한·삭제하면서 파생 소설은 판매만 멈추고 산 사람의 열람을 남겼는가(정상 작품이면 의미 없다).
    novel_buyers_kept: bool


class AdminContentActionRequest(CamelModel):
    """`reason_category`는 `restrict`/`delete`에만 필수다(`api/admin/contents.py`의
    `act_on_content`가 조치별로 조건부 검증한다) — `lift-restriction`은 `Notification`을
    만들지 않아 신고 사유 카테고리를 강제할 근거가 없다."""

    action: ModerationActionType
    reason_category: ReportReasonCategory | None = None
    admin_comment: str | None = None
    # 이용제한·삭제 때 그 원작의 파생 소설을 어떻게 하나(`DerivativeNovelsChoice`). 빼면 `close`(지금 동작), 다른 조치에서는
    # 보지 않는다.
    derivative_novels: DerivativeNovelsChoice | None = None


class AdminHomeCurationContent(CamelModel):
    id: uuid.UUID
    name: str
    thumbnail_url: str | None
    visibility: ContentVisibility
    moderation_status: ModerationStatus


class AdminHomeCurationSlot(CamelModel):
    """`is_listed` 는 지정 작품이 지금 홈에 보이는가다 — 공개 목록과 같은 판정이라, 지정 뒤 이용제한·비공개가
    되면 지정은 남은 채 거짓이 된다. 지정이 없으면 거짓이다."""

    type: ContentType
    content: AdminHomeCurationContent | None
    is_listed: bool


class AdminHomeCurationListResponse(CamelModel):
    items: list[AdminHomeCurationSlot]


class AdminHomeCurationSetRequest(CamelModel):
    """코멘트는 선택이다 — 되돌릴 수 있고 작가에게 불이익이 없는 조작이라 사유를 강제하지 않는다. 감사 로그에
    누가·언제는 남는다."""

    content_id: uuid.UUID
    admin_comment: str | None = None


class AdminHomeCurationClearRequest(CamelModel):
    admin_comment: str | None = None


class AdminHomeNovelCurationNovel(CamelModel):
    """홈 노벨 자리에 걸린 노벨. `title` 은 공개본 제목(비어 있으면 원작 제목), `cover_url` 은 원작 썸네일이다."""

    id: uuid.UUID
    title: str
    source_title: str
    cover_url: str | None
    publisher_nickname: str | None
    visibility: NovelPublicationVisibility
    moderation_status: NovelPublicationModerationStatus


class AdminHomeNovelCurationSlot(CamelModel):
    """`is_listed` 는 걸린 노벨이 지금 홈에 보이는가다 — 노벨 목록과 같은 판정이라, 건 뒤 거둬지거나 이용제한되면 지정은
    남은 채 거짓이 된다. 비어 있는 자리면 `novel` 이 비고 거짓이다."""

    position: int
    novel: AdminHomeNovelCurationNovel | None
    is_listed: bool


class AdminHomeNovelCurationListResponse(CamelModel):
    items: list[AdminHomeNovelCurationSlot]


class AdminHomeNovelCurationSetRequest(CamelModel):
    """코멘트는 선택이다(작품 홈 지정과 같은 이유 — 되돌릴 수 있고 게시자에게 불이익이 없다)."""

    novel_id: uuid.UUID
    admin_comment: str | None = None


class AdminUserListItem(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str
    created_at: datetime
    suspended_at: datetime | None
    beta_joined_at: datetime | None
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
    target_comment_id: uuid.UUID | None
    id: uuid.UUID
    action_type: AdminActionType
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
    signup_method: Literal["kakao", "google", "email"]
    content_count: int
    # 지금 정지하면 새로 이용제한(restricted)될 작품 수 — `content_count`(전체 작품 수)와
    # 달리 이미 restricted/deleted인 작품은 제외한다. `api/admin/users.py`의
    # `suspend_user()`가 실제로 UPDATE하는 조건과 정확히 같아야 한다.
    restrictable_content_count: int
    # 지금 정지를 해제하면 정상으로 돌아올 작품 수 — 정지가 내렸고 그 뒤 작품 단위 조치가 없었던 작품.
    # `api/admin/users.py`의 `unsuspend_user()`가 실제로 UPDATE하는 조건과 정확히 같아야 한다.
    restorable_content_count: int
    # 레이트리밋 면제 플래그는 상세에만 실린다(목록·필터 없음).
    # 값을 바꾸는 유일한 경로는 `POST /admin/users/{id}/rate-limit-exempt`다.
    rate_limit_exempt: bool
    # 베타 참가자로 처음 지정된 시각(NULL 이면 참가자 아님). 목록 항목에도 실린다.
    # 값을 바꾸는 유일한 경로는 `POST /admin/users/{id}/beta`다.
    beta_joined_at: datetime | None
    # 소설화 허용 행이 생긴 시각(NULL 이면 허용 행 없음). 상세에만 실린다. 허용 행만 보여 주는 값이라 전역 스위치와
    # env 명단 때문에 실제로는 막혀 있을 수 있다. 값을 바꾸는 유일한 경로는 `POST /admin/users/{id}/novelize-grant`다.
    novelize_granted_at: datetime | None
    # 소설 상위 모델 허용 행이 생긴 시각(NULL 이면 허용 행 없음). 소설화 허용 시각과 같은 성질이고(기능 스위치·env 명단
    # 때문에 실제로는 막혀 있을 수 있다), 바꾸는 경로는 `POST /admin/users/{id}/novelize-premium-models-grant` 다. 채팅 상위
    # 모델은 스위치 하나로 열려 허용 행을 보지 않으므로 칸이 없다. 기본값은 이 필드를 모르는 생성 타입과의 호환용이다.
    novelize_premium_models_granted_at: datetime | None = None
    # 잔액도 상세에만 실린다(목록·필터 없음). 변동 **이력**은 이
    # 응답에 넣지 않고 `GET /admin/users/{id}/clover-ledger`가 따로 준다 — 상세 응답은 이미
    # reports·action_logs·chat_rooms 셋을 싣고 있어 네 번째 목록을 더하면 한 요청이 무거워진다.
    clover_balance: int
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


class AdminUserUnsuspendResponse(CamelModel):
    restored_content_count: int


class AdminUserUnsuspendRequest(CamelModel):
    """`reason_category`가 없다 — 이 액션은 `Notification`을 만들지 않는다(unsuspend는
    알림 발송 대상이 아니라는 판단, `api/admin/users.py`의 `unsuspend_user` docstring
    참고). 대신 `admin_comment`가 필수다(비어 있으면 422, 콘텐츠 직접 조치 `lift-restriction`과 같은
    규칙)."""

    admin_comment: str | None = None


class AdminUserRateLimitExemptRequest(CamelModel):
    """켜기/끄기를 `exempt` 한 필드로 받는 토글이다(경로를 둘로
    쪼개지 않는다). `reason_category`가 없는 이유와 `admin_comment`가 필수인 이유는
    `AdminUserUnsuspendRequest`와 같다 — `Notification`을 만들지 않아 사유를 인용할 자리가
    없고, 대신 "왜 면제했나"가 감사 로그에 남아야 한다(비어 있으면 422)."""

    exempt: bool
    admin_comment: str | None = None


class AdminUserBetaRequest(CamelModel):
    """베타 참가자 지정/해제를 `beta` 한 필드로 받는 토글이다. `admin_comment`가 필수인 이유는
    `AdminUserRateLimitExemptRequest`와 같다(비어 있으면 422)."""

    beta: bool
    admin_comment: str | None = None


class AdminUserFeatureGrantRequest(CamelModel):
    """기능 허용/회수를 `granted` 한 필드로 받는 토글이다. `admin_comment`가 필수인 이유는
    `AdminUserRateLimitExemptRequest`와 같다(비어 있으면 422). 소설 상위 모델 허용 경로가 쓴다."""

    granted: bool
    admin_comment: str | None = None


class AdminUserNovelizeGrantRequest(AdminUserFeatureGrantRequest):
    """소설화 허용 경로의 요청. 모양은 `AdminUserFeatureGrantRequest` 와 같고, 이 이름은 그 경로의 생성 타입 이름을 지키려고
    남긴다."""


class AdminUserCloverRequest(CamelModel):
    """지급과 회수를 **부호 있는 한 필드**로 받는다(경로를 둘로
    쪼개지 않는다. `AdminUserRateLimitExemptRequest`가 켜기/끄기를 한 필드로 받는 것과 같은
    관례다). `admin_comment`가 필수인 이유도 같다 — `Notification`을 만들지 않아 사유를
    인용할 자리가 없고 대신 "왜 줬나"가 감사 로그에 남아야 한다.

    `±100,000` 상한의 근거(`images/schemas.py`의 `count` 상한이 "왜 2인가"를 적은 관례):
    현행 단가(기본 모델 채팅 1턴 10) 기준 100,000클로버 = 채팅 10,000턴이다.
    운영자가 한 번에 줄 만한 어떤 보상보다도 크고, **자릿수를 잘못 눌렀을 때 걸리는 그물**이
    이 상한의 목적이다. 더 큰 금액이 필요하면 여러 번 나눠 주면 되고 그 편이 감사 로그에도
    낫다.

    🔴 `idempotency_key`는 **클라이언트가 요청마다 새로 만든다**.
    미션 청구처럼 서버가 `(user, 미션)`으로 파생할 수 없다 — 같은 어드민이 같은 유저에게 같은 금액을
    **의도적으로 두 번** 줄 수 있어야 하기 때문이다. 막으려는 것은 "두 번 주는 것"이 아니라
    **한 번 누른 것이 두 번 도착하는 것**(더블클릭·네트워크 재시도)이다.
    """

    amount: int = Field(ge=-100_000, le=100_000)
    admin_comment: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=64)


class AdminCloverLedgerItem(CamelModel):
    id: uuid.UUID
    # 부호 있는 증감. 지급은 양수, 소모·회수·소멸은 음수(`db/models/clover.py`).
    amount: int
    balance_after: int
    # `db/models/clover.py`의 `kind` — Text라 값이 늘어도 마이그레이션이 없다. 그래서 여기도
    # `Literal`로 좁히지 않는다(좁히면 BE가 값을 늘릴 때마다 FE 코드젠이 깨진다).
    kind: str
    created_at: datetime


class AdminCloverLedgerListResponse(CamelModel):
    items: list[AdminCloverLedgerItem]
    page: int
    total_pages: int
    total_count: int


class AdminLegalDraftItem(CamelModel):
    body_markdown: str
    change_notice_markdown: str | None
    created_at: datetime


class AdminLegalPublishedItem(CamelModel):
    """`reconsent_scopes` 는 이 판이 다시 받은 동의 단위다."""

    version: str
    body_markdown: str
    change_notice_markdown: str | None
    published_at: datetime
    effective_at: datetime
    reconsent_scopes: list[LegalConsentUnit]


class AdminLegalDocumentResponse(CamelModel):
    """`published` 는 지금 시행 중인 현행판, `upcoming` 은 시행 시각이 아직 오지 않은 예약 판이다."""

    kind: LegalDocumentKind
    draft: AdminLegalDraftItem | None
    published: AdminLegalPublishedItem | None
    upcoming: AdminLegalPublishedItem | None


class AdminLegalDraftUpsertRequest(CamelModel):
    """`change_notice_markdown` 을 아예 보내지 않으면 초안의 변경 안내를 그대로 둔다 — 안내 칸을 모르는 이전 어드민 화면이
    본문만 저장해도 안내가 지워지지 않게 한다. null 을 보내면 비운다."""

    body_markdown: str
    change_notice_markdown: str | None = None


class AdminLegalPublishRequest(CamelModel):
    """`version` 은 날짜(`YYYY-MM-DD`)이고, 같은 날 다시 게시하면 순번 접미사를 붙인다(첫 판은 접미사 없음, 둘째부터
    `.2`, `.3`, … `.10`). 접미사는 `.0`·`.1`·앞자리 0 을 받지 않아 한 판에 이름이 하나뿐이다. 판의 앞뒤는 버전 문자열이
    아니라 시행 시각으로 정하므로(`api/legal/documents.py`) 이 형식은 사람이 읽는 이름을 고르게 할 뿐이다. 달력상 유효한
    날짜인지는 검사하지 않는다.

    `effective_at` 은 시행 시각이다. 비우면 게시 시각과 같아 즉시 현행이 되고, 미래면 그 시각까지 시행 예정 판으로
    남는다. 시간대가 없는 값은 받지 않는다(서버 시계와 비교할 수 없다).

    재동의 범위는 `reconsent_scopes` 로 받는다. 약관은 `terms`, 처리방침은 `collection`·`transfer` 를 고를 수 있고 정책
    문서는 고를 수 없다. 비우면 재동의 없는 게시다.

    모르는 칸은 422 로 거부한다. 동의 단위를 모르던 이전 어드민 화면은 재동의를 불리언 `requiresReconsent` 로 보냈는데,
    그 칸을 조용히 버리면 재동의를 걸려던 게시가 재동의 없는 게시로 나간다."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, pattern=r"^\d{4}-\d{2}-\d{2}(\.([2-9]|[1-9]\d+))?$")
    reconsent_scopes: list[LegalConsentUnit] = Field(default_factory=list)
    effective_at: AwareDatetime | None = None


# 이력 표의 판 상태. 현행 = 지금 시행 중, 예정 = 시행 시각 전, 철회 = 시행 전에 거둔 판, 지난 판 = 다음 판이 시행돼 밀려난 판.
AdminLegalVersionState = Literal["current", "scheduled", "withdrawn", "past"]


class AdminLegalVersionItem(CamelModel):
    version: str
    published_at: datetime
    effective_at: datetime
    reconsent_scopes: list[LegalConsentUnit]
    change_notice_markdown: str | None
    state: AdminLegalVersionState


class AdminLegalVersionsResponse(CamelModel):
    items: list[AdminLegalVersionItem]


class ChatViewReasonCategory(str, enum.Enum):
    """기존 `ReportReasonCategory`(작품·댓글 신고 사유)와
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
    평문 페어로 내려준다 — 더 불러올 게 없으면 둘 다 null."""

    items: list[AdminChatMessageItem]
    before_created_at: datetime | None
    before_id: uuid.UUID | None


class AdminChatMemorySummary(CamelModel):
    text: str
    source: Literal["auto", "user"]


class AdminChatRoomViewResponse(AdminChatMessagesResponse):
    """열람 시작 응답 — 더보기와 같은 페이지에 방 기억(사용자 노트·현재 요약)을 더한다. 기억은 사유를
    남기는 이 열람에서만 내려 준다: 공용 모델에 두면 로그를 남기지 않는 더보기도 노트를 돌려준다.
    `memory_summary`는 첫 요약 전이면 null이다."""

    memory_note: str
    memory_summary: AdminChatMemorySummary | None


class AdminPromptSetSummary(CamelModel):
    """이력 목록은 메타만. 섹션 전문은
    `GET /admin/prompt-sets/{id}`로 뺀다."""

    id: uuid.UUID
    version: str | None
    status: str
    note: str
    created_at: datetime
    published_at: datetime | None
    lane: PromptLane
    model: PromptSetModelId
    is_active: bool
    # 체인 판(`1.2.0` 꼴). 판이 없는 게시본(판을 매기기 전의 게시, 옛 이미지의 게시)과 초안은 null 이다 — 화면은 정수 `version` 으로
    # 옛 판을 보여 준다.
    semver: str | None = None


class AdminPromptSetListResponse(CamelModel):
    items: list[AdminPromptSetSummary]


class AdminPromptLabels(CamelModel):
    user_label: str
    story_assistant_label: str
    story_example_label: str
    character_assistant_label: str


class AdminPromptSectionItem(CamelModel):
    channel: str
    scope: str
    slot: str
    variant: str
    body: str
    conditional: bool
    order: int


class AdminPromptSectionSemver(CamelModel):
    """섹션 하나의 판. `channel` 은 채널 이름이거나 화자 라벨 넷 묶음 `speaker_labels` 다. `level` 은 그 게시에서 바뀌어 올린
    단계이고, 바뀌지 않아 기준판의 번호를 물려받았거나 체인의 시작판이면 null 이다."""

    channel: str
    semver: str
    level: SemverLevel | None


class AdminPromptSetDetailResponse(CamelModel):
    """`GET /admin/prompt-sets/{id}` — 특정 버전의 섹션 전문. 게시 응답도 이 꼴이다.

    `semver`·`section_semvers` 는 판이 없는 세트면 null·빈 목록이다. `removed_sections` 는 게시 응답에서만 채운다(기준판에
    있었는데 이번 게시에 없는 섹션) — 상세 조회는 기준판과 다시 견주지 않아 늘 빈 목록이다."""

    id: uuid.UUID
    version: str | None
    status: str
    lane: PromptLane
    model: PromptSetModelId
    note: str
    created_at: datetime
    published_at: datetime | None
    labels: AdminPromptLabels
    sections: list[AdminPromptSectionItem]
    semver: str | None = None
    section_semvers: list[AdminPromptSectionSemver] = Field(default_factory=list)
    removed_sections: list[str] = Field(default_factory=list)


class AdminPromptDraftResponse(CamelModel):
    """`id`가 `None`이면 아직 저장된 초안 행이 없다는 뜻이다 — `GET .../draft`가 활성
    세트의 복제본을 그 자리에서 만들어 보여줄 뿐 아무것도 저장하지 않는다(부작용 없는
    조회)."""

    id: uuid.UUID | None
    model: PromptSetModelId
    labels: AdminPromptLabels
    sections: list[AdminPromptSectionItem]


class AdminPromptSectionInput(CamelModel):
    channel: str
    scope: str
    slot: str
    variant: str = ""
    body: str
    conditional: bool
    order: int


class AdminPromptDraftUpsertRequest(CamelModel):
    """섹션 전체 교체 — 부분 패치가 아니다."""

    labels: AdminPromptLabels
    sections: list[AdminPromptSectionInput]


class AdminPromptPublishRequest(CamelModel):
    """`version`을 받지 않는다 — 서버가 자동 증가 정수를 부여한다. `note`가 "왜
    바꿨나"를 대신 받는다.

    판 칸 셋은 모두 생략할 수 있다 — 생략하면 바뀐 섹션 전부가 patch 이고 기준값을 견주지 않는다(단계를 고르지 않는 화면).
    - `levels`: 바뀐 섹션마다 고른 단계. 바뀌지 않은 섹션이나 없는 섹션 이름이 있으면 422 다. 체인의 첫 판(기준판 없음)에서는
      이 세트에 있는 섹션의 단계를 무시한다(전부 1.0.0).
    - `base_set_id`: 바뀐 섹션 조회 때 받은 기준판 id(기준판이 없었으면 null 을 그대로). 보냈는데 지금 기준판과 다르면 409 다.
    - `draft_hash`: 바뀐 섹션 조회 때 받은 초안 내용 해시. 보냈는데 지금 초안과 다르면 409 다 — 그 사이 다른 관리자가 초안을
      고쳐, 화면이 보지도 고르지도 않은 변경이 patch 로 나가는 것을 막는다."""

    note: str = ""
    levels: dict[str, SemverLevel] = Field(default_factory=dict)
    base_set_id: uuid.UUID | None = None
    draft_hash: str | None = None


class AdminPromptSectionChange(CamelModel):
    """게시 전 섹션 하나의 변화. `initial` 은 체인에 기준판이 없어 이 게시가 1.0.0 으로 시작한다는 뜻이다(단계를 고를 것이
    없다). `current_semver` 는 기준판에서의 번호이고, 기준판에 없던 섹션이면 null 이다."""

    channel: str
    change: SectionChange
    current_semver: str | None


class AdminPromptDraftChangesResponse(CamelModel):
    """`GET /admin/prompt-sets/{lane}/draft/changes` — 게시하면 판이 어떻게 갈릴지 미리 본다. `base_set_id`·`draft_hash` 를
    게시 요청에 그대로 돌려보내면, 그 사이 다른 게시나 초안 저장이 끼어들었을 때 게시가 409 로 멈춘다."""

    base_set_id: uuid.UUID | None
    base_semver: str | None
    draft_hash: str
    sections: list[AdminPromptSectionChange]


class AdminPromptPreviewItem(CamelModel):
    channel: str
    label: str
    text: str


class AdminPromptPreviewResponse(CamelModel):
    items: list[AdminPromptPreviewItem]


class AdminPromptRouteRow(CamelModel):
    """모델 배정 표의 한 행. 생성 행은 `chain_model` 이 없다(늘 방 모델의 체인을 읽는다)."""

    lane: RoutingLane
    room_model: ChatRoomModelId
    stage: PromptStage
    chain_model: PromptSetModelId | None
    call_model: PromptSetModelId
    backend: BackendId


class AdminPromptRoutingSaveRequest(CamelModel):
    """표 전체를 갈아 끼운다 — 부분 패치가 아니다. 빈 `rows` 는 표를 비워 전부 env 규칙으로 돌린다. `base_revision_id` 는 화면이
    읽은 최신 이력이고(이력이 없으면 null), 그 사이 다른 저장이 있었으면 409 다."""

    base_revision_id: uuid.UUID | None
    note: str = ""
    rows: list[AdminPromptRouteRow]


class AdminPromptRoutingRestoreRequest(CamelModel):
    base_revision_id: uuid.UUID | None
    note: str = ""


class AdminPromptRouteAllowedPair(CamelModel):
    kind: StageKind
    model: PromptSetModelId
    backend: BackendId


class AdminPromptRoutePrice(CamelModel):
    """USD / 1M 토큰. 원가 표(`llm/pricing.py`)의 값을 그대로 옮긴다."""

    input_usd_per_million: float
    cached_input_usd_per_million: float
    output_usd_per_million: float
    cache_write_usd_per_million: float


class AdminPromptRouteCall(CamelModel):
    """칸 하나를 읽는 호출 위치 하나가 실제로 보낼 모델 id 와 경로. 단가 표에 없는 id 면 `price` 가 null 이다(0 이 아니다)."""

    call_site: LLMCallSite
    backend: BackendId
    model_id: str
    price: AdminPromptRoutePrice | None


class AdminPromptRouteSkip(CamelModel):
    """그 칸에 쓸 행이 있었지만 지금 env 로는 적용되지 않는다. `stage` 는 그 행의 단계다(물려받으려던 행이면 물려준 단계)."""

    stage: PromptStage
    reason: SkipReason
    message: str


class AdminPromptRouteEffective(CamelModel):
    chain_model: PromptSetModelId
    call_model: PromptSetModelId
    backend: BackendId
    source: RouteSource
    source_detail: str | None


class AdminPromptRouteCell(CamelModel):
    """(레인, 방 모델, 단계) 한 칸. `configured` 는 그 칸 자신의 행이고, `effective` 는 채팅 호출 위치로 푼 값이다."""

    lane: RoutingLane
    room_model: ChatRoomModelId
    stage: PromptStage
    configured: AdminPromptRouteRow | None
    effective: AdminPromptRouteEffective
    skipped: AdminPromptRouteSkip | None
    calls: list[AdminPromptRouteCall]


class AdminPromptRouteChainReader(CamelModel):
    room_model: ChatRoomModelId
    stage: PromptStage
    channels: list[str]


class AdminPromptRouteChain(CamelModel):
    """한 체인(레인, 모델)을 지금 어느 칸이 어느 채널로 읽는가. 칸들의 실효 체인을 묶은 값이라 화면이 스스로 조합하지 않는다."""

    lane: RoutingLane
    model: PromptSetModelId
    read_by: list[AdminPromptRouteChainReader]


class AdminPromptRoutingResponse(CamelModel):
    """`revision_id`·`revision_number` 는 최신 이력이고, 한 번도 저장한 적 없으면 null 이다."""

    revision_id: uuid.UUID | None
    revision_number: int | None
    prices_as_of: date
    allowed_pairs: list[AdminPromptRouteAllowedPair]
    cells: list[AdminPromptRouteCell]
    chains: list[AdminPromptRouteChain]


class AdminPromptRouteRevisionSummary(CamelModel):
    id: uuid.UUID
    number: int
    note: str
    admin_id: uuid.UUID
    restored_from_id: uuid.UUID | None
    created_at: datetime
    row_count: int


class AdminPromptRouteRevisionListResponse(CamelModel):
    items: list[AdminPromptRouteRevisionSummary]


class AdminPromptRouteRevisionDetailResponse(AdminPromptRouteRevisionSummary):
    """지금 코드가 모르는 값(내린 모델 등)이 든 스냅샷 행은 응답 검증에서 500 이 나지 않게 `rows` 에서 빼고, 뺀 개수를
    `dropped_row_count` 로 알린다. 그런 스냅샷을 되돌리면 저장 검사가 거부한다."""

    rows: list[AdminPromptRouteRow]
    dropped_row_count: int


class AdminLlmUsageRow(CamelModel):
    """`day` 가 None 이면 조회 기간을 합친 줄이다. 날짜는 KST."""

    day: date | None
    call_site: str
    model: str
    calls: int
    prompt_tokens: int
    cached_tokens: int
    # 캐시에 새로 쓴 입력(Claude 만 보고한다). `prompt_tokens` 안의 몫이고, 정가보다 비싸게 과금된다.
    cache_write_tokens: int
    output_tokens: int
    thoughts_tokens: int
    total_tokens: int
    missing_calls: int
    # 입력 토큰이 비어 온 호출(이미지가 실린 호출)까지 `total − 출력 − 사고` 로 복원한 입력 전체.
    input_tokens: int
    cache_hit_rate: float | None
    judgment_ratio: float | None
    estimated_cost_usd: float | None


class AdminLlmModelPrice(CamelModel):
    model: str
    input_usd_per_million: float
    cached_input_usd_per_million: float
    output_usd_per_million: float
    cache_write_usd_per_million: float


class AdminLlmUsageResponse(CamelModel):
    rows: list[AdminLlmUsageRow]
    totals: list[AdminLlmUsageRow]
    estimated_cost_usd_total: float
    # 단가표에 없는 모델의 호출 수 — 0 이 아니면 위 합계가 그만큼 빠진 값이다.
    unpriced_calls: int
    prices_as_of: date
    prices: list[AdminLlmModelPrice]


class AdminUserPaymentItem(CamelModel):
    # 포트원 결제 id. 환불 견적·실행 경로가 이 값으로 결제를 가리킨다.
    payment_id: str
    product_key: str
    order_name: str
    amount_krw: int
    status: PaymentStatus
    paid_at: datetime | None
    cancelled_amount_krw: int
    # 클로버는 회수했고 포트원 결과가 확정되지 않은 환불 시도가 있다 — 화면이 "확인 필요"로 보이고 같은 실행 경로로
    # 재시도한다.
    refund_pending: bool
    created_at: datetime


class AdminUserPaymentListResponse(CamelModel):
    items: list[AdminUserPaymentItem]


class AdminRefundQuoteResponse(CamelModel):
    refund_krw: int
    ratio_percent: int
    paid_remaining: int
    bonus_used: int
    clawback_paid: int
    clawback_bonus: int
    cancellable_krw: int
    paid_at: datetime


class AdminRefundRequest(CamelModel):
    """멱등키를 받지 않는다 — 그 결제의 진행 중 환불 시도(서버의 `requested` 행)가 시도 단위다. 진행 중 시도가 있으면
    `expected_refund_krw`·`received_on`·`company_fault` 는 쓰이지 않고 그 시도를 마무리한다."""

    reason: str = Field(max_length=1000)
    # 다이얼로그가 보여 준 견적. 실행 시점 견적과 다르면 409 — 그사이 사용자가 클로버를 써 금액이 바뀌었다.
    expected_refund_krw: int = Field(ge=0)
    # 환불 신청을 받은 날(KST). 비율의 7일 판정을 처리일이 아니라 이 날로 한다.
    received_on: date
    company_fault: bool = False


class AdminRefundResponse(CamelModel):
    # succeeded: 포트원 취소 확인(200). requested: 클로버는 회수했고 포트원 결과를 기다린다(202).
    status: Literal["succeeded", "requested"]
    amount_krw: int
    clawback_paid: int
    clawback_bonus: int


class AdminCreatorPayoutEligibility(CamelModel):
    """신청자의 지금 자격. 회원의 신청·승인 재확인과 같은 판정 함수의 값이다."""

    identity_verified: bool
    adult: bool
    published_count: int
    suspended: bool
    withdrawn: bool


class AdminCreatorPayoutApplicationItem(CamelModel):
    id: uuid.UUID
    user_id: uuid.UUID
    # 탈퇴 회원은 닉네임이 파기돼 null 이다.
    nickname: str | None
    status: CreatorPayoutApplicationStatus
    applied_at: datetime
    decided_at: datetime | None
    decision_reason: str
    revoked_at: datetime | None
    eligibility: AdminCreatorPayoutEligibility


class AdminCreatorPayoutApplicationListResponse(CamelModel):
    items: list[AdminCreatorPayoutApplicationItem]
    page: int
    total_pages: int
    total_count: int


class AdminCreatorPayoutApproveRequest(CamelModel):
    # 승인 메모. 감사 로그에만 남고 신청자에게는 보이지 않는다.
    reason_text: str = Field(default="", max_length=1000)


class AdminCreatorPayoutApproveResponse(CamelModel):
    # 첫 승인 때 확정한 소급 적립액(원). 승인 취소 뒤 다시 승인하면 소급하지 않아 null 이다.
    retro_amount_krw: int | None


class AdminCreatorPayoutDecisionRequest(CamelModel):
    """거절·승인 취소 사유. 공백만이면 422(라우터가 확인한다). 두 사유 모두 신청자의 크리에이터 정산 화면에 그대로
    보이므로(감사 로그에도 남는다) 신청자에게 보여도 되는 글만 적고 내부 판단 근거는 적지 않는다."""

    reason_text: str = Field(max_length=1000)


class AdminCreatorPayoutItem(CamelModel):
    id: uuid.UUID
    user_id: uuid.UUID
    # 탈퇴 회원은 닉네임이 파기돼 null 이다. 탈퇴 전에 신청한 지급도 끝까지 처리하므로 목록에 남는다.
    nickname: str | None
    withdrawn: bool
    status: CreatorPayoutStatus
    amount_krw: int
    net_amount_krw: int
    requested_at: datetime


class AdminCreatorPayoutListResponse(CamelModel):
    items: list[AdminCreatorPayoutItem]
    page: int
    total_pages: int
    total_count: int


class AdminCreatorPayoutWithholding(CamelModel):
    income_tax_rate_bps: int
    income_tax_krw: int
    local_tax_krw: int
    net_amount_krw: int


class AdminCreatorPayoutDetail(CamelModel):
    """지급 건 하나. 회원 상세(탈퇴 회원은 404)에 기대지 않고 처리에 필요한 값을 이 응답이 갖는다.

    `withholding` 은 신청 때 계산해 남긴 원천징수이고 이체는 이 값으로 한다. `currentWithholding` 은 지금 코드의 세율로
    다시 계산한 값이라, 신청 뒤 세율 상수가 바뀌었으면 둘이 달라 화면이 경고한다. 수취인은 실명 첫·끝 글자, 은행, 계좌
    끝 4자리만 싣는다 — 원문은 사유를 적고 `payee-info-view` 로만 본다.

    수취인의 암호화한 칸(실명·주민등록번호·계좌번호) 중 하나라도 복호화하지 못하면(키 분실 등) 상세 전체를 거절하지
    않고 `payeeInfoReadable` 을 거짓, `maskedName` 을 null 로 싣는다 — 그 건도 열어서 반려·보류할 수 있어야 한다. 은행과
    계좌 끝 4자리는 평문 칸이라 그대로 싣는다. 복호화한 값은 싣지 않는다.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    nickname: str | None
    withdrawn: bool
    status: CreatorPayoutStatus
    amount_krw: int
    for_withdrawal: bool
    withholding: AdminCreatorPayoutWithholding
    current_withholding: AdminCreatorPayoutWithholding
    # 수취인의 암호화한 세 칸을 모두 복호화할 수 있는가. 거짓이면 `masked_name` 이 null 이고 원문 열람·이체 기록도 409 다.
    payee_info_readable: bool
    masked_name: str | None
    bank_code: BankCode
    account_last4: str
    requested_at: datetime
    paid_at: datetime | None
    transferred_on: date | None
    returned_at: datetime | None
    # 보류한 시각과 사유(운영자만 본다). 보류한 뒤 이체한 건도 남는다.
    held_at: datetime | None
    hold_reason: str
    admin_memo: str
    return_reason: str
    # 지금 수취인이 운영자가 넣은 판인가(탈퇴한 회원에게 문의로 받아 바꾼 수취 정보).
    payee_entered_by_admin: bool
    # 지금 수취인 판의 id. 이체 완료를 기록할 때 되돌려 보내, 그 사이 수취 정보가 바뀌었으면 409 를 받는다.
    payee_profile_id: uuid.UUID


class PayeeInfoViewReasonCategory(str, enum.Enum):
    """지급 정보 원문 열람 사유 분류. 채팅 열람(`ChatViewReasonCategory`)과 따로 둔다 — 원문을 여는 흔한 이유는 이체 전
    계좌 확인과 지급명세서 작성인데, 신고 조사·이의제기 검토는 지급 업무에 없다. 감사 로그의 `reason_category` 에 섞여
    들어가므로 겹치는 값(`legal-request`·`other`)은 채팅 열람과 뜻이 같다."""

    PAYOUT_PROCESSING = "payout-processing"
    PAYOUT_STATEMENT = "payout-statement"
    LEGAL_REQUEST = "legal-request"
    OTHER = "other"


class AdminPayeeInfoViewRequest(CamelModel):
    """지급 정보 원문 열람 사유. `reason_text` 가 공백만이면 422(라우터가 확인한다)."""

    reason_category: PayeeInfoViewReasonCategory
    reason_text: str = Field(max_length=1000)


class AdminPayeeInfoViewResponse(CamelModel):
    """지급 정보 원문. 이 응답에만 싣고 로그·감사 기록에는 남기지 않는다."""

    # 이 원문이 어느 수취인 판의 것인가. 이 값으로 이체 완료를 기록하면 열람 뒤 바뀐 정보에 기록이 붙지 않는다.
    payee_profile_id: uuid.UUID
    legal_name: str
    rrn: str
    bank_code: BankCode
    account_number: str


class AdminCreatorPayoutTransferRequest(CamelModel):
    # 운영자가 보고 이체한 수취인 판의 id(상세·원문 열람 응답의 `payeeProfileId`). 지금 판과 다르면 409 — 그 사이 수취
    # 정보가 바뀌어 돈이 간 곳과 기록이 가리키는 곳이 달라진다.
    payee_profile_id: uuid.UUID
    # 실제로 이체한 날(KST). 신청일(KST)보다 앞서거나 오늘(KST)보다 뒤면 422.
    transferred_on: date
    # 운영자만 보는 메모(감사 로그에도 남는다).
    admin_memo: str = Field(default="", max_length=1000)


class AdminCreatorPayoutHoldRequest(CamelModel):
    """보류 사유. 공백만이면 422(라우터가 확인한다). 운영자만 본다 — 보류는 탈퇴한 회원의 건이라 보일 사람이 없다."""

    reason_text: str = Field(max_length=1000)


class AdminCreatorPayoutPayeeReplaceRequest(CamelModel):
    """탈퇴한 회원에게 문의로 받은 새 수취 정보와 바꾸는 사유. 형식은 라우터가 확인하고 `CREATOR_PAYOUT_INFO_INVALID` 로
    답한다 — 스키마 검증 오류는 입력값을 응답에 되돌려 싣기 때문이다. 형식은 회원의 지급 정보 입력과 같다. 사유는 감사
    로그에 남고, 값은 남지 않는다."""

    legal_name: str
    rrn: str
    bank_code: str
    account_number: str
    reason_text: str = Field(max_length=1000)


class AdminCreatorPayoutReturnRequest(CamelModel):
    """반려 사유. 공백만이면 422(라우터가 확인한다). 신청자의 크리에이터 정산 화면에 그대로 보인다."""

    reason_text: str = Field(max_length=1000)


class AdminUserCreatorPayoutApplication(CamelModel):
    """정산 신청 하나. `decisionReason` 은 거절·승인 취소 사유(신청자에게 보이는 글)다."""

    id: uuid.UUID
    status: CreatorPayoutApplicationStatus
    applied_at: datetime
    decided_at: datetime | None
    decision_reason: str
    accrual_start_at: datetime | None
    revoked_at: datetime | None


class AdminUserCreatorPayoutConfirmation(CamelModel):
    id: uuid.UUID
    kind: CreatorPayoutConfirmationKind
    period_month: date | None
    window_start: datetime
    window_end: datetime
    gross_units: int
    refunded_units: int
    rate_bps: int
    amount_krw: int
    created_at: datetime


class AdminUserCreatorPayoutPayout(CamelModel):
    id: uuid.UUID
    status: CreatorPayoutStatus
    amount_krw: int
    net_amount_krw: int
    requested_at: datetime
    transferred_on: date | None


class AdminUserCreatorPayoutResponse(CamelModel):
    """회원 상세의 크리에이터 정산 섹션: 신청 이력 전부(최신순), 적립 잔액(음수일 수 있다), 최근 확정 12개, 최근 지급 20개."""

    applications: list[AdminUserCreatorPayoutApplication]
    balance_krw: int
    confirmations: list[AdminUserCreatorPayoutConfirmation]
    payouts: list[AdminUserCreatorPayoutPayout]
