"""소설 레인 문안 데이터 마이그레이션 둘의 검증.

- `fe3df6f8e4d5`: Claude 소설 체인(sonnet·opus)에 경계 제안·문단 수정·여러 문단 수정·묶음 재검사 네 채널을 소설 Gemini 활성
  세트의 바이트 사본으로 심는다.
- `e4df46a80bfa`: 소설 세 체인에 등급 규칙 채널 `novelize_rating`(scope story·character)을 채팅 Gemini 활성 세트의 등급 규칙
  본문 사본으로 심고, 원문 줄 라벨을 채팅 세트(스토리 라벨은 스토리 세트, 캐릭터 라벨은 캐릭터 세트)에서 옮긴다.

마이그레이션 자체는 다시 돌리지 않는다(앞의 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마가 이미 `upgrade head` 를 했으므로
시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows` 는 테스트마다 롤백되는
`db_session` 의 커넥션에 `run_sync` 로 직접 부른다. 기대 행은 이 파일이 DB 의 이전 활성 세트와 채팅 세트에서 직접 읽어 만든다 —
마이그레이션의 행 조립으로 기대값을 만들면 그 조립이 틀려도 테스트가 같이 틀린다."""

import hashlib
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
from api.chat.prompt_builder import ALLOWED_PLACEHOLDERS, PromptLane, load_active_prompt_set
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


_C = _load("fe3df6f8e4d5")
_B = _load("e4df46a80bfa")
# 두 리비전 직전 소설 레인 활성 — Gemini 는 여러 문단 수정 문안 리비전, Claude 두 체인은 구성안 문안 리비전의 세트다.
_PREVIOUS_SET_IDS: dict[str, uuid.UUID] = {
    "gemini": _load("174f78b92e5c").NEW_SET_IDS["gemini"],
    **{model: _load("b389c2317149").NEW_SET_IDS[model] for model in ("sonnet", "opus")},
}
_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")
_CLAUDE_MODELS: tuple[PromptSetModelId, ...] = ("sonnet", "opus")
_CHANNELS = ("novelize_boundary", "novelize_revise", "novelize_revise_blocks", "novelize_revise_recheck")
_RATING = "novelize_rating"
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")

T = TypeVar("T")

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]


def _md5(body: str) -> str:
    return hashlib.md5(body.encode()).hexdigest()


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
    db_session: AsyncSession, source_id: uuid.UUID, *, status: str, published_at: datetime | None
) -> uuid.UUID:
    """`source_id` 세트를 같은 체인에 복제한다(어드민 게시·초안 흉내)."""
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


async def _undo_both(db_session: AsyncSession) -> None:
    """실제 downgrade 순서 — 등급 규칙 리비전이 먼저, 그다음 Claude 채널 리비전."""
    await _run(db_session, _B.delete_seeded_rows)
    await _run(db_session, _C.delete_seeded_rows)


async def _seed_both(db_session: AsyncSession) -> None:
    await _run(db_session, _C.seed_published_sets)
    await _run(db_session, _B.seed_published_sets)


async def _chat_rating_rows(db_session: AsyncSession) -> dict[str, PromptSection]:
    """채팅 두 레인 Gemini 활성의 `system/rule_rating` 행 — 등급 규칙 사본의 원본."""
    rows: dict[str, PromptSection] = {}
    for lane in ("story", "character"):
        chat = await _active(db_session, lane)
        (row,) = [s for s in await _sections_of(db_session, chat.id) if (s.channel, s.slot) == ("system", "rule_rating")]
        rows[lane] = row
    return rows


# ---- 허용 자리표시자 ----------------------------------------------------------------------------


def test_the_rating_channel_allows_the_same_placeholders_as_the_chat_rating_rule() -> None:
    """등급 규칙 채널은 표에 행이 없어 게시 검증이 빈 집합을 읽는다 — 그 값이 채팅 등급 규칙의 허용 집합과 같아야 한다. 깨지는
    시나리오: 채팅 등급 규칙에 자리표시자를 허용하는 행을 더했는데 소설 쪽은 빈 집합이라 같은 문안이 소설 레인 게시에서만 막힌다."""
    assert ALLOWED_PLACEHOLDERS.get((_RATING, "rule_rating"), frozenset()) == ALLOWED_PLACEHOLDERS[("system", "rule_rating")]


# ---- 시드 결과(head 상태) --------------------------------------------------------------------


@pytest.mark.parametrize("model", _CLAUDE_MODELS)
async def test_the_claude_channel_seed_is_the_previous_claude_set_plus_the_gemini_rows(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """Claude 채널 시드는 이전 Claude 활성 행 전부 + Gemini 활성의 네 채널 행(본문·conditional·order 그대로)이고 라벨은 이전
    Claude 세트 그대로다. 깨지는 시나리오: 사본이 Claude 체인의 화 생성 행을 잃거나, 네 채널이 Gemini 와 한 바이트라도 달라 고른
    모델에 따라 경계 제안·문단 수정 글이 달라진다."""
    previous = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[model]))
    gemini = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS["gemini"]))
    seeded = _keyed(await _sections_of(db_session, _C.NEW_SET_IDS[model]))

    assert {key: value for key, value in seeded.items() if key in previous} == previous
    assert {key: value for key, value in seeded.items() if key not in previous} == {
        key: value for key, value in gemini.items() if key[0] in _CHANNELS
    }
    assert not set(previous) & {key for key in gemini if key[0] in _CHANNELS}
    previous_set = await _get_set(db_session, _PREVIOUS_SET_IDS[model])
    seeded_set = await _get_set(db_session, _C.NEW_SET_IDS[model])
    assert [getattr(seeded_set, label) for label in _LABELS] == [getattr(previous_set, label) for label in _LABELS]
    assert seeded_set.published_at is not None and previous_set.published_at is not None
    assert seeded_set.published_at > previous_set.published_at


@pytest.mark.parametrize("model", _MODELS)
async def test_each_novel_chain_is_active_at_the_rating_seed_with_the_chat_rating_rule_and_labels(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """세 체인 활성은 등급 규칙 시드이고, 그 세트는 직전 활성 행 전부 + 등급 규칙 두 행(채팅 Gemini 활성 본문 그대로)이다. 라벨은
    사용자·스토리 라벨이 스토리 채팅 세트, 캐릭터 라벨이 캐릭터 채팅 세트 값이다. 깨지는 시나리오: 캐릭터 라벨을 스토리 세트에서
    읽어 캐릭터 원작 소설의 원문 줄 라벨이 대화 때와 달라지거나, 등급 규칙 사본이 채팅 원본과 달라 소설 수위가 바뀐다."""
    assert (await _active(db_session, "novel", model)).id == _B.NEW_SET_IDS[model]
    before_id = _C.NEW_SET_IDS[model] if model in _CLAUDE_MODELS else _PREVIOUS_SET_IDS["gemini"]
    before = _keyed(await _sections_of(db_session, before_id))
    seeded = _keyed(await _sections_of(db_session, _B.NEW_SET_IDS[model]))

    assert {key: value for key, value in seeded.items() if key in before} == before
    chat_rows = await _chat_rating_rows(db_session)
    added = {key: value for key, value in seeded.items() if key not in before}
    assert {key: (_md5(body), cond, order) for key, (body, cond, order) in added.items()} == {
        (_RATING, scope, "rule_rating", ""): (_md5(chat_rows[scope].body), chat_rows[scope].conditional, 0)
        for scope in ("story", "character")
    }

    # `_active`·`_sections_of` 가 식별자 맵을 만료시키므로 읽은 즉시 값을 꺼내 둔다.
    story_chat = await _active(db_session, "story")
    story_user, story_assistant = story_chat.user_label, story_chat.story_assistant_label
    character_chat = await _active(db_session, "character")
    character_user, character_assistant = character_chat.user_label, character_chat.character_assistant_label
    before_set = await _get_set(db_session, before_id)
    seeded_set = await _get_set(db_session, _B.NEW_SET_IDS[model])
    assert seeded_set.user_label == story_user == character_user
    assert seeded_set.story_assistant_label == story_assistant
    assert seeded_set.character_assistant_label == character_assistant
    assert seeded_set.story_example_label == before_set.story_example_label
    assert seeded_set.published_at is not None and before_set.published_at is not None
    assert seeded_set.published_at > before_set.published_at


@pytest.mark.parametrize("model", _MODELS)
async def test_the_seeded_sets_pass_publish_validation(db_session: AsyncSession, model: PromptSetModelId) -> None:
    """깨지는 시나리오: 시드가 게시 검증의 슬롯 집합과 어긋나 배포 직후 소설 레인 그 체인의 어드민 게시가 "누락·잉여"로 막힌다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="novel", model=model)
    _validate_prompt_draft_for_publish(prompt_set, sections, lane="novel", model=model)


@pytest.mark.parametrize("model", _MODELS)
async def test_the_rating_seed_gets_a_minor_bump_on_top_of_the_previous_chain_version(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """두 시드 모두 판 행을 받는다 — 체인 판은 직전 활성을 기준판으로 minor, 새로 들어온 채널은 1.0.0 minor. 깨지는 시나리오:
    판 행이 없어 다음 어드민 게시가 이 변경을 자기 판에 섞어 세거나, 기준판이 틀려 판 사슬이 끊긴다."""
    async def semver(set_id: uuid.UUID) -> tuple[object, ...]:
        return tuple(
            (
                await db_session.execute(
                    sa.text("SELECT level, base_set_id FROM prompt_set_semvers WHERE prompt_set_id = :id"),
                    {"id": set_id},
                )
            ).one()
        )

    async def section_semvers(set_id: uuid.UUID) -> dict[str, tuple[int, int, int, str | None]]:
        rows = await db_session.execute(
            sa.text("SELECT channel, major, minor, patch, level FROM prompt_section_semvers WHERE prompt_set_id = :id"),
            {"id": set_id},
        )
        return {channel: (major, minor, patch, level) for channel, major, minor, patch, level in rows}

    before_id = _C.NEW_SET_IDS[model] if model in _CLAUDE_MODELS else _PREVIOUS_SET_IDS["gemini"]
    assert await semver(_B.NEW_SET_IDS[model]) == ("minor", before_id)
    assert (await section_semvers(_B.NEW_SET_IDS[model]))[_RATING] == (1, 0, 0, "minor")
    if model in _CLAUDE_MODELS:
        assert await semver(_C.NEW_SET_IDS[model]) == ("minor", _PREVIOUS_SET_IDS[model])
        claude = await section_semvers(_C.NEW_SET_IDS[model])
        assert {channel: claude[channel] for channel in _CHANNELS} == {channel: (1, 0, 0, "minor") for channel in _CHANNELS}


# ---- 옛 이미지 × 새 데이터 --------------------------------------------------------------------------


async def test_the_two_revisions_leave_every_chat_chain_untouched(db_session: AsyncSession) -> None:
    """옛 이미지는 라벨·등급 규칙을 계속 채팅 Gemini 세트에서 읽고 소설 채널은 이전과 같은 행을 렌더한다(등급 규칙 채널은 읽지
    않는다). 그래서 두 리비전이 채팅 체인의 활성·행을 하나도 바꾸지 않아야 옛 이미지의 렌더가 그대로다. 깨지는 시나리오: 시드가
    채팅 세트의 등급 규칙이나 라벨을 고쳐 배포 겹침 동안 옛 이미지의 채팅·소설 글이 바뀐다."""
    lanes: tuple[PromptLane, ...] = ("story", "character")
    models: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")
    chains: list[tuple[PromptLane, PromptSetModelId]] = [(lane, model) for lane in lanes for model in models]
    async def snapshot() -> dict[tuple[str, str], tuple[uuid.UUID, list[str], dict[Key, Value]]]:
        taken: dict[tuple[str, str], tuple[uuid.UUID, list[str], dict[Key, Value]]] = {}
        for chain in chains:
            active = await _active(db_session, *chain)
            set_id, labels = active.id, [getattr(active, label) for label in _LABELS]
            taken[chain] = (set_id, labels, _keyed(await _sections_of(db_session, set_id)))
        return taken

    at_head = await snapshot()

    await _undo_both(db_session)

    assert await snapshot() == at_head


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_every_novel_chain_back_and_forth(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 되돌리기가 시드나 초안 행을 남겨 다시 올릴 때 "이미 있다"로 배포가 멈추거나, 이전 활성으로 돌아가지 않는다.
    다른 레인 테스트가 되돌리기를 거듭 부르므로 두 번째 호출도 조용히 끝나야 한다."""
    await _undo_both(db_session)
    await _undo_both(db_session)

    for model in _MODELS:
        assert (await _active(db_session, "novel", model)).id == _PREVIOUS_SET_IDS[model]
    for set_id in [*_B.NEW_SET_IDS.values(), *_C.NEW_SET_IDS.values()]:
        assert await db_session.get(PromptSet, set_id) is None
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.channel == _RATING)
    )
    assert remaining == 0

    await _seed_both(db_session)

    for model in _MODELS:
        assert (await _active(db_session, "novel", model)).id == _B.NEW_SET_IDS[model]


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    with pytest.raises(RuntimeError, match="이미 있다"):
        await _run(db_session, _B.seed_published_sets)
    await _run(db_session, _B.delete_seeded_rows)
    with pytest.raises(RuntimeError, match="이미 있다"):
        await _run(db_session, _C.seed_published_sets)


async def test_rating_upgrade_stops_when_the_two_chat_sets_disagree_on_the_user_label(db_session: AsyncSession) -> None:
    """소설 세트에는 사용자 라벨 칸이 하나뿐이다 — 두 채팅 세트 값이 다르면 어느 쪽을 옮겨도 한 원작 종류의 원문 줄 라벨이 대화 때와
    달라지므로 아무것도 넣지 않고 멈춘다. 깨지는 시나리오: 스토리 값만 옮겨 캐릭터 원작 소설의 사용자 줄 라벨이 조용히 바뀐다."""
    await _run(db_session, _B.delete_seeded_rows)
    story_chat = await _active(db_session, "story")
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.id == story_chat.id).values(user_label="합성 사용자 라벨")
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="user_label"):
        await _run(db_session, _B.seed_published_sets)

    for set_id in _B.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is None


@pytest.mark.parametrize("late_model", ["opus", "sonnet"])
async def test_both_upgrades_seed_every_chain_when_the_lanes_latest_set_is_not_gemini(
    db_session: AsyncSession, late_model: PromptSetModelId
) -> None:
    """운영 꼴 — 소설 레인 전체의 최신 게시가 Gemini 가 아니어도(어드민이 Claude 체인을 나중에, 지금보다 뒤 시각으로 게시) 두 시드가
    (레인, 모델)별 활성만 보고 세 체인 모두에 새 세트를 넣는다. 새 세트 시각은 그 체인 활성 + 1초다. 깨지는 시나리오: 레인 전체 최신이
    Gemini 라는 단언이 운영 upgrade 를 멈추거나, 새 세트 시각이 미래 시각 활성보다 앞이라 옛 세트가 계속 뽑힌다."""
    await _undo_both(db_session)
    previous_at = (await _get_set(db_session, _PREVIOUS_SET_IDS[late_model])).published_at
    assert previous_at is not None
    late_at = max(previous_at, datetime.now(previous_at.tzinfo)) + timedelta(hours=1)
    late_id = await _copy_set(db_session, _PREVIOUS_SET_IDS[late_model], status="published", published_at=late_at)
    latest_model = await db_session.scalar(
        sa.select(PromptSet.model)
        .where(PromptSet.status == "published", PromptSet.lane == "novel")
        .order_by(PromptSet.published_at.desc())
        .limit(1)
    )
    assert latest_model == late_model

    await _seed_both(db_session)

    for model in _MODELS:
        assert (await _active(db_session, "novel", model)).id == _B.NEW_SET_IDS[model]
    claude_seed = await _get_set(db_session, _C.NEW_SET_IDS[late_model])
    assert claude_seed.published_at == late_at + timedelta(seconds=1)
    source = _keyed(await _sections_of(db_session, late_id))
    seeded = _keyed(await _sections_of(db_session, _C.NEW_SET_IDS[late_model]))
    assert {key: value for key, value in seeded.items() if key in source} == source


async def test_claude_upgrade_stops_when_a_claude_set_already_has_a_structured_row(db_session: AsyncSession) -> None:
    await _undo_both(db_session)
    latest = (await _get_set(db_session, _PREVIOUS_SET_IDS["opus"])).published_at
    assert latest is not None
    edited = await _copy_set(
        db_session, _PREVIOUS_SET_IDS["opus"], status="published", published_at=latest + timedelta(seconds=5)
    )
    db_session.add(
        PromptSection(
            prompt_set_id=edited,
            channel="novelize_revise",
            scope="both",
            slot="instruction",
            variant="",
            body="합성 지시문",
            conditional=False,
            order=99,
        )
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="novel/opus"):
        await _run(db_session, _C.seed_published_sets)

    for set_id in _C.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is None


async def test_rating_downgrade_stops_when_the_admin_published_after_the_seed(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 되돌리기가 시드를 지워 등급 규칙 행이 든 어드민 게시본이 활성으로 남고, 옛 이미지의 그 체인 게시가 막힌다."""
    seeded = await _get_set(db_session, _B.NEW_SET_IDS["gemini"])
    assert seeded.published_at is not None
    await _copy_set(
        db_session, _B.NEW_SET_IDS["gemini"], status="published", published_at=seeded.published_at + timedelta(seconds=1)
    )

    with pytest.raises(RuntimeError, match="novel/gemini"):
        await _run(db_session, _B.delete_seeded_rows)

    for set_id in _B.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is not None


async def test_rating_downgrade_stops_when_a_version_row_uses_the_seed_as_its_base(db_session: AsyncSession) -> None:
    """시드보다 앞 시각 게시라도 그 판이 시드를 기준판으로 가리키면 지우지 않는다. 깨지는 시나리오: 기준판 FK 위반이 무엇을 해야
    하는지 알 수 없는 오류로 배포를 멈추거나, 판 사슬이 끊긴다."""
    seeded = await _get_set(db_session, _B.NEW_SET_IDS["gemini"])
    assert seeded.published_at is not None
    earlier = await _copy_set(
        db_session, _B.NEW_SET_IDS["gemini"], status="published", published_at=seeded.published_at - timedelta(seconds=10)
    )
    await db_session.execute(
        sa.text(
            "INSERT INTO prompt_set_semvers (id, prompt_set_id, lane, model, major, minor, patch, level, base_set_id)"
            " VALUES (:id, :set_id, 'novel', 'gemini', 99, 0, 0, 'patch', :base)"
        ),
        {"id": uuid.uuid4(), "set_id": earlier, "base": _B.NEW_SET_IDS["gemini"]},
    )

    with pytest.raises(RuntimeError, match="기준판"):
        await _run(db_session, _B.delete_seeded_rows)

    for set_id in _B.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is not None


async def test_claude_downgrade_stops_while_the_rating_seed_is_still_on_top(db_session: AsyncSession) -> None:
    """등급 규칙 시드가 Claude 채널 시드 위에 게시돼 있고 그 판의 기준판이다 — 순서를 거꾸로 되돌리면 멈춘다. 깨지는 시나리오:
    Claude 채널 시드를 먼저 지워 등급 규칙 시드의 기준판이 사라진다."""
    with pytest.raises(RuntimeError):
        await _run(db_session, _C.delete_seeded_rows)

    for set_id in _C.NEW_SET_IDS.values():
        assert await db_session.get(PromptSet, set_id) is not None


# ---- 초안 제자리 패치 ----------------------------------------------------------------------------


async def test_claude_patch_drafts_adds_the_structured_rows_in_place_and_downgrade_removes_them(
    db_session: AsyncSession,
) -> None:
    """네 채널이 없는 Claude 초안(배포 전 활성본에서 만든 초안)에 Gemini 활성의 같은 행을 넣고, 다 있으면 건드리지 않는다. 깨지는
    시나리오: 배포 전부터 있던 Claude 초안이 "누락"으로 게시가 막히거나, 패치가 다른 행을 바꿔 운영자 편집을 잃는다."""
    draft_id = await _copy_set(db_session, _PREVIOUS_SET_IDS["sonnet"], status="draft", published_at=None)
    before = _keyed(await _sections_of(db_session, draft_id))

    patched_what = await _run(db_session, _C._patch_drafts)
    assert sorted(patched_what) == sorted(("sonnet", channel) for channel in _CHANNELS)
    patched = _keyed(await _sections_of(db_session, draft_id))
    assert {key: value for key, value in patched.items() if key in before} == before
    seeded = _keyed(await _sections_of(db_session, _C.NEW_SET_IDS["sonnet"]))
    assert {key: value for key, value in patched.items() if key not in before} == {
        key: value for key, value in seeded.items() if key[0] in _CHANNELS
    }

    assert await _run(db_session, _C._patch_drafts) == []

    await _run(db_session, _C._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_rating_patch_drafts_adds_the_rating_rows_and_labels_in_place(db_session: AsyncSession) -> None:
    """등급 규칙 행이 없는 소설 초안에 시드와 같은 두 행을 넣고 라벨 셋을 채팅 값으로 맞춘 뒤 게시 검증을 통과한다. 이미 있으면
    건드리지 않는다. 되돌리기는 그 행만 지운다. 깨지는 시나리오: 배포 전 초안이 "누락"으로 게시가 막히거나, 초안 라벨이 옛 사본으로
    남아 그 초안을 게시하면 캐릭터 원작 원문 줄 라벨이 바뀐다."""
    draft_id = await _copy_set(db_session, _PREVIOUS_SET_IDS["gemini"], status="draft", published_at=None)
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.id == draft_id).values(character_assistant_label="합성 옛 라벨")
    )
    await db_session.flush()
    before = _keyed(await _sections_of(db_session, draft_id))

    assert await _run(db_session, _B._patch_drafts) == ["gemini"]
    patched = _keyed(await _sections_of(db_session, draft_id))
    seeded = _keyed(await _sections_of(db_session, _B.NEW_SET_IDS["gemini"]))
    assert {key: value for key, value in patched.items() if key in before} == before
    assert {key: value for key, value in patched.items() if key not in before} == {
        key: value for key, value in seeded.items() if key[0] == _RATING
    }
    draft = await _get_set(db_session, draft_id)
    seeded_set = await _get_set(db_session, _B.NEW_SET_IDS["gemini"])
    assert [draft.user_label, draft.story_assistant_label, draft.character_assistant_label] == [
        seeded_set.user_label,
        seeded_set.story_assistant_label,
        seeded_set.character_assistant_label,
    ]
    draft_sections = await _sections_of(db_session, draft_id)
    draft = await _get_set(db_session, draft_id)
    _validate_prompt_draft_for_publish(draft, draft_sections, lane="novel", model="gemini")

    assert await _run(db_session, _B._patch_drafts) == []

    await _run(db_session, _B._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before
