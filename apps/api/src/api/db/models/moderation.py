import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Text, Uuid, false, func
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
    """techspec-db-schema.md §8, tasks/techspec.md §3-3.

    `type`은 지금 5종이다 — `moderation-action`(기본값, `moderation/router.py`의 신고
    처리에서 INSERT), `user-warned`(`admin/users.py`의 경고), `user-suspended`
    (`admin/users.py`의 정지), `notice`(`admin/notices.py`의 공지 게시 fan-out),
    `inquiry-reply`(`admin/inquiries.py`의 문의 답변). `type`이 Postgres enum이 아니라 `Text`인 이유가
    그것이다 — 값이 늘어날 여지가 있어 새 값을 추가해도 마이그레이션이 필요 없다.

    그래도 범용 알림 프레임워크는 아니다 — type이 코드에 열거된 소수이고 임의 알림을
    만들 수는 없다.

    `reason_category`/`admin_comment`는 nullable이다. 위 조치 통지 3종은 앞으로도 두
    컬럼을 계속 채우지만, 공지·문의답변은 인용할 사유가 없어 채울 것이 없다.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, server_default="moderation-action", nullable=False)
    content_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=True)
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("moderation_actions.id"), nullable=True
    )
    reason_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("notices.id"), nullable=True)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("inquiries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)

    # notice_id 참조는 위 컬럼 정의가 먼저 실행돼 클래스 바디 네임스페이스에 바인딩된
    # 뒤라야 동작한다 — 그래서 __table_args__를 컬럼들 다음에 둔다(`AdminActionLog` 참고).
    # postgresql_where=notice_id(bare 컬럼 참조)는 autogenerate가 `MappedColumn` 객체의
    # repr을 마이그레이션 소스에 그대로 박아 SyntaxError를 낸다(T-6에서 실측 재현,
    # `apps/api/CLAUDE.md` §마이그레이션) — `.is_not(None)`로 식을 만들어야 한다.
    __table_args__ = (
        Index(
            "ux_notifications_notice_user",
            "notice_id",
            "user_id",
            unique=True,
            postgresql_where=notice_id.is_not(None),
        ),
    )


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


class AdminActionLog(Base):
    """techspec.md §1-3, goal-prompt.md §3-2. 콘텐츠 조치는 `moderation_actions`와 이 테이블
    양쪽에 기록된다 — 중복이 아니라 계층이다. `moderation_actions`는 콘텐츠 조치의 실체
    레코드이자 `Notification.action_id`의 FK 대상이라 없앨 수 없고, 이 테이블은 콘텐츠
    조치·유저 제재·채팅 열람을 한 형식으로 담는 감사 로그다."""

    __tablename__ = "admin_action_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    target_content_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contents.id"), nullable=True
    )
    target_chat_room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id"), nullable=True
    )
    reason_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_text: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # `created_at.desc()` 참조는 위 컬럼 정의가 먼저 실행돼 클래스 바디 네임스페이스에
    # 바인딩된 뒤라야 동작한다 — 그래서 __table_args__를 컬럼들 다음에 둔다.
    __table_args__ = (
        Index("ix_admin_action_logs_created_at", created_at.desc()),
        Index("ix_admin_action_logs_target_user_id", "target_user_id"),
        Index("ix_admin_action_logs_target_content_id", "target_content_id"),
    )
