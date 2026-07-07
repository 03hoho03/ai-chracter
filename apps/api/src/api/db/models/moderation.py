import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ReportReasonCategory(str, enum.Enum):
    ADULT = "adult"
    COPYRIGHT = "copyright"
    HATE = "hate"
    SPAM = "spam"
    OTHER = "other"


class ReportStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class ModerationActionType(str, enum.Enum):
    RESTRICT = "restrict"
    LIFT_RESTRICTION = "lift-restriction"
    DELETE = "delete"
    REJECT = "reject"


class AppealTargetKind(str, enum.Enum):
    PUBLISH_REJECTION = "publish-rejection"
    MODERATION_ACTION = "moderation-action"


class AppealStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


class AppealVerdict(str, enum.Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Report(Base):
    """techspec-db-schema.md §8."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    reason_category: Mapped[ReportReasonCategory] = mapped_column(
        Enum(ReportReasonCategory, name="report_reason_category"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus, name="report_status"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModerationAction(Base):
    """techspec-db-schema.md §8."""

    __tablename__ = "moderation_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    action: Mapped[ModerationActionType] = mapped_column(
        Enum(ModerationActionType, name="moderation_action_type"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notification(Base):
    """techspec-db-schema.md §8. `type` 하나(moderation-action)만 존재 — 범용 알림 프레임워크 아님
    (techspec-builder-common.md §5.2)."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, server_default="moderation-action", nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    action_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("moderation_actions.id"), nullable=False)
    reason_category: Mapped[str] = mapped_column(Text, nullable=False)
    admin_comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)


class Appeal(Base):
    """techspec-db-schema.md §8. `target_id`는 target_kind에 따라 발행거부 이력 또는
    moderation_actions.id를 가리키는 다형(polymorphic) 참조라 DB FK를 걸지 않는다."""

    __tablename__ = "appeals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    target_kind: Mapped[AppealTargetKind] = mapped_column(
        Enum(AppealTargetKind, name="appeal_target_kind"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AppealStatus] = mapped_column(Enum(AppealStatus, name="appeal_status"), nullable=False)
    verdict: Mapped[AppealVerdict | None] = mapped_column(
        Enum(AppealVerdict, name="appeal_verdict"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
