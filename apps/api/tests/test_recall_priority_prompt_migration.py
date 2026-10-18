"""회상 섹션 문안의 우선순위 문장에서 사실 섹션 이름을 빼는 데이터 마이그레이션 `726aad108167`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 기억 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가 이미
`upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows`·`_delete_draft_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행에서 회상 본문만 새 상수) — 마이그레이션의 행 조립 함수로 기대값을 만들면 그
함수가 틀려도 테스트가 같이 틀린다."""

import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
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


_M = _load("726aad108167")
# 이 리비전 직전의 활성 세트 — 여덟 체인 모두 관계·사실 기억 문안 리비전의 세트다(그 사이에 프롬프트를 게시한 리비전이 없다).
_FACT_MIGRATION = _load("5cab2abe4e7b")
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = _FACT_MIGRATION.NEW_SET_IDS
# 이 리비전 뒤에 여덟 체인에 사실 추출 지시문만 바꾼 새 세트를 게시하는 리비전. head 상태에서는 그 세트들이 활성이라, "이 리비전
# 직후 상태"를 보는 테스트와 이 리비전을 되돌리는 테스트는 그 리비전을 먼저 되돌린다(실제 downgrade 순서).
_LATER = _load("e4e407a62d03")
# 그 뒤 여덟 체인의 요약 채널에 비밀 표기 슬롯을 더한 새 세트를 게시하는 리비전.
_LATEST = _load("0aeadefcf159")
# 그 뒤 story 레인 네 체인에 장면 헤더 판정 채널을 더한 세트를 게시하는 리비전 — 초안 게시 검사가 head 코드 표를 쓰므로
# story 초안은 이것도 거친다.
_SCENE_JUDGMENT = _load("0346abdbcc92")
# 그 뒤 여덟 체인에 장면 추출 지시문만 바꾼 세트를 게시하는 리비전 — 여덟 체인의 head 활성이라 되돌릴 때는 이것부터다.
_EPISODE_KNOWN_BY = _load("eb8d3cc6d5c2")

_LANES: tuple[PromptLane, ...] = ("story", "character")
_WRITING_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")
_WRITING_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [
    (lane, model) for lane in _LANES for model in _WRITING_MODELS
]

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_RECALL_KEY: Key = ("generation", "both", "memory_recall", "")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 사실 섹션 머리글 — 사실 주입이 꺼지면 프롬프트에 없는 이름이다.
_FACTS_HEADER = _FACT_MIGRATION.FACTS_BODY.partition("\n")[0]
# 새 회상 본문의 지문 — 글자 하나가 바뀌어도 여기서 깨진다.
_NEW_RECALL_MD5 = "f331f21d3abe833d6afbb911c1b5fb4c"


def _ids(pairs: list[tuple[PromptLane, PromptSetModelId]]) -> list[str]:
    return [f"{lane}-{model}" for lane, model in pairs]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_after(before: dict[Key, Value]) -> dict[Key, Value]:
    """이전 행 그대로, 회상 본문만 새 상수."""
    _old_body, conditional, order = before[_RECALL_KEY]
    return {**before, _RECALL_KEY: (_M.RECALL_BODY, conditional, order)}


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_EPISODE_KNOWN_BY.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
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


def _in_order(text: str, markers: list[str]) -> bool:
    positions = [text.find(marker) for marker in markers]
    return all(p >= 0 for p in positions) and positions == sorted(positions)


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_old_recall_body_this_revision_expects_is_the_one_the_fact_revision_seeded() -> None:
    """운영 본문이 이 상수와 같을 때만 바꾼다 — 상수가 앞 리비전 문안과 한 글자라도 다르면 모든 체인에서 멈춘다."""
    assert _M.OLD_RECALL_BODY == _FACT_MIGRATION.RECALL_BODY


def test_new_recall_body_drops_the_facts_header_and_keeps_every_other_sentence() -> None:
    """사실 섹션 머리글이 본문 어디에도 없고, 바뀐 것은 우선순위 줄에서 그 이름을 뺀 것과 다음 문장의 사실 기억 구절뿐이다."""
    new = _M.RECALL_BODY
    assert hashlib.md5(new.encode()).hexdigest() == _NEW_RECALL_MD5
    assert _FACTS_HEADER == "[관계와 사실]"
    assert _FACTS_HEADER not in new
    assert _FACTS_HEADER in _M.OLD_RECALL_BODY
    assert new == _M.OLD_RECALL_BODY.replace(f"{_FACTS_HEADER} > ", "", 1).replace(
        "현재 상황 정보도", "현재 상황 정보와, 실려 있다면 관계·사실 기억도", 1
    )
    assert new.partition("\n")[0] == "[지난 기억 — 참고]"
    assert new.endswith("\n{memory_recall_lines}") and new.count("{") == 1


def test_new_recall_body_agrees_with_the_facts_section_priority() -> None:
    """두 문안이 서로 어긋나지 않는다 — 둘이 함께 부르는 섹션의 순서가 같고, 사실 섹션은 자기를 회상보다 앞에, 회상은 사실
    기억을 자기보다 앞에 둔다."""
    recall = _M.RECALL_BODY[_M.RECALL_BODY.index("이 순서로 따른다") :]
    facts = _FACT_MIGRATION.FACTS_BODY[_FACT_MIGRATION.FACTS_BODY.index("이 순서로 따른다") :]
    shared = ["[대화 기록]", "[기억 노트]", "[지금까지의 이야기]"]
    assert _in_order(recall, [*shared, "이 기억"])
    assert _in_order(facts, [*shared, "이 섹션", "[지난 기억"])
    assert "실려 있다면 관계·사실 기억도 이 기억보다\n앞선다" in recall


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _WRITING_PAIRS, ids=_ids(_WRITING_PAIRS))
async def test_each_writing_chain_is_active_at_its_seeded_set_with_the_new_recall_bytes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]
    _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    (recall,) = [s for s in sections if (s.channel, s.slot) == ("generation", "memory_recall")]
    assert hashlib.md5(recall.body.encode()).hexdigest() == _NEW_RECALL_MD5


@pytest.mark.parametrize("lane", _LANES)
async def test_judgment_only_chain_keeps_its_active_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """판정 전용 체인에는 회상 슬롯이 없어 새 세트를 만들지 않는다."""
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, lane, "haiku") == _PREVIOUS_SET_IDS[(lane, "haiku")]
    assert (lane, "haiku") not in _M.NEW_SET_IDS


@pytest.mark.parametrize("lane", _LANES)
async def test_the_lane_only_select_picks_the_new_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """모델 열을 모르는 원시 SQL 이 레인만 보고 최신 게시본을 고를 때도 새 Gemini 세트를 집는다."""
    await _undo_later_revisions(db_session)
    assert await _lane_only_active_id(db_session, lane) == _M.NEW_SET_IDS[(lane, "gemini")]


@pytest.mark.parametrize(("lane", "model"), _WRITING_PAIRS, ids=_ids(_WRITING_PAIRS))
async def test_new_set_is_the_previous_active_set_with_only_the_recall_body_changed(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이전 활성 세트의 행이 바이트 그대로 옮겨지고(회상 본문만 다르다), 더하거나 빠진 행이 없다. 라벨도 이전 활성 세트 것이다."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    new = _keyed(new_sections)
    # 다음 `_sections_of` 가 `expire_all` 로 이 객체들을 만료시키므로 그 전에 읽어 둔다(만료된 속성을 읽으면 동기 지연 로드다).
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)]))

    assert before[_RECALL_KEY][0] == _M.OLD_RECALL_BODY
    assert new == _expected_after(before)
    assert all(section_id == _M._section_id(lane, model, *key) for section_id, key in ids.items())

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    old_set = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    assert (this_set.lane, this_set.model, this_set.status) == (lane, model, "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(old_set, a) for a in _LABELS]


@pytest.mark.parametrize("lane", _LANES)
async def test_new_sets_are_published_in_the_window_of_both_active_rules(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """새 Gemini 세트는 원본보다 나중, sonnet·opus 의 새 세트는 (그 체인 이전 활성, 새 Gemini) 의 중간값."""
    gemini_old = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, "gemini")])
    gemini_new = await _get_set(db_session, _M.NEW_SET_IDS[(lane, "gemini")])
    assert gemini_old.published_at is not None and gemini_new.published_at is not None
    assert gemini_new.published_at >= gemini_old.published_at + timedelta(seconds=1)
    for model in ("sonnet", "opus"):
        old = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
        new = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
        assert old.published_at is not None and new.published_at is not None
        assert old.published_at < new.published_at < gemini_new.published_at
        assert new.published_at == old.published_at + (gemini_new.published_at - old.published_at) / 2


async def test_versions_continue_the_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    """전 레인·전 모델 published 최대 + 1 을 (story, character) × (gemini, sonnet, opus) 순서로."""
    order = [_M.NEW_SET_IDS[pair] for pair in _WRITING_PAIRS]
    versions = [int((await _get_set(db_session, set_id)).version or "0") for set_id in order]
    others = (
        await db_session.scalars(
            sa.select(sa.cast(PromptSet.version, sa.Integer)).where(
                PromptSet.status == "published",
                PromptSet.id.not_in(order),
                PromptSet.id.not_in(list(_LATER.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_LATEST.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_SCENE_JUDGMENT.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_EPISODE_KNOWN_BY.NEW_SET_IDS.values())),
            )
        )
    ).all()
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 사실 추출 지시문·요약 비밀 표기·장면 추출 지시문 리비전의 것뿐이다(그 세트들의
    # 버전은 이 리비전보다 뒤다).
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


@pytest.mark.parametrize(("lane", "model"), _WRITING_PAIRS, ids=_ids(_WRITING_PAIRS))
async def test_seeded_sets_pass_publish_validation_but_for_the_later_summary_slot(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전은 행 집합·자리표시자를 바꾸지 않는다. 지금 코드 표는 뒤 리비전(요약 비밀 표기 슬롯)까지 기준이라 이 세트는 그
    슬롯 "누락"으로만 막히고, 그 슬롯이 있는 head 활성 세트(장면 추출 지시문 리비전의 것)는 통과한다."""
    prompt_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(
            prompt_set, await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)]), lane=lane, model=model
        )
    later_set, later_sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    assert later_set.id == _EPISODE_KNOWN_BY.NEW_SET_IDS[(lane, model)]
    _validate_prompt_draft_for_publish(later_set, later_sections, lane=lane, model=model)


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


def _set(*, lane: str, model: str, published_at: datetime) -> PromptSet:
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


async def _clone_as_draft(
    db_session: AsyncSession, set_id: uuid.UUID, lane: str, model: str, *, edit: dict[Key, str] | None = None
) -> uuid.UUID:
    """`set_id` 세트를 초안으로 복제한다. `edit` 는 그 키의 body 를 바꾼다."""
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


async def test_downgrade_then_upgrade_swaps_every_writing_chain_back_and_forth(db_session: AsyncSession) -> None:
    """되돌리면 여섯 체인 활성이 이전 세트(처음부터 옛 회상 본문)로, 레인만 보는 조회가 이전 Gemini 세트로 돌아가고, 다시
    올리면 같은 리터럴 세트가 활성이 된다."""
    connection = await db_session.connection()

    await connection.run_sync(_EPISODE_KNOWN_BY.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)

    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _WRITING_PAIRS:
        assert await _active_id(db_session, lane, model) == _PREVIOUS_SET_IDS[(lane, model)]
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, model)]) is None
    for lane in _LANES:
        assert await _lane_only_active_id(db_session, lane) == _PREVIOUS_SET_IDS[(lane, "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.body == _M.RECALL_BODY)
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _WRITING_PAIRS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


@pytest.mark.parametrize(("lane", "model"), _WRITING_PAIRS, ids=_ids(_WRITING_PAIRS))
async def test_upgrade_refuses_to_overwrite_a_recall_body_the_admin_edited(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """활성 회상 본문이 앞 리비전 문안과 한 글자라도 다르면 어드민이 고친 운영 문안이다 — 조용히 덮어쓰지 않고, 그 레인에는
    아무 세트도 넣지 않은 채 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_EPISODE_KNOWN_BY.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[(lane, model)],
            PromptSection.channel == "generation",
            PromptSection.slot == "memory_recall",
        )
        .values(body=PromptSection.body + " ")
    )

    with pytest.raises(RuntimeError, match=f"{lane}/{model}") as caught:
        await connection.run_sync(_M.seed_published_sets)
    assert "memory_recall" in str(caught.value)
    for other in _WRITING_MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, other)]) is None


async def test_upgrade_stops_when_the_recall_row_is_not_exactly_one(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_EPISODE_KNOWN_BY.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.delete(PromptSection).where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("character", "sonnet")],
            PromptSection.channel == "generation",
            PromptSection.slot == "memory_recall",
        )
    )

    with pytest.raises(RuntimeError, match=r"character/sonnet\] generation 채널의 memory_recall 행이 정확히 하나가 아니다\(0개"):
        await connection.run_sync(_M.seed_published_sets)
    for model in _WRITING_MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("character", model)]) is None


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 있다"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_the_lane_only_select_does_not_pick_gemini(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_EPISODE_KNOWN_BY.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    assert previous.published_at is not None
    db_session.add(_set(lane="story", model="sonnet", published_at=previous.published_at + timedelta(seconds=1)))
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[story\] 레인만 보는"):
        await connection.run_sync(_M.seed_published_sets)
    for model in ("gemini", "opus"):
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None


@pytest.mark.parametrize(("lane", "model"), _WRITING_PAIRS, ids=_ids(_WRITING_PAIRS))
async def test_downgrade_stops_when_the_admin_published_after_the_seed(
    db_session: AsyncSession, lane: PromptLane, model: str
) -> None:
    await _undo_later_revisions(db_session)
    seeded = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    assert seeded.published_at is not None
    db_session.add(_set(lane=lane, model=model, published_at=seeded.published_at + timedelta(seconds=1)))
    await db_session.flush()
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match=f"{lane}/{model}"):
        await connection.run_sync(_M.delete_seeded_rows)

    for pair in _WRITING_PAIRS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[pair]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _WRITING_PAIRS, ids=_ids(_WRITING_PAIRS))
async def test_patch_drafts_swaps_the_recall_body_in_place_and_the_draft_publishes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 초안(이전 활성 세트 복제)이 새 세트와 같은 행이 되고 그 체인의 게시 게이트를 통과한다.
    되돌리기는 회상 본문을 옛 문안으로 돌린다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS[(lane, model)], lane, model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [(lane, model)]

    assert _keyed(await _sections_of(db_session, draft_id)) == _expected_after(before)
    # 코드 표는 head 기준이라, 체인이 실제로 하듯 뒤 리비전(요약 비밀 표기 슬롯)의 초안 패치도 거친 뒤 게시 게이트를 태운다.
    assert await connection.run_sync(_LATEST._patch_drafts) == [(lane, model)]
    await connection.run_sync(_SCENE_JUDGMENT._patch_drafts)
    sections = await _sections_of(db_session, draft_id)
    _validate_prompt_draft_for_publish(await _get_set(db_session, draft_id), sections, lane=lane, model=model)

    # 되돌리기도 실제 순서대로 뒤 리비전부터.
    await connection.run_sync(_SCENE_JUDGMENT._delete_draft_rows)
    assert await connection.run_sync(_LATEST._delete_draft_rows) == [(lane, model)]
    assert await connection.run_sync(_M._delete_draft_rows) == [(lane, model)]
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_keeps_a_recall_body_edited_in_the_draft(db_session: AsyncSession) -> None:
    """초안에서 고치던 회상 문안은 그대로 둔다(배포를 멈추지도 않는다). 되돌리기도 고친 본문을 건드리지 않는다."""
    edited_recall = "운영자가 고치던 회상 문안\n{memory_recall_lines}"
    draft_id = await _clone_as_draft(
        db_session, _PREVIOUS_SET_IDS[("story", "opus")], "story", "opus", edit={_RECALL_KEY: edited_recall}
    )
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before

    assert await connection.run_sync(_M._delete_draft_rows) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before
