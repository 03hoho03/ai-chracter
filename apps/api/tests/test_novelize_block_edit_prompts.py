"""여러 문단 수정의 프롬프트 빌더 두 개(수정·재검사)와 어드민 표·미리보기. 문안은 지금 활성 세트(시드)에서 읽는다."""

from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import (
    _CLAUDE_SET_CHANNELS_BY_LANE,
    _EXPECTED_ROWS_BY_LANE,
    _FROZEN_NOVELIZE_ROWS,
    _novel_preview_items,
)
from api.chat.prompt_builder import PromptRenderError, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.novelize.prompts import build_novelize_revise_blocks_prompt, build_novelize_revise_recheck_prompt

_NEW_CHANNELS = {"novelize_revise_blocks", "novelize_revise_recheck"}


async def _novel_sections(db: AsyncSession) -> list[PromptSection]:
    return (await load_active_prompt_set(db, lane="novel", model="gemini"))[1]


async def test_the_block_edit_prompt_carries_the_context_lines_the_target_numbers_and_the_rating_rule(
    db_session: AsyncSession,
) -> None:
    """지시문(뒤에 채팅 세트 등급 규칙) 은 따로, 본문에는 작품 설정·설정 노트·번호 붙은 문맥 문단·고칠 문단 번호·요청이 실린다.
    설정 노트가 비면 그 섹션이 빠진다."""
    sections = await _novel_sections(db_session)
    _chat_set, chat_sections = await load_active_prompt_set(db_session, lane="story", model="gemini")

    built = build_novelize_revise_blocks_prompt(
        chat_sections=chat_sections,
        sections=sections,
        is_story_chat=True,
        work_setting="작품 설정 글",
        setting_notes="노트 글",
        paragraph_lines="[2] 둘째.\n\n[3] 셋째.\n\n[5] 다섯째.",
        target_labels=[2, 5],
        user_request="더 쓸쓸하게",
    )
    without_notes = build_novelize_revise_blocks_prompt(
        chat_sections=chat_sections,
        sections=sections,
        is_story_chat=True,
        work_setting="작품 설정 글",
        setting_notes="",
        paragraph_lines="[2] 둘째.",
        target_labels=[2],
        user_request="더 쓸쓸하게",
    )

    assert "[수위]" in built.system_instruction and "[고치는 규칙]" in built.system_instruction
    for piece in ("작품 설정 글", "노트 글", "[2] 둘째.", "[5] 다섯째.", "2번, 5번", "더 쓸쓸하게"):
        assert piece in built.prompt
    assert "[설정 노트]" in built.prompt and "[설정 노트]" not in without_notes.prompt


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        pytest.param({"user_request": "  "}, "user_request", id="blank-request"),
        pytest.param({"target_labels": []}, "target", id="no-targets"),
        pytest.param({"paragraph_lines": ""}, "paragraph_lines", id="no-context"),
    ],
)
async def test_the_block_edit_prompt_refuses_to_render_without_a_request_targets_or_context(
    db_session: AsyncSession, kwargs: dict[str, object], match: str
) -> None:
    sections = await _novel_sections(db_session)
    _chat_set, chat_sections = await load_active_prompt_set(db_session, lane="story", model="gemini")
    values: dict[str, object] = {
        "work_setting": "작품",
        "setting_notes": "",
        "paragraph_lines": "[1] 첫째.",
        "target_labels": [1],
        "user_request": "고쳐",
        **kwargs,
    }

    with pytest.raises(PromptRenderError, match=match):
        build_novelize_revise_blocks_prompt(
            chat_sections=chat_sections, sections=sections, is_story_chat=False, **values  # type: ignore[arg-type]
        )


async def test_the_block_edit_prompt_refuses_a_set_without_the_channel(db_session: AsyncSession) -> None:
    sections = [s for s in await _novel_sections(db_session) if s.channel != "novelize_revise_blocks"]
    _chat_set, chat_sections = await load_active_prompt_set(db_session, lane="story", model="gemini")

    with pytest.raises(PromptRenderError, match="필수 슬롯"):
        build_novelize_revise_blocks_prompt(
            chat_sections=chat_sections,
            sections=sections,
            is_story_chat=True,
            work_setting="작품",
            setting_notes="",
            paragraph_lines="[1] 첫째.",
            target_labels=[1],
            user_request="고쳐",
        )


async def test_the_recheck_prompt_carries_the_edited_text_and_the_pending_patches_and_drops_an_empty_context(
    db_session: AsyncSession,
) -> None:
    sections = await _novel_sections(db_session)

    built = build_novelize_revise_recheck_prompt(
        sections=sections,
        is_story_chat=False,
        edited_lines="[2] 사용자가 고친 둘째.",
        patch_lines="[4] 고친 넷째.",
        paragraph_lines="[3] 셋째.",
    )
    bare = build_novelize_revise_recheck_prompt(
        sections=sections, is_story_chat=False, edited_lines="[2] 고친 둘째.", patch_lines="[4] 고친 넷째."
    )

    assert built.system_instruction.strip()
    for piece in ("사용자가 고친 둘째.", "고친 넷째.", "[3] 셋째."):
        assert piece in built.prompt
    assert "[3] 셋째." not in bare.prompt
    with pytest.raises(PromptRenderError):
        build_novelize_revise_recheck_prompt(sections=sections, is_story_chat=False, edited_lines="", patch_lines="x")


# ── 어드민 표 ────────────────────────────────────────────────────────────────
def test_the_new_channels_live_only_in_the_gemini_novel_chain_and_leave_the_chat_lanes_frozen_rows_alone() -> None:
    """새 두 채널은 소설 레인 표에만 있고(Claude 체인 채널 집합에는 없다 — Gemini 고정), 채팅 레인이 얼려 둔 옛 소설 행 집합은
    그대로 세 채널이다. 깨지는 시나리오: 얼린 행 집합에 새 채널이 섞여 채팅 레인 게시가 "누락"으로 막히거나, Claude 체인에 새
    채널을 요구해 그 체인 게시가 막힌다."""
    assert _NEW_CHANNELS <= set(_EXPECTED_ROWS_BY_LANE["novel"])
    assert set(_FROZEN_NOVELIZE_ROWS) == {"novelize_boundary", "novelize_chapter", "novelize_revise"}
    assert not _NEW_CHANNELS & set(_EXPECTED_ROWS_BY_LANE["story"])
    assert not _NEW_CHANNELS & set(_EXPECTED_ROWS_BY_LANE["character"])
    assert not _NEW_CHANNELS & _CLAUDE_SET_CHANNELS_BY_LANE["novel"]


async def test_the_admin_preview_shows_both_new_channels_for_the_gemini_chain_only(db_session: AsyncSession) -> None:
    sections = await _novel_sections(db_session)
    chat_sets: dict[Literal["story", "character"], tuple[PromptSet, list[PromptSection]]] = {
        "story": await load_active_prompt_set(db_session, lane="story", model="gemini"),
        "character": await load_active_prompt_set(db_session, lane="character", model="gemini"),
    }
    sonnet_sections = (await load_active_prompt_set(db_session, lane="novel", model="sonnet"))[1]

    gemini_items = _novel_preview_items(sections, model="gemini", chat_sets=chat_sets)
    sonnet_items = _novel_preview_items(sonnet_sections, model="sonnet", chat_sets=chat_sets)

    previews = {item.label: item.text for item in gemini_items if item.channel in _NEW_CHANNELS}
    assert set(previews) == {
        "novelize_revise_blocks · 스토리",
        "novelize_revise_blocks · 캐릭터",
        "novelize_revise_recheck · 스토리",
        "novelize_revise_recheck · 캐릭터",
    }
    assert all("미리 볼 수 없습니다" not in text for text in previews.values())
    assert not {item.channel for item in sonnet_items} & _NEW_CHANNELS
