import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.content import ContentType, ContentVisibility, ModerationStatus

VisibilityFilter = Literal["all", "public", "link", "private"]


class DraftSummary(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_asset_id: uuid.UUID
    updated_at: datetime


class ContentSummary(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_asset_id: uuid.UUID
    thumbnail_url: str | None
    view_count: int
    visibility: ContentVisibility
    moderation_status: ModerationStatus


class UserProfileResponse(CamelModel):
    nickname: str
    bio: str | None
    profile_image_asset_id: uuid.UUID | None
    profile_image_url: str | None


class UpdateProfileRequest(CamelModel):
    nickname: str = Field(min_length=1)
    bio: str | None = None
    profile_image_asset_id: uuid.UUID | None = None
