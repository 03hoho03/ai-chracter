"""채팅 두 레인의 여덟 체인에 인상 생성 문안 채널(`memory_impression`)을 심는 데이터 마이그레이션 `6558ab4d3dbc`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 판정·요약 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가
이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행 그대로 + 새 세 행) — 마이그레이션의 행 조립으로 기대값을 만들면 그 조립이
틀려도 테스트가 같이 틀린다.

세 본문은 측정에서 고른 판을 바이트 그대로 옮긴 것이어야 한다. 그 원본 파일은 저장소에 없으므로(측정 산출물은 추적하지 않는다)
본문마다 원본의 sha256 과 글자 수를 여기 적어 둔다."""

import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, build_memory_impression_prompt, load_active_prompt_set
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


_M = _load("6558ab4d3dbc")
# 이 리비전 직전의 활성 세트 — story 네 체인은 장면 판정 지시문 교체 리비전, character 네 체인은 요약 비밀 표기 출처 리비전의
# 세트다(그 뒤 채팅 레인에 프롬프트를 게시한 리비전이 없다).
_SCENE_INSTRUCTION_V2 = _load("0f82ea9f9fa5")
_SOURCE_MARKING = _load("0c1a85bc5c2f")

_LANES: tuple[PromptLane, ...] = ("story", "character")
_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")
_CHAINS: list[tuple[PromptLane, PromptSetModelId]] = [(lane, model) for lane in _LANES for model in _MODELS]


def _previous_set_id(lane: str, model: str) -> uuid.UUID:
    source = _SCENE_INSTRUCTION_V2 if lane == "story" else _SOURCE_MARKING
    set_id: uuid.UUID = source.NEW_SET_IDS[(lane, model)]
    return set_id


Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 측정에서 고른 판의 본문마다 (sha256, 글자 수) — 글자 하나가 바뀌어도 여기서 깨진다.
_SOURCE_BODIES = {
    "instruction": ("4bb8bcac8a3540073d24687825d2f3b0b524e23330b9b308d60819d0082136b6", 789),
    "episodes": ("864f577bcedbc5c100513802524b9958e753563e55264fb92284e27a85e1e6ce", 23),
    "facts": ("ca28033017260ea5e219388e33a57bceeabb6885c9b3a8aed87e5313e8cbd211", 23),
}
# 슬롯마다 쓰는 자리표시자 — `build_memory_impression_prompt` 가 넘기는 이름뿐이어야 한다.
_PLACEHOLDERS: dict[str, list[str]] = {"instruction": [], "episodes": ["episode_lines"], "facts": ["fact_lines"]}


def _expected_new_rows() -> dict[Key, tuple[str, bool, int]]:
    """새 세 행의 (sha256, conditional, order)."""
    return {
        ("memory_impression", "both", "instruction", ""): (_SOURCE_BODIES["instruction"][0], False, 0),
        ("memory_impression", "both", "episodes", ""): (_SOURCE_BODIES["episodes"][0], True, 1),
        ("memory_impression", "both", "facts", ""): (_SOURCE_BODIES["facts"][0], True, 2),
    }


def _fingerprinted(rows: dict[Key, Value]) -> dict[Key, tuple[str, bool, int]]:
    return {key: (hashlib.sha256(body.encode()).hexdigest(), cond, order) for key, (body, cond, order) in rows.items()}


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


async def _active_id(db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane=lane, model=model))[0].id


async def _lane_only_active_id(db_session: AsyncSession, lane: str) -> uuid.UUID:
    connection = await db_session.connection()
    chosen: uuid.UUID = (await connection.execute(_M._LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane})).one().id
    return chosen


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


def _published(*, lane: str, model: str, published_at: datetime) -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version="9001",
        status="published",
        lane=lane,
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
        published_at=published_at,
    )


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_seed_bodies_are_the_measured_text_byte_for_byte_and_use_only_their_placeholders() -> None:
    bodies = {slot: body for _c, _s, slot, _v, body, _cond, _o in _M.NEW_ROWS}
    assert {slot: (hashlib.sha256(body.encode()).hexdigest(), len(body)) for slot, body in bodies.items()} == (
        _SOURCE_BODIES
    )
    assert {
        slot: [name for _, name, _, _ in Formatter().parse(body) if name] for slot, body in bodies.items()
    } == _PLACEHOLDERS


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _CHAINS)
async def test_each_chain_is_active_at_its_seed_which_is_the_previous_set_plus_three_rows(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """여덟 체인 모두 새 세트가 활성이고, 새 세트는 이전 활성 세트의 행을 바이트 그대로 옮긴 데에 새 세 행만 더한 것이다(기존
    채널의 렌더는 그대로). 라벨도 이전 활성 세트 것이다."""
    assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    new = _keyed(new_sections)
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _previous_set_id(lane, model)))
    assert not any(key[0] == "memory_impression" for key in before)

    assert {key: value for key, value in new.items() if key[0] != "memory_impression"} == before
    assert _fingerprinted({key: value for key, value in new.items() if key[0] == "memory_impression"}) == (
        _expected_new_rows()
    )
    assert all(section_id == _M._section_id(lane, model, *key) for section_id, key in ids.items())

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    old_set = await _get_set(db_session, _previous_set_id(lane, model))
    assert (this_set.lane, this_set.model, this_set.status) == (lane, model, "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(old_set, a) for a in _LABELS]


@pytest.mark.parametrize("lane", _LANES)
async def test_the_lane_only_select_picks_the_new_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    assert await _lane_only_active_id(db_session, lane) == _M.NEW_SET_IDS[(lane, "gemini")]


async def test_new_sets_are_published_in_the_window_of_both_active_rules(db_session: AsyncSession) -> None:
    """새 Gemini 세트는 원본보다 나중, 나머지 세 체인의 새 세트는 (그 체인 이전 활성, 그 레인 새 Gemini) 의 중간값."""
    for lane in _LANES:
        gemini_old = await _get_set(db_session, _previous_set_id(lane, "gemini"))
        gemini_new = await _get_set(db_session, _M.NEW_SET_IDS[(lane, "gemini")])
        assert gemini_old.published_at is not None and gemini_new.published_at is not None
        assert gemini_new.published_at >= gemini_old.published_at + timedelta(seconds=1)
        for model in ("sonnet", "opus", "haiku"):
            old = await _get_set(db_session, _previous_set_id(lane, model))
            new = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
            assert old.published_at is not None and new.published_at is not None
            assert new.published_at == old.published_at + (gemini_new.published_at - old.published_at) / 2


async def test_versions_continue_the_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    order = [_M.NEW_SET_IDS[chain] for chain in _CHAINS]
    versions = [int((await _get_set(db_session, set_id)).version or "0") for set_id in order]
    # 이 리비전이 프롬프트를 게시한 마지막 리비전이라 다른 게시본은 모두 이 리비전보다 앞 버전이다.
    others = (
        await db_session.scalars(
            sa.select(sa.cast(PromptSet.version, sa.Integer)).where(
                PromptSet.status == "published", PromptSet.id.not_in(order)
            )
        )
    ).all()
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


@pytest.mark.parametrize(("lane", "model"), _CHAINS)
async def test_seeded_sets_pass_publish_validation_and_the_previous_sets_no_longer_do(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """새 세트는 지금 코드의 게시 검증(슬롯 집합·자리표시자 허용 목록)을 통과하고, 이전 세트는 이 채널이 없어 "누락"으로
    막힌다 — 코드 표와 시드가 같이 움직였다는 증거다. 다른 모델 체인으로 게시하려 하면 여전히 막힌다(체인마다 채널 집합이
    다르다)."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    assert prompt_set.id == _M.NEW_SET_IDS[(lane, model)]
    _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=model)

    previous = await _get_set(db_session, _previous_set_id(lane, model))
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(
            previous, await _sections_of(db_session, _previous_set_id(lane, model)), lane=lane, model=model
        )


@pytest.mark.parametrize(("lane", "model"), _CHAINS)
async def test_the_seeded_channel_renders_and_drops_the_side_with_no_lines(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """심은 세트로 인상 프롬프트가 렌더되고, 줄이 없는 쪽 섹션은 머리글째 빠진다."""
    _set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)

    def render(episodes: list[str], facts: list[str]) -> str:
        return build_memory_impression_prompt(
            sections=sections, is_story_chat=lane == "story", episode_lines=episodes, fact_lines=facts
        )

    episode = "- 옥상의 약속: 둘은 방과 후 옥상에서 만나기로 했다"
    fact = "- 하린 → 사용자: 신뢰 — 믿고 열쇠를 맡김 (confirmed)"
    both = render([episode], [fact])
    assert both.startswith(_M.IMPRESSION_INSTRUCTION_BODY)
    assert f"[장면 기억]\n{episode}" in both and f"[관계·사실 기억]\n{fact}" in both

    only_episodes = render([episode], [])
    assert "[장면 기억]" in only_episodes and "[관계·사실 기억]" not in only_episodes
    only_facts = render([], [fact])
    assert "[장면 기억]" not in only_facts and "[관계·사실 기억]" in only_facts


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_every_chain_back_and_forth(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _CHAINS:
        assert await _active_id(db_session, lane, model) == _previous_set_id(lane, model)
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, model)]) is None
    for lane in _LANES:
        assert await _lane_only_active_id(db_session, lane) == _previous_set_id(lane, "gemini")
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.channel == "memory_impression")
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _CHAINS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 있다"):
        await connection.run_sync(_M.seed_published_sets)


@pytest.mark.parametrize(("lane", "model"), [("story", "opus"), ("character", "haiku")])
async def test_upgrade_refuses_to_overwrite_a_channel_the_admin_already_added(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """어느 체인의 활성 세트에 이 채널 행이 이미 있으면(어드민이 먼저 넣은 운영 문안) 그 레인 네 체인 어디에도 넣지 않은 채
    멈추고, 운영 문안은 그대로 남는다."""
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)
    db_session.add(
        PromptSection(
            prompt_set_id=_previous_set_id(lane, model),
            channel="memory_impression",
            scope="both",
            slot="instruction",
            variant="",
            body="어드민이 먼저 넣은 인상 문안",
            conditional=False,
            order=0,
        )
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match=rf"\[{lane}/{model}\] memory_impression 채널 행이 이미 있다"):
        await connection.run_sync(_M.seed_published_sets)
    for other in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, other)]) is None
    kept = _keyed(await _sections_of(db_session, _previous_set_id(lane, model)))
    assert kept[("memory_impression", "both", "instruction", "")][0] == "어드민이 먼저 넣은 인상 문안"


@pytest.mark.parametrize("lane", _LANES)
async def test_upgrade_stops_when_the_lane_only_select_does_not_pick_gemini(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _previous_set_id(lane, "gemini"))
    assert previous.published_at is not None
    db_session.add(_published(lane=lane, model="sonnet", published_at=previous.published_at + timedelta(seconds=1)))
    await db_session.flush()

    with pytest.raises(RuntimeError, match=rf"\[{lane}\] 레인만 보는"):
        await connection.run_sync(_M.seed_published_sets)


@pytest.mark.parametrize(("lane", "model"), _CHAINS)
async def test_downgrade_stops_when_the_admin_published_after_the_seed(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """시드 뒤에 어드민이 여덟 체인 중 하나라도 새 버전을 게시했으면 아무것도 지우지 않고 멈춘다."""
    seeded = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    assert seeded.published_at is not None
    db_session.add(_published(lane=lane, model=model, published_at=seeded.published_at + timedelta(seconds=1)))
    await db_session.flush()
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match=f"{lane}/{model}"):
        await connection.run_sync(_M.delete_seeded_rows)

    for chain in _CHAINS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[chain]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


async def _clone_as_draft(db_session: AsyncSession, set_id: uuid.UUID, lane: str, model: str) -> uuid.UUID:
    source = await _get_set(db_session, set_id)
    copy = PromptSet(
        version=None,
        status="draft",
        lane=lane,
        model=model,
        user_label=source.user_label,
        story_assistant_label=source.story_assistant_label,
        story_example_label=source.story_example_label,
        character_assistant_label=source.character_assistant_label,
        published_at=None,
    )
    db_session.add(copy)
    await db_session.flush()
    copy_id = copy.id
    for s in await _sections_of(db_session, set_id):
        db_session.add(
            PromptSection(
                prompt_set_id=copy_id,
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
    return copy_id


@pytest.mark.parametrize(("lane", "model"), _CHAINS)
async def test_patch_drafts_adds_the_rows_in_place_the_draft_publishes_and_downgrade_removes_them(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 채널이 없는 초안(배포 전 이전 활성본에서 만든 초안)에 같은 세 행을 넣어 지금 코드의 게시 검증을 통과하게 하고, 되돌리면
    그 행만 지워 원래 초안으로 돌아간다. 이미 채널이 있는 초안은 건드리지 않는다."""
    draft_id = await _clone_as_draft(db_session, _previous_set_id(lane, model), lane, model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [(lane, model)]
    patched = _keyed(await _sections_of(db_session, draft_id))
    assert {key: value for key, value in patched.items() if key[0] != "memory_impression"} == before
    assert _fingerprinted({key: value for key, value in patched.items() if key[0] == "memory_impression"}) == (
        _expected_new_rows()
    )
    sections = await _sections_of(db_session, draft_id)
    draft = await _get_set(db_session, draft_id)  # 섹션을 읽으며 세션이 만료시킨 뒤에 읽는다
    _validate_prompt_draft_for_publish(draft, sections, lane=lane, model=model)

    assert await connection.run_sync(_M._patch_drafts) == []

    assert await connection.run_sync(_M._delete_draft_rows) == [(lane, model)]
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_leaves_a_draft_that_already_has_the_channel(db_session: AsyncSession) -> None:
    """운영자가 초안에 이미 이 채널을 넣었으면 그 초안의 문안을 건드리지 않는다."""
    draft_id = await _clone_as_draft(db_session, _M.NEW_SET_IDS[("character", "gemini")], "character", "gemini")
    await db_session.execute(
        sa.update(PromptSection)
        .where(PromptSection.prompt_set_id == draft_id, PromptSection.channel == "memory_impression")
        .where(PromptSection.slot == "instruction")
        .values(body="운영자가 고치던 지시문")
    )
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before
