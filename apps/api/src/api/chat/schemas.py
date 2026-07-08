import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.chat import ChatMessageRole
from api.db.models.content import ContentType
from api.db.models.story import EndingRuleOperator, LogicalOp


class ChatRoomCreateRequest(CamelModel):
    content_id: uuid.UUID
    content_type: Literal["character", "story"]
    starting_setup_id: uuid.UUID | None = None


class ChatMessageCreateRequest(CamelModel):
    content: str = Field(min_length=1)
    shortcut_id: uuid.UUID | None = None


class ChatRoomRenameRequest(CamelModel):
    name: str = Field(min_length=1)


class ChatMessageResponse(CamelModel):
    id: uuid.UUID
    role: ChatMessageRole
    content: str
    created_at: datetime


# 스토리 챗 전용 스냅샷 (techspec-content-versioning.md §2). entity_id 기반 id를 쓴다 —
# 물리적 PK가 아니라 버전이 바뀌어도 안정적인 참조(§1 원칙 4)라 SSE statChange/endingReached,
# chat_room_stats, story_ending_unlocks가 참조하는 값과 그대로 일치한다.
class StatDefSnapshot(CamelModel):
    id: uuid.UUID
    name: str
    icon: str
    color: str
    min_value: int
    max_value: int
    initial_value: int
    unit: str | None
    description: str


class ShortcutSnapshot(CamelModel):
    id: uuid.UUID
    name: str
    description: str
    prompt: str


class EndingRuleItem(CamelModel):
    kind: Literal["rule"] = "rule"
    id: uuid.UUID
    stat_id: uuid.UUID
    operator: EndingRuleOperator
    threshold: float
    next_op: LogicalOp | None


class EndingRuleGroupItem(CamelModel):
    kind: Literal["group"] = "group"
    id: uuid.UUID
    rules: list[EndingRuleItem]
    next_op: LogicalOp | None


EndingRuleListItem = Annotated[
    EndingRuleItem | EndingRuleGroupItem,
    Field(discriminator="kind"),
]


class EndingSnapshot(CamelModel):
    id: uuid.UUID
    name: str
    turn_count_gate: int
    judgment_prompt: str
    epilogue: str | None
    hint: str | None
    stat_rules: list[EndingRuleListItem]


class ChatRoomContentSnapshot(CamelModel):
    stats: list[StatDefSnapshot]
    endings: list[EndingSnapshot]
    shortcuts: list[ShortcutSnapshot]
    suggested_replies: list[str]


class ChatRoomResponse(CamelModel):
    id: uuid.UUID
    content_id: uuid.UUID
    content_type: ContentType
    name: str
    starting_setup_id: uuid.UUID | None = None
    turn_count: int
    ending_reached: bool
    stats: dict[str, float] | None = None
    messages: list[ChatMessageResponse]
    content_snapshot: ChatRoomContentSnapshot | None = None
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
class ChatTokenEvent(CamelModel):
    type: Literal["token"] = "token"
    delta: str


class ChatStatChangeEvent(CamelModel):
    type: Literal["statChange"] = "statChange"
    stat_id: str
    new_value: float


class ChatEndingReachedEvent(CamelModel):
    type: Literal["endingReached"] = "endingReached"
    ending_id: uuid.UUID
    epilogue: str | None


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
    ChatTokenEvent
    | ChatStatChangeEvent
    | ChatEndingReachedEvent
    | ChatPolicyWarningEvent
    | ChatDoneEvent
    | ChatErrorEvent,
    Field(discriminator="type"),
]
