import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AssetKind(str, enum.Enum):
    ORIGINAL = "original"
    BLURRED = "blurred"
    THUMBNAIL = "thumbnail"


class AssetStatus(str, enum.Enum):
    """techspec-backend-media.md §1: row is created pending at presigned-upload
    time, and flipped to ready once POST /assets/{id}/complete confirms the S3
    object exists."""

    PENDING = "pending"
    READY = "ready"


class Asset(Base):
    """techspec-db-schema.md §9. Row is created (status=pending) when a presigned
    upload URL is issued, and flipped to status=ready once upload completes."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[AssetKind] = mapped_column(Enum(AssetKind, name="asset_kind"), nullable=False)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"), nullable=False, default=AssetStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
