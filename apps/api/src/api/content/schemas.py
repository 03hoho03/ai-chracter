import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.content import ContentType, ContentVisibility, ModerationStatus
from api.db.models.moderation import ReportReasonCategory

VisibilityFilter = Literal["all", "public", "link", "private"]


class DraftSummary(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_asset_id: uuid.UUID | None
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


class GenreResponse(CamelModel):
    id: uuid.UUID
    name: str
    sort_order: int


class ContentListItem(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_url: str | None
    view_count: int
    creator_user_id: uuid.UUID
    creator_nickname: str


class ContentListResponse(CamelModel):
    items: list[ContentListItem]
    next_cursor: str | None


class StartingSetupSummary(CamelModel):
    id: uuid.UUID
    name: str
    prologue: str


AccessStatusKind = Literal["accessible", "restricted", "deleted"]


class ContentAccessStatus(CamelModel):
    """Mirrors techspec-content-versioning.md §1's `resolveAccessStatus` union:
    `visibility` is only meaningful when `kind == "accessible"`."""

    kind: AccessStatusKind
    visibility: ContentVisibility | None = None


class ContentDetailResponse(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_url: str | None
    creator_user_id: uuid.UUID
    creator_nickname: str
    genre_id: uuid.UUID
    genre_name: str
    hashtags: list[str]
    one_liner: str
    detail_description: str
    chat_count: int
    like_count: int
    is_liked: bool
    is_favorited: bool
    starting_setups: list[StartingSetupSummary] | None
    version_number: int
    updated_at: datetime
    access_status: ContentAccessStatus
    is_owner: bool


class ContentVersionSummary(CamelModel):
    version_number: int
    published_at: datetime


class ReportRequest(CamelModel):
    reason_category: ReportReasonCategory


class ContentCreateRequest(CamelModel):
    """techspec-backend-content.md §1.2. Only `'character'` is implemented so far —
    US-084 widens this to also accept `'story'`."""

    type: Literal["character"]


class ContentCreateResponse(CamelModel):
    content_id: uuid.UUID


class ExampleDialogueItem(CamelModel):
    id: str
    user_line: str
    character_line: str


class CharacterSituationalImageDraftInput(CamelModel):
    """`PATCH /contents/{id}/draft` payload item — only the fields this endpoint owns.
    `imageAssetId`/blurred variant are exclusively written by
    `POST /assets/{id}/register-situational-image` (US-071)."""

    id: uuid.UUID
    trigger_condition: str


class CharacterDraftPayload(CamelModel):
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    intro: str
    example_dialogues: list[ExampleDialogueItem]
    character_prompt: str
    playguide: str | None
    situational_images: list[CharacterSituationalImageDraftInput]


class CharacterSituationalImageItem(CamelModel):
    id: uuid.UUID
    image_asset_id: uuid.UUID | None
    trigger_condition: str


class CharacterDraftResponse(CamelModel):
    id: uuid.UUID
    type: Literal["character"] = "character"
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    intro: str
    example_dialogues: list[ExampleDialogueItem]
    character_prompt: str
    playguide: str | None
    situational_images: list[CharacterSituationalImageItem]
