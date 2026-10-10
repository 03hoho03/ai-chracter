import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.content.author_macros import expand_author_macros, resolve_user_name
from api.content.media_tags import strip_media_tags
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StatDef, StatRule, StoryPromptTemplate
from api.llm.chat_models import PromptSetModelId
from api.llm.client import SegmentedPrompt

logger = logging.getLogger(__name__)

# `"legacy"`를 이 유니온에 넣지 않는다 — 넣는
# 순간 `list_prompt_sets`가 legacy를 걸러야 할 이유가 사라지고 FE가 4번째 탭을 만들게 된다.
PromptLane = Literal["story", "character", "publish_filter", "novel", "novel_screen"]

# mypy는 각 원소가 PromptLane인지는 보지만 "전부 들어 있는지"는 못 본다 — 그 한 칸은
# tests가 typing.get_args로 메운다.
_PROMPT_LANES: tuple[PromptLane, ...] = ("story", "character", "publish_filter", "novel", "novel_screen")


def as_prompt_lane(value: str) -> PromptLane | None:
    """DB의 `Mapped[str]`을 `PromptLane`으로 좁힌다. legacy는 `None`이다.

    public인 이유: `admin/prompts.py`(restore·list)가 쓴다. 파일 간 헬퍼 비공유 관례
    (apps/api/CLAUDE.md)가 있지만 이건 타입 유니온과 한 몸인 술어라 유니온이 사는 곳에
    함께 둔다 — 복제하면 유니온이 늘 때 한쪽만 갱신된다."""
    return next((lane for lane in _PROMPT_LANES if lane == value), None)


class PromptSetNotFoundError(RuntimeError):
    """활성(published) 프롬프트 세트가 없을 때 조용히 빈
    프롬프트를 내는 대신 명시적으로 실패한다."""


class PromptRenderError(RuntimeError):
    """`PromptSection.body`(DB 값)를 `values`로 채우다가 실패했을 때 던진다.

    이전 코드(f-string 리터럴 조립, 4-멤버 enum을 전수 커버하는 dict lookup)에는 이 실패
    경로가 아예 없었다 — "DB 값을 신뢰하고 `.format()` 한다"는 문안을 DB로 옮기며 처음 생겼다.
    `LLMClientError`를 재사용하지 않는다 — 원인이 LLM이 아니라 운영자가 편집한 문안이라
    성격이 다르고, 호출부가 "이 턴만 포기"할지 "생성 자체를 포기"할지 다르게 판단해야
    한다. `KeyError`/`ValueError`/`IndexError`를 그대로 두지 않고 여기로 정규화하는 이유는
    apps/api/CLAUDE.md "SSE 스트리밍" 절 — 정규화 안 된 원시 예외가 SSE 제너레이터 본문에서 새면
    `except LLMClientError`가 못 잡아 태스크 취소 → 커넥션 강제종료로 번진다(실측)."""


# `(channel, slot)` -> 그 슬롯의 `body`가 쓸 수 있는
# `{name}` 플레이스홀더 전체 — 이 아래 `build_*`/`content/publish.py`의 `build_*_filter_prompt`
# 호출부가 각자 만드는 `values` 딕셔너리 키를 그대로 옮긴 것이다(지금까지는 그 딕셔너리
# 리터럴에만 암묵적으로 있었다). 어드민 게시 검증이 이 목록 밖의 이름을 거부하려면
# "허용되는 이름이 뭔지" 코드 어딘가에 명시적으로 있어야 하는데, 그 정의를 여기 하나로만
# 두고 `admin/prompts.py`가 이 상수를 그대로 import해서 쓴다 — 값을 다시 나열하면 둘 중
# 하나가 바뀔 때 나머지가 조용히 갈린다. `variant`별로 다른 슬롯(`base_content`)은 두
# variant가 쓰는 이름의 합집합이다 — 어느 variant든 같은 `values` 딕셔너리를 받으므로
# 실제로 크래시 나지 않는 이름 전부가 여기 있어야 한다. `system` 채널은 전부 빈 집합이다
# — `system_instruction_for`가 `render_prompt_channel`을 `values={}`로 호출하기 때문에
# 플레이스홀더가 하나라도 있으면 그 자리에서 반드시 `PromptRenderError`가 난다.
ALLOWED_PLACEHOLDERS: dict[tuple[str, str], frozenset[str]] = {
    ("system", "self_definition"): frozenset(),
    ("system", "rule_response_format"): frozenset(),
    ("system", "rule_user_agency"): frozenset(),
    ("system", "rule_open_turn"): frozenset(),
    ("system", "rule_rating"): frozenset(),
    ("system", "template_instruction"): frozenset(),
    ("system", "priority_tail"): frozenset(),
    ("generation", "character_prompt"): frozenset({"character_prompt"}),
    ("generation", "base_content"): frozenset({"setting_text", "custom_prompt"}),
    ("generation", "example_dialogues"): frozenset({"example_lines"}),
    ("generation", "rules"): frozenset({"rules"}),
    ("generation", "user_goal"): frozenset({"user_goal"}),
    ("generation", "development_examples"): frozenset({"example_lines"}),
    ("generation", "prologue"): frozenset({"prologue"}),
    # 대화 생성 채널에만 있다. 판정 채널에는 넣지 않는다.
    ("generation", "user_persona"): frozenset({"user_persona"}),
    # 사용자 이름 한 줄. 판정·요약 채널은 프로필 전체가 아니라 이 이름 한 줄만 받는다. 값이 비면(실제 이름이 없으면,
    # 생성 채널은 프로필이 있으면) conditional 이라 섹션째 빠진다 — `PromptNames` 가 값을 정한다.
    ("generation", "user_name"): frozenset({"user_name"}),
    # 채팅방 기억 — 사용자 노트와 자동 요약. 둘 다 conditional이라 값이 비면 섹션째 빠진다.
    ("generation", "memory_note"): frozenset({"memory_note"}),
    ("generation", "memory_summary"): frozenset({"memory_summary"}),
    ("generation", "history"): frozenset({"history_lines"}),
    ("generation", "keyword_notes"): frozenset({"keyword_note_lines"}),
    # 조건이 참인 상황 노트 본문. conditional 이라 참인 노트가 없으면 섹션째 빠진다.
    ("generation", "situation_notes"): frozenset({"situation_note_lines"}),
    ("generation", "shortcut_prompt"): frozenset({"shortcut_prompt"}),
    ("generation", "final_frame"): frozenset({"user_label", "user_message", "assistant_label"}),
    # 옛 절대값 판정 채널. 더 이상 렌더하지 않지만 운영 프롬프트 세트에 행이 남아 있어, 게시 검증(플레이스홀더 허용 목록)이
    # 그 행을 통과시키도록 둔다.
    ("stat_judgment", "stat_defs_intro"): frozenset({"stat_lines"}),
    ("stat_judgment", "turn_context"): frozenset(
        {"user_label", "user_message", "assistant_label", "assistant_message"}
    ),
    ("stat_judgment", "judgment_instruction"): frozenset(),
    ("stat_judgment", "user_name"): frozenset({"user_name"}),
    # 규칙 판정 — `build_stat_rule_judgment_prompt` 가 만드는 `values`.
    ("stat_rule_judgment", "stat_defs_intro"): frozenset({"stat_lines"}),
    ("stat_rule_judgment", "turn_context"): frozenset(
        {"user_label", "user_message", "assistant_label", "assistant_message"}
    ),
    ("stat_rule_judgment", "judgment_instruction"): frozenset(),
    ("stat_rule_judgment", "user_name"): frozenset({"user_name"}),
    ("ending_judgment", "memory_summary"): frozenset({"memory_summary"}),
    ("ending_judgment", "history_header"): frozenset(),
    ("ending_judgment", "turn_context"): frozenset({"turn_lines"}),
    ("ending_judgment", "criteria"): frozenset({"judgment_prompt"}),
    ("ending_judgment", "user_name"): frozenset({"user_name"}),
    # 요약 호출 전용 channel — `build_memory_summary_prompt`가 만드는 `values`.
    ("memory_summary", "instruction"): frozenset(),
    ("memory_summary", "previous_summary"): frozenset({"previous_summary"}),
    ("memory_summary", "turn_context"): frozenset({"turn_lines"}),
    ("memory_summary", "user_name"): frozenset({"user_name"}),
    ("image_judgment", "image_list_intro"): frozenset({"image_lines"}),
    ("image_judgment", "turn_context"): frozenset({"turn_lines"}),
    ("image_judgment", "judgment_instruction"): frozenset(),
    ("image_judgment", "user_name"): frozenset({"user_name"}),
    # 발행 심사는 이미지만 본다 — 작가 글은 싣지 않고, 코드가 만든 이미지 목록 라벨 하나만 넘긴다.
    ("publish_filter", "intro_instruction"): frozenset(),
    ("publish_filter", "image_list"): frozenset({"image_lines"}),
    ("publish_filter", "verdict_instruction"): frozenset(),
    # 소설화 세 채널 — `novelize/prompts.py` 의 빌더가 만드는 `values`. `instruction` 은 system_instruction 으로 따로
    # 렌더되므로(`values={}`) 빈 집합이어야 한다. 소설 레인과 채팅 레인에 얼려 둔 옛 소설 행이 같은 (channel, slot) 을
    # 쓴다 — 인물 메모·지난 화 요약·화 수 지시 슬롯은 소설 레인에만 있다.
    ("novelize_boundary", "instruction"): frozenset(),
    ("novelize_boundary", "user_name"): frozenset({"user_name"}),
    ("novelize_boundary", "max_turns"): frozenset({"max_turns"}),
    ("novelize_boundary", "turn_context"): frozenset({"user_label", "assistant_label", "turn_lines"}),
    ("novelize_chapter", "instruction"): frozenset(),
    ("novelize_chapter", "work_setting"): frozenset({"work_setting"}),
    ("novelize_chapter", "user_name"): frozenset({"user_name"}),
    ("novelize_chapter", "setting_notes"): frozenset({"setting_notes"}),
    ("novelize_chapter", "character_notes"): frozenset({"character_notes"}),
    ("novelize_chapter", "previous_summaries"): frozenset({"previous_summaries"}),
    ("novelize_chapter", "previous_excerpt"): frozenset({"previous_excerpt"}),
    ("novelize_chapter", "episode_plan"): frozenset({"episode_count", "episode_chars", "novel_title_rule"}),
    ("novelize_chapter", "turn_context"): frozenset({"user_label", "assistant_label", "turn_lines"}),
    ("novelize_revise", "instruction"): frozenset(),
    ("novelize_revise", "work_setting"): frozenset({"work_setting"}),
    ("novelize_revise", "setting_notes"): frozenset({"setting_notes"}),
    ("novelize_revise", "paragraphs"): frozenset({"paragraph_lines"}),
    ("novelize_revise", "target_range"): frozenset({"first_paragraph", "last_paragraph"}),
    ("novelize_revise", "user_request"): frozenset({"user_request"}),
    # 노벨 공개 전 텍스트 심사 — `novel_public/screening.py` 의 빌더가 만드는 `values`. `instruction` 은
    # system_instruction 으로 따로 렌더되므로(`values={}`) 빈 집합이어야 한다. 심사할 글은 게시자가 쓴 글이라 지시문과 다른
    # 통로(본문)에 싣는다.
    ("novel_screen", "instruction"): frozenset(),
    ("novel_screen", "screened_text"): frozenset({"screened_text"}),
}


async def load_active_prompt_set(
    db: AsyncSession, *, lane: PromptLane, model: PromptSetModelId = "gemini"
) -> tuple[PromptSet, list[PromptSection]]:
    """`(lane, model)`의 활성 세트(published 중 `published_at`이 가장 최신인 것)와 그 섹션 전부를
    읽는다. `model` 기본값이 Gemini 인 것은 심사·소설 묶음 경계·문단 수정처럼 모델을 고르지 않는 호출이 Gemini 세트를 읽기
    때문이고(소설 화 생성은 작업의 모델 체인, 판정·요약은 판정·요약 모델 설정의 체인을 읽는다), 모델을 빠뜨린 호출부도 지금까지와 같은 세트로 간다. `legal_documents`의 `_get_latest_published`와 같은 모양이다. 활성 세트가 없으면
    `PromptSetNotFoundError` — downgrade 직후처럼 테이블 자체가 없는 게 아니라
    행만 없는 상태는 만들어지기 어렵지만, 그 경우에도 조용히 넘어가지 않는다.

    `lane`은 키워드 전용이다 — 현행 호출부가 전부 단일 인자였으므로, 위치 인자로 두면
    두 번째 인자가 섞여 들어가는 실수가 타입 체커를 통과할 여지가 생긴다."""
    prompt_set = await db.scalar(
        select(PromptSet)
        .where(PromptSet.status == "published", PromptSet.lane == lane, PromptSet.model == model)
        .order_by(PromptSet.published_at.desc())
        .limit(1)
    )
    if prompt_set is None:
        raise PromptSetNotFoundError(f"활성 프롬프트 세트가 없다 (lane={lane}, model={model})")
    sections = list(
        (
            await db.scalars(
                select(PromptSection)
                .where(PromptSection.prompt_set_id == prompt_set.id)
                .order_by(
                    PromptSection.channel,
                    PromptSection.order,
                    PromptSection.scope,
                    PromptSection.slot,
                    PromptSection.variant,
                )
            )
        ).all()
    )
    return prompt_set, sections


def select_sections_for_render(
    sections: Sequence[PromptSection], *, channel: str, scope: str, variant: str = ""
) -> list[PromptSection]:
    """`render_prompt_channel`의 1~3단계(scope 필터 → variant 선택 → order 정렬) — 렌더러와
    `admin/prompts.py`의 렌더 order 중복 검사가 **같은 함수**를 부른다.
    사본을 두면 렌더러가 바뀔 때 그 검사가 조용히 딴 것을 검사하게 된다.

    1. `channel`이 같고 `scope ∈ {both, 요청한 scope}`인 섹션만 후보로 남긴다.
    2. 같은 `slot`끼리 묶어 `variant`가 일치하는 행을 고르고, 없으면 기본(`variant=""`)
       행으로 대체한다 — `variant`별 행만 있는 슬롯(`template_instruction`)은 요청한
       `variant`가 없으면 그 슬롯 자체가 통째로 빠진다(L0.5 없는 `system_instruction_for`).
    3. `order`로 정렬한다.
    """
    candidates = [s for s in sections if s.channel == channel and s.scope in ("both", scope)]

    by_slot: dict[str, list[PromptSection]] = {}
    for section in candidates:
        by_slot.setdefault(section.slot, []).append(section)

    selected: list[PromptSection] = []
    for group in by_slot.values():
        chosen = next((s for s in group if s.variant == variant), None)
        if chosen is None:
            chosen = next((s for s in group if s.variant == ""), None)
        if chosen is not None:
            selected.append(chosen)
    selected.sort(key=lambda s: s.order)
    return selected


def render_prompt_channel(
    sections: Sequence[PromptSection],
    *,
    channel: str,
    scope: str,
    variant: str = "",
    values: dict[str, str],
) -> str:
    """렌더링 규약을 구현하는 순수 함수 — DB에 닿지 않는다.

    1~3단계(scope 필터 → variant 선택 → order 정렬)는 `select_sections_for_render`가 한다.

    4. `conditional=True`인 슬롯은 body가 참조하는 플레이스홀더 값이 전부 비어 있으면
       (`values`에서 falsy) 섹션째 드롭한다. `conditional=False`는 값이 비어도 유지한다
       — "비어 있으면 드롭"만으로는 재현되지 않는다(`generation_character_empty_prompt`
       골든이 그 증거).
    5. 남은 섹션의 body를 `values`로 채우고 `"\\n\\n"`으로 잇는다.
    """
    selected = select_sections_for_render(sections, channel=channel, scope=scope, variant=variant)

    rendered: list[str] = []
    for section in selected:
        fields = [name for _, name, _, _ in Formatter().parse(section.body) if name]
        is_empty = bool(fields) and all(not values.get(name) for name in fields)
        if section.conditional and is_empty:
            continue
        try:
            rendered.append(section.body.format(**values))
        except (KeyError, ValueError, IndexError) as exc:
            raise PromptRenderError(
                f"channel={channel!r} slot={section.slot!r} variant={section.variant!r} body 렌더 실패: {exc!r}"
            ) from exc
    return "\n\n".join(rendered)


def system_instruction_for(
    sections: Sequence[PromptSection], *, is_story_chat: bool, template: StoryPromptTemplate | None = None
) -> str:
    """생성 호출에 붙일 바닥 지시문을 챗 종류로 고르고, 스토리 챗이면 템플릿별 L0.5를 잇는다.

    스토리 챗의 모델은 장면 밖에서 서술하는 화자이고 캐릭터 챗의 모델은 캐릭터 본인이라,
    공통 규칙이 같아도 첫 줄의 자기 규정과 금지할 라벨이 다르다(`system` 채널의
    `self_definition` 슬롯이 scope별로 두 행을 갖는 이유).

    `template`은 스토리 챗에서만 의미가 있다 — 캐릭터 챗은 템플릿 개념이 없으므로
    호출부가 넘기지 않는다(기본값 `None`). 스토리 챗 호출부가 `template`을 안 넘기면
    `template_instruction` 슬롯에 `variant=""` 행이 없어 그 슬롯 자체가 빠진다(L0.5 없이
    L0까지만 반환, `render_prompt_channel` 참고).
    """
    scope = "story" if is_story_chat else "character"
    variant = template.value if template is not None else ""
    return render_prompt_channel(sections, channel="system", scope=scope, variant=variant, values={})


# 프로필 필드 라벨은 코드 상수다(히스토리 줄의 `라벨: 내용`을
# 코드가 조립하는 것과 같은 자리). 지시문은 전부 DB의 `generation/user_persona` body에 있다.
_PERSONA_NAME_LABEL = "이름"
_PERSONA_GENDER_LABEL = "성별"
_PERSONA_DESCRIPTION_LABEL = "설명"
# 키가 `str | None`인 이유: `UserPersona.gender`(`Mapped[str | None]`)를 그대로 `.get`에 넣는다.
# 허용값은 요청 스키마가 강제하고, 맵에 없는 값은 None과 같이
# 줄을 생략한다 — 이 함수는 SSE 제너레이터 본문이 부르는 `build_room_prompt`(`chat/turn_prompt.py`)에서 불려서 예외를 내면
# 안 된다(apps/api/CLAUDE.md "SSE 스트리밍" 절).
_PERSONA_GENDER_TEXT: dict[str | None, str] = {"male": "남성", "female": "여성"}


def format_user_persona(*, name: str, gender: str | None, description: str) -> str:
    """대화 프로필을 `{user_persona}` 값으로 조립한다.

    `이름: …` / `성별: 남성|여성` / `설명: …`을 줄바꿈으로 잇는다. 성별이 None("선택 안 함")이면
    성별 줄을, 설명이 비면 설명 줄을 생략한다. 이름의 금지 문자(`:`·개행)는
    요청 스키마가 막는다 — 여기서는 거르거나 고치지 않는다(이름은 라벨·stop
    sequence에 들어가지 않는다). 키워드 전용인 이유: `name`과 `description`이 둘 다
    `str`이라 위치 인자로 바뀌어 들어와도 타입 체커가 못 잡는다."""
    lines = [f"{_PERSONA_NAME_LABEL}: {name}"]
    gender_text = _PERSONA_GENDER_TEXT.get(gender)
    if gender_text is not None:
        lines.append(f"{_PERSONA_GENDER_LABEL}: {gender_text}")
    if description:
        lines.append(f"{_PERSONA_DESCRIPTION_LABEL}: {description}")
    return "\n".join(lines)


@dataclass(frozen=True)
class PromptNames:
    """한 턴의 프롬프트가 쓰는 이름 — 작가 글의 `{{user}}`·`{{char}}` 를 바꿀 이름과 이름 한 줄 섹션의 값.

    `persona_name` 은 대화 프로필 이름(없으면 None), `char_name` 은 캐릭터 작품의 이름(스토리는 None — `{{char}}` 를
    글자 그대로 둔다).

    작가 글은 원문 그대로 저장되고 빌더가 값을 조립하는 순간 바꾼다. 빌더가 바꾸는 것은 작가 글 필드와 대화 기록의
    모델 응답 줄(첫 메시지는 작가 글의 복사본이다)뿐이다 — 사용자 메시지는 화면이 보내기 전에 이미 바꿔 저장하므로, 거기
    남은 `{{user}}` 는 사용자가 친 글자다. 이미지 태그는 먼저 지우고 나서 바꾼다(이름이 태그로 읽히지 않게)."""

    persona_name: str | None
    char_name: str | None

    def expand(self, text: str) -> str:
        return expand_author_macros(text, user_name=resolve_user_name(self.persona_name), char_name=self.char_name)

    @property
    def judgment_user_name(self) -> str:
        """판정·요약 채널의 이름 한 줄 값 — 프로필 이름이 있을 때만. 대체어 "당신" 은 이름이 아니라 "사용자의 이름: 당신"
        같은 줄이 나가지 않게 비운다."""
        return self.persona_name or ""

    @property
    def generation_user_name(self) -> str:
        """생성 채널의 이름 한 줄 값 — 실채팅에서는 늘 비어 있다. 프로필이 있으면 프로필 섹션이 이미 이름을 주고, 없으면
        실을 이름이 없다. 슬롯은 DB 프롬프트 세트에 남아 있어 값은 계속 넘기고, 비어 있으니 conditional 로 섹션째 빠진다.
        어드민 미리보기는 이 섹션 문안을 보이려고 하위 클래스에서 샘플 이름으로 덮는다."""
        return ""


def _turn_text(message: ChatMessage, names: PromptNames, *, strip_tags: bool) -> str:
    """대화 기록 한 줄의 모델 사본. 모델 응답 줄만 이름을 바꾸고 사용자 줄은 그대로 둔다(`PromptNames` 참고)."""
    text = strip_media_tags(message.content) if strip_tags else message.content
    return text if message.role == ChatMessageRole.USER else names.expand(text)


def _story_generation_variant(template: StoryPromptTemplate) -> str:
    """스토리 generation 채널의 variant — `build_story_generation_prompt`와
    `user_persona_rendered`가 같은 규칙을 쓰도록 한 자리에 둔다."""
    return "custom" if template == StoryPromptTemplate.CUSTOM else ""


def user_persona_rendered(
    sections: Sequence[PromptSection],
    *,
    is_story_chat: bool,
    template: StoryPromptTemplate | None = None,
    user_persona: str,
) -> bool:
    """그 턴 생성 프롬프트에 대화 프로필 섹션이
    **실제로** 들어갔는가.

    값이 비지 않았고, 그 턴의 scope·variant로 렌더러와 **같은 선택 함수**
    (`select_sections_for_render`)가 `user_persona` 슬롯을 골랐을 때만 참이다. conditional
    섹션은 값이 비지 않으면 반드시 렌더되므로 이 둘이 "포함됨"과 같다. 값만 보면 캐시 TTL 창처럼
    활성 세트에 슬롯이 아직 없을 때도 참이 된다. 인자 모양은 `system_instruction_for`와
    같다 — `template`은 스토리 챗에서만 의미가 있다."""
    return _generation_slot_rendered(
        sections, is_story_chat=is_story_chat, template=template, slot="user_persona", value=user_persona
    )


def memory_note_rendered(
    sections: Sequence[PromptSection],
    *,
    is_story_chat: bool,
    template: StoryPromptTemplate | None = None,
    memory_note: str,
) -> bool:
    """그 턴 생성 프롬프트에 방의 기억 노트 섹션이 **실제로** 들어갔는가. 판정 규칙과 인자 모양은
    `user_persona_rendered`와 같다(정책 안내 문구 분기용)."""
    return _generation_slot_rendered(
        sections, is_story_chat=is_story_chat, template=template, slot="memory_note", value=memory_note
    )


def _generation_slot_rendered(
    sections: Sequence[PromptSection],
    *,
    is_story_chat: bool,
    template: StoryPromptTemplate | None,
    slot: str,
    value: str,
) -> bool:
    if not value:
        return False
    scope = "story" if is_story_chat else "character"
    variant = _story_generation_variant(template) if template is not None else ""
    selected = select_sections_for_render(sections, channel="generation", scope=scope, variant=variant)
    return any(section.slot == slot for section in selected)


# 캐시 블록 경계를 렌더 결과 안에서 찾기 위한 표지. Postgres text 는 NUL 을 담지 못해 DB 에서 온 문안·작가 글·대화
# 기록과 겹치지 않는다. 겹치더라도(이번 입력에 섞여 온 NUL) 아래 검사가 표지 개수와 원문 일치를 보고 나누지 않는다.
_BLOCK_MARK = "\x00"


def _render_generation(
    sections: Sequence[PromptSection],
    *,
    scope: str,
    variant: str = "",
    values: dict[str, str],
    history_lines: list[str],
    history_roles: list[ChatMessageRole],
) -> str:
    """생성 채널을 렌더하고, 대화 기록이 있으면 Claude 프롬프트 캐시용 블록 셋으로 나눈 `SegmentedPrompt` 를 돌려준다.

    블록은 [대화 기록의 직전 교환 앞까지][직전 교환][기록 뒤 섹션 + 이번 입력]이다. 직전 교환은 기록의 마지막 사용자 줄부터
    끝까지(사용자 줄이 없으면 마지막 줄)다. 다음 턴에는 이 턴의 첫째·둘째 블록을 이은 것이 그대로 첫째 블록이 되어, 이
    턴이 둘째 블록 끝에 쓴 캐시를 다음 턴이 자기 첫째 블록 경계에서 찾는다(캐시는 블록 모양이 아니라 경계까지의 누적
    내용으로 맞춘다). 기록 줄 사이의 줄바꿈은 뒤 블록 앞에 붙인다 — 앞 블록 끝에 붙이면 이 턴의 둘째 블록만 줄바꿈 없이
    끝나 다음 턴의 누적 내용과 어긋난다. 기억 노트가 바뀌거나 요약이 접히는 턴은 앞부분이 달라져 어차피 맞지 않는다.

    경계는 섹션 제목이 아니라 기록 값에 박은 표지로 찾는다(문안은 어드민이 고친다). 표지가 정확히 두 번 나오지 않거나,
    나눈 조각을 이은 것이 표지 없이 렌더한 문자열과 다르거나, 빈 블록이 생기면 나누지 않고 보통 문자열을 돌려준다 —
    캐시를 못 맞출 뿐 보내는 글은 같고, 경고로 남긴다. 기록이 비면 표지를 넣지 않고 보통 문자열을 돌려준다(넣으면 조건부 기록
    섹션이 살아난다) — 나눌 경계가 원래 없는 정상 경우라 남기지 않는다."""
    plain = render_prompt_channel(
        sections, channel="generation", scope=scope, variant=variant, values={**values, "history_lines": "\n".join(history_lines)}
    )
    if not history_lines:
        return plain
    exchange_start = max(
        (i for i, role in enumerate(history_roles) if role == ChatMessageRole.USER), default=len(history_lines) - 1
    )
    marked_lines = [*history_lines]
    if exchange_start > 0:
        marked_lines[exchange_start - 1] += _BLOCK_MARK
    else:
        marked_lines[0] = _BLOCK_MARK + marked_lines[0]
    marked_lines[-1] += _BLOCK_MARK
    marked = render_prompt_channel(
        sections, channel="generation", scope=scope, variant=variant, values={**values, "history_lines": "\n".join(marked_lines)}
    )
    segments = tuple(marked.split(_BLOCK_MARK))
    if len(segments) != 3 or "".join(segments) != plain or not all(segments):
        # 기록이 있는데 나누지 못한 턴만 남긴다(기록이 빈 턴은 위에서 이미 돌아갔다). Bedrock 은 경계 없는 문자열을 받아도
        # 이유를 몰라 남기지 않으므로 여기가 유일한 신호다. Gemini 턴에서도 남지만 보내는 글은 같다.
        logger.warning("생성 프롬프트를 캐시 경계로 나누지 못해 블록 하나로 보낸다(조각 %d개)", len(segments))
        return plain
    return SegmentedPrompt(segments)


def build_generation_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    character_prompt: str,
    example_dialogues: list[dict[str, Any]],
    history: list[ChatMessage],
    user_message: str,
    user_persona: str,
    memory_note: str,
    memory_summary: str,
    names: PromptNames,
) -> str:
    """생성 프롬프트를 조립한다 — 캐릭터 챗 전용.

    캐릭터 프롬프트 뒤에 예시 대화("말투 예시")를 매 턴 포함하고, 최근 메시지
    히스토리와 이번 턴의 사용자 메시지로 마무리한다. 화자 라벨(`사용자`/`캐릭터`)은
    코드가 조립하는 줄 안에서도 `prompt_set`에서 읽는다.

    `user_persona`는 `format_user_persona`의 결과이거나 `""`(프로필 없음·선택 없음)다.
    `""`이면 conditional 섹션째 드롭되어 이 인자가 없던 시절과 바이트까지 같다.
    기본값이 없는 이유는 호출부 누락을 mypy가 잡게 하려는
    것이다.

    `memory_note`(사용자가 적은 기억 노트)와 `memory_summary`(윈도우 밖으로 접힌 대화의 현재 요약)도
    같은 규칙이다 — 비어 있으면 섹션째 빠지고, 기본값이 없다.

    작가 글(캐릭터 프롬프트, 예시 대화의 양쪽 줄 — 사용자 라벨 줄도 작가가 쓴 글이다)과 대화 기록의 모델 응답 줄은
    `names` 로 `{{user}}`·`{{char}}` 를 바꾼다. 이 빌더는 이미지 태그를 지우지 않는다(캐릭터 작품에는 미디어 북이 없다).
    """
    example_lines = "\n".join(
        f"{prompt_set.user_label}: {names.expand(pair['userLine'])}\n"
        f"{prompt_set.character_assistant_label}: {names.expand(pair['characterLine'])}"
        for pair in example_dialogues
    )
    history_lines = [
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.character_assistant_label}: "
        f"{_turn_text(message, names, strip_tags=False)}"
        for message in history
    ]
    values = {
        "character_prompt": names.expand(character_prompt),
        "example_lines": example_lines,
        "user_persona": user_persona,
        "user_name": names.generation_user_name,
        "memory_note": memory_note,
        "memory_summary": memory_summary,
        "user_label": prompt_set.user_label,
        "user_message": user_message,
        "assistant_label": prompt_set.character_assistant_label,
    }
    return _render_generation(
        sections,
        scope="character",
        values=values,
        history_lines=history_lines,
        history_roles=[message.role for message in history],
    )


def build_story_generation_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    prompt_template: StoryPromptTemplate,
    setting_text: str | None,
    development_examples: list[dict[str, Any]],
    user_goal: str | None,
    rules: str | None,
    custom_prompt: str | None,
    prologue: str,
    history: list[ChatMessage],
    user_message: str,
    user_persona: str,
    memory_note: str,
    memory_summary: str,
    names: PromptNames,
    keyword_note_texts: list[str] | None = None,
    situation_note_texts: list[str] | None = None,
    shortcut_prompt: str | None = None,
) -> str:
    """생성 프롬프트를 조립한다 — 스토리 챗 전용.

    `user_persona`·`memory_note`·`memory_summary`는 `build_generation_prompt`와 같다(필수 인자).

    "스토리 설정 템플릿+시작설정 프롤로그" 뒤에 최근 히스토리, 매칭된 키워드북 정보
    (사용자에게는 비노출, `match_keyword_notes`로 이미 걸러진 결과만 받음), (단축어
    실행 시) 단축어 프롬프트, 이번 턴의 사용자 메시지 순으로 마무리한다.

    `[키워드북]`은 `[대화 기록]`
    **뒤**에 온다 — 변하는 속도가 느린 것이 앞, 빠른 것이 뒤여야 캐시 프리픽스가
    안정된다는 이유는 `prompt_sections.order` 시드값이 이미 반영하고 있다.

    `situation_note_texts` 는 스탯 조건이 참인 상황 노트 본문(호출부가 이미 골라 순서대로 넘긴다)이다. 값이
    비면 빈 문자열을 넘겨 conditional 섹션째 빠지게 한다 — 노트가 없는 방의 프롬프트는 이 인자 이전과 같다.

    전개 예시(`development_examples`)는 `story_example_label`("서술자")을, 그 외
    자리(히스토리·마지막 프레임)는 `story_assistant_label`("진행자")을 쓴다 —
    같은 스토리 챗인데 자리마다 라벨이 다른 것은 표류가 아니라 실측된 현재 동작이라
    여기서 통일하지 않는다.

    `prologue` 와 히스토리 본문에서는 미디어 북 이미지 태그를 지운다. 태그는 화면에서만 그림이 되는
    표지라, 모델이 받으면 태그를 흉내 내거나 인물·장면 이름이 문맥을 오염시킨다. 첫 메시지(작성자 글의
    복사본)가 히스토리로 매 턴 다시 들어오므로 히스토리는 역할과 무관하게 모든 줄에 건다. 이번 턴
    `user_message` 는 사용자가 방금 친 글이라 그대로 싣는다.

    작가 글 필드 전부(설정·커스텀·규칙·목표·전개 예시의 양쪽 줄·프롤로그·키워드북·상황 노트·단축어 프롬프트)와 대화
    기록의 모델 응답 줄은 태그를 지운 뒤 `names` 로 `{{user}}` 를 바꾼다. 단축어 프롬프트는 화면이 같은 이름으로 바꿔
    보낸 사용자 메시지와 한 프롬프트에 함께 실린다.
    """
    example_lines = "\n".join(
        f"{prompt_set.user_label}: {names.expand(pair['userLine'])}\n"
        f"{prompt_set.story_example_label}: {names.expand(pair['assistantLine'])}"
        for pair in development_examples
    )
    history_lines = [
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.story_assistant_label}: "
        f"{_turn_text(message, names, strip_tags=True)}"
        for message in history
    ]
    values = {
        "setting_text": names.expand(setting_text or ""),
        "custom_prompt": names.expand(custom_prompt or ""),
        "rules": names.expand(rules or ""),
        "user_goal": names.expand(user_goal or ""),
        "example_lines": example_lines,
        "prologue": names.expand(strip_media_tags(prologue)),
        "user_persona": user_persona,
        "user_name": names.generation_user_name,
        "memory_note": memory_note,
        "memory_summary": memory_summary,
        "keyword_note_lines": "\n".join(names.expand(text) for text in keyword_note_texts) if keyword_note_texts else "",
        "situation_note_lines": (
            "\n".join(names.expand(text) for text in situation_note_texts) if situation_note_texts else ""
        ),
        "shortcut_prompt": names.expand(shortcut_prompt or ""),
        "user_label": prompt_set.user_label,
        "user_message": user_message,
        "assistant_label": prompt_set.story_assistant_label,
    }
    return _render_generation(
        sections,
        scope="story",
        variant=_story_generation_variant(prompt_template),
        values=values,
        history_lines=history_lines,
        history_roles=[message.role for message in history],
    )


def stat_rule_letters(index: int) -> str:
    """판정 스탯 순번(0부터)의 글자 — a…z, 그다음 aa, ab… 스탯 수에 상한이 없어 26개를 넘어도 겹치지 않아야 한다. 규칙 id 가
    글자 + 숫자라 글자 부분이 겹치지 않으면 id 전체가 겹치지 않는다."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def build_stat_rule_judgment_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    stat_defs: list[StatDef],
    rules_by_stat_id: Mapping[uuid.UUID, Sequence[StatRule]],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> tuple[str, dict[str, tuple[str, StatRule]]]:
    """규칙 판정 프롬프트를 조립한다 — 판정 LLM 이 이번 턴에 발동한 규칙의 짧은 id 만 고르게 한다(`StatRuleJudgmentResult`).
    반환은 프롬프트와, 짧은 id → (스탯 entity_id, 규칙) 대응표다(`apply_rule_judgment` 가 받는다).

    규칙이 있는 판정 스탯(카운터가 아닌 스탯)마다 `이름 / 범위 / 설명` 한 줄과 규칙 줄 `- <짧은 id>: <조건>` 을 싣는다. 짧은
    id 는 스탯 글자(`stat_rule_letters`, 실린 스탯의 `stat_defs` 순서) + 그 스탯 안의 규칙 순번(`order` 순, 1부터)이다. 카운터
    스탯은 판정을 받지 않아 싣지 않는다. 규칙이 없는 판정 스탯도 싣지 않는다 — 고를 규칙이 없으니 판정할 것이 없고, 그 값은
    그대로 남는다(발행은 그런 스탯을 막으므로 초안 미리보기에서만 생긴다).

    **현재값과 폭은 싣지 않는다.** 폭이 규칙에 고정돼 있어 새 값을 계산하는 데 현재값이 필요 없고, 맥락에 놓인 점수는 판정을
    끌어당긴다 — 절대값을 내던 옛 판정에서 다른 스탯 줄의 현재값을 이 스탯의 기준으로 읽어 새 값을 낸 오독이 실제로 있었다.

    히스토리 전체는 싣지 않고 이번 턴만 싣는다. 스탯 변화는 "이번 턴에" 무엇이 일어났는지의 함수이지 누적 서사가 아니다 —
    `build_ending_judgment_prompt` 는 반대로 히스토리를 싣는다(엔딩은 지금까지의 대화가 기준을 충족하는지 묻는 누적 판단이다).

    스탯 이름·설명·규칙 조건(작가 글)과 이번 턴 모델 응답은 `names` 로 `{{user}}` 를 바꾸고, 사용자 메시지는 그대로 둔다. 이름
    한 줄에 실제 이름을 싣는다."""
    rule_ids: dict[str, tuple[str, StatRule]] = {}
    blocks: list[str] = []
    judged = [
        stat_def
        for stat_def in stat_defs
        if stat_def.per_turn_delta is None and rules_by_stat_id.get(stat_def.entity_id)
    ]
    for stat_index, stat_def in enumerate(judged):
        letters = stat_rule_letters(stat_index)
        lines = [
            f"{names.expand(stat_def.name)} / 범위 [{stat_def.min_value}, {stat_def.max_value}] / "
            f"{names.expand(stat_def.description)}"
        ]
        rules = sorted(rules_by_stat_id[stat_def.entity_id], key=lambda rule: rule.order)
        for rule_index, rule in enumerate(rules, start=1):
            rule_id = f"{letters}{rule_index}"
            rule_ids[rule_id] = (str(stat_def.entity_id), rule)
            lines.append(f"- {rule_id}: {names.expand(rule.condition)}")
        blocks.append("\n".join(lines))
    values = {
        "stat_lines": "\n\n".join(blocks),
        "user_label": prompt_set.user_label,
        "user_message": user_message,
        "assistant_label": prompt_set.story_assistant_label,
        "assistant_message": names.expand(assistant_message),
        "user_name": names.judgment_user_name,
    }
    return render_prompt_channel(sections, channel="stat_rule_judgment", scope="story", values=values), rule_ids


class StatRuleJudgmentResult(BaseModel):
    """이번 턴에 실제로 일어난 일에 해당하는 규칙의 id 목록. 해당하는 규칙이 없으면 빈 목록."""

    fired_rule_ids: list[str]


@dataclass(frozen=True)
class StatJudgmentRequest:
    """한 턴의 스탯 판정 요청. `prompt` 가 None 이면 판정 LLM 을 부르지 않고 "발동한 규칙 없음"으로 반영한다(카운터는 굴린다).
    `rule_ids` 는 짧은 id 대응표다(`build_stat_rule_judgment_prompt`)."""

    prompt: str | None
    rule_ids: dict[str, tuple[str, StatRule]]


def prepare_stat_judgment(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    stat_defs: list[StatDef],
    rules_by_stat_id: Mapping[uuid.UUID, Sequence[StatRule]],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> StatJudgmentRequest:
    """이번 턴의 스탯 판정 요청을 만든다. 실채팅과 빌더 미리보기가 함께 쓴다. `rules_by_stat_id` 는 스탯 entity_id → 그 스탯의
    규칙이다.

    규칙이 있는 판정 스탯이 하나도 없으면(스탯이 없거나, 카운터뿐이거나, 초안의 판정 스탯에 아직 규칙이 없으면) 판정을 부르지
    않는 요청(`prompt=None`)을 돌려준다. 실패가 아니라 "변화 없음"이다 — 호출부는 카운터를 굴리고 엔딩 판정도 그대로 이어 간다.
    엔딩 판정은 스탯 반영 결과가 있을 때만 돌기 때문에, 이것을 실패로 돌리면 스탯 판정이 필요 없는 작품의 엔딩이 멈춘다.

    규칙 판정 채널의 렌더가 빈 문자열이어도(그 채널 행이 없는 프롬프트 세트) 빈 프롬프트로 판정을 부르지 않고 같은 "변화 없음"
    요청을 돌려주며 경고를 남긴다 — 세트 설정 문제라 스탯은 멈추지만 대화와 엔딩은 이어진다."""
    prompt, rule_ids = build_stat_rule_judgment_prompt(
        prompt_set=prompt_set,
        sections=sections,
        stat_defs=stat_defs,
        rules_by_stat_id=rules_by_stat_id,
        user_message=user_message,
        assistant_message=assistant_message,
        names=names,
    )
    if not rule_ids:
        return StatJudgmentRequest(prompt=None, rule_ids={})
    if not prompt:
        logger.warning("스탯 규칙 판정 채널 렌더가 비었다(프롬프트 세트에 행이 없다) — 이번 턴 스탯은 바꾸지 않는다")
        return StatJudgmentRequest(prompt=None, rule_ids={})
    return StatJudgmentRequest(prompt=prompt, rule_ids=rule_ids)


def build_ending_judgment_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    judgment_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    memory_summary: str,
    names: PromptNames,
) -> str:
    """판단 프롬프트를 조립한다 — 엔딩 판정(스토리 챗 전용).

    엔딩 하나의 judgment_prompt(판정 기준)와 이번 턴까지의 대화를 근거로
    LLMClient.generateStructured()가 EndingJudgmentResult(구조화 출력)로 그 엔딩의
    발동 조건 충족 여부를 판단하게 한다. 여러 엔딩이 있으면 이 함수를 엔딩별로 호출한다.

    여긴 `history`를 싣는다 — `build_stat_rule_judgment_prompt`는 뺐다.
    엔딩은 "지금까지의 대화가 기준을 충족하는지"를 묻는 누적 판단이라 이번 턴
    만으로는 판정할 수 없지만, 스탯 변화는 이번 턴에 무엇이 일어났는지의 함수라 히스토리가
    필요 없다. 이 비대칭이 그 변경의 핵심이다.

    `turn_lines`는 히스토리와 이번 턴을 한 블롭으로 만들어 라벨을 플레이스홀더로 뽑을 수
    없다(히스토리가 비면 개행 아티팩트가 낀다) — 그래도 그 블롭을 만드는 이 코드가
    `prompt_set.story_assistant_label`을 읽으므로 라벨은 여전히 DB에서 온다.

    `memory_summary`는 대화 기록 앞에 싣는 현재 요약이다. `""`이면 섹션째 빠져 이 인자가 없던 시절과
    바이트까지 같다(기본값이 없는 이유는 생성 빌더와 같다).

    히스토리 본문의 미디어 북 이미지 태그는 생성 빌더와 같은 이유로 지운다.

    판정 기준(작가 글)과 모델 응답 줄(대화 기록·이번 턴)은 `names` 로 `{{user}}` 를 바꾸고, 이름 한 줄에 실제 이름을
    싣는다.
    """
    turn_lines = [
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.story_assistant_label}: "
        f"{_turn_text(message, names, strip_tags=True)}"
        for message in history
    ]
    turn_lines.append(f"{prompt_set.user_label}: {user_message}")
    turn_lines.append(f"{prompt_set.story_assistant_label}: {names.expand(assistant_message)}")

    values = {
        "turn_lines": "\n".join(turn_lines),
        "judgment_prompt": names.expand(judgment_prompt),
        "memory_summary": memory_summary,
        "user_name": names.judgment_user_name,
    }
    return render_prompt_channel(sections, channel="ending_judgment", scope="story", values=values)


class EndingJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 엔딩 판정."""

    triggered: bool


def situational_image_lines(situational_images: Sequence[SituationalImage], *, names: PromptNames) -> str:
    """캐릭터 상황별 이미지 판정의 후보 줄 — 이미지마다 id 와 노출 조건(order 오름차순은 호출부가 정한다). 노출 조건은
    작가 글이라 `{{user}}`·`{{char}}` 를 바꾼다."""
    return "\n".join(
        f"- imageEntityId={image.entity_id}, 노출 조건={names.expand(image.trigger_condition)}"
        for image in situational_images
    )


@dataclass(frozen=True)
class MediaCellCandidate:
    """스토리 미디어 북 칸 판정의 후보 한 칸. 실채팅은 방 버전의 칸 행에서, 미리보기는 빌더 페이로드에서 만든다."""

    entity_id: uuid.UUID
    person: str
    scene: str
    situation_description: str


def media_cell_image_lines(cells: Sequence[MediaCellCandidate], *, names: PromptNames) -> str:
    """스토리 칸 판정의 후보 줄 — 판정 근거는 칸의 인물·장면 이름과, 작성자가 적었으면 상황 설명이다(비었으면
    그 항목을 줄에서 뺀다 — 빈 값을 근거처럼 보이게 하지 않는다). 상황 설명만 `{{user}}` 를 바꾼다 — 인물·장면 이름은
    이미지 태그(`{{img::인물/장면}}`)의 키라 바꾸면 태그와 어긋난다."""
    return "\n".join(
        f"- imageEntityId={cell.entity_id}, 인물={cell.person}, 장면={cell.scene}"
        + (f", 상황 설명={names.expand(cell.situation_description)}" if cell.situation_description else "")
        for cell in cells
    )


def build_image_judgment_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    scope: Literal["character", "story"],
    assistant_label: str,
    image_lines: str,
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> str:
    """판단 프롬프트를 조립한다 — 이번 턴에 붙일 그림 하나 고르기. 캐릭터 상황별 이미지(`scope="character"`,
    후보 = `situational_image_lines`)와 스토리 미디어 북 칸(`scope="story"`, 후보 = `media_cell_image_lines`)이
    같은 채널을 쓴다.

    후보 목록과 이번 턴까지의 대화를 근거로 LLMClient.generateStructured()가 ImageMatchJudgmentResult(구조화
    출력)로 하나를 고른다. 응답은 항상 단수라 여러 후보가 맞을 때의 고르는 법은 레인 문안(DB)이 정한다 — 현재
    문안은 캐릭터 레인이 목록에서 더 앞의 하나를, story 레인이 상황 설명이 이번 턴과 가장 구체적으로 맞는 칸
    하나를 고르게 지시한다(칸 목록의 축 순서는 우선순위가 아니다).

    `assistant_label` 은 레인이 게시 검증하는 라벨을 넘긴다 — 캐릭터는 `character_assistant_label`, 스토리는
    `story_assistant_label`(story 레인 게시 검증은 캐릭터 라벨을 보지 않는다).

    히스토리 본문의 미디어 북 태그는 생성 빌더와 같은 이유로 지운다(스토리 첫 메시지가 칸 id 형태 태그를 담는다.
    태그가 없는 글은 바이트 그대로다). 모델 응답 줄(대화 기록·이번 턴)은 그다음 `names` 로 `{{user}}`·`{{char}}` 를
    바꾸고, 이름 한 줄에 실제 이름을 싣는다. 후보 줄(`image_lines`)은 후보 줄 헬퍼가 이미 바꿔 넘긴다.

    렌더 결과가 비면 `PromptRenderError` — 레인에 이 채널 행이 없는 세트(배포 직후 활성 세트 캐시에 남은 옛
    story 세트)로는 빈 프롬프트로 판정을 부르지 않고 그 턴의 그림만 포기하게 한다(`fold_memory` 와 같은 가드).
    """
    turn_lines = [
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else assistant_label}: "
        f"{_turn_text(message, names, strip_tags=True)}"
        for message in history
    ]
    turn_lines.append(f"{prompt_set.user_label}: {user_message}")
    turn_lines.append(f"{assistant_label}: {names.expand(assistant_message)}")

    values = {
        "image_lines": image_lines,
        "turn_lines": "\n".join(turn_lines),
        "user_name": names.judgment_user_name,
    }
    prompt = render_prompt_channel(sections, channel="image_judgment", scope=scope, values=values)
    if not prompt:
        raise PromptRenderError(f"channel='image_judgment' scope={scope!r} 렌더 결과가 비었다 — 이 레인 세트에 행이 없다")
    return prompt


class ImageMatchJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 상황별 이미지 매칭(캐릭터 챗 전용)."""

    matched_image_entity_id: str | None


class MemorySummaryResult(BaseModel):
    """대화 요약 결과. `summary`에는 요약 본문만 담는다."""

    summary: str


def build_memory_summary_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    previous_summary: str,
    turns: list[ChatMessage],
    names: PromptNames,
) -> str:
    """요약 호출 프롬프트를 조립한다 — 긴 방에서 윈도우 밖으로 접을 대화를 요약한다.

    지시문 전체가 `memory_summary` channel(DB)에 있고, 코드는 직전 요약과 접을 대화 줄만 만든다.
    `previous_summary`가 `""`(첫 요약)이면 그 섹션은 통째로 빠진다. 화자 라벨은 생성 프롬프트와 같은
    것을 쓴다 — 스토리 챗은 `story_assistant_label`, 캐릭터 챗은 `character_assistant_label`.
    노트·스탯·계정 정보는 인자로 받지 않는다: 노트는 매 턴 따로 실리고, 스탯 수치가 요약에 새면
    진실 소스가 둘이 되며, 계정 정보는 프롬프트에 넣지 않는다. 사용자 이름은 계정 정보가 아니라 이야기 속에서 사용자를
    부르는 이름이라(대화 프로필 이름) 이름 한 줄로 싣는다 — 요약이 대화 속 그 이름이 사용자라는 걸
    알게 하려는 것이다. 모델 응답 줄은 `names` 로 `{{user}}`·`{{char}}` 를 바꾼다(태그는 지우지 않는다 — 요약 입력에는
    작가 글의 복사본인 첫 메시지가 빠져 있다)."""
    assistant_label = prompt_set.story_assistant_label if is_story_chat else prompt_set.character_assistant_label
    turn_lines = "\n".join(
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else assistant_label}: "
        f"{_turn_text(message, names, strip_tags=False)}"
        for message in turns
    )
    values = {"previous_summary": previous_summary, "turn_lines": turn_lines, "user_name": names.judgment_user_name}
    return render_prompt_channel(
        sections, channel="memory_summary", scope="story" if is_story_chat else "character", values=values
    )
