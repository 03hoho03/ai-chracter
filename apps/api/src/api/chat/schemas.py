import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from api.chat.memory_fold import SUMMARY_MAX_LENGTH
from api.content.schemas import CharacterDraftPayload, MediaTagImage, StoryDraftPayload
from api.core.schema import CamelModel
from api.db.models.chat import ChatMessageReportReason, ChatMessageRole
from api.db.models.content import ContentType
from api.db.models.moderation import ReportStatus
from api.db.models.story import EndingRuleOperator, LogicalOp
from api.llm.chat_models import DEFAULT_CHAT_MODEL, ChatModelId, chat_turn_cost


class ChatRoomCreateRequest(CamelModel):
    content_id: uuid.UUID
    content_type: Literal["character", "story"]
    starting_setup_id: uuid.UUID | None = None


class ChatMessageCreateRequest(CamelModel):
    content: str = Field(min_length=1)
    shortcut_id: uuid.UUID | None = None


class ChatMessageEditRequest(CamelModel):
    content: str = Field(min_length=1)


class ChatRoomRenameRequest(CamelModel):
    name: str = Field(min_length=1)


class ChangeStartingSetupRequest(CamelModel):
    starting_setup_id: uuid.UUID


# 기억 노트 상한. 요약 상한(`SUMMARY_MAX_LENGTH`)과 함께 `GET .../memory`의 `limits`로 내려 보내
# FE가 사본을 들지 않게 한다. `strip_whitespace`가 길이 검사보다 먼저라 앞뒤 공백은 세지 않는다.
MEMORY_NOTE_MAX_LENGTH = 1_000

MemoryNoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MEMORY_NOTE_MAX_LENGTH)]
MemorySummaryText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=SUMMARY_MAX_LENGTH)]


class ChatRoomMemoryNoteRequest(CamelModel):
    """공백만 보내면 빈 노트로 저장된다(비우기와 같다)."""

    note: MemoryNoteText


class ChatRoomMemorySummaryRequest(CamelModel):
    """`version`은 편집 폼을 연 시점의 `memoryVersion`이다 — 그 사이 요약이 새로 접혔거나 대화가
    되감겼으면 서버 값과 달라 409로 거절된다(사용자 편집이 새 요약을 조용히 덮지 않게)."""

    summary: MemorySummaryText
    version: int


class ChatRoomMemoryRevertRequest(CamelModel):
    version: int


class ChatRoomMemorySummary(CamelModel):
    """방의 현재 요약. `can_revert`는 사용자가 이 요약을 고친 적이 있어 고치기 직전 본문으로 한 번
    되돌릴 수 있는가다 — AI가 새로 접은 요약은 되돌릴 대상이 없다."""

    text: str
    source: Literal["auto", "user"]
    can_revert: bool
    updated_at: datetime


class ChatRoomMemoryLimits(CamelModel):
    note_max_length: int
    summary_max_length: int


class ChatRoomMemoryResponse(CamelModel):
    """`summary`는 첫 접기 전이면 null이다(그때는 요약을 고칠 수 없다). `rolled_back_at`은 지난
    메시지를 고치거나 지워 요약이 이전 판으로 돌아간 마지막 시각이고, 초기화하면 null로 돌아간다."""

    note: str
    summary: ChatRoomMemorySummary | None
    version: int
    rolled_back_at: datetime | None
    limits: ChatRoomMemoryLimits


class ChatMessageResponse(CamelModel):
    id: uuid.UUID
    role: ChatMessageRole
    content: str
    created_at: datetime
    # 상황이미지 매칭 결과(entity_id). done 이벤트의 finalMessage와
    # `GET /chat-rooms/{id}` 재조회 둘 다에 실린다 — chat_messages.image_id에 저장되고
    # `_to_response`가 채운다.
    image_id: uuid.UUID | None = None
    # 인라인 렌더링용 presigned GET URL(원본 키). 저장하지 않고 응답 시점에
    # 서명한다(같은 15분 구간 안에서는 같은 URL, 받은 뒤 15~30분 유효). 해석이 안 되면
    # image_id는 남고 이 필드만 None.
    image_url: str | None = None
    # 스토리 미디어 북 그림의 픽셀 크기 — 화면이 원본 비율로 높이를 미리 잡는다. 캐릭터 상황별 이미지에는
    # 싣지 않는다(그쪽은 고정 비율 칸으로 그린다). 크기를 모르는 자산도 None 이다.
    image_width: int | None = None
    image_height: int | None = None


class ChatMessagePageResponse(CamelModel):
    """`GET /chat-rooms/{id}/messages?before=` 의 한 페이지 — 커서 메시지 바로 앞 메시지들을 오래된 것부터."""

    messages: list[ChatMessageResponse]
    has_more_before: bool


# 스토리 챗 전용 스냅샷. entity_id 기반 id를 쓴다 —
# 물리적 PK가 아니라 버전이 바뀌어도 안정적인 참조라 SSE statChange/endingReached,
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
    # 유일하게 물리적 PK인 필드(위 entity_id 기반 id들과 다름). GET /stories/starting-setups/
    # {id}/ending-collection이 물리적 PK를 요구하는데(POST /chat-rooms의 startingSetupId 관례와
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
    # `messageLimit` 로 꼬리만 받았을 때 그 앞에 메시지가 더 있는가. 전량 조회는 언제나 거짓이다.
    has_more_messages_before: bool
    content_snapshot: ChatRoomContentSnapshot | None = None
    latest_version_available: bool
    version_auto_upgraded: bool
    # 방이 고른 대화 프로필. None이 "선택 없음".
    # 옆의 nullable 필드들처럼 `= None`을 둔다 — 생성 타입에서 선택 필드가 되어 이 필드를 모르는
    # 기존 FE 픽스처(`toChatRoomState.test.ts`)가 깨지지 않는다. 응답에는 항상 실린다.
    persona_id: uuid.UUID | None = None
    # 아래 셋은 화면이 작가 글의 `{{user}}`·`{{char}}` 를 바꿀 때 쓰는 이름이다. 작품 쪽 둘은 방이 고정한 버전의 값이다
    # — 최신 발행본 상세로 대신하면 작가가 이름을 바꿔 재발행한 뒤 모델이 부른 이름과 화면의 이름이 갈린다.
    # 프로필 이름은 조회할 때 읽으므로 프로필 이름을 고치거나 지우면 다음 조회에 바로 반영된다. 기본값을 두는 이유는
    # `persona_id` 와 같다.
    # 방이 고른 대화 프로필의 이름. 프로필이 없으면 None.
    persona_name: str | None = None
    # 작품 기본 이름. 빈 값이면 대체어를 쓴다.
    default_user_name: str = Field(default_factory=str)
    # 작품명. 캐릭터 작품에서는 이것이 `{{char}}` 의 이름이다(스토리에는 `{{char}}` 가 없다).
    content_name: str = Field(default_factory=str)
    # 첫 메시지(작성자 글의 복사본)에 든 칸 id 형태 태그가 가리키는 그림 — 방이 고정한 버전의 칸으로
    # 해석한다. 사용자 메시지에 사용자가 친 태그는 보지 않는다(아무 칸 id 나 쳐서 원본을 받지 못하게).
    media_tag_images: dict[uuid.UUID, MediaTagImage] = Field(default_factory=dict)
    # 작품이 이용제한·삭제돼 이 방에서 대화를 이어갈 수 없는가. 방을 여는 순간 입력창 대신 안내를 띄우려고 싣는다 —
    # 없으면 보내 본 뒤 403 을 받고서야 안다.
    content_restricted: bool
    # 방이 고른 글쓰기 모델 — 저장된 값 그대로다(None 이 기본 모델). 레지스트리에서 내린 모델의 옛 값일 수도 있어 문자열이다.
    chat_model: str | None = None
    # 다음 턴이 실제로 쓸 모델과 그 턴의 클로버. 허용을 거뒀거나 레지스트리에서 내린 모델이면 Gemini 와 Gemini 가격이다 —
    # 화면은 저장 값이 아니라 이 둘을 보여 준다. 기본값은 이 필드를 모르는 생성 타입·픽스처와의 호환용이고(`persona_id` 와
    # 같은 이유), 응답에는 항상 실린다. 둘 다 `default_factory` 다 — 스키마에 `default` 가 실리면 생성 타입이 그 필드를 필수로
    # 만들어 기존 픽스처가 깨진다.
    effective_chat_model: ChatModelId = Field(default_factory=lambda: DEFAULT_CHAT_MODEL)
    turn_cost: int = Field(default_factory=lambda: chat_turn_cost(DEFAULT_CHAT_MODEL))
    created_at: datetime
    updated_at: datetime


class ChatRoomModelSelectRequest(CamelModel):
    """`PUT /chat-rooms/{id}/model`. 필드는 필수다 — 기본 모델로 되돌리기는 `"gemini"` 나 null 을 명시한다. 레지스트리 밖
    값은 422 다."""

    model: ChatModelId | None


class ChatRoomModelResponse(CamelModel):
    """지정한 뒤의 방 모델. 방 응답의 같은 이름 세 필드와 같은 값이다 — 화면이 방을 다시 읽지 않고 바로 반영한다."""

    chat_model: str | None
    effective_chat_model: ChatModelId
    turn_cost: int


class ChatModelItem(CamelModel):
    """`GET /chat-models` 의 한 항목 — 이 계정이 채팅방에 고를 수 있는 모델과 그 모델의 턴 가격."""

    id: ChatModelId
    name: str
    turn_cost: int


class ChatRoomListItem(CamelModel):
    id: uuid.UUID
    name: str
    last_message_preview: str
    created_at: datetime


class MyChatRoomListItem(CamelModel):
    id: uuid.UUID
    name: str
    content_id: uuid.UUID
    content_type: ContentType
    content_name: str
    thumbnail_url: str | None
    last_message_preview: str
    last_message_at: datetime | None
    created_at: datetime


class EndingCollectionItem(CamelModel):
    id: uuid.UUID
    name: str
    reached: bool
    epilogue: str | None = None
    hint: str | None = None
    # 도달한 엔딩 에필로그의 칸 id 형태 태그가 가리키는 그림. 도달하지 않은 엔딩은 비어 있다.
    media_tag_images: dict[uuid.UUID, MediaTagImage] = Field(default_factory=dict)


class ImageArchiveItem(CamelModel):
    id: uuid.UUID
    exposed: bool
    image_url: str


class StoryImageArchiveItem(ImageArchiveItem):
    """스토리 미디어 북 보관함의 칸 하나. `id` 는 칸 entity_id, `exposed` 는 사용자가 채팅에서 이 칸을 봤는가다
    (대화 중 판정·첫 메시지·엔딩 에필로그). 본 칸은 `image_url` 이 원본 썸네일이고, 못 본 칸은 블러본 썸네일과
    작가가 적은 `unlock_hint`(없으면 빈 문자열)다. `width`·`height` 는 그림의 픽셀 크기(모르면 null)로 화면이
    그림이 오기 전에 높이를 잡는 데 쓴다. `person_name` 은 늘 싣고, `scene_name` 은 본 칸에만 싣는다(못 본 칸은
    빈 문자열) — 장면 이름은 무엇이 그려졌는지를 미리 알려 주므로 해금 전까지 숨기고, 인물 이름은 누구의
    그림인지만 알려 주는 안내라 남긴다."""

    width: int | None = None
    height: int | None = None
    person_name: str = ""
    scene_name: str = ""
    unlock_hint: str = ""


class PlayGuideResponse(CamelModel):
    play_guide: str | None


# 빌더 미리보기 세션. 실제 ChatRoom과 형태는 비슷하지만
# Postgres에 전혀 기록되지 않고 Redis에만 저장되는 별도 상태다(지표 미반영, TTL 자동 소멸).
class PreviewSessionState(CamelModel):
    """Redis에 그대로 직렬화되는 세션 상태. `payload`는 발행/자동저장과 동일한
    formToServer 결과(검증 없이 그대로 저장)이고,
    `messages`/`stats`는 그 payload로부터 계산한 첫 턴 상태(오프닝 메시지/스탯 초기값)다."""

    payload: CharacterDraftPayload | StoryDraftPayload
    messages: list[ChatMessageResponse]
    stats: dict[str, float]
    turn_count: int = 0
    ending_reached: bool = False


class PreviewSessionStartResponse(CamelModel):
    preview_session_id: str


# SSE 이벤트 스키마.
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
    # 에필로그의 칸 id 형태 태그가 가리키는 그림(방이 고정한 버전 기준).
    media_tag_images: dict[uuid.UUID, MediaTagImage] = Field(default_factory=dict)


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


# 신고 메모 상한. 웹 신고 모달의 입력 상한과 같은 값이어야 한다 — 다르면 모달이 허용한 메모가
# 422로 거절된다. `strip_whitespace`가 길이 검사보다 먼저라 앞뒤 공백은 세지 않는다.
CHAT_REPORT_NOTE_MAX_LENGTH = 200

ChatReportNoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=CHAT_REPORT_NOTE_MAX_LENGTH)]


class ChatMessageReportCreateRequest(CamelModel):
    """메모는 선택이다. 공백만 보내면 메모 없음(NULL)으로 저장한다 — 빈 문자열과 NULL 두 가지로
    "메모 없음"이 갈리면 어드민이 둘을 따로 다뤄야 한다."""

    model_config = ConfigDict(extra="forbid")

    reason: ChatMessageReportReason
    note: ChatReportNoteText | None = None

    @field_validator("note")
    @classmethod
    def _blank_note_is_none(cls, value: str | None) -> str | None:
        return value or None


class ChatMessageReportResponse(CamelModel):
    report_id: uuid.UUID
    status: ReportStatus


class AdminChatMessageReportListItem(CamelModel):
    """`chat_room_id`·`chat_message_id`는 방 삭제·재생성·메시지 삭제로 대상이 지워지면 null이다."""

    id: uuid.UUID
    reporter_user_id: uuid.UUID
    chat_room_id: uuid.UUID | None
    chat_message_id: uuid.UUID | None
    reason: ChatMessageReportReason
    status: ReportStatus
    created_at: datetime
    evidence_expires_at: datetime
    evidence_available: bool


class AdminChatMessageReportListResponse(CamelModel):
    items: list[AdminChatMessageReportListItem]
    page: int
    total_pages: int
    total_count: int


class ChatMessageReportEvidenceResponse(CamelModel):
    """`available`이 false면(90일 만료·파기·탈퇴) 두 본문은 null이다. `available`이 true인데
    `user_message`가 null이면 신고된 응답 앞에 사용자 메시지가 없었다는 뜻이다(오프닝 신고)."""

    expires_at: datetime
    available: bool
    response: str | None
    user_message: str | None


class AdminChatMessageReportDetailResponse(CamelModel):
    id: uuid.UUID
    reporter_user_id: uuid.UUID
    chat_room_id: uuid.UUID | None
    chat_message_id: uuid.UUID | None
    reason: ChatMessageReportReason
    note: str | None
    status: ReportStatus
    created_at: datetime
    resolved_by_admin_id: uuid.UUID | None
    resolved_at: datetime | None
    evidence: ChatMessageReportEvidenceResponse


class AdminChatMessageReportActionRequest(CamelModel):
    """AI 응답에는 숨기거나 제재할 작성자가 없어 처리는 해결·기각 둘뿐이다."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["resolve", "reject"]
    admin_comment: str
