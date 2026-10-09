"""어드민 노벨 화면의 요청·응답 꼴."""

import uuid
from datetime import datetime
from typing import Literal

from api.core.schema import CamelModel
from api.db.models.content import ModerationStatus
from api.db.models.moderation import ReportReasonCategory, ReportStatus
from api.db.models.novel import (
    NovelCommentDeletedBy,
    NovelPublicationModerationStatus,
    NovelPublicationVisibility,
    NovelScreeningOutcome,
    NovelScreeningPart,
)

AdminNovelModerationAction = Literal["restrict", "lift"]
AdminNovelReportAction = Literal["restrict", "reject"]
AdminNovelCommentAction = Literal["hide", "restore", "delete"]
AdminNovelCommentReportAction = Literal["hide", "delete", "reject"]


class AdminNovelListItem(CamelModel):
    """공개 상태 행이 있는 소설 하나(거둔 것·이용제한된 것 포함). `readable` 은 지금 독자에게 보이는가(거둠·이용제한·게시자
    정지·원작 숨김·공개 화 없음이면 거짓). `purchase_count` 는 환급되지 않은 구매 수, `pending_report_count` 는 처리 전 노벨
    신고 수다."""

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


class AdminNovelListResponse(CamelModel):
    items: list[AdminNovelListItem]
    page: int
    total_pages: int
    total_count: int


class AdminNovelChapterItem(CamelModel):
    id: uuid.UUID
    ordinal: int
    title: str | None
    edition: int


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
    는 게시자 정지 여부다 — 둘 다 `readable` 이 거짓인 이유를 가른다. `reports` 는 최근 노벨 신고 20개다."""

    synopsis: str
    content_id: uuid.UUID
    source_moderation_status: ModerationStatus | None
    publisher_suspended: bool
    first_published_at: datetime
    chapters: list[AdminNovelChapterItem]
    screenings: list[AdminNovelScreeningItem]
    reports: list[AdminNovelReportListItem]
    purchase_buyer_count: int
    purchase_amount: int


class AdminNovelChapterResponse(CamelModel):
    """화 공개본 — 독자에게 나가는 그대로(제목·작가의 말·본문 문단)."""

    id: uuid.UUID
    ordinal: int
    title: str | None
    author_note: str
    edition: int
    paragraphs: list[str]


class AdminNovelModerationRequest(CamelModel):
    """`admin_comment` 는 감사 로그에 남는 조치 사유(공백만이면 422). `reason_category` 는 신고 사유 분류를 고를 때만."""

    action: AdminNovelModerationAction
    admin_comment: str
    reason_category: ReportReasonCategory | None = None


class AdminNovelModerationResponse(CamelModel):
    novel_id: uuid.UUID
    moderation_status: NovelPublicationModerationStatus


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
    """`novel_moderation_status` 는 신고된 노벨의 지금 이용제한 상태(소설이 지워졌으면 비어 있다)."""

    resolved_by_admin_id: uuid.UUID | None
    resolved_at: datetime | None
    novel_moderation_status: NovelPublicationModerationStatus | None
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
