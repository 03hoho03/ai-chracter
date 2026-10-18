"""관계·사실 기억 추출 채널과 사실 슬롯을 채팅 두 레인의 여덟 체인에 심고, 장면 추출 지시문·회상 섹션 문안을 바꾸는 데이터
마이그레이션 `5cab2abe4e7b`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_memory_episode_prompt_migration.py`와 같은 방식). 세션 스코프 스키마
(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·
`_patch_drafts`·`delete_seeded_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행 + 새 행, 회상 슬롯부터 뒤의 생성 행만 order +1, 바꾸는 두 본문만 새 상수)
— 마이그레이션의 행 조립 함수로 기대값을 만들면 그 함수가 틀려도 테스트가 같이 틀린다.

사실 추출 지시문과 장면 추출 새 지시문은 측정에서 다듬은 판을 바이트 그대로 옮긴 것이어야 한다. 그 원본 파일은 저장소에
없으므로(측정 산출물은 추적하지 않는다) 원본의 해시와 길이를 여기 적어 둔다."""

import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
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


_M = _load("5cab2abe4e7b")
# 이 리비전 직전의 활성 세트 — 여덟 체인 모두 장면 기억 문안 리비전의 세트다(그 사이에 프롬프트를 게시한 리비전이 없다).
_EPISODE_MIGRATION = _load("fc6f0e134782")
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = _EPISODE_MIGRATION.NEW_SET_IDS
# 이 리비전 뒤에 글을 쓰는 여섯 체인에 회상 문안만 바꾼 새 세트를 게시하는 리비전. head 상태에서는 그 세트들이 활성이라,
# "이 리비전 직후 상태"를 보는 테스트와 이 리비전을 되돌리는 테스트는 그 리비전을 먼저 되돌린다(실제 downgrade 순서).
_LATER = _load("726aad108167")
# 그 뒤 여덟 체인에 사실 추출 지시문만 바꾼 새 세트를 게시하는 리비전.
_LATEST = _load("e4e407a62d03")
# 그 뒤 여덟 체인의 요약 채널에 비밀 표기 슬롯을 더한 새 세트를 게시하는 리비전 — 되돌릴 때는 이것부터 되돌린다. 초안 게시
# 검사가 head 코드 표를 쓰므로 초안은 이것도 거친다.
_SECRET_MARKING = _load("0aeadefcf159")
# 그 뒤 story 레인 네 체인에 장면 헤더 판정 채널을 더한 세트를 게시하는 리비전 — story 레인의 head 활성이라 되돌릴 때는
# 이것부터다. 초안 게시 검사가 head 코드 표를 쓰므로 story 초안은 이것도 거친다.
_SCENE_JUDGMENT = _load("0346abdbcc92")

_LANES: tuple[PromptLane, ...] = ("story", "character")
_WRITING_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")
_ALL_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [
    (lane, model) for lane in _LANES for model in (*_WRITING_MODELS, "haiku")
]
_WRITING_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [
    (lane, model) for lane in _LANES for model in _WRITING_MODELS
]

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

# 측정 하네스가 쓴 사실 추출 지시문 파일(끝 개행 하나를 뗀 본문)과 장면 추출 새 지시문 파일의 지문.
_FACT_INSTRUCTION_SHA256 = "9e74a07ccd89df1d5cc972949a4835fe56c1af337ca74b6d3beaa341d39ba545"
_FACT_INSTRUCTION_BYTES = 9799
_EPISODE_INSTRUCTION_MD5 = "751604bb8576cfa3103a6410b93c91b7"
_EPISODE_INSTRUCTION_BYTES = 3102

# 하네스의 조립(지시문 → 이름 한 줄 → 기존 키 → 접힌 대화)과 같은 모양이 되는 행. 기존 키 섹션은 conditional 이 아니다 — 첫
# 구간에도 머리글과 "(없음)"이 실려야 측정한 프롬프트와 같다.
_FACT_ROWS: dict[Key, Value] = {
    ("memory_fact", "both", "instruction", ""): (_M.FACT_INSTRUCTION_BODY, False, 0),
    ("memory_fact", "both", "user_name", ""): ("사용자의 이야기 속 이름: {user_name}", True, 1),
    ("memory_fact", "both", "existing_facts", ""): ("[기존 키]\n{existing_facts}", False, 2),
    ("memory_fact", "both", "turn_context", ""): ("[접힌 대화]\n{turn_lines}", False, 3),
}
_EPISODE_INSTRUCTION_KEY: Key = ("memory_episode", "both", "instruction", "")
_RECALL_KEY: Key = ("generation", "both", "memory_recall", "")
_FACTS_KEY: Key = ("generation", "both", "memory_facts", "")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")


def _ids(pairs: list[tuple[PromptLane, PromptSetModelId]]) -> list[str]:
    return [f"{lane}-{model}" for lane, model in pairs]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_after(before: dict[Key, Value], model: str) -> dict[Key, Value]:
    """이전 행 + 새 행. 장면 추출 지시문은 본문만 새 상수로 바뀐다. 글을 쓰는 체인은 회상 슬롯 자리부터 뒤의 생성 행을 하나씩
    밀고 그 자리에 사실 슬롯을 두며, 회상 본문도 새 상수로 바뀐다."""
    expected = dict(before)
    _old_body, conditional, order = before[_EPISODE_INSTRUCTION_KEY]
    expected[_EPISODE_INSTRUCTION_KEY] = (_M.EPISODE_INSTRUCTION_BODY, conditional, order)
    if model != "haiku":
        recall_order = before[_RECALL_KEY][2]
        for key, (body, conditional, order) in before.items():
            if key[0] == "generation" and order >= recall_order:
                expected[key] = (body, conditional, order + 1)
        expected[_RECALL_KEY] = (_M.RECALL_BODY, True, recall_order + 1)
        expected[_FACTS_KEY] = (_M.FACTS_BODY, True, recall_order)
    return {**expected, **_FACT_ROWS}


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_SECRET_MARKING.delete_seeded_rows)
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


def test_fact_instruction_is_the_measured_text_byte_for_byte() -> None:
    body = _M.FACT_INSTRUCTION_BODY.encode()
    assert len(body) == _FACT_INSTRUCTION_BYTES
    assert hashlib.sha256(body).hexdigest() == _FACT_INSTRUCTION_SHA256


def test_episode_instruction_is_the_measured_text_and_keeps_numbers_and_times_verbatim() -> None:
    body = _M.EPISODE_INSTRUCTION_BODY.encode()
    assert len(body) == _EPISODE_INSTRUCTION_BYTES
    assert hashlib.md5(body).hexdigest() == _EPISODE_INSTRUCTION_MD5
    assert "날짜·시각·숫자·값은 원문 표기 그대로 쓰고 어림하지 않는다" in _M.EPISODE_INSTRUCTION_BODY
    assert _M.EPISODE_INSTRUCTION_BODY != _EPISODE_MIGRATION.EPISODE_INSTRUCTION_BODY


def test_old_bodies_this_revision_expects_are_the_ones_the_episode_revision_seeded() -> None:
    """운영 본문이 이 상수와 같을 때만 바꾼다 — 상수가 앞 리비전 문안과 한 글자라도 다르면 모든 체인에서 멈춘다."""
    assert _M.OLD_EPISODE_INSTRUCTION_BODY == _EPISODE_MIGRATION.EPISODE_INSTRUCTION_BODY
    assert _M.OLD_RECALL_BODY == _EPISODE_MIGRATION.RECALL_BODY


def test_facts_section_explains_its_tags_and_priority_within_the_length_budget() -> None:
    body = _M.FACTS_BODY
    header, _, rest = body.partition("\n")
    assert header.startswith("[") and header.endswith("]")
    assert body.endswith("\n{memory_fact_lines}")
    assert body.count("{") == 1
    assert len(body.replace("{memory_fact_lines}", "")) <= 300
    assert "지금까지 확인된 인물 관계와 사실이다" in rest
    for tag in ("(사실 아님으로 밝혀짐)", "만 앎)", "의 말)", "(사용자의 말)"):
        assert tag in rest, tag
    assert "확인된 사실이 아니" in rest
    assert "꺼내 말할 필요" in rest
    assert _in_order(
        rest,
        [
            "작품 설정",
            "키워드북",
            "[현재 상황]",
            "[대화 기록]",
            "[기억 노트]",
            "[지금까지의 이야기]",
            "이 섹션",
            "[지난 기억",
        ],
    )


def test_recall_section_gains_the_user_tag_and_the_facts_section_in_its_priority() -> None:
    """바뀌는 것은 사용자 꼬리표 한 구절과 우선순위 줄에 사실 섹션이 끼는 것뿐이고, 나머지 문장은 그대로다."""
    old, new = _EPISODE_MIGRATION.RECALL_BODY, _M.RECALL_BODY
    facts_header = _M.FACTS_BODY.partition("\n")[0]

    assert new.startswith(old.split("다른 정보와")[0])
    assert new.endswith("\n{memory_recall_lines}")
    assert "작품 설정·키워드북·현재 상황 정보도 이 기억보다" in new
    assert '"(인물의 말)"로 표시된 내용은 그때 인물이 그렇게 말했다는 뜻이지 확인된 사실이 아니다.' in new
    assert "(사용자의 말)" in new and "(사용자의 말)" not in old
    priority = new[new.index("이 순서로 따른다") :]
    assert _in_order(priority, ["[대화 기록]", "[기억 노트]", "[지금까지의 이야기]", facts_header, "이 기억"])


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_each_chain_is_active_at_its_seeded_set(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


@pytest.mark.parametrize("lane", _LANES)
async def test_the_lane_only_select_picks_the_new_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """모델 열을 모르는 원시 SQL 이 레인만 보고 최신 게시본을 고를 때도 새 Gemini 세트를 집는다."""
    await _undo_later_revisions(db_session)
    assert await _lane_only_active_id(db_session, lane) == _M.NEW_SET_IDS[(lane, "gemini")]


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_new_set_is_the_previous_active_set_plus_the_new_rows(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이전 활성 세트의 행이 바이트 그대로 옮겨지고(바꾸는 두 본문과 밀리는 order 만 다르다), 새 행만 더해진다. 라벨도 이전
    활성 세트 것이다."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    new = _keyed(new_sections)
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)]))

    assert new == _expected_after(before, model)
    assert (_FACTS_KEY in new) == (model != "haiku")
    assert all(section_id == _M._section_id("", lane, model, *key) for section_id, key in ids.items())

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    old_set = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    assert (this_set.lane, this_set.model, this_set.status) == (lane, model, "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(old_set, a) for a in _LABELS]


@pytest.mark.parametrize(
    ("lane", "follower"), [("story", "keyword_notes"), ("character", "final_frame")], ids=["story", "character"]
)
@pytest.mark.parametrize("model", _WRITING_MODELS)
async def test_facts_slot_renders_between_history_and_recall(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId, follower: str
) -> None:
    sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    slots = [s.slot for s in select_sections_for_render(sections, channel="generation", scope=lane)]

    assert "memory_facts" in slots
    at = slots.index("memory_facts")
    assert slots[at - 1 : at + 3] == ["history", "memory_facts", "memory_recall", follower]


@pytest.mark.parametrize("lane", _LANES)
async def test_new_sets_are_published_in_the_window_of_both_active_rules(
    db_session: AsyncSession, lane: PromptLane
) -> None:
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
                PromptSet.id.not_in(list(_LATEST.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_SECRET_MARKING.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_SCENE_JUDGMENT.NEW_SET_IDS.values())),
            )
        )
    ).all()
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 회상 문안·사실 추출 지시문·요약 비밀 표기 리비전의 것뿐이다(그 세트들의 버전은
    # 이 리비전보다 뒤다).
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_seeded_sets_pass_publish_validation_and_the_previous_sets_no_longer_do(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """게시 검증의 기대 집합·허용 플레이스홀더와 시드가 맞물린다 — 어긋나면 운영자가 그 체인을 손대는 순간 게시가 막힌다. 새
    행이 없는 이전 세트는 이제 슬롯 집합 검사에 막힌다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=model)

    previous_sections = await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    with pytest.raises(HTTPException) as caught:
        _validate_prompt_draft_for_publish(previous, previous_sections, lane=lane, model=model)
    assert cast(dict[str, object], caught.value.detail)["rule"] == "R-1"


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


async def test_downgrade_then_upgrade_swaps_every_chain_back_and_forth(db_session: AsyncSession) -> None:
    """되돌리면 여덟 체인 활성이 이전 세트로, 레인만 보는 조회가 이전 Gemini 세트로 돌아가고(이전 세트의 장면 추출 지시문·회상
    본문은 처음부터 옛 문안이다), 다시 올리면 같은 리터럴 세트가 활성이 된다."""
    connection = await db_session.connection()

    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)

    await connection.run_sync(_SECRET_MARKING.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _ALL_PAIRS:
        assert await _active_id(db_session, lane, model) == _PREVIOUS_SET_IDS[(lane, model)]
    for lane in _LANES:
        assert await _lane_only_active_id(db_session, lane) == _PREVIOUS_SET_IDS[(lane, "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(PromptSection)
        .where(sa.or_(PromptSection.channel == "memory_fact", PromptSection.slot == "memory_facts"))
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _ALL_PAIRS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


async def test_upgrade_copies_the_operators_edited_text_not_the_seed(db_session: AsyncSession) -> None:
    """어드민이 고쳐 게시한 다른 문안(요약 지시문)은 새 세트에 그대로 실린다 — 바꾸는 것은 두 본문뿐이다."""
    connection = await db_session.connection()
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_SECRET_MARKING.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    instruction_key: Key = ("memory_summary", "both", "instruction", "")
    edited_body = "운영자가 고친 요약 지시문"
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("story", "sonnet")],
            PromptSection.channel == "memory_summary",
            PromptSection.slot == "instruction",
        )
        .values(body=edited_body)
    )
    edited = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[("story", "sonnet")]))

    await connection.run_sync(_M.seed_published_sets)

    new = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[("story", "sonnet")]))
    assert new == _expected_after(edited, "sonnet")
    assert new[instruction_key][0] == edited_body


async def test_upgrade_copies_each_chains_own_labels(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_SECRET_MARKING.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.id == _PREVIOUS_SET_IDS[("character", "opus")]).values(user_label="독자")
    )

    await connection.run_sync(_M.seed_published_sets)

    db_session.expire_all()
    assert (await _get_set(db_session, _M.NEW_SET_IDS[("character", "opus")])).user_label == "독자"
    assert (await _get_set(db_session, _M.NEW_SET_IDS[("character", "gemini")])).user_label != "독자"


@pytest.mark.parametrize(
    ("lane", "model", "channel", "slot"),
    [
        pytest.param("story", "haiku", "memory_episode", "instruction", id="episode-instruction"),
        pytest.param("character", "opus", "generation", "memory_recall", id="recall"),
    ],
)
async def test_upgrade_refuses_to_overwrite_a_body_the_admin_edited(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId, channel: str, slot: str
) -> None:
    """바꾸려는 본문이 앞 리비전 문안과 한 글자라도 다르면 어드민이 고친 운영 문안이다 — 조용히 덮어쓰지 않고, 그 레인에는 아무
    세트도 넣지 않은 채 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_SECRET_MARKING.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[(lane, model)],
            PromptSection.channel == channel,
            PromptSection.slot == slot,
        )
        .values(body=PromptSection.body + " ")
    )

    with pytest.raises(RuntimeError, match=f"{lane}/{model}") as caught:
        await connection.run_sync(_M.seed_published_sets)
    assert slot in str(caught.value)
    for other in (*_WRITING_MODELS, "haiku"):
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, other)]) is None


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 있다"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_the_lane_only_select_does_not_pick_gemini(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_SECRET_MARKING.delete_seeded_rows)
    await connection.run_sync(_LATEST.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    assert previous.published_at is not None
    db_session.add(_set(lane="story", model="sonnet", published_at=previous.published_at + timedelta(seconds=1)))
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[story\] 레인만 보는"):
        await connection.run_sync(_M.seed_published_sets)
    for model in ("gemini", "opus", "haiku"):
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
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

    for pair in _ALL_PAIRS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[pair]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _ALL_PAIRS, ids=_ids(_ALL_PAIRS))
async def test_patch_drafts_rewrites_the_draft_in_place_and_the_draft_publishes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 초안(이전 활성 세트 복제)이 새 세트와 같은 모양이 되고 그 체인의 게시 게이트를 통과한다.
    되돌리기는 초안의 새 행을 지우고 order 와 두 본문을 되돌린다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS[(lane, model)], lane, model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [(lane, model)]

    assert _keyed(await _sections_of(db_session, draft_id)) == _expected_after(before, model)
    # 코드 표는 head 기준이라, 체인이 실제로 하듯 뒤 리비전(요약 비밀 표기 슬롯)의 초안 패치도 거친 뒤 게시 게이트를 태운다.
    assert await connection.run_sync(_SECRET_MARKING._patch_drafts) == [(lane, model)]
    await connection.run_sync(_SCENE_JUDGMENT._patch_drafts)
    sections = await _sections_of(db_session, draft_id)
    draft = await _get_set(db_session, draft_id)
    _validate_prompt_draft_for_publish(draft, sections, lane=lane, model=model)

    # 되돌리기도 실제 순서대로 뒤 리비전부터.
    await connection.run_sync(_SCENE_JUDGMENT._delete_draft_rows)
    assert await connection.run_sync(_SECRET_MARKING._delete_draft_rows) == [(lane, model)]
    await connection.run_sync(_M._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_raises_when_the_draft_already_has_the_rows(db_session: AsyncSession) -> None:
    await _clone_as_draft(db_session, _M.NEW_SET_IDS[("character", "haiku")], "character", "haiku")
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match="character/haiku 초안"):
        await connection.run_sync(_M._patch_drafts)


async def test_patch_drafts_keeps_a_body_edited_in_the_draft_and_still_adds_the_new_rows(
    db_session: AsyncSession,
) -> None:
    """초안에서 고치던 회상 문안은 그대로 두고(배포를 멈추지도 않는다) 새 행은 더한다. 고치지 않은 장면 추출 지시문은 새
    문안으로 바뀐다. 되돌리기도 고친 본문을 건드리지 않는다."""
    edited_recall = "운영자가 고치던 회상 문안\n{memory_recall_lines}"
    draft_id = await _clone_as_draft(
        db_session,
        _PREVIOUS_SET_IDS[("story", "gemini")],
        "story",
        "gemini",
        edit={_RECALL_KEY: edited_recall},
    )
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [("story", "gemini")]

    expected = _expected_after(before, "gemini")
    expected[_RECALL_KEY] = (edited_recall, True, expected[_RECALL_KEY][2])
    assert _keyed(await _sections_of(db_session, draft_id)) == expected

    await connection.run_sync(_M._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before
