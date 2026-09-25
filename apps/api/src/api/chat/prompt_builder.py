from collections.abc import Sequence
from string import Formatter
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StatDef, StoryPromptTemplate

# `"legacy"`를 이 유니온에 넣지 않는다 — 넣는
# 순간 `list_prompt_sets`가 legacy를 걸러야 할 이유가 사라지고 FE가 4번째 탭을 만들게 된다.
PromptLane = Literal["story", "character", "publish_filter"]

# mypy는 각 원소가 PromptLane인지는 보지만 "전부 들어 있는지"는 못 본다 — 그 한 칸은
# tests가 typing.get_args로 메운다.
_PROMPT_LANES: tuple[PromptLane, ...] = ("story", "character", "publish_filter")


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
    ("generation", "history"): frozenset({"history_lines"}),
    ("generation", "keyword_notes"): frozenset({"keyword_note_lines"}),
    ("generation", "shortcut_prompt"): frozenset({"shortcut_prompt"}),
    ("generation", "final_frame"): frozenset({"user_label", "user_message", "assistant_label"}),
    ("stat_judgment", "stat_defs_intro"): frozenset({"stat_lines"}),
    ("stat_judgment", "turn_context"): frozenset(
        {"user_label", "user_message", "assistant_label", "assistant_message"}
    ),
    ("stat_judgment", "judgment_instruction"): frozenset(),
    ("ending_judgment", "history_header"): frozenset(),
    ("ending_judgment", "turn_context"): frozenset({"turn_lines"}),
    ("ending_judgment", "criteria"): frozenset({"judgment_prompt"}),
    ("image_judgment", "image_list_intro"): frozenset({"image_lines"}),
    ("image_judgment", "turn_context"): frozenset({"turn_lines"}),
    ("image_judgment", "judgment_instruction"): frozenset(),
    ("publish_filter", "intro_instruction"): frozenset(),
    ("publish_filter", "name"): frozenset({"name"}),
    ("publish_filter", "one_liner"): frozenset({"one_liner"}),
    ("publish_filter", "intro"): frozenset({"intro"}),
    ("publish_filter", "setting_text"): frozenset({"setting_text"}),
    ("publish_filter", "development_example_legacy"): frozenset({"development_example"}),
    ("publish_filter", "custom_prompt"): frozenset({"custom_prompt"}),
    ("publish_filter", "rules"): frozenset({"rules"}),
    ("publish_filter", "user_goal"): frozenset({"user_goal"}),
    ("publish_filter", "development_examples_pairs"): frozenset({"example_lines"}),
    ("publish_filter", "example_dialogues"): frozenset({"dialogue_lines"}),
    ("publish_filter", "character_prompt"): frozenset({"character_prompt"}),
    ("publish_filter", "detail_description"): frozenset({"detail_description"}),
    ("publish_filter", "starting_setups"): frozenset({"setup_lines"}),
    ("publish_filter", "verdict_instruction"): frozenset(),
}


async def load_active_prompt_set(
    db: AsyncSession, *, lane: PromptLane
) -> tuple[PromptSet, list[PromptSection]]:
    """`lane`의 활성 세트(published 중 `published_at`이 가장 최신인 것)와 그 섹션 전부를
    읽는다. `legal_documents`의 `_get_latest_published`와 같은 모양이다. 활성 세트가 없으면
    `PromptSetNotFoundError` — downgrade 직후처럼 테이블 자체가 없는 게 아니라
    행만 없는 상태는 만들어지기 어렵지만, 그 경우에도 조용히 넘어가지 않는다.

    `lane`은 키워드 전용이다 — 현행 호출부가 전부 단일 인자였으므로, 위치 인자로 두면
    두 번째 인자가 섞여 들어가는 실수가 타입 체커를 통과할 여지가 생긴다."""
    prompt_set = await db.scalar(
        select(PromptSet)
        .where(PromptSet.status == "published", PromptSet.lane == lane)
        .order_by(PromptSet.published_at.desc())
        .limit(1)
    )
    if prompt_set is None:
        raise PromptSetNotFoundError(f"활성 프롬프트 세트가 없다 (lane={lane})")
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
# 줄을 생략한다 — 이 함수는 SSE 제너레이터 본문(`_build_prompt`)에서 불려서 예외를 내면
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
    if not user_persona:
        return False
    scope = "story" if is_story_chat else "character"
    variant = _story_generation_variant(template) if template is not None else ""
    selected = select_sections_for_render(sections, channel="generation", scope=scope, variant=variant)
    return any(section.slot == "user_persona" for section in selected)


def build_generation_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    character_prompt: str,
    example_dialogues: list[dict[str, Any]],
    history: list[ChatMessage],
    user_message: str,
    user_persona: str,
) -> str:
    """생성 프롬프트를 조립한다 — 캐릭터 챗 전용.

    캐릭터 프롬프트 뒤에 예시 대화("말투 예시")를 매 턴 포함하고, 최근 메시지
    히스토리와 이번 턴의 사용자 메시지로 마무리한다. 화자 라벨(`사용자`/`캐릭터`)은
    코드가 조립하는 줄 안에서도 `prompt_set`에서 읽는다.

    `user_persona`는 `format_user_persona`의 결과이거나 `""`(프로필 없음·선택 없음)다.
    `""`이면 conditional 섹션째 드롭되어 이 인자가 없던 시절과 바이트까지 같다.
    기본값이 없는 이유는 호출부 누락을 mypy가 잡게 하려는
    것이다.
    """
    example_lines = "\n".join(
        f"{prompt_set.user_label}: {pair['userLine']}\n{prompt_set.character_assistant_label}: {pair['characterLine']}"
        for pair in example_dialogues
    )
    history_lines = "\n".join(
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.character_assistant_label}: "
        f"{message.content}"
        for message in history
    )
    values = {
        "character_prompt": character_prompt,
        "example_lines": example_lines,
        "user_persona": user_persona,
        "history_lines": history_lines,
        "user_label": prompt_set.user_label,
        "user_message": user_message,
        "assistant_label": prompt_set.character_assistant_label,
    }
    return render_prompt_channel(sections, channel="generation", scope="character", values=values)


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
    keyword_note_texts: list[str] | None = None,
    shortcut_prompt: str | None = None,
) -> str:
    """생성 프롬프트를 조립한다 — 스토리 챗 전용.

    `user_persona`는 `build_generation_prompt`와 같다(필수 인자).

    "스토리 설정 템플릿+시작설정 프롤로그" 뒤에 최근 히스토리, 매칭된 키워드북 정보
    (사용자에게는 비노출, `match_keyword_notes`로 이미 걸러진 결과만 받음), (단축어
    실행 시) 단축어 프롬프트, 이번 턴의 사용자 메시지 순으로 마무리한다.

    `[키워드북]`은 `[대화 기록]`
    **뒤**에 온다 — 변하는 속도가 느린 것이 앞, 빠른 것이 뒤여야 캐시 프리픽스가
    안정된다는 이유는 `prompt_sections.order` 시드값이 이미 반영하고 있다.

    전개 예시(`development_examples`)는 `story_example_label`("서술자")을, 그 외
    자리(히스토리·마지막 프레임)는 `story_assistant_label`("진행자")을 쓴다 —
    같은 스토리 챗인데 자리마다 라벨이 다른 것은 표류가 아니라 실측된 현재 동작이라
    여기서 통일하지 않는다.
    """
    example_lines = "\n".join(
        f"{prompt_set.user_label}: {pair['userLine']}\n{prompt_set.story_example_label}: {pair['assistantLine']}"
        for pair in development_examples
    )
    history_lines = "\n".join(
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.story_assistant_label}: "
        f"{message.content}"
        for message in history
    )
    values = {
        "setting_text": setting_text or "",
        "custom_prompt": custom_prompt or "",
        "rules": rules or "",
        "user_goal": user_goal or "",
        "example_lines": example_lines,
        "prologue": prologue,
        "user_persona": user_persona,
        "history_lines": history_lines,
        "keyword_note_lines": "\n".join(keyword_note_texts) if keyword_note_texts else "",
        "shortcut_prompt": shortcut_prompt or "",
        "user_label": prompt_set.user_label,
        "user_message": user_message,
        "assistant_label": prompt_set.story_assistant_label,
    }
    return render_prompt_channel(
        sections, channel="generation", scope="story", variant=_story_generation_variant(prompt_template), values=values
    )


def build_stat_judgment_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    stat_defs: list[StatDef],
    current_stats: dict[str, float],
    user_message: str,
    assistant_message: str,
) -> str:
    """판단 프롬프트를 조립한다 — 스탯 변경 판단(스토리 챗 전용).

    스탯 정의(설명/범위/현재값)와 **이번 턴만**을 근거로 LLMClient.generateStructured()가
    StatJudgmentResult(구조화 출력)로 각 스탯의 변경 여부를 판단하게 한다.

    히스토리 전체를 안 싣는다. 스탯
    변화는 "이번 턴에" 무엇이 일어났는지의 함수이지 누적 서사가 아니다 — 아래 지시
    문구가 이미 "마지막 사용자 행동과 그에 대한 응답"만 근거로 명시하고 있었으니 실제
    입력도 거기 맞춘다. `build_ending_judgment_prompt`는 반대로 히스토리를 싣는다 —
    엔딩은 "지금까지의 대화가 기준을 충족하는지"를 묻는 누적 판단이라 이번 턴만으로는
    판정할 수 없다. 이 비대칭이 이 변경의 핵심이다.
    """
    # `per_turn_delta`가 있는 스탯은 `apply_stat_changes`가 매 턴 결정적으로 굴리고 LLM 판단은
    # 무시된다. 그래도 현재값은 서사 판단의 근거이므로 목록에는 남기고, 판단 대상이 아니라는
    # 것만 표시해 불필요한 출력을 줄인다.
    stat_lines = "\n".join(
        f"- statId={stat_def.entity_id}, 이름={stat_def.name}, 설명={stat_def.description}, "
        f"범위=[{stat_def.min_value}, {stat_def.max_value}], "
        f"현재값={current_stats.get(str(stat_def.entity_id), stat_def.initial_value)}"
        + ("  ※ 시스템이 매 턴 자동 조정하는 값이다. statChanges에 넣지 마라." if stat_def.per_turn_delta is not None else "")
        for stat_def in stat_defs
    )
    values = {
        "stat_lines": stat_lines,
        "user_label": prompt_set.user_label,
        "user_message": user_message,
        "assistant_label": prompt_set.story_assistant_label,
        "assistant_message": assistant_message,
    }
    return render_prompt_channel(sections, channel="stat_judgment", scope="story", values=values)


class StatChangeJudgment(BaseModel):
    stat_id: str
    new_value: float


class StatJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 스탯 변경."""

    stat_changes: list[StatChangeJudgment]


def build_ending_judgment_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    judgment_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> str:
    """판단 프롬프트를 조립한다 — 엔딩 판정(스토리 챗 전용).

    엔딩 하나의 judgment_prompt(판정 기준)와 이번 턴까지의 대화를 근거로
    LLMClient.generateStructured()가 EndingJudgmentResult(구조화 출력)로 그 엔딩의
    발동 조건 충족 여부를 판단하게 한다. 여러 엔딩이 있으면 이 함수를 엔딩별로 호출한다.

    여긴 `history`를 싣는다 — `build_stat_judgment_prompt`는 뺐다.
    엔딩은 "지금까지의 대화가 기준을 충족하는지"를 묻는 누적 판단이라 이번 턴
    만으로는 판정할 수 없지만, 스탯 변화는 이번 턴에 무엇이 일어났는지의 함수라 히스토리가
    필요 없다. 이 비대칭이 그 변경의 핵심이다.

    `turn_lines`는 히스토리와 이번 턴을 한 블롭으로 만들어 라벨을 플레이스홀더로 뽑을 수
    없다(히스토리가 비면 개행 아티팩트가 낀다) — 그래도 그 블롭을 만드는 이 코드가
    `prompt_set.story_assistant_label`을 읽으므로 라벨은 여전히 DB에서 온다.
    """
    turn_lines = [
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.story_assistant_label}: "
        f"{message.content}"
        for message in history
    ]
    turn_lines.append(f"{prompt_set.user_label}: {user_message}")
    turn_lines.append(f"{prompt_set.story_assistant_label}: {assistant_message}")

    values = {
        "turn_lines": "\n".join(turn_lines),
        "judgment_prompt": judgment_prompt,
    }
    return render_prompt_channel(sections, channel="ending_judgment", scope="story", values=values)


class EndingJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 엔딩 판정."""

    triggered: bool


def build_image_judgment_prompt(
    *,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    situational_images: list[SituationalImage],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> str:
    """판단 프롬프트를 조립한다 — 상황별 이미지 매칭(캐릭터 챗 전용).

    등록된 이미지의 노출 조건(trigger_condition)과 이번 턴까지의 대화를 근거로
    LLMClient.generateStructured()가 ImageMatchJudgmentResult(구조화 출력)로 매칭되는 이미지가
    있는지 판단하게 한다. 목록을 order 오름차순으로 제시하고, 여러 조건이 동시에 충족돼도
    응답은 항상 단수이므로 더 앞(우선순위가 높은) 이미지 하나만 고르도록 명시적으로 지시한다.
    """
    image_lines = "\n".join(
        f"- imageEntityId={image.entity_id}, 노출 조건={image.trigger_condition}"
        for image in situational_images
    )
    turn_lines = [
        f"{prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.character_assistant_label}: "
        f"{message.content}"
        for message in history
    ]
    turn_lines.append(f"{prompt_set.user_label}: {user_message}")
    turn_lines.append(f"{prompt_set.character_assistant_label}: {assistant_message}")

    values = {
        "image_lines": image_lines,
        "turn_lines": "\n".join(turn_lines),
    }
    return render_prompt_channel(sections, channel="image_judgment", scope="character", values=values)


class ImageMatchJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 상황별 이미지 매칭(캐릭터 챗 전용)."""

    matched_image_entity_id: str | None
