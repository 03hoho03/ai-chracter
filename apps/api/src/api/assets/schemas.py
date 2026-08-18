import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.content import ContentType
from api.db.models.media import AssetStatus


class AssetPurpose(str, enum.Enum):
    """techspec-backend-media.md §1. Extend as new upload flows need a purpose."""

    PROFILE_IMAGE = "profile-image"
    CONTENT_THUMBNAIL = "content-thumbnail"
    SITUATIONAL_IMAGE = "situational-image"


# Per-purpose upload size limits in bytes, applied to the *resized* result the FE
# uploads (tasks/prd-image-delivery-optimization.md) — the normal path stays far
# below these, so the server-side check is purely a bypass safety net.
UPLOAD_SIZE_LIMIT_BYTES: dict[AssetPurpose, int] = {
    AssetPurpose.PROFILE_IMAGE: 2 * 1024 * 1024,
    AssetPurpose.CONTENT_THUMBNAIL: 5 * 1024 * 1024,
    AssetPurpose.SITUATIONAL_IMAGE: 5 * 1024 * 1024,
}


class PresignedUploadRequest(CamelModel):
    content_type: str = Field(min_length=1)
    purpose: AssetPurpose


class PresignedUploadResponse(CamelModel):
    upload_url: str
    asset_id: uuid.UUID
    expires_at: datetime


class AssetCompleteResponse(CamelModel):
    asset_id: uuid.UUID
    status: AssetStatus


class RegisterSituationalImageRequest(CamelModel):
    entity_id: uuid.UUID
    content_version_id: uuid.UUID
    trigger_condition: str = Field(min_length=1)
    order: int


class SituationalImageResponse(CamelModel):
    entity_id: uuid.UUID
    image_asset_id: uuid.UUID
    blurred_asset_id: uuid.UUID
    trigger_condition: str
    order: int


GeneratedImageUsageField = Literal["thumbnail", "situationalImage"]


class GeneratedImageUsage(CamelModel):
    """One content referencing a generated asset (US-001, tasks/prd-image-library.md).

    Draft and published versions both count as "in use"; versions of the same
    content referencing the asset with the same field are merged into one entry.
    """

    content_id: uuid.UUID
    content_type: ContentType
    content_title: str
    field: GeneratedImageUsageField


class GeneratedImageItem(CamelModel):
    """techspec-backend-media.md §3: `GET /me/generated-images` item shape."""

    asset_id: uuid.UUID
    image_url: str
    created_at: datetime
    usages: list[GeneratedImageUsage]
