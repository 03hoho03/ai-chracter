"""소설 구성 흐름의 프롬프트 빌더 — 전체 구성안·화 하나의 장면 구성안, 그리고 화 생성의 새 두 슬롯(장면 계획·연속성 참고).

지시문만 system_instruction 으로, 나머지는 본문으로 보낸다(지시문 뒤에 채팅 세트의 등급 규칙). conditional 슬롯은 값이 비면 섹션째
빠진다 — 옛 흐름의 화 생성은 새 두 슬롯 값을 넘기지 않아 렌더가 그대로다. 섹션은 세션 없이 생성자로만 채운다(DB 를 타지 않는
순수 함수)."""

from typing import Any

import pytest

from api.chat.prompt_builder import PromptRenderError
from api.db.models.prompt import PromptSection, PromptSet
from api.novelize.prompts import (
    NovelizePrompt,
    build_novelize_chapter_prompt,
    build_novelize_episode_outline_prompt,
    build_novelize_outline_prompt,
)

_CHAT_SET = PromptSet(
    user_label="사용자", story_assistant_label="진행자", story_example_label="서술자", character_assistant_label="캐릭터"
)


def _section(channel: str, slot: str, body: str, order: int, *, conditional: bool = False) -> PromptSection:
    return PromptSection(
        channel=channel, scope="both", slot=slot, variant="", body=body, conditional=conditional, order=order
    )


_RULE_ROWS = [_section("system", "rule_rating", "[수위]\n등급 규칙", 3)]


def _plan_rows(channel: str, instruction: str, middle: list[PromptSection]) -> list[PromptSection]:
    return [
        _section(channel, "instruction", instruction, 0),
        _section(channel, "work_setting", "설정:\n{work_setting}", 1),
        _section(channel, "user_name", "이름: {user_name}", 2),
        _section(channel, "setting_notes", "노트:\n{setting_notes}", 3, conditional=True),
        _section(channel, "character_notes", "인물:\n{character_notes}", 4, conditional=True),
        _section(channel, "previous_summaries", "지난:\n{previous_summaries}", 5, conditional=True),
        *middle,
        _section(channel, "turn_context", "'{user_label}'/'{assistant_label}'\n{turn_lines}", 8),
    ]


_OUTLINE_ROWS = _plan_rows(
    "novelize_outline",
    "구성 지시",
    [
        _section("novelize_outline", "continuity_context", "참고:\n{context_lines}", 6, conditional=True),
        _section("novelize_outline", "outline_plan", "범위 {max_episodes} 안내 {episode_hint}", 7),
    ],
)
_EPISODE_ROWS = _plan_rows(
    "novelize_episode_outline",
    "장면 지시",
    [
        _section("novelize_episode_outline", "episode_outline", "이번 화:\n{episode_outline}", 6),
        _section("novelize_episode_outline", "continuity_context", "참고:\n{context_lines}", 7, conditional=True),
    ],
)
_CHAPTER_ROWS = [
    _section("novelize_chapter", "instruction", "장 지시", 0),
    _section("novelize_chapter", "work_setting", "설정:\n{work_setting}", 1),
    _section("novelize_chapter", "user_name", "이름: {user_name}", 2),
    _section("novelize_chapter", "episode_plan", "{episode_count}화 {episode_chars}자\n{novel_title_rule}", 3),
    _section("novelize_chapter", "turn_context", "'{user_label}'/'{assistant_label}'\n{turn_lines}", 4),
    _section("novelize_chapter", "scene_plan", "계획:\n{scene_plan}", 5, conditional=True),
    _section("novelize_chapter", "continuity_context", "참고:\n{context_lines}", 6, conditional=True),
]
_ALL_ROWS = [*_OUTLINE_ROWS, *_EPISODE_ROWS, *_CHAPTER_ROWS]
_TURN_LINES = "[턴 1] 캐릭터: 왔어?\n[턴 2] 사용자: 응.\n[턴 2] 캐릭터: 앉아."


def _outline(sections: list[PromptSection] = _ALL_ROWS, **overrides: Any) -> NovelizePrompt:
    kwargs: dict[str, Any] = {
        "chat_set": _CHAT_SET,
        "chat_sections": _RULE_ROWS,
        "sections": sections,
        "is_story_chat": True,
        "work_setting": "작품 설정 원문",
        "user_name": "서진",
        "setting_notes": "",
        "turn_lines": _TURN_LINES,
        "max_episodes": 8,
        "episode_hint": 3,
        **overrides,
    }
    return build_novelize_outline_prompt(**kwargs)


def _episode(sections: list[PromptSection] = _ALL_ROWS, **overrides: Any) -> NovelizePrompt:
    kwargs: dict[str, Any] = {
        "chat_set": _CHAT_SET,
        "chat_sections": _RULE_ROWS,
        "sections": sections,
        "is_story_chat": False,
        "work_setting": "작품 설정 원문",
        "user_name": "서진",
        "setting_notes": "",
        "episode_outline": "3화 · 빗속의 약속 — 두 사람이 다시 만난다.",
        "turn_lines": _TURN_LINES,
        **overrides,
    }
    return build_novelize_episode_outline_prompt(**kwargs)


def _chapter(**overrides: Any) -> NovelizePrompt:
    kwargs: dict[str, Any] = {
        "chat_set": _CHAT_SET,
        "chat_sections": _RULE_ROWS,
        "sections": _ALL_ROWS,
        "is_story_chat": True,
        "work_setting": "작품 설정 원문",
        "user_name": "서진",
        "setting_notes": "",
        "previous_excerpt": "",
        "turn_lines": _TURN_LINES,
        "episode_chars": 5000,
        **overrides,
    }
    return build_novelize_chapter_prompt(**kwargs)


def test_the_outline_prompt_sends_its_instruction_with_the_rating_rule_and_drops_empty_optional_sections() -> None:
    """전체 구성안은 지시문 + 등급 규칙을 system 으로, 나머지를 본문으로 보내고 빈 conditional 섹션(노트·인물·지난 화·연속성
    참고)은 빠진다. 값을 주면 그 차례에 들어간다. 깨지는 시나리오: 화 수 범위가 빠져 모델이 화 수를 마음대로 정하거나, 맥락
    구간이 원문과 같은 머리글로 섞여 소설 사건이 된다."""
    bare = _outline()
    assert bare.system_instruction == "구성 지시\n\n[수위]\n등급 규칙"
    assert bare.prompt == f"설정:\n작품 설정 원문\n\n이름: 서진\n\n범위 8 안내 3\n\n'사용자'/'진행자'\n{_TURN_LINES}"

    full = _outline(
        setting_notes="스물셋",
        character_notes="도윤: 소꿉친구",
        previous_summaries="1화: 만났다.",
        context_lines="[턴 9] 캐릭터: 참고 대사",
        is_story_chat=False,
    )
    assert full.prompt == (
        "설정:\n작품 설정 원문\n\n이름: 서진\n\n노트:\n스물셋\n\n인물:\n도윤: 소꿉친구\n\n지난:\n1화: 만났다.\n\n"
        f"참고:\n[턴 9] 캐릭터: 참고 대사\n\n범위 8 안내 3\n\n'사용자'/'캐릭터'\n{_TURN_LINES}"
    )


def test_the_episode_outline_prompt_carries_the_episodes_plan_before_the_source() -> None:
    """장면 구성안은 이번 화 구성(전체 구성안의 그 화)을 원문 앞에 싣는다. 깨지는 시나리오: 이번 화 구성이 빠져 모델이 원문
    구간 전체를 다른 화의 줄거리로 짠다."""
    built = _episode(context_lines="[턴 9] 캐릭터: 참고")

    assert built.system_instruction == "장면 지시\n\n[수위]\n등급 규칙"
    assert built.prompt == (
        "설정:\n작품 설정 원문\n\n이름: 서진\n\n이번 화:\n3화 · 빗속의 약속 — 두 사람이 다시 만난다.\n\n"
        f"참고:\n[턴 9] 캐릭터: 참고\n\n'사용자'/'캐릭터'\n{_TURN_LINES}"
    )


def test_the_chapter_prompt_renders_the_new_slots_only_when_given() -> None:
    """옛 흐름은 장면 계획·연속성 참고 값을 넘기지 않아 두 섹션째 빠진다 — 옛 흐름 렌더가 바이트 그대로다. 구성 흐름 원고는
    둘을 싣는다. 깨지는 시나리오: 새 슬롯이 conditional 이 아니거나 빈 값에서 렌더되어 옛 흐름 화에 빈 머리글이 붙는다."""
    old = _chapter()
    new = _chapter(scene_plan="1. 비 오는 정류장", context_lines="[턴 9] 캐릭터: 참고")

    assert old.prompt == f"설정:\n작품 설정 원문\n\n이름: 서진\n\n1화 5000자\n\n\n'사용자'/'진행자'\n{_TURN_LINES}"
    assert new.prompt == old.prompt + "\n\n계획:\n1. 비 오는 정류장\n\n참고:\n[턴 9] 캐릭터: 참고"


@pytest.mark.parametrize(
    ("build", "channel"),
    [pytest.param(_outline, "novelize_outline", id="outline"), pytest.param(_episode, "novelize_episode_outline", id="episode")],
)
def test_a_set_without_the_outline_channel_raises_instead_of_rendering_empty(build: Any, channel: str) -> None:
    """구성안 채널 행이 없는 세트(이 문안을 심기 전의 세트)로는 렌더하지 않는다 — 빈 프롬프트로 과금 호출이 나가지 않게."""
    with pytest.raises(PromptRenderError, match=channel):
        build(sections=_CHAPTER_ROWS)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"turn_lines": " "}, id="no-source"),
        pytest.param({"user_name": ""}, id="no-name"),
    ],
)
def test_missing_material_raises_before_a_paid_outline_call(overrides: dict[str, Any]) -> None:
    """원문이나 주인공 이름이 비면 호출 전에 거절한다 — 호출부가 차감 전 거절이나 환불로 처리한다."""
    with pytest.raises(PromptRenderError):
        _outline(**overrides)
    with pytest.raises(PromptRenderError):
        _episode(**overrides)


def test_the_episode_outline_needs_its_plan() -> None:
    with pytest.raises(PromptRenderError, match="episode_outline"):
        _episode(episode_outline=" ")


@pytest.mark.parametrize(("max_episodes", "hint"), [(0, 1), (3, 0), (3, 4)])
def test_the_outline_refuses_an_episode_range_that_cannot_hold_its_hint(max_episodes: int, hint: int) -> None:
    """화 수 범위는 1 이상 상한 이하이고 안내값도 그 안이다 — 어긋난 값으로 "0화 이하로 나눈다" 같은 지시가 나가지 않게."""
    with pytest.raises(PromptRenderError, match="novelize_outline"):
        _outline(max_episodes=max_episodes, episode_hint=hint)
