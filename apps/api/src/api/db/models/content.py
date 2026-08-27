import enum
import uuid
from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ContentType(str, enum.Enum):
    CHARACTER = "character"
    STORY = "story"


class ContentTarget(str, enum.Enum):
    FEMALE = "female"
    MALE = "male"
    ALL = "all"


class ContentVisibility(str, enum.Enum):
    PUBLIC = "public"
    LINK = "link"
    PRIVATE = "private"


class ModerationStatus(str, enum.Enum):
    NORMAL = "normal"
    RESTRICTED = "restricted"
    DELETED = "deleted"


class Genre(Base):
    """techspec-db-schema.md §3. Master data, seeded via migration."""

    __tablename__ = "genres"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Content(Base):
    """techspec-db-schema.md §3. Shared character/story content header.

    `current_published_version_id` -> content_versions.id is declared with use_alter
    because content_versions.content_id -> contents.id creates a table-creation cycle
    between contents and content_versions; use_alter defers this FK to a post-create
    ALTER TABLE (same pattern as users/assets, see auth.py).

    `genre_id`/`target` are nullable even though the registration tab treats them as
    required (US-083 publish validation enforces that) — a brand-new draft
    (`POST /contents`, US-082) has neither set yet, so the DB must allow the empty state.
    """

    __tablename__ = "contents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[ContentType] = mapped_column(Enum(ContentType, name="content_type"), nullable=False)
    creator_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    genre_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("genres.id"), nullable=True)
    target: Mapped[ContentTarget | None] = mapped_column(
        Enum(ContentTarget, name="content_target"), nullable=True
    )
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    visibility: Mapped[ContentVisibility] = mapped_column(
        Enum(ContentVisibility, name="content_visibility"), nullable=False
    )
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        Enum(ModerationStatus, name="moderation_status"), nullable=False
    )
    current_published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "content_versions.id", use_alter=True, name="fk_contents_current_published_version_id"
        ),
        nullable=True,
    )
    # 초안이 현재 발행본과 달라졌는지. 타임스탬프로는 판정할 수 없어 명시적 플래그다 —
    # `ContentVersion`에 `updated_at`이 없고, 초안의 자식 행들(상황이미지·시작설정 등)은 별도
    # 테이블이라 편집해도 버전 행을 건드리지 않는다. 자동저장이 세우고 발행·편집취소가 내린다.
    has_unpublished_changes: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), nullable=False
    )
    view_count: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    like_count: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    chat_count: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentVersion(Base):
    """techspec-db-schema.md §3. Immutable snapshot; draft = the row with published_at IS NULL."""

    __tablename__ = "content_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail_description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Favorite(Base):
    """techspec-db-schema.md §7."""

    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Like(Base):
    """techspec-db-schema.md §7."""

    __tablename__ = "likes"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
