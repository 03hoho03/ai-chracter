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
    nickname: Mapped[str] = mapped_column(Text, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
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
