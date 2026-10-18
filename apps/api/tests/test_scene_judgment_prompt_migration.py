"""story 레인 네 체인에 장면 헤더 판정 채널(`scene_judgment`)을 심는 데이터 마이그레이션 `0346abdbcc92`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 판정·요약 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가
이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행 그대로 + 새 세 행) — 마이그레이션의 행 조립으로 기대값을 만들면 그 조립이
틀려도 테스트가 같이 틀린다. 문안 원문은 적지 않고 지문(md5)과 자리표시자로 고정한다."""

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
from api.chat.prompt_builder import PromptNames, build_scene_judgment_prompt, load_active_prompt_set
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


_M = _load("0346abdbcc92")
# 이 리비전 직전 story 네 체인의 활성 세트(요약 비밀 표기 슬롯 리비전 — 그 사이에 프롬프트를 게시한 리비전이 없다).
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = _load("0aeadefcf159").NEW_SET_IDS
# 이 리비전 뒤에 두 레인 여덟 체인에 장면 추출 지시문만 바꾼 새 세트를 게시하는 리비전. head 상태에서는 그 세트들이 활성이라,
# "이 리비전 직후 상태"를 보는 테스트와 이 리비전을 되돌리는 테스트는 그 리비전을 먼저 되돌린다(실제 downgrade 순서).
_LATER = _load("eb8d3cc6d5c2")

_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 시드 문안의 지문 — 글자 하나가 바뀌어도 여기서 깨진다.
_BODY_MD5 = {
    "instruction": "03b352bae2560b1394d9aadf8cd349ce",
    "previous_scene": "fd0104bc487110c0ab13c68e2f660fd8",
    "turn_context": "f9be12623ba44ceae3f13b215ae748ca",
}
_PLACEHOLDERS = {
    "instruction": [],
    "previous_scene": ["previous_place", "previous_time"],
    "turn_context": ["user_label", "user_message", "assistant_label", "assistant_message"],
}


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_new_rows() -> dict[Key, tuple[str, bool, int]]:
    """새 세 행의 (지문, conditional, order)."""
    return {
        ("scene_judgment", "story", "instruction", ""): (_BODY_MD5["instruction"], False, 0),
        ("scene_judgment", "story", "previous_scene", ""): (_BODY_MD5["previous_scene"], True, 1),
        ("scene_judgment", "story", "turn_context", ""): (_BODY_MD5["turn_context"], False, 2),
    }


def _fingerprinted(rows: dict[Key, Value]) -> dict[Key, tuple[str, bool, int]]:
    return {key: (hashlib.md5(body.encode()).hexdigest(), cond, order) for key, (body, cond, order) in rows.items()}


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_LATER.delete_seeded_rows)


async def _active_id(db_session: AsyncSession, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane="story", model=model))[0].id


async def _lane_only_active_id(db_session: AsyncSession) -> uuid.UUID:
    connection = await db_session.connection()
    chosen: uuid.UUID = (await connection.execute(_M._LANE_ONLY_ACTIVE_SET_SQL, {"lane": "story"})).one().id
    return chosen


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


def _published(*, model: str, published_at: datetime) -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version="9001",
        status="published",
        lane="story",
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
        published_at=published_at,
    )


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_seed_bodies_are_fixed_and_use_only_their_placeholders() -> None:
    """시드 문안은 지문으로 고정하고, 슬롯마다 쓰는 자리표시자는 렌더 함수가 넘기는 이름뿐이다."""
    bodies = {slot: body for _c, _s, slot, _v, body, _cond, _o in _M.NEW_ROWS}
    assert {slot: hashlib.md5(body.encode()).hexdigest() for slot, body in bodies.items()} == _BODY_MD5
    assert {
        slot: [name for _, name, _, _ in Formatter().parse(body) if name] for slot, body in bodies.items()
    } == _PLACEHOLDERS


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize("model", _MODELS)
async def test_each_story_chain_is_active_at_its_seed_which_is_the_previous_set_plus_three_rows(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """네 체인 모두 새 세트가 활성이고, 새 세트는 이전 활성 세트의 행을 바이트 그대로 옮긴 데에 새 세 행만 더한 것이다(기존
    채널의 렌더는 그대로). 라벨도 이전 활성 세트 것이다."""
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, model) == _M.NEW_SET_IDS[("story", model)]
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[("story", model)])
    new = _keyed(new_sections)
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[("story", model)]))
    assert not any(key[0] == "scene_judgment" for key in before)

    assert {key: value for key, value in new.items() if key[0] != "scene_judgment"} == before
    assert _fingerprinted({key: value for key, value in new.items() if key[0] == "scene_judgment"}) == (
        _expected_new_rows()
    )
    assert all(section_id == _M._section_id("story", model, *key) for section_id, key in ids.items())

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[("story", model)])
    old_set = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", model)])
    assert (this_set.lane, this_set.model, this_set.status) == ("story", model, "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(old_set, a) for a in _LABELS]


async def test_the_lane_only_select_picks_the_new_gemini_set_and_character_is_untouched(
    db_session: AsyncSession,
) -> None:
    await _undo_later_revisions(db_session)
    assert await _lane_only_active_id(db_session) == _M.NEW_SET_IDS[("story", "gemini")]
    _set, sections = await load_active_prompt_set(db_session, lane="character", model="gemini")
    assert not any(s.channel == "scene_judgment" for s in sections)


async def test_new_sets_are_published_in_the_window_of_both_active_rules(db_session: AsyncSession) -> None:
    """새 Gemini 세트는 원본보다 나중, 나머지 세 체인의 새 세트는 (그 체인 이전 활성, 새 Gemini) 의 중간값."""
    gemini_old = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    gemini_new = await _get_set(db_session, _M.NEW_SET_IDS[("story", "gemini")])
    assert gemini_old.published_at is not None and gemini_new.published_at is not None
    assert gemini_new.published_at >= gemini_old.published_at + timedelta(seconds=1)
    for model in ("sonnet", "opus", "haiku"):
        old = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", model)])
        new = await _get_set(db_session, _M.NEW_SET_IDS[("story", model)])
        assert old.published_at is not None and new.published_at is not None
        assert new.published_at == old.published_at + (gemini_new.published_at - old.published_at) / 2


async def test_versions_continue_the_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    order = [_M.NEW_SET_IDS[("story", model)] for model in _MODELS]
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
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 장면 추출 지시문 리비전의 것뿐이다(그 세트들의 버전은 이 리비전보다 뒤다).
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


@pytest.mark.parametrize("model", _MODELS)
async def test_seeded_sets_pass_publish_validation_and_the_previous_sets_no_longer_do(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """새 세트는 지금 코드의 게시 검증(슬롯 집합·자리표시자 허용 목록)을 통과하고, 이전 세트는 이 채널이 없어 "누락"으로
    막힌다 — 코드 표와 시드가 같이 움직였다는 증거다."""
    await _undo_later_revisions(db_session)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story", model=model)
    _validate_prompt_draft_for_publish(prompt_set, sections, lane="story", model=model)

    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", model)])
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(
            previous, await _sections_of(db_session, _PREVIOUS_SET_IDS[("story", model)]), lane="story", model=model
        )


@pytest.mark.parametrize("model", _MODELS)
async def test_the_seeded_channel_renders_and_drops_the_previous_scene_when_both_are_empty(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """심은 세트로 렌더가 비지 않고, 직전 장면이 둘 다 없으면 그 섹션만 빠진다(첫 장면이 없는 방의 첫 턴)."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story", model=model)
    names = PromptNames(persona_name=None, char_name=None)

    def render(place: str | None, time: str | None) -> str:
        return build_scene_judgment_prompt(
            prompt_set=prompt_set,
            sections=sections,
            previous_place=place,
            previous_time=time,
            user_message="옥상으로 올라가자",
            assistant_message="둘은 계단을 올라 옥상 문을 열었다.",
            names=names,
        )

    with_previous = render("교실", None)
    without_previous = render(None, None)
    assert "교실" in with_previous and "옥상으로 올라가자" in with_previous
    assert "교실" not in without_previous and "옥상으로 올라가자" in without_previous
    assert len(without_previous) < len(with_previous)


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_every_chain_back_and_forth(db_session: AsyncSession) -> None:
    connection = await db_session.connection()

    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    for model in _MODELS:
        assert await _active_id(db_session, model) == _PREVIOUS_SET_IDS[("story", model)]
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None
    assert await _lane_only_active_id(db_session) == _PREVIOUS_SET_IDS[("story", "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.channel == "scene_judgment")
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for model in _MODELS:
        assert await _active_id(db_session, model) == _M.NEW_SET_IDS[("story", model)]


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 있다"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_a_chain_already_has_the_channel(db_session: AsyncSession) -> None:
    """어느 체인의 활성 세트에 이 채널 행이 이미 있으면 네 체인 어디에도 넣지 않은 채 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    db_session.add(
        PromptSection(
            prompt_set_id=_PREVIOUS_SET_IDS[("story", "opus")],
            channel="scene_judgment",
            scope="story",
            slot="instruction",
            variant="",
            body="어드민이 먼저 넣은 행",
            conditional=False,
            order=0,
        )
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[story/opus\] scene_judgment 채널 행이 이미 있다"):
        await connection.run_sync(_M.seed_published_sets)
    for model in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None


async def test_upgrade_stops_when_the_lane_only_select_does_not_pick_gemini(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    assert previous.published_at is not None
    db_session.add(_published(model="sonnet", published_at=previous.published_at + timedelta(seconds=1)))
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[story\] 레인만 보는"):
        await connection.run_sync(_M.seed_published_sets)


@pytest.mark.parametrize("model", _MODELS)
async def test_downgrade_stops_when_the_admin_published_after_the_seed(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """시드 뒤에 어드민이 네 체인 중 하나라도 새 버전을 게시했으면 아무것도 지우지 않고 멈춘다."""
    await _undo_later_revisions(db_session)
    seeded = await _get_set(db_session, _M.NEW_SET_IDS[("story", model)])
    assert seeded.published_at is not None
    db_session.add(_published(model=model, published_at=seeded.published_at + timedelta(seconds=1)))
    await db_session.flush()
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match=f"story/{model}"):
        await connection.run_sync(_M.delete_seeded_rows)

    for other in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", other)]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


async def _clone_as_draft(db_session: AsyncSession, set_id: uuid.UUID, model: str) -> uuid.UUID:
    source = await _get_set(db_session, set_id)
    copy = PromptSet(
        version=None,
        status="draft",
        lane="story",
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


@pytest.mark.parametrize("model", _MODELS)
async def test_patch_drafts_adds_the_rows_in_place_the_draft_publishes_and_downgrade_removes_them(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """이 채널이 없는 초안(배포 전 이전 활성본에서 만든 초안)에 같은 세 행을 넣어 지금 코드의 게시 검증을 통과하게 하고, 되돌리면
    그 행만 지워 원래 초안으로 돌아간다. 이미 채널이 있는 초안은 건드리지 않는다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS[("story", model)], model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [("story", model)]
    patched = _keyed(await _sections_of(db_session, draft_id))
    assert {key: value for key, value in patched.items() if key[0] != "scene_judgment"} == before
    assert _fingerprinted({key: value for key, value in patched.items() if key[0] == "scene_judgment"}) == (
        _expected_new_rows()
    )
    sections = await _sections_of(db_session, draft_id)
    draft = await _get_set(db_session, draft_id)  # 섹션을 읽으며 세션이 만료시킨 뒤에 읽는다
    _validate_prompt_draft_for_publish(draft, sections, lane="story", model=model)

    assert await connection.run_sync(_M._patch_drafts) == []

    assert await connection.run_sync(_M._delete_draft_rows) == [("story", model)]
    assert _keyed(await _sections_of(db_session, draft_id)) == before
