"""소설화 프롬프트 빌더 세 개 — 지시문(system_instruction)과 본문을 나눠 렌더하고, 빈 프롬프트로 과금 호출이 나가지
않게 막는 분기. 소설 문안(소설 레인 세트)과 라벨·등급 규칙(채팅 세트)을 따로 받는다. 섹션은 세션 없이 생성자로만
채운다(DB 를 타지 않는 순수 함수)."""

from collections.abc import Callable
from typing import Any

import pytest

from api.chat.prompt_builder import PromptRenderError
from api.core.config import settings
from api.db.models.prompt import PromptSection, PromptSet
from api.novelize.prompts import (
    NovelizePrompt,
    build_novelize_boundary_prompt,
    build_novelize_chapter_prompt,
    build_novelize_revise_prompt,
)

_CHAT_SET = PromptSet(
    user_label="사용자", story_assistant_label="진행자", story_example_label="서술자", character_assistant_label="캐릭터"
)


def _section(channel: str, slot: str, body: str, order: int, *, conditional: bool = False, scope: str = "both") -> PromptSection:
    return PromptSection(
        channel=channel, scope=scope, slot=slot, variant="", body=body, conditional=conditional, order=order
    )


_RULE_ROWS = [
    _section("system", "self_definition", "채팅용 자기 규정", 0, scope="story"),
    _section("system", "rule_rating", "[수위]\n등급 규칙", 3),
]
_BOUNDARY_ROWS = [
    _section("novelize_boundary", "instruction", "경계 지시", 0),
    _section("novelize_boundary", "user_name", "이름: {user_name}", 1, conditional=True),
    _section("novelize_boundary", "max_turns", "범위 {max_turns}", 2),
    _section("novelize_boundary", "turn_context", "'{user_label}'/'{assistant_label}'\n{turn_lines}", 3),
]
_CHAPTER_ROWS = [
    _section("novelize_chapter", "instruction", "장 지시", 0),
    _section("novelize_chapter", "work_setting", "설정:\n{work_setting}", 1),
    _section("novelize_chapter", "user_name", "이름: {user_name}", 2),
    _section("novelize_chapter", "setting_notes", "노트:\n{setting_notes}", 3, conditional=True),
    _section("novelize_chapter", "previous_excerpt", "앞 화:\n{previous_excerpt}", 4, conditional=True),
    _section("novelize_chapter", "episode_plan", "{episode_count}화 {episode_chars}자\n{novel_title_rule}", 5),
    _section("novelize_chapter", "turn_context", "'{user_label}'/'{assistant_label}'\n{turn_lines}", 6),
]
_REVISE_ROWS = [
    _section("novelize_revise", "instruction", "수정 지시", 0),
    _section("novelize_revise", "work_setting", "설정:\n{work_setting}", 1),
    _section("novelize_revise", "setting_notes", "노트:\n{setting_notes}", 2, conditional=True),
    _section("novelize_revise", "paragraphs", "본문:\n{paragraph_lines}", 3),
    _section("novelize_revise", "target_range", "{first_paragraph}~{last_paragraph}", 4),
    _section("novelize_revise", "user_request", "요청:\n{user_request}", 5),
]
# 소설 레인 세트 — 등급 규칙 행이 없다(채팅 세트 `_RULE_ROWS` 에서 읽는다).
_ALL_ROWS = [*_BOUNDARY_ROWS, *_CHAPTER_ROWS, *_REVISE_ROWS]
_TURN_LINES = "[턴 1] 캐릭터: 왔어?\n[턴 2] 사용자: 응.\n[턴 2] 캐릭터: 앉아."


def _boundary(sections: list[PromptSection] = _ALL_ROWS, **overrides: Any) -> NovelizePrompt:
    kwargs: dict[str, Any] = {
        "chat_set": _CHAT_SET,
        "sections": sections,
        "is_story_chat": False,
        "max_turns": 12,
        "user_name": "서진",
        "turn_lines": _TURN_LINES,
        **overrides,
    }
    return build_novelize_boundary_prompt(**kwargs)


def _chapter(sections: list[PromptSection] = _ALL_ROWS, **overrides: Any) -> NovelizePrompt:
    kwargs: dict[str, Any] = {
        "chat_set": _CHAT_SET,
        "chat_sections": _RULE_ROWS,
        "sections": sections,
        "is_story_chat": True,
        "work_setting": "작품 설정 원문",
        "user_name": "서진",
        "setting_notes": "",
        "previous_excerpt": "",
        "turn_lines": _TURN_LINES,
        **overrides,
    }
    return build_novelize_chapter_prompt(**kwargs)


def _revise(sections: list[PromptSection] = _ALL_ROWS, **overrides: Any) -> NovelizePrompt:
    kwargs: dict[str, Any] = {
        "chat_sections": _RULE_ROWS,
        "sections": sections,
        "is_story_chat": False,
        "work_setting": "작품 설정 원문",
        "setting_notes": "",
        "paragraphs": ["첫 문단", "둘째 문단", "셋째 문단"],
        "first_index": 1,
        "last_index": 2,
        "user_request": "더 긴장감 있게",
        **overrides,
    }
    return build_novelize_revise_prompt(**kwargs)


# ---- 렌더 모양 -------------------------------------------------------------------------------


def test_boundary_sends_only_the_instruction_as_system_and_labels_follow_the_room_kind() -> None:
    character = _boundary()
    assert character.system_instruction == "경계 지시"
    assert character.prompt == f"이름: 서진\n\n범위 12\n\n'사용자'/'캐릭터'\n{_TURN_LINES}"

    story = _boundary(is_story_chat=True, user_name="")
    # 이름이 아직 없으면(첫 장 이름 입력 전) 그 섹션째 빠지고, 스토리 방은 진행자 라벨이다.
    assert story.prompt == f"범위 12\n\n'사용자'/'진행자'\n{_TURN_LINES}"


def test_chapter_appends_the_chat_sets_rating_rule_to_the_instruction_and_drops_empty_optional_sections() -> None:
    bare = _chapter(episode_count=3, episode_chars=5000, novel_title_rule="제목도 쓴다.")
    assert bare.system_instruction == "장 지시\n\n[수위]\n등급 규칙"
    assert bare.prompt == (
        f"설정:\n작품 설정 원문\n\n이름: 서진\n\n3화 5000자\n제목도 쓴다.\n\n'사용자'/'진행자'\n{_TURN_LINES}"
    )

    full = _chapter(
        setting_notes="서진은 스물셋",
        previous_excerpt="앞 화 마지막 문단",
        novel_title_rule="제목은 쓰지 않는다.",
        is_story_chat=False,
    )
    assert full.prompt == (
        "설정:\n작품 설정 원문\n\n이름: 서진\n\n노트:\n서진은 스물셋\n\n앞 화:\n앞 화 마지막 문단\n\n"
        f"1화 {settings.novelize_episode_target_chars}자\n제목은 쓰지 않는다.\n\n'사용자'/'캐릭터'\n{_TURN_LINES}"
    )


def test_the_rating_rule_and_labels_come_from_the_chat_set_not_the_novel_set() -> None:
    """소설 레인 세트에 등급 규칙 행이 끼어 있어도 채팅 세트의 것을 붙인다 — 등급 규칙의 소스는 채팅 세트 하나다."""
    stray_rule = _section("system", "rule_rating", "소설 세트에 끼어든 수위", 3)
    chat_set = PromptSet(
        user_label="나", story_assistant_label="화자", story_example_label="예", character_assistant_label="그"
    )
    built = _chapter([stray_rule, *_CHAPTER_ROWS], chat_set=chat_set)
    assert built.system_instruction == "장 지시\n\n[수위]\n등급 규칙"
    assert "'나'/'화자'" in built.prompt


def test_revise_numbers_paragraphs_from_one_and_shifts_the_zero_based_range() -> None:
    built = _revise(setting_notes="말끝은 ~죠")
    assert built.system_instruction == "수정 지시\n\n[수위]\n등급 규칙"
    assert built.prompt == (
        "설정:\n작품 설정 원문\n\n노트:\n말끝은 ~죠\n\n본문:\n[1] 첫 문단\n\n[2] 둘째 문단\n\n[3] 셋째 문단\n\n"
        "2~3\n\n요청:\n더 긴장감 있게"
    )
    assert "2~2" in _revise(first_index=1, last_index=1).prompt


def test_rating_rule_is_picked_by_the_rooms_scope() -> None:
    """등급 규칙 행이 레인 안에서 scope 로 갈라져 있으면 방 종류의 행을 고른다(렌더러와 같은 선택 함수)."""
    split_rule = [
        _section("system", "rule_rating", "스토리 수위", 3, scope="story"),
        _section("system", "rule_rating", "캐릭터 수위", 3, scope="character"),
    ]
    assert _chapter(chat_sections=split_rule, is_story_chat=True).system_instruction.endswith("스토리 수위")
    assert _chapter(chat_sections=split_rule, is_story_chat=False).system_instruction.endswith("캐릭터 수위")


# ---- 빈 프롬프트로 과금 호출을 내지 않는다 ---------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [pytest.param(_boundary, id="boundary"), pytest.param(_chapter, id="chapter"), pytest.param(_revise, id="revise")],
)
def test_a_set_without_novelize_rows_raises_instead_of_rendering_empty(build: Callable[..., NovelizePrompt]) -> None:
    """소설화 채널 행이 없는 세트(다른 레인 세트를 잘못 넘긴 경우)로는 렌더러가 빈 문자열을 낸다."""
    with pytest.raises(PromptRenderError, match="novelize_"):
        build(_RULE_ROWS)


@pytest.mark.parametrize(
    ("build", "rows", "slot"),
    [
        pytest.param(_boundary, _BOUNDARY_ROWS, "turn_context", id="boundary-turn_context"),
        pytest.param(_chapter, _CHAPTER_ROWS, "instruction", id="chapter-instruction"),
        pytest.param(_chapter, _CHAPTER_ROWS, "episode_plan", id="chapter-episode_plan"),
        pytest.param(_revise, _REVISE_ROWS, "user_request", id="revise-user_request"),
    ],
)
def test_a_missing_required_slot_raises(
    build: Callable[..., NovelizePrompt], rows: list[PromptSection], slot: str
) -> None:
    with pytest.raises(PromptRenderError, match=slot):
        build([s for s in rows if s.slot != slot])


@pytest.mark.parametrize(
    "build", [pytest.param(_chapter, id="chapter"), pytest.param(_revise, id="revise")]
)
def test_chapter_and_revise_raise_without_a_rating_rule(build: Callable[..., NovelizePrompt]) -> None:
    without_rule = [s for s in _RULE_ROWS if s.slot != "rule_rating"]
    with pytest.raises(PromptRenderError, match="rule_rating"):
        build(chat_sections=without_rule)


def test_boundary_does_not_need_a_rating_rule() -> None:
    assert _boundary().system_instruction == "경계 지시"


@pytest.mark.parametrize(
    ("build", "overrides"),
    [
        pytest.param(_boundary, {"turn_lines": ""}, id="boundary-no-turns"),
        pytest.param(_boundary, {"max_turns": 0}, id="boundary-zero-range"),
        pytest.param(_chapter, {"turn_lines": " \n"}, id="chapter-no-turns"),
        pytest.param(_chapter, {"user_name": ""}, id="chapter-no-name"),
        pytest.param(_revise, {"paragraphs": []}, id="revise-no-paragraphs"),
        pytest.param(_revise, {"user_request": "  "}, id="revise-no-request"),
        pytest.param(_revise, {"first_index": 2, "last_index": 1}, id="revise-reversed-range"),
        pytest.param(_revise, {"first_index": -1, "last_index": 0}, id="revise-negative-start"),
        pytest.param(_revise, {"last_index": 3}, id="revise-range-past-end"),
    ],
)
def test_missing_material_raises_before_a_paid_call(
    build: Callable[..., NovelizePrompt], overrides: dict[str, Any]
) -> None:
    """옮길 원문·이름·고칠 문단·요청이 없으면 지시문만 실린 프롬프트로 과금 호출이 나간다 — 호출 전에 실패시킨다."""
    with pytest.raises(PromptRenderError):
        build(**overrides)
