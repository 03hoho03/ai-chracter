import enum
import uuid
from datetime import datetime

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.media import AssetStatus


class AssetPurpose(str, enum.Enum):
    """techspec-backend-media.md §1. Extend as new upload flows need a purpose."""

    PROFILE_IMAGE = "profile-image"
    SITUATIONAL_IMAGE = "situational-image"


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


class GeneratedImageItem(CamelModel):
    """techspec-backend-media.md §3: `GET /me/generated-images` item shape."""

    asset_id: uuid.UUID
    image_url: str
    created_at: datetime
