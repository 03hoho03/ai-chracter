"""판정·요약 문안을 Claude 체인(sonnet·opus)과 판정 전용 체인(haiku)에 심는 데이터 마이그레이션 `1a843a0b2d8f`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_stat_rule_judgment_prompt_migration.py`와 같은 방식). 세션 스코프
스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, 순수 함수와
`seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로
직접 부른다(되돌리기 → 다시 올리기 왕복)."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _build_preview_items, _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
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


_M = _load("1a843a0b2d8f")
# 이 리비전 직전의 Claude 활성 세트 — 테스트 DB에서는 모델 축 리비전이 심은 시드다(그 뒤 Claude 채팅 체인에 게시한
# 리비전이 없다).
_PREVIOUS_CLAUDE_SET_IDS: dict[tuple[str, str], uuid.UUID] = _load("e6aa289fea62").NEW_SET_IDS
# 이 리비전 직전의 Gemini 활성 세트 — story 는 스탯 규칙 판정 채널 리비전, character 는 소설화 채널 리비전의 세트다.
_GEMINI_SET_IDS: dict[str, uuid.UUID] = {
    "story": _load("d9768bc0cfee").NEW_SET_ID,
    "character": _load("3bb2cc159b6d").NEW_SET_IDS["character"],
}

_LANES: tuple[PromptLane, ...] = ("story", "character")
_CLAUDE_MODELS: tuple[PromptSetModelId, ...] = ("sonnet", "opus")
_CLAUDE_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [(lane, model) for lane in _LANES for model in _CLAUDE_MODELS]
_ALL_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [
    (lane, model) for lane in _LANES for model in (*_CLAUDE_MODELS, "haiku")
]
_EXPECTED_JUDGMENT_CHANNELS = {
    "story": {"stat_rule_judgment", "ending_judgment", "image_judgment", "memory_summary"},
    "character": {"image_judgment", "memory_summary"},
}

Key = tuple[str, str, str, str]


def _ids(pairs: list[tuple[PromptLane, PromptSetModelId]]) -> list[str]:
    return [f"{lane}-{model}" for lane, model in pairs]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, tuple[str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


async def _active_id(db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane=lane, model=model))[0].id


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")


# ---- 순수 함수 -------------------------------------------------------------------------------


def test_channel_table_is_the_lanes_judgment_and_summary_channels() -> None:
    """옛 `stat_judgment` 은 읽는 코드가 없어 넣지 않는다. 소설화 채널은 판정·요약이 아니다."""
    assert {lane: set(channels) for lane, channels in _M.JUDGMENT_CHANNELS.items()} == _EXPECTED_JUDGMENT_CHANNELS


def test_seed_time_is_strictly_between_in_a_one_second_window() -> None:
    """테스트 DB·운영 모두 character 레인 창이 정확히 1초다 — 옛 시드처럼 Gemini − 1초를 쓰면 기존 Claude 세트와 같은
    시각이 돼 모델로 거르는 활성 조회가 동률이 된다."""
    claude_at = datetime(2026, 10, 6, 2, 26, 46, 147299, tzinfo=UTC)
    gemini_at = claude_at + timedelta(seconds=1)

    chosen = _M._seed_time(claude_at, gemini_at)

    assert claude_at < chosen < gemini_at
    assert chosen == claude_at + timedelta(milliseconds=500)


@pytest.mark.parametrize("gap", [pytest.param(timedelta(0), id="same"), pytest.param(timedelta(seconds=1), id="later")])
def test_seed_time_raises_without_a_window(gap: timedelta) -> None:
    """Claude 활성이 Gemini 활성보다 과거가 아니면 두 조회 규칙을 함께 만족하는 시각이 없다 — 배포를 멈춘다."""
    gemini_at = datetime(2026, 10, 8, 12, 0, 57, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="시각"):
        _M._seed_time(gemini_at + gap, gemini_at)


def test_seed_time_raises_when_the_window_is_too_narrow_to_split() -> None:
    claude_at = datetime(2026, 10, 8, 12, 0, 57, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="시각"):
        _M._seed_time(claude_at, claude_at + timedelta(microseconds=1))


@pytest.mark.parametrize("lane", _LANES)
def test_gemini_source_must_carry_every_judgment_channel(lane: str) -> None:
    channels = sorted(_EXPECTED_JUDGMENT_CHANNELS[lane])
    _M._assert_gemini_source(["system", "generation", *channels], lane=lane)
    with pytest.raises(RuntimeError, match=f"누락 \\['{channels[0]}'\\]"):
        _M._assert_gemini_source(["system", "generation", *channels[1:]], lane=lane)


@pytest.mark.parametrize("missing", ["system", "generation"])
def test_claude_source_must_carry_the_generation_channels(missing: str) -> None:
    with pytest.raises(RuntimeError, match=f"누락 \\['{missing}'\\]"):
        _M._assert_claude_source([c for c in ("system", "generation") if c != missing], lane="story", what="story/opus")


def test_claude_source_with_a_judgment_row_already_raises() -> None:
    _M._assert_claude_source(["system", "generation"], lane="character", what="character/sonnet")
    with pytest.raises(RuntimeError, match="이미 있다"):
        _M._assert_claude_source(["system", "generation", "memory_summary"], lane="character", what="character/sonnet")


def test_retired_stat_judgment_rows_do_not_count_as_judgment_rows() -> None:
    """옛 채널은 표에 없어 Claude 세트에 있어도 이 리비전의 "두 번 적용" 신호가 아니다."""
    _M._assert_claude_source(["system", "generation", "stat_judgment"], lane="story", what="story/sonnet")


def test_an_existing_judgment_only_set_raises() -> None:
    _M._assert_no_judgment_only_sets(0, lane="story")
    with pytest.raises(RuntimeError, match="이미 세트가 2개"):
        _M._assert_no_judgment_only_sets(2, lane="story")


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_each_chain_is_active_at_its_seeded_set(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


@pytest.mark.parametrize("lane", _LANES)
async def test_gemini_chain_and_the_lane_only_select_keep_the_gemini_set(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """기본 Gemini 체인은 그대로다. 모델 열을 모르는 코드(옛 이미지·옛 마이그레이션의 원시 SQL)가 레인만 보고 최신
    게시본을 고를 때도 여전히 Gemini 세트를 집는다 — 새 세트가 그보다 과거여야 성립한다."""
    assert await _active_id(db_session, lane, "gemini") == _GEMINI_SET_IDS[lane]
    connection = await db_session.connection()
    chosen = (await connection.execute(_M._LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane})).one().id
    assert chosen == _GEMINI_SET_IDS[lane]


@pytest.mark.parametrize(("lane", "model"), _CLAUDE_PAIRS, ids=_ids(_CLAUDE_PAIRS))
async def test_claude_set_is_the_previous_claude_set_plus_the_gemini_judgment_rows(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    previous = _PREVIOUS_CLAUDE_SET_IDS[(lane, model)]
    new = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)]))
    old = _keyed(await _sections_of(db_session, previous))
    gemini = _keyed(await _sections_of(db_session, _GEMINI_SET_IDS[lane]))
    judgment = {key: value for key, value in gemini.items() if key[0] in _EXPECTED_JUDGMENT_CHANNELS[lane]}

    assert {key[0] for key in old} == {"system", "generation"}
    assert new == {**old, **judgment}
    assert {key[0] for key in new} == {"system", "generation"} | _EXPECTED_JUDGMENT_CHANNELS[lane]

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    old_set = await _get_set(db_session, previous)
    assert (this_set.lane, this_set.model, this_set.status) == (lane, model, "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(old_set, a) for a in _LABELS]


@pytest.mark.parametrize("lane", _LANES)
async def test_judgment_only_set_holds_only_the_gemini_judgment_rows(db_session: AsyncSession, lane: PromptLane) -> None:
    """판정 전용 체인으로는 생성하지 않는다 — 생성 채널 없이 판정·요약 행과 그 렌더가 읽는 라벨만."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, "haiku")])
    new = _keyed(new_sections)
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    gemini = _keyed(await _sections_of(db_session, _GEMINI_SET_IDS[lane]))

    assert new == {key: value for key, value in gemini.items() if key[0] in _EXPECTED_JUDGMENT_CHANNELS[lane]}
    assert all(section_id == _M._section_id("", lane, "haiku", *key) for section_id, key in ids.items())

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, "haiku")])
    gemini_set = await _get_set(db_session, _GEMINI_SET_IDS[lane])
    assert (this_set.lane, this_set.model, this_set.status) == (lane, "haiku", "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(gemini_set, a) for a in _LABELS]


@pytest.mark.parametrize("lane", _LANES)
async def test_new_sets_are_published_inside_the_window(db_session: AsyncSession, lane: PromptLane) -> None:
    """Claude 새 세트는 이전 Claude 세트와 Gemini 세트 사이(중간값), 판정 전용 세트는 Gemini 세트보다 과거."""
    gemini = await _get_set(db_session, _GEMINI_SET_IDS[lane])
    assert gemini.published_at is not None
    for model in _CLAUDE_MODELS:
        old = await _get_set(db_session, _PREVIOUS_CLAUDE_SET_IDS[(lane, model)])
        new = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
        assert old.published_at is not None and new.published_at is not None
        assert old.published_at < new.published_at < gemini.published_at
        assert new.published_at == old.published_at + (gemini.published_at - old.published_at) / 2
    haiku = await _get_set(db_session, _M.NEW_SET_IDS[(lane, "haiku")])
    assert haiku.published_at == gemini.published_at - timedelta(seconds=1)


async def test_versions_continue_the_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    """전 레인·전 모델 published 최대 + 1 을 (story, character) × (sonnet, opus, haiku) 순서로."""
    order = [_M.NEW_SET_IDS[pair] for pair in _ALL_PAIRS]
    versions = [int((await _get_set(db_session, set_id)).version or "0") for set_id in order]
    others = (
        await db_session.scalars(
            sa.select(sa.cast(PromptSet.version, sa.Integer)).where(
                PromptSet.status == "published", PromptSet.id.not_in(order)
            )
        )
    ).all()
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 없다.
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


async def test_no_drafts_are_seeded(db_session: AsyncSession) -> None:
    drafts = (await db_session.scalars(sa.select(PromptSet.id).where(PromptSet.status == "draft"))).all()
    assert drafts == []


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_seeded_sets_pass_publish_validation_for_their_chain(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """게시 검증의 기대 집합과 시드가 맞물린다 — 어긋나면 운영자가 그 체인을 손대는 순간 게시가 막힌다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)

    _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=model)
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model="gemini")


@pytest.mark.parametrize(("lane", "model"), _CLAUDE_PAIRS, ids=_ids(_CLAUDE_PAIRS))
async def test_generation_renders_the_same_before_and_after(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 전후로 그 모델의 생성 문안(바닥 지시문·생성 프롬프트)이 같은 샘플에서 한 글자도 다르지 않다 — 배포 중
    옛 이미지가 새 세트로 생성해도, 새 이미지가 생성해도 같은 글이 나간다."""

    async def generation_items(set_id: uuid.UUID) -> list[tuple[str, str, str]]:
        # `_sections_of` 가 세션 객체를 만료시키므로 세트는 그 뒤에 읽고 바로 렌더한다.
        sections = await _sections_of(db_session, set_id)
        prompt_set = await _get_set(db_session, set_id)
        items = _build_preview_items(prompt_set, sections, lane=lane, model=model)
        return [(i.channel, i.label, i.text) for i in items if i.channel in ("system", "generation")]

    before = await generation_items(_PREVIOUS_CLAUDE_SET_IDS[(lane, model)])
    assert len(before) >= 2
    assert await generation_items(_M.NEW_SET_IDS[(lane, model)]) == before


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


async def _after_gemini(db_session: AsyncSession, lane: PromptLane) -> datetime:
    """그 레인 Gemini 활성보다 1초 뒤 — 어드민이 시드 뒤에 게시한 시각. 파이썬 `now()` 를 쓰지 않는 이유: 앞선 시드 리비전들이
    새 세트를 "원본 + 1초"로 쌓아, 마이그레이션만으로 만든 테스트 DB 에서는 활성 세트 시각이 실제 시각보다 몇 초 앞서 있다.
    스키마를 만든 직후에 돌면 `now()` 가 시드보다 과거가 된다(묶음을 작게 돌렸을 때 실제로 그렇게 깨졌다)."""
    gemini = await _get_set(db_session, _GEMINI_SET_IDS[lane])
    assert gemini.published_at is not None
    return gemini.published_at + timedelta(seconds=1)


async def _judgment_rows_in_claude_chains(db_session: AsyncSession) -> int:
    count = 0
    for lane, channels in _EXPECTED_JUDGMENT_CHANNELS.items():
        count += await db_session.scalar(
            sa.select(sa.func.count())
            .select_from(PromptSection)
            .join(PromptSet, PromptSet.id == PromptSection.prompt_set_id)
            .where(
                PromptSet.lane == lane,
                PromptSet.model.in_(["sonnet", "opus"]),
                PromptSection.channel.in_(sorted(channels)),
            )
        ) or 0
    return count


async def test_downgrade_then_upgrade_swaps_the_chains_back_and_forth(db_session: AsyncSession) -> None:
    """되돌리면 Claude 체인 활성이 이전 세트로 돌아가고, 판정 전용 세트는 어드민이 만든 초안까지 하나도 남지 않으며, Claude
    체인 어디에도(시드 뒤 저장한 초안 포함) 판정·요약 행이 없다. Gemini 체인은 내내 그대로다. 다시 올리면 같은 리터럴 세트가
    활성이 된다."""
    db_session.add(_set(lane="story", model="haiku", status="draft"))
    await db_session.flush()
    draft_id = await _clone_as_draft(db_session, _M.NEW_SET_IDS[("story", "sonnet")], "story", "sonnet")
    gemini_before = {lane: await _active_id(db_session, lane, "gemini") for lane in _LANES}
    connection = await db_session.connection()

    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _CLAUDE_PAIRS:
        assert await _active_id(db_session, lane, model) == _PREVIOUS_CLAUDE_SET_IDS[(lane, model)]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(PromptSet).where(PromptSet.model == "haiku")) == 0
    assert await _judgment_rows_in_claude_chains(db_session) == 0
    assert {s.channel for s in await _sections_of(db_session, draft_id)} == {"system", "generation"}
    assert {lane: await _active_id(db_session, lane, "gemini") for lane in _LANES} == gemini_before

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _ALL_PAIRS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]
    assert {lane: await _active_id(db_session, lane, "gemini") for lane in _LANES} == gemini_before


async def test_downgrade_removes_judgment_only_sets_the_admin_published(db_session: AsyncSession) -> None:
    """이전 코드는 판정 전용 세트를 목록·조회·복원 어디서도 다루지 못한다 — 남기면 고아이고, 다시 올릴 때 "이미 세트가
    있다"로 막힌다."""
    db_session.add(_set(lane="character", model="haiku", status="published", published_at=datetime.now(UTC)))
    await db_session.flush()
    connection = await db_session.connection()

    await connection.run_sync(_M.delete_seeded_rows)

    assert await db_session.scalar(sa.select(sa.func.count()).select_from(PromptSet).where(PromptSet.model == "haiku")) == 0


@pytest.mark.parametrize(("lane", "model"), _CLAUDE_PAIRS, ids=_ids(_CLAUDE_PAIRS))
async def test_downgrade_stops_when_the_admin_published_a_claude_set_after_the_seed(
    db_session: AsyncSession, lane: PromptLane, model: str
) -> None:
    """그 게시본에도 판정 행이 있어 되돌린 뒤 활성으로 남으면 이전 코드의 게시 검증이 그 체인을 막는다 — 풀 길이 옛 버전
    통째 복원뿐이라 사람이 판단하게 멈춘다. 아무것도 지우지 않는다."""
    db_session.add(_set(lane=lane, model=model, status="published", published_at=await _after_gemini(db_session, lane)))
    await db_session.flush()
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match=f"{lane}/{model}"):
        await connection.run_sync(_M.delete_seeded_rows)

    for pair in _ALL_PAIRS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[pair]) is not None


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_the_lane_has_no_window(db_session: AsyncSession) -> None:
    """어드민이 Claude 체인을 Gemini 활성보다 나중에 게시했으면(레인만 보는 조회가 이미 Claude 를 집는다) 두 규칙을 함께
    만족하는 시각이 없다."""
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)
    db_session.add(_set(lane="story", model="opus", status="published", published_at=await _after_gemini(db_session, "story")))
    await db_session.flush()

    with pytest.raises(RuntimeError, match="story"):
        await connection.run_sync(_M.seed_published_sets)


# ---- `_patch_drafts` ------------------------------------------------------------------------


async def _clone_as_draft(db_session: AsyncSession, set_id: uuid.UUID, lane: str, model: str) -> uuid.UUID:
    source = await _get_set(db_session, set_id)
    draft = PromptSet(
        version=None,
        status="draft",
        lane=lane,
        model=model,
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


@pytest.mark.parametrize(("lane", "model"), _CLAUDE_PAIRS, ids=_ids(_CLAUDE_PAIRS))
async def test_patch_drafts_adds_the_judgment_rows_in_place_and_the_draft_publishes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 Claude 초안(이전 Claude 세트 복제)에 판정·요약 행이 더해지고 다른 행은 그대로이며, 그 체인의
    게시 게이트를 통과한다. 되돌리기는 초안의 그 행만 지운다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_CLAUDE_SET_IDS[(lane, model)], lane, model)
    before = _keyed(await _sections_of(db_session, draft_id))
    gemini = _keyed(await _sections_of(db_session, _GEMINI_SET_IDS[lane]))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [(lane, model)]

    sections = await _sections_of(db_session, draft_id)
    assert _keyed(sections) == {
        **before,
        **{key: value for key, value in gemini.items() if key[0] in _EXPECTED_JUDGMENT_CHANNELS[lane]},
    }
    draft = await _get_set(db_session, draft_id)
    _validate_prompt_draft_for_publish(draft, sections, lane=lane, model=model)

    await connection.run_sync(_M._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_leaves_gemini_drafts_alone(db_session: AsyncSession) -> None:
    draft_id = await _clone_as_draft(db_session, _GEMINI_SET_IDS["story"], "story", "gemini")
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_raises_when_the_draft_already_has_judgment_rows(db_session: AsyncSession) -> None:
    await _clone_as_draft(db_session, _M.NEW_SET_IDS[("character", "opus")], "character", "opus")
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match="character/opus"):
        await connection.run_sync(_M._patch_drafts)
