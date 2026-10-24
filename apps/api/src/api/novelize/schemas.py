"""소설 라우트의 요청·응답 모델."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, StringConstraints, field_validator, model_validator

from api.content.author_macros import user_name_error
from api.core.schema import CamelModel
from api.db.models.novel import (
    NovelContentType,
    NovelIllustrationPlacement,
    NovelIllustrationSource,
    NovelIllustrationWithheld,
    NovelJobFailureCode,
    NovelJobKind,
    NovelJobStatus,
    NovelOutlineSource,
    NovelRevisionSource,
    NovelSnapshotKind,
    NovelSourceSectionMode,
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
# 여러 문단 수정 한 번에 고를 수 있는 문단 수. 응답 스키마가 문단마다 수정안을 내므로 출력 길이와 응답 유효율이 이 수에 달려
# 있다 — 측정 전의 임시값이다.
BLOCK_EDIT_MAX_BLOCKS = 20
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
    # 여러 문단 수정 한 번에 고를 수 있는 문단 수. 기본값은 이 칸을 모르는 생성 타입·픽스처와의 호환용이고, 응답에는 항상 실린다.
    block_edit_max_blocks: int = BLOCK_EDIT_MAX_BLOCKS


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
    """끝났지만 적용도 버리기도 하지 않은 AI 수정. 기준 개정이 지금도 그 장의 현재 개정과 글이 같은 것만 싣는다 — 그
    사이 장의 글이 바뀌었으면 적용이 409 라 미리보기로 내보일 이유가 없다(같은 글의 새 개정만 쌓였으면 그대로 싣고 적용도
    된다). 화면이 작업 id 를 잃어도(새로고침·다른 기기) 여기서
    미리보기를 다시 찾아 적용(`apply`)하거나 버린다(`dismiss`). `result_text` 는 장 전체 본문이다."""

    id: uuid.UUID
    chapter_id: uuid.UUID
    paragraph_start: int
    paragraph_end: int
    instruction: str
    result_text: str
    created_at: datetime


class NovelBlockEditPatchView(CamelModel):
    """여러 문단 수정의 블록 하나 수정안. `state` 가 대기(`pending`)일 때만 `paragraphs`(그 블록 하나를 대신할 새 문단들)가 있다.
    `fresh` 는 지금 개정에 아직 쓸 수 있는가다 — 그 블록이 있고 글이 수정을 맡길 때와 같다(사용자가 그 블록을 고쳤으면 거짓)."""

    id: str
    block_id: uuid.UUID
    state: Literal["pending", "applied", "dismissed", "stale"]
    paragraphs: list[str] | None
    fresh: bool


class NovelBlockEditBundleView(CamelModel):
    """함께 적용해야 하는 수정안 묶음(둘 이상). 묶음에 든 수정안은 하나씩 적용하지 않는다."""

    id: str
    patch_ids: list[str]
    reason: str | None


class NovelPendingBlockEdit(CamelModel):
    """끝났고 아직 대기 수정안이 남은 여러 문단 수정. 화면이 작업 id 를 잃어도 여기서 수정안을 다시 찾는다. 수정안은 본문
    차례다."""

    id: uuid.UUID
    chapter_id: uuid.UUID
    instruction: str
    patches: list[NovelBlockEditPatchView]
    bundles: list[NovelBlockEditBundleView]
    created_at: datetime


class NovelChapterReadingPosition(CamelModel):
    """화 하나를 읽던 자리. `paragraph_count` 는 저장할 때의 문단 수라, 그 뒤 개정이 바뀌었으면 비율로 옮긴다.
    `finished` 는 그 화를 끝까지 읽은 적이 있는가다(목차의 `finished_reading` 과 같은 값)."""

    paragraph_index: int
    paragraph_count: int
    revision_id: uuid.UUID
    finished: bool


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
    # 사용자가 화 제목을 고쳤는가. 참이면 다시 만들기가 그 제목을 그대로 둔다.
    title_edited: bool
    summary: str | None
    author_note: str
    # 현재 개정 본문의 글자 수.
    char_count: int
    # 이 화를 끝까지 읽은 적이 있는가. 한 번 끝까지 읽으면 그 뒤 앞부분을 다시 읽어도 참이다.
    finished_reading: bool
    # 이 화를 읽던 자리. 읽은 적 없으면 null 이다. 마지막으로 읽은 화가 아니어도 그 화를 다시 열면 이 자리로 돌아간다.
    reading_position: NovelChapterReadingPosition | None
    # 구성 흐름(구성안 → 장면 구성안 → 원고)으로 쓴 화이면 그 화를 쓴 장면 구성안 리비전 id, 옛 흐름 화이면 null 이다. 구성 흐름 화는
    # 옛 다시 만들기 라우트가 거절하고 구성 흐름 다시 만들기로만 다시 만든다. 구성 흐름 스위치와 무관하게 싣는다.
    episode_outline_id: uuid.UUID | None


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


class NovelPurchaseRefundPreview(CamelModel):
    """지우면 돌려줄 구매. 소설 삭제 확인에는 소설 전체를, 마지막 묶음(화) 삭제 확인에는 마지막 묶음을 본다. 금액은 산 값
    그대로다(결제가 전액 취소된 구매분은 실제 환급에서 빠질 수 있다). 탈퇴한 구매자의 구매는 돌려주지 않으므로 사람 수에도
    금액에도 들지 않는다."""

    novel_buyer_count: int = 0
    novel_refund_amount: int = 0
    last_batch_buyer_count: int = 0
    last_batch_refund_amount: int = 0
    # 정책 스위치가 켜졌을 때만 참이 된다. `novel_sold`: 소설을 지우면 환급하지 않고 숨긴다(산 사람이 계속 읽는다) — 위
    # 두 칸의 환급 안내는 맞지 않는다. `last_batch_sold`: 마지막 묶음에 산 화가 있어 지울 수 없다(409 `NOVEL_BATCH_SOLD`).
    novel_sold: bool = False
    last_batch_sold: bool = False


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
    # 여러 문단 수정 중 대기 수정안이 남은 것, 최근 것 먼저. 스위치와 무관하다(끈 뒤에도 남은 수정안을 본다). 기본값은 이 칸을
    # 모르는 생성 타입·픽스처와의 호환용이고, 응답에는 항상 실린다.
    pending_block_edits: list[NovelPendingBlockEdit] = Field(default_factory=list)
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
    # 노벨에서 이 소설의 화를 산 구매자 수와 지우면 돌려줄 클로버 — 삭제 확인 화면의 환급 고지에 쓴다. 기본값은 위 둘과 같은
    # 호환용이다.
    purchase_refunds: NovelPurchaseRefundPreview = Field(default_factory=NovelPurchaseRefundPreview)


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
    """보낸 칸만 바꾼다. 화 제목을 보내면 그 뒤 다시 만들기가 그 제목을 덮지 않는다(본문·요약·등장 인물은 새로 쓴다).
    `title` 에 null 을 보내면 제목을 비우고, 다음 다시 만들기가 AI 제목을 다시 쓴다."""

    title: ChapterTitleText | None = None
    author_note: AuthorNoteText | None = None


# ── 장·개정 ─────────────────────────────────────────────────────────────────
class NovelRevisionSummary(CamelModel):
    id: uuid.UUID
    revision_no: int
    source: NovelRevisionSource
    reverted_from_revision_id: uuid.UUID | None
    created_at: datetime


class NovelBlock(CamelModel):
    id: uuid.UUID
    text: str


class NovelIllustration(CamelModel):
    """개정에 붙은 삽화 한 장. `id` 는 이 개정의 배치 id 다 — 옮기기·바꾸기·떼기가 이 값으로 고르고, 개정이 바뀌면 새 id 가 된다.
    `anchor_block_id`·`placement` 가 비어 있으면 위치 확인 필요(앵커 문단이 사라진 그림)다. `url` 은 크게 그리는 정지 변형이고,
    `width`·`height` 는 그림 크기(모르면 null — 화면이 고정 비율 칸에 그린다)다. `order` 는 같은 자리(앵커·앞뒤) 안의 순서다.
    `withheld` 가 차 있으면 독자 화면과 같이 그림 자리만 남는다 — `url` 이 없고, 운영자가 내린 그림이면 `withheld_reason` 에
    운영자가 적은 사유가 있다. 내린 그림이 든 화는 그 그림을 바꾸거나 떼야 다시 공개할 수 있다."""

    id: uuid.UUID
    anchor_block_id: uuid.UUID | None
    placement: NovelIllustrationPlacement | None
    order: int
    asset_id: uuid.UUID
    source: NovelIllustrationSource
    url: str | None
    width: int | None
    height: int | None
    withheld: NovelIllustrationWithheld | None
    withheld_reason: str | None


class NovelRevisionScene(CamelModel):
    """개정의 장면 하나. `id` 는 장면 구성안의 장면 id, `title` 은 그 블록들을 쓴 장면 구성안 리비전의 장면 제목, `block_ids` 는 이
    장면에 든 블록 id(본문 차례)다. 여러 문단 수정은 한 장면 안의 블록만 함께 고를 수 있다."""

    id: str
    title: str
    block_ids: list[uuid.UUID]


class NovelRevisionResponse(NovelRevisionSummary):
    body: str
    # 본문을 빈 줄로 나눈 문단. 문단 범위(AI 수정)의 인덱스는 이 배열 기준이다 — 화면이 다시 나누지 않는다.
    paragraphs: list[str]
    # 문단마다 블록 id 를 붙인 같은 배열(블록 i = 문단 i). 개정이 바뀌어도 같은 문단을 가리키는 id 다.
    blocks: list[NovelBlock]
    # 이 개정의 삽화 — 문단에 붙은 것(문단 순서·앞 먼저·자리 안 순서)과 위치 확인 필요인 것. 삽화 스위치가 꺼져 있으면 둘 다 빈 목록이다.
    illustrations: list[NovelIllustration]
    unplaced_illustrations: list[NovelIllustration]
    # 이 개정의 장면(본문에 처음 나오는 차례). 블록마다 꼭 한 장면에 든다. 장면 경계가 없는 화(옛 흐름 화)는 빈 목록이고 화 전체가
    # 한 장면이다.
    scenes: list[NovelRevisionScene]


class NovelChapterResponse(CamelModel):
    id: uuid.UUID
    novel_id: uuid.UUID
    ordinal: int
    assistant_message_count: int
    revision: NovelRevisionResponse


class NovelRevisionListResponse(CamelModel):
    items: list[NovelRevisionSummary]


class NovelRevisionCreateRequest(CamelModel):
    """직접 수정 — 장 전체 본문을 보낸다. 화면이 고른 문단을 본문 안에서 바꿔 보낸다.

    `block_ids` 는 선택이다. 실으면 본문 문단마다 하나씩 기준 개정의 블록 id 나 새 문단(null)을 적는다 — 문단 수와 다르거나
    기준 개정에 없는 id·같은 id 둘이면 422 `NOVEL_BLOCK_IDS_INVALID`. 싣지 않으면 서버가 기준 개정과 글자로 맞춰 잇는다."""

    base_revision_id: uuid.UUID
    body: ChapterBodyText
    block_ids: list[uuid.UUID | None] | None = None


class NovelRevisionRestoreRequest(CamelModel):
    base_revision_id: uuid.UUID


class NovelIllustrationAttachRequest(CamelModel):
    """그림 한 장을 문단(`anchor_block_id`, 지금 개정의 블록 id)의 앞·뒤에 붙인다. `order` 는 그 자리 안의 자리(0부터)이고, 비우거나
    자리 수보다 크면 맨 끝이다. `source` 는 그림이 어디서 왔는가 — 서버가 그 출처로 쓸 수 있는 그림인지 본다."""

    base_revision_id: uuid.UUID
    anchor_block_id: uuid.UUID
    placement: NovelIllustrationPlacement
    order: int | None = Field(default=None, ge=0)
    asset_id: uuid.UUID
    source: NovelIllustrationSource


class NovelIllustrationMoveRequest(CamelModel):
    """배치 하나를 다른 자리로 옮긴다(위치 확인 필요인 그림을 다시 놓을 때도). `order` 는 붙이기와 같다."""

    base_revision_id: uuid.UUID
    anchor_block_id: uuid.UUID
    placement: NovelIllustrationPlacement
    order: int | None = Field(default=None, ge=0)


class NovelIllustrationReplaceRequest(CamelModel):
    """배치 하나의 그림만 바꾼다(자리는 그대로)."""

    base_revision_id: uuid.UUID
    asset_id: uuid.UUID
    source: NovelIllustrationSource


class NovelIllustrationDetachRequest(CamelModel):
    base_revision_id: uuid.UUID


class NovelOriginalIllustrationCandidate(CamelModel):
    """원작 그림 후보 한 장. `kind` 는 원작에서의 자리(대표 이미지·상황 이미지·미디어 북 칸)다."""

    asset_id: uuid.UUID
    kind: Literal["thumbnail", "situationalImage", "mediaBook"]
    url: str
    width: int | None
    height: int | None


class NovelOriginalIllustrationCandidates(CamelModel):
    items: list[NovelOriginalIllustrationCandidate]


class NovelAiEditRequest(CamelModel):
    base_revision_id: uuid.UUID
    paragraph_start: int = Field(ge=0)
    paragraph_end: int = Field(ge=0)
    instruction: InstructionText
    expected_cost: int


class NovelBlockEditRequest(CamelModel):
    """여러 문단 수정 — 기준 개정의 블록 id 를 고른 만큼(같은 장면 안, 차례 무관) 보낸다. 서버가 같은 장면의 문단을 문맥으로
    함께 보낸다."""

    base_revision_id: uuid.UUID
    block_ids: list[uuid.UUID]
    instruction: InstructionText
    expected_cost: int


class NovelPatchUnitRequest(CamelModel):
    """여러 문단 수정의 적용 단위 — 묶음에 들지 않은 수정안 하나(`patchId`) 또는 묶음 하나(`bundleId`). 둘 중 하나만 보낸다."""

    patch_id: str | None = None
    bundle_id: str | None = None

    @model_validator(mode="after")
    def _one_unit(self) -> Self:
        if (self.patch_id is None) == (self.bundle_id is None):
            raise ValueError("patchId 와 bundleId 중 하나만 보낸다")
        return self


class NovelPatchDismissRequest(CamelModel):
    """버릴 것 — 적용 단위 하나(`patchId`·`bundleId`) 또는 남은 수정안 전부(`all: true`). 셋 중 하나만 보낸다."""

    patch_id: str | None = None
    bundle_id: str | None = None
    all: bool = False

    @model_validator(mode="after")
    def _one_choice(self) -> Self:
        if [self.patch_id is not None, self.bundle_id is not None, self.all].count(True) != 1:
            raise ValueError("patchId·bundleId·all 중 하나만 보낸다")
        return self


class NovelBundleRecheckResponse(CamelModel):
    """묶음 재검사 판정. `separable` 이 참이면 사용자가 고친 수정안이 묶음에서 빠져 남은 수정안을 따로 적용할 수 있다(상세를 다시
    받아 본다). 거짓이면 묶음은 그대로라 버리기만 된다. `reason` 은 판정 이유 한 문장이다(저장하지 않는다)."""

    separable: bool
    reason: str


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

    # 문단은 한 글자 이상이라 문단 수는 본문 글자 수를 넘지 못하고, 본문은 본문 상한(생성 출력으로 나올 수 있는 길이보다
    # 넉넉하게 잡은 값) 안에 있다. 상한이 없으면 큰 값이 DB 정수 칸을 넘쳐 500 이 된다.
    paragraph_index: int = Field(ge=0, lt=CHAPTER_BODY_MAX_LENGTH)
    paragraph_count: int = Field(ge=1, le=CHAPTER_BODY_MAX_LENGTH)
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


# ── 구간 선택 ───────────────────────────────────────────────────────────────
# 한 선택에 담을 수 있는 구간 수. 화면이 구간을 하나하나 고르는 것이라 긴 방이라도 한참 아래에서 끝난다 — 요청 하나가 구간마다
# 원문을 다시 읽어 해시하므로 상한을 둔다.
SOURCE_SECTIONS_MAX_COUNT = 200


class NovelSourceSectionInput(CamelModel):
    """고른 구간 하나 — 양 끝 메시지(양 끝 포함)와 mode. 소설에 넣을 구간은 `include`, 앞뒤 맥락으로만 보낼 구간은 `context` 다.
    빼는 구간(exclude)은 보내지 않는다 — 고르지 않은 나머지가 exclude 다."""

    mode: NovelSourceSectionMode
    start_message_id: uuid.UUID
    end_message_id: uuid.UUID


class NovelSourceSelectionSaveRequest(CamelModel):
    """선택 초안 저장. `base_revision` 은 화면이 본 가장 최근 리비전(선택이 아직 없으면 null)이고 지금 최신과 다르면 409 다.
    구간은 키 순으로, 겹치지 않게(맞닿은 메시지도 공유하지 않게) 보낸다.

    `room_end_message_id` 는 고정 끝(이 선택이 다루는 방의 마지막 메시지) — 화면이 본 그 메시지를 그대로 돌려보낸다. 첫 저장이면
    조회의 기본 제안의 고정 끝이고, 그 뒤 저장은 기준 리비전의 고정 끝이어야 한다(다르면 409) — 고른 뒤 이어진 대화가 저절로
    붙지 않게. `extend_to_room_end` 를 켠 저장만 고정 끝을 화면이 본 지금 방 끝(조회의 `room_end_message_id`)으로 옮겨 새 대화를
    고를 수 있게 한다("새 구간 추가"). 서버가 저장 때의 방 끝을 쓰지 않는 것은, 화면이 본 뒤 들어온 메시지가 사용자가 보지도
    못한 채 "고르지 않은 나머지"로 숨지 않게 하려는 것이다 — 고정 끝 뒤에 남아 "새 대화 있음"으로 다시 보인다."""

    base_revision: int | None = Field(ge=1)
    extend_to_room_end: bool = False
    room_end_message_id: uuid.UUID
    sections: list[NovelSourceSectionInput] = Field(max_length=SOURCE_SECTIONS_MAX_COUNT)


class NovelSourceSelectionApproveRequest(CamelModel):
    """승인할 리비전. 가장 최근 리비전이어야 한다."""

    revision: int = Field(ge=1)


class NovelSourceRange(CamelModel):
    """양 끝 메시지로 가리킨 구간(양 끝 포함)."""

    start_message_id: uuid.UUID
    end_message_id: uuid.UUID


class NovelSourceKeyedRange(NovelSourceRange):
    """응답의 구간 — 양 끝 id 와 그 메시지의 `created_at`(메시지 키 = (`created_at`, id)). 끝 메시지가 지워져 화면의 메시지 목록에
    없어도 이 키로 구간의 정확한 자리를 잡는다. 요청 입력(`basis`)에는 쓰지 않는다.

    datetime 은 방 메시지 `createdAt` 과 같은 기본 직렬화라 마이크로초가 0 이면 소수부가 빠진다(`…:03Z` 와 `…:03.000005Z`). 글자
    비교는 순서를 뒤집고 JS `Date` 는 밀리초까지라, 순서를 비교하려면 소수부를 6자리로 맞춘 (초, 마이크로초, id) 로 본다. id 동률은
    소문자 hex 글자 순이 DB 의 uuid 순과 같다."""

    start_message_created_at: datetime
    end_message_created_at: datetime


class NovelSourceSectionView(NovelSourceKeyedRange):
    """저장된 구간 하나. `source_changed` 는 저장 때의 해시와 지금 방 원문의 해시가 다른가다 — 참이면 그 구간을 쓰는 다음 생성이
    원문 변경으로 막히므로 화면이 다시 고르라고 알린다."""

    mode: NovelSourceSectionMode
    assistant_message_count: int
    source_changed: bool


class NovelSourceSelectionView(CamelModel):
    """선택 한 판. `revision` 이 null 이면 아직 저장하지 않은 기본 제안이다. `room_end_message_id` 는 이 선택의 고정 끝(제안이면
    지금 방 끝, 방이 비었으면 null)이고, 그 안에서 구간 밖·잠긴 구간 밖이 소설에서 빼는 구간이다."""

    revision: int | None
    approved_at: datetime | None
    room_end_message_id: uuid.UUID | None
    # 고정 끝 메시지의 `created_at`(`room_end_message_id` 와 함께 null). 그 메시지가 지워져도 실린다.
    room_end_message_created_at: datetime | None
    sections: list[NovelSourceSectionView]


class NovelSourceSelectionState(CamelModel):
    """구간 선택 화면의 상태. `approved` 는 가장 최근에 승인한 선택, `draft` 는 그보다 새 미승인 초안, `proposal` 은 선택이 하나도
    없을 때의 기본 제안(화가 없으면 방 전체, 있으면 마지막 화 끝 다음부터 방 끝까지 include)이다.

    `locked_ranges` 는 이미 화가 된 구간이다 — include 로 다시 고를 수 없고, 고르지 않아도 빼는 구간(exclude)이 아니다(앞 화를
    거쳐 이미 소설에 들어가 있다). `room_end_message_id` 는 지금 방의 마지막 메시지, `has_new_messages` 는 가장 최근 선택의 고정
    끝 뒤에 대화가 이어졌는가다."""

    approved: NovelSourceSelectionView | None
    draft: NovelSourceSelectionView | None
    proposal: NovelSourceSelectionView | None
    locked_ranges: list[NovelSourceKeyedRange]
    room_end_message_id: uuid.UUID | None
    has_new_messages: bool


# ── 전체 구성안 ─────────────────────────────────────────────────────────────
# 화 하나의 줄거리·목적 길이 상한. 모델이 낸 글은 이 길이에서 자르고(문안은 2~3문장·한 문장을 요구한다), 사용자가 고친 글은 넘으면
# 422 다. 화 수·화 하나의 근거 구간 수 상한은 요청 하나의 크기를 묶는 값이다 — 실제 화 수 상한은 설정(`novelize_outline_max_episodes`)
# 이고 서버가 따로 본다.
OUTLINE_SUMMARY_MAX_LENGTH = 1_000
OUTLINE_GOAL_MAX_LENGTH = 300
OUTLINE_EPISODES_MAX_COUNT = 200
OUTLINE_BASIS_MAX_COUNT = 50

OutlineSummaryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=OUTLINE_SUMMARY_MAX_LENGTH)
]
OutlineGoalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=OUTLINE_GOAL_MAX_LENGTH)]


# 화 하나의 장면 구성안 상태 — 그 화의 가장 최근 판으로 정한다. 판이 없으면 none, 그 판이 낡았으면(장면 구성안 조회의 `stale`)
# 승인 여부와 무관하게 stale, 아니면 미승인 draft·승인 approved 다. 승인본 위에 새 초안이 있으면 draft 다.
NovelSceneOutlineStatus = Literal["none", "draft", "approved", "stale"]


class NovelOutlineEpisodeView(CamelModel):
    """구성안의 화 하나. `key` 는 리비전이 바뀌어도 같은 화를 가리키는 화 키, `basis` 는 이 화의 근거가 된 대화 구간(양 끝 포함,
    키 순)이다 — 근거는 그 구성안이 쓴 구간 선택의 include 구간 안에만 있다. 목록 순서가 화 순서다.

    `chapter_id` 는 이 화 키를 이미 원고로 쓴 화(없으면 null), `scene_outline` 은 이 화 장면 구성안의 상태다. 둘 다 이 판이 아니라
    지금 상태다 — 승인본과 미승인 초안의 같은 화 키는 같은 값을 싣는다."""

    key: uuid.UUID
    title: str
    summary: str
    goal: str
    basis: list[NovelSourceRange]
    chapter_id: uuid.UUID | None
    scene_outline: NovelSceneOutlineStatus


class NovelOutlineView(CamelModel):
    """구성안 한 판. `source` 는 모델이 만든 판(`generate`)인지 사용자가 고친 판(`edit`)인지, `model` 은 만든 모델(고친 판은 null)이다.
    `stale` 이 참이면 그 판이 근거로 삼은 include 구간이 지금 승인한 구간 선택에서 빠졌거나 바뀌었다 — 승인·편집할 수 없고, 구간
    선택에 맞춰 다시 만들어야 한다."""

    revision: int
    source: NovelOutlineSource
    model: str | None
    approved_at: datetime | None
    created_at: datetime
    stale: bool
    episodes: list[NovelOutlineEpisodeView]


class NovelOutlineModel(CamelModel):
    """이 계정이 전체 구성안에 고를 수 있는 모델 하나와 그 모델의 구성안 한 번 가격(요청의 `expectedCost`)."""

    id: ChatModelId
    name: str
    cost: int


class NovelOutlineState(CamelModel):
    """전체 구성안 화면의 상태. `approved` 는 가장 최근에 승인한 판, `draft` 는 그보다 새 미승인 판(모델이 막 만든 판이거나 사용자가
    고친 판)이다. `max_episodes` 는 구성안 화 수 상한, `models` 는 고를 수 있는 모델과 가격이다."""

    approved: NovelOutlineView | None
    draft: NovelOutlineView | None
    max_episodes: int
    models: list[NovelOutlineModel]


class NovelOutlineCreateRequest(CamelModel):
    """전체 구성안 만들기(과금). 지금 승인한 구간 선택을 근거로 한다. `model` 은 상위 모델이면 소설 상위 모델 허용이 있어야 하고,
    `expected_cost` 는 조회 상태의 그 모델 `cost` 다."""

    expected_cost: int
    model: ChatModelId = DEFAULT_CHAT_MODEL


class NovelOutlineEpisodeInput(CamelModel):
    """고친 화 하나. `key` 는 기준 리비전에 있던 화의 키이고, 화를 나눠 새로 생긴 화는 비워 보낸다(서버가 새 키를 준다)."""

    key: uuid.UUID | None = None
    title: ChapterTitleText
    summary: OutlineSummaryText
    goal: OutlineGoalText = ""
    basis: list[NovelSourceRange] = Field(min_length=1, max_length=OUTLINE_BASIS_MAX_COUNT)


class NovelOutlineSaveRequest(CamelModel):
    """고친 구성안 저장 — 기준 리비전(화면이 본 가장 최근 판) 위의 새 미승인 리비전이 된다. 승인한 판은 고치지 않는다."""

    base_revision: int = Field(ge=1)
    episodes: list[NovelOutlineEpisodeInput] = Field(min_length=1, max_length=OUTLINE_EPISODES_MAX_COUNT)


class NovelOutlineApproveRequest(CamelModel):
    """승인할 리비전. 가장 최근 리비전이어야 한다."""

    revision: int = Field(ge=1)


# ── 화별 장면 구성안 · 구성 흐름 원고 ───────────────────────────────────────
# 장면 구성안 한 판의 장면 수와 장면 하나의 등장인물 수 상한 — 요청 하나의 크기를 묶는 값이고, 모델이 낸 판도 이 장면 수를 넘으면
# 쓸 수 없는 판으로 실패·환불한다. 장면 제목·내용·목적 길이는 화 제목·구성안 줄거리·목표와 같다.
EPISODE_OUTLINE_SCENES_MAX_COUNT = 30
SCENE_CHARACTERS_MAX_COUNT = 20


class NovelSceneView(CamelModel):
    """장면 구성안의 장면 하나. `id` 는 리비전이 바뀌어도 같은 장면을 가리키는 장면 id 이고, `basis` 는 이 장면의 근거 대화
    구간(양 끝 포함, 키 순)이다 — 근거는 그 화의 근거 구간 안에만 있다. `flashback` 은 회상 장면인가다. 목록 순서가 원고가 쓰는
    장면 차례다."""

    id: str
    title: str
    summary: str
    purpose: str
    characters: list[str]
    flashback: bool
    basis: list[NovelSourceRange]


class NovelEpisodeOutlineView(CamelModel):
    """장면 구성안 한 판. `stale` 이 참이면 지금 승인한 전체 구성안에서 그 화의 근거가 바뀌었거나(또는 화가 빠졌거나) 근거 include
    구간이 지금 구간 선택에서 빠졌다 — 승인·편집·원고에 쓸 수 없고 다시 만들어야 한다."""

    revision: int
    source: NovelOutlineSource
    model: str | None
    approved_at: datetime | None
    created_at: datetime
    stale: bool
    scenes: list[NovelSceneView]


class NovelEpisodeOutlineState(CamelModel):
    """한 화의 장면 구성안 화면 상태. `approved` 는 가장 최근에 승인한 판, `draft` 는 그보다 새 미승인 판이다. `models` 는 장면 구성안
    가격, `chapter_models` 는 원고 가격(화 단가)이고, `chapter_id` 는 이 화를 이미 원고로 쓴 화다(없으면 null)."""

    episode_key: uuid.UUID
    approved: NovelEpisodeOutlineView | None
    draft: NovelEpisodeOutlineView | None
    models: list[NovelOutlineModel]
    chapter_models: list[NovelOutlineModel]
    chapter_id: uuid.UUID | None


class NovelEpisodeOutlineCreateRequest(CamelModel):
    """장면 구성안 만들기(과금). 지금 승인한 전체 구성안의 그 화를 근거로 한다. `expected_cost` 는 조회 상태의 그 모델 가격이다."""

    expected_cost: int
    model: ChatModelId = DEFAULT_CHAT_MODEL


class NovelSceneInput(CamelModel):
    """고친 장면 하나. `id` 는 기준 리비전에 있던 장면의 id 이고, 나눠서 새로 생긴 장면은 비워 보낸다(서버가 새 id 를 준다)."""

    id: str | None = None
    title: ChapterTitleText
    summary: OutlineSummaryText
    purpose: OutlineGoalText = ""
    characters: list[CharacterNameText] = Field(default_factory=list, max_length=SCENE_CHARACTERS_MAX_COUNT)
    flashback: bool = False
    basis: list[NovelSourceRange] = Field(min_length=1, max_length=OUTLINE_BASIS_MAX_COUNT)


class NovelEpisodeOutlineSaveRequest(CamelModel):
    """고친 장면 구성안 저장 — 기준 리비전(화면이 본 그 화의 가장 최근 판) 위의 새 미승인 리비전이 된다. 장면을 빼려면 목록에서
    지우고, 차례를 바꾸려면 목록 순서를 바꾼다."""

    base_revision: int = Field(ge=1)
    scenes: list[NovelSceneInput] = Field(min_length=1, max_length=EPISODE_OUTLINE_SCENES_MAX_COUNT)


class NovelEpisodeOutlineApproveRequest(CamelModel):
    """승인할 리비전. 그 화의 가장 최근 리비전이어야 한다."""

    revision: int = Field(ge=1)


class NovelOutlineChapterRequest(CamelModel):
    """구성 흐름 원고 쓰기·다시 만들기(과금). 금액은 고른 모델의 화 단가 하나다."""

    expected_cost: int
    model: ChatModelId = DEFAULT_CHAT_MODEL
