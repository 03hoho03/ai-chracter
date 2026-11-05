"""정본 기억 문안 채널 시드 리비전(`d39cf46dcb5c`)의 검증.

소설 레인 세 체인(gemini·sonnet·opus)마다 직전 활성 세트의 바이트 사본에 정본 기억 채널 넷(사건·사실·지식 추출, 모호 판정)의
행을 더한 새 published 세트를 심는다. 마이그레이션 자체는 다시 돌리지 않는다(앞의 문안 리비전 테스트와 같은 방식). 세션 스코프
스키마가 이미 `upgrade head` 를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows` 는 테스트마다 롤백되는 `db_session` 의 커넥션에 `run_sync` 로 직접 부른다. 이전 행의 기대값은 DB 의 이전 활성
세트에서 직접 읽고, 새 행의 슬롯·순서·조건부 표시는 이 파일의 표로 따로 적는다 — 마이그레이션의 행 조립으로 기대값을 만들면 그
조립이 틀려도 테스트가 같이 틀린다."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from string import Formatter
from types import ModuleType
from typing import TypeVar

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import PromptSetModelId
from api.novel_bible.core.contracts import PromptSource
from api.novel_bible.core.render import render

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("d39cf46dcb5c")
# 이 리비전 직전 소설 레인 세 체인의 활성 — 등급 규칙 채널 리비전의 세트다.
_PREVIOUS_SET_IDS: dict[str, uuid.UUID] = dict(_load("e4df46a80bfa").NEW_SET_IDS)
_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")

# 새 행의 (슬롯, 순서, 조건부) — 지시문과 필수 입력은 조건부가 아니고 선택 입력만 조건부다.
_BIBLE_SLOTS: dict[str, tuple[tuple[str, int, bool], ...]] = {
    "novel_bible_events": (
        ("instruction", 0, False),
        ("manuscript", 1, False),
        ("scene_hints", 2, True),
        ("known_entities", 3, True),
        ("prior_events", 4, True),
    ),
    "novel_bible_facts": (
        ("instruction", 0, False),
        ("manuscript", 1, False),
        ("known_entities", 2, True),
        ("known_attributes", 3, True),
        ("source_canon", 4, True),
        ("play_facts", 5, True),
    ),
    "novel_bible_knowledge": (("instruction", 0, False), ("manuscript", 1, False), ("known_entities", 2, True)),
    "novel_bible_conflicts": (("instruction", 0, False), ("candidate", 1, False)),
}
_CHANNELS = tuple(_BIBLE_SLOTS)

T = TypeVar("T")

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    rows = (await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all()
    return [
        PromptSection(
            channel=s.channel,
            scope=s.scope,
            slot=s.slot,
            variant=s.variant,
            body=s.body,
            conditional=s.conditional,
            order=s.order,
        )
        for s in rows
    ]


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


async def _active(db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId = "gemini") -> PromptSet:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane=lane, model=model))[0]


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


async def _copy_set(
    db_session: AsyncSession,
    source_id: uuid.UUID,
    *,
    status: str,
    published_at: datetime | None,
    drop_channel: str | None = None,
) -> uuid.UUID:
    """`source_id` 세트를 같은 체인에 복제한다(어드민 게시·초안 흉내). `drop_channel` 의 행은 옮기지 않는다."""
    source = await _get_set(db_session, source_id)
    copy = PromptSet(
        version="9001" if status == "published" else None,
        status=status,
        lane="novel",
        model=source.model,
        **{label: getattr(source, label) for label in _LABELS},
        published_at=published_at,
    )
    db_session.add(copy)
    await db_session.flush()
    copy_id = copy.id
    for s in await _sections_of(db_session, source_id):
        if s.channel == drop_channel:
            continue
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


async def _run(db_session: AsyncSession, fn: Callable[[Connection], T]) -> T:
    connection = await db_session.connection()
    return await connection.run_sync(fn)


async def _bible_row_count(db_session: AsyncSession) -> int:
    return int(
        await db_session.scalar(
            sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.channel.in_(_CHANNELS))
        )
        or 0
    )


# ---- 시드 결과(head 상태) --------------------------------------------------------------------


@pytest.mark.parametrize("model", _MODELS)
async def test_each_novel_chain_is_active_at_the_seed_with_the_previous_rows_and_the_bible_rows(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """세 체인 활성은 이 시드이고, 그 세트는 직전 활성 행 전부(본문·조건부·순서 그대로) + 정본 기억 채널 행이다. 라벨은 직전 활성
    그대로다. 깨지는 시나리오: 사본이 화 생성·등급 규칙 행을 잃거나 한 바이트라도 바꿔 시드만으로 소설 글이 달라지거나, 필수 입력을
    조건부로 심어 빈 원고가 오류 대신 원고 없는 프롬프트로 나간다."""
    assert (await _active(db_session, "novel", model)).id == _M.NEW_SET_IDS[model]
    previous = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[model]))
    seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[model]))

    assert {key: value for key, value in seeded.items() if key in previous} == previous
    added = {key: value for key, value in seeded.items() if key not in previous}
    assert {key: (conditional, order) for key, (_, conditional, order) in added.items()} == {
        (channel, "both", slot, ""): (conditional, order)
        for channel, slots in _BIBLE_SLOTS.items()
        for slot, order, conditional in slots
    }
    assert not {key[0] for key in previous} & set(_CHANNELS)
    assert all(body.strip() for body, _, _ in added.values())

    previous_set = await _get_set(db_session, _PREVIOUS_SET_IDS[model])
    previous_labels = [getattr(previous_set, label) for label in _LABELS]
    previous_at = previous_set.published_at
    seeded_set = await _get_set(db_session, _M.NEW_SET_IDS[model])
    assert [getattr(seeded_set, label) for label in _LABELS] == previous_labels
    assert seeded_set.published_at is not None and previous_at is not None
    assert seeded_set.published_at > previous_at


async def test_the_three_chains_get_the_same_bible_rows(db_session: AsyncSession) -> None:
    """같은 첫 본문을 세 체인에 심는다. 깨지는 시나리오: 체인마다 본문이 달라 어느 체인을 읽느냐에 따라 추출이 갈린다."""
    rows = []
    for model in _MODELS:
        seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[model]))
        rows.append({key: value for key, value in seeded.items() if key[0] in _CHANNELS})
    assert rows[0] == rows[1] == rows[2]


@pytest.mark.parametrize("model", _MODELS)
async def test_the_seeded_sets_pass_publish_validation(db_session: AsyncSession, model: PromptSetModelId) -> None:
    """깨지는 시나리오: 시드가 게시 검증의 슬롯·자리표시자 표와 어긋나 배포 직후 소설 레인 그 체인의 어드민 게시가 막힌다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="novel", model=model)
    _validate_prompt_draft_for_publish(prompt_set, sections, lane="novel", model=model)


def _synthetic_values() -> dict[str, dict[str, str]]:
    return {
        "novel_bible_events": {
            "manuscript": "[장면 1]\n[1] 합성 문단 하나.\n[2] 합성 문단 둘.",
            "scene_hints": "장면 1. 합성 장면",
            "known_entities": "- 합성 인물 (인물)",
            "prior_events": "P1. 1화 — 합성 사건",
        },
        "novel_bible_facts": {
            "manuscript": "[1] 합성 문단 하나.",
            "known_entities": "- 합성 인물 (인물)",
            "known_attributes": "- 합성 인물 (인물) · 눈 색: 갈색",
            "source_canon": "[S] 합성 작품 설정",
            "play_facts": "P1. 합성 인물 · 직업: 합성 값",
        },
        "novel_bible_knowledge": {"manuscript": "[1] 합성 문단 하나.", "known_entities": "- 합성 인물 (인물)"},
        "novel_bible_conflicts": {"candidate": "규칙: 합성 규칙\n앞 항목: 1화 합성 서술\n뒤 항목: 2화 합성 서술"},
    }


@pytest.mark.parametrize("model", _MODELS)
@pytest.mark.parametrize("scope", ["story", "character"])
async def test_the_seed_renders_every_bible_channel_with_and_without_the_optional_values(
    db_session: AsyncSession, model: PromptSetModelId, scope: str
) -> None:
    """정본 기억 렌더가 시드 문안을 그대로 쓴다 — 지시문은 값 없이, 값 섹션은 슬롯 값으로. 선택 값이 비면 그 섹션만 빠지고 필수
    값은 남는다. 깨지는 시나리오: 지시문에 중괄호가 섞여 값 없는 렌더가 실패하거나, 값 섹션이 슬롯 코드가 내지 않는 이름을 참조해
    모든 확정이 문안 없음으로 실패한다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="novel", model=model)
    source = PromptSource(prompt_set_id=prompt_set.id, sections=sections)
    for channel, values in _synthetic_values().items():
        rendered = render(source, channel=channel, scope=scope, values=values)
        assert rendered.system_instruction.strip()
        for value in values.values():
            assert value in rendered.prompt
            assert value not in rendered.system_instruction

        required = {slot for slot, _, conditional in _BIBLE_SLOTS[channel] if not conditional} - {"instruction"}
        only_required = {name: value if name in required else "" for name, value in values.items()}
        rendered = render(source, channel=channel, scope=scope, values=only_required)
        assert rendered.prompt.strip()
        for name, value in values.items():
            assert (value in rendered.prompt) == (name in required)


async def test_every_value_section_references_only_its_own_slot_name(db_session: AsyncSession) -> None:
    """값 섹션은 자기 슬롯 이름의 값 하나만 참조하고 지시문은 아무 값도 참조하지 않는다 — 슬롯 코드가 그 이름으로 값을 낸다.
    깨지는 시나리오: 한 섹션이 두 값을 참조해 한쪽이 빈 선택 값이어도 섹션이 남거나, 필수 섹션이 선택 값에 기대 검사에 걸린다."""
    seeded = await _sections_of(db_session, _M.NEW_SET_IDS["gemini"])
    for section in seeded:
        if section.channel not in _CHANNELS:
            continue
        fields = {name for _, name, _, _ in Formatter().parse(section.body) if name}
        assert fields == (set() if section.slot == "instruction" else {section.slot}), (section.channel, section.slot)


@pytest.mark.parametrize("model", _MODELS)
async def test_the_seed_gets_a_minor_bump_on_top_of_the_previous_chain_version(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """체인 판은 직전 활성을 기준판으로 minor, 처음 들어온 채널 넷은 1.0.0 minor, 나머지 채널은 직전 번호 그대로(단계 없음). 깨지는
    시나리오: 판 행이 없어 다음 어드민 게시가 이 변경을 자기 판에 섞어 세거나, 기준판이 틀려 판 사슬이 끊긴다."""
    level, base = (
        await db_session.execute(
            sa.text("SELECT level, base_set_id FROM prompt_set_semvers WHERE prompt_set_id = :id"),
            {"id": _M.NEW_SET_IDS[model]},
        )
    ).one()
    assert (level, base) == ("minor", _PREVIOUS_SET_IDS[model])

    async def section_semvers(set_id: uuid.UUID) -> dict[str, tuple[int, int, int, str | None]]:
        rows = await db_session.execute(
            sa.text("SELECT channel, major, minor, patch, level FROM prompt_section_semvers WHERE prompt_set_id = :id"),
            {"id": set_id},
        )
        return {channel: (major, minor, patch, level) for channel, major, minor, patch, level in rows}

    seeded = await section_semvers(_M.NEW_SET_IDS[model])
    previous = await section_semvers(_PREVIOUS_SET_IDS[model])
    assert {channel: seeded[channel] for channel in _CHANNELS} == {channel: (1, 0, 0, "minor") for channel in _CHANNELS}
    assert {channel: value for channel, value in seeded.items() if channel not in _CHANNELS} == {
        channel: (major, minor, patch, None) for channel, (major, minor, patch, _) in previous.items()
    }


# ---- 옛 이미지 × 새 데이터 --------------------------------------------------------------------------


async def test_the_seed_leaves_every_chat_chain_untouched(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 시드가 채팅 체인의 활성·행을 바꿔 배포 겹침 동안 옛 이미지의 채팅 글이 바뀐다."""
    lanes: tuple[PromptLane, ...] = ("story", "character")
    models: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")

    async def snapshot() -> dict[tuple[str, str], tuple[uuid.UUID, dict[Key, Value]]]:
        taken: dict[tuple[str, str], tuple[uuid.UUID, dict[Key, Value]]] = {}
        for lane in lanes:
            for model in models:
                set_id = (await _active(db_session, lane, model)).id
                taken[(lane, model)] = (set_id, _keyed(await _sections_of(db_session, set_id)))
        return taken

    at_head = await snapshot()

    await _run(db_session, _M.delete_seeded_rows)

    assert await snapshot() == at_head


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_every_novel_chain_back_and_forth(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 되돌리기가 시드나 초안 행을 남겨 다시 올릴 때 "이미 있다"로 배포가 멈추거나, 이전 활성으로 돌아가지 않는다.
    다른 레인 테스트의 되돌리기 헬퍼가 거듭 부르므로 두 번째 호출도 조용히 같은 결과로 끝나야 한다."""
    await _run(db_session, _M.delete_seeded_rows)
    await _run(db_session, _M.delete_seeded_rows)

    for model in _MODELS:
        assert (await _active(db_session, "novel", model)).id == _PREVIOUS_SET_IDS[model]
    for set_id in _M.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is None
    assert await _bible_row_count(db_session) == 0

    await _run(db_session, _M.seed_published_sets)

    for model in _MODELS:
        assert (await _active(db_session, "novel", model)).id == _M.NEW_SET_IDS[model]


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    with pytest.raises(RuntimeError, match="이미 있다"):
        await _run(db_session, _M.seed_published_sets)


async def test_upgrade_stops_when_an_active_set_already_has_a_bible_row(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 어드민이 먼저 넣은 정본 기억 행 위에 시드가 같은 키의 행을 더해 한 채널 안에 같은 슬롯이 둘이 된다."""
    await _run(db_session, _M.delete_seeded_rows)
    latest = (await _get_set(db_session, _PREVIOUS_SET_IDS["opus"])).published_at
    assert latest is not None
    edited = await _copy_set(
        db_session, _PREVIOUS_SET_IDS["opus"], status="published", published_at=latest + timedelta(seconds=5)
    )
    db_session.add(
        PromptSection(
            prompt_set_id=edited, channel="novel_bible_facts", scope="both", slot="instruction", variant="",
            body="합성 지시문", conditional=False, order=0,
        )
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="novel/opus"):
        await _run(db_session, _M.seed_published_sets)

    for set_id in _M.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is None


async def test_upgrade_stops_when_an_active_set_is_not_a_novel_prompt_set(db_session: AsyncSession) -> None:
    """화 생성 채널이 없는 세트는 소설 레인 문안이 아니다 — 그 위에 정본 기억 채널을 얹지 않고 멈춘다."""
    await _run(db_session, _M.delete_seeded_rows)
    latest = (await _get_set(db_session, _PREVIOUS_SET_IDS["sonnet"])).published_at
    assert latest is not None
    await _copy_set(
        db_session,
        _PREVIOUS_SET_IDS["sonnet"],
        status="published",
        published_at=latest + timedelta(seconds=5),
        drop_channel="novelize_chapter",
    )

    with pytest.raises(RuntimeError, match="novel/sonnet"):
        await _run(db_session, _M.seed_published_sets)

    for set_id in _M.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is None


async def test_downgrade_stops_when_the_admin_published_after_the_seed(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 되돌리기가 시드를 지워 정본 기억 행이 든 어드민 게시본이 활성으로 남고, 옛 이미지의 그 체인 게시가 막힌다."""
    seeded = await _get_set(db_session, _M.NEW_SET_IDS["gemini"])
    assert seeded.published_at is not None
    await _copy_set(
        db_session, _M.NEW_SET_IDS["gemini"], status="published", published_at=seeded.published_at + timedelta(seconds=1)
    )

    with pytest.raises(RuntimeError, match="novel/gemini"):
        await _run(db_session, _M.delete_seeded_rows)

    for set_id in _M.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is not None


async def test_downgrade_stops_when_a_version_row_uses_the_seed_as_its_base(db_session: AsyncSession) -> None:
    """시드보다 앞 시각 게시라도 그 판이 시드를 기준판으로 가리키면 지우지 않는다. 깨지는 시나리오: 기준판 FK 위반이 무엇을 해야
    하는지 알 수 없는 오류로 배포를 멈추거나, 판 사슬이 끊긴다."""
    seeded = await _get_set(db_session, _M.NEW_SET_IDS["gemini"])
    assert seeded.published_at is not None
    earlier = await _copy_set(
        db_session, _M.NEW_SET_IDS["gemini"], status="published", published_at=seeded.published_at - timedelta(seconds=10)
    )
    await db_session.execute(
        sa.text(
            "INSERT INTO prompt_set_semvers (id, prompt_set_id, lane, model, major, minor, patch, level, base_set_id)"
            " VALUES (:id, :set_id, 'novel', 'gemini', 99, 0, 0, 'patch', :base)"
        ),
        {"id": uuid.uuid4(), "set_id": earlier, "base": _M.NEW_SET_IDS["gemini"]},
    )

    with pytest.raises(RuntimeError, match="기준판"):
        await _run(db_session, _M.delete_seeded_rows)

    for set_id in _M.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is not None


# ---- 초안 제자리 패치 ----------------------------------------------------------------------------


async def test_patch_drafts_adds_only_the_missing_bible_rows_in_place(db_session: AsyncSession) -> None:
    """정본 기억 행이 없는 초안(배포 전 활성본에서 만든 초안)에는 시드와 같은 행을 넣고, 운영자가 이미 넣은 행은 건드리지 않고
    빠진 행만 채운 뒤 게시 검증을 통과한다. 되돌리기는 정본 기억 행만 지운다. 깨지는 시나리오: 배포 전부터 있던 초안이 "누락"으로
    게시가 막히거나, 패치가 운영자가 고친 문안을 덮어쓴다."""
    gemini_draft = await _copy_set(db_session, _PREVIOUS_SET_IDS["gemini"], status="draft", published_at=None)
    opus_draft = await _copy_set(db_session, _PREVIOUS_SET_IDS["opus"], status="draft", published_at=None)
    db_session.add(
        PromptSection(
            prompt_set_id=opus_draft, channel="novel_bible_events", scope="both", slot="instruction", variant="",
            body="합성 운영자 지시문", conditional=False, order=0,
        )
    )
    await db_session.flush()
    before = {draft: _keyed(await _sections_of(db_session, draft)) for draft in (gemini_draft, opus_draft)}

    assert await _run(db_session, _M._patch_drafts) == ["gemini", "opus"]

    drafts: tuple[tuple[uuid.UUID, PromptSetModelId], ...] = ((gemini_draft, "gemini"), (opus_draft, "opus"))
    for draft, model in drafts:
        patched = _keyed(await _sections_of(db_session, draft))
        seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[model]))
        assert {key: value for key, value in patched.items() if key in before[draft]} == before[draft]
        assert {key: value for key, value in patched.items() if key not in before[draft]} == {
            key: value for key, value in seeded.items() if key[0] in _CHANNELS and key not in before[draft]
        }
        # `_sections_of` 가 식별자 맵을 만료시키므로 세트는 섹션을 읽은 뒤에 꺼낸다.
        draft_sections = await _sections_of(db_session, draft)
        draft_set = await _get_set(db_session, draft)
        _validate_prompt_draft_for_publish(draft_set, draft_sections, lane="novel", model=model)
    assert _keyed(await _sections_of(db_session, opus_draft))[("novel_bible_events", "both", "instruction", "")][0] == (
        "합성 운영자 지시문"
    )

    assert await _run(db_session, _M._patch_drafts) == []

    await _run(db_session, _M._delete_draft_rows)
    for draft in (gemini_draft, opus_draft):
        after = _keyed(await _sections_of(db_session, draft))
        assert after == {key: value for key, value in before[draft].items() if key[0] not in _CHANNELS}
