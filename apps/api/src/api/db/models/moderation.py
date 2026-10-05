import enum
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ReportReasonCategory(str, enum.Enum):
    ADULT = "adult"
    # 미성년으로 보이는 인물의 성적 대상화·그루밍 같은 신고. 다른 신고보다 먼저 처리하므로 다른 사유와 섞이지 않게
    # 따로 받는다(기준은 `CONTENT_POLICY.md` 의 "신고와 처리" 절). 채팅 응답 신고 사유에도 같은 키가 있다.
    MINOR_SAFETY = "minor_safety"
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
    __tablename__ = "moderation_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 조치는 초안에도 걸릴 수 있고 초안은 소유자가 지울 수 있다. 조치 기록은 남기고 사라진 작품을
    # 가리키던 칸만 비운다 — 그래서 NULL이 곧 "작품이 삭제됨"이다.
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contents.id", ondelete="SET NULL"), nullable=True
    )
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    action: Mapped[ModerationActionType] = mapped_column(
        Enum(ModerationActionType, name="moderation_action_type"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notification(Base):
    """`type`은 운영·공지·문의·댓글 사건을 구분한다 — `moderation-action`(기본값, `moderation/router.py`의 신고
    처리에서 INSERT), `user-warned`(`admin/users.py`의 경고), `user-suspended`
    (`admin/users.py`의 정지), `notice`(`admin/notices.py`의 공지 게시 fan-out),
    `inquiry-reply`(`admin/inquiries.py`의 문의 답변), 댓글 생성·답글·멘션·운영 조치 알림이다.
    `type`이 Postgres enum이 아니라 `Text`인 이유가
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
    # 조치 통지가 가리키던 초안을 소유자가 지우면 통지는 남기고 작품 칸만 비운다.
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contents.id", ondelete="SET NULL"), nullable=True
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("moderation_actions.id"), nullable=True
    )
    reason_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("notices.id"), nullable=True)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("inquiries.id"), nullable=True)
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("comments.id", name="fk_notifications_comment_id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_notifications_actor_user_id"), nullable=True
    )
    comment_action_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("comment_moderation_actions.id", name="fk_notifications_comment_action_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)

    # notice_id 참조는 위 컬럼 정의가 먼저 실행돼 클래스 바디 네임스페이스에 바인딩된
    # 뒤라야 동작한다 — 그래서 __table_args__를 컬럼들 다음에 둔다(`AdminActionLog` 참고).
    # postgresql_where=notice_id(bare 컬럼 참조)는 autogenerate가 `MappedColumn` 객체의
    # repr을 마이그레이션 소스에 그대로 박아 SyntaxError를 낸다(실측 재현,
    # `apps/api/CLAUDE.md` §마이그레이션) — `.is_not(None)`로 식을 만들어야 한다.
    __table_args__ = (
        Index(
            "ux_notifications_notice_user",
            "notice_id",
            "user_id",
            unique=True,
            postgresql_where=notice_id.is_not(None),
        ),
        Index(
            "ux_notifications_comment_user",
            "comment_id",
            "user_id",
            unique=True,
            postgresql_where=comment_id.is_not(None) & comment_action_id.is_(None),
        ),
        Index(
            "ux_notifications_comment_action_user",
            "comment_action_id",
            "user_id",
            unique=True,
            postgresql_where=comment_action_id.is_not(None),
        ),
        Index("ix_notifications_user_created", "user_id", "created_at", "id"),
    )


class Appeal(Base):
    """`target_id`는 target_kind에 따라 발행거부 이력 또는
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


# 감사 로그 액션 종류의 단일 소스. `record_admin_action`의 파라미터와
# 응답 스키마 `AdminUserActionLogItem.action_type`이 이 타입을 쓰므로, 목록 밖 값은 호출부에서
# mypy가 막고 응답은 OpenAPI 유니언으로 FE에 내려간다. 처음 계획은 `admin/action_log.py`였지만
# 그 모듈이 이 파일을 import하므로 여기 둔다(순환 import 회피).
# 값을 추가할 때 마이그레이션은 필요 없다(컬럼은 Text) — 이 목록과 FE 라벨만 늘린다.
AdminActionType = Literal[
    "appeal-accept",
    "chat-report-reject",
    "chat-report-resolve",
    "chat-view",
    "comment-hide",
    "comment-report-reject",
    "comment-restore",
    "content-delete",
    "content-lift",
    "content-restrict",
    "home-curation-clear",
    "home-curation-set",
    "image-view",
    "inquiry-reply",
    "legal-publish",
    "notice-publish",
    "notice-unpublish",
    "prompt-set-publish",
    "report-reject",
    "user-beta-off",
    "user-beta-on",
    "user-clover-grant",
    "user-clover-revoke",
    "user-novelize-off",
    "user-novelize-on",
    "user-rate-limit-exempt-off",
    "user-rate-limit-exempt-on",
    "user-suspend",
    "user-unsuspend",
    "user-warn",
]


class AdminActionLog(Base):
    """콘텐츠 조치는 `moderation_actions`와 이 테이블
    양쪽에 기록된다 — 중복이 아니라 계층이다. `moderation_actions`는 콘텐츠 조치의 실체
    레코드이자 `Notification.action_id`의 FK 대상이라 없앨 수 없고, 이 테이블은 콘텐츠
    조치·유저 제재·채팅 열람을 한 형식으로 담는 감사 로그다. 직접 조치와 신고 조치 둘 다
    그렇다. 예외는 이의제기 수용(`appeal-accept`)으로, 조치를
    되돌릴 뿐 새 조치가 아니라 이 테이블에만 남는다.

    `action_type` 컬럼은 native enum이 아니라 Text다 — 값이 늘 때 마이그레이션 없이 넓히기
    위해서다. 값 범위(`AdminActionType`, 위 Literal)는 mypy가 `record_admin_action` 파라미터와
    속성 대입에서만 검사한다 — 선언형 생성자 kwargs는 `**kw: Any`라 검사되지 않으므로 행은
    `record_admin_action`으로만 만든다. 이것도 파이썬 쪽 검사일 뿐 DB 제약은 없다. 목록 밖 값이
    든 행이 있으면 유저 상세 응답 직렬화가 실패한다."""

    __tablename__ = "admin_action_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    action_type: Mapped[AdminActionType] = mapped_column(Text, nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    # 초안 삭제도 같은 이유 — 조치 로그는 남기고 사라진 작품 칸만 비운다.
    target_content_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contents.id", ondelete="SET NULL"), nullable=True
    )
    # 소유자는 관리자가 열람한 방도 지울 수 있다(방 삭제·탈퇴). 로그는 감사 기록이라 남기고
    # 사라진 방을 가리키던 칸만 비운다 — 누가 언제 누구의 채팅을 봤는지는 `target_user_id`로 남는다.
    target_chat_room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True
    )
    target_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("comments.id", name="fk_admin_action_logs_target_comment_id"), nullable=True
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
