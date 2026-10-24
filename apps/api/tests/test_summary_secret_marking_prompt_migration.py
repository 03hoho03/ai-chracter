"""요약 채널에 비밀 표기 슬롯(`secret_marking`, conditional)을 더하는 데이터 마이그레이션 `0aeadefcf159`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 기억 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가 이미
`upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows`·`_delete_draft_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행에서 요약 채널의 지시문 뒤 행을 한 칸 밀고 새 행 하나) — 마이그레이션의 행 조립
함수로 기대값을 만들면 그 함수가 틀려도 테스트가 같이 틀린다."""

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


_M = _load("0aeadefcf159")
# 소설 레인 세 체인에 구성안 문안을 심은 리비전의 세트 — 다른 레인과 무관하지만 전역 버전 번호를 이 리비전 뒤에서 이어
# 쓰므로 버전 차례를 보는 시험에서 뺀다.
_NOVEL_OUTLINE_SET_IDS: list[uuid.UUID] = list(_load("b389c2317149").NEW_SET_IDS.values()) + list(
    _load("174f78b92e5c").NEW_SET_IDS.values()  # 그 뒤 여러 문단 수정 문안을 심은 소설 레인 Gemini 세트도 같은 이유로 뺀다.
)
# 그 뒤 story 레인 네 체인에 장면 헤더 판정 채널을 더한 세트를 게시하는 리비전 — 초안 게시 검사가 head 코드 표를 쓰므로
# story 초안은 이것도 거친다.
_SCENE_JUDGMENT = _load("0346abdbcc92")
# 이 리비전 직전 여덟 체인의 활성 세트(사실 추출 지시문만 바꾼 리비전 — 그 사이에 프롬프트를 게시한 리비전이 없다).
_PREVIOUS = _load("e4e407a62d03")
# 장면 헤더 판정 채널 리비전 뒤에 여덟 체인에 장면 추출 지시문만 바꾼 새 세트를 게시하는 리비전. head 상태에서는 그 뒤 리비전의
# 세트들이 활성이라, "이 리비전 직후 상태"를 보는 테스트와 이 리비전을 되돌리는 테스트는 뒤 리비전부터 먼저 되돌린다(실제
# downgrade 순서).
_LATER = _load("eb8d3cc6d5c2")
# 그 뒤 여덟 체인에 사실 추출 지시문만 바꾼 세트를 게시하는 리비전.
_FACT_KNOWN_BY_ORDER = _load("c1f3945cb802")
# 그 뒤 여덟 체인의 요약 비밀 표기 슬롯 본문에 미확인 주장의 출처 규칙을 더한 세트를 게시하는 리비전 — character 레인의
# head 활성이다.
_SOURCE_MARKING = _load("0c1a85bc5c2f")
# 그 뒤 story 레인 네 체인에 장면 판정 지시문만 바꾼 세트를 게시하는 리비전 — story 레인의 head 활성이라 되돌릴 때는 이것부터다.
_SCENE_INSTRUCTION_V2 = _load("0f82ea9f9fa5")
# 그 뒤 채팅 두 레인 여덟 체인에 인상 생성 문안 채널을 더한 세트를 게시하는 리비전 — 여덟 체인의 head 활성이라 되돌릴
# 때는 이것부터다.
_IMPRESSION = _load("6558ab4d3dbc")

_LANES: tuple[PromptLane, ...] = ("story", "character")
_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")
_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [(lane, model) for lane in _LANES for model in _MODELS]
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = _PREVIOUS.NEW_SET_IDS

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_NEW_KEY: Key = ("memory_summary", "both", "secret_marking", "")
_INSTRUCTION_KEY: Key = ("memory_summary", "both", "instruction", "")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 측정에서 고른 슬롯 문안의 지문 — 글자 하나가 바뀌어도 여기서 깨진다.
_SLOT_MD5 = "d4828aab8ab8ceee24c0f2787135930a"
# 이 리비전이 기대하는 요약 채널의 렌더 순서(앞)와 뒤.
_SLOTS_BEFORE = ["instruction", "user_name", "previous_summary", "turn_context"]
_SLOTS_AFTER = ["instruction", "secret_marking", "user_name", "previous_summary", "turn_context"]


def _ids(pairs: list[tuple[PromptLane, PromptSetModelId]]) -> list[str]:
    return [f"{lane}-{model}" for lane, model in pairs]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_after(before: dict[Key, Value]) -> dict[Key, Value]:
    """이전 행 그대로(요약 채널에서 지시문보다 뒤인 행만 order +1), 그리고 지시문 바로 뒤 새 행."""
    at = before[_INSTRUCTION_KEY][2] + 1
    moved = {
        key: (body, conditional, order + 1 if key[0] == "memory_summary" and order >= at else order)
        for key, (body, conditional, order) in before.items()
    }
    return {**moved, _NEW_KEY: (_M.SECRET_MARKING_BODY, True, at)}


def _summary_slots(sections: list[PromptSection]) -> list[str]:
    return [s.slot for s in select_sections_for_render(sections, channel="memory_summary", scope="story")]


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_SOURCE_MARKING.delete_seeded_rows)
    await connection.run_sync(_FACT_KNOWN_BY_ORDER.delete_seeded_rows)
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


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_slot_body_is_the_measured_wording_with_one_placeholder() -> None:
    """측정에서 고른 판이 바이트 그대로이고, 자리표시자는 `{room_people}` 하나다 — 이 값이 비면 conditional 로 섹션째 빠지므로
    값을 넘기지 않는 옛 코드와 스위치가 꺼진 새 코드는 이 슬롯을 싣지 않는다."""
    assert hashlib.md5(_M.SECRET_MARKING_BODY.encode()).hexdigest() == _SLOT_MD5
    assert [name for _, name, _, _ in Formatter().parse(_M.SECRET_MARKING_BODY) if name] == ["room_people"]
    assert _M.SECRET_MARKING_BODY.startswith("[비밀 표기]\n")
    assert "(이름·이름만 앎)" in _M.SECRET_MARKING_BODY


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_each_chain_is_active_at_its_seeded_set_with_the_slot_right_after_the_instruction(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    await _undo_later_revisions(db_session)
    # 장면 추출 지시문 리비전을 되돌린 뒤 story 레인의 활성은 이 세트를 바이트 그대로 옮긴 뒤 리비전(장면 헤더 판정 채널)의 세트다.
    head = _SCENE_JUDGMENT if lane == "story" else _M
    assert await _active_id(db_session, lane, model) == head.NEW_SET_IDS[(lane, model)]
    _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    assert _summary_slots(sections) == _SLOTS_AFTER
    (slot,) = [s for s in sections if (s.channel, s.slot) == ("memory_summary", "secret_marking")]
    assert (slot.scope, slot.variant, slot.conditional) == ("both", "", True)
    assert hashlib.md5(slot.body.encode()).hexdigest() == _SLOT_MD5


@pytest.mark.parametrize("lane", _LANES)
async def test_the_lane_only_select_picks_the_new_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """모델 열을 모르는 원시 SQL 이 레인만 보고 최신 게시본을 고를 때도 새 Gemini 세트를 집는다."""
    await _undo_later_revisions(db_session)
    head = _SCENE_JUDGMENT if lane == "story" else _M  # story 는 뒤 리비전의 Gemini 세트가 활성이다
    assert await _lane_only_active_id(db_session, lane) == head.NEW_SET_IDS[(lane, "gemini")]


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_new_set_is_the_previous_active_set_plus_the_slot(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이전 활성 세트의 행이 바이트 그대로 옮겨지고(요약 채널의 지시문 뒤 행만 order 가 한 칸 밀린다), 새 행 하나만 더해진다.
    라벨도 이전 활성 세트 것이다."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    new = _keyed(new_sections)
    # 다음 `_sections_of` 가 `expire_all` 로 이 객체들을 만료시키므로 그 전에 읽어 둔다(만료된 속성을 읽으면 동기 지연 로드다).
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    previous_sections = await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    assert _summary_slots(previous_sections) == _SLOTS_BEFORE
    before = _keyed(previous_sections)

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
    """새 Gemini 세트는 원본보다 나중, 나머지 세 체인의 새 세트는 (그 체인 이전 활성, 새 Gemini) 의 중간값."""
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
    order = [_M.NEW_SET_IDS[pair] for pair in _PAIRS]
    versions = [int((await _get_set(db_session, set_id)).version or "0") for set_id in order]
    others = (
        await db_session.scalars(
            sa.select(sa.cast(PromptSet.version, sa.Integer)).where(
                PromptSet.status == "published",
                PromptSet.id.not_in(order), PromptSet.id.not_in(_NOVEL_OUTLINE_SET_IDS),
                PromptSet.id.not_in(list(_SCENE_JUDGMENT.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_LATER.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_FACT_KNOWN_BY_ORDER.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_SOURCE_MARKING.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_SCENE_INSTRUCTION_V2.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_IMPRESSION.NEW_SET_IDS.values())),
            )
        )
    ).all()
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 뒤 다섯 리비전(장면 헤더 판정 채널, 장면 추출 지시문, 사실 추출 지시문 차례,
    # 이 슬롯 본문에 출처 규칙을 더한 리비전, 장면 판정 지시문 교체)의 것뿐이다(그 세트들의 버전은 이 리비전보다 뒤다).
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_seeded_sets_pass_publish_validation_and_the_previous_sets_no_longer_do(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """새 세트는 뒤 리비전(인상 생성 채널)의 행만 더하면 지금 코드의 게시 검증(슬롯 집합·자리표시자 허용 목록)을 통과한다.
    이전 세트는 이 슬롯이 없어 "누락"으로 막힌다 — 코드 표와 시드가 같이 움직였다는 증거다."""
    await _undo_later_revisions(db_session)
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    sections = [
        *sections,
        *(
            PromptSection(
                prompt_set_id=prompt_set.id, channel=c, scope=s, slot=sl, variant=v, body=b, conditional=cond, order=o
            )
            for c, s, sl, v, b, cond, o in _IMPRESSION.NEW_ROWS
        ),
    ]
    # 장면 추출 지시문 리비전을 되돌린 뒤 story 레인의 활성은 뒤 리비전(장면 헤더 판정 채널)의 세트다 — 이 세트는 그 채널
    # "누락"으로 막히고, 그 채널만 더한 뒤 리비전의 세트가 통과한다.
    if lane == "story":
        assert prompt_set.id == _SCENE_JUDGMENT.NEW_SET_IDS[(lane, model)]
        _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=model)
        prompt_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
        with pytest.raises(HTTPException):
            _validate_prompt_draft_for_publish(
                prompt_set, await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)]), lane=lane, model=model
            )
    else:
        assert prompt_set.id == _M.NEW_SET_IDS[(lane, model)]
        _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=model)

    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[(lane, model)])
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(
            previous, await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)]), lane=lane, model=model
        )


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


async def _clone_as_draft(db_session: AsyncSession, set_id: uuid.UUID, lane: str, model: str) -> uuid.UUID:
    """`set_id` 세트를 초안으로 복제한다."""
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


async def test_downgrade_then_upgrade_swaps_every_chain_back_and_forth(db_session: AsyncSession) -> None:
    """되돌리면 여덟 체인 활성이 이전 세트(처음부터 이 슬롯이 없다)로, 레인만 보는 조회가 이전 Gemini 세트로 돌아가고, 다시
    올리면 같은 리터럴 세트가 활성이 된다."""
    connection = await db_session.connection()

    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)

    await connection.run_sync(_SOURCE_MARKING.delete_seeded_rows)
    await connection.run_sync(_FACT_KNOWN_BY_ORDER.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)

    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _PAIRS:
        assert await _active_id(db_session, lane, model) == _PREVIOUS_SET_IDS[(lane, model)]
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, model)]) is None
    for lane in _LANES:
        assert await _lane_only_active_id(db_session, lane) == _PREVIOUS_SET_IDS[(lane, "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.slot == "secret_marking")
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _PAIRS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


async def test_upgrade_copies_an_instruction_the_admin_edited(db_session: AsyncSession) -> None:
    """운영 story 요약 지시문처럼 어드민이 고쳐 게시한 지시문이 활성이면 멈추지 않고 그 본문을 그대로 옮긴다 — 가정 검사는
    본문이 아니라 슬롯 모양만 본다."""
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_SOURCE_MARKING.delete_seeded_rows)
    await connection.run_sync(_FACT_KNOWN_BY_ORDER.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    edited = "운영자가 어드민에서 고쳐 게시한 요약 지시문"
    for model in _MODELS:
        await db_session.execute(
            sa.update(PromptSection)
            .where(
                PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("story", model)],
                PromptSection.channel == "memory_summary",
                PromptSection.slot == "instruction",
            )
            .values(body=edited)
        )

    await connection.run_sync(_M.seed_published_sets)

    for model in _MODELS:
        _prompt_set, sections = await load_active_prompt_set(db_session, lane="story", model=model)
        (instruction,) = [s for s in sections if (s.channel, s.slot) == ("memory_summary", "instruction")]
        assert instruction.body == edited
        assert _summary_slots(sections) == _SLOTS_AFTER


@pytest.mark.parametrize(
    "change",
    [
        pytest.param("drop_user_name", id="missing-row"),
        pytest.param("swap_order", id="reordered"),
        pytest.param("already_there", id="slot-already-present"),
    ],
)
async def test_upgrade_stops_when_the_summary_layout_is_not_the_expected_one(
    db_session: AsyncSession, change: str
) -> None:
    """요약 채널이 기대한 슬롯 집합·순서가 아니면(행이 빠짐, 어드민이 순서를 바꿈, 이 슬롯이 이미 있음) 그 레인에는 아무 세트도
    넣지 않은 채 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_SOURCE_MARKING.delete_seeded_rows)
    await connection.run_sync(_FACT_KNOWN_BY_ORDER.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    target = _PREVIOUS_SET_IDS[("character", "opus")]
    in_summary = (PromptSection.prompt_set_id == target, PromptSection.channel == "memory_summary")
    if change == "drop_user_name":
        await db_session.execute(sa.delete(PromptSection).where(*in_summary, PromptSection.slot == "user_name"))
    elif change == "swap_order":
        rows = {s.slot: s.order for s in await _sections_of(db_session, target) if s.channel == "memory_summary"}
        for slot, other in (("user_name", "previous_summary"), ("previous_summary", "user_name")):
            await db_session.execute(
                sa.update(PromptSection).where(*in_summary, PromptSection.slot == slot).values(order=rows[other])
            )
    else:
        db_session.add(
            PromptSection(
                prompt_set_id=target,
                channel="memory_summary",
                scope="both",
                slot="secret_marking",
                variant="",
                body=_M.SECRET_MARKING_BODY,
                conditional=True,
                order=99,
            )
        )
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[character/opus\] memory_summary 채널의 슬롯 모양이"):
        await connection.run_sync(_M.seed_published_sets)
    for model in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("character", model)]) is None


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 있다"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_the_lane_only_select_does_not_pick_gemini(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_SOURCE_MARKING.delete_seeded_rows)
    await connection.run_sync(_FACT_KNOWN_BY_ORDER.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    assert previous.published_at is not None
    db_session.add(_set(lane="story", model="sonnet", published_at=previous.published_at + timedelta(seconds=1)))
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[story\] 레인만 보는"):
        await connection.run_sync(_M.seed_published_sets)
    for model in ("gemini", "opus", "haiku"):
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_downgrade_stops_when_the_admin_published_after_the_seed(
    db_session: AsyncSession, lane: PromptLane, model: str
) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_SOURCE_MARKING.delete_seeded_rows)
    await connection.run_sync(_FACT_KNOWN_BY_ORDER.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_SCENE_JUDGMENT.delete_seeded_rows)
    seeded = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    assert seeded.published_at is not None
    db_session.add(_set(lane=lane, model=model, published_at=seeded.published_at + timedelta(seconds=1)))
    await db_session.flush()

    with pytest.raises(RuntimeError, match=f"{lane}/{model}"):
        await connection.run_sync(_IMPRESSION.delete_seeded_rows)
        await connection.run_sync(_M.delete_seeded_rows)

    for pair in _PAIRS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[pair]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_patch_drafts_adds_the_slot_in_place_and_the_draft_publishes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 초안(이전 활성 세트 복제)이 새 세트와 같은 행이 되고 그 체인의 게시 게이트를 통과한다.
    되돌리기는 그 행을 지우고 뒤 행 order 를 되돌린다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS[(lane, model)], lane, model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [(lane, model)]

    # 코드 표는 head 기준이라 story 초안은 뒤 리비전(장면 헤더 판정 채널)의 패치도 거친 뒤 게시 게이트를 태운다.
    await connection.run_sync(_SCENE_JUDGMENT._patch_drafts)

    sections = await _sections_of(db_session, draft_id)
    assert {key: value for key, value in _keyed(sections).items() if key[0] != "scene_judgment"} == _expected_after(
        before
    )
    await connection.run_sync(_IMPRESSION._patch_drafts)
    sections = await _sections_of(db_session, draft_id)
    _validate_prompt_draft_for_publish(await _get_set(db_session, draft_id), sections, lane=lane, model=model)

    await connection.run_sync(_IMPRESSION._delete_draft_rows)
    await connection.run_sync(_SCENE_JUDGMENT._delete_draft_rows)

    assert await connection.run_sync(_M._delete_draft_rows) == [(lane, model)]
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_leaves_a_draft_with_another_summary_layout(db_session: AsyncSession) -> None:
    """초안에서 요약 채널 모양을 바꾸던 중이면(행을 지움) 그대로 둔다 — 배포를 멈추지도 않는다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS[("story", "haiku")], "story", "haiku")
    await db_session.execute(
        sa.delete(PromptSection).where(
            PromptSection.prompt_set_id == draft_id,
            PromptSection.channel == "memory_summary",
            PromptSection.slot == "user_name",
        )
    )
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == []

    assert _keyed(await _sections_of(db_session, draft_id)) == before
