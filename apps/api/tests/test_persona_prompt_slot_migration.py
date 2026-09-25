"""대화 프로필 슬롯(`generation/user_persona`)을
넣는 데이터 마이그레이션 `b72c33c70240`(이하 M2)의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`tests/test_clover_lots.py`의 `_load_migration`과 같은
방식). 세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로:

- ③ published 분기는 "마이그레이션 뒤 DB 상태"를 단언한다 — 리터럴 PK가 이미 있어 다시
  실행하면 충돌한다.
- ④·⑥ 순수 함수(`_assert_generation_layout`·`_build_published_rows`)는 직접 부른다.
- ⑤·⑥ `_patch_draft`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 부른다.
  테스트 DB의 활성 세트에는 이미 슬롯이 있으므로, M2 이전 배치의 초안은 `a69cbd40dec8`이
  심은 레인 세트(M2가 복사한 원본)를 `status='draft'`로 복제해 만든다.
"""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, load_active_prompt_set, select_sections_for_render
from api.db.models.prompt import PromptSection, PromptSet

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M2 = _load("b72c33c70240")
# M2가 복사한 원본(M2 이전 레인 세트) — 테스트 DB에서는 `a69cbd40dec8`이 심은 세트다.
_SEED_SET_IDS: dict[str, uuid.UUID] = _load("a69cbd40dec8").NEW_SET_IDS

_PERSONA_KEY = ("generation", "both", "user_persona", "")

# 확정 문안을 글자 그대로 옮겼다. 마이그레이션의
# 상수와 비교하는 대신 여기 따로 적는 이유: 상수끼리 비교하면 상수가 틀려도 통과한다.
_CONFIRMED_BODY = (
    "[사용자 정보]\n"
    "아래는 사용자가 스스로 정한 자기 설정이다. 작품 설정이 사용자에게 정해 둔 역할이나 세계관이 "
    "있으면 그것이 우선하고, 이 정보는 그 위에 이름·성별·특징을 덧붙이는 참고로만 쓴다.\n"
    "{user_persona}"
)

# 시드 배치 — `(channel, scope, slot, variant, order)`.
_STORY_SEED_GENERATION: list[tuple[str, str, str, str, int]] = [
    ("generation", "story", "base_content", "", 1),
    ("generation", "story", "base_content", "custom", 1),
    ("generation", "story", "rules", "", 2),
    ("generation", "story", "user_goal", "", 3),
    ("generation", "story", "development_examples", "", 4),
    ("generation", "story", "prologue", "", 5),
    ("generation", "both", "history", "", 6),
    ("generation", "story", "keyword_notes", "", 7),
    ("generation", "story", "shortcut_prompt", "", 8),
    ("generation", "both", "final_frame", "", 9),
]
_CHARACTER_SEED_GENERATION: list[tuple[str, str, str, str, int]] = [
    ("generation", "character", "character_prompt", "", 1),
    ("generation", "character", "example_dialogues", "", 2),
    ("generation", "both", "history", "", 6),
    ("generation", "both", "final_frame", "", 9),
]
# generation 밖의 행은 배치 검사가 보지 않아야 한다 — 같은 order 6을 일부러 준다.
_SYSTEM_ROW = ("system", "both", "rule_rating", "", 6)


def _with_orders(
    rows: list[tuple[str, str, str, str, int]], orders: dict[str, int]
) -> list[tuple[str, str, str, str, int]]:
    return [(c, s, slot, v, orders.get(slot, o)) for c, s, slot, v, o in rows]


# ---- ④ `_assert_generation_layout` — 가정이 맞으면 H, 어긋나면 raise -------------------------


@pytest.mark.parametrize(
    ("lane", "rows"),
    [
        pytest.param("story", _STORY_SEED_GENERATION, id="story"),
        pytest.param("character", _CHARACTER_SEED_GENERATION, id="character"),
    ],
)
def test_assert_layout_returns_history_order_for_seed_layout(
    lane: str, rows: list[tuple[str, str, str, str, int]]
) -> None:
    assert _M2._assert_generation_layout([*rows, _SYSTEM_ROW], lane) == 6


def test_assert_layout_follows_history_when_operator_moved_it() -> None:
    """H는 고정 숫자가 아니라 `history`의 현재 order다."""
    rows = _with_orders(_STORY_SEED_GENERATION, {"history": 7, "keyword_notes": 6})

    assert _M2._assert_generation_layout(rows, "story") == 7


def test_assert_layout_raises_when_a_slot_is_missing() -> None:
    rows = [r for r in _STORY_SEED_GENERATION if r[2] != "keyword_notes"]

    with pytest.raises(RuntimeError, match="story"):
        _M2._assert_generation_layout(rows, "story")


def test_assert_layout_raises_when_an_unknown_slot_is_present() -> None:
    rows = [*_CHARACTER_SEED_GENERATION, ("generation", "character", "surprise", "", 10)]

    with pytest.raises(RuntimeError, match="character"):
        _M2._assert_generation_layout(rows, "character")


def test_assert_layout_raises_when_user_persona_already_exists() -> None:
    rows = [*_CHARACTER_SEED_GENERATION, ("generation", "both", "user_persona", "", 5)]

    # 슬롯 집합 검사도 "잉여"로 raise하므로 메시지로 전용 검사가 먼저 걸렸는지 가른다.
    with pytest.raises(RuntimeError, match="user_persona 행이 이미 있다"):
        _M2._assert_generation_layout(rows, "character")


def test_assert_layout_raises_when_story_prologue_is_after_history() -> None:
    """슬롯 위치 규칙 "prologue 뒤, history 앞"을 동시에 만족할 수 없다 — 조용히 한쪽을 고르지
    않고 멈춘다."""
    rows = _with_orders(_STORY_SEED_GENERATION, {"prologue": 6, "history": 5})

    with pytest.raises(RuntimeError, match="prologue"):
        _M2._assert_generation_layout(rows, "story")


# ---- ⑥ `_build_published_rows` — 재배치된 배치에서도 `history` 바로 앞 ---------------------


def _source_rows(
    rows: list[tuple[str, str, str, str, int]],
) -> list[tuple[str, str, str, str, str, bool, int]]:
    """`(channel, scope, slot, variant, body, conditional, order)` — body·conditional은 행마다
    다르게 줘서 복사 중에 뒤섞이면 드러나게 한다."""
    return [(c, s, slot, v, f"body:{slot}:{v}", i % 2 == 0, o) for i, (c, s, slot, v, o) in enumerate(rows)]


def _render_slots(sections: list[PromptSection], *, scope: str, variant: str = "") -> list[str]:
    return [s.slot for s in select_sections_for_render(sections, channel="generation", scope=scope, variant=variant)]


@pytest.mark.parametrize(
    ("lane", "rows"),
    [
        pytest.param("story", _STORY_SEED_GENERATION, id="story-seed"),
        pytest.param(
            "story",
            _with_orders(
                _STORY_SEED_GENERATION,
                {"development_examples": 5, "prologue": 4, "history": 7, "keyword_notes": 6},
            ),
            id="story-swapped",
        ),
        pytest.param("character", _CHARACTER_SEED_GENERATION, id="character-seed"),
        pytest.param(
            "character",
            _with_orders(_CHARACTER_SEED_GENERATION, {"history": 9, "final_frame": 6}),
            id="character-swapped",
        ),
    ],
)
def test_build_published_rows_inserts_persona_right_before_history(
    lane: str, rows: list[tuple[str, str, str, str, int]]
) -> None:
    source = _source_rows([*rows, _SYSTEM_ROW])
    set_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    insert_order = _M2._assert_generation_layout([*rows, _SYSTEM_ROW], lane)

    built = _M2._build_published_rows(source, lane, set_id, insert_order)

    assert len(built) == len(source) + 1
    assert all(row["prompt_set_id"] == set_id for row in built)
    assert len({row["id"] for row in built}) == len(built)

    by_key = {(r["channel"], r["scope"], r["slot"], r["variant"]): r for r in built}
    persona = by_key.pop(_PERSONA_KEY)
    assert (persona["body"], persona["conditional"], persona["order"]) == (_CONFIRMED_BODY, True, insert_order)

    # 나머지 행은 order 외에 바이트 그대로이고, order는 generation에서 `>= H`만 +1이다.
    for channel, scope, slot, variant, body, conditional, order in source:
        copied = by_key.pop((channel, scope, slot, variant))
        assert (copied["body"], copied["conditional"]) == (body, conditional)
        shifted = channel == "generation" and order >= insert_order
        assert copied["order"] == (order + 1 if shifted else order), slot
    assert by_key == {}

    # 렌더 선택 결과에서 `history` 바로 앞이고, 나머지 상대 순서는 입력과 같다.
    built_sections = [PromptSection(**r) for r in built]
    source_sections = [
        PromptSection(channel=c, scope=s, slot=slot, variant=v, body=b, conditional=cond, order=o)
        for c, s, slot, v, b, cond, o in source
    ]
    after_slots = _render_slots(built_sections, scope=lane)
    assert after_slots[after_slots.index("user_persona") + 1] == "history"
    assert [s for s in after_slots if s != "user_persona"] == _render_slots(source_sections, scope=lane)


def test_build_published_rows_ids_are_deterministic_per_lane() -> None:
    """리터럴을 나열할 수 없는 섹션 PK는 uuid5로 결정적으로 만든다 — 같은
    입력이면 같은 id, 레인이 다르면 다른 id."""
    source = _source_rows(_CHARACTER_SEED_GENERATION)
    set_id = uuid.uuid4()

    first = [r["id"] for r in _M2._build_published_rows(source, "character", set_id, 6)]
    second = [r["id"] for r in _M2._build_published_rows(source, "character", set_id, 6)]
    other_lane = [r["id"] for r in _M2._build_published_rows(source, "story", set_id, 6)]

    assert first == second
    assert set(first).isdisjoint(other_lane)


# ---- ③ 마이그레이션 뒤 DB 상태 — published 분기 ------------------------------------------------

_LANES: list[PromptLane] = ["story", "character"]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    result = await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))
    return list(result.all())


def _keyed(sections: list[PromptSection]) -> dict[tuple[str, str, str, str], PromptSection]:
    return {(s.channel, s.scope, s.slot, s.variant): s for s in sections}


@pytest.mark.parametrize("lane", _LANES)
async def test_active_set_is_the_m2_set_with_one_persona_row_before_history(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """회귀 방지 — `published_at`이 원본보다 과거가 되면 M2 세트가 활성이 되지
    못하고, 골든은 옛 세트로도 통과하므로 신호가 없다. 그래서 id를 직접 단언한다."""
    active, sections = await load_active_prompt_set(db_session, lane=lane)
    assert active.id == _M2.NEW_SET_IDS[lane]

    source_set = await db_session.get(PromptSet, _SEED_SET_IDS[lane])
    assert source_set is not None
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(active, a) for a in labels] == [getattr(source_set, a) for a in labels]
    assert active.note == "대화 프로필 슬롯 추가 (persona-goal-prompt.md UP-13)"

    new = _keyed(sections)
    old = _keyed(await _sections_of(db_session, _SEED_SET_IDS[lane]))
    assert set(new) - set(old) == {_PERSONA_KEY}
    assert set(old) <= set(new)

    insert_order = old[("generation", "both", "history", "")].order
    persona = new[_PERSONA_KEY]
    assert (persona.body, persona.conditional, persona.order) == (_CONFIRMED_BODY, True, insert_order)

    for key, old_section in old.items():
        new_section = new[key]
        assert (new_section.body, new_section.conditional) == (old_section.body, old_section.conditional), key
        shifted = key[0] == "generation" and old_section.order >= insert_order
        assert new_section.order == old_section.order + (1 if shifted else 0), key

    slots = _render_slots(sections, scope=lane)
    assert slots[slots.index("user_persona") + 1] == "history"


async def test_m2_versions_follow_global_sequence_story_first(db_session: AsyncSession) -> None:
    """`max(version::int)+1` 전 레인 대상, story 먼저. 테스트 DB의 기존
    published는 전부 "1"이라 story "2", character "3"이다."""
    versions = {
        lane: (await db_session.get(PromptSet, _M2.NEW_SET_IDS[lane])) for lane in ("story", "character")
    }
    assert {lane: s.version if s else None for lane, s in versions.items()} == {"story": "2", "character": "3"}


# ---- ⑤·⑥ `_patch_draft` --------------------------------------------------------


async def _clone_seed_set_as_draft(
    db_session: AsyncSession, lane: PromptLane, *, generation_orders: dict[str, int] | None = None
) -> uuid.UUID:
    """M2 이전 배치의 초안을 만든다 — 원본 레인 세트를 `status='draft'`로 복제하고, 필요하면
    어드민 위·아래 버튼처럼 generation 행의 order를 바꾼다."""
    source = await db_session.get(PromptSet, _SEED_SET_IDS[lane])
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
    orders = generation_orders or {}
    for s in await _sections_of(db_session, source.id):
        order = orders.get(s.slot, s.order) if s.channel == "generation" else s.order
        db_session.add(
            PromptSection(
                prompt_set_id=draft.id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=s.body,
                conditional=s.conditional,
                order=order,
            )
        )
    await db_session.flush()
    return draft.id


async def _snapshot(db_session: AsyncSession, set_id: uuid.UUID) -> dict[tuple[str, str, str, str], tuple[str, bool, int]]:
    db_session.expire_all()
    return {key: (s.body, s.conditional, s.order) for key, s in _keyed(await _sections_of(db_session, set_id)).items()}


@pytest.mark.parametrize(
    ("lane", "generation_orders"),
    [
        pytest.param("story", None, id="story-seed"),
        pytest.param(
            "story",
            {"development_examples": 5, "prologue": 4, "history": 7, "keyword_notes": 6},
            id="story-swapped",
        ),
        pytest.param("character", None, id="character-seed"),
        pytest.param("character", {"history": 9, "final_frame": 6}, id="character-swapped"),
    ],
)
async def test_patch_draft_adds_persona_row_in_place_and_draft_then_publishes(
    db_session: AsyncSession, lane: PromptLane, generation_orders: dict[str, int] | None
) -> None:
    draft_id = await _clone_seed_set_as_draft(db_session, lane, generation_orders=generation_orders)
    before = await _snapshot(db_session, draft_id)
    before_slots = _render_slots(await _sections_of(db_session, draft_id), scope=lane)
    insert_order = before[("generation", "both", "history", "")][2]

    connection = await db_session.connection()
    assert await connection.run_sync(_M2._patch_draft, lane) is True

    after = await _snapshot(db_session, draft_id)
    assert after.pop(_PERSONA_KEY) == (_CONFIRMED_BODY, True, insert_order)
    assert set(after) == set(before)
    for key, (body, conditional, order) in before.items():
        shifted = key[0] == "generation" and order >= insert_order
        assert after[key] == (body, conditional, order + 1 if shifted else order), key

    sections = await _sections_of(db_session, draft_id)
    after_slots = _render_slots(sections, scope=lane)
    assert after_slots[after_slots.index("user_persona") + 1] == "history"
    assert [s for s in after_slots if s != "user_persona"] == before_slots

    # 게시 게이트 전체를 그대로 태운다 — 슬롯 집합·허용 플레이스홀더 검사는 코드 표
    # (`_EXPECTED_ROWS_BY_LANE`·`ALLOWED_PLACEHOLDERS`)가 M2와 같이 갔는지도 함께 본다.
    draft = await db_session.get(PromptSet, draft_id)
    assert draft is not None
    _validate_prompt_draft_for_publish(draft, sections, lane=lane)


@pytest.mark.parametrize("lane", _LANES)
async def test_patch_draft_without_draft_returns_false_and_changes_nothing(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    async def all_sections() -> set[tuple[uuid.UUID, int]]:
        db_session.expire_all()
        return {(s.id, s.order) for s in (await db_session.scalars(sa.select(PromptSection))).all()}

    before = await all_sections()

    connection = await db_session.connection()
    assert await connection.run_sync(_M2._patch_draft, lane) is False

    assert await all_sections() == before


async def test_patch_draft_raises_on_draft_layout_it_cannot_satisfy(db_session: AsyncSession) -> None:
    """초안에도 `_assert_generation_layout`을 **초안 자신의 배치로** 적용한다."""
    await _clone_seed_set_as_draft(db_session, "story", generation_orders={"prologue": 6, "history": 5})

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="prologue"):
        await connection.run_sync(_M2._patch_draft, "story")
