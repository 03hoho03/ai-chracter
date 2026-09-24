"""persona-goal-prompt.md §4 S4 ① (UP-18 (a)). 프로필 값이 있으면 `generation/user_persona`
섹션이 **렌더 결과**에서 story는 `prologue` 바로 뒤·`history` 바로 앞, character는
`example_dialogues` 바로 뒤·`history` 바로 앞에 온다.

S3 ③은 M2 뒤 DB의 섹션 배치(`order`)를 봤다. 여기는 `build_*`가 값을 실제로 `values`에
넣어 그 자리에 **글자로** 나오는지를 본다 — 인자를 받고도 `values`에 안 넣으면 conditional
드롭(F1)으로 조용히 사라지고, 배치 테스트는 그걸 모른다. 세트는 `_migrated_schema`가 심은
활성 세트를 `load_active_prompt_set`으로 읽는다(프로덕션이 고르는 규칙과 같다). 이웃 섹션의
기대 텍스트는 같은 세트의 body를 `format_map`해서 만든다 — 문안을 테스트에 복제하지 않는다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    build_generation_prompt,
    build_story_generation_prompt,
    load_active_prompt_set,
)
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection
from api.db.models.story import StoryPromptTemplate

_PERSONA = "이름: 하늘\n성별: 여성\n설명: 밤하늘을 좋아한다"


def _generation_body(sections: list[PromptSection], slot: str) -> str:
    return next(s.body for s in sections if s.channel == "generation" and s.slot == slot)


def _history() -> list[ChatMessage]:
    return [ChatMessage(role=ChatMessageRole.USER, content="이전 메시지")]


async def test_story_persona_section_sits_right_after_prologue_and_right_before_history(
    db_session: AsyncSession,
) -> None:
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
        prologue="시작 상황 문장",
        history=_history(),
        user_message="이번 메시지",
        user_persona=_PERSONA,
    )

    values = {
        "prologue": "시작 상황 문장",
        "user_persona": _PERSONA,
        "history_lines": f"{prompt_set.user_label}: 이전 메시지",
    }
    expected_run = "\n\n".join(
        _generation_body(sections, slot).format_map(values) for slot in ("prologue", "user_persona", "history")
    )
    assert expected_run in prompt
    assert prompt.count(_PERSONA) == 1


async def test_character_persona_section_sits_right_after_examples_and_right_before_history(
    db_session: AsyncSession,
) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")

    prompt = build_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        character_prompt="캐릭터 프롬프트",
        example_dialogues=[{"userLine": "안녕", "characterLine": "응"}],
        history=_history(),
        user_message="이번 메시지",
        user_persona=_PERSONA,
    )

    values = {
        "example_lines": f"{prompt_set.user_label}: 안녕\n{prompt_set.character_assistant_label}: 응",
        "user_persona": _PERSONA,
        "history_lines": f"{prompt_set.user_label}: 이전 메시지",
    }
    expected_run = "\n\n".join(
        _generation_body(sections, slot).format_map(values)
        for slot in ("example_dialogues", "user_persona", "history")
    )
    assert expected_run in prompt
    assert prompt.count(_PERSONA) == 1
