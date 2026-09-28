"""기억 값(노트·요약)이 있으면 `build_*`가 그 값을 **렌더 결과에 글자로** 싣고, 자리는 생성
프롬프트에서 `user_persona → memory_note → memory_summary → history`, 엔딩 판정에서
`memory_summary → history_header`다. 요약 호출 프롬프트는 지시문 → 직전 요약 → 접을 대화 순이다.

`test_memory_prompt_slot_migration.py`는 DB의 섹션 배치(`order`)를 봤다. 여기는 빌더가 인자를 실제로
`values`에 넣는지를 본다 — 인자를 받고도 `values`에 안 넣으면 conditional 드롭으로 조용히 사라지고,
배치 테스트는 그걸 모른다. 세트는 `_migrated_schema`가 심은 활성 세트를 `load_active_prompt_set`으로
읽고, 기대 텍스트는 같은 세트의 body를 `format_map`해서 만든다 — 문안을 테스트에 복제하지 않는다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_memory_summary_prompt,
    build_story_generation_prompt,
    load_active_prompt_set,
)
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection
from api.db.models.story import StoryPromptTemplate

_PERSONA = "이름: 하늘"
_NOTE = "여동생 이름은 서연이다."
_SUMMARY = "두 사람은 편의점에서 처음 만났다."


def _body(sections: list[PromptSection], channel: str, slot: str) -> str:
    return next(s.body for s in sections if s.channel == channel and s.slot == slot)


def _history() -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatMessageRole.USER, content="이전 메시지"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="이전 응답"),
    ]


def _generation_run(sections: list[PromptSection], values: dict[str, str]) -> str:
    return "\n\n".join(
        _body(sections, "generation", slot).format_map(values)
        for slot in ("user_persona", "memory_note", "memory_summary", "history")
    )


async def test_story_generation_puts_note_then_summary_between_persona_and_history(db_session: AsyncSession) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")

    prompt = build_story_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관",
        development_examples=[],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="시작 상황",
        history=_history(),
        user_message="이번 메시지",
        user_persona=_PERSONA,
        memory_note=_NOTE,
        memory_summary=_SUMMARY,
    )

    history_lines = f"{prompt_set.user_label}: 이전 메시지\n{prompt_set.story_assistant_label}: 이전 응답"
    values = {"user_persona": _PERSONA, "memory_note": _NOTE, "memory_summary": _SUMMARY, "history_lines": history_lines}
    assert _generation_run(sections, values) in prompt
    assert (prompt.count(_NOTE), prompt.count(_SUMMARY)) == (1, 1)


async def test_character_generation_puts_note_then_summary_between_persona_and_history(
    db_session: AsyncSession,
) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")

    prompt = build_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        character_prompt="캐릭터 프롬프트",
        example_dialogues=[],
        history=_history(),
        user_message="이번 메시지",
        user_persona=_PERSONA,
        memory_note=_NOTE,
        memory_summary=_SUMMARY,
    )

    history_lines = f"{prompt_set.user_label}: 이전 메시지\n{prompt_set.character_assistant_label}: 이전 응답"
    values = {"user_persona": _PERSONA, "memory_note": _NOTE, "memory_summary": _SUMMARY, "history_lines": history_lines}
    assert _generation_run(sections, values) in prompt
    assert (prompt.count(_NOTE), prompt.count(_SUMMARY)) == (1, 1)


async def test_ending_judgment_puts_summary_right_before_history_header(db_session: AsyncSession) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")

    prompt = build_ending_judgment_prompt(
        prompt_set=prompt_set,
        sections=sections,
        judgment_prompt="기준",
        history=[],
        user_message="이번 메시지",
        assistant_message="이번 응답",
        memory_summary=_SUMMARY,
    )

    expected_start = "\n\n".join(
        [
            _body(sections, "ending_judgment", "memory_summary").format_map({"memory_summary": _SUMMARY}),
            _body(sections, "ending_judgment", "history_header"),
        ]
    )
    assert prompt.startswith(expected_start)
    assert prompt.count(_SUMMARY) == 1


async def test_memory_summary_prompt_with_previous_summary_is_instruction_previous_then_turns(
    db_session: AsyncSession,
) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")

    prompt = build_memory_summary_prompt(
        prompt_set=prompt_set, sections=sections, is_story_chat=True, previous_summary=_SUMMARY, turns=_history()
    )

    turn_lines = f"{prompt_set.user_label}: 이전 메시지\n{prompt_set.story_assistant_label}: 이전 응답"
    assert prompt == "\n\n".join(
        [
            _body(sections, "memory_summary", "instruction"),
            _body(sections, "memory_summary", "previous_summary").format_map({"previous_summary": _SUMMARY}),
            _body(sections, "memory_summary", "turn_context").format_map({"turn_lines": turn_lines}),
        ]
    )


async def test_first_memory_summary_prompt_drops_previous_summary_and_uses_character_label(
    db_session: AsyncSession,
) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")

    prompt = build_memory_summary_prompt(
        prompt_set=prompt_set, sections=sections, is_story_chat=False, previous_summary="", turns=_history()
    )

    turn_lines = f"{prompt_set.user_label}: 이전 메시지\n{prompt_set.character_assistant_label}: 이전 응답"
    assert prompt == "\n\n".join(
        [
            _body(sections, "memory_summary", "instruction"),
            _body(sections, "memory_summary", "turn_context").format_map({"turn_lines": turn_lines}),
        ]
    )
