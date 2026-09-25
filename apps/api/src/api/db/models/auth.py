import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class User(Base):
    """`profile_image_asset_id` -> assets.id is declared with use_alter because
    assets.owner_user_id -> users.id creates a table-creation cycle between
    users and assets; use_alter defers this FK to a post-create ALTER TABLE.
    `default_persona_id` -> user_personas.id is the same cycle
    (user_personas.user_id -> users.id).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    # 탈퇴 시 파기 대상이라 nullable. 빈 문자열은
    # "닉네임이 빈 사람"과 구분되지 않으므로 NULL을 쓴다.
    nickname: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 탈퇴 시 파기 대상이라 nullable.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    terms_agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    privacy_agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_image_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("assets.id", use_alter=True, name="fk_users_profile_image_asset_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terms_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    privacy_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 국외이전 동의는 처리방침 버전에 묶여
    # `transfer_version`에 그 시점의 처리방침 버전을 그대로 쓴다. 둘 다 nullable —
    # non-null로 두면 기존 회원 행을 채울 참값이 없다(그들은 국외이전 동의를 요구받은
    # 적이 없다). 시행일 재동의 게이트를 거치며 재동의 처리가 채운다.
    transfer_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transfer_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 레이트리밋 예외 플래그. 일일·토큰버킷만 면제하고 분당
    # 버스트는 유지한다. 값은 어드민 토글로만 바뀐다 — 상한값 자체는 상수라
    # 여기 담기지 않는다.
    rate_limit_exempt: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    # 잔액은 원장의 파생이 아니라
    # **불변식의 소재지**다 — 판정은 반드시 이 컬럼의 조건부 UPDATE로 하고 원장은 그
    # 트랜잭션에 얹는 기록이다. 순서를 뒤집어 원장 SUM으로 판정하면 이중 지불이 돌아온다.
    clover_balance: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # KST 날짜 두 개. NULL은
    # "한 번도 없었다"다. 게이트가 이미 이 행을 들고 있어(`is_rate_limit_exempt`) 추가 왕복이
    # 0이고, Redis와 달리 매일 pg_dump 백업을 탄다.
    clover_attendance_granted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    clover_spend_confirmed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 유저의 기본 대화 프로필 — 새 방이 이 값으로
    # 시작한다. 컬럼 하나라 "기본은 최대 1개"가 구조적으로 성립한다. FK는 "그 프로필이
    # **본인 것**인가"를 보장하지 못하므로 소유권은 API가 검사한다.
    default_persona_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("user_personas.id", use_alter=True, name="fk_users_default_persona_id"),
        nullable=True,
    )

    # 정상 경로는 조건부 UPDATE(`clover_balance >= :amount`)가 이미
    # 막으므로 이 제약이 발동할 일이 없다 — 갈리는 것은 우회 경로(어드민 회수 버그·수동 SQL·
    # 미래의 새 경로)에서 **조용히 음수가 되느냐 IntegrityError로 터지느냐** 하나뿐이고,
    # 돈이라 터지는 쪽을 골랐다.
    # 🔴 `alembic check`는 이 제약을 검증하지 못한다(alembic 1.18.5에 CHECK 비교자가 없다 —
    # `db/models/story.py`의 `EndingRule` docstring 참고). 검증은 행위 테스트가 유일하다.
    __table_args__ = (
        CheckConstraint("clover_balance >= 0", name="ck_users_clover_balance_non_negative"),
    )


class WithdrawnEmail(Base):
    """탈퇴 시 `users.email`이 복원 불가능한
    자리표시자로 바뀌므로, 재가입 차단은 평문 이메일 대신 이 테이블의 키 있는
    HMAC-SHA256 해시로 조회한다. 순수 SHA-256은 이메일 공간이 좁아 사전 공격으로 되돌릴
    수 있어 서버 비밀키를 붙인 HMAC을 쓴다. `withdrawn_at + 1년`이 지난 행은
    조회 시점에 무시하고, 행 자체는 매일 도는 백업 크론이 지운다
    (`scripts/ops/backup_db.py`).
    """

    __tablename__ = "withdrawn_emails"

    email_hmac: Mapped[str] = mapped_column(Text, primary_key=True)
    withdrawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GuardianConsent(Base):
    """법정대리인 자기신고 (실제 본인인증 없음, MVP)."""

    __tablename__ = "guardian_consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    guardian_name: Mapped[str] = mapped_column(Text, nullable=False)
    guardian_contact: Mapped[str] = mapped_column(Text, nullable=False)
    consent_agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)


class AdminUser(Base):
    """완전 별도 테이블, 공개 가입 없음."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
