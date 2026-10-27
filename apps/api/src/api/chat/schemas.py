import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from api.chat.memory_fold import SUMMARY_MAX_LENGTH
from api.content.schemas import CharacterDraftPayload, MediaTagImage, StoryDraftPayload
from api.core.schema import CamelModel, NoNul
from api.db.models.chat import (
    ChatMessageReportReason,
    ChatMessageRole,
    EpisodeAssertedBy,
    FactAssertedBy,
    FactKind,
    FactTruthStatus,
)
from api.db.models.content import ContentType
from api.db.models.moderation import ReportStatus
from api.db.models.story import EndingRuleOperator, LogicalOp
from api.llm.chat_models import (
    CHAT_MODELS_BY_ID,
    DEFAULT_CHAT_MODEL,
    DEFAULT_CHAT_ROOM_MODEL,
    ChatModelId,
    ChatRoomModelId,
    chat_turn_cost,
)


class ChatRoomCreateRequest(CamelModel):
    content_id: uuid.UUID
    content_type: Literal["character", "story"]
    starting_setup_id: uuid.UUID | None = None
    # 시작 화면에서 고른 대화 프로필. 없으면 기본 프로필로 시작한다(이 필드를 모르는 예전 화면도 그대로 된다).
    persona_id: uuid.UUID | None = None


class ChatTurnRequest(CamelModel):
    """채팅 턴(전송·재생성·편집·빌더 미리보기) 요청이 함께 싣는 칸. 재생성은 이 칸만 있는 본문을 받는다(본문 없이도 된다).

    `price_version` 은 화면이 공개 가격 응답에서 받은 가격표 버전이다. 이 턴이 클로버로 낼 턴인데 서버 버전과 다르면 차감
    게이트가 깎기 전에 409 로 멈춘다(`core/rate_limit_gate.py`). 비우면 대조하지 않는다 — 버전을 모르는 배포 전 화면이 그렇다."""

    price_version: int | None = None


class ChatMessageCreateRequest(ChatTurnRequest):
    content: Annotated[str, Field(min_length=1), NoNul]
    shortcut_id: uuid.UUID | None = None


# 메시지 수정·삭제가 지운 턴의 스탯을 어떻게 되돌렸는지 — 값의 뜻은 `chat/stat_rewind.py` 모듈 설명.
StatRewind = Literal["rewound", "partial", "kept"]


class ChatMessageEditRequest(ChatTurnRequest):
    content: Annotated[str, Field(min_length=1), NoNul]


class ChatMessageDeleteResponse(CamelModel):
    """메시지 삭제의 응답. `stat_rewind` 로 화면이 안내 문구를 고른다(사용자 메시지·오프닝 삭제처럼 알릴 것이 없으면 null)."""

    stat_rewind: StatRewind | None


class ChatRoomRenameRequest(CamelModel):
    name: str = Field(min_length=1)


class ChangeStartingSetupRequest(CamelModel):
    starting_setup_id: uuid.UUID


# 기억 노트 상한. 요약 상한(`SUMMARY_MAX_LENGTH`)과 함께 `GET .../memory`의 `limits`로 내려 보내
# FE가 사본을 들지 않게 한다. `strip_whitespace`가 길이 검사보다 먼저라 앞뒤 공백은 세지 않는다.
MEMORY_NOTE_MAX_LENGTH = 1_000

MemoryNoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MEMORY_NOTE_MAX_LENGTH), NoNul]
MemorySummaryText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=SUMMARY_MAX_LENGTH), NoNul]


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


class ChatRoomMemoryRegenerateRequest(CamelModel):
    """`version` 은 확인 대화를 연 시점의 `memoryVersion`, `expected_cost` 는 확인 대화에 보인 가격이다. 버전이 다르면(그사이
    요약이 새로 접혔거나 고쳐졌거나 되감겼다) 409, 가격이 지금 가격과 다르면 409 — 둘 다 클로버를 깎기 전에 거절한다."""

    version: int
    expected_cost: int


class ChatRoomMemorySummary(CamelModel):
    """방의 현재 요약. `can_revert`는 사용자가 이 요약을 고쳤거나 AI 로 다시 만들어 그 직전 본문으로 한 번
    되돌릴 수 있는가다 — 대화가 길어져 AI가 새로 접은 요약은 되돌릴 대상이 없다."""

    text: str
    source: Literal["auto", "user"]
    can_revert: bool
    updated_at: datetime


class ChatRoomMemoryLimits(CamelModel):
    note_max_length: int
    summary_max_length: int


class ChatRoomMemoryFeatures(CamelModel):
    """기억 화면이 문구를 가를 서버 스위치. `items_visible` 은 장면·사실 목록 API 가 열려 있는가(닫혀 있으면 그 라우트가
    404 라, 화면은 목록을 부르지 않고 "목록 없음"과 구별한다). `summary_folding` 은 긴 방의 대화를 요약으로 접는 생성 윈도우가
    켜져 있는가다 — 꺼져 있으면 새 요약이 생기지 않고 있는 요약도 응답에 쓰이지 않는다."""

    items_visible: bool
    summary_folding: bool


class ChatRoomMemoryResponse(CamelModel):
    """`summary`는 첫 접기 전이면 null이다(그때는 요약을 고칠 수 없다). `rolled_back_at`은 지난
    메시지를 고치거나 지워 요약이 이전 판으로 돌아간 마지막 시각이고, 초기화하면 null로 돌아간다."""

    note: str
    summary: ChatRoomMemorySummary | None
    version: int
    rolled_back_at: datetime | None
    limits: ChatRoomMemoryLimits
    features: ChatRoomMemoryFeatures


class ChatRoomMemoryEpisodeItem(CamelModel):
    """장면 기억 하나. `asserted_by` 는 장면의 내용을 누가 말했는가(사용자·캐릭터·서술·섞임)다 — 캐릭터가 대사로만 말한 장면은
    회상에 실리지 않는다. 턴은 추출 시점의 응답 순번이라 그 뒤 메시지가 지워졌으면 근사값이다."""

    id: uuid.UUID
    title: str
    detail: str
    asserted_by: EpisodeAssertedBy
    start_turn: int
    end_turn: int


class ChatRoomMemoryFactItem(CamelModel):
    """키마다 지금 이긴 사실 하나. `kind` 가 `relation` 이면 `subject`·`object` 사이 관계이고 `fact` 면 `subject` 의
    `attribute` 다. `truth_label` 은 `truth_status` 를 사용자에게 보일 말로 바꾼 것이고, `speaker` 는 그 말을 한 인물(말한 사람
    꼬리표, 없으면 null)이다. 아는 사람 목록은 싣지 않는다 — 응답에서 비밀을 가리는 내부 장치다."""

    id: uuid.UUID
    fact_key: str
    kind: FactKind
    subject: str
    object: str | None
    attribute: str | None
    value: str
    truth_status: FactTruthStatus
    truth_label: str
    asserted_by: FactAssertedBy
    speaker: str | None
    start_turn: int
    end_turn: int


class ChatRoomMemoryImpressionItem(CamelModel):
    """관계 인상 하나 — 요약 접기 몇 번을 한 묶음으로 읽고 인물 사이 감정·태도의 흐름을 적은 읽기 전용 글. 근거 행 id 는 싣지
    않고 개수만 싣는다. `scene_count` 는 지금 남아 있는 근거 장면 수, `fact_count` 는 지금 남아 있는 근거 사실 행의 서로 다른 키
    수다(근거에는 한 키의 옛 값 행도 들어 있다). `turn_start`·`turn_end` 는 남은 근거 행들의 턴 범위라 근사값이고, 근거 행이
    하나도 남지 않았으면 null 이다."""

    id: uuid.UUID
    text: str
    created_at: datetime
    turn_start: int | None
    turn_end: int | None
    scene_count: int
    fact_count: int


class ChatRoomMemoryItemsResponse(CamelModel):
    """방의 장면·사실 기억. 둘 다 지금 요약 커서까지 접힌 것이고, 요약이 아직 없으면 둘 다 비어 있다.

    - `episodes` 는 일어난 순서로 한 페이지다. `next_cursor` 를 `cursor` 로 다시 보내면 다음 페이지이고, 마지막 페이지면 null.
    - `facts` 는 키마다 이긴 행 전부다(페이지 없음, 이긴 행을 쓴 순서). 페이지마다 같은 목록이 온다.
    - `episodes_used_in_replies`·`facts_used_in_replies` 는 이 방의 다음 턴에 그 기억이 응답 프롬프트에 실릴 수 있는가 — 기억
      스위치가 켜져 있고 이 방의 레인과 다음 턴 모델이 기억 사용 범위에 들 때만 참이다. 거짓이어도 기억은 계속 쌓인다.
    - `impressions` 는 이 방의 관계 인상을 최근 묶음 먼저 전부 싣는다(페이지 없음, 페이지마다 같은 목록). 인상 보기 스위치가
      꺼져 있거나 이 방의 레인과 다음 턴 모델이 기억 사용 범위 밖이면 — 인상 행이 있어도 — null 이라 화면이 인상 구획을 그리지
      않는다. 그 밖에는 목록이고 인상이 없으면 빈 목록이다."""

    episodes: list[ChatRoomMemoryEpisodeItem]
    next_cursor: str | None
    facts: list[ChatRoomMemoryFactItem]
    episodes_used_in_replies: bool
    facts_used_in_replies: bool
    impressions: list[ChatRoomMemoryImpressionItem] | None


class ChatRoomMemoryFactForgetPreview(CamelModel):
    """사실 키 하나를 잊기 전 확인 대화에 보일 것. `episode_count` 는 함께 잊을 장면 수다 — 아는 사람이 정해진(비밀) 사실이면
    그 키의 근거 대화 구간과 겹치는 장면도 함께 잊는다(사실만 지우면 그 장면이 응답에 다시 실릴 수 있다). 공개 사실이면 0."""

    episode_count: int


class StoryScene(CamelModel):
    """장면 헤더의 장면 — 지금 장소와 시간. 모르는 칸은 null 이다. 같은 이름의 미디어 북 장면 축·장면 기억과는 다른 것이다."""

    place: str | None
    time: str | None


def story_scene_of(value: dict[str, Any] | None) -> StoryScene | None:
    """저장된 장면 칸(`chat_messages.scene`·`chat_previous_responses.scene`)을 응답 모양으로. 비어 있으면 `None`."""
    return StoryScene.model_validate(value) if value is not None else None


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
    # 장면 헤더를 켠 스토리 방의 AI 응답에 저장된 그 턴의 장면(`chat_messages.scene`). 꺼진 작품·켜기 전 메시지·사용자
    # 메시지·오프닝은 null 이다. 화면은 마지막 AI 응답의 장면을 헤더에 보이고, 아직 AI 턴이 없으면 방 스냅숏의 첫 장면을 보인다.
    scene: StoryScene | None = None


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
    # 작가가 플레이어에게 보여 주려고 쓴 짧은 설명(게이지 칸을 눌러 여는 팝오버). 판정용 설명과 다른 칸이고
    # 판정·생성 프롬프트에는 실리지 않는다. 판정용 설명은 판정 재료라 이 스냅숏에 싣지 않는다. 숨긴 스탯은 스탯째
    # 스냅숏에서 빠지므로 여기 실리는 것은 보이는 스탯 것뿐이다. 쓰지 않았으면 None.
    player_description: str | None


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
    """플레이어 방 응답의 엔딩. 판정 문안은 판정 재료이고 에필로그는 아직 닿지 않은 엔딩의 내용이라 싣지 않는다 — 도달한
    엔딩의 에필로그는 방 응답의 `ending` 칸에 실린다. 힌트는 엔딩 모음이 미도달 엔딩에만 골라 싣는 칸이라 여기에는 없다."""

    id: uuid.UUID
    name: str
    turn_count_gate: int
    # 언제나 빈 목록이다. 이 칸을 목록으로 읽는 옛 화면이 깨지지 않도록 키만 남겨 둔다.
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
    # 작가가 켠 장면 헤더(방이 고정한 버전의 토글)와 시작설정의 첫 장면. 첫 장면은 방에 아직 AI 턴이 없을 때 헤더에 보인다 —
    # 작가가 장소·시간을 둘 다 비워 두었으면 null 이다.
    # 기본값을 `default_factory` 로 두는 이유는 `KeywordNoteDraftInput`(content/schemas.py)의 같은 주석과 같다 — OpenAPI 에
    # `default` 가 찍히면 FE 생성 타입이 이 칸을 필수로 만든다.
    scene_header_enabled: bool = Field(default_factory=bool)
    initial_scene: StoryScene | None = None


class ChatRoomEnding(CamelModel):
    """방이 도달한 엔딩. 엔딩 도달 이벤트(`ChatEndingReachedEvent`)와 같은 세 칸이다 — 이벤트는 그 턴의 스트림에만
    실리므로, 방을 다시 받아도(새로고침·재조회) 화면이 에필로그를 그리도록 방 응답에도 싣는다."""

    ending_id: uuid.UUID
    epilogue: str | None
    # 에필로그의 칸 id 형태 태그가 가리키는 그림(방이 고정한 버전 기준). 첫 메시지의 맵(`media_tag_images`)과 따로 둔다.
    media_tag_images: dict[uuid.UUID, MediaTagImage] = Field(default_factory=dict)


class ChatRoomResponse(CamelModel):
    id: uuid.UUID
    content_id: uuid.UUID
    content_type: ContentType
    name: str
    starting_setup_id: uuid.UUID | None = None
    turn_count: int
    ending_reached: bool
    # 도달한 엔딩. 도달 전·초기화 뒤, 그리고 방 버전에 그 엔딩이 없으면(버전이 옮겨 가며 빠졌으면) None 이다 — 그때도
    # `ending_reached` 는 그대로라 도달 표시만 남는다. 기본값을 두는 이유는 `persona_id` 와 같다(이 칸을 모르는 화면·픽스처).
    ending: ChatRoomEnding | None = None
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
    # 아래 둘은 화면이 작가 글의 `{{user}}`·`{{char}}` 를 바꿀 때 쓰는 이름이다. 작품명은 방이 고정한 버전의 값이다
    # — 최신 발행본 상세로 대신하면 작가가 이름을 바꿔 재발행한 뒤 모델이 부른 이름과 화면의 이름이 갈린다.
    # 프로필 이름은 조회할 때 읽으므로 프로필 이름을 고치거나 지우면 다음 조회에 바로 반영된다. 기본값을 두는 이유는
    # `persona_id` 와 같다.
    # 방이 고른 대화 프로필의 이름. 프로필이 없으면 None — 화면은 대체어를 쓴다.
    persona_name: str | None = None
    # 작품명. 캐릭터 작품에서는 이것이 `{{char}}` 의 이름이다(스토리에는 `{{char}}` 가 없다).
    content_name: str = Field(default_factory=str)
    # 첫 메시지(작성자 글의 복사본)에 든 칸 id 형태 태그가 가리키는 그림 — 방이 고정한 버전의 칸으로
    # 해석한다. 사용자 메시지에 사용자가 친 태그는 보지 않는다(아무 칸 id 나 쳐서 원본을 받지 못하게).
    media_tag_images: dict[uuid.UUID, MediaTagImage] = Field(default_factory=dict)
    # 작품이 이용제한·삭제돼 이 방에서 대화를 이어갈 수 없는가. 방을 여는 순간 입력창 대신 안내를 띄우려고 싣는다 —
    # 없으면 보내 본 뒤 403 을 받고서야 안다.
    content_restricted: bool
    # 이 방에서 소설을 새로 만들 수 없는가 — 작가가 소설화를 허용하지 않았고, 내가 그 작가가 아니며, 이 방에 첫 화가
    # 저장되어 잠긴 소설이 없을 때 참이다(잠기기 전의 빈 소설은 이어 쓸 수 없어 없는 것과 같다. 잠긴 소설이 있으면
    # 「소설로 보기」는 그 소설을 연다. 잠금이 없어도 성공한 화 생성 작업이 있으면 생성 경로가 잠그고 통과시키므로
    # 막지 않는다). 판정을 화면이 복제하지 않게 서버가 계산해 싣는다.
    # 부정형인 이유: 이 칸을 모르는 옛 서버의 응답에서는 칸이 없어 "막지 않음"으로 읽혀야 한다(옛 서버는 막지도 않는다).
    # 기본값을 `default_factory` 로 두는 이유는 `effective_chat_model` 과 같다.
    novel_creation_blocked: bool = Field(default_factory=bool)
    # 재생성이 밀어낸 직전 응답으로 되돌릴 수 있는 지금 응답의 id(`POST …/messages/{id}/restore-previous` 의 대상). 없거나 그 사이
    # 대화가 바뀌었으면 None. 참/거짓이 아니라 id 인 이유는 화면이 낡은 캐시의 다른 응답에 메뉴를 띄우지 않게 마지막 응답과
    # 맞대 보게 하려는 것이다. 기본값을 두는 이유는 `persona_id` 와 같다.
    previous_response_for: uuid.UUID | None = None
    # 방이 고른 글쓰기 모델 — 저장된 값 그대로다(None 이 기본 모델). 레지스트리에서 내린 모델의 옛 값일 수도 있어 문자열이다.
    chat_model: str | None = None
    # 다음 턴이 실제로 쓸 모델과 그 턴의 클로버. 허용을 거뒀거나, 레지스트리에서 내렸거나 채팅에서 고를 수 없는
    # 모델이면 Gemini 와 Gemini 가격이다 — 화면은 저장 값이 아니라 이 둘을 보여 준다. 기본값은 이 필드를 모르는 생성
    # 타입·픽스처와의 호환용이고(`persona_id` 와 같은 이유), 응답에는 항상 실린다. 둘 다 `default_factory` 다 — 스키마에 `default` 가 실리면 생성 타입이 그 필드를 필수로
    # 만들어 기존 픽스처가 깨진다.
    effective_chat_model: ChatRoomModelId = Field(default_factory=lambda: DEFAULT_CHAT_ROOM_MODEL)
    # 유효 모델의 화면 이름(`GET /chat-models` 의 같은 모델 `name` 과 같다). 기본값을 두는 이유는 `effective_chat_model` 과
    # 같다.
    effective_chat_model_name: str = Field(default_factory=lambda: CHAT_MODELS_BY_ID[DEFAULT_CHAT_MODEL].name)
    turn_cost: int = Field(default_factory=lambda: chat_turn_cost(DEFAULT_CHAT_MODEL))
    created_at: datetime
    updated_at: datetime


class ChatRoomModelSelectRequest(CamelModel):
    """`PUT /chat-rooms/{id}/model`. 필드는 필수다 — 기본 모델로 되돌리기는 `"gemini"` 나 null 을 명시한다. 채팅에서 고를
    수 없는 값(레지스트리 밖, 소설에만 남은 Sonnet)은 422 다."""

    model: ChatRoomModelId | None


class ChatRoomModelResponse(CamelModel):
    """지정한 뒤의 방 모델. 방 응답의 같은 이름 네 필드와 같은 값이다 — 화면이 방을 다시 읽지 않고 바로 반영한다."""

    chat_model: str | None
    effective_chat_model: ChatRoomModelId
    effective_chat_model_name: str
    turn_cost: int


class ChatModelItem(CamelModel):
    """`GET /chat-models` 의 한 항목 — 이 계정이 채팅방에 고를 수 있는 모델과 그 모델의 턴 가격."""

    id: ChatRoomModelId
    name: str
    beta: bool
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
    # 장면 헤더를 켠 초안의 지금 장면 — 시작은 첫 시작설정의 첫 장면이고, 턴마다 장면 판정이 적은 장면으로 바뀐다. 켜지
    # 않았으면 null 이다. 다음 턴 장면 판정이 이 값을 직전 장면으로 잇는다.
    story_scene: StoryScene | None = None
    # 세션을 시작할 때 고른 글쓰기 모델(`POST /preview-sessions?model=`). 본문을 감싸지 않고 옆 칸으로 두어, 이 칸을 모르는 이미지도
    # 본문을 그대로 읽고 모르는 키를 버린 채 Gemini 로 돈다. 기본 모델이면 싣지 않는다 — 기본 세션의 상태 JSON 이 이 칸이 생기기 전과
    # 같다. 모델을 바꾸려면 새 세션을 시작한다(턴 도중에 이 값을 바꾸는 길은 없다).
    chat_model: ChatRoomModelId = Field(
        default=DEFAULT_CHAT_ROOM_MODEL, exclude_if=lambda value: value == DEFAULT_CHAT_ROOM_MODEL
    )


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


class ChatHiddenStatSignalEvent(CamelModel):
    """플레이어에게 숨긴 스탯 가운데 익명 신호를 켠 것이 이번 턴에 바뀌었다는 표시. 몇 개가 바뀌었든 한 턴에 하나이고,
    어느 스탯인지·어느 쪽으로 얼마나 움직였는지는 싣지 않는다 — 싣는 순간 숨긴 스탯을 되짚을 수 있다."""

    type: Literal["hiddenStatSignal"] = "hiddenStatSignal"


class ChatEndingReachedEvent(CamelModel):
    type: Literal["endingReached"] = "endingReached"
    ending_id: uuid.UUID
    epilogue: str | None
    # 에필로그의 칸 id 형태 태그가 가리키는 그림(방이 고정한 버전 기준).
    media_tag_images: dict[uuid.UUID, MediaTagImage] = Field(default_factory=dict)


class ChatSceneChangeEvent(CamelModel):
    """장면 헤더를 켠 스토리 방(과 미리보기)의 매 턴 장면 — 바뀌지 않았어도 턴마다 보낸다. `message_id` 는 그 장면이 저장된 AI
    응답이다(뒤따르는 `done` 의 메시지와 같다)."""

    type: Literal["sceneChange"] = "sceneChange"
    message_id: uuid.UUID
    place: str | None
    time: str | None


class ChatPolicyWarningEvent(CamelModel):
    type: Literal["policyWarning"] = "policyWarning"
    message: str


class ChatDoneEvent(CamelModel):
    """`stat_rewind` 는 메시지 수정의 done 에만 싣는다 — 편집 지점 뒤에서 지운 턴의 스탯을 어떻게 되돌렸는지(`chat/stat_rewind.py`)로
    화면이 안내 문구를 고른다. 다른 경로와, 지운 턴이 없던 수정의 done 에는 칸이 아예 없다."""

    type: Literal["done"] = "done"
    final_message: ChatMessageResponse
    stat_rewind: StatRewind | None = Field(default=None, exclude_if=lambda value: value is None)


class ChatErrorEvent(CamelModel):
    type: Literal["error"] = "error"
    message: str


ChatStreamEvent = Annotated[
    ChatTokenEvent
    | ChatStatChangeEvent
    | ChatHiddenStatSignalEvent
    | ChatEndingReachedEvent
    | ChatSceneChangeEvent
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
