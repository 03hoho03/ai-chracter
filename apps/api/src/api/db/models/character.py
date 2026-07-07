import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class CharacterVersionDetail(Base):
    """techspec-db-schema.md §4. 1:1 extension of content_versions for type='character'."""

    __tablename__ = "character_version_details"

    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    one_liner: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    intro: Mapped[str] = mapped_column(Text, nullable=False)
    example_dialogues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    character_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    playguide: Mapped[str | None] = mapped_column(Text, nullable=True)


class SituationalImage(Base):
    """techspec-db-schema.md §4. entity_id pattern (§1 원칙 4): `id` is the physical
    per-version PK, `entity_id` is the client-generated UUID that stays stable across
    versions (used for cross-version image-vault accumulation, US-028).
    """

    __tablename__ = "situational_images"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    image_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    blurred_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    trigger_condition: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
