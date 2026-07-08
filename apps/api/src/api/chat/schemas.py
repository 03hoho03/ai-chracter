import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.chat import ChatMessageRole
from api.db.models.content import ContentType


class ChatRoomCreateRequest(CamelModel):
    content_id: uuid.UUID
    content_type: Literal["character"]


class ChatMessageCreateRequest(CamelModel):
    content: str = Field(min_length=1)


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


# SSE 이벤트 스키마 (techspec-backend-chat.md §2, techspec-chat-story.md §1.2가 유일한 정의처).
# statChange/endingReached는 스토리 챗 전용(US-059/US-062)이라 여기서는 다루지 않는다.
class ChatTokenEvent(CamelModel):
    type: Literal["token"] = "token"
    delta: str


class ChatPolicyWarningEvent(CamelModel):
    type: Literal["policyWarning"] = "policyWarning"
    message: str


class ChatDoneEvent(CamelModel):
    type: Literal["done"] = "done"
    final_message: ChatMessageResponse


class ChatErrorEvent(CamelModel):
    type: Literal["error"] = "error"
    message: str


ChatStreamEvent = Annotated[
    ChatTokenEvent | ChatPolicyWarningEvent | ChatDoneEvent | ChatErrorEvent,
    Field(discriminator="type"),
]
