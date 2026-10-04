"""story 레인 generation 에 상황 노트 행(`situation_notes`, conditional)을 넣는 데이터 마이그레이션 `2417f5829bb1`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_memory_prompt_slot_migration.py`와 같은 방식). 세션 스코프
스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 published 분기는 "마이그레이션 뒤 DB 상태"를
단언하고, 순수 함수·`_patch_draft`·`_delete_draft_row`는 직접 부른다(뒤 둘은 테스트마다 롤백되는
`db_session`의 커넥션에 `run_sync`로).

character 레인에도 generation channel 이 있다 — 이 리비전의 어떤 쿼리도 그 레인의 행을 건드리지 않아야 한다."""

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


_M = _load("2417f5829bb1")
# 이 리비전이 복사한 원본(이전 story 활성 세트) — 테스트 DB에서는 미디어 북 칸 판정 리비전의 세트다.
_PREVIOUS_STORY_SET_ID: uuid.UUID = _load("2519dde454e0").NEW_SET_ID
# 손대지 않아야 하는 character 활성 세트 — 테스트 DB에서는 채팅방 기억 행을 넣은 리비전의 세트다.
_CHARACTER_SET_ID: uuid.UUID = _load("c328445d4c2d").NEW_SET_IDS["character"]

_NEW_KEY = ("generation", "story", "situation_notes", "")

# 운영 story 활성 세트의 generation 배치(2026-10-03 읽기 전용 조회와 같다) — `(channel, scope, slot, variant, order)`.
_STORY_LAYOUT: list[tuple[str, str, str, str, int]] = [
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
    ("generation", "story", "shortcut_prompt", "", 11),
    ("generation", "both", "final_frame", "", 12),
]
# 배치 검사가 보지 않는 채널의 행 — 기준 뒤 order 를 일부러 준다(밀리면 안 된다).
_OTHER_CHANNEL_ROW = ("stat_judgment", "story", "turn_context", "", 11)
# 운영자가 위·아래 버튼으로 맞바꾼 배치 — 키워드북을 대화 기록 앞으로 올렸다.
_SWAPPED = {"history": 10, "keyword_notes": 9}


def _with_orders(
    rows: list[tuple[str, str, str, str, int]], orders: dict[str, int]
) -> list[tuple[str, str, str, str, int]]:
    return [(c, s, slot, v, orders.get(slot, o)) for c, s, slot, v, o in rows]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[tuple[str, str, str, str], tuple[str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _shifted(
    before: dict[tuple[str, str, str, str], tuple[str, bool, int]], anchor_order: int
) -> dict[tuple[str, str, str, str], tuple[str, bool, int]]:
    """기준 뒤 generation 행만 +1 한 기대값."""
    return {
        key: (body, conditional, order + 1 if key[0] == "generation" and order > anchor_order else order)
        for key, (body, conditional, order) in before.items()
    }


def _generation_slots(sections: list[PromptSection]) -> list[str]:
    return [
        s.slot
        for s in sorted(sections, key=lambda s: s.order)
        if s.channel == "generation" and s.variant == "" and s.scope in ("story", "both")
    ]


# ---- 문안 성질 --------------------------------------------------------------------------------


def test_body_uses_exactly_the_allowed_placeholder() -> None:
    """conditional 행은 플레이스홀더가 있어야 빈 값에서 드롭되고, 허용 밖 이름이 있으면 렌더가 실패한다."""
    names = [name for _, name, _, _ in Formatter().parse(_M.SITUATION_NOTES_BODY) if name]
    assert names == ["situation_note_lines"]
    assert set(names) == ALLOWED_PLACEHOLDERS[("generation", "situation_notes")]


def test_body_frames_the_notes_as_facts_of_the_story_world() -> None:
    assert _M.SITUATION_NOTES_BODY == (
        "[현재 상황]\n"
        "아래는 지금 이야기 세계에서 사실인 상황이다. 이번 장면은 이 사실과 어긋나지 않게 쓴다.\n"
        "{situation_note_lines}"
    )


# ---- `_assert_layout` --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        pytest.param(_STORY_LAYOUT, 10, id="prod"),
        pytest.param(_with_orders(_STORY_LAYOUT, _SWAPPED), 9, id="swapped"),
    ],
)
def test_assert_layout_returns_the_keyword_notes_order(rows: list[tuple[str, str, str, str, int]], expected: int) -> None:
    assert _M._assert_layout([*rows, _OTHER_CHANNEL_ROW]) == expected


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([*_STORY_LAYOUT, ("generation", "story", "situation_notes", "", 11)], id="already-applied"),
        pytest.param([r for r in _STORY_LAYOUT if r[2] != "keyword_notes"], id="missing-anchor"),
        pytest.param([*_STORY_LAYOUT, ("generation", "character", "character_prompt", "", 1)], id="unknown-slot"),
    ],
)
def test_assert_layout_raises_on_unexpected_layout(rows: list[tuple[str, str, str, str, int]]) -> None:
    with pytest.raises(RuntimeError, match="generation 슬롯 집합"):
        _M._assert_layout(rows)


# ---- `_build_published_rows` -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows",
    [pytest.param(_STORY_LAYOUT, id="prod"), pytest.param(_with_orders(_STORY_LAYOUT, _SWAPPED), id="swapped")],
)
def test_build_published_rows_puts_the_row_right_after_keyword_notes(rows: list[tuple[str, str, str, str, int]]) -> None:
    layout = [*rows, _OTHER_CHANNEL_ROW]
    # body·conditional 은 행마다 달리 줘서 복사 중에 뒤섞이면 드러나게 한다.
    source = [(c, s, slot, v, f"body:{c}:{slot}:{v}", i % 2 == 0, o) for i, (c, s, slot, v, o) in enumerate(layout)]
    set_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    anchor_order = _M._assert_layout(layout)

    built = _M._build_published_rows(source, set_id, anchor_order)

    assert all(row["prompt_set_id"] == set_id for row in built)
    assert len({row["id"] for row in built}) == len(built)
    by_key = {(r["channel"], r["scope"], r["slot"], r["variant"]): (r["body"], r["conditional"], r["order"]) for r in built}
    assert by_key.pop(_NEW_KEY) == (_M.SITUATION_NOTES_BODY, True, anchor_order + 1)
    assert by_key == _shifted({(c, s, slot, v): (b, cond, o) for c, s, slot, v, b, cond, o in source}, anchor_order)

    sections = [PromptSection(**r) for r in built]
    slots = _generation_slots(sections)
    assert slots[slots.index("keyword_notes") + 1] == "situation_notes"


# ---- 마이그레이션 뒤 DB 상태 — published 분기 ----------------------------------------------------


async def test_active_story_set_is_this_revisions_set_with_the_new_row(db_session: AsyncSession) -> None:
    """회귀 방지 — `published_at`이 원본보다 과거가 되면 새 세트가 활성이 되지 못하고, 골든은 옛 세트로도 통과하므로
    신호가 없다. 그래서 활성 세트를 id 로 직접 단언한다. 다른 행은 원본과 바이트까지 같고 기준 뒤 generation 행만
    한 칸 밀린다."""
    active, sections = await load_active_prompt_set(db_session, lane="story")
    assert active.id == _M.NEW_SET_ID
    assert active.note == _M._NOTE
    # 이전 published 최대는 발행 심사 이미지 전용 리비전의 "8"이다.
    assert active.version == "9"

    source_set = await db_session.get(PromptSet, _PREVIOUS_STORY_SET_ID)
    assert source_set is not None and source_set.published_at is not None and active.published_at is not None
    assert active.published_at > source_set.published_at
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(active, a) for a in labels] == [getattr(source_set, a) for a in labels]

    new = _keyed(sections)
    old = _keyed(await _sections_of(db_session, _PREVIOUS_STORY_SET_ID))
    anchor_order = old[("generation", "story", "keyword_notes", "")][2]
    assert new.pop(_NEW_KEY) == (_M.SITUATION_NOTES_BODY, True, anchor_order + 1)
    assert new == _shifted(old, anchor_order)


async def test_character_lane_is_untouched(db_session: AsyncSession) -> None:
    active, sections = await load_active_prompt_set(db_session, lane="character")
    assert active.id == _CHARACTER_SET_ID
    assert all(s.slot != "situation_notes" for s in sections)


@pytest.mark.parametrize("variant", ["", "custom"])
async def test_story_generation_drops_the_section_when_no_note_is_true(db_session: AsyncSession, variant: str) -> None:
    """노트가 없는 방은 이 리비전 전 세트와 렌더가 바이트까지 같다. 노트가 있으면 키워드북 바로 뒤에 실린다."""
    old_sections = await _sections_of(db_session, _PREVIOUS_STORY_SET_ID)
    values = {
        name: f"<{name}>" for section in old_sections for _, name, _, _ in Formatter().parse(section.body) if name
    }

    def render(sections: list[PromptSection], situation: str) -> str:
        return render_prompt_channel(
            sections,
            channel="generation",
            scope="story",
            variant=variant,
            values={**values, "situation_note_lines": situation},
        )

    before = render(old_sections, "")
    assert before  # 빈 문자열끼리의 비교가 아니다
    _, new_sections = await load_active_prompt_set(db_session, lane="story")
    assert render(new_sections, "") == before

    with_note = render(new_sections, "<노트>")
    section = _M.SITUATION_NOTES_BODY.format(situation_note_lines="<노트>")
    assert section in with_note
    assert with_note.index("<keyword_note_lines>") < with_note.index(section) < with_note.index("<shortcut_prompt>")


# ---- `_patch_draft` ------------------------------------------------------------------------


async def _clone_as_draft(
    db_session: AsyncSession, set_id: uuid.UUID, lane: PromptLane, *, orders: dict[str, int] | None = None
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
                order=(orders or {}).get(s.slot, s.order) if s.channel == "generation" else s.order,
            )
        )
    await db_session.flush()
    return draft_id


@pytest.mark.parametrize("orders", [pytest.param(None, id="as-published"), pytest.param(_SWAPPED, id="swapped")])
async def test_patch_draft_adds_the_row_in_place_and_draft_then_publishes(
    db_session: AsyncSession, orders: dict[str, int] | None
) -> None:
    """운영 story 레인에는 초안이 있다 — 이 분기가 실제로 탄다. 이 리비전 이전 배치의 초안(이전 활성 세트 복제)에
    행이 초안 **자신의** 키워드북 바로 뒤에 더해지고, 게시 게이트 전체(head 코드 표)를 통과한다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_STORY_SET_ID, "story", orders=orders)
    before = _keyed(await _sections_of(db_session, draft_id))
    anchor_order = before[("generation", "story", "keyword_notes", "")][2]

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is True

    sections = await _sections_of(db_session, draft_id)
    after = _keyed(sections)
    assert after.pop(_NEW_KEY) == (_M.SITUATION_NOTES_BODY, True, anchor_order + 1)
    assert after == _shifted(before, anchor_order)
    slots = _generation_slots(sections)
    assert slots[slots.index("keyword_notes") + 1] == "situation_notes"

    draft = await db_session.get(PromptSet, draft_id)
    assert draft is not None
    _validate_prompt_draft_for_publish(draft, sections, lane="story")


async def test_patch_draft_leaves_character_draft_alone(db_session: AsyncSession) -> None:
    """character 초안만 있으면 story 패치는 할 일이 없다 — 레인 조건이 빠지면 character 초안의 order 가 밀린다."""
    character_draft = await _clone_as_draft(db_session, _CHARACTER_SET_ID, "character")
    before = _keyed(await _sections_of(db_session, character_draft))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is False

    assert _keyed(await _sections_of(db_session, character_draft)) == before


async def test_patch_draft_raises_when_story_draft_already_has_the_row(db_session: AsyncSession) -> None:
    await _clone_as_draft(db_session, _M.NEW_SET_ID, "story")

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="잉여"):
        await connection.run_sync(_M._patch_draft)


# ---- 되돌리기 ------------------------------------------------------------------------------


async def test_delete_draft_row_restores_story_draft_and_leaves_others(db_session: AsyncSession) -> None:
    """되돌리기는 story 초안의 이 행만 지우고 밀었던 order 를 되돌린다 — character 초안과 published 세트는 남는다."""
    story_draft = await _clone_as_draft(db_session, _PREVIOUS_STORY_SET_ID, "story")
    character_draft = await _clone_as_draft(db_session, _CHARACTER_SET_ID, "character")
    story_original = _keyed(await _sections_of(db_session, story_draft))
    connection = await db_session.connection()
    await connection.run_sync(_M._patch_draft)
    character_before = _keyed(await _sections_of(db_session, character_draft))
    published_before = _keyed(await _sections_of(db_session, _M.NEW_SET_ID))

    await connection.run_sync(_M._delete_draft_row)

    assert _keyed(await _sections_of(db_session, story_draft)) == story_original
    assert _keyed(await _sections_of(db_session, character_draft)) == character_before
    assert _keyed(await _sections_of(db_session, _M.NEW_SET_ID)) == published_before
