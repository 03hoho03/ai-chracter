"""소설 라우트의 요청·응답 모델."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, StringConstraints, field_validator

from api.content.author_macros import user_name_error
from api.core.schema import CamelModel
from api.db.models.novel import (
    NovelContentType,
    NovelJobFailureCode,
    NovelJobKind,
    NovelJobStatus,
    NovelRevisionSource,
    NovelSnapshotKind,
)
from api.llm.chat_models import CHAT_MODELS_BY_ID, DEFAULT_CHAT_MODEL, ChatModelId, novel_episode_unit_price
from api.novelize.episodes import RegenerateIneligibility
from api.persona.schemas import PERSONA_NAME_MAX_LENGTH

# 설정 노트·직접 수정 본문·AI 수정 지시문의 길이 상한. 상세 응답의 `limits` 로 내려 보내 FE 가 사본을 들지 않게 한다.
# 설정 노트는 장마다 프롬프트에 실리므로 대화 기억 노트(1,000자)보다 조금 넉넉한 정도로 둔다. 본문 상한은 장 생성
# 출력 상한(토큰)으로 나올 수 있는 길이보다 넉넉하게, 지시문은 한두 문장이면 되는 길이로 둔다.
SETTING_NOTES_MAX_LENGTH = 2_000
CHAPTER_BODY_MAX_LENGTH = 100_000
AI_EDIT_INSTRUCTION_MAX_LENGTH = 500
# 소설 제목·화 제목은 목차와 표지에 한 줄로 보이는 길이, 소개는 작품 정보 화면의 몇 문단, 작가의 말은 설정 노트와 같은
# 정도로 둔다. 작가의 말은 프롬프트에 실리지 않아 넉넉해도 비용이 없다.
NOVEL_TITLE_MAX_LENGTH = 100
SYNOPSIS_MAX_LENGTH = 1_000
CHAPTER_TITLE_MAX_LENGTH = 100
AUTHOR_NOTE_MAX_LENGTH = 2_000

SettingNotesText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=SETTING_NOTES_MAX_LENGTH)]
ChapterBodyText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CHAPTER_BODY_MAX_LENGTH)
]
InstructionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=AI_EDIT_INSTRUCTION_MAX_LENGTH)
]
ProtagonistName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PERSONA_NAME_MAX_LENGTH)
]
NovelTitleText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOVEL_TITLE_MAX_LENGTH)
]
SynopsisText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=SYNOPSIS_MAX_LENGTH)]
ChapterTitleText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CHAPTER_TITLE_MAX_LENGTH)
]
AuthorNoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=AUTHOR_NOTE_MAX_LENGTH)]

# 인물 이름·별칭은 카드와 목차에 한 줄로 보이는 길이, 메모는 설정 노트와 같은 정도로 둔다. 메모가 빈 인물은 다음 묶음
# 입력에서 빠지고, 메모는 다음 묶음 생성 입력에 실리므로 설정 노트보다 넉넉하게 두지 않는다. 별칭 수는 표기가 갈린 이름을
# 몇 번 합쳐도 닿지 않을 정도로 둔다(합치기는 이 상한을 보지 않는다 — 사용자가 직접 적는 목록에만 건다).
CHARACTER_NAME_MAX_LENGTH = 50
CHARACTER_ALIASES_MAX_COUNT = 20
CHARACTER_MEMO_MAX_LENGTH = 2_000
# 스냅샷 이름은 목록에 한 줄로 보이는 길이.
SNAPSHOT_NAME_MAX_LENGTH = 50
# 편집 보드 배치를 직렬화한 크기 상한(바이트). 화·인물 노드 수백 개의 좌표와 화면 위치가 한참 아래에 든다. 화면이 같은
# 값을 상세의 `limits` 로 받아 보낼 몫을 미리 줄인다.
BOARD_LAYOUT_MAX_BYTES = 65_536

CharacterNameText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CHARACTER_NAME_MAX_LENGTH)
]
CharacterMemoText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=CHARACTER_MEMO_MAX_LENGTH)]
SnapshotNameText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SNAPSHOT_NAME_MAX_LENGTH)
]


# ── 작업 ───────────────────────────────────────────────────────────────────
class NovelAiEditPreview(CamelModel):
    """문단 수정 작업의 입력과 결과 후보. `result_text` 는 범위 밖 문단까지 이은 장 전체 본문이고, 성공 전에는 null.

    적용했거나 버렸거나, 그 장에 새 개정이 생겨 더는 적용할 수 없게 된 작업은 성공이어도 `instruction`·`result_text`
    가 null 이다(쓸 데가 없어진 지시문과 결과 사본은 서버가 비운다). 장을 지운 작업, 실패·환불된 작업도 같다."""

    base_revision_id: uuid.UUID | None
    paragraph_start: int | None
    paragraph_end: int | None
    instruction: str | None
    result_text: str | None


class NovelJobResponse(CamelModel):
    id: uuid.UUID
    kind: NovelJobKind
    status: NovelJobStatus
    charged_amount: int
    refunded: bool
    failure_reason: NovelJobFailureCode | None
    chapter_id: uuid.UUID | None
    # 이 작업이 만든 개정. 장 생성·재생성은 성공하면 채워지고, 문단 수정은 적용했을 때 그 적용으로 생긴 개정이 된다
    # (적용 전에는 null).
    revision_id: uuid.UUID | None
    ai_edit: NovelAiEditPreview | None
    created_at: datetime
    # 장 생성·재생성에 쓴(쓰는) 글쓰기 모델의 레지스트리 id — 모델 칸이 생기기 전의 장 작업은 `"gemini"` 다. AI 수정은
    # 모델을 고르지 않아 null 이다. 레지스트리에서 내린 모델의 옛 값일 수도 있어 문자열이다. 기본값은 이 필드를 모르는
    # 생성 타입·픽스처와의 호환용이고, 응답에는 항상 실린다.
    model: str | None = None
    # 실제로 돌려준 클로버. 실패한 작업만이 아니라 목표보다 적은 화를 낸 성공도 모자란 화만큼 돌려받으므로, 화면은
    # `refunded` 가 아니라 이 금액으로 안내한다. 돌려준 것이 없으면 0 이다.
    refunded_amount: int
    # 묶음 생성·다시 만들기가 대상으로 삼은(성공하면 만든) 묶음. AI 수정과 아직 묶음이 정해지지 않은 생성은 null 이다.
    batch_id: uuid.UUID | None
    # "남은 대화 한 번에"(연쇄 생성)의 진행 — 끝낸 묶음 수와 계획한 묶음 수. 연쇄가 아닌 작업은 둘 다 null 이다.
    completed_batches: int | None
    planned_batches: int | None


# ── 소설 ───────────────────────────────────────────────────────────────────
class NovelPrices(CamelModel):
    """작업 한 번의 클로버 단가. 화면은 이 값만 보여 주고, 요청에 확인한 금액(`expectedCost`)으로 싣는다."""

    chapter_generate: int
    chapter_regenerate: int
    ai_edit: int


class NovelChapterModel(CamelModel):
    """이 계정이 장 생성·재생성에 고를 수 있는 모델 하나와 그 모델의 화 하나 가격. 생성 한 번은 여러 화를 쓸 수 있어
    요청의 `expectedCost` 는 이 값 × 화 수다. 생성·재생성 두 칸은 같은 값이다(옛 화면이 읽는 칸 이름을 그대로 둔다)."""

    id: ChatModelId
    name: str
    chapter_generate: int
    chapter_regenerate: int


def chapter_model_option(model: ChatModelId) -> NovelChapterModel:
    return NovelChapterModel(
        id=model,
        name=CHAT_MODELS_BY_ID[model].name,
        chapter_generate=novel_episode_unit_price(model),
        chapter_regenerate=novel_episode_unit_price(model),
    )


def _default_chapter_models() -> list[NovelChapterModel]:
    return [chapter_model_option(DEFAULT_CHAT_MODEL)]


class NovelLimits(CamelModel):
    setting_notes_max_length: int
    chapter_body_max_length: int
    ai_edit_instruction_max_length: int
    protagonist_name_max_length: int
    title_max_length: int
    synopsis_max_length: int
    chapter_title_max_length: int
    author_note_max_length: int
    character_name_max_length: int
    character_aliases_max_count: int
    character_memo_max_length: int
    snapshot_name_max_length: int
    board_layout_max_bytes: int


class NovelActiveJob(CamelModel):
    """진행 중(대기·실행) 작업. 화면을 새로 열어도 이 id 로 폴링을 이어 간다. 연쇄 생성 중에는 부모 작업이다 — 화면이
    묶음 하나를 맡은 자식을 폴링하면 첫 묶음이 끝날 때 전체가 끝난 것으로 읽는다."""

    id: uuid.UUID
    kind: NovelJobKind
    status: NovelJobStatus
    chapter_id: uuid.UUID | None
    # 작업 응답의 같은 이름 칸과 같다.
    batch_id: uuid.UUID | None
    completed_batches: int | None
    planned_batches: int | None


class NovelPendingAiEdit(CamelModel):
    """끝났지만 적용도 버리기도 하지 않은 AI 수정. 기준 개정이 지금도 그 장의 현재 개정인 것만 싣는다 — 그 사이 장이
    바뀌었으면 적용이 409 라 미리보기로 내보일 이유가 없다. 화면이 작업 id 를 잃어도(새로고침·다른 기기) 여기서
    미리보기를 다시 찾아 적용(`apply`)하거나 버린다(`dismiss`). `result_text` 는 장 전체 본문이다."""

    id: uuid.UUID
    chapter_id: uuid.UUID
    paragraph_start: int
    paragraph_end: int
    instruction: str
    result_text: str
    created_at: datetime


class NovelChapterSummary(CamelModel):
    """목차의 화 한 줄. 본문은 화 조회로 따로 읽는다. `ordinal` 은 소설 전체의 화 번호다."""

    id: uuid.UUID
    ordinal: int
    assistant_message_count: int
    current_revision_id: uuid.UUID
    current_revision_no: int
    current_revision_source: NovelRevisionSource
    # 현재 개정이 만들어진 시각(장의 마지막 수정 시각).
    updated_at: datetime
    created_at: datetime
    # 이 화가 든 묶음(생성 한 번)과 묶음 안 순번(0부터). 묶음의 원문 구간·다시 만들기 금액은 `batches` 에 있다.
    batch_id: uuid.UUID
    episode_index: int
    # 생성 출력이 쓴 화 제목·요약. 이 칸들이 생기기 전에 만든 화는 null 이다.
    title: str | None
    summary: str | None
    author_note: str
    # 현재 개정 본문의 글자 수.
    char_count: int
    # 이 화를 끝까지 읽은 적이 있는가. 한 번 끝까지 읽으면 그 뒤 앞부분을 다시 읽어도 참이다.
    finished_reading: bool


class NovelRegenerateOption(CamelModel):
    """묶음 하나를 이 모델로 다시 만들 때의 금액과 고를 수 있는지. 다시 만들기는 묶음의 화 수를 그대로 지키므로 금액은 그
    화 수 × 이 모델의 화 단가이고, 그 화 수나 묶음의 턴 수가 이 모델의 상한을 넘으면 고를 수 없다(요청하면 409
    `NOVEL_MODEL_INELIGIBLE`) — `ineligible_reason` 이 그 이유다(`too_many_episodes`·`too_many_turns`)."""

    model: ChatModelId
    name: str
    cost: int
    eligible: bool
    ineligible_reason: RegenerateIneligibility | None


class NovelBatchSummary(CamelModel):
    """묶음 하나 = 생성 한 번이 옮긴 원문 구간. 다시 만들기·마지막 묶음 삭제의 단위다."""

    id: uuid.UUID
    ordinal: int
    # 이 묶음의 화(묶음 안 순서대로).
    chapter_ids: list[uuid.UUID]
    assistant_message_count: int
    # 이 계정이 고를 수 있는 모델마다 다시 만들기 금액(상세의 `chapter_models` 와 같은 모델·같은 순서).
    regenerate_options: list[NovelRegenerateOption]


NovelCoverSource = Literal["generated", "work"]


class NovelCover(CamelModel):
    """표지. 사용자가 고른 생성 이미지(`generated`)가 있으면 그것이고, 없거나 그 이미지가 지워졌으면 원작 썸네일
    (`work`)이다. 원작 썸네일도 없으면 `url` 이 null 이다."""

    asset_id: uuid.UUID | None
    url: str | None
    source: NovelCoverSource


class NovelSource(CamelModel):
    """원작 표기. 작품명·캐릭터명은 상세의 `content_title`·`character_name` 이다. `linkable` 은 지금 이 사용자가 원작
    상세를 볼 수 있는가(이용 제한·삭제·남의 비공개 작품이면 거짓 — 화면은 글자만 보인다)."""

    thumbnail_url: str | None
    linkable: bool


class NovelLastRead(CamelModel):
    """이 소설에서 가장 최근에 읽은 자리. `paragraph_count` 는 그때의 문단 수라, 그 뒤 개정이 바뀌었으면 비율로 옮긴다."""

    chapter_id: uuid.UUID
    paragraph_index: int
    paragraph_count: int
    revision_id: uuid.UUID
    updated_at: datetime


class NovelDetailResponse(CamelModel):
    id: uuid.UUID
    # 원래 대화방. 방이 지워졌으면 null 이고, 그때는 새 장을 만들 수 없다(읽기·수정은 된다).
    chat_room_id: uuid.UUID | None
    content_id: uuid.UUID
    content_type: NovelContentType
    content_title: str
    character_name: str | None
    # 본문에서 사용자 쪽 인물을 부르는 이름. null 이면 첫 장을 만들기 전에 받아야 한다.
    protagonist_name: str | None
    setting_notes: str
    # 소설 제목. 생성이 채우고, 사용자가 고친 뒤(`title_edited`)에는 AI 가 덮지 않는다. null 이면 화면은 원작 제목을 쓴다.
    title: str | None
    title_edited: bool
    synopsis: str
    cover: NovelCover
    source: NovelSource
    # 묶음 번호 순.
    batches: list[NovelBatchSummary]
    chapters: list[NovelChapterSummary]
    last_read: NovelLastRead | None
    active_job: NovelActiveJob | None
    # 최근 것 먼저.
    pending_ai_edits: list[NovelPendingAiEdit]
    prices: NovelPrices
    limits: NovelLimits
    created_at: datetime
    updated_at: datetime
    # 장 생성·재생성 확인에서 고를 수 있는 모델과 그 가격. 기본 모델(맨 앞)은 늘 있고, 상위 모델은 소설 상위 모델 허용이
    # 있을 때만 실린다. `prices` 의 장 가격은 기본 모델 값 그대로다(옛 화면이 읽는 칸). 아래 둘의 기본값은 이 필드를 모르는
    # 생성 타입·픽스처와의 호환용이고, 응답에는 항상 실린다.
    chapter_models: list[NovelChapterModel] = Field(default_factory=_default_chapter_models)
    # 확인 화면의 기본 선택 — 이 소설에서 가장 최근에 성공한 장 작업의 모델이다. 그런 작업이 없거나 그 모델을 지금 쓸 수
    # 없으면(허용 회수·레지스트리에서 내림) 기본 모델이다.
    last_chapter_model: ChatModelId = Field(default_factory=lambda: DEFAULT_CHAT_MODEL)


class NovelListItem(CamelModel):
    id: uuid.UUID
    chat_room_id: uuid.UUID | None
    content_type: NovelContentType
    content_title: str
    character_name: str | None
    chapter_count: int
    # 상세의 같은 이름 칸과 같다.
    title: str | None
    cover: NovelCover
    created_at: datetime
    updated_at: datetime


class NovelListResponse(CamelModel):
    items: list[NovelListItem]
    next_cursor: str | None


class NovelSettingNotesRequest(CamelModel):
    """공백만 보내면 빈 노트로 저장된다."""

    setting_notes: SettingNotesText


class NovelProtagonistNameRequest(CamelModel):
    protagonist_name: ProtagonistName

    @field_validator("protagonist_name")
    @classmethod
    def _reject_forbidden_characters(cls, value: str) -> str:
        # 대화 프로필 이름과 같은 자리(작가 글의 `{{user}}`)에 들어가므로 같은 규칙으로 막는다.
        error = user_name_error(value)
        if error is not None:
            raise ValueError(error)
        return value


# ── 장 경계 제안·장 생성 ────────────────────────────────────────────────────
class NovelChapterCandidate(CamelModel):
    """다음 묶음의 끝으로 고를 수 있는 턴 하나. `message_id` 는 그 턴의 AI 응답이고, `ordinal` 은 다음 묶음 시작부터 센
    턴 번호(1부터)다. `episode_count`·`cost` 는 이 턴까지를 요청한 모델로 만들 때의 화 수와 금액이다 — 생성 요청의
    `expectedCost` 는 고른 후보의 `cost` 다."""

    message_id: uuid.UUID
    ordinal: int
    created_at: datetime
    excerpt: str
    episode_count: int
    cost: int


class NovelChapterSuggestion(CamelModel):
    end_message_id: uuid.UUID
    reason: str


class NovelChapterProposalRequest(CamelModel):
    # 묶음을 쓸 모델. 후보는 이 모델의 턴 상한까지이고 후보마다 화 수·금액도 이 모델 기준이다. 모델을 바꾸면 제안을 다시
    # 받는다. 상위 모델은 소설 상위 모델 허용이 있어야 한다(없으면 403 `NOVEL_MODEL_NOT_ALLOWED`).
    model: ChatModelId = DEFAULT_CHAT_MODEL


class NovelChapterProposalResponse(CamelModel):
    start_message_id: uuid.UUID
    # 요청한 모델의 턴 상한까지.
    candidates: list[NovelChapterCandidate]
    # 모델 제안. 호출이 실패하면 null 이다 — 후보는 그대로라 사용자가 직접 고를 수 있다.
    suggestion: NovelChapterSuggestion | None
    # 기본 모델의 화 단가(옛 화면이 읽는 칸). 실제 금액은 후보의 `cost` 이고, 모델별 단가는 `chapter_models` 에 있다(상세
    # 응답의 같은 이름 칸과 같은 목록).
    cost: int
    chapter_models: list[NovelChapterModel] = Field(default_factory=_default_chapter_models)


class NovelChapterCreateRequest(CamelModel):
    end_message_id: uuid.UUID
    expected_cost: int
    # 이 묶음을 쓸 모델. 보내지 않으면 기본 모델이다(이 필드를 모르는 옛 화면). 상위 모델은 소설 상위 모델 허용이 있어야
    # 하고(없으면 403 `NOVEL_MODEL_NOT_ALLOWED`), `expected_cost` 는 그 모델로 이 끝까지 만들 때의 금액(경계 제안의 후보
    # `cost`)이어야 한다.
    model: ChatModelId = DEFAULT_CHAT_MODEL


class NovelChapterRegenerateRequest(CamelModel):
    """화 하나를 골라 다시 만들기 — 그 화가 든 묶음 전체를 다시 만든다(묶음 다시 만들기 요청과 같다)."""

    expected_cost: int
    # 장 생성 요청의 같은 칸과 같다. 처음 만든 모델과 달라도 된다.
    model: ChatModelId = DEFAULT_CHAT_MODEL


class NovelBatchRegenerateRequest(CamelModel):
    # 상세의 묶음 `regenerate_options` 에서 고른 모델과 그 `cost`.
    model: ChatModelId
    expected_cost: int


class NovelChainEstimate(CamelModel):
    """"남은 대화 한 번에"를 이 모델로 할 때. 묶음 경계는 돌면서 정하므로 금액은 묶음마다 이 모델의 화 수 상한만큼
    미리 받는 값이고(`max_episode_count` × 화 단가), 끝나면 쓰지 않은 몫을 돌려준다. 같은 남은 대화라도 턴 상한이 작은
    모델은 묶음이 더 많이 들고, 한 번에 만드는 묶음 수에는 상한이 있어 덜 진행할 수 있다."""

    model: ChatModelId
    name: str
    # 이번에 만들 묶음 수(남은 대화를 이 모델의 턴 상한으로 나눈 수, 한 번의 상한까지). 생성 요청의 `maxBatches` 로 보낸다.
    batch_count: int
    max_episode_count: int
    cost: int


class NovelChainEstimateResponse(CamelModel):
    # 이 계정이 고를 수 있는 모델마다(상세의 `chapter_models` 와 같은 모델·같은 순서).
    options: list[NovelChainEstimate]


class NovelChainCreateRequest(CamelModel):
    # 연쇄 전체를 쓸 모델 하나. 상위 모델은 소설 상위 모델 허용이 있어야 한다(없으면 403 `NOVEL_MODEL_NOT_ALLOWED`).
    model: ChatModelId
    # 견적에서 고른 모델의 `cost` 와 `batch_count`. 묶음 수는 상한이다 — 그 사이 대화가 늘어도 이 수까지만 만들고 금액도
    # 그대로다. 대화가 줄어 묶음 수가 줄면 금액이 달라져 409 `NOVELIZE_PRICE_CHANGED` + `currentCost` 다.
    expected_cost: int
    max_batches: int = Field(ge=1)


class NovelUpdateRequest(CamelModel):
    """보낸 칸만 바꾼다. 제목을 바꾸면 그 뒤로 AI 가 제목을 덮지 않는다. `coverAssetId` 는 null 을 보내면 원작 썸네일로
    되돌리고, 값을 보내면 내 생성 이미지 중 준비가 끝난 것이어야 한다(아니면 422 `NOVEL_COVER_INVALID`)."""

    title: NovelTitleText | None = None
    synopsis: SynopsisText | None = None
    cover_asset_id: uuid.UUID | None = None


class NovelChapterUpdateRequest(CamelModel):
    """보낸 칸만 바꾼다. 화 제목은 다음 다시 만들기가 새 출력으로 덮는다(본문과 함께 나온 값이다)."""

    title: ChapterTitleText | None = None
    author_note: AuthorNoteText | None = None


# ── 장·개정 ─────────────────────────────────────────────────────────────────
class NovelRevisionSummary(CamelModel):
    id: uuid.UUID
    revision_no: int
    source: NovelRevisionSource
    reverted_from_revision_id: uuid.UUID | None
    created_at: datetime


class NovelRevisionResponse(NovelRevisionSummary):
    body: str
    # 본문을 빈 줄로 나눈 문단. 문단 범위(AI 수정)의 인덱스는 이 배열 기준이다 — 화면이 다시 나누지 않는다.
    paragraphs: list[str]


class NovelChapterResponse(CamelModel):
    id: uuid.UUID
    novel_id: uuid.UUID
    ordinal: int
    assistant_message_count: int
    revision: NovelRevisionResponse


class NovelRevisionListResponse(CamelModel):
    items: list[NovelRevisionSummary]


class NovelRevisionCreateRequest(CamelModel):
    """직접 수정 — 장 전체 본문을 보낸다. 화면이 고른 문단을 본문 안에서 바꿔 보낸다."""

    base_revision_id: uuid.UUID
    body: ChapterBodyText


class NovelRevisionRestoreRequest(CamelModel):
    base_revision_id: uuid.UUID


class NovelAiEditRequest(CamelModel):
    base_revision_id: uuid.UUID
    paragraph_start: int = Field(ge=0)
    paragraph_end: int = Field(ge=0)
    instruction: InstructionText
    expected_cost: int


# ── 인물 카드 ───────────────────────────────────────────────────────────────
class NovelCharacterResponse(CamelModel):
    """인물 카드 하나. 이름과 별칭을 모은 공간은 소설 안에서 겹치지 않는다 — 생성 출력의 등장 인물 이름이 이름이나 별칭에
    맞는 카드에 붙는다. `chapter_ids` 는 이 인물이 나온 화(화 번호 순)다."""

    id: uuid.UUID
    name: str
    aliases: list[str]
    memo: str
    chapter_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class NovelCharacterListResponse(CamelModel):
    # 만든 순서대로.
    items: list[NovelCharacterResponse]


class NovelCharacterAddRequest(CamelModel):
    """이 이름의 카드가 있게 한다. 같은 이름의 카드가 이미 있으면 아무것도 바꾸지 않는다(다시 보내도 같다). 다른 카드의
    별칭이면 409 `NOVEL_CHARACTER_NAME_TAKEN` + `name`."""

    name: CharacterNameText


class NovelCharacterUpdateRequest(CamelModel):
    """보낸 칸만 바꾼다. `aliases` 는 목록 통째다(앞뒤 공백·빈 값·중복·이름과 같은 값은 서버가 뺀다). 이름이나 별칭이 다른
    카드의 이름·별칭과 겹치면 409 `NOVEL_CHARACTER_NAME_TAKEN` + `name`(겹친 값)."""

    name: CharacterNameText | None = None
    aliases: list[CharacterNameText] | None = Field(default=None, max_length=CHARACTER_ALIASES_MAX_COUNT)
    memo: CharacterMemoText | None = None


class NovelCharacterMergeRequest(CamelModel):
    """경로의 카드를 이 카드로 합친다 — 경로 카드의 이름·별칭이 이 카드의 별칭이 되고, 메모는 이 카드 메모 뒤에
    `[이름] 메모` 로 붙고, 등장 화가 옮겨진 뒤 경로 카드는 지워진다."""

    into_character_id: uuid.UUID


# ── 편집 보드 배치 ──────────────────────────────────────────────────────────
# 노드 키: 화 `episode:{화 id}`, 인물 `character:{인물 id}`, 설정 노트 `notes`.
BoardNodeKey = Annotated[
    str,
    StringConstraints(
        pattern=r"^(notes|(episode|character):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
    ),
]


class NovelBoardPosition(CamelModel):
    # 유한한 수만 받는다 — JSON 에 무한·NaN 은 적을 수 없어 저장이 DB 오류가 된다.
    x: FiniteFloat
    y: FiniteFloat


class NovelBoardViewport(CamelModel):
    x: FiniteFloat
    y: FiniteFloat
    zoom: FiniteFloat = Field(gt=0)


class NovelBoardLayout(CamelModel):
    """편집 보드의 노드 위치와 화면 위치. 서버는 형식만 보고 통째로 저장한다. 읽을 때는 지금 없는 화·인물의 키를 빼고
    돌려주므로(묶음 삭제·인물 합치기 뒤), 화면은 받은 키만 다시 보내면 된다. 직렬화한 크기가 상세 `limits` 의
    `board_layout_max_bytes` 를 넘으면 422 `NOVEL_BOARD_LAYOUT_TOO_LARGE`."""

    version: Literal[1]
    positions: dict[BoardNodeKey, NovelBoardPosition]
    viewport: NovelBoardViewport | None


class NovelBoardLayoutResponse(CamelModel):
    # 저장한 배치가 없으면 null 이다(화면이 자동 배치한다).
    layout: NovelBoardLayout | None


# ── 읽은 위치 ───────────────────────────────────────────────────────────────
class NovelReadingPositionRequest(CamelModel):
    """화를 읽던 자리. 같은 값을 다시 보내도 결과가 같다. `finished` 가 한 번 참이 되면 그 화는 그 뒤 앞부분으로 돌아가
    저장해도 다 읽은 화로 남는다. `revision_id` 는 읽던 개정이다(그 뒤 개정이 바뀌면 문단 수 비율로 옮긴다)."""

    paragraph_index: int = Field(ge=0)
    paragraph_count: int = Field(ge=1)
    revision_id: uuid.UUID
    finished: bool


# ── 스냅샷 ─────────────────────────────────────────────────────────────────
class NovelSnapshotCreateRequest(CamelModel):
    name: SnapshotNameText


class NovelSnapshotSummary(CamelModel):
    """`manual` 은 사용자가 이름 붙여 저장한 것, `auto_before_restore` 는 복원 직전 상태를 서버가 떠 둔 것이다."""

    id: uuid.UUID
    name: str
    kind: NovelSnapshotKind
    created_at: datetime


class NovelSnapshotListResponse(CamelModel):
    # 최근 것 먼저.
    items: list[NovelSnapshotSummary]
    # 소설 하나의 스냅샷 수 상한. 닿으면 가장 오래된 자동 스냅샷부터 지워지고, 이름 붙인 것만 남았으면 새 저장이 409
    # `NOVEL_SNAPSHOT_LIMIT` 다.
    limit: int


class NovelSnapshotCharacter(CamelModel):
    id: uuid.UUID
    name: str
    aliases: list[str]
    memo: str


class NovelSnapshotChapter(CamelModel):
    """스냅샷의 화 하나. `deleted` 가 참이면 그 뒤 마지막 묶음 삭제로 화가 지워진 것이고, 나머지 칸은 null 이다(지운 화의
    내용은 스냅샷에서도 함께 지워진다)."""

    chapter_id: uuid.UUID
    deleted: bool
    revision_id: uuid.UUID | None
    title: str | None
    summary: str | None
    author_note: str | None


class NovelSnapshotDetail(NovelSnapshotSummary):
    title: str | None
    title_edited: bool
    synopsis: str
    setting_notes: str
    characters: list[NovelSnapshotCharacter]
    # 스냅샷 때의 화 번호 순.
    chapters: list[NovelSnapshotChapter]


class NovelSnapshotRestoreResponse(CamelModel):
    """복원 결과. 스냅샷 뒤에 생긴 화는 그대로 두고, 스냅샷에 있던 화는 그때의 본문을 새 개정으로 쌓는다. 화나 그 개정이
    지워져 되돌릴 수 없던 화는 `skipped_chapters` 에 있다. 복원 직전 상태는 `auto_snapshot_id` 스냅샷으로 남는다."""

    novel: NovelDetailResponse
    skipped_chapters: list[uuid.UUID]
    auto_snapshot_id: uuid.UUID
