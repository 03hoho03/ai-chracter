"""채팅 두 레인 Gemini 체인에서 옛 소설화 세 채널 행을 뺀 세트를 게시하는 데이터 마이그레이션(`7caed2db87dc`)의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마가 이미 `upgrade head` 를 했으므로
시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_delete_draft_rows`·`delete_seeded_rows` 는 테스트마다 롤백되는
`db_session` 의 커넥션에 `run_sync` 로 직접 부른다. 기대 행은 이 파일이 DB 의 이전 활성 세트에서 직접 읽어 만든다 — 마이그레이션의
행 조립으로 기대값을 만들면 그 조립이 틀려도 테스트가 같이 틀린다."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
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

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("7caed2db87dc")
# 이 리비전 직전 채팅 두 레인 Gemini 체인의 활성 — 인상 생성 문안 리비전의 세트다(그 뒤 리비전들은 소설 레인만 게시했다).
_IMPRESSION = _load("6558ab4d3dbc")
_LANES: tuple[PromptLane, ...] = ("story", "character")
_PREVIOUS_SET_IDS: dict[str, uuid.UUID] = {lane: _IMPRESSION.NEW_SET_IDS[(lane, "gemini")] for lane in _LANES}
_DROPPED = frozenset({"novelize_boundary", "novelize_chapter", "novelize_revise"})
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")

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


def _without_dropped(rows: dict[Key, Value]) -> dict[Key, Value]:
    return {key: value for key, value in rows.items() if key[0] not in _DROPPED}


async def _active(db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId = "gemini") -> PromptSet:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane=lane, model=model))[0]


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


async def _copy_set(
    db_session: AsyncSession, source_id: uuid.UUID, *, status: str, published_at: datetime | None
) -> uuid.UUID:
    """`source_id` 세트를 같은 체인에 복제한다(어드민 게시·초안 흉내)."""
    source = await _get_set(db_session, source_id)
    copy = PromptSet(
        version="9001" if status == "published" else None,
        status=status,
        lane=source.lane,
        model=source.model,
        **{label: getattr(source, label) for label in _LABELS},
        published_at=published_at,
    )
    db_session.add(copy)
    await db_session.flush()
    copy_id = copy.id
    for s in await _sections_of(db_session, source_id):
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


async def _seed_count(db_session: AsyncSession) -> int:
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSet).where(PromptSet.id.in_(list(_M.NEW_SET_IDS.values())))
    )
    assert count is not None
    return count


# ---- 시드 결과(head 상태) --------------------------------------------------------------------


@pytest.mark.parametrize("lane", _LANES)
async def test_each_chat_gemini_chain_is_active_at_the_seed_which_is_the_previous_set_without_the_novel_rows(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """두 체인 활성은 시드이고, 시드는 직전 활성 행에서 소설화 세 채널 행만 뺀 것이다(나머지 행의 본문·conditional·order 바이트
    그대로). 라벨도 직전 활성 그대로다. 깨지는 시나리오: 사본이 채팅 행 하나를 잃거나 바꿔 배포 직후 채팅 프롬프트가 달라지거나,
    소설 행이 남아 새 코드의 게시 검증이 그 체인 게시를 "잉여"로 막는다."""
    assert (await _active(db_session, lane)).id == _M.NEW_SET_IDS[lane]
    previous = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[lane]))
    seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[lane]))

    assert {key[0] for key in previous} >= _DROPPED
    assert seeded == _without_dropped(previous)

    previous_set = await _get_set(db_session, _PREVIOUS_SET_IDS[lane])
    seeded_set = await _get_set(db_session, _M.NEW_SET_IDS[lane])
    assert (seeded_set.lane, seeded_set.model, seeded_set.status) == (lane, "gemini", "published")
    assert [getattr(seeded_set, label) for label in _LABELS] == [getattr(previous_set, label) for label in _LABELS]
    assert seeded_set.published_at is not None and previous_set.published_at is not None
    assert seeded_set.published_at > previous_set.published_at


@pytest.mark.parametrize("lane", _LANES)
async def test_the_seeded_sets_pass_publish_validation(db_session: AsyncSession, lane: PromptLane) -> None:
    """깨지는 시나리오: 시드가 게시 검증의 채팅 레인 슬롯 집합과 어긋나 배포 직후 그 체인의 어드민 게시가 막힌다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model="gemini")
    _validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model="gemini")


@pytest.mark.parametrize("lane", _LANES)
async def test_the_seed_gets_a_patch_bump_on_top_of_the_previous_chain_version(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """체인 판은 직전 활성을 기준판으로 patch 이고, 남긴 채널은 기준판 번호를 그대로 물려받는다(바뀌지 않은 섹션). 깨지는 시나리오:
    판 행이 없어 다음 어드민 게시가 이 변경을 자기 판에 섞어 세거나, 남긴 채널 번호가 올라 바뀌지 않은 문안이 바뀐 것처럼 보인다."""
    level, base_set_id = (
        await db_session.execute(
            sa.text("SELECT level, base_set_id FROM prompt_set_semvers WHERE prompt_set_id = :id"),
            {"id": _M.NEW_SET_IDS[lane]},
        )
    ).one()
    assert (level, base_set_id) == ("patch", _PREVIOUS_SET_IDS[lane])

    async def section_semvers(set_id: uuid.UUID) -> dict[str, tuple[int, int, int]]:
        rows = await db_session.execute(
            sa.text("SELECT channel, major, minor, patch FROM prompt_section_semvers WHERE prompt_set_id = :id"),
            {"id": set_id},
        )
        return {channel: (major, minor, patch) for channel, major, minor, patch in rows}

    previous = await section_semvers(_PREVIOUS_SET_IDS[lane])
    seeded = await section_semvers(_M.NEW_SET_IDS[lane])
    assert seeded == {channel: number for channel, number in previous.items() if channel not in _DROPPED}


async def test_the_revision_touches_only_the_two_chat_gemini_chains(db_session: AsyncSession) -> None:
    """채팅 Claude·판정 전용 체인과 소설·심사 레인 체인의 활성·행은 그대로다 — 특히 같은 이름의 채널을 가진 소설 레인 세트를
    건드리지 않는다. 되돌리면 두 체인 활성이 직전 세트로 돌아간다. 깨지는 시나리오: 채널 이름으로만 걸러 소설 레인 행까지 빼
    소설 호출의 렌더가 비거나, 다른 체인 활성이 바뀌어 그 체인 채팅 프롬프트가 달라진다."""
    chat_models: tuple[PromptSetModelId, ...] = ("sonnet", "opus", "haiku")
    novel_models: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")
    chains: list[tuple[PromptLane, PromptSetModelId]] = [
        *((lane, model) for lane in _LANES for model in chat_models),
        *(("novel", model) for model in novel_models),
        ("publish_filter", "gemini"),
        ("novel_screen", "gemini"),
    ]

    async def snapshot() -> dict[tuple[str, str], tuple[uuid.UUID, dict[Key, Value]]]:
        taken: dict[tuple[str, str], tuple[uuid.UUID, dict[Key, Value]]] = {}
        for chain in chains:
            set_id = (await _active(db_session, *chain)).id
            taken[chain] = (set_id, _keyed(await _sections_of(db_session, set_id)))
        return taken

    at_head = await snapshot()
    assert {key[0] for key in at_head[("novel", "gemini")][1]} >= _DROPPED

    await _run(db_session, _M.delete_seeded_rows)

    assert await snapshot() == at_head
    for lane in _LANES:
        assert (await _active(db_session, lane)).id == _PREVIOUS_SET_IDS[lane]


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_the_two_chains_back_and_forth(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 되돌리기가 시드를 남겨 다시 올릴 때 "이미 있다"로 배포가 멈추거나, 직전 활성으로 돌아가지 않는다. 다른
    리비전 테스트의 되돌리기 헬퍼가 되돌리기를 거듭 부르므로 두 번째 호출도 조용히 끝나야 한다."""
    await _run(db_session, _M.delete_seeded_rows)
    await _run(db_session, _M.delete_seeded_rows)

    assert await _seed_count(db_session) == 0
    for lane in _LANES:
        assert (await _active(db_session, lane)).id == _PREVIOUS_SET_IDS[lane]

    await _run(db_session, _M.seed_published_sets)

    for lane in _LANES:
        assert (await _active(db_session, lane)).id == _M.NEW_SET_IDS[lane]


async def test_downgrade_stops_when_the_admin_published_after_the_seed(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 되돌리기가 시드를 지워도 소설 행이 없는 어드민 게시본이 활성으로 남아 서빙 문안은 되돌아가지 않고, 이전
    코드의 그 체인 게시가 "누락"으로 막힌다 — 되돌릴 수 없다고 멈춰야 한다."""
    seeded = await _get_set(db_session, _M.NEW_SET_IDS["character"])
    assert seeded.published_at is not None
    await _copy_set(
        db_session, _M.NEW_SET_IDS["character"], status="published", published_at=seeded.published_at + timedelta(seconds=1)
    )

    with pytest.raises(RuntimeError, match="character/gemini"):
        await _run(db_session, _M.delete_seeded_rows)

    assert await _seed_count(db_session) == len(_M.NEW_SET_IDS)


async def test_downgrade_stops_when_a_version_row_uses_the_seed_as_its_base(db_session: AsyncSession) -> None:
    """시드보다 앞 시각 게시라도 그 판이 시드를 기준판으로 가리키면 지우지 않는다. 깨지는 시나리오: 기준판 FK 위반이 무엇을 해야
    하는지 알 수 없는 오류로 배포를 멈추거나, 판 사슬이 끊긴다."""
    seeded = await _get_set(db_session, _M.NEW_SET_IDS["story"])
    assert seeded.published_at is not None
    earlier = await _copy_set(
        db_session, _M.NEW_SET_IDS["story"], status="published", published_at=seeded.published_at - timedelta(seconds=10)
    )
    await db_session.execute(
        sa.text(
            "INSERT INTO prompt_set_semvers (id, prompt_set_id, lane, model, major, minor, patch, level, base_set_id)"
            " VALUES (:id, :set_id, 'story', 'gemini', 99, 0, 0, 'patch', :base)"
        ),
        {"id": uuid.uuid4(), "set_id": earlier, "base": _M.NEW_SET_IDS["story"]},
    )

    with pytest.raises(RuntimeError, match="기준판"):
        await _run(db_session, _M.delete_seeded_rows)

    assert await _seed_count(db_session) == len(_M.NEW_SET_IDS)


# ---- 가정 검사 ----------------------------------------------------------------------------------


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    with pytest.raises(RuntimeError, match="이미 있다"):
        await _run(db_session, _M.seed_published_sets)


async def test_upgrade_stops_when_a_chain_has_no_active_set(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 활성이 없는 체인을 조용히 건너뛰어 한 레인만 바뀌고, 다른 레인은 새 코드의 게시 검증에 막힌 채 남는다."""
    await _run(db_session, _M.delete_seeded_rows)
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.status == "published", PromptSet.lane == "character", PromptSet.model == "gemini")
        .values(status="archived")
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="character/gemini"):
        await _run(db_session, _M.seed_published_sets)

    assert await _seed_count(db_session) == 0


async def test_upgrade_stops_when_the_active_set_lacks_a_novel_channel(db_session: AsyncSession) -> None:
    """활성에 세 채널 중 하나라도 없으면 이 리비전의 전제(얼려 둔 행이 그대로 있다)가 깨진 것이라 두 레인 모두 아무것도 넣지 않고
    멈춘다. 깨지는 시나리오: 누가 이미 손으로 행을 지운 체인에 사본을 하나 더 쌓아 판 사슬이 사람이 모르는 변경을 담는다."""
    await _run(db_session, _M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS["character"])
    assert previous.published_at is not None
    edited = await _copy_set(
        db_session,
        _PREVIOUS_SET_IDS["character"],
        status="published",
        published_at=previous.published_at + timedelta(seconds=5),
    )
    await db_session.execute(
        sa.delete(PromptSection).where(PromptSection.prompt_set_id == edited, PromptSection.channel == "novelize_revise")
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="character/gemini"):
        await _run(db_session, _M.seed_published_sets)

    assert await _seed_count(db_session) == 0


# ---- 초안 정리 ----------------------------------------------------------------------------------


async def test_delete_draft_rows_removes_only_the_novel_rows_of_the_chat_gemini_drafts(db_session: AsyncSession) -> None:
    """채팅 Gemini 초안의 세 채널 행만 지우고 다른 행은 그대로 둔다. 소설 레인 초안의 같은 이름 채널은 건드리지 않는다. 깨지는
    시나리오: 배포 전 초안이 "잉여"로 게시가 막히거나, 소설 초안의 문안을 지워 소설 탭 편집을 잃는다."""
    story_draft = await _copy_set(db_session, _PREVIOUS_SET_IDS["story"], status="draft", published_at=None)
    novel_draft = await _copy_set(db_session, (await _active(db_session, "novel")).id, status="draft", published_at=None)
    story_before = _keyed(await _sections_of(db_session, story_draft))
    novel_before = _keyed(await _sections_of(db_session, novel_draft))
    assert {key[0] for key in story_before} >= _DROPPED

    assert await _run(db_session, _M._delete_draft_rows) == ["story"]

    assert _keyed(await _sections_of(db_session, story_draft)) == _without_dropped(story_before)
    assert _keyed(await _sections_of(db_session, novel_draft)) == novel_before
    draft = await _get_set(db_session, story_draft)
    _validate_prompt_draft_for_publish(draft, await _sections_of(db_session, story_draft), lane="story", model="gemini")

    assert await _run(db_session, _M._delete_draft_rows) == []
