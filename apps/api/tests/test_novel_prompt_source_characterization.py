"""소설 프롬프트 빌더 일곱 개의 렌더 결과 기대값 — 라벨·등급 규칙을 어디서 읽든 같은 글이 나가야 한다.

기대값 파일(`fixtures/novel_prompt_source_characterization.json`)은 라벨·등급 규칙을 소설 원작 종류의 채팅 Gemini 활성 세트에서
읽던 코드로 만든다. 케이스는 빌더 7 × 원작 2(스토리·캐릭터) × 소설 체인 3(gemini·sonnet·opus) = 42 이고, 케이스마다 지시문과
본문의 sha256 만 적는다(문안 원문은 적지 않는다). 렌더 입력은 이 파일의 `_INPUTS` 가 유일한 정의처다.

그때 코드에서 경계 제안·문단 수정·여러 문단 수정·묶음 재검사는 고른 모델과 무관하게 늘 소설 Gemini 체인 세트로 렌더했으므로,
sonnet·opus 체인의 그 네 빌더 기대값은 Gemini 체인 렌더다.

기대값 만들기: 라벨·등급 규칙을 옮기기 전 코드에서 `NOVEL_PROMPT_SOURCE_GOLDEN_WRITE=1` 을 켜고 이 파일을 돌리면 파일을 새로
쓴다. 옮긴 뒤 코드로 만들면 대조가 항진명제가 되므로, 기대값이 다르면 파일을 고치지 말고 멈춘다.
"""

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.novelize.prompts import (
    NovelizePrompt,
    build_novelize_boundary_prompt,
    build_novelize_chapter_prompt,
    build_novelize_episode_outline_prompt,
    build_novelize_outline_prompt,
    build_novelize_revise_blocks_prompt,
    build_novelize_revise_prompt,
    build_novelize_revise_recheck_prompt,
)

FIXTURE = Path(__file__).parent / "fixtures" / "novel_prompt_source_characterization.json"
_WRITE_SWITCH = "NOVEL_PROMPT_SOURCE_GOLDEN_WRITE"

SCOPES: tuple[str, ...] = ("story", "character")
MODELS: tuple[str, ...] = ("gemini", "sonnet", "opus")
BUILDERS: tuple[str, ...] = (
    "boundary",
    "chapter",
    "outline",
    "episode_outline",
    "revise",
    "revise_blocks",
    "revise_recheck",
)
# 그때 코드에서 고른 모델의 체인 세트로 렌더한 빌더 — 나머지는 늘 Gemini 체인이었다.
CHAIN_BUILDERS: frozenset[str] = frozenset({"chapter", "outline", "episode_outline"})

_TURN_LINES = "[턴 1] {assistant}: 비가 오네.\n[턴 2] {user}: 우산 같이 쓸래?\n[턴 2] {assistant}: 고마워."
_INPUTS: dict[str, dict[str, Any]] = {
    "boundary": {"max_turns": 2, "user_name": "하늘"},
    "chapter": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "user_name": "하늘",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "previous_excerpt": "문이 닫히고 빗소리만 남았다.",
        "character_notes": "세빈: 말수가 적다.",
        "previous_summaries": "1화: 두 사람이 정류장에서 처음 만났다.",
        "episode_count": 2,
        "episode_chars": 3000,
        "novel_title_rule": "이번에는 소설 제목도 쓴다.",
        "scene_plan": "1. 정류장에서 다시 만난다.",
        "context_lines": "[턴 1] {assistant}: 지난번 일은 잊어.",
    },
    "outline": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "user_name": "하늘",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "max_episodes": 4,
        "episode_hint": 2,
        "character_notes": "세빈: 말수가 적다.",
        "previous_summaries": "1화: 두 사람이 정류장에서 처음 만났다.",
        "context_lines": "[턴 1] {assistant}: 지난번 일은 잊어.",
    },
    "episode_outline": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "user_name": "하늘",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "episode_outline": "2화 정류장: 두 사람이 비 오는 정류장에서 다시 만난다.",
        "character_notes": "세빈: 말수가 적다.",
        "previous_summaries": "1화: 두 사람이 정류장에서 처음 만났다.",
        "context_lines": "[턴 1] {assistant}: 지난번 일은 잊어.",
    },
    "revise": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "paragraphs": ["비가 왔다.", "세빈이 우산을 폈다.", "둘은 말없이 걸었다."],
        "first_index": 1,
        "last_index": 1,
        "user_request": "더 쓸쓸하게",
    },
    "revise_blocks": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "paragraph_lines": "[1] 비가 왔다.\n\n[2] 세빈이 우산을 폈다.\n\n[3] 둘은 말없이 걸었다.",
        "target_labels": [1, 3],
        "user_request": "더 쓸쓸하게",
    },
    "revise_recheck": {
        "edited_lines": "[2] 세빈이 낡은 우산을 폈다.",
        "patch_lines": "[3] 둘은 낡은 우산 아래에서 말없이 걸었다.",
        "paragraph_lines": "[1] 비가 왔다.",
    },
}


def case_key(builder: str, scope: str, model: str) -> str:
    return f"{builder}/{scope}/{model}"


def all_cases() -> list[tuple[str, str, str]]:
    return [(builder, scope, model) for builder in BUILDERS for scope in SCOPES for model in MODELS]


def _turn_lines(text: str, *, user: str, assistant: str) -> str:
    return text.format(user=user, assistant=assistant)


def digest(prompt: NovelizePrompt) -> dict[str, str]:
    return {
        "system": hashlib.sha256(prompt.system_instruction.encode()).hexdigest(),
        "prompt": hashlib.sha256(prompt.prompt.encode()).hexdigest(),
    }


def _render_with(
    builder: str,
    *,
    is_story: bool,
    sections: list[PromptSection],
    label_kwargs: Callable[[], dict[str, Any]],
    rating_kwargs: Callable[[], dict[str, Any]],
    user_label: str,
    assistant_label: str,
) -> NovelizePrompt:
    values = dict(_INPUTS[builder])
    lines = _turn_lines(_TURN_LINES, user=user_label, assistant=assistant_label)
    if "context_lines" in values:
        values["context_lines"] = _turn_lines(values["context_lines"], user=user_label, assistant=assistant_label)
    common: dict[str, Any] = {"sections": sections, "is_story_chat": is_story}
    if builder == "boundary":
        return build_novelize_boundary_prompt(**common, **label_kwargs(), turn_lines=lines, **values)
    if builder == "chapter":
        return build_novelize_chapter_prompt(**common, **label_kwargs(), **rating_kwargs(), turn_lines=lines, **values)
    if builder == "outline":
        return build_novelize_outline_prompt(**common, **label_kwargs(), **rating_kwargs(), turn_lines=lines, **values)
    if builder == "episode_outline":
        return build_novelize_episode_outline_prompt(
            **common, **label_kwargs(), **rating_kwargs(), turn_lines=lines, **values
        )
    if builder == "revise":
        return build_novelize_revise_prompt(**common, **rating_kwargs(), **values)
    if builder == "revise_blocks":
        return build_novelize_revise_blocks_prompt(**common, **rating_kwargs(), **values)
    return build_novelize_revise_recheck_prompt(**common, **values)


async def render_old_path(db: AsyncSession, builder: str, scope: str, model: str) -> NovelizePrompt:
    """라벨·등급 규칙을 원작 종류의 채팅 Gemini 활성 세트에서 빌리던 경로 — 기대값을 쓸 때만 쓴다."""
    chain = model if builder in CHAIN_BUILDERS else "gemini"
    _novel_set, sections = await load_active_prompt_set(db, lane="novel", model=chain)  # type: ignore[arg-type]
    chat_set, chat_sections = await load_active_prompt_set(db, lane=scope)  # type: ignore[arg-type]
    is_story = scope == "story"
    assistant = chat_set.story_assistant_label if is_story else chat_set.character_assistant_label
    return _render_with(
        builder,
        is_story=is_story,
        sections=sections,
        label_kwargs=lambda: {"chat_set": chat_set},
        rating_kwargs=lambda: {"chat_sections": chat_sections},
        user_label=chat_set.user_label,
        assistant_label=assistant,
    )


def _labels_of(prompt_set: PromptSet, *, is_story: bool) -> tuple[str, str]:
    return prompt_set.user_label, (
        prompt_set.story_assistant_label if is_story else prompt_set.character_assistant_label
    )


@pytest.mark.skipif(not os.environ.get(_WRITE_SWITCH), reason=f"{_WRITE_SWITCH}=1 일 때만 기대값 파일을 쓴다")
async def test_write_expected_digests(db_session: AsyncSession) -> None:
    expected = {
        case_key(builder, scope, model): digest(await render_old_path(db_session, builder, scope, model))
        for builder, scope, model in all_cases()
    }
    assert len(expected) == 42
    FIXTURE.write_text(json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
