import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.moderation import ReportReasonCategory, ReportStatus


class CommentSticker(Base):
    """공식 자산은 사용자 업로드와 분리하고, 선택 중지 후에도 기존 게시물에 남긴다."""

    __tablename__ = "comment_stickers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    alt: Mapped[str] = mapped_column(Text, nullable=False)
    # web이 제공하는 경로다. admin에서도 같은 자산을 사용하므로 응답 URL은 web origin으로 조립한다.
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_selectable: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)


class Comment(Base):
    """표시는 2단이고, 스레드 소속과 실제 답한 댓글은 별도 참조다.

    삭제 시 행을 지우지 않아 타인의 답글 참조를 보존한다. 원문과 스티커는 비우며,
    별도 신고 증거는 그 신고의 보유기간을 따른다.
    """

    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    root_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("comments.id"), nullable=True
    )
    reply_to_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("comments.id"), nullable=True
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sticker_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("comment_stickers.id"), nullable=True
    )
    is_spoiler: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    inherited_spoiler: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    creator_hidden: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    moderator_hidden: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # 원문을 중복 저장하지 않고 최초 생성 요청과 비교한다. 수정한 뒤에도 처음 요청의 지문을 유지한다.
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("author_user_id", "request_id", name="ux_comments_author_request"),
        CheckConstraint(
            "(root_comment_id IS NULL AND reply_to_comment_id IS NULL) OR "
            "(root_comment_id IS NOT NULL AND reply_to_comment_id IS NOT NULL)",
            name="ck_comments_reply_references_together",
        ),
        CheckConstraint("root_comment_id IS NULL OR root_comment_id <> id", name="ck_comments_not_own_root"),
        CheckConstraint(
            "reply_to_comment_id IS NULL OR reply_to_comment_id <> id", name="ck_comments_not_own_reply_target"
        ),
        Index("ix_comments_content_root_created", "content_id", "root_comment_id", "created_at", "id"),
        Index("ix_comments_author", "author_user_id"),
        Index("ix_comments_reply_target", "reply_to_comment_id"),
    )


class CommentMention(Base):
    __tablename__ = "comment_mentions"

    comment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("comments.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)


class CommentLike(Base):
    __tablename__ = "comment_likes"

    comment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("comments.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_comment_likes_user", "user_id"),)


class CommentMute(Base):
    __tablename__ = "comment_mutes"

    viewer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    target_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("viewer_user_id <> target_user_id", name="ck_comment_mutes_not_self"),
    )


class CommentNotificationPreference(Base):
    __tablename__ = "comment_notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    new_comment: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
    reply: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
    mention: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)


class CommentReport(Base):
    """신고 metadata와 원문 증거의 수명을 분리한다.

    만료된 증거는 조회에서 즉시 제외하고 파기 작업이 저장 원문을 비운다. 과거 닉네임과
    프로필 이미지를 복사하지 않는다. 같은 회원의 재신고는 최초 신고를 연장하지 않는다.
    """

    __tablename__ = "comment_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    comment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("comments.id"), nullable=False)
    reason_category: Mapped[ReportReasonCategory] = mapped_column(
        Enum(ReportReasonCategory, name="report_reason_category"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_sticker_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("comment_stickers.id"), nullable=True
    )
    evidence_mention_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]"), nullable=False
    )
    evidence_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '90 days'"), nullable=False
    )
    evidence_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("reporter_user_id", "comment_id", name="ux_comment_reports_reporter_comment"),
        Index("ix_comment_reports_status_created", "status", "created_at", "id"),
        Index("ix_comment_reports_evidence_expires", "evidence_expires_at"),
    )


CommentModerationActionType = Literal["hide", "restore", "reject"]


class CommentModerationAction(Base):
    __tablename__ = "comment_moderation_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    comment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("comments.id"), nullable=False)
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("comment_reports.id"), nullable=True
    )
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    action: Mapped[CommentModerationActionType] = mapped_column(Text, nullable=False)
    reason_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_comment_moderation_actions_comment", "comment_id", "created_at"),)
