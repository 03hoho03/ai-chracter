import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class StoryPromptTemplate(str, enum.Enum):
    BASIC = "basic"
    EMOTIONAL = "emotional"
    SIMULATION = "simulation"
    CUSTOM = "custom"


class StoryVersionDetail(Base):
    """techspec-db-schema.md §5. 1:1 extension of content_versions for type='story'."""

    __tablename__ = "story_version_details"

    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    one_liner: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    prompt_template: Mapped[StoryPromptTemplate] = mapped_column(
        Enum(StoryPromptTemplate, name="story_prompt_template"), nullable=False
    )
    setting_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    development_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)


class StartingSetup(Base):
    """techspec-db-schema.md §5. entity_id pattern (§1 원칙 4), order-sensitive list (§1 원칙 2)."""

    __tablename__ = "starting_setups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prologue: Mapped[str] = mapped_column(Text, nullable=False)
    opening_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    playguide: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_replies: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class StatDef(Base):
    """techspec-db-schema.md §5. Stats are independent per starting_setup, not shared."""

    __tablename__ = "stat_defs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    starting_setup_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("starting_setups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[int] = mapped_column(Integer, nullable=False)
    max_value: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_value: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
