"""소설 라우트의 요청·응답 모델."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from api.content.author_macros import user_name_error
from api.core.schema import CamelModel
from api.db.models.novel import (
    NovelContentType,
    NovelJobFailureCode,
    NovelJobKind,
    NovelJobStatus,
    NovelRevisionSource,
)
from api.llm.chat_models import CHAT_MODELS_BY_ID, DEFAULT_CHAT_MODEL, ChatModelId, novel_chapter_cost
from api.persona.schemas import PERSONA_NAME_MAX_LENGTH

# 설정 노트·직접 수정 본문·AI 수정 지시문의 길이 상한. 상세 응답의 `limits` 로 내려 보내 FE 가 사본을 들지 않게 한다.
# 설정 노트는 장마다 프롬프트에 실리므로 대화 기억 노트(1,000자)보다 조금 넉넉한 정도로 둔다. 본문 상한은 장 생성
# 출력 상한(토큰)으로 나올 수 있는 길이보다 넉넉하게, 지시문은 한두 문장이면 되는 길이로 둔다.
SETTING_NOTES_MAX_LENGTH = 2_000
CHAPTER_BODY_MAX_LENGTH = 100_000
AI_EDIT_INSTRUCTION_MAX_LENGTH = 500

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


# ── 소설 ───────────────────────────────────────────────────────────────────
class NovelPrices(CamelModel):
    """작업 한 번의 클로버 단가. 화면은 이 값만 보여 주고, 요청에 확인한 금액(`expectedCost`)으로 싣는다."""

    chapter_generate: int
    chapter_regenerate: int
    ai_edit: int


class NovelChapterModel(CamelModel):
    """이 계정이 장 생성·재생성에 고를 수 있는 모델 하나와 그 모델의 장 가격. 요청의 `model` 과 `expectedCost` 로 싣는다."""

    id: ChatModelId
    name: str
    chapter_generate: int
    chapter_regenerate: int


def chapter_model_option(model: ChatModelId) -> NovelChapterModel:
    return NovelChapterModel(
        id=model,
        name=CHAT_MODELS_BY_ID[model].name,
        chapter_generate=novel_chapter_cost(model, regenerate=False),
        chapter_regenerate=novel_chapter_cost(model, regenerate=True),
    )


def _default_chapter_models() -> list[NovelChapterModel]:
    return [chapter_model_option(DEFAULT_CHAT_MODEL)]


class NovelLimits(CamelModel):
    setting_notes_max_length: int
    chapter_body_max_length: int
    ai_edit_instruction_max_length: int
    protagonist_name_max_length: int


class NovelActiveJob(CamelModel):
    """진행 중(대기·실행) 작업. 화면을 새로 열어도 이 id 로 폴링을 이어 간다."""

    id: uuid.UUID
    kind: NovelJobKind
    status: NovelJobStatus
    chapter_id: uuid.UUID | None


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
    """목차의 장 한 줄. 본문은 장 조회로 따로 읽는다."""

    id: uuid.UUID
    ordinal: int
    assistant_message_count: int
    current_revision_id: uuid.UUID
    current_revision_no: int
    current_revision_source: NovelRevisionSource
    # 현재 개정이 만들어진 시각(장의 마지막 수정 시각).
    updated_at: datetime
    created_at: datetime


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
    chapters: list[NovelChapterSummary]
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
    """다음 장의 끝으로 고를 수 있는 턴 하나. `message_id` 는 그 턴의 AI 응답이고, `ordinal` 은 다음 장 시작부터 센
    턴 번호(1부터)다."""

    message_id: uuid.UUID
    ordinal: int
    created_at: datetime
    excerpt: str


class NovelChapterSuggestion(CamelModel):
    end_message_id: uuid.UUID
    reason: str


class NovelChapterProposalResponse(CamelModel):
    start_message_id: uuid.UUID
    candidates: list[NovelChapterCandidate]
    # 모델 제안. 호출이 실패하면 null 이다 — 후보는 그대로라 사용자가 직접 고를 수 있다.
    suggestion: NovelChapterSuggestion | None
    # 기본 모델의 장 생성 가격. 모델별 가격은 `chapter_models` 에 있다(상세 응답의 같은 이름 칸과 같은 목록).
    cost: int
    chapter_models: list[NovelChapterModel] = Field(default_factory=_default_chapter_models)


class NovelChapterCreateRequest(CamelModel):
    end_message_id: uuid.UUID
    expected_cost: int
    # 이 장을 쓸 모델. 보내지 않으면 기본 모델이다(이 필드를 모르는 옛 화면). 상위 모델은 소설 상위 모델 허용이 있어야
    # 하고(없으면 403 `NOVEL_MODEL_NOT_ALLOWED`), `expected_cost` 는 그 모델의 가격이어야 한다.
    model: ChatModelId = DEFAULT_CHAT_MODEL


class NovelChapterRegenerateRequest(CamelModel):
    expected_cost: int
    # 장 생성 요청의 같은 칸과 같다. 처음 만든 모델과 달라도 된다.
    model: ChatModelId = DEFAULT_CHAT_MODEL


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
