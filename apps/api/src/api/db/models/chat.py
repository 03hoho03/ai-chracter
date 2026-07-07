import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ChatMessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatRoom(Base):
    """techspec-db-schema.md §6. Pinned to the content_version it was created against
    (PRD "이미 생성된 대화방은 생성 시점 버전에 고정")."""

    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    starting_setup_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    ending_reached: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    ending_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ending_reached_at_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_auto_upgraded: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatMessage(Base):
    """techspec-db-schema.md §6."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    role: Mapped[ChatMessageRole] = mapped_column(
        Enum(ChatMessageRole, name="chat_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatRoomStat(Base):
    """techspec-db-schema.md §6. The chat room's current value for a stat_defs entity_id
    (referenced by entity_id, not id, so it keeps matching across a version switch)."""

    __tablename__ = "chat_room_stats"

    chat_room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id"), primary_key=True
    )
    stat_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class StoryEndingUnlock(Base):
    """techspec-db-schema.md §6. US-057 엔딩 컬렉션: accumulates per user+starting_setup,
    never deleted/replaced once a row exists for a given ending."""

    __tablename__ = "story_ending_unlocks"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    starting_setup_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    ending_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_reached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CharacterImageExposure(Base):
    """techspec-db-schema.md §6. US-028 이미지 보관함: accumulates per user+character."""

    __tablename__ = "character_image_exposures"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    image_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_exposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
