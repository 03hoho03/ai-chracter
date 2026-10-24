"""사실 추출 지시문의 비밀 규칙을 아는 인물 차례 목록으로 바꾸는 데이터 마이그레이션 `c1f3945cb802`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 기억 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가 이미
`upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows`·`_delete_draft_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행에서 사실 추출 지시문만 새 상수) — 마이그레이션의 행 조립 함수로 기대값을 만들면
그 함수가 틀려도 테스트가 같이 틀린다."""

import difflib
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
from api.chat.memory_knowledge import USER_INSTRUCTION_WORD
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


_M = _load("c1f3945cb802")
# 소설 레인 세 체인에 구성안 문안을 심은 리비전의 세트 — 다른 레인과 무관하지만 전역 버전 번호를 이 리비전 뒤에서 이어
# 쓰므로 버전 차례를 보는 시험에서 뺀다.
_NOVEL_OUTLINE_SET_IDS: list[uuid.UUID] = list(_load("b389c2317149").NEW_SET_IDS.values()) + list(
    _load("174f78b92e5c").NEW_SET_IDS.values()  # 그 뒤 여러 문단 수정 문안을 심은 소설 레인 Gemini 세트도 같은 이유로 뺀다.
)
# 사실 추출 지시문을 마지막으로 바꾼 리비전 — 옛 지시문의 출처다.
_FACT_TEXT_MIGRATION = _load("e4e407a62d03")
# 이 리비전 직전 여덟 체인의 활성 세트(장면 추출 지시문만 바꾼 리비전 — 그 사이에 프롬프트를 게시한 리비전이 없다). 이 리비전이
# 그대로 옮겨야 하는 장면 추출 지시문의 출처이기도 하다.
_EPISODE_KNOWN_BY = _load("eb8d3cc6d5c2")
# 이 리비전 뒤에 여덟 체인의 요약 비밀 표기 슬롯 본문만 바꾼 새 세트를 게시하는 리비전 — character 레인의 head 활성이다.
# "이 리비전 직후 상태"를 보는 테스트와 이 리비전을 되돌리는 테스트는 뒤 리비전부터 먼저 되돌린다(실제 downgrade 순서).
_LATER = _load("0c1a85bc5c2f")
# 그 뒤 story 레인 네 체인에 장면 판정 지시문만 바꾼 세트를 게시하는 리비전 — story 레인의 head 활성이라 되돌릴 때는 이것부터다.
_SCENE_INSTRUCTION_V2 = _load("0f82ea9f9fa5")
# 그 뒤 채팅 두 레인 여덟 체인에 인상 생성 문안 채널을 더한 세트를 게시하는 리비전 — 여덟 체인의 head 활성이라 되돌릴
# 때는 이것부터다.
_IMPRESSION = _load("6558ab4d3dbc")

_LANES: tuple[PromptLane, ...] = ("story", "character")
_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")
_PAIRS: list[tuple[PromptLane, PromptSetModelId]] = [(lane, model) for lane in _LANES for model in _MODELS]
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = _EPISODE_KNOWN_BY.NEW_SET_IDS

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_INSTRUCTION_KEY: Key = ("memory_fact", "both", "instruction", "")
_EPISODE_INSTRUCTION_KEY: Key = ("memory_episode", "both", "instruction", "")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 새 지시문과 옛 지시문의 지문 — 글자 하나가 바뀌어도 여기서 깨진다. 새 지시문은 측정에서 고른 판의 파일과 같은 값이다.
_NEW_INSTRUCTION_MD5 = "1dc4e0fabaea765f4056ea4ab84433a5"
_OLD_INSTRUCTION_MD5 = "31fab9859bca21d5f9831b5415528a1f"


def _ids(pairs: list[tuple[PromptLane, PromptSetModelId]]) -> list[str]:
    return [f"{lane}-{model}" for lane, model in pairs]


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _flat(text: str) -> str:
    return " ".join(line.strip() for line in text.split("\n"))


def _changed_block() -> tuple[list[str], list[str], int, int]:
    """옛 판과 새 판 사이에 바뀐 덩어리 하나 — (옛 줄들, 새 줄들, 옛 시작 위치, 옛 끝 위치)."""
    old_lines, new_lines = _M.OLD_FACT_INSTRUCTION_BODY.split("\n"), _M.FACT_INSTRUCTION_BODY.split("\n")
    changes = [
        op for op in difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False).get_opcodes() if op[0] != "equal"
    ]
    assert len(changes) == 1
    (tag, a1, a2, b1, b2) = changes[0]
    assert tag == "replace"
    return old_lines[a1:a2], new_lines[b1:b2], a1, a2


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_after(before: dict[Key, Value]) -> dict[Key, Value]:
    """이전 행 그대로, 사실 추출 지시문만 새 상수."""
    _old_body, conditional, order = before[_INSTRUCTION_KEY]
    return {**before, _INSTRUCTION_KEY: (_M.FACT_INSTRUCTION_BODY, conditional, order)}


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
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


def _instruction_of(sections: list[PromptSection], channel: str) -> str:
    (instruction,) = [s for s in sections if (s.channel, s.slot) == (channel, "instruction")]
    return instruction.body


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_old_instruction_this_revision_expects_is_the_one_the_last_fact_text_revision_seeded() -> None:
    """운영 본문이 이 상수와 같을 때만 바꾼다 — 상수가 앞 리비전 문안과 한 글자라도 다르면 모든 체인에서 멈춘다. 그보다 앞의
    판(사실 채널을 처음 심은 리비전의 문안)과는 달라야 한다."""
    assert _M.OLD_FACT_INSTRUCTION_BODY == _FACT_TEXT_MIGRATION.FACT_INSTRUCTION_BODY
    assert _M.OLD_FACT_INSTRUCTION_BODY != _FACT_TEXT_MIGRATION.OLD_FACT_INSTRUCTION_BODY
    assert _md5(_M.OLD_FACT_INSTRUCTION_BODY) == _OLD_INSTRUCTION_MD5


def test_new_instruction_replaces_only_the_body_of_the_secret_rule() -> None:
    """바뀐 곳은 10번 비밀 규칙의 본문 한 덩어리뿐이다 — 10번 머리 줄과 그 앞 줄, 그 아래 비밀 주인 규칙부터 끝까지는 옛 판
    그대로다. 자리표시자가 없다 — 옛 이미지가 이 판을 렌더해도 넘길 값이 없어 깨지지 않는다. 끝에 줄바꿈이 없다(측정이 넣은
    그대로)."""
    new, old = _M.FACT_INSTRUCTION_BODY, _M.OLD_FACT_INSTRUCTION_BODY
    assert _md5(new) == _NEW_INSTRUCTION_MD5
    assert "{" not in new and "}" not in new and "{" not in old
    assert not new.endswith("\n")

    _removed, added, start, end = _changed_block()
    old_lines = old.split("\n")
    assert old_lines[start - 1].startswith("10. ")
    assert old_lines[end].lstrip().startswith("- ")
    assert all(line.startswith("    ") for line in added)


def test_new_secret_rule_lists_the_cases_in_order() -> None:
    """새 10번 본문은 아는 인물을 정하는 경우를 차례 번호가 붙은 네 항목으로 나누고, 마지막 항목만 빈 목록을 허락한다. 맞는
    경우가 여럿이면 인물을 합친다. 옛 판에는 이 차례가 없다."""
    _removed, added, _start, _end = _changed_block()
    markers = [line.strip()[0] for line in added if line.strip()[:1] in "①②③④"]
    assert markers == ["①", "②", "③", "④"]
    last = next(line for line in added if line.strip().startswith("④"))
    assert "빈 목록" in last

    flat, old_flat = _flat(_M.FACT_INSTRUCTION_BODY), _flat(_M.OLD_FACT_INSTRUCTION_BODY)
    for phrase in ("known_by 를 아래 순서로 정한다", "맞는 항목이 여럿이면 그 인물을 모두 합친다", "주인 없는 사건 포함"):
        assert phrase in flat
        assert phrase not in old_flat


def test_new_instruction_calls_the_user_by_the_word_the_reader_filters() -> None:
    """프로필 이름이 없는 방에서 추출이 지시문의 사용자 낱말을 아는 인물·말한 사람에 그대로 적을 수 있다 — 읽는 쪽이 사용자
    표기로 거르는 낱말과 같아야 그 이름이 다른 인물로 읽히지 않는다."""
    assert USER_INSTRUCTION_WORD in _M.FACT_INSTRUCTION_BODY
    _removed, added, _start, _end = _changed_block()
    assert USER_INSTRUCTION_WORD in "\n".join(added)


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_each_chain_is_active_at_its_seeded_set_with_the_new_instruction_bytes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]
    _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    instruction = _instruction_of(sections, "memory_fact")
    assert instruction == _M.FACT_INSTRUCTION_BODY
    assert _md5(instruction) == _NEW_INSTRUCTION_MD5


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_active_extraction_instructions_carry_the_user_word_the_reader_filters(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """운영 활성 세트의 사실·장면 추출 지시문이 읽는 쪽이 사용자 표기로 거르는 낱말을 쓴다 — 지시문이 사용자를 다른 낱말로 부르게
    바뀌었는데 그 상수가 그대로면 여기서 깨진다."""
    _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    assert USER_INSTRUCTION_WORD in _instruction_of(sections, "memory_fact")
    assert USER_INSTRUCTION_WORD in _instruction_of(sections, "memory_episode")


def test_the_revision_seeds_exactly_eight_chains() -> None:
    assert sorted(_M.NEW_SET_IDS) == sorted(_PAIRS)
    assert len(set(_M.NEW_SET_IDS.values())) == 8


@pytest.mark.parametrize("lane", _LANES)
async def test_the_lane_only_select_picks_the_new_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """모델 열을 모르는 원시 SQL 이 레인만 보고 최신 게시본을 고를 때도 새 Gemini 세트를 집는다."""
    await _undo_later_revisions(db_session)
    assert await _lane_only_active_id(db_session, lane) == _M.NEW_SET_IDS[(lane, "gemini")]


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_new_set_is_the_previous_active_set_with_only_the_instruction_changed(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이전 활성 세트의 행이 바이트 그대로 옮겨지고(사실 추출 지시문만 다르다), 더하거나 빠진 행이 없다. 바로 앞 리비전이 바꾼
    장면 추출 지시문과 story 레인의 장면 헤더 판정 행도 그대로다. 라벨도 이전 활성 세트 것이다."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[(lane, model)])
    new = _keyed(new_sections)
    # 다음 `_sections_of` 가 `expire_all` 로 이 객체들을 만료시키므로 그 전에 읽어 둔다(만료된 속성을 읽으면 동기 지연 로드다).
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[(lane, model)]))

    assert before[_INSTRUCTION_KEY][0] == _M.OLD_FACT_INSTRUCTION_BODY
    assert new == _expected_after(before)
    assert new[_EPISODE_INSTRUCTION_KEY][0] == _EPISODE_KNOWN_BY.EPISODE_INSTRUCTION_BODY
    scene_judgment = {key: value for key, value in new.items() if key[0] == "scene_judgment"}
    assert scene_judgment == {key: value for key, value in before.items() if key[0] == "scene_judgment"}
    assert bool(scene_judgment) == (lane == "story")
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
                PromptSet.id.not_in(list(_SCENE_INSTRUCTION_V2.NEW_SET_IDS.values())),
                PromptSet.id.not_in(list(_IMPRESSION.NEW_SET_IDS.values())),
            )
        )
    ).all()
    # 테스트 DB에는 이 리비전 뒤에 게시한 세트가 요약 비밀 표기 출처·장면 판정 지시문 교체 리비전의 것뿐이다(그 세트들의
    # 버전은 이 리비전보다 뒤다).
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
    """되돌리면 여덟 체인 활성이 이전 세트(처음부터 옛 지시문)로, 레인만 보는 조회가 이전 Gemini 세트로 돌아가고, 다시 올리면
    같은 리터럴 세트가 활성이 된다."""
    connection = await db_session.connection()

    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)

    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    for lane, model in _PAIRS:
        assert await _active_id(db_session, lane, model) == _PREVIOUS_SET_IDS[(lane, model)]
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, model)]) is None
        _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
        assert _instruction_of(sections, "memory_fact") == _M.OLD_FACT_INSTRUCTION_BODY
    for lane in _LANES:
        assert await _lane_only_active_id(db_session, lane) == _PREVIOUS_SET_IDS[(lane, "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.body == _M.FACT_INSTRUCTION_BODY)
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for lane, model in _PAIRS:
        assert await _active_id(db_session, lane, model) == _M.NEW_SET_IDS[(lane, model)]


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_ids(_PAIRS))
async def test_upgrade_refuses_to_overwrite_an_instruction_the_admin_edited(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """활성 지시문이 앞 리비전 문안과 한 글자라도 다르면 어드민이 고친 운영 문안이다 — 조용히 덮어쓰지 않고, 그 레인에는 아무
    세트도 넣지 않은 채 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[(lane, model)],
            PromptSection.channel == "memory_fact",
            PromptSection.slot == "instruction",
        )
        .values(body=PromptSection.body + " ")
    )

    with pytest.raises(RuntimeError, match=f"{lane}/{model}") as caught:
        await connection.run_sync(_M.seed_published_sets)
    assert "memory_fact 채널의 instruction 본문이 앞 리비전이 심은 문안과 다르다" in str(caught.value)
    for other in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, other)]) is None


async def test_upgrade_stops_on_the_text_before_the_last_fact_text_revision(db_session: AsyncSession) -> None:
    """활성 본문이 사실 채널을 처음 심은 리비전의 문안(그 뒤 한 번 바뀌기 전 판)이어도 바꾸지 않고 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("story", "gemini")],
            PromptSection.channel == "memory_fact",
            PromptSection.slot == "instruction",
        )
        .values(body=_FACT_TEXT_MIGRATION.OLD_FACT_INSTRUCTION_BODY)
    )

    with pytest.raises(RuntimeError, match=r"story/gemini\] memory_fact 채널의 instruction 본문"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_the_instruction_row_is_not_exactly_one(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
    await connection.run_sync(_LATER.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.delete(PromptSection).where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("character", "haiku")],
            PromptSection.channel == "memory_fact",
            PromptSection.slot == "instruction",
        )
    )

    with pytest.raises(
        RuntimeError, match=r"character/haiku\] memory_fact 채널의 instruction 행이 정확히 하나가 아니다\(0개"
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
    await connection.run_sync(_SCENE_INSTRUCTION_V2.delete_seeded_rows)
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
async def test_patch_drafts_swaps_the_instruction_in_place_and_the_draft_publishes(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 초안(이전 활성 세트 복제)이 새 세트와 같은 행이 되고 그 체인의 게시 게이트를 통과한다.
    되돌리기는 지시문을 옛 문안으로 돌린다."""
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


async def test_patch_drafts_keeps_an_instruction_edited_in_the_draft(db_session: AsyncSession) -> None:
    """초안에서 고치던 지시문은 그대로 둔다(배포를 멈추지도 않는다). 되돌리기도 고친 본문을 건드리지 않는다."""
    draft_id = await _clone_as_draft(
        db_session,
        _PREVIOUS_SET_IDS[("story", "haiku")],
        "story",
        "haiku",
        edit={_INSTRUCTION_KEY: "운영자가 고치던 사실 추출 지시문"},
    )
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before

    assert await connection.run_sync(_M._delete_draft_rows) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before
