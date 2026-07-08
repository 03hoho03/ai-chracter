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
    # US-072 상황별 이미지 매칭(캐릭터 챗 전용) 결과. 판단 시점에만 채워지는 세션 한정
    # 필드라 chat_messages 테이블엔 컬럼이 없다 — GET 재조회 시 항상 None(techspec-chat-character.md
    # §1: 별도 이벤트가 아니라 done 이벤트의 finalMessage에만 실려온다).
    image_id: uuid.UUID | None = None


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
    # US-070 — 유일하게 물리적 PK인 필드(위 entity_id 기반 id들과 다름). GET /stories/starting-setups/
    # {id}/ending-collection(US-069)이 물리적 PK를 요구하는데(POST /chat-rooms의 startingSetupId 관례와
    # 동일), ChatRoomResponse.startingSetupId(entity_id, 이미 테스트로 고정됨)로는 그 호출을 만들 수
    # 없어 room이 고정한 물리적 StartingSetup 행의 id를 별도로 노출한다.
    pinned_starting_setup_id: uuid.UUID


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


class EndingCollectionItem(CamelModel):
    id: uuid.UUID
    name: str
    reached: bool
    epilogue: str | None = None
    hint: str | None = None


class PlayGuideResponse(CamelModel):
    play_guide: str | None


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
