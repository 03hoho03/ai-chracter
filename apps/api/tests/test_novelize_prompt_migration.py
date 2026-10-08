"""소설화 세 채널(장 경계 제안·장 생성·문단 수정)을 story·character 레인에 넣는 데이터 마이그레이션 `3bb2cc159b6d`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_user_name_prompt_migration.py`와 같은 방식). 세션 스코프 스키마
(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 published 분기는 "마이그레이션 뒤 DB 상태"를 단언하고, 순수 함수·
`_patch_draft`·`_delete_draft_rows`는 직접 부른다(뒤 둘은 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로).
왕복(upgrade/downgrade)은 세션 스키마의 teardown 이 `downgrade base` 로 탄다."""

import importlib.util
import uuid
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import ALLOWED_PLACEHOLDERS, PromptLane, PromptRenderError, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.novelize.prompts import (
    build_novelize_boundary_prompt,
    build_novelize_chapter_prompt,
    build_novelize_revise_prompt,
)

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("3bb2cc159b6d")
# 이 리비전이 복사한 원본 — 테스트 DB에서는 두 레인 모두 사용자 이름 한 줄 리비전의 세트다.
_SOURCE_SET_IDS: dict[str, uuid.UUID] = _load("8e895c898730").NEW_SET_IDS
_LANES: tuple[PromptLane, ...] = ("story", "character")

Key = tuple[str, str, str, str]


def _placeholders(body: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(body) if name}


# ---- 문안 성질 --------------------------------------------------------------------------------


def test_every_body_uses_exactly_the_allowed_placeholders() -> None:
    """허용 밖 이름이 있으면 렌더가 실패하고, 허용 이름을 안 쓰면 빌더가 만든 값이 프롬프트에 실리지 않는다."""
    for channel, rows in _M.ROWS.items():
        for slot, body, _conditional in rows:
            assert _placeholders(body) == ALLOWED_PLACEHOLDERS[(channel, slot)], (channel, slot)


def test_instructions_have_no_placeholder_and_conditional_rows_have_one() -> None:
    """지시문은 `values={}` 로 따로 렌더한다. conditional 행은 자리표시자가 있어야 값이 비었을 때 섹션째 빠진다."""
    for channel, rows in _M.ROWS.items():
        assert rows[0][0] == "instruction", channel
        for slot, body, conditional in rows:
            if slot == "instruction":
                assert not _placeholders(body) and not conditional, channel
            if conditional:
                assert _placeholders(body), (channel, slot)


def test_conditional_slots_are_the_ones_that_may_be_empty() -> None:
    conditional = {(channel, slot) for channel, rows in _M.ROWS.items() for slot, _b, cond in rows if cond}
    assert conditional == {
        ("novelize_boundary", "user_name"),
        ("novelize_chapter", "setting_notes"),
        ("novelize_chapter", "previous_excerpt"),
        ("novelize_revise", "setting_notes"),
    }


# ---- `_assert_layout` · `_build_published_rows` -----------------------------------------------

_LAYOUT: list[tuple[str, str, str, str, int]] = [
    ("system", "both", "rule_rating", "", 2),
    ("generation", "both", "history", "", 0),
    ("memory_summary", "both", "instruction", "", 0),
]


def test_assert_layout_accepts_a_set_without_novelize_rows() -> None:
    _M._assert_layout(_LAYOUT, "story")


@pytest.mark.parametrize("channel", _M.CHANNELS)
def test_assert_layout_raises_when_a_novelize_row_already_exists(channel: str) -> None:
    with pytest.raises(RuntimeError, match="잉여"):
        _M._assert_layout([*_LAYOUT, (channel, "both", "instruction", "", 0)], "character")


def test_build_published_rows_copies_the_source_as_is_and_adds_the_channels_from_order_zero() -> None:
    # body·conditional 은 행마다 달리 줘서 복사 중에 뒤섞이면 드러나게 한다.
    source = [(c, s, slot, v, f"body:{c}:{slot}", i % 2 == 0, o) for i, (c, s, slot, v, o) in enumerate(_LAYOUT)]
    set_id = uuid.UUID("00000000-0000-0000-0000-000000000004")

    built = _M._build_published_rows(source, "story", set_id)

    assert all(row["prompt_set_id"] == set_id for row in built)
    assert len({row["id"] for row in built}) == len(built)
    rows = [(r["channel"], r["scope"], r["slot"], r["variant"], r["body"], r["conditional"], r["order"]) for r in built]
    assert rows[: len(source)] == source
    added = rows[len(source) :]
    assert added == [
        (channel, "both", slot, "", body, conditional, order)
        for channel, channel_rows in _M.ROWS.items()
        for order, (slot, body, conditional) in enumerate(channel_rows)
    ]
    assert len(added) == 16


# ---- 마이그레이션 뒤 DB 상태 — published 분기 ----------------------------------------------------


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, tuple[str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_new_rows() -> dict[Key, tuple[str, bool, int]]:
    return {
        (channel, "both", slot, ""): (body, conditional, order)
        for channel, rows in _M.ROWS.items()
        for order, (slot, body, conditional) in enumerate(rows)
    }


@pytest.mark.parametrize("lane", _LANES)
async def test_active_set_is_this_revisions_set_with_the_novelize_rows(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """회귀 방지 — `published_at`이 원본보다 과거가 되면 새 세트가 활성이 되지 못한다. 이 리비전의 세트이거나 뒤
    리비전이 이 세트를 복사해 만든 더 나중 세트가 활성이다. 원본의 다른 행은 body·conditional·order 가 바이트
    그대로다(채팅 렌더가 바뀌지 않는다)."""
    latest, _ = await load_active_prompt_set(db_session, lane=lane)
    this_set = await db_session.get(PromptSet, _M.NEW_SET_IDS[lane])
    source_set = await db_session.get(PromptSet, _SOURCE_SET_IDS[lane])
    assert this_set is not None and source_set is not None
    assert latest.published_at is not None and this_set.published_at is not None
    assert source_set.published_at is not None
    assert latest.id == this_set.id or latest.published_at > this_set.published_at
    assert this_set.published_at > source_set.published_at
    assert this_set.note == _M._NOTE
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(this_set, a) for a in labels] == [getattr(source_set, a) for a in labels]

    new = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[lane]))
    old = _keyed(await _sections_of(db_session, _SOURCE_SET_IDS[lane]))
    added = {key: new.pop(key) for key in list(new) if key[0] in _M.CHANNELS}
    assert new == old
    assert added == _expected_new_rows()


async def test_versions_follow_global_sequence_story_first(db_session: AsyncSession) -> None:
    """`max(version::int)+1` 전 레인 대상, story 먼저. 테스트 DB의 이전 published 최대는 사용자 이름 한 줄 리비전의
    "11"이다."""
    versions = {lane: await db_session.get(PromptSet, _M.NEW_SET_IDS[lane]) for lane in _LANES}
    assert {lane: s.version if s else None for lane, s in versions.items()} == {"story": "12", "character": "13"}


@pytest.mark.parametrize("lane", _LANES)
async def test_builders_render_the_seeded_text_with_the_lanes_rating_rule(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """시드한 문안이 빌더로 실제로 렌더된다 — 지시문은 문안 그대로이고, 문단 수정은 그 뒤에 같은 세트의 등급 규칙 본문이
    붙는다. 이 행은 지금 채팅 레인에 얼려 둔 옛 문안이다(옛 이미지로 되돌렸을 때 옛 코드가 읽는다). 지금 코드는 소설 레인
    세트를 읽고, 장 생성 행은 화 수 지시 슬롯이 없어 지금 빌더로는 렌더되지 않는다 — 그래서 장 생성 문안은 렌더하지 않고
    문안 상수로 본다."""
    sections = await _sections_of(db_session, _M.NEW_SET_IDS[lane])  # 식별자 맵을 만료시키므로 세트보다 먼저
    prompt_set = await db_session.get(PromptSet, _M.NEW_SET_IDS[lane])
    assert prompt_set is not None
    rule = next(s.body for s in sections if s.channel == "system" and s.slot == "rule_rating")
    is_story = lane == "story"

    boundary = build_novelize_boundary_prompt(
        chat_set=prompt_set,
        sections=sections,
        is_story_chat=is_story,
        max_turns=7,
        user_name="서진",
        turn_lines="[턴 1] 캐릭터: 왔어?",
    )
    assert boundary.system_instruction == _M.BOUNDARY_INSTRUCTION
    assert "이름: 서진" in boundary.prompt and "[턴 1]부터 [턴 7]까지" in boundary.prompt
    # 경계 제안도 장 생성과 같은 줄 형식을 받으므로, 같은 번호의 줄이 한 턴이라는 설명을 같은 글자로 싣는다.
    same_turn_note = "줄마다 앞에 [턴 n] 번호가 붙어 있고, 같은 번호의 줄은 한 턴이다."
    assert same_turn_note in boundary.prompt and same_turn_note in _M.CHAPTER_TURN_CONTEXT
    assert "[n턴]" not in boundary.system_instruction
    # 이야기 밖 말(OOC·AI·저장 같은 질문)에 상대가 작중 말투로 답하면 모델은 그 교환을 이야기 속 대화로 남겼다 —
    # 경계 제안은 그 교환을 장면으로 치지 않고, 장 생성은 말과 반응을 함께 뺀다. 질문만이 아니라 "이거 저장해 둬"
    # 같은 진술도 이야기 밖 말이므로, 범위는 "묻는 말"이 아니라 "관한 말"로 적는다.
    meta_scope = "AI·모델·프롬프트·저장·턴·설정에 관한 말"
    assert meta_scope in boundary.system_instruction
    assert "그에 대한 상대 쪽의 반응은 장면으로 치지 않는다" in boundary.system_instruction

    chapter_instruction = next(s.body for s in sections if s.channel == "novelize_chapter" and s.slot == "instruction")
    assert chapter_instruction == _M.CHAPTER_INSTRUCTION
    assert meta_scope in chapter_instruction
    assert "그 교환을 통째로 빼고 앞뒤 이야기를 자연스럽게 잇는다" in chapter_instruction
    assert "이야기 밖 말과 그에 대한 반응만 있는 줄은 예외다" in chapter_instruction
    with pytest.raises(PromptRenderError, match="episode_plan"):
        build_novelize_chapter_prompt(
            chat_set=prompt_set,
            chat_sections=sections,
            sections=sections,
            is_story_chat=is_story,
            work_setting="<설정>",
            user_name="서진",
            setting_notes="",
            previous_excerpt="",
            turn_lines="[턴 1] 캐릭터: 왔어?",
        )

    revise = build_novelize_revise_prompt(
        chat_sections=sections,
        sections=sections,
        is_story_chat=is_story,
        work_setting="<설정>",
        setting_notes="<노트>",
        paragraphs=["가", "나"],
        first_index=0,
        last_index=1,
        user_request="<요청>",
    )
    assert revise.system_instruction == f"{_M.REVISE_INSTRUCTION}\n\n{rule}"
    assert "[1] 가\n\n[2] 나" in revise.prompt and "1번 문단부터 2번 문단까지" in revise.prompt


async def test_the_set_before_this_revision_refuses_to_render(db_session: AsyncSession) -> None:
    """배포 직후 캐시에 남은 옛 세트에는 소설화 행이 없다 — 빈 프롬프트 대신 렌더 오류다."""
    sections = await _sections_of(db_session, _SOURCE_SET_IDS["story"])  # 식별자 맵을 만료시키므로 세트보다 먼저
    prompt_set = await db_session.get(PromptSet, _SOURCE_SET_IDS["story"])
    assert prompt_set is not None
    with pytest.raises(PromptRenderError):
        build_novelize_chapter_prompt(
            chat_set=prompt_set,
            chat_sections=sections,
            sections=sections,
            is_story_chat=True,
            work_setting="<설정>",
            user_name="서진",
            setting_notes="",
            previous_excerpt="",
            turn_lines="[턴 1] 진행자: 시작",
        )


# ---- `_patch_draft` ------------------------------------------------------------------------


async def _clone_as_draft(db_session: AsyncSession, set_id: uuid.UUID, lane: PromptLane) -> uuid.UUID:
    source = await db_session.get(PromptSet, set_id)
    assert source is not None
    draft = PromptSet(
        version=None,
        status="draft",
        lane=lane,
        user_label=source.user_label,
        story_assistant_label=source.story_assistant_label,
        story_example_label=source.story_example_label,
        character_assistant_label=source.character_assistant_label,
    )
    db_session.add(draft)
    await db_session.flush()
    draft_id = draft.id
    for s in await _sections_of(db_session, set_id):
        db_session.add(
            PromptSection(
                prompt_set_id=draft_id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=s.body,
                conditional=s.conditional,
                order=s.order,
            )
        )
    await db_session.flush()
    return draft_id


@pytest.mark.parametrize("lane", _LANES)
async def test_patch_draft_adds_the_rows_and_the_draft_then_publishes(db_session: AsyncSession, lane: PromptLane) -> None:
    """운영 두 레인에는 초안이 있다 — 이 분기가 실제로 탄다. 이 리비전 이전 배치의 초안(원본 세트 복제)에 소설화 행이
    더해지고, 기존 행은 그대로이며, 게시 게이트 전체(head 코드 표)를 통과한다."""
    draft_id = await _clone_as_draft(db_session, _SOURCE_SET_IDS[lane], lane)
    before = _keyed(await _sections_of(db_session, draft_id))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft, lane) is True

    sections = await _sections_of(db_session, draft_id)
    after = _keyed(sections)
    added = {key: after.pop(key) for key in list(after) if key[0] in _M.CHANNELS}
    assert after == before
    assert added == _expected_new_rows()

    draft = await db_session.get(PromptSet, draft_id)
    assert draft is not None
    _validate_prompt_draft_for_publish(draft, sections, lane=lane)


async def test_patch_draft_without_a_draft_is_a_no_op(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft, "character") is False


async def test_patch_draft_raises_when_draft_already_has_the_rows(db_session: AsyncSession) -> None:
    await _clone_as_draft(db_session, _M.NEW_SET_IDS["story"], "story")

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="잉여"):
        await connection.run_sync(_M._patch_draft, "story")


# ---- 되돌리기 ------------------------------------------------------------------------------


async def test_delete_draft_rows_restores_drafts_and_leaves_published_sets(db_session: AsyncSession) -> None:
    drafts = {lane: await _clone_as_draft(db_session, _SOURCE_SET_IDS[lane], lane) for lane in _LANES}
    originals = {lane: _keyed(await _sections_of(db_session, draft_id)) for lane, draft_id in drafts.items()}
    connection = await db_session.connection()
    for lane in _LANES:
        await connection.run_sync(_M._patch_draft, lane)
    published_before = {lane: _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[lane])) for lane in _LANES}

    await connection.run_sync(_M._delete_draft_rows)

    for lane, draft_id in drafts.items():
        assert _keyed(await _sections_of(db_session, draft_id)) == originals[lane]
        assert _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[lane])) == published_before[lane]
