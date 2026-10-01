import uuid
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict

from api.core.schema import CamelModel
from api.db.models.content import ContentType, ContentVisibility, ModerationStatus
from api.db.models.moderation import ReportReasonCategory, ReportStatus

CommentDisplayState = Literal["normal", "deleted", "muted", "creator-hidden", "moderator-hidden"]
CommentSort = Literal["latest", "popular"]
CommentPageDirection = Literal["after", "before"]


class CommentAuthorResponse(CamelModel):
    id: uuid.UUID
    nickname: str
    profile_image_url: str | None
    is_creator: bool


class CommentStickerResponse(CamelModel):
    id: str
    name: str
    alt: str
    image_url: str
    is_selectable: bool


class CommentReplyTargetResponse(CamelModel):
    id: uuid.UUID
    display_state: CommentDisplayState
    author: CommentAuthorResponse | None
    body_preview: str | None
    effective_spoiler: bool


class CommentResponse(CamelModel):
    id: uuid.UUID
    content_id: uuid.UUID
    root_comment_id: uuid.UUID | None
    reply_to_comment_id: uuid.UUID | None
    reply_to: CommentReplyTargetResponse | None
    display_state: CommentDisplayState
    author: CommentAuthorResponse | None
    body: str | None
    sticker: CommentStickerResponse | None
    mentions: list[CommentAuthorResponse]
    is_spoiler: bool
    effective_spoiler: bool
    inherited_spoiler: bool
    created_at: datetime
    updated_at: datetime | None
    is_edited: bool
    like_count: int
    is_liked: bool
    reply_count: int
    is_pinned: bool
    creator_hidden: bool
    moderator_hidden: bool
    can_reply: bool
    can_edit: bool
    can_delete: bool
    can_like: bool
    can_report: bool
    can_pin: bool
    can_creator_hide: bool
    can_creator_restore: bool


class CommentListResponse(CamelModel):
    content_id: uuid.UUID
    content_type: ContentType
    creator_user_id: uuid.UUID
    comments_paused: bool
    can_read: Literal[True]
    can_participate: bool
    can_create: bool
    can_manage: bool
    visible_comment_count: int
    hidden_comment_count: int | None
    pinned_comment: CommentResponse | None
    items: list[CommentResponse]
    next_cursor: str | None


class CommentRepliesResponse(CamelModel):
    root_comment_id: uuid.UUID
    items: list[CommentResponse]
    previous_cursor: str | None
    next_cursor: str | None
    visible_reply_count: int


class CommentLocationResponse(CamelModel):
    content_id: uuid.UUID
    content_type: ContentType
    root: CommentResponse
    target: CommentResponse
    replies: CommentRepliesResponse | None


class CommentHiddenListResponse(CamelModel):
    items: list[CommentResponse]
    next_cursor: str | None
    total_count: int


class CommentMutationRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")


class CommentWriteRequest(CommentMutationRequest):
    body: str
    sticker_id: str | None
    is_spoiler: bool
    mention_user_ids: list[uuid.UUID]


class CommentCreateRequest(CommentWriteRequest):
    request_id: uuid.UUID
    root_comment_id: uuid.UUID | None
    reply_to_comment_id: uuid.UUID | None


class CommentUpdateRequest(CommentWriteRequest):
    pass


class CommentLikeResponse(CamelModel):
    comment_id: uuid.UUID
    like_count: int
    is_liked: bool


class CommentSettingsUpdateRequest(CommentMutationRequest):
    comments_paused: bool


class CommentSettingsResponse(CamelModel):
    content_id: uuid.UUID
    comments_paused: bool


class CommentPinRequest(CommentMutationRequest):
    comment_id: uuid.UUID


class CommentPinResponse(CamelModel):
    pinned_comment: CommentResponse | None


class CommentMentionCandidatesResponse(CamelModel):
    items: list[CommentAuthorResponse]
    next_cursor: str | None


class CommentStickerCatalogResponse(CamelModel):
    items: list[CommentStickerResponse]


class CommentMutesResponse(CamelModel):
    items: list[CommentAuthorResponse]
    next_cursor: str | None


class CommentNotificationPreferencesResponse(CamelModel):
    new_comment: bool
    reply: bool
    mention: bool


class CommentNotificationPreferencesUpdateRequest(CommentMutationRequest):
    new_comment: bool
    reply: bool
    mention: bool


class CommentNotificationTargetResponse(CamelModel):
    content_id: uuid.UUID
    content_type: ContentType
    comment_id: uuid.UUID
    root_comment_id: uuid.UUID
    availability: Literal["available", "unavailable"]
    is_spoiler: bool
    author: CommentAuthorResponse | None
    body_preview: str | None
    sticker_name: str | None


class CommentReportCreateRequest(CommentMutationRequest):
    reason_category: ReportReasonCategory


class CommentReportResponse(CamelModel):
    report_id: uuid.UUID
    status: ReportStatus


class AdminCommentReportListItem(CamelModel):
    id: uuid.UUID
    comment_id: uuid.UUID
    content_id: uuid.UUID
    content_type: ContentType
    content_name: str
    reason_category: ReportReasonCategory
    status: ReportStatus
    created_at: datetime
    evidence_expires_at: datetime
    evidence_available: bool


class AdminCommentReportListResponse(CamelModel):
    items: list[AdminCommentReportListItem]
    page: int
    total_pages: int
    total_count: int


class AdminCommentContentContextResponse(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_url: str | None
    detail_description: str
    visibility: ContentVisibility
    moderation_status: ModerationStatus


class AdminCommentCurrentResponse(CamelModel):
    id: uuid.UUID
    content_id: uuid.UUID
    root_comment_id: uuid.UUID | None
    reply_to_comment_id: uuid.UUID | None
    author: CommentAuthorResponse | None
    body: str | None
    sticker: CommentStickerResponse | None
    mentions: list[CommentAuthorResponse]
    is_spoiler: bool
    inherited_spoiler: bool
    effective_spoiler: bool
    creator_hidden: bool
    moderator_hidden: bool
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None


class CommentReportEvidenceResponse(CamelModel):
    expires_at: datetime
    available: bool
    body: str | None
    sticker_id: str | None
    mention_user_ids: list[uuid.UUID]


class AdminCommentReportDetailResponse(CamelModel):
    id: uuid.UUID
    reason_category: ReportReasonCategory
    reporter_user_id: uuid.UUID
    status: ReportStatus
    created_at: datetime
    resolved_by_admin_id: uuid.UUID | None
    resolved_at: datetime | None
    content: AdminCommentContentContextResponse
    comment: AdminCommentCurrentResponse
    root: AdminCommentCurrentResponse
    reply_to: AdminCommentCurrentResponse | None
    evidence: CommentReportEvidenceResponse


class AdminCommentReportActionRequest(CommentMutationRequest):
    action: Literal["hide", "restore", "reject"]
    admin_comment: str


class AdminCommentModerationRequest(CommentMutationRequest):
    admin_comment: str
