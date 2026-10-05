"""채팅방 기억 행(generation `memory_note`·`memory_summary`, ending_judgment `memory_summary`, 새 channel
`memory_summary`)을 넣는 데이터 마이그레이션 `c328445d4c2d`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_persona_prompt_slot_migration.py`와 같은 방식). 세션
스코프 스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로:

- published 분기는 "마이그레이션 뒤 DB 상태"를 단언한다 — 리터럴 PK가 이미 있어 다시 실행하면
  충돌한다.
- 순수 함수(`_assert_layout`·`_build_published_rows`)는 직접 부른다. 배치 픽스처는 2026-09-28
  프로덕션 읽기 전용 조회에서 본 배치(generation `user_persona` 6 · `history` 7, ending
  `history_header` 1)와 운영자가 order를 맞바꾼 배치다.
- `_patch_draft`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 부른다. 이 리비전 이전
  배치의 초안은 이 리비전이 복사한 원본 세트(`b72c33c70240`의 세트)를 `status='draft'`로 복제해
  만든다.

문안은 마이그레이션의 상수와 비교한다 — 문안이 검토로 바뀌어도 이 파일은 고칠 곳이 없게 하려는
것이다. 문안 자체의 성질(플레이스홀더가 있어 빈 값이면 드롭된다)은 따로 본다.
"""

import importlib.util
import uuid
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import (
    PromptLane,
    load_active_prompt_set,
    render_prompt_channel,
    select_sections_for_render,
)
from api.db.models.prompt import PromptSection, PromptSet

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("c328445d4c2d")
# 이 리비전이 복사한 원본(이전 레인 활성 세트) — 테스트 DB에서는 `b72c33c70240`이 만든 세트다.
_SOURCE_SET_IDS: dict[str, uuid.UUID] = _load("b72c33c70240").NEW_SET_IDS
# 이 리비전 뒤에 같은 방식으로 story 레인에 행을 더하는 리비전 — 초안 게시 검사가 head 코드 표를 쓰므로 함께
# 거친다.
_NEXT_STORY_MIGRATION = _load("2519dde454e0")
# 그 뒤 story 레인 generation 에 상황 노트 행을 더하는 리비전 — 같은 이유로 story 초안은 이것도 거친다.
_SITUATION_NOTES_MIGRATION = _load("2417f5829bb1")
# 그 뒤 두 레인에 사용자 이름 한 줄 행을 더하는 리비전 — 같은 이유로 초안은 이것도 거친다.
_USER_NAME_MIGRATION = _load("8e895c898730")
# 그 뒤 두 레인에 소설화 채널 행을 더하는 리비전 — 같은 이유로 초안은 이것도 거친다.
_NOVELIZE_MIGRATION = _load("3bb2cc159b6d")

_NOTE_KEY = ("generation", "both", "memory_note", "")
_GEN_SUMMARY_KEY = ("generation", "both", "memory_summary", "")
_ENDING_SUMMARY_KEY = ("ending_judgment", "story", "memory_summary", "")
_CHANNEL_KEYS = [
    ("memory_summary", "both", "instruction", ""),
    ("memory_summary", "both", "previous_summary", ""),
    ("memory_summary", "both", "turn_context", ""),
]


def _added_keys(lane: str) -> set[tuple[str, str, str, str]]:
    keys = {_NOTE_KEY, _GEN_SUMMARY_KEY, *_CHANNEL_KEYS}
    return keys | {_ENDING_SUMMARY_KEY} if lane == "story" else keys


# 새 행의 기대 (body, conditional). order는 배치마다 달라 따로 본다.
_EXPECTED_NEW: dict[tuple[str, str, str, str], tuple[str, bool]] = {
    _NOTE_KEY: (_M.MEMORY_NOTE_BODY, True),
    _GEN_SUMMARY_KEY: (_M.GENERATION_SUMMARY_BODY, True),
    _ENDING_SUMMARY_KEY: (_M.ENDING_SUMMARY_BODY, True),
    _CHANNEL_KEYS[0]: (_M.SUMMARY_INSTRUCTION_BODY, False),
    _CHANNEL_KEYS[1]: (_M.SUMMARY_PREVIOUS_BODY, True),
    _CHANNEL_KEYS[2]: (_M.SUMMARY_TURNS_BODY, False),
}

# 프로덕션 배치 — `(channel, scope, slot, variant, order)`.
_STORY_LAYOUT: list[tuple[str, str, str, str, int]] = [
    ("generation", "story", "base_content", "", 1),
    ("generation", "story", "base_content", "custom", 1),
    ("generation", "story", "rules", "", 2),
    ("generation", "story", "user_goal", "", 3),
    ("generation", "story", "development_examples", "", 4),
    ("generation", "story", "prologue", "", 5),
    ("generation", "both", "user_persona", "", 6),
    ("generation", "both", "history", "", 7),
    ("generation", "story", "keyword_notes", "", 8),
    ("generation", "story", "shortcut_prompt", "", 9),
    ("generation", "both", "final_frame", "", 10),
    ("ending_judgment", "story", "history_header", "", 1),
    ("ending_judgment", "story", "turn_context", "", 2),
    ("ending_judgment", "story", "criteria", "", 3),
]
_CHARACTER_LAYOUT: list[tuple[str, str, str, str, int]] = [
    ("generation", "character", "character_prompt", "", 1),
    ("generation", "character", "example_dialogues", "", 2),
    ("generation", "both", "user_persona", "", 6),
    ("generation", "both", "history", "", 7),
    ("generation", "both", "final_frame", "", 10),
]
# 배치 검사가 보지 않는 채널의 행 — generation의 H와 같은 order를 일부러 준다.
_SYSTEM_ROW = ("system", "both", "rule_rating", "", 7)

# 운영자가 위·아래 버튼으로 맞바꾼 배치. story는 history를 keyword_notes 뒤로, ending은 기록 머리글을
# 턴 맥락 뒤로 보냈다. character는 history를 final_frame 뒤로 보냈다.
_STORY_SWAPPED = {("generation", "history"): 9, ("generation", "keyword_notes"): 7, ("generation", "shortcut_prompt"): 8,
                  ("ending_judgment", "history_header"): 2, ("ending_judgment", "turn_context"): 1}
_CHARACTER_SWAPPED = {("generation", "history"): 10, ("generation", "final_frame"): 7}


def _with_orders(
    rows: list[tuple[str, str, str, str, int]], orders: dict[tuple[str, str], int]
) -> list[tuple[str, str, str, str, int]]:
    return [(c, s, slot, v, orders.get((c, slot), o)) for c, s, slot, v, o in rows]


# ---- 문안 성질 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "placeholder"),
    [
        pytest.param(_M.MEMORY_NOTE_BODY, "memory_note", id="note"),
        pytest.param(_M.GENERATION_SUMMARY_BODY, "memory_summary", id="generation-summary"),
        pytest.param(_M.ENDING_SUMMARY_BODY, "memory_summary", id="ending-summary"),
        pytest.param(_M.SUMMARY_PREVIOUS_BODY, "previous_summary", id="previous-summary"),
        pytest.param(_M.SUMMARY_TURNS_BODY, "turn_lines", id="turns"),
    ],
)
def test_memory_bodies_use_exactly_their_own_placeholder(body: str, placeholder: str) -> None:
    """conditional 행은 플레이스홀더가 있어야 빈 값에서 드롭된다 — 빠지면 모든 방에 머리글만 나간다."""
    assert [name for _, name, _, _ in Formatter().parse(body) if name] == [placeholder]


def test_summary_instruction_has_no_placeholder() -> None:
    """지시문은 항상 실리는 행이고 렌더 `values`에 없는 이름이 있으면 렌더가 실패한다."""
    assert [name for _, name, _, _ in Formatter().parse(_M.SUMMARY_INSTRUCTION_BODY) if name] == []


# ---- `_assert_layout` — 가정이 맞으면 (H, E), 어긋나면 raise --------------------------------


@pytest.mark.parametrize(
    ("lane", "rows", "expected"),
    [
        pytest.param("story", _STORY_LAYOUT, (7, 1), id="story-prod"),
        pytest.param("story", _with_orders(_STORY_LAYOUT, _STORY_SWAPPED), (9, 2), id="story-swapped"),
        pytest.param("character", _CHARACTER_LAYOUT, (7, None), id="character-prod"),
        pytest.param("character", _with_orders(_CHARACTER_LAYOUT, _CHARACTER_SWAPPED), (10, None), id="character-swapped"),
    ],
)
def test_assert_layout_returns_history_and_history_header_orders(
    lane: str, rows: list[tuple[str, str, str, str, int]], expected: tuple[int, int | None]
) -> None:
    assert _M._assert_layout([*rows, _SYSTEM_ROW], lane) == expected


@pytest.mark.parametrize(
    ("lane", "rows", "match"),
    [
        pytest.param(
            "story", [r for r in _STORY_LAYOUT if r[2] != "keyword_notes"], "generation 슬롯 집합", id="missing-slot"
        ),
        pytest.param(
            "character",
            [*_CHARACTER_LAYOUT, ("generation", "character", "surprise", "", 11)],
            "generation 슬롯 집합",
            id="unknown-slot",
        ),
        pytest.param(
            "story",
            [r for r in _STORY_LAYOUT if r[2] != "criteria"],
            "ending_judgment 슬롯 집합",
            id="story-ending-missing",
        ),
        pytest.param(
            "character",
            [*_CHARACTER_LAYOUT, ("ending_judgment", "story", "history_header", "", 1)],
            "ending_judgment 슬롯 집합",
            id="character-has-ending",
        ),
        pytest.param(
            "story",
            _with_orders(_STORY_LAYOUT, {("generation", "user_persona"): 8, ("generation", "keyword_notes"): 6}),
            "user_persona",
            id="persona-after-history",
        ),
    ],
)
def test_assert_layout_raises_on_unexpected_layout(
    lane: str, rows: list[tuple[str, str, str, str, int]], match: str
) -> None:
    with pytest.raises(RuntimeError, match=match):
        _M._assert_layout(rows, lane)


@pytest.mark.parametrize(
    ("lane", "extra", "match"),
    [
        pytest.param("character", ("generation", "both", "memory_note", "", 7), "기억 슬롯이 이미", id="note"),
        pytest.param("story", ("generation", "both", "memory_summary", "", 7), "기억 슬롯이 이미", id="summary"),
        pytest.param("story", ("ending_judgment", "story", "memory_summary", "", 1), "기억 슬롯이 이미", id="ending"),
        pytest.param("character", ("memory_summary", "both", "instruction", "", 1), "channel 행이 이미", id="channel"),
    ],
)
def test_assert_layout_raises_when_memory_rows_already_exist(
    lane: str, extra: tuple[str, str, str, str, int], match: str
) -> None:
    """두 번 적용되는 것을 막는다. 슬롯 집합 검사도 "잉여"로 raise하므로 메시지로 전용 검사가 먼저
    걸렸는지 가른다."""
    rows = _STORY_LAYOUT if lane == "story" else _CHARACTER_LAYOUT
    with pytest.raises(RuntimeError, match=match):
        _M._assert_layout([*rows, extra], lane)


# ---- `_build_published_rows` — 재배치된 배치에서도 기준 행 바로 앞 --------------------------------


def _source_rows(
    rows: list[tuple[str, str, str, str, int]],
) -> list[tuple[str, str, str, str, str, bool, int]]:
    """`(channel, scope, slot, variant, body, conditional, order)` — body·conditional은 행마다 다르게
    줘서 복사 중에 뒤섞이면 드러나게 한다."""
    return [(c, s, slot, v, f"body:{c}:{slot}:{v}", i % 2 == 0, o) for i, (c, s, slot, v, o) in enumerate(rows)]


def _render_slots(sections: list[PromptSection], *, channel: str, scope: str, variant: str = "") -> list[str]:
    return [s.slot for s in select_sections_for_render(sections, channel=channel, scope=scope, variant=variant)]


def _assert_render_order(sections: list[PromptSection], before: list[PromptSection], lane: str) -> None:
    """기억 행이 기준 행 바로 앞에 오고, 나머지 상대 순서는 원본과 같다."""
    gen = _render_slots(sections, channel="generation", scope=lane)
    i = gen.index("memory_note")
    assert gen[i : i + 3] == ["memory_note", "memory_summary", "history"]
    assert [s for s in gen if not s.startswith("memory_")] == _render_slots(before, channel="generation", scope=lane)

    assert _render_slots(sections, channel="memory_summary", scope=lane) == [
        "instruction",
        "previous_summary",
        "turn_context",
    ]
    if lane == "story":
        ending = _render_slots(sections, channel="ending_judgment", scope=lane)
        j = ending.index("memory_summary")
        assert ending[j + 1] == "history_header"
        assert [s for s in ending if s != "memory_summary"] == _render_slots(
            before, channel="ending_judgment", scope=lane
        )


@pytest.mark.parametrize(
    ("lane", "rows"),
    [
        pytest.param("story", _STORY_LAYOUT, id="story-prod"),
        pytest.param("story", _with_orders(_STORY_LAYOUT, _STORY_SWAPPED), id="story-swapped"),
        pytest.param("character", _CHARACTER_LAYOUT, id="character-prod"),
        pytest.param("character", _with_orders(_CHARACTER_LAYOUT, _CHARACTER_SWAPPED), id="character-swapped"),
    ],
)
def test_build_published_rows_puts_memory_rows_right_before_their_anchor(
    lane: str, rows: list[tuple[str, str, str, str, int]]
) -> None:
    source = _source_rows([*rows, _SYSTEM_ROW])
    set_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    insert_order, ending_order = _M._assert_layout([*rows, _SYSTEM_ROW], lane)

    built = _M._build_published_rows(source, lane, set_id, insert_order, ending_order)

    assert all(row["prompt_set_id"] == set_id for row in built)
    assert len({row["id"] for row in built}) == len(built)

    by_key = {(r["channel"], r["scope"], r["slot"], r["variant"]): r for r in built}
    for key in _added_keys(lane):
        row = by_key.pop(key)
        assert (row["body"], row["conditional"]) == _EXPECTED_NEW[key], key
        if key == _NOTE_KEY:
            assert row["order"] == insert_order
        elif key == _GEN_SUMMARY_KEY:
            assert row["order"] == insert_order + 1
        elif key == _ENDING_SUMMARY_KEY:
            assert row["order"] == ending_order

    # 나머지 행은 order 외에 바이트 그대로이고, order는 generation `>= H`만 +2, ending `>= E`만 +1이다.
    for channel, scope, slot, variant, body, conditional, order in source:
        copied = by_key.pop((channel, scope, slot, variant))
        assert (copied["body"], copied["conditional"]) == (body, conditional)
        if channel == "generation" and order >= insert_order:
            expected_order = order + 2
        elif channel == "ending_judgment" and ending_order is not None and order >= ending_order:
            expected_order = order + 1
        else:
            expected_order = order
        assert copied["order"] == expected_order, slot
    assert by_key == {}

    built_sections = [PromptSection(**r) for r in built]
    source_sections = [
        PromptSection(channel=c, scope=s, slot=slot, variant=v, body=b, conditional=cond, order=o)
        for c, s, slot, v, b, cond, o in source
    ]
    _assert_render_order(built_sections, source_sections, lane)


def test_build_published_rows_ids_are_deterministic_per_lane() -> None:
    source = _source_rows(_CHARACTER_LAYOUT)
    set_id = uuid.uuid4()

    first = [r["id"] for r in _M._build_published_rows(source, "character", set_id, 7, None)]
    second = [r["id"] for r in _M._build_published_rows(source, "character", set_id, 7, None)]
    other_lane = [r["id"] for r in _M._build_published_rows(source, "story", set_id, 7, None)]

    assert first == second
    assert set(first).isdisjoint(other_lane)


# ---- 마이그레이션 뒤 DB 상태 — published 분기 ----------------------------------------------------

_LANES: list[PromptLane] = ["story", "character"]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    result = await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))
    return list(result.all())


def _keyed(sections: list[PromptSection]) -> dict[tuple[str, str, str, str], PromptSection]:
    return {(s.channel, s.scope, s.slot, s.variant): s for s in sections}


@pytest.mark.parametrize("lane", _LANES)
async def test_active_set_is_this_revisions_set_or_a_later_one_with_memory_rows(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """회귀 방지 — `published_at`이 원본보다 과거가 되면 새 세트가 활성이 되지 못하고, 골든은 옛
    세트로도 통과하므로 신호가 없다. 그래서 활성 세트를 id·게시 시각으로 직접 단언한다 — 이 리비전의 세트이거나,
    뒤 리비전이 이 세트를 복사해 만든 더 나중 세트다(story 레인은 미디어 북 칸 판정 리비전이 그렇다)."""
    latest, _ = await load_active_prompt_set(db_session, lane=lane)
    active = await db_session.get(PromptSet, _M.NEW_SET_IDS[lane])
    assert active is not None
    assert latest.published_at is not None and active.published_at is not None
    assert latest.id == active.id or latest.published_at > active.published_at
    assert active.note == _M._NOTE
    sections = await _sections_of(db_session, active.id)

    source_set = await db_session.get(PromptSet, _SOURCE_SET_IDS[lane])
    assert source_set is not None
    assert source_set.published_at is not None
    assert active.published_at > source_set.published_at
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(active, a) for a in labels] == [getattr(source_set, a) for a in labels]

    source_sections = await _sections_of(db_session, _SOURCE_SET_IDS[lane])
    new = _keyed(sections)
    old = _keyed(source_sections)
    assert set(new) - set(old) == _added_keys(lane)
    assert set(old) <= set(new)

    insert_order = old[("generation", "both", "history", "")].order
    assert (new[_NOTE_KEY].order, new[_GEN_SUMMARY_KEY].order) == (insert_order, insert_order + 1)
    for key in _added_keys(lane):
        assert (new[key].body, new[key].conditional) == _EXPECTED_NEW[key], key

    ending_order = old[("ending_judgment", "story", "history_header", "")].order if lane == "story" else None
    for key, old_section in old.items():
        new_section = new[key]
        assert (new_section.body, new_section.conditional) == (old_section.body, old_section.conditional), key
        if key[0] == "generation" and old_section.order >= insert_order:
            assert new_section.order == old_section.order + 2, key
        elif key[0] == "ending_judgment" and ending_order is not None and old_section.order >= ending_order:
            assert new_section.order == old_section.order + 1, key
        else:
            assert new_section.order == old_section.order, key

    _assert_render_order(sections, source_sections, lane)


async def test_versions_follow_global_sequence_story_first(db_session: AsyncSession) -> None:
    """`max(version::int)+1` 전 레인 대상, story 먼저. 테스트 DB의 이전 published 최대는 대화 프로필
    슬롯 마이그레이션의 character "3"이라 story "4", character "5"다."""
    versions = {lane: await db_session.get(PromptSet, _M.NEW_SET_IDS[lane]) for lane in _LANES}
    assert {lane: s.version if s else None for lane, s in versions.items()} == {"story": "4", "character": "5"}


# ---- `_patch_draft` ------------------------------------------------------------------------


async def _clone_source_set_as_draft(
    db_session: AsyncSession, lane: PromptLane, *, orders: dict[tuple[str, str], int] | None = None
) -> uuid.UUID:
    """이 리비전 이전 배치의 초안을 만든다 — 원본 레인 세트를 `status='draft'`로 복제하고, 필요하면
    어드민 위·아래 버튼처럼 order를 바꾼다."""
    source = await db_session.get(PromptSet, _SOURCE_SET_IDS[lane])
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
    for s in await _sections_of(db_session, source.id):
        db_session.add(
            PromptSection(
                prompt_set_id=draft.id,
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
    return draft.id


async def _snapshot(
    db_session: AsyncSession, set_id: uuid.UUID
) -> dict[tuple[str, str, str, str], tuple[str, bool, int]]:
    db_session.expire_all()
    return {key: (s.body, s.conditional, s.order) for key, s in _keyed(await _sections_of(db_session, set_id)).items()}


@pytest.mark.parametrize(
    ("lane", "orders"),
    [
        pytest.param("story", None, id="story"),
        pytest.param("story", _STORY_SWAPPED, id="story-swapped"),
        pytest.param("character", None, id="character"),
        pytest.param("character", _CHARACTER_SWAPPED, id="character-swapped"),
    ],
)
async def test_patch_draft_adds_memory_rows_in_place_and_draft_then_publishes(
    db_session: AsyncSession, lane: PromptLane, orders: dict[tuple[str, str], int] | None
) -> None:
    draft_id = await _clone_source_set_as_draft(db_session, lane, orders=orders)
    before = await _snapshot(db_session, draft_id)
    before_sections = [
        PromptSection(channel=c, scope=s, slot=slot, variant=v, body=b, conditional=cond, order=o)
        for (c, s, slot, v), (b, cond, o) in before.items()
    ]
    insert_order = before[("generation", "both", "history", "")][2]
    ending_key = ("ending_judgment", "story", "history_header", "")
    ending_order = before[ending_key][2] if lane == "story" else None

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft, lane) is True

    after = await _snapshot(db_session, draft_id)
    assert after.pop(_NOTE_KEY) == (*_EXPECTED_NEW[_NOTE_KEY], insert_order)
    assert after.pop(_GEN_SUMMARY_KEY) == (*_EXPECTED_NEW[_GEN_SUMMARY_KEY], insert_order + 1)
    if ending_order is not None:
        assert after.pop(_ENDING_SUMMARY_KEY) == (*_EXPECTED_NEW[_ENDING_SUMMARY_KEY], ending_order)
    for order, key in enumerate(_CHANNEL_KEYS, start=1):
        assert after.pop(key) == (*_EXPECTED_NEW[key], order)
    assert set(after) == set(before)
    for key, (body, conditional, order) in before.items():
        if key[0] == "generation" and order >= insert_order:
            expected_order = order + 2
        elif key[0] == "ending_judgment" and ending_order is not None and order >= ending_order:
            expected_order = order + 1
        else:
            expected_order = order
        assert after[key] == (body, conditional, expected_order), key

    sections = await _sections_of(db_session, draft_id)
    _assert_render_order(sections, before_sections, lane)

    # 게시 게이트 전체를 그대로 태운다 — 슬롯 집합·허용 플레이스홀더·order 중복 검사는 코드 표
    # (`_EXPECTED_ROWS_BY_LANE`·`ALLOWED_PLACEHOLDERS`)가 이 마이그레이션과 같이 갔는지도 함께 본다. 코드 표는
    # 지금 head 기준이라, 체인이 실제로 하듯 뒤 리비전(story 레인 미디어 북 칸 판정 행)의 초안 패치도 거친다.
    if lane == "story":
        assert await connection.run_sync(_NEXT_STORY_MIGRATION._patch_draft) is True
        assert await connection.run_sync(_SITUATION_NOTES_MIGRATION._patch_draft) is True
    assert await connection.run_sync(_USER_NAME_MIGRATION._patch_draft, lane) is True
    assert await connection.run_sync(_NOVELIZE_MIGRATION._patch_draft, lane) is True
    db_session.expire_all()  # 원시 SQL이 민 order를 식별자 맵의 옛 값이 가리지 않게
    draft = await db_session.get(PromptSet, draft_id)
    assert draft is not None
    _validate_prompt_draft_for_publish(draft, await _sections_of(db_session, draft_id), lane=lane)


@pytest.mark.parametrize("lane", _LANES)
async def test_patch_draft_without_draft_returns_false_and_changes_nothing(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    async def all_sections() -> set[tuple[uuid.UUID, int]]:
        db_session.expire_all()
        return {(s.id, s.order) for s in (await db_session.scalars(sa.select(PromptSection))).all()}

    before = await all_sections()

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft, lane) is False

    assert await all_sections() == before


async def test_patch_draft_raises_on_draft_layout_it_cannot_satisfy(db_session: AsyncSession) -> None:
    """초안에도 `_assert_layout`을 **초안 자신의 배치로** 적용한다."""
    await _clone_source_set_as_draft(
        db_session,
        "story",
        orders={("generation", "user_persona"): 8, ("generation", "keyword_notes"): 6},
    )

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="user_persona"):
        await connection.run_sync(_M._patch_draft, "story")


# ---- 값이 빈 방은 이 리비전 이전 세트와 렌더가 같다 ------------------------------------------------


@pytest.mark.parametrize(
    ("lane", "channel"),
    [
        pytest.param("story", "generation", id="story-generation"),
        pytest.param("story", "ending_judgment", id="story-ending"),
        pytest.param("character", "generation", id="character-generation"),
    ],
)
async def test_empty_memory_renders_same_as_source_set(
    db_session: AsyncSession, lane: PromptLane, channel: str
) -> None:
    """마이그레이션 쪽의 바이트 동일 — 원본 세트와 새 세트를 같은 값(기억은 빈 값, 나머지는 채움)으로
    렌더한 결과가 같다. 렌더러 쪽 바이트 동일은 골든(`test_prompt_goldens.py`)이 이관 전 코드가 뜬
    파일로 본다."""
    _, new_sections = await load_active_prompt_set(db_session, lane=lane)
    old_sections = await _sections_of(db_session, _SOURCE_SET_IDS[lane])
    values = {
        name: f"<{name}>"
        for section in old_sections
        for _, name, _, _ in Formatter().parse(section.body)
        if name
    }
    values |= {"memory_note": "", "memory_summary": ""}

    for variant in ("", "custom"):
        rendered = [
            render_prompt_channel(sections, channel=channel, scope=lane, variant=variant, values=values)
            for sections in (old_sections, new_sections)
        ]
        assert rendered[0] == rendered[1]
        assert rendered[0]  # 빈 문자열끼리의 비교가 아니다
