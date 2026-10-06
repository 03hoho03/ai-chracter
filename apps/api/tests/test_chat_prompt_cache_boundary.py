"""생성 프롬프트의 캐시 경계 — 빌더가 낸 블록 셋이 Claude 프롬프트 캐시에서 다음 턴의 앞부분과 맞는지.

캐시는 체크포인트(둘째 블록 끝)까지의 누적 내용으로 맞추고, 다음 요청은 자기 블록 경계를 거슬러 보며 그 내용을 찾는다.
그래서 이 파일이 지키는 성질은 "N 턴의 첫째+둘째 블록 = N+1 턴의 첫째 블록"이다. 깨지는 시나리오는 셋이다 — 경계가 한
칸 어긋나 히스토리 줄 사이의 줄바꿈이 엉뚱한 블록에 붙는 것(실측으로 적중 0), 블록을 이은 결과가 Gemini 로 가는 문자열과
달라지는 것, 히스토리가 비었는데 표지가 남아 조건부 섹션이 살아나는 것.
"""

import uuid

import pytest

from api.chat.prompt_builder import PromptNames, build_generation_prompt, build_story_generation_prompt
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StoryPromptTemplate
from api.llm.client import SegmentedPrompt

_NO_NAMES = PromptNames(persona_name=None, default_user_name="", char_name=None)
_PROMPT_SET = PromptSet(
    status="published", user_label="나", story_assistant_label="진행", story_example_label="서술", character_assistant_label="너"
)


def _section(slot: str, body: str, *, order: int, conditional: bool = True, scope: str = "both") -> PromptSection:
    return PromptSection(
        channel="generation", scope=scope, slot=slot, variant="", body=body, conditional=conditional, order=order
    )


_SECTIONS = [
    _section("character", "[설정]\n{character_prompt}", order=1, conditional=False, scope="character"),
    _section("setting", "[설정]\n{setting_text}", order=1, conditional=False, scope="story"),
    _section("memory_summary", "[지금까지의 이야기]\n{memory_summary}", order=2),
    _section("history", "[대화 기록]\n{history_lines}", order=3),
    _section("keyword_notes", "[키워드북]\n{keyword_note_lines}", order=4),
    _section("final_frame", "{user_label}: {user_message}\n{assistant_label}:", order=5, conditional=False),
]


def _msg(role: ChatMessageRole, content: str) -> ChatMessage:
    return ChatMessage(chat_room_id=uuid.uuid4(), role=role, content=content)


def _u(content: str) -> ChatMessage:
    return _msg(ChatMessageRole.USER, content)


def _a(content: str) -> ChatMessage:
    return _msg(ChatMessageRole.ASSISTANT, content)


def _character(
    history: list[ChatMessage], *, user_message: str = "지금", sections: list[PromptSection] = _SECTIONS
) -> str:
    return build_generation_prompt(
        prompt_set=_PROMPT_SET,
        sections=sections,
        character_prompt="설정",
        example_dialogues=[],
        history=history,
        user_message=user_message,
        user_persona="",
        memory_note="",
        memory_summary="",
        names=_NO_NAMES,
    )


def _story(history: list[ChatMessage], *, user_message: str, summary: str = "", keywords: list[str] | None = None) -> str:
    return build_story_generation_prompt(
        prompt_set=_PROMPT_SET,
        sections=_SECTIONS,
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="설정",
        development_examples=[],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="",
        history=history,
        user_message=user_message,
        user_persona="",
        memory_note="",
        memory_summary=summary,
        names=_NO_NAMES,
        keyword_note_texts=keywords,
    )


def _segments(prompt: str) -> tuple[str, ...]:
    assert isinstance(prompt, SegmentedPrompt)
    assert "".join(prompt.segments) == prompt
    return prompt.segments


def test_blocks_split_before_the_line_break_of_the_latest_exchange_and_after_the_history() -> None:
    """히스토리 줄 사이의 줄바꿈은 뒤 블록 앞에 붙는다 — 앞 블록 끝에 붙이면 N 턴의 둘째 블록만 줄바꿈 없이 끝나
    N+1 턴의 누적 앞부분과 어긋난다."""
    prompt = _character([_a("오프닝"), _u("u1"), _a("a1")])

    assert _segments(prompt) == (
        "[설정]\n설정\n\n[대화 기록]\n너: 오프닝",
        "\n나: u1\n너: a1",
        "\n\n나: 지금\n너:",
    )


def test_the_next_turn_first_block_is_this_turn_first_two_blocks_even_when_later_sections_change() -> None:
    turn_n = _story([_a("오프닝"), _u("u1"), _a("a1")], user_message="u2", keywords=["열쇠"])
    turn_n1 = _story([_a("오프닝"), _u("u1"), _a("a1"), _u("u2"), _a("a2")], user_message="u3", keywords=["편지"])

    first, second, _ = _segments(turn_n)
    assert _segments(turn_n1)[0] == first + second


@pytest.mark.parametrize(
    ("history", "expected_first", "expected_second"),
    [
        pytest.param([_u("u1"), _a("a1")], "[설정]\n설정\n\n[대화 기록]\n", "나: u1\n너: a1", id="exchange-opens-history"),
        pytest.param(
            [_a("오프닝1"), _a("오프닝2")],
            "[설정]\n설정\n\n[대화 기록]\n너: 오프닝1",
            "\n너: 오프닝2",
            id="no-user-line",
        ),
        pytest.param(
            [_a("오프닝"), _u("u1"), _a("a1"), _u("u2")],
            "[설정]\n설정\n\n[대화 기록]\n너: 오프닝\n나: u1\n너: a1",
            "\n나: u2",
            id="history-ends-on-a-user-line",
        ),
    ],
)
def test_the_second_block_starts_at_the_last_user_line_or_holds_the_last_line(
    history: list[ChatMessage], expected_first: str, expected_second: str
) -> None:
    first, second, _ = _segments(_character(history))

    assert (first, second) == (expected_first, expected_second)


def test_the_first_turn_after_a_history_opened_by_an_exchange_extends_its_cached_prefix() -> None:
    first, second, _ = _segments(_character([_u("u1"), _a("a1")]))

    assert _segments(_character([_u("u1"), _a("a1"), _u("u2"), _a("a2")]))[0] == first + second


def test_a_memory_fold_breaks_the_cached_prefix() -> None:
    """요약이 바뀌고 오래된 줄이 빠지는 턴은 앞 턴이 쓴 캐시를 읽을 수 없다 — 경계가 그 사실을 감추지 않아야 원가 어림이
    맞는다."""
    turn_n = _story([_u("u1"), _a("a1"), _u("u2"), _a("a2")], user_message="u3")
    turn_n1 = _story([_u("u2"), _a("a2"), _u("u3"), _a("a3")], user_message="u4", summary="u1 을 했다")

    first, second, _ = _segments(turn_n)
    assert not turn_n1.startswith(first + second)


def test_an_empty_history_is_a_plain_string_without_the_history_section() -> None:
    prompt = _character([])

    assert type(prompt) is str
    assert prompt == "[설정]\n설정\n\n나: 지금\n너:"


@pytest.mark.parametrize(
    ("user_message", "sections", "expected"),
    [
        pytest.param(
            "널\x00문자",
            _SECTIONS,
            "[설정]\n설정\n\n[대화 기록]\n나: u1\n너: a1\n\n나: 널\x00문자\n너:",
            id="marker-char-in-input",
        ),
        pytest.param(
            "지금",
            [_section("echo", "[다시]\n{history_lines}", order=0), *_SECTIONS],
            "[다시]\n나: u1\n너: a1\n\n[설정]\n설정\n\n[대화 기록]\n나: u1\n너: a1\n\n나: 지금\n너:",
            id="history-rendered-twice",
        ),
        pytest.param(
            "널\x00",
            [_section("history", "[대화 기록]\n{history_lines:.4}", order=3), _SECTIONS[0], _SECTIONS[-1]],
            "[설정]\n설정\n\n[대화 기록]\n나: u\n\n나: 널\x00\n너:",
            id="format-spec-cuts-a-marker",
        ),
        pytest.param(
            "지금",
            [_section("history", "{history_lines}", order=1), _SECTIONS[-1]],
            "나: u1\n너: a1\n\n나: 지금\n너:",
            id="empty-first-block",
        ),
    ],
)
def test_an_unsplittable_render_falls_back_to_the_plain_string(
    user_message: str, sections: list[PromptSection], expected: str
) -> None:
    """폴백은 표지 없이 렌더한 문자열 그대로여야 한다 — 바뀌면 Gemini 로 가는 프롬프트가 바뀐다."""
    prompt = _character([_u("u1"), _a("a1")], user_message=user_message, sections=sections)

    assert type(prompt) is str
    assert prompt == expected
