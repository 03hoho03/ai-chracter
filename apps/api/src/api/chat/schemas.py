import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.chat import ChatMessageRole
from api.db.models.content import ContentType


class ChatRoomCreateRequest(CamelModel):
    content_id: uuid.UUID
    content_type: Literal["character"]


class ChatRoomRenameRequest(CamelModel):
    name: str = Field(min_length=1)


class ChatMessageResponse(CamelModel):
    id: uuid.UUID
    role: ChatMessageRole
    content: str
    created_at: datetime


class ChatRoomResponse(CamelModel):
    id: uuid.UUID
    content_id: uuid.UUID
    content_type: ContentType
    name: str
    turn_count: int
    ending_reached: bool
    messages: list[ChatMessageResponse]
    latest_version_available: bool
    version_auto_upgraded: bool
    created_at: datetime
    updated_at: datetime


class ChatRoomListItem(CamelModel):
    id: uuid.UUID
    name: str
    last_message_preview: str
    created_at: datetime
