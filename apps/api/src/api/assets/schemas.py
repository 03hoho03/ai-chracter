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
