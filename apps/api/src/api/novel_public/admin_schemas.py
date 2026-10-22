"""어드민 노벨 화면의 요청·응답 꼴."""

import uuid
from datetime import datetime
from typing import Literal

from api.core.schema import CamelModel
from api.db.models.content import ModerationStatus, NovelPermission
from api.db.models.moderation import ReportReasonCategory, ReportStatus
from api.db.models.novel import (
    NovelCommentDeletedBy,
    NovelPublicationModerationStatus,
    NovelPublicationReviewStatus,
    NovelPublicationVisibility,
    NovelScreeningOutcome,
    NovelScreeningPart,
    NovelSerialLockSource,
)
from api.novel_public.schemas import PublicNovelIllustration

AdminNovelModerationAction = Literal["restrict", "lift"]
AdminNovelReviewAction = Literal["approve", "reject"]
AdminNovelReportAction = Literal["restrict", "stop_sales", "reject", "illustration_takedown"]
AdminNovelSalesAction = Literal["stop", "resume"]
AdminNovelCommentAction = Literal["hide", "restore", "delete"]
AdminNovelCommentReportAction = Literal["hide", "delete", "reject"]


class AdminNovelListItem(CamelModel):
    """공개 상태 행이 있는 소설 하나(거둔 것·이용제한된 것 포함). `readable` 은 지금 독자에게 보이는가(거둠·이용제한·게시자
    정지·원작 숨김·공개 화 없음·첫 공개 승인 대기나 반려면 거짓). `purchase_count` 는 환급되지 않은 구매 수(탈퇴한 구매자의
    구매도 거래 기록이라 센다), `pending_report_count` 는 처리 전 노벨 신고 수다. `review_status` 는 첫 공개의 운영자 심사
    (대기·승인·반려, 심사 없이 공개됐으면 비어 있다) — 대기·반려 행의 `visibility` 는 `withdrawn` 이지만 게시자가 거둔 것이
    아니다. `hidden_at` 은 노벨로 팔린 소설을 작가가 지웠거나 그 작가가 탈퇴해 숨긴 시각이다 — 숨긴 소설도 공개 범위가 `withdrawn` 이라 이 값으로
    게시자가 거둔 것과 가른다(숨기지 않았으면 비어 있다). `sales_stopped_at` 은 운영자가 판매를 멈춘 시각이다 — 이용제한과
    따로 걸리고 따로 풀리며, 멈춘 노벨은 `readable` 이 거짓이지만 산 사람은 계속 읽는다(멈추지 않았으면 비어 있다)."""

    id: uuid.UUID
    title: str
    source_title: str
    publisher_user_id: uuid.UUID
    publisher_nickname: str | None
    visibility: NovelPublicationVisibility
    moderation_status: NovelPublicationModerationStatus
    readable: bool
    chapter_count: int
    like_count: int
    view_count: int
    purchase_count: int
    pending_report_count: int
    published_at: datetime
    review_status: NovelPublicationReviewStatus | None
    hidden_at: datetime | None
    sales_stopped_at: datetime | None


class AdminNovelListResponse(CamelModel):
    items: list[AdminNovelListItem]
    page: int
    total_pages: int
    total_count: int


class AdminNovelChapterItem(CamelModel):
    """공개 화 한 줄. `price` 는 그 화의 지금 가격(0 = 무료)이다."""

    id: uuid.UUID
    ordinal: int
    title: str | None
    edition: int
    price: int


class AdminNovelScreeningItem(CamelModel):
    """텍스트 심사 한 번. `reason` 은 심사 모델이 쓴 사유로 운영자만 본다."""

    chapter_ordinal: int | None
    outcome: NovelScreeningOutcome
    flagged_parts: list[NovelScreeningPart]
    reason: str | None
    model: str
    created_at: datetime


class AdminNovelReportListItem(CamelModel):
    """노벨 신고 하나. 소설·화가 지워지면 `novel_id`·`chapter_id` 가 비고, 무엇이 신고됐는지는 `evidence_title`·
    `chapter_ordinal`·`publisher_user_id` 로 읽는다(증거가 파기되면 제목도 빈다). `chapter_ordinal` 이 있으면 화 신고다."""

    id: uuid.UUID
    novel_id: uuid.UUID | None
    chapter_id: uuid.UUID | None
    chapter_ordinal: int | None
    publisher_user_id: uuid.UUID
    reporter_user_id: uuid.UUID
    reason_category: ReportReasonCategory
    status: ReportStatus
    created_at: datetime
    evidence_title: str | None
    evidence_expires_at: datetime
    evidence_available: bool


class AdminNovelDetailResponse(AdminNovelListItem):
    """공개본 글과 운영 판단 재료. `source_moderation_status` 는 원작의 지금 상태(원작이 없으면 비어 있다), `publisher_suspended`
    는 게시자 정지 여부, `publisher_withdrawn` 은 게시자 탈퇴 여부다 — 셋 다 `readable` 이 거짓인 이유를 가른다(탈퇴한
    게시자의 팔린 소설은 숨긴 채 남아 `hidden_at` 이 있다 — 탈퇴로 숨겼는지는 이것으로 본다. 작가가 지워 숨긴 뒤 탈퇴했으면
    둘 다 참이다). `reports` 는 최근 노벨 신고 20개다.
    `purchase_amount` 는 환급되지 않은 구매의 가격 합(탈퇴한 구매자의 구매 포함), `purchase_buyer_count` 는 그 구매를 한 사람
    수다 — 탈퇴한 구매자는 누구인지 남지 않아 사람 수에 들지 않는다.

    `review_reason` 은 반려 사유(작가에게 그대로 보인다), `reviewed_at` 은 마지막 승인·반려 시각이다. `serial_lock_*` 는 연재권
    잠금 기록이다 — 잠긴 시각, 그때의 원작 소설화 허락·원작 게시본 id·시행 중이던 약관 판의 사본과 출처(`first_publish` 는
    첫 공개·승인이 찍음, `backfill` 은 이 기록이 생기기 전 공개된 소설을 뒤늦게 채움 — 허락·원작 게시본을 알 수 없어 비어
    있다). 잠기지 않았으면 모두 비어 있다."""

    synopsis: str
    content_id: uuid.UUID
    source_moderation_status: ModerationStatus | None
    publisher_suspended: bool
    publisher_withdrawn: bool
    first_published_at: datetime
    chapters: list[AdminNovelChapterItem]
    screenings: list[AdminNovelScreeningItem]
    reports: list[AdminNovelReportListItem]
    purchase_buyer_count: int
    purchase_amount: int
    review_reason: str | None
    reviewed_at: datetime | None
    serial_locked_at: datetime | None
    serial_lock_permission: NovelPermission | None
    serial_lock_content_version_id: uuid.UUID | None
    serial_lock_terms_version: str | None
    serial_lock_source: NovelSerialLockSource | None


class AdminNovelIllustration(PublicNovelIllustration):
    asset_id: uuid.UUID


class AdminNovelChapterEditionItem(CamelModel):
    """화의 판 하나 — 판 번호, 그 판을 공개한 시각, 작가가 쓴 변경 요약(첫 판·요약 없이 낸 판은 비어 있다). `current` 는 지금
    독자에게 나가는 판인가."""

    edition: int
    published_at: datetime
    change_summary: str | None
    current: bool


class AdminNovelChapterResponse(CamelModel):
    """화의 판 하나 — 그 판을 산 회원에게 나가는 그대로(제목·작가의 말·본문 문단). `edition` 은 실제로 준 판이다(요청한 판을
    모르는 서버는 지금 판을 주므로 화면은 이 값으로 어느 판을 보는지 판단한다). `editions` 는 그 화의 판 전부(최신순)다."""

    id: uuid.UUID
    ordinal: int
    title: str | None
    author_note: str
    edition: int
    paragraphs: list[str]
    # 독자에게 나가는 그대로의 삽화(`PublicNovelIllustration`)에 그림 자산 id 를 더한 것 — 그림 내리기가 이 id 로 고른다.
    illustrations: list[AdminNovelIllustration]
    editions: list[AdminNovelChapterEditionItem]


class AdminNovelIllustrationTakedownRequest(CamelModel):
    """그림 하나를 모든 판에서 내린다. `reason` 은 그 그림 자리에 독자에게 보일 사유이자 감사 로그의 조치 사유다(공백만이면 422)."""

    reason: str


class AdminNovelIllustrationTakedownResponse(CamelModel):
    """`already_taken_down` 이 참이면 같은 파일이 다른 자산으로 이미 내려가 있어 새로 내리지 않았다(이 자산도 이미 내린 그림으로
    보인다). 그때 `taken_down_at` 은 처음 내린 시각이다."""

    asset_id: uuid.UUID
    taken_down_at: datetime
    already_taken_down: bool


class AdminNovelModerationRequest(CamelModel):
    """`admin_comment` 는 감사 로그에 남는 조치 사유(공백만이면 422). `reason_category` 는 신고 사유 분류를 고를 때만."""

    action: AdminNovelModerationAction
    admin_comment: str
    reason_category: ReportReasonCategory | None = None


class AdminNovelModerationResponse(CamelModel):
    novel_id: uuid.UUID
    moderation_status: NovelPublicationModerationStatus


class AdminNovelSalesRequest(CamelModel):
    """판매 중단(`stop`)·재개(`resume`). `admin_comment` 는 감사 로그에 남는 조치 사유(공백만이면 422). `reason_category` 는
    신고 사유 분류를 고를 때만."""

    action: AdminNovelSalesAction
    admin_comment: str
    reason_category: ReportReasonCategory | None = None


class AdminNovelSalesResponse(CamelModel):
    """`sales_stopped_at` 은 판매를 멈춘 시각(재개했으면 비어 있다)."""

    novel_id: uuid.UUID
    sales_stopped_at: datetime | None


class AdminNovelReviewRequest(CamelModel):
    """첫 공개 승인(`approve`)·반려(`reject`). `admin_comment` 는 감사 로그에 남는 글이고, 반려에서는 운영자가 쓴 글 그대로
    작가에게 보이는 반려 사유이기도 하다(반려는 공백뿐이면 422)."""

    action: AdminNovelReviewAction
    admin_comment: str


class AdminNovelReviewResponse(CamelModel):
    novel_id: uuid.UUID
    review_status: NovelPublicationReviewStatus
    visibility: NovelPublicationVisibility


class AdminNovelReportEvidence(CamelModel):
    """신고 시점 공개본 사본. 보유 기간이 지났거나 파기됐으면 `available` 이 거짓이고 글 칸이 모두 빈다."""

    expires_at: datetime
    available: bool
    title: str | None
    synopsis: str | None
    chapter_title: str | None
    body: str | None


class AdminNovelReportListResponse(CamelModel):
    items: list[AdminNovelReportListItem]
    page: int
    total_pages: int
    total_count: int


class AdminNovelReportDetailResponse(AdminNovelReportListItem):
    """`novel_moderation_status` 는 신고된 노벨의 지금 이용제한 상태, `novel_sales_stopped_at` 은 판매를 멈춘 시각이다(소설이
    지워졌거나 멈추지 않았으면 비어 있다)."""

    resolved_by_admin_id: uuid.UUID | None
    resolved_at: datetime | None
    novel_moderation_status: NovelPublicationModerationStatus | None
    novel_sales_stopped_at: datetime | None
    evidence: AdminNovelReportEvidence


class AdminNovelReportActionRequest(CamelModel):
    action: AdminNovelReportAction
    admin_comment: str


class AdminNovelCommentItem(CamelModel):
    """운영자가 보는 댓글 — 지운 댓글·숨긴 댓글도 싣는다(지운 댓글은 본문이 비어 있다)."""

    id: uuid.UUID
    novel_id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_ordinal: int
    author_user_id: uuid.UUID
    author_nickname: str | None
    body: str | None
    moderator_hidden: bool
    deleted_by: NovelCommentDeletedBy | None
    deleted_at: datetime | None
    created_at: datetime


class AdminNovelCommentListResponse(CamelModel):
    items: list[AdminNovelCommentItem]
    page: int
    total_pages: int
    total_count: int


class AdminNovelCommentActionRequest(CamelModel):
    action: AdminNovelCommentAction
    admin_comment: str


class AdminNovelCommentReportEvidence(CamelModel):
    expires_at: datetime
    available: bool
    body: str | None


class AdminNovelCommentReportListItem(CamelModel):
    """노벨 댓글 신고 하나. 댓글·소설이 지워지면 `comment_id`·`novel_id` 가 비고, 누가 쓴 댓글이었는지는
    `comment_author_user_id` 로 남는다."""

    id: uuid.UUID
    comment_id: uuid.UUID | None
    novel_id: uuid.UUID | None
    comment_author_user_id: uuid.UUID
    reporter_user_id: uuid.UUID
    reason_category: ReportReasonCategory
    status: ReportStatus
    created_at: datetime
    evidence_expires_at: datetime
    evidence_available: bool


class AdminNovelCommentReportListResponse(CamelModel):
    items: list[AdminNovelCommentReportListItem]
    page: int
    total_pages: int
    total_count: int


class AdminNovelCommentReportDetailResponse(AdminNovelCommentReportListItem):
    """`comment` 는 지금 댓글 행(지워졌으면 비어 있다), `evidence` 는 신고 시점 사본이다."""

    resolved_by_admin_id: uuid.UUID | None
    resolved_at: datetime | None
    comment: AdminNovelCommentItem | None
    evidence: AdminNovelCommentReportEvidence


class AdminNovelCommentReportActionRequest(CamelModel):
    action: AdminNovelCommentReportAction
    admin_comment: str
