import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class User(Base):
    """techspec-db-schema.md §2.

    `profile_image_asset_id` -> assets.id is declared with use_alter because
    assets.owner_user_id -> users.id creates a table-creation cycle between
    users and assets; use_alter defers this FK to a post-create ALTER TABLE.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    # legal-revision-goal-prompt.md LR-20: 탈퇴 시 파기 대상이라 nullable. 빈 문자열은
    # "닉네임이 빈 사람"과 구분되지 않으므로 NULL을 쓴다.
    nickname: Mapped[str | None] = mapped_column(Text, nullable=True)
    # legal-revision-goal-prompt.md LR-6: 탈퇴 시 파기 대상이라 nullable.
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
    # legal-revision-goal-prompt.md LR-2·LR-16: 국외이전 동의는 처리방침 버전에 묶여
    # `transfer_version`에 그 시점의 처리방침 버전을 그대로 쓴다(LR-3). 둘 다 nullable —
    # non-null로 두면 기존 회원 행을 채울 참값이 없다(그들은 국외이전 동의를 요구받은
    # 적이 없다). 시행일 재동의 게이트를 거치며 LR-5가 채운다.
    transfer_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transfer_version: Mapped[str | None] = mapped_column(Text, nullable=True)


class WithdrawnEmail(Base):
    """legal-revision-goal-prompt.md LR-7·LR-8. 탈퇴 시 `users.email`이 복원 불가능한
    자리표시자로 바뀌므로(LR-6), 재가입 차단은 평문 이메일 대신 이 테이블의 키 있는
    HMAC-SHA256 해시로 조회한다. 순수 SHA-256은 이메일 공간이 좁아 사전 공격으로 되돌릴
    수 있어 서버 비밀키를 붙인 HMAC을 쓴다(LR-8). `withdrawn_at + 1년`이 지난 행은
    조회 시점에 무시한다(LR-23) — 별도 삭제 배치는 없다.
    """

    __tablename__ = "withdrawn_emails"

    email_hmac: Mapped[str] = mapped_column(Text, primary_key=True)
    withdrawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GuardianConsent(Base):
    """techspec-db-schema.md §2. 법정대리인 자기신고 (실제 본인인증 없음, MVP)."""

    __tablename__ = "guardian_consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    guardian_name: Mapped[str] = mapped_column(Text, nullable=False)
    guardian_contact: Mapped[str] = mapped_column(Text, nullable=False)
    consent_agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)


class AdminUser(Base):
    """techspec-db-schema.md §2. 완전 별도 테이블, 공개 가입 없음."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
