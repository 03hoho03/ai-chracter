"""작가 글의 `{{user}}`·`{{char}}` 가 모델로 가는 사본에서 이름으로 바뀌는지 — 빌더마다 작가 글이 들어가는 자리 전부와,
바뀌면 안 되는 자리(사용자가 쓴 글)를 함께 본다.

작가 글은 원문 그대로 저장되고 프롬프트를 조립하는 순간 바뀐다. 사용자 메시지는 화면이 보내기 전에 이미 바꿔 저장하므로
대화 기록의 사용자 줄과 이번 턴 사용자 메시지는 그대로 둔다 — 거기 남은 `{{user}}` 는 사용자가 친 글자다.

섹션은 이 파일에서 만든 한 줄짜리 body 라 렌더 결과 전체를 문자열로 비교한다. 이름은 받침 있는 이름("지훈")으로 둬
조사 보정이 실제로 일어났는지(`{{user}}는` → `지훈은`)까지 드러나게 한다.
"""

import uuid

from api.chat.keyword_notes import match_keyword_notes, recent_scan_turns
from api.chat.prompt_builder import (
    MediaCellCandidate,
    PromptNames,
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_memory_summary_prompt,
    build_stat_rule_judgment_prompt,
    build_story_generation_prompt,
    media_cell_image_lines,
    situational_image_lines,
)
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import KeywordNote, StatDef, StatRule, StoryPromptTemplate

_STORY = PromptNames(persona_name="지훈", char_name=None)
_CHARACTER = PromptNames(persona_name="지훈", char_name="하늘")


def _section(channel: str, scope: str, body: str) -> PromptSection:
    return PromptSection(channel=channel, scope=scope, slot="all", variant="", body=body, conditional=False, order=1)


def _prompt_set() -> PromptSet:
    return PromptSet(
        status="published",
        user_label="U",
        story_assistant_label="N",
        story_example_label="E",
        character_assistant_label="C",
    )


def _message(role: ChatMessageRole, content: str) -> ChatMessage:
    return ChatMessage(chat_room_id=uuid.uuid4(), role=role, content=content)


def _history() -> list[ChatMessage]:
    return [
        _message(ChatMessageRole.ASSISTANT, "{{user}}는 {{img::민아/옥상}}문 앞에 선다."),
        _message(ChatMessageRole.USER, "{{user}}라고 쳤다"),
    ]


# ---- 이름 고르기 ---------------------------------------------------------------------------


def test_prompt_names_choose_the_macro_name_and_the_name_line_values() -> None:
    """`{{user}}` 는 언제나 이름이 있다(프로필이 없으면 "당신"). 판정·요약의 이름 한 줄은 프로필 이름이 있을 때만 값이
    있어 비면 섹션째 빠진다. 생성 채널의 이름 한 줄은 늘 비어 있다 — 프로필이 있으면 프로필 섹션이 이미 이름을 준다."""
    with_persona = PromptNames(persona_name="지훈", char_name=None)
    nothing = PromptNames(persona_name=None, char_name=None)

    assert [names.expand("{{user}}는") for names in (with_persona, nothing)] == ["지훈은", "당신은"]
    assert [names.judgment_user_name for names in (with_persona, nothing)] == ["지훈", ""]
    assert [names.generation_user_name for names in (with_persona, nothing)] == ["", ""]


# ---- 생성 ----------------------------------------------------------------------------------


def test_story_generation_expands_every_author_field_and_assistant_history_only() -> None:
    body = "|".join(
        f"{{{name}}}"
        for name in (
            "setting_text",
            "custom_prompt",
            "rules",
            "user_goal",
            "example_lines",
            "prologue",
            "history_lines",
            "keyword_note_lines",
            "situation_note_lines",
            "shortcut_prompt",
            "user_message",
            "user_name",
        )
    )
    prompt = build_story_generation_prompt(
        prompt_set=_prompt_set(),
        sections=[_section("generation", "story", body)],
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="설정 {{user}}는",
        development_examples=[{"userLine": "예 {{user}}가", "assistantLine": "답 {{user}}를"}],
        user_goal="목표 {{user}}의",
        rules="규칙 {{user}}와",
        custom_prompt="커스텀 {{user}}야",
        prologue="{{img::민아/옥상}}프롤로그 {{user}}이",
        history=_history(),
        user_message="이번 {{user}}는",
        user_persona="",
        memory_note="",
        memory_summary="",
        keyword_note_texts=["키워드 {{user}}을"],
        situation_note_texts=["상황 {{user}}과"],
        shortcut_prompt="단축어 {{user}}로",
        names=_STORY,
    )

    assert prompt.split("|") == [
        "설정 지훈은",
        "커스텀 지훈아",
        "규칙 지훈과",
        "목표 지훈의",
        "U: 예 지훈이\nE: 답 지훈을",
        "프롤로그 지훈이",
        "N: 지훈은 문 앞에 선다.\nU: {{user}}라고 쳤다",
        "키워드 지훈을",
        "상황 지훈과",
        "단축어 지훈으로",
        "이번 {{user}}는",
        # 프로필이 있으면 생성 채널의 이름 한 줄은 비운다.
        "",
    ]


def test_story_generation_leaves_char_as_text() -> None:
    """스토리에는 `{{char}}` 가 가리킬 한 사람이 없다 — 몰래 지우지 않고 글자 그대로 둔다."""
    prompt = build_story_generation_prompt(
        prompt_set=_prompt_set(),
        sections=[_section("generation", "story", "{setting_text}")],
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="{{char}}가 {{user}}를 본다",
        development_examples=[],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="",
        history=[],
        user_message="",
        user_persona="",
        memory_note="",
        memory_summary="",
        names=_STORY,
    )

    assert prompt == "{{char}}가 지훈을 본다"


def test_character_generation_expands_prompt_examples_and_assistant_history() -> None:
    prompt = build_generation_prompt(
        prompt_set=_prompt_set(),
        sections=[
            _section(
                "generation", "character", "{character_prompt}|{example_lines}|{history_lines}|{user_message}|{user_name}"
            )
        ],
        character_prompt="{{char}}는 {{user}}를 기다린다",
        example_dialogues=[{"userLine": "{{char}}야", "characterLine": "{{user}}아"}],
        history=[
            _message(ChatMessageRole.ASSISTANT, "{{char}}가 웃는다"),
            _message(ChatMessageRole.USER, "{{char}}라고 쳤다"),
        ],
        user_message="{{user}} 그대로",
        user_persona="",
        memory_note="",
        memory_summary="",
        names=PromptNames(persona_name=None, char_name="하늘"),
    )

    assert prompt.split("|") == [
        "하늘은 당신을 기다린다",
        "U: 하늘아\nC: 당신아",
        "C: 하늘이 웃는다\nU: {{char}}라고 쳤다",
        "{{user}} 그대로",
        # 프로필이 없어도 생성 채널의 이름 한 줄은 비운다 — 슬롯 값은 늘 넘기되 빈 값이라 섹션째 빠진다.
        "",
    ]


# ---- 판정·요약 -----------------------------------------------------------------------------


def test_stat_judgment_expands_stat_name_description_rule_conditions_and_this_turn_response() -> None:
    stat = StatDef(
        entity_id=uuid.UUID(int=1),
        name="{{user}}의 용기",
        description="{{user}}가 겁먹으면 내려간다",
        min_value=0,
        max_value=10,
        initial_value=5,
    )
    rule = StatRule(entity_id=uuid.UUID(int=4), condition="{{user}}가 물러선다", delta=-1, order=0)

    prompt, _ = build_stat_rule_judgment_prompt(
        prompt_set=_prompt_set(),
        sections=[_section("stat_rule_judgment", "story", "{stat_lines}|{user_message}|{assistant_message}|{user_name}")],
        stat_defs=[stat],
        rules_by_stat_id={stat.entity_id: [rule]},
        user_message="{{user}} 그대로",
        assistant_message="{{user}}는 버틴다",
        names=_STORY,
    )

    assert prompt.split("|") == [
        "지훈의 용기 / 범위 [0, 10] / 지훈이 겁먹으면 내려간다\n- a1: 지훈이 물러선다",
        "{{user}} 그대로",
        "지훈은 버틴다",
        "지훈",
    ]


def test_ending_judgment_expands_criteria_and_assistant_lines() -> None:
    prompt = build_ending_judgment_prompt(
        prompt_set=_prompt_set(),
        sections=[_section("ending_judgment", "story", "{judgment_prompt}|{turn_lines}|{user_name}")],
        judgment_prompt="{{user}}가 떠나면",
        history=_history(),
        user_message="{{user}} 그대로",
        assistant_message="{{user}}는 떠난다",
        memory_summary="",
        names=_STORY,
    )

    assert prompt.split("|") == [
        "지훈이 떠나면",
        "N: 지훈은 문 앞에 선다.\nU: {{user}}라고 쳤다\nU: {{user}} 그대로\nN: 지훈은 떠난다",
        "지훈",
    ]


def test_image_judgment_expands_candidate_conditions_but_not_media_book_names() -> None:
    """칸의 인물·장면 이름은 이미지 태그의 키라 바꾸지 않는다 — 상황 설명만 바꾼다."""
    situational = situational_image_lines(
        [SituationalImage(entity_id=uuid.UUID(int=2), trigger_condition="{{char}}가 {{user}}를 볼 때", order=0)],
        names=_CHARACTER,
    )
    cells = media_cell_image_lines(
        [
            MediaCellCandidate(
                entity_id=uuid.UUID(int=3),
                person="{{user}}",
                scene="{{user}}의 방",
                situation_description="{{user}}가 웃는다",
            )
        ],
        names=_STORY,
    )
    prompt = build_image_judgment_prompt(
        prompt_set=_prompt_set(),
        sections=[_section("image_judgment", "character", "{image_lines}|{turn_lines}|{user_name}")],
        scope="character",
        assistant_label="C",
        image_lines=situational,
        history=[_message(ChatMessageRole.ASSISTANT, "{{char}}가 {{user}}를 반긴다")],
        user_message="{{char}} 그대로",
        assistant_message="{{char}}는 웃는다",
        names=_CHARACTER,
    )

    assert situational == f"- imageEntityId={uuid.UUID(int=2)}, 노출 조건=하늘이 지훈을 볼 때"
    assert cells == f"- imageEntityId={uuid.UUID(int=3)}, 인물={{{{user}}}}, 장면={{{{user}}}}의 방, 상황 설명=지훈이 웃는다"
    assert prompt.split("|") == [
        situational,
        "C: 하늘이 지훈을 반긴다\nU: {{char}} 그대로\nC: 하늘은 웃는다",
        "지훈",
    ]


def test_memory_summary_expands_assistant_lines_and_carries_the_name_line() -> None:
    prompt = build_memory_summary_prompt(
        prompt_set=_prompt_set(),
        sections=[_section("memory_summary", "story", "{turn_lines}|{user_name}")],
        is_story_chat=True,
        previous_summary="",
        turns=_history(),
        names=PromptNames(persona_name="모험가", char_name=None),
    )

    # 요약은 태그를 지우지 않는다(요약 입력에는 첫 메시지가 빠져 태그가 오지 않는다) — 바꾸기만 한다.
    assert prompt.split("|") == ["N: 모험가는 {{img::민아/옥상}}문 앞에 선다.\nU: {{user}}라고 쳤다", "모험가"]


def test_judgment_name_line_section_drops_without_an_actual_name() -> None:
    """이름 한 줄은 conditional 행이다 — 프로필이 없으면 값이 비어 섹션째 빠지고, "사용자의 이름: 당신" 같은 줄이
    나가지 않는다."""
    sections = [
        PromptSection(
            channel="stat_rule_judgment", scope="story", slot="user_name", variant="",
            body="사용자의 이름: {user_name}", conditional=True, order=1,
        ),
        _section("stat_rule_judgment", "story", "{user_message}"),
    ]
    sections[1].order = 2

    def render(names: PromptNames) -> str:
        prompt, _ = build_stat_rule_judgment_prompt(
            prompt_set=_prompt_set(), sections=sections, stat_defs=[], rules_by_stat_id={},
            user_message="메시지", assistant_message="응답", names=names,
        )
        return prompt

    assert render(PromptNames(persona_name=None, char_name=None)) == "메시지"
    assert render(_STORY) == "사용자의 이름: 지훈\n\n메시지"


# ---- 키워드 스캔 ---------------------------------------------------------------------------


def test_keyword_scan_reads_the_expanded_assistant_text() -> None:
    """키워드는 모델이 받는 글과 같은 글에서 찾는다 — 첫 메시지의 `{{user}}` 가 이름으로 바뀐 뒤 매칭한다. 사용자 줄은
    그대로다."""
    history = [_message(ChatMessageRole.ASSISTANT, "{{user}}는 {{img::민아/옥상}}문을 연다")]

    turns = recent_scan_turns(history, "{{user}}야", 0, names=_STORY)
    note = KeywordNote(
        entity_id=uuid.uuid4(), info_text="이름이 불렸다", trigger_keywords=["지훈"], exclude_keywords=[],
        sticky_turns=0, always_on=False, order=0,
    )

    assert [(turn.assistant_text, turn.user_texts) for turn in turns] == [("지훈은 문을 연다", ("{{user}}야",))]
    assert match_keyword_notes([note], history, "안녕", names=_STORY) == [note]
    # 이름이 다르면 같은 첫 메시지라도 걸리지 않는다 — 원문(`{{user}}`)이 아니라 바뀐 글을 본다는 뜻이다.
    assert match_keyword_notes([note], history, "안녕", names=PromptNames(None, None)) == []
