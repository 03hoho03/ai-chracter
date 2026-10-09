"""사용자 이름 한 줄 행(`user_name`, conditional)을 story·character 레인에 넣는 데이터 마이그레이션 `8e895c898730`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_situation_notes_prompt_migration.py`와 같은 방식). 세션 스코프
스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 published 분기는 "마이그레이션 뒤 DB 상태"를 단언하고,
순수 함수·`_patch_draft`·`_delete_draft_rows`는 직접 부른다(뒤 둘은 테스트마다 롤백되는 `db_session`의 커넥션에
`run_sync`로).

배치 픽스처는 2026-10-04 운영 읽기 전용 조회에서 본 활성 세트 배치와, 운영자가 위·아래 버튼으로 order를 맞바꾼 배치다."""

import importlib.util
import uuid
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import ALLOWED_PLACEHOLDERS, PromptLane, load_active_prompt_set, render_prompt_channel
from api.db.models.prompt import PromptSection, PromptSet

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("8e895c898730")
# 이 리비전이 복사한 원본(이전 레인 활성 세트) — 테스트 DB에서는 story 가 상황 노트 리비전의 세트, character 가 채팅방
# 기억 리비전의 세트다.
_SOURCE_SET_IDS: dict[str, uuid.UUID] = {
    "story": _load("2417f5829bb1").NEW_SET_ID,
    "character": _load("c328445d4c2d").NEW_SET_IDS["character"],
}
_LANES: tuple[PromptLane, ...] = ("story", "character")
# 이 리비전 뒤에 두 레인에 소설화 채널 행을 더하는 리비전 — 활성 세트가 그 세트로 넘어가고, 초안 게시 검사가 head 코드
# 표를 쓰므로 초안도 그 패치를 거친다.
_NOVELIZE_MIGRATION = _load("3bb2cc159b6d")
# story 레인 Gemini 체인에 스탯 규칙 판정 채널을 더하는 리비전 — 초안 게시 검사가 head 코드 표를 쓰므로 story 초안은
# 이것도 거친다.
_STAT_RULE_MIGRATION = _load("d9768bc0cfee")

Layout = list[tuple[str, str, str, str, int]]

_MEMORY_SUMMARY_LAYOUT: Layout = [
    ("memory_summary", "both", "instruction", "", 1),
    ("memory_summary", "both", "previous_summary", "", 2),
    ("memory_summary", "both", "turn_context", "", 3),
]
# 운영 활성 세트 배치(story v14·character v8) — `(channel, scope, slot, variant, order)`.
_LAYOUTS: dict[str, Layout] = {
    "story": [
        ("generation", "story", "base_content", "", 1),
        ("generation", "story", "base_content", "custom", 1),
        ("generation", "story", "rules", "", 2),
        ("generation", "story", "user_goal", "", 3),
        ("generation", "story", "development_examples", "", 4),
        ("generation", "story", "prologue", "", 5),
        ("generation", "both", "user_persona", "", 6),
        ("generation", "both", "memory_note", "", 7),
        ("generation", "both", "memory_summary", "", 8),
        ("generation", "both", "history", "", 9),
        ("generation", "story", "keyword_notes", "", 10),
        ("generation", "story", "situation_notes", "", 11),
        ("generation", "story", "shortcut_prompt", "", 12),
        ("generation", "both", "final_frame", "", 13),
        ("stat_judgment", "story", "stat_defs_intro", "", 1),
        ("stat_judgment", "story", "turn_context", "", 2),
        ("stat_judgment", "story", "judgment_instruction", "", 3),
        ("ending_judgment", "story", "memory_summary", "", 1),
        ("ending_judgment", "story", "history_header", "", 2),
        ("ending_judgment", "story", "turn_context", "", 3),
        ("ending_judgment", "story", "criteria", "", 4),
        ("image_judgment", "story", "image_list_intro", "", 1),
        ("image_judgment", "story", "turn_context", "", 2),
        ("image_judgment", "story", "judgment_instruction", "", 3),
        *_MEMORY_SUMMARY_LAYOUT,
        # 배치 검사가 보지 않는 채널의 행 — 새 행 자리와 같은 order 를 일부러 준다(밀리면 안 된다).
        ("system", "both", "rule_rating", "", 2),
    ],
    "character": [
        ("generation", "character", "character_prompt", "", 1),
        ("generation", "character", "example_dialogues", "", 2),
        ("generation", "both", "user_persona", "", 6),
        ("generation", "both", "memory_note", "", 7),
        ("generation", "both", "memory_summary", "", 8),
        ("generation", "both", "history", "", 9),
        ("generation", "both", "final_frame", "", 12),
        ("image_judgment", "character", "image_list_intro", "", 1),
        ("image_judgment", "character", "turn_context", "", 2),
        ("image_judgment", "character", "judgment_instruction", "", 3),
        *_MEMORY_SUMMARY_LAYOUT,
        ("system", "both", "rule_rating", "", 2),
    ],
}
# 운영 배치에서 새 행이 들어갈 자리 — generation 은 프로필 바로 뒤, 판정·요약은 대화 기록 묶음 바로 앞.
_PROD_INSERT_ORDERS: dict[str, dict[str, int]] = {
    "story": {"generation": 7, "stat_judgment": 2, "ending_judgment": 1, "image_judgment": 2, "memory_summary": 2},
    "character": {"generation": 7, "image_judgment": 2, "memory_summary": 2},
}
# 운영자가 위·아래 버튼으로 맞바꾼 배치 — 프로필을 기억 노트 뒤로, 판정 대화 기록을 목록 앞으로 올렸다.
_SWAPPED: dict[tuple[str, str], int] = {
    ("generation", "user_persona"): 7,
    ("generation", "memory_note"): 6,
    ("stat_judgment", "turn_context"): 1,
    ("stat_judgment", "stat_defs_intro"): 2,
    ("image_judgment", "turn_context"): 1,
    ("image_judgment", "image_list_intro"): 2,
}


def _with_orders(rows: Layout, orders: dict[tuple[str, str], int]) -> Layout:
    return [(c, s, slot, v, orders.get((c, slot), o)) for c, s, slot, v, o in rows]


def _render_slots(rows: list[tuple[str, str, str, str, int]], channel: str, scope: str) -> list[str]:
    sections = [
        PromptSection(channel=c, scope=s, slot=slot, variant=v, body="x", conditional=False, order=o)
        for c, s, slot, v, o in rows
    ]
    return [s.slot for s in sorted(sections, key=lambda s: s.order) if s.channel == channel and s.scope in ("both", scope) and s.variant == ""]


# 새 행의 기준 — `(기준 slot, 기준 바로 뒤에 오는가)`. 아니면 기준 바로 앞이다.
_ANCHORS: dict[str, tuple[str, bool]] = {
    "generation": ("user_persona", True),
    "stat_judgment": ("turn_context", False),
    "ending_judgment": ("memory_summary", False),
    "image_judgment": ("turn_context", False),
    "memory_summary": ("previous_summary", False),
}


def _assert_neighbours(rows: list[tuple[str, str, str, str, int]], lane: str) -> None:
    """렌더 순서에서 새 행이 채널마다 기준 행 바로 뒤(또는 바로 앞)에 하나씩 있다."""
    for channel in _PROD_INSERT_ORDERS[lane]:
        anchor, after = _ANCHORS[channel]
        slots = _render_slots(rows, channel, lane)
        assert slots.count("user_name") == 1, (channel, slots)
        index = slots.index("user_name")
        assert slots[index - 1 if after else index + 1] == anchor, (channel, slots)


# ---- 문안 성질 --------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [_M.GENERATION_BODY, _M.JUDGMENT_BODY])
def test_bodies_use_exactly_the_allowed_placeholder(body: str) -> None:
    """conditional 행은 플레이스홀더가 있어야 빈 값에서 드롭되고, 허용 밖 이름이 있으면 렌더가 실패한다."""
    names = [name for _, name, _, _ in Formatter().parse(body) if name]
    assert names == ["user_name"]
    for channel in _M._CHECKED_CHANNELS:
        assert ALLOWED_PLACEHOLDERS[(channel, "user_name")] == frozenset(names)


def test_bodies_read_as_the_name_inside_the_conversation() -> None:
    assert _M.GENERATION_BODY == "[사용자 이름]\n대화 속 사용자의 이름: {user_name}"
    assert _M.JUDGMENT_BODY == "대화 속 사용자의 이름: {user_name}"


# ---- `_assert_layout` · `_build_published_rows` -----------------------------------------------


@pytest.mark.parametrize("lane", _LANES)
def test_assert_layout_returns_insert_orders_for_prod_layout(lane: str) -> None:
    assert _M._assert_layout(_LAYOUTS[lane], lane) == _PROD_INSERT_ORDERS[lane]


@pytest.mark.parametrize("lane", _LANES)
def test_assert_layout_follows_the_anchors_current_order(lane: str) -> None:
    orders = _M._assert_layout(_with_orders(_LAYOUTS[lane], _SWAPPED), lane)
    # 프로필이 7 로 내려갔으니 그 뒤 8, 대화 기록이 1 로 올라갔으니 그 자리 1.
    assert orders["generation"] == 8
    assert orders["image_judgment"] == 1
    if lane == "story":
        assert orders["stat_judgment"] == 1


@pytest.mark.parametrize(
    ("lane", "rows"),
    [
        pytest.param(
            "story", [*_LAYOUTS["story"], ("stat_judgment", "story", "user_name", "", 4)], id="already-applied"
        ),
        pytest.param(
            "character",
            [*_LAYOUTS["character"], ("stat_judgment", "story", "turn_context", "", 1)],
            id="character-with-stat-judgment",
        ),
        pytest.param(
            "story", [r for r in _LAYOUTS["story"] if r[2] != "user_persona"], id="missing-anchor"
        ),
    ],
)
def test_assert_layout_raises_on_unexpected_layout(lane: str, rows: Layout) -> None:
    with pytest.raises(RuntimeError, match="슬롯 집합"):
        _M._assert_layout(rows, lane)


@pytest.mark.parametrize("lane", _LANES)
@pytest.mark.parametrize("orders", [pytest.param({}, id="prod"), pytest.param(_SWAPPED, id="swapped")])
def test_build_published_rows_puts_each_row_between_its_neighbours(
    lane: str, orders: dict[tuple[str, str], int]
) -> None:
    layout = _with_orders(_LAYOUTS[lane], orders)
    # body·conditional 은 행마다 달리 줘서 복사 중에 뒤섞이면 드러나게 한다.
    source = [(c, s, slot, v, f"body:{c}:{slot}:{v}", i % 2 == 0, o) for i, (c, s, slot, v, o) in enumerate(layout)]
    set_id = uuid.UUID("00000000-0000-0000-0000-000000000003")
    insert_orders = _M._assert_layout(layout, lane)

    built = _M._build_published_rows(source, lane, set_id, insert_orders)

    assert all(row["prompt_set_id"] == set_id for row in built)
    assert len({row["id"] for row in built}) == len(built)
    added = [row for row in built if row["slot"] == "user_name"]
    assert {row["channel"]: (row["body"], row["conditional"]) for row in added} == {
        channel: (_M.GENERATION_BODY if channel == "generation" else _M.JUDGMENT_BODY, True)
        for channel in _PROD_INSERT_ORDERS[lane]
    }
    copied = {(r["channel"], r["scope"], r["slot"], r["variant"]): (r["body"], r["conditional"]) for r in built}
    assert all(copied[(c, s, slot, v)] == (body, cond) for c, s, slot, v, body, cond, _ in source)
    rows = [(str(r["channel"]), str(r["scope"]), str(r["slot"]), str(r["variant"]), r["order"]) for r in built]
    assert all(isinstance(order, int) for *_, order in rows)
    _assert_neighbours([(c, s, slot, v, int(str(o))) for c, s, slot, v, o in rows], lane)
    # 다른 채널(system)의 행은 같은 order 라도 밀리지 않는다.
    assert ("system", "both", "rule_rating", "", 2) in rows


# ---- 마이그레이션 뒤 DB 상태 — published 분기 ----------------------------------------------------


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _rows(sections: list[PromptSection]) -> list[tuple[str, str, str, str, int]]:
    return [(s.channel, s.scope, s.slot, s.variant, s.order) for s in sections]


@pytest.mark.parametrize("lane", _LANES)
async def test_active_set_is_this_revisions_set_with_name_rows(db_session: AsyncSession, lane: PromptLane) -> None:
    """회귀 방지 — `published_at`이 원본보다 과거가 되면 새 세트가 활성이 되지 못하고, 골든은 옛 세트로도 통과하므로
    신호가 없다. 그래서 활성 세트를 id·게시 시각으로 직접 단언한다 — 이 리비전의 세트이거나, 뒤 리비전이 이 세트를
    복사해 만든 더 나중 세트다(소설화 채널 리비전이 그렇다). 원본의 다른 행은 body·conditional 이 바이트 그대로다."""
    latest, _ = await load_active_prompt_set(db_session, lane=lane)
    active = await db_session.get(PromptSet, _M.NEW_SET_IDS[lane])
    assert active is not None
    assert latest.published_at is not None and active.published_at is not None
    assert latest.id == active.id or latest.published_at > active.published_at
    assert active.note == _M._NOTE
    source_set = await db_session.get(PromptSet, _SOURCE_SET_IDS[lane])
    assert source_set is not None and source_set.published_at is not None and active.published_at is not None
    assert active.published_at > source_set.published_at
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(active, a) for a in labels] == [getattr(source_set, a) for a in labels]

    # `_sections_of` 가 식별자 맵을 만료시키므로 이 리비전 세트 섹션 값은 그 전에 뽑는다.
    sections = await _sections_of(db_session, _M.NEW_SET_IDS[lane])
    new = {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional) for s in sections}
    new_rows = _rows(sections)
    old = {
        (s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional)
        for s in await _sections_of(db_session, _SOURCE_SET_IDS[lane])
    }
    added = {key: new.pop(key) for key in list(new) if key[2] == "user_name"}
    assert new == old
    assert {key[0] for key in added} == set(_PROD_INSERT_ORDERS[lane])
    _assert_neighbours(new_rows, lane)


async def test_versions_follow_global_sequence_story_first(db_session: AsyncSession) -> None:
    """`max(version::int)+1` 전 레인 대상, story 먼저. 테스트 DB의 이전 published 최대는 상황 노트 리비전의 "9"다."""
    versions = {lane: await db_session.get(PromptSet, _M.NEW_SET_IDS[lane]) for lane in _LANES}
    assert {lane: s.version if s else None for lane, s in versions.items()} == {"story": "10", "character": "11"}


_RENDER_SCOPES: dict[str, list[tuple[str, str, str]]] = {
    "story": [
        ("generation", "story", ""),
        ("generation", "story", "custom"),
        ("stat_judgment", "story", ""),
        ("ending_judgment", "story", ""),
        ("image_judgment", "story", ""),
        ("memory_summary", "story", ""),
    ],
    "character": [
        ("generation", "character", ""),
        ("image_judgment", "character", ""),
        ("memory_summary", "character", ""),
    ],
}


@pytest.mark.parametrize("lane", _LANES)
async def test_render_is_byte_identical_without_a_name_and_shows_the_line_with_one(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """이름이 없으면(생성은 프로필이 있어도) 이 리비전 전 세트와 렌더가 바이트까지 같다. 이름이 있으면 그 채널에 한 줄이
    더해진다."""
    old_sections = await _sections_of(db_session, _SOURCE_SET_IDS[lane])
    _, new_sections = await load_active_prompt_set(db_session, lane=lane)
    values = {
        name: f"<{name}>" for section in old_sections for _, name, _, _ in Formatter().parse(section.body) if name
    }

    for channel, scope, variant in _RENDER_SCOPES[lane]:
        before = render_prompt_channel(
            old_sections, channel=channel, scope=scope, variant=variant, values={**values, "user_name": ""}
        )
        without_name = render_prompt_channel(
            new_sections, channel=channel, scope=scope, variant=variant, values={**values, "user_name": ""}
        )
        with_name = render_prompt_channel(
            new_sections, channel=channel, scope=scope, variant=variant, values={**values, "user_name": "지훈"}
        )
        assert before, channel  # 빈 문자열끼리의 비교가 아니다
        assert without_name == before, channel
        line = (_M.GENERATION_BODY if channel == "generation" else _M.JUDGMENT_BODY).format(user_name="지훈")
        assert with_name.count(line) == 1, channel
        assert with_name.replace(line + "\n\n", "", 1) == before or with_name.replace("\n\n" + line, "", 1) == before


# ---- `_patch_draft` ------------------------------------------------------------------------


async def _clone_as_draft(
    db_session: AsyncSession, set_id: uuid.UUID, lane: PromptLane, *, orders: dict[tuple[str, str], int] | None = None
) -> uuid.UUID:
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
                order=(orders or {}).get((s.channel, s.slot), s.order),
            )
        )
    await db_session.flush()
    return draft_id


@pytest.mark.parametrize("lane", _LANES)
@pytest.mark.parametrize("orders", [pytest.param(None, id="as-published"), pytest.param(_SWAPPED, id="swapped")])
async def test_patch_draft_adds_rows_in_place_and_draft_then_publishes(
    db_session: AsyncSession, lane: PromptLane, orders: dict[tuple[str, str], int] | None
) -> None:
    """운영 두 레인에는 초안이 있다 — 이 분기가 실제로 탄다. 이 리비전 이전 배치의 초안(원본 세트 복제)에 행이 초안
    **자신의** 기준 행 옆에 더해지고, 게시 게이트 전체(head 코드 표)를 통과한다."""
    draft_id = await _clone_as_draft(db_session, _SOURCE_SET_IDS[lane], lane, orders=orders)
    before = {(s.channel, s.scope, s.slot, s.variant): s.body for s in await _sections_of(db_session, draft_id)}

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft, lane) is True

    sections = await _sections_of(db_session, draft_id)
    after = {(s.channel, s.scope, s.slot, s.variant): s.body for s in sections}
    assert {key: body for key, body in after.items() if key[2] != "user_name"} == before
    _assert_neighbours(_rows(sections), lane)

    # 코드 표는 지금 head 기준이라, 체인이 실제로 하듯 뒤 리비전(소설화 채널)의 초안 패치도 거친 뒤 검사한다.
    assert await connection.run_sync(_NOVELIZE_MIGRATION._patch_draft, lane) is True
    assert await connection.run_sync(_STAT_RULE_MIGRATION._patch_draft) is (lane == "story")
    sections = await _sections_of(db_session, draft_id)
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
    originals = {lane: _rows(await _sections_of(db_session, draft_id)) for lane, draft_id in drafts.items()}
    connection = await db_session.connection()
    for lane in _LANES:
        await connection.run_sync(_M._patch_draft, lane)
    published_before = {lane: _rows(await _sections_of(db_session, _M.NEW_SET_IDS[lane])) for lane in _LANES}

    await connection.run_sync(_M._delete_draft_rows)

    for lane, draft_id in drafts.items():
        assert sorted(_rows(await _sections_of(db_session, draft_id))) == sorted(originals[lane])
        assert sorted(_rows(await _sections_of(db_session, _M.NEW_SET_IDS[lane]))) == sorted(published_before[lane])
