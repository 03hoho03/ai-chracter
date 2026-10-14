"""장면 기억 추출 채널과 회상 슬롯을 채팅 두 레인의 여덟 체인에 심는 데이터 마이그레이션 `fc6f0e134782`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_prompt_judgment_chains_migration.py`와 같은 방식). 세션 스코프 스키마
(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, 순수 함수와
`seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로
직접 부른다(되돌리기 → 다시 올리기 왕복).

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행 + 새 행, `history` 뒤 생성 행만 order +1) — 마이그레이션의
`_with_new_rows` 로 기대값을 만들면 그 함수가 틀려도 테스트가 같이 틀린다."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _expected_slots, _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, load_active_prompt_set, select_sections_for_render
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import PromptSetModelId

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("fc6f0e134782")
_LANES: tuple[PromptLane, ...] = ("story", "character")
_WRITING_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")
_ALL_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [
    (lane, model) for lane in _LANES for model in (*_WRITING_MODELS, "haiku")
]
_WRITING_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [
    (lane, model) for lane in _LANES for model in _WRITING_MODELS
]
# 이 리비전 직전의 활성 세트 — 테스트 DB 에서 Gemini 는 story 가 스탯 규칙 판정 채널 리비전, character 가 소설화 채널
# 리비전의 세트이고, 다른 세 체인은 판정 문안 체인 리비전의 세트다(그 사이에 이 체인들에 게시한 리비전이 없다).
_judgment_chains = _load("1a843a0b2d8f").NEW_SET_IDS
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): _load("d9768bc0cfee").NEW_SET_ID,
    ("character", "gemini"): _load("3bb2cc159b6d").NEW_SET_IDS["character"],
    **_judgment_chains,
}

# 이 리비전 뒤에 여덟 체인에 관계·사실 기억 문안을 더한 새 세트를 게시하는 리비전. head 상태에서는 그 세트들이 활성이라,
# "이 리비전 직후 상태"를 보는 테스트는 그 리비전을 먼저 되돌린다(실제 downgrade 순서).
_LATER = _load("5cab2abe4e7b")

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_EPISODE_ROWS: dict[Key, Value] = {
    ("memory_episode", "both", "instruction", ""): (_M.EPISODE_INSTRUCTION_BODY, False, 0),
    ("memory_episode", "both", "user_name", ""): ("사용자의 이야기 속 이름: {user_name}", True, 1),
    ("memory_episode", "both", "previous_titles", ""): ("[앞 구간의 마지막 장면]\n{previous_titles}", True, 2),
    ("memory_episode", "both", "turn_context", ""): ("[접힌 대화]\n{turn_lines}", False, 3),
}
_RECALL_KEY: Key = ("generation", "both", "memory_recall", "")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")


def _ids(pairs: list[tuple[PromptLane, PromptSetModelId]]) -> list[str]:
    return [f"{lane}-{model}" for lane, model in pairs]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_after(before: dict[Key, Value], model: str) -> dict[Key, Value]:
    """이전 행 + 새 행. 글을 쓰는 체인은 `history` 뒤 생성 행을 하나씩 밀고 회상 슬롯을 바로 뒤에 둔다."""
    expected = dict(before)
    if model != "haiku":
        history_order = before[("generation", "both", "history", "")][2]
        for key, (body, conditional, order) in before.items():
            if key[0] == "generation" and order > history_order:
                expected[key] = (body, conditional, order + 1)
        expected[_RECALL_KEY] = (_M.RECALL_BODY, True, history_order + 1)
    return {**expected, **_EPISODE_ROWS}


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_LATER.delete_seeded_rows)


async def _active_id(db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane=lane, model=model))[0].id


async def _lane_only_active_id(db_session: AsyncSession, lane: PromptLane) -> uuid.UUID:
    connection = await db_session.connection()
    chosen: uuid.UUID = (await connection.execute(_M._LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane})).one().id
    return chosen


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


# ---- 순수 함수 -------------------------------------------------------------------------------

_GENERATION_ROWS: list[tuple[str, str, str, str, str, bool, int]] = [
    ("generation", "both", "memory_summary", "", "요약", True, 4),
    ("generation", "both", "history", "", "{history_lines}", True, 5),
    ("generation", "story", "keyword_notes", "", "키워드", True, 6),
    ("generation", "both", "final_frame", "", "프레임", False, 9),
]


def test_layout_returns_the_history_order_of_a_writing_chain() -> None:
    assert _M._assert_layout(_GENERATION_ROWS, model="sonnet", what="story/sonnet") == 5


def test_layout_of_a_judgment_only_chain_has_no_history_to_find() -> None:
    assert _M._assert_layout([("memory_summary", "both", "instruction", "", "요약", False, 1)], model="haiku", what="x") is None


@pytest.mark.parametrize("model", ["gemini", "haiku"])
def test_layout_with_an_episode_row_already_raises(model: str) -> None:
    rows = [*_GENERATION_ROWS, ("memory_episode", "both", "instruction", "", "지시", False, 0)]
    with pytest.raises(RuntimeError, match="memory_episode 채널 행이 이미 있다"):
        _M._assert_layout(rows, model=model, what=f"story/{model}")


def test_layout_with_a_recall_row_already_raises() -> None:
    rows = [*_GENERATION_ROWS, ("generation", "both", "memory_recall", "", "{memory_recall_lines}", True, 6)]
    with pytest.raises(RuntimeError, match="memory_recall 행이 이미 있다"):
        _M._assert_layout(rows, model="opus", what="character/opus")


@pytest.mark.parametrize("count", [0, 2])
def test_layout_needs_exactly_one_history_row(count: int) -> None:
    rows = [row for row in _GENERATION_ROWS if row[2] != "history"]
    rows += [("generation", scope, "history", "", "{history_lines}", True, 5) for scope in ("both", "story")[:count]]
    with pytest.raises(RuntimeError, match=f"정확히 하나가 아니다\\({count}개\\)"):
        _M._assert_layout(rows, model="gemini", what="story/gemini")


def test_new_rows_shift_only_generation_rows_after_history() -> None:
    """같은 order 를 쓰는 다른 채널 행과 `history` 앞 행은 그대로다."""
    other = ("memory_summary", "both", "instruction", "", "요약 지시", False, 7)
    rows = _M._with_new_rows([*_GENERATION_ROWS, other], 5)
    by_slot = {(row[0], row[2]): row[6] for row in rows}

    assert by_slot[("generation", "memory_summary")] == 4
    assert by_slot[("generation", "history")] == 5
    assert by_slot[("generation", "memory_recall")] == 6
    assert by_slot[("generation", "keyword_notes")] == 7
    assert by_slot[("generation", "final_frame")] == 10
    assert by_slot[("memory_summary", "instruction")] == 7


def test_seed_times_keep_gemini_last_and_others_strictly_inside() -> None:
    gemini_at = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
    earlier_now = gemini_at - timedelta(minutes=5)
    later_now = gemini_at + timedelta(minutes=5)

    assert _M._gemini_seed_time(gemini_at, earlier_now) == gemini_at + timedelta(seconds=1)
    assert _M._gemini_seed_time(gemini_at, later_now) == later_now
    chain_at = gemini_at - timedelta(seconds=1)
    assert _M._seed_time(chain_at, gemini_at + timedelta(seconds=1)) == gemini_at


@pytest.mark.parametrize(
    "gap", [pytest.param(timedelta(0), id="same"), pytest.param(timedelta(microseconds=1), id="too-narrow")]
)
def test_seed_time_raises_without_a_window(gap: timedelta) -> None:
    gemini_seed_at = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="시각"):
        _M._seed_time(gemini_seed_at - gap, gemini_seed_at)


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_each_chain_is_active_at_its_seeded_set(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


@pytest.mark.parametrize("lane", _LANES)
async def test_the_lane_only_select_picks_the_new_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """모델 열을 모르는 원시 SQL 이 레인만 보고 최신 게시본을 고를 때도 Gemini 세트를 집는다."""
    await _undo_later_revisions(db_session)
    assert await _lane_only_active_id(db_session, lane) == _M.NEW_SET_IDS[(lane, "gemini")]


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_new_set_is_the_previous_active_set_plus_the_new_rows(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이전 활성 세트의 모든 행이 바이트 그대로 옮겨지고(order 는 `history` 뒤 생성 행만 +1), 새 행만 더해진다. 라벨도
    이전 활성 세트 것이다."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    new = _keyed(new_sections)
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)]))

    assert new == _expected_after(before, model)
    assert (_RECALL_KEY in new) == (model != "haiku")
    assert all(section_id == _M._section_id("", lane, model, *key) for section_id, key in ids.items())

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    old_set = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    assert (this_set.lane, this_set.model, this_set.status) == (lane, model, "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(old_set, a) for a in _LABELS]


@pytest.mark.parametrize(
    ("lane", "follower"), [("story", "keyword_notes"), ("character", "final_frame")], ids=["story", "character"]
)
@pytest.mark.parametrize("model", _WRITING_MODELS)
async def test_recall_slot_renders_right_after_history(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId, follower: str
) -> None:
    """렌더 순서로 본 자리 — 스토리는 대화 기록과 키워드북 사이, 캐릭터는 대화 기록과 마지막 프레임 사이."""
    sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    slots = [s.slot for s in select_sections_for_render(sections, channel="generation", scope=lane)]

    at = slots.index("memory_recall")
    assert slots[at - 1 : at + 2] == ["history", "memory_recall", follower]


@pytest.mark.parametrize("lane", _LANES)
async def test_new_sets_are_published_in_the_window_of_both_active_rules(db_session: AsyncSession, lane: PromptLane) -> None:
    """새 Gemini 세트는 원본보다 나중, 다른 세 체인의 새 세트는 (그 체인 이전 활성, 새 Gemini) 의 중간값."""
    gemini_old = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, "gemini")])
    gemini_new = await _get_set(db_session, _M.NEW_SET_IDS[(lane, "gemini")])
    assert gemini_old.published_at is not None and gemini_new.published_at is not None
    assert gemini_new.published_at >= gemini_old.published_at + timedelta(seconds=1)
    for model in ("sonnet", "opus", "haiku"):
        old = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
        new = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
        assert old.published_at is not None and new.published_at is not None
        assert old.published_at < new.published_at < gemini_new.published_at
        assert new.published_at == old.published_at + (gemini_new.published_at - old.published_at) / 2


async def test_versions_continue_the_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    """전 레인·전 모델 published 최대 + 1 을 (story, character) × (gemini, sonnet, opus, haiku) 순서로."""
    order = [_M.NEW_SET_IDS[pair] for pair in _ALL_PAIRS]
    versions = [int((await _get_set(db_session, set_id)).version or "0") for set_id in order]
    others = (
        await db_session.scalars(
            sa.select(sa.cast(PromptSet.version, sa.Integer)).where(
                PromptSet.status == "published",
                PromptSet.id.not_in(order),
                PromptSet.id.not_in(list(_LATER.NEW_SET_IDS.values())),
            )
        )
    ).all()
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 관계·사실 기억 문안 리비전의 것뿐이다(그 세트들의 버전은 이 리비전보다 뒤다).
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


async def test_no_drafts_are_seeded(db_session: AsyncSession) -> None:
    drafts = (await db_session.scalars(sa.select(PromptSet.id).where(PromptSet.status == "draft"))).all()
    assert drafts == []


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_seeded_sets_pass_publish_validation_and_the_previous_sets_no_longer_do(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """게시 검증의 기대 집합과 시드가 맞물린다 — head 코드 표와의 차이는 뒤 리비전(관계·사실 기억 문안)이 더한 행뿐이고, 그
    행을 더한 뒤 리비전의 세트가 게시 검증을 통과한다. 새 행이 없는 이전 세트는 슬롯 집합 검사에 막힌다(이 리비전 이전 버전을
    복원해 게시할 수 없다)."""
    sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    later = {(row[0], row[1], row[2]) for row in _LATER.FACT_CHANNEL_ROWS}
    if model != "haiku":
        later.add(("generation", "both", _LATER.FACTS_SLOT))
    seeded = {(s.channel, s.scope, s.slot) for s in sections}
    expected = {(channel, scope, slot) for channel, slots in _expected_slots(lane, model).items() for scope, slot in slots}
    assert seeded | later == expected and not seeded & later
    later_set, later_sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    assert later_set.id == _LATER.NEW_SET_IDS[(lane, model)]
    _validate_prompt_draft_for_publish(later_set, later_sections, lane=lane, model=model)

    previous_sections = await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    with pytest.raises(HTTPException) as caught:
        _validate_prompt_draft_for_publish(previous, previous_sections, lane=lane, model=model)
    assert cast(dict[str, object], caught.value.detail)["rule"] == "R-1"


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


def _set(*, lane: str, model: str, status: str, published_at: datetime | None = None) -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version="9001" if status == "published" else None,
        status=status,
        lane=lane,
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
        published_at=published_at,
    )


async def _clone(
    db_session: AsyncSession,
    set_id: uuid.UUID,
    lane: str,
    model: str,
    *,
    published_at: datetime | None = None,
    edit: dict[Key, str] | None = None,
) -> uuid.UUID:
    """`set_id` 세트를 초안(또는 `published_at` 이 있으면 게시본)으로 복제한다. `edit` 는 그 키의 body 를 바꾼다."""
    source = await _get_set(db_session, set_id)
    copy = PromptSet(
        version=None if published_at is None else "9001",
        status="draft" if published_at is None else "published",
        lane=lane,
        model=model,
        user_label=source.user_label,
        story_assistant_label=source.story_assistant_label,
        story_example_label=source.story_example_label,
        character_assistant_label=source.character_assistant_label,
        published_at=published_at,
    )
    db_session.add(copy)
    await db_session.flush()
    copy_id = copy.id
    for s in await _sections_of(db_session, set_id):
        key = (s.channel, s.scope, s.slot, s.variant)
        db_session.add(
            PromptSection(
                prompt_set_id=copy_id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=(edit or {}).get(key, s.body),
                conditional=s.conditional,
                order=s.order,
            )
        )
    await db_session.flush()
    return copy_id


async def test_downgrade_then_upgrade_swaps_every_chain_back_and_forth(db_session: AsyncSession) -> None:
    """되돌리면 여덟 체인 활성이 이전 세트로, 레인만 보는 조회가 이전 Gemini 세트로 돌아가고, 다시 올리면 같은 리터럴
    세트가 활성이 된다."""
    connection = await db_session.connection()

    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _ALL_PAIRS:
        assert await _active_id(db_session, lane, model) == _PREVIOUS_SET_IDS[(lane, model)]
    for lane in _LANES:
        assert await _lane_only_active_id(db_session, lane) == _PREVIOUS_SET_IDS[(lane, "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.channel == "memory_episode")
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _ALL_PAIRS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


async def test_upgrade_copies_the_operators_edited_text_not_the_seed(db_session: AsyncSession) -> None:
    """운영 요약 문안처럼 어드민이 고쳐 게시한 문안이 활성이면 새 세트에 그 문안이 그대로 실린다 — 시드 상수로 만들면 조용히
    되돌아간다."""
    connection = await db_session.connection()
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    assert previous.published_at is not None
    instruction_key: Key = ("memory_summary", "both", "instruction", "")
    edited_body = "운영자가 고친 요약 지시문"
    edited_id = await _clone(
        db_session,
        _PREVIOUS_SET_IDS[("story", "gemini")],
        "story",
        "gemini",
        published_at=previous.published_at + timedelta(seconds=1),
        edit={instruction_key: edited_body},
    )
    edited = _keyed(await _sections_of(db_session, edited_id))

    await connection.run_sync(_M.seed_published_sets)

    new = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[("story", "gemini")]))
    assert new[instruction_key][0] == edited_body
    assert new == _expected_after(edited, "gemini")


async def test_upgrade_copies_each_chains_own_labels(db_session: AsyncSession) -> None:
    """라벨도 그 체인 활성 세트의 것이다 — 어드민은 체인마다 라벨을 따로 고칠 수 있다(테스트 DB 의 시드는 모든 체인 라벨이
    같아, 한 체인만 바꿔야 Gemini 라벨을 복사하는 실수와 갈린다)."""
    connection = await db_session.connection()
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.id == _PREVIOUS_SET_IDS[("story", "sonnet")]).values(user_label="독자")
    )

    await connection.run_sync(_M.seed_published_sets)

    db_session.expire_all()
    assert (await _get_set(db_session, _M.NEW_SET_IDS[("story", "sonnet")])).user_label == "독자"
    assert (await _get_set(db_session, _M.NEW_SET_IDS[("story", "gemini")])).user_label != "독자"


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 있다"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_the_lane_only_select_does_not_pick_gemini(db_session: AsyncSession) -> None:
    """어드민이 Gemini 가 아닌 체인을 Gemini 활성보다 나중에 게시했으면 레인만 보는 조회가 이미 그 세트를 집는다 — 아무것도
    넣지 않고 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("character", "gemini")])
    assert previous.published_at is not None
    db_session.add(
        _set(lane="character", model="opus", status="published", published_at=previous.published_at + timedelta(seconds=1))
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[character\] 레인만 보는"):
        await connection.run_sync(_M.seed_published_sets)
    for model in ("gemini", "sonnet", "haiku"):
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("character", model)]) is None


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_downgrade_stops_when_the_admin_published_after_the_seed(
    db_session: AsyncSession, lane: PromptLane, model: str
) -> None:
    """그 게시본에도 새 행이 있어 되돌린 뒤 활성으로 남으면 이전 코드의 게시 검증이 그 체인을 막는다 — 풀 길이 옛 버전 통째
    복원뿐이라 사람이 판단하게 멈춘다. 아무것도 지우지 않는다."""
    await _undo_later_revisions(db_session)
    seeded = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    assert seeded.published_at is not None
    db_session.add(_set(lane=lane, model=model, status="published", published_at=seeded.published_at + timedelta(seconds=1)))
    await db_session.flush()
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match=f"{lane}/{model}"):
        await connection.run_sync(_M.delete_seeded_rows)

    for pair in _ALL_PAIRS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[pair]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_patch_drafts_adds_the_rows_in_place_and_the_draft_publishes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 초안(이전 활성 세트 복제)에 새 행이 더해지고 `history` 뒤 생성 행만 밀리며, 그 체인의 게시
    게이트를 통과한다. 되돌리기는 초안의 새 행만 지우고 order 를 되돌린다."""
    draft_id = await _clone(db_session, _PREVIOUS_SET_IDS[(lane, model)], lane, model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [(lane, model)]

    patched = _keyed(await _sections_of(db_session, draft_id))
    assert patched == _expected_after(before, model)
    # 코드 표는 head 기준이라, 체인이 실제로 하듯 뒤 리비전(관계·사실 기억 문안)의 초안 패치도 거친 뒤 게시 게이트를 태운다.
    assert await connection.run_sync(_LATER._patch_drafts) == [(lane, model)]
    sections = await _sections_of(db_session, draft_id)
    draft = await _get_set(db_session, draft_id)  # 섹션을 읽으며 세션이 만료시킨 뒤에 읽는다
    _validate_prompt_draft_for_publish(draft, sections, lane=lane, model=model)

    # 되돌리기도 실제 순서대로 뒤 리비전부터.
    await connection.run_sync(_LATER._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == patched
    await connection.run_sync(_M._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_raises_when_the_draft_already_has_the_rows(db_session: AsyncSession) -> None:
    await _clone(db_session, _M.NEW_SET_IDS[("character", "haiku")], "character", "haiku")
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match="character/haiku 초안"):
        await connection.run_sync(_M._patch_drafts)
