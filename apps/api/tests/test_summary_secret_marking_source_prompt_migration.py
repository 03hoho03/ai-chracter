"""요약 비밀 표기 슬롯 본문 끝에 미확인 주장의 출처 규칙 한 항목을 더하는 데이터 마이그레이션 `0c1a85bc5c2f`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 기억 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가 이미
`upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows`·`_delete_draft_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행에서 비밀 표기 슬롯 본문만 새 상수) — 마이그레이션의 행 조립 함수로 기대값을
만들면 그 함수가 틀려도 테스트가 같이 틀린다. 새 항목의 글은 이 파일에 옮겨 적지 않고 마이그레이션 상수에서 잘라 쓴다."""

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
from api.chat.prompt_builder import PromptLane, PromptNames, build_memory_summary_prompt, load_active_prompt_set
from api.db.models.chat import ChatMessage, ChatMessageRole
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


_M = _load("0c1a85bc5c2f")
# 소설 레인 세 체인에 구성안 문안을 심은 리비전의 세트 — 다른 레인과 무관하지만 전역 버전 번호를 이 리비전 뒤에서 이어
# 쓰므로 버전 차례를 보는 시험에서 뺀다.
_NOVEL_OUTLINE_SET_IDS: list[uuid.UUID] = list(_load("b389c2317149").NEW_SET_IDS.values()) + list(
    _load("174f78b92e5c").NEW_SET_IDS.values()  # 그 뒤 여러 문단 수정 문안을 심은 소설 레인 Gemini 세트도 같은 이유로 뺀다.
)
# 비밀 표기 슬롯을 만든 리비전 — 옛 본문의 출처다(그 뒤 이 슬롯을 바꾼 리비전이 없다).
_SECRET_MARKING = _load("0aeadefcf159")
# 이 리비전 직전 여덟 체인의 활성 세트(사실 추출 지시문 차례를 바꾼 리비전 — 그 사이의 리비전은 프롬프트를 게시하지 않는다).
_PREVIOUS = _load("c1f3945cb802")
# 이 리비전 뒤에 story 레인 네 체인에 장면 판정 지시문만 바꾼 새 세트를 게시하는 리비전. head 상태에서는 story 레인에서 그
# 세트들이 활성이라, "이 리비전 직후 상태"를 보는 테스트와 이 리비전을 되돌리는 테스트는 그 리비전을 먼저 되돌린다(실제
# downgrade 순서).
_LATER = _load("0f82ea9f9fa5")
# 그 뒤 채팅 두 레인 여덟 체인에 인상 생성 문안 채널을 더한 세트를 게시하는 리비전 — 여덟 체인의 head 활성이라 되돌릴
# 때는 이것부터다.
_IMPRESSION = _load("6558ab4d3dbc")

_LANES: tuple[PromptLane, ...] = ("story", "character")
_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")
_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [(lane, model) for lane in _LANES for model in _MODELS]
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = _PREVIOUS.NEW_SET_IDS

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_SLOT_KEY: Key = ("memory_summary", "both", "secret_marking", "")
_INSTRUCTION_KEY: Key = ("memory_summary", "both", "instruction", "")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 새 본문과 옛 본문의 지문 — 글자 하나가 바뀌어도 여기서 깨진다. 새 본문은 측정에서 고른 판의 파일과 같은 값이다.
_NEW_SLOT_MD5 = "b0f255b24fe38eed2638baa93832354a"
_OLD_SLOT_MD5 = "d4828aab8ab8ceee24c0f2787135930a"
# 새 판에만 있는 항목 한 줄 — 옛 판 뒤의 줄바꿈 다음부터 끝까지.
_ADDED_LINE = _M.SECRET_MARKING_BODY[len(_M.OLD_SECRET_MARKING_BODY) + 1 :]

_NAMES = PromptNames(persona_name="하늘", char_name=None)
_SUMMARY = "두 사람은 편의점에서 처음 만났다."


def _ids(pairs: list[tuple[PromptLane, PromptSetModelId]]) -> list[str]:
    return [f"{lane}-{model}" for lane, model in pairs]


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_after(before: dict[Key, Value]) -> dict[Key, Value]:
    """이전 행 그대로, 비밀 표기 슬롯 본문만 새 상수."""
    _old_body, conditional, order = before[_SLOT_KEY]
    return {**before, _SLOT_KEY: (_M.SECRET_MARKING_BODY, conditional, order)}


async def _active_id(db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane=lane, model=model))[0].id


async def _lane_only_active_id(db_session: AsyncSession, lane: PromptLane) -> uuid.UUID:
    connection = await db_session.connection()
    chosen: uuid.UUID = (await connection.execute(_M._LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane})).one().id
    return chosen


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


def _summary_body(sections: list[PromptSection], slot: str) -> str:
    (section,) = [s for s in sections if (s.channel, s.slot) == ("memory_summary", slot)]
    return section.body


def _turns() -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatMessageRole.USER, content="이전 메시지"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="이전 응답"),
    ]


async def _summary_prompt(
    db_session: AsyncSession, set_id: uuid.UUID, lane: PromptLane, room_people: list[str] | None
) -> str:
    """그 세트로 렌더한 요약 프롬프트. `room_people` 이 None 이면 스위치가 꺼진 호출과 같다(값이 비어 슬롯이 빠진다)."""
    sections = await _sections_of(db_session, set_id)
    prompt_set = await _get_set(db_session, set_id)
    return build_memory_summary_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=lane == "story",
        previous_summary=_SUMMARY,
        turns=_turns(),
        names=_NAMES,
        room_people=room_people,
    )


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_old_body_this_revision_expects_is_the_one_the_slot_revision_seeded() -> None:
    """운영 본문이 이 상수와 같을 때만 바꾼다 — 상수가 슬롯을 만든 리비전의 문안과 한 글자라도 다르면 모든 체인에서 멈춘다."""
    assert _M.OLD_SECRET_MARKING_BODY == _SECRET_MARKING.SECRET_MARKING_BODY
    assert _md5(_M.OLD_SECRET_MARKING_BODY) == _OLD_SLOT_MD5


def test_new_body_is_the_old_body_plus_one_item_with_the_same_placeholder() -> None:
    """앞 판 전체가 글자 그대로 남고 그 뒤에 줄바꿈과 항목 한 줄만 붙는다. 자리표시자는 앞 판과 같은 `room_people` 하나다 —
    그 이름이 빠지면 스위치가 꺼진 방에도 슬롯이 실리고, 다른 이름이 늘면 렌더가 깨진다. 끝에 줄바꿈이 없다(측정이 넣은 그대로)."""
    new, old = _M.SECRET_MARKING_BODY, _M.OLD_SECRET_MARKING_BODY
    assert _md5(new) == _NEW_SLOT_MD5
    assert new == old + "\n" + _ADDED_LINE
    assert _ADDED_LINE.startswith("- ") and "\n" not in _ADDED_LINE
    assert _ADDED_LINE not in old
    assert [name for _, name, _, _ in Formatter().parse(new) if name] == ["room_people"]
    assert new.count("{room_people}") == 1
    assert not new.endswith("\n")


def test_the_revision_seeds_exactly_eight_chains() -> None:
    assert sorted(_M.NEW_SET_IDS) == sorted(_PAIRS)
    assert len(set(_M.NEW_SET_IDS.values())) == 8


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_each_chain_is_active_at_its_seeded_set_with_the_new_slot_bytes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]
    _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    body = _summary_body(sections, "secret_marking")
    assert body == _M.SECRET_MARKING_BODY
    assert _md5(body) == _NEW_SLOT_MD5
    assert _ADDED_LINE in body


@pytest.mark.parametrize("lane", _LANES)
async def test_the_lane_only_select_picks_the_new_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """모델 열을 모르는 원시 SQL 이 레인만 보고 최신 게시본을 고를 때도 새 Gemini 세트를 집는다."""
    await _undo_later_revisions(db_session)
    assert await _lane_only_active_id(db_session, lane) == _M.NEW_SET_IDS[(lane, "gemini")]


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_new_set_is_the_previous_active_set_with_only_the_slot_changed(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이전 활성 세트의 행이 바이트 그대로 옮겨지고(비밀 표기 슬롯 본문만 다르다), 더하거나 빠진 행이 없다. 요약 지시문과 슬롯의
    conditional·order 도 그대로다. 라벨도 이전 활성 세트 것이다."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    new = _keyed(new_sections)
    # 다음 `_sections_of` 가 `expire_all` 로 이 객체들을 만료시키므로 그 전에 읽어 둔다(만료된 속성을 읽으면 동기 지연 로드다).
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)]))

    assert before[_SLOT_KEY][0] == _M.OLD_SECRET_MARKING_BODY
    assert new == _expected_after(before)
    assert new[_INSTRUCTION_KEY] == before[_INSTRUCTION_KEY]
    assert new[_SLOT_KEY][1] is True
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
                PromptSet.id.not_in(list(_LATER.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_IMPRESSION.NEW_SET_IDS.values())),
            )
        )
    ).all()
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 장면 판정 지시문 교체 리비전의 것뿐이다(그 세트들의 버전은 이 리비전보다 뒤다).
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_seeded_sets_pass_publish_validation(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전은 행 집합·자리표시자를 바꾸지 않는다. 지금 코드 표는 뒤 리비전(인상 생성 채널)까지 기준이라 이 세트는 그 채널
    "누락"으로만 막히고, 그 채널을 더한 head 활성 세트는 통과한다."""
    # 행을 먼저 읽는다: `_sections_of` 가 세션을 만료시키므로, 세트를 먼저 읽으면 검증이 동기 문맥에서 만료된 속성을 다시 읽으려다 실패한다.
    sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    prompt_set = await _get_set(db_session, _M.NEW_SET_IDS[(lane, model)])
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=model)
    later_set, later_sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    assert later_set.id == _IMPRESSION.NEW_SET_IDS[(lane, model)]
    _validate_prompt_draft_for_publish(later_set, later_sections, lane=lane, model=model)


# ---- 요약 프롬프트 ------------------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_switched_off_the_summary_prompt_is_byte_identical_to_the_previous_set(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """스위치가 꺼진 호출(이름 목록 없음)은 슬롯이 섹션째 빠져, 새 세트로 렌더한 요약 프롬프트가 이전 활성 세트로 렌더한 것과
    바이트까지 같다 — 운영 요약과 그 요약을 읽는 엔딩 판정·생성이 이 리비전으로 바뀌지 않는다."""
    new = await _summary_prompt(db_session, _M.NEW_SET_IDS[(lane, model)], lane, None)
    old = await _summary_prompt(db_session, _PREVIOUS_SET_IDS[(lane, model)], lane, None)
    assert new == old
    assert _ADDED_LINE not in new


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_switched_on_the_summary_prompt_carries_the_new_item(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """스위치가 켜지면 새 항목이 비밀 표기 슬롯 끝에 실린다 — 이전 세트로 렌더한 프롬프트에는 없다. 나머지는 그 한 줄을 뺀 것과
    같다."""
    new = await _summary_prompt(db_session, _M.NEW_SET_IDS[(lane, model)], lane, ["오태민", "Mina"])
    old = await _summary_prompt(db_session, _PREVIOUS_SET_IDS[(lane, model)], lane, ["오태민", "Mina"])
    assert _ADDED_LINE in new and _ADDED_LINE not in old
    assert new.replace("\n" + _ADDED_LINE, "", 1) == old


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
    """되돌리면 여덟 체인 활성이 이전 세트(처음부터 옛 본문)로, 레인만 보는 조회가 이전 Gemini 세트로 돌아가고, 다시 올리면
    같은 리터럴 세트가 활성이 된다."""
    connection = await db_session.connection()

    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _PAIRS:
        assert await _active_id(db_session, lane, model) == _PREVIOUS_SET_IDS[(lane, model)]
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, model)]) is None
        _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
        assert _summary_body(sections, "secret_marking") == _M.OLD_SECRET_MARKING_BODY
    for lane in _LANES:
        assert await _lane_only_active_id(db_session, lane) == _PREVIOUS_SET_IDS[(lane, "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.body == _M.SECRET_MARKING_BODY)
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _PAIRS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


async def test_upgrade_copies_a_summary_instruction_the_admin_edited(db_session: AsyncSession) -> None:
    """운영 story 요약 지시문처럼 어드민이 고쳐 게시한 지시문이 활성이어도 멈추지 않고 그 본문을 그대로 옮긴다 — 가정 검사와
    교체는 비밀 표기 슬롯만 본다. 검사가 지시문 본문을 견주게 바뀌면 여기서 `RuntimeError` 로 깨진다."""
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    edited = "운영자가 어드민에서 고쳐 게시한 요약 지시문"
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id.in_([_PREVIOUS_SET_IDS[("story", model)] for model in _MODELS]),
            PromptSection.channel == "memory_summary",
            PromptSection.slot == "instruction",
        )
        .values(body=edited)
    )

    await connection.run_sync(_M.seed_published_sets)

    for model in _MODELS:
        new = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[("story", model)]))
        before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[("story", model)]))
        assert new[_INSTRUCTION_KEY][0] == edited
        assert new[_SLOT_KEY][0] == _M.SECRET_MARKING_BODY
        assert new == _expected_after(before)


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_upgrade_refuses_to_overwrite_a_slot_body_the_admin_edited(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """활성 슬롯 본문이 앞 리비전 문안과 한 글자라도 다르면 어드민이 고친 운영 문안이다 — 조용히 덮어쓰지 않고, 그 레인에는 아무
    세트도 넣지 않은 채 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[(lane, model)],
            PromptSection.channel == "memory_summary",
            PromptSection.slot == "secret_marking",
        )
        .values(body=PromptSection.body + " ")
    )

    with pytest.raises(RuntimeError, match=f"{lane}/{model}") as caught:
        await connection.run_sync(_M.seed_published_sets)
    assert "memory_summary 채널의 secret_marking 본문이 앞 리비전이 심은 문안과 다르다" in str(caught.value)
    for other in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, other)]) is None


async def test_upgrade_stops_when_the_slot_row_is_not_exactly_one(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.delete(PromptSection).where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("character", "haiku")],
            PromptSection.channel == "memory_summary",
            PromptSection.slot == "secret_marking",
        )
    )

    with pytest.raises(
        RuntimeError, match=r"character/haiku\] memory_summary 채널의 secret_marking 행이 정확히 하나가 아니다\(0개"
    ):
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


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
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
        await connection.run_sync(_IMPRESSION.delete_seeded_rows)
        await connection.run_sync(_M.delete_seeded_rows)

    for pair in _PAIRS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[pair]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_patch_drafts_swaps_the_slot_body_in_place_and_the_draft_publishes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 초안(이전 활성 세트 복제)이 새 세트와 같은 행이 되고 그 체인의 게시 게이트를 통과한다.
    되돌리기는 슬롯 본문을 옛 문안으로 돌린다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS[(lane, model)], lane, model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [(lane, model)]

    assert _keyed(await _sections_of(db_session, draft_id)) == _expected_after(before)
    await connection.run_sync(_IMPRESSION._patch_drafts)
    sections = await _sections_of(db_session, draft_id)
    _validate_prompt_draft_for_publish(await _get_set(db_session, draft_id), sections, lane=lane, model=model)

    await connection.run_sync(_IMPRESSION._delete_draft_rows)
    assert await connection.run_sync(_M._delete_draft_rows) == [(lane, model)]
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_keeps_a_slot_body_edited_in_the_draft(db_session: AsyncSession) -> None:
    """초안에서 고치던 슬롯 본문은 그대로 둔다(배포를 멈추지도 않는다). 되돌리기도 고친 본문을 건드리지 않는다."""
    draft_id = await _clone_as_draft(
        db_session,
        _PREVIOUS_SET_IDS[("story", "haiku")],
        "story",
        "haiku",
        edit={_SLOT_KEY: "운영자가 고치던 비밀 표기 {room_people}"},
    )
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before

    assert await connection.run_sync(_M._delete_draft_rows) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before
