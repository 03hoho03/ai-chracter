"""프롬프트 체인 판 표(`prompt_set_semvers`)와 섹션 판 표(`prompt_section_semvers`)의 제약, 백필, downgrade 가드.

`alembic check` 는 CHECK 제약을 비교하지 않으므로 아래 `IntegrityError` 테스트가 그 제약의 유일한 신호다. 유니크 둘(같은
기준판, 같은 체인 번호)은 `alembic check` 도 보지만 동시 게시 경합을 막는 실체라 행위로도 고정한다. downgrade·upgrade 를 실제로
돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 리비전 함수를 직접 부른다 — 워커 DB 에 커밋되면 다른 테스트와 세션
끝의 `downgrade base` 를 깬다."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import PromptSectionSemver, PromptSet, PromptSetSemver

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_CHAIN = ("story", "semver-schema-test")


def _load_schema_migration() -> ModuleType:
    (path,) = _VERSIONS_DIR.glob("*_prompt_semvers.py")
    spec = importlib.util.spec_from_file_location("_migration_prompt_semvers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_schema_migration()


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 이 리비전 뒤 게시 세트에 판을 매겨 넣은 문안 리비전 — 등급 규칙 채널을 소설 세 체인에 심은 것과 그 앞의 Claude 소설 체인 채널을
# 심은 것. 둘의 판 행은 단계가 있어 이 리비전의 downgrade 를 멈추게 하므로, downgrade 를 실제로 돌리는 테스트는 실제 downgrade
# 순서대로 그 둘부터 되돌린 상태를 기준으로 본다(롤백되는 트랜잭션 안).
_LATER_SEEDS: tuple[ModuleType, ...] = (_load("e4df46a80bfa"), _load("fe3df6f8e4d5"))


async def _undo_later_seeds(connection: AsyncConnection) -> None:
    for later in _LATER_SEEDS:
        await connection.run_sync(later.delete_seeded_rows)


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _rejects(db: AsyncSession, row: object, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with db.begin_nested():
            db.add(row)
            await db.flush()


async def _published_sets(db: AsyncSession, count: int, *, chain: tuple[str, str] = _CHAIN) -> list[uuid.UUID]:
    """판을 매길 게시 세트를 섹션 없이 넣는다(제약만 보는 테스트라 내용은 필요 없다)."""
    lane, model = chain
    ids = [uuid.uuid4() for _ in range(count)]
    for index, set_id in enumerate(ids):
        db.add(
            PromptSet(
                id=set_id,
                version=str(90000 + index),
                status="published",
                lane=lane,
                model=model,
                user_label="사용자",
                story_assistant_label="진행자",
                story_example_label="서술자",
                character_assistant_label="캐릭터",
                published_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
            )
        )
    await db.flush()
    return ids


def _chain_row(set_id: uuid.UUID, **overrides: object) -> PromptSetSemver:
    values: dict[str, object] = {
        "prompt_set_id": set_id,
        "lane": _CHAIN[0],
        "model": _CHAIN[1],
        "major": 1,
        "minor": 0,
        "patch": 0,
        "level": None,
        "base_set_id": None,
    }
    values.update(overrides)
    return PromptSetSemver(**values)


def _section_row(set_id: uuid.UUID, **overrides: object) -> PromptSectionSemver:
    values: dict[str, object] = {
        "prompt_set_id": set_id,
        "channel": "generation",
        "major": 1,
        "minor": 0,
        "patch": 0,
        "level": None,
    }
    values.update(overrides)
    return PromptSectionSemver(**values)


# ── 체인 판 CHECK ────────────────────────────────────────────────────────────
async def test_chain_semver_parts_must_start_at_one_point_zero_point_zero(db_session: AsyncSession) -> None:
    """앞자리는 1 이상, 나머지는 0 이상이다. 깨지는 시나리오: 계산 실수로 0.x 나 음수 번호가 저장돼 화면의 판 비교가
    뒤집힌다."""
    (set_id,) = await _published_sets(db_session, 1)
    await _rejects(db_session, _chain_row(set_id, major=0), "ck_prompt_set_semvers_parts_range")
    await _rejects(db_session, _chain_row(set_id, minor=-1), "ck_prompt_set_semvers_parts_range")
    await _rejects(db_session, _chain_row(set_id, patch=-1), "ck_prompt_set_semvers_parts_range")


async def test_chain_semver_level_is_one_of_three(db_session: AsyncSession) -> None:
    """단계는 major·minor·patch 셋뿐이다. 깨지는 시나리오: 오타 난 단계가 저장돼 이력 화면이 단계를 읽지 못한다."""
    base_id, set_id = await _published_sets(db_session, 2)
    await _rejects(
        db_session, _chain_row(set_id, level="huge", base_set_id=base_id), "ck_prompt_set_semvers_level_values"
    )


async def test_chain_semver_level_and_base_come_together(db_session: AsyncSession) -> None:
    """단계와 기준판은 함께 있거나 함께 없다. 깨지는 시나리오: 단계는 있는데 무엇과 견줬는지 모르는 판, 또는 기준판과
    견줬는데 단계가 빠진 판이 저장돼 판 사슬을 되짚을 수 없다."""
    base_id, set_id = await _published_sets(db_session, 2)
    await _rejects(db_session, _chain_row(set_id, level="patch"), "ck_prompt_set_semvers_level_iff_base")
    await _rejects(db_session, _chain_row(set_id, base_set_id=base_id), "ck_prompt_set_semvers_level_iff_base")


async def test_chain_semver_is_not_its_own_base(db_session: AsyncSession) -> None:
    """자기 자신을 기준판으로 두지 않는다. 깨지는 시나리오: 기준판 조회가 방금 넣은 세트를 집어 자기와 견준 판이 저장된다."""
    (set_id,) = await _published_sets(db_session, 1)
    await _rejects(
        db_session, _chain_row(set_id, level="patch", base_set_id=set_id), "ck_prompt_set_semvers_not_own_base"
    )


# ── 섹션 판 CHECK ────────────────────────────────────────────────────────────
async def test_section_semver_parts_and_level_are_checked(db_session: AsyncSession) -> None:
    """섹션 판도 번호 범위와 단계 값을 지킨다. 깨지는 시나리오: 섹션 판에만 0.x 번호나 오타 단계가 저장된다."""
    (set_id,) = await _published_sets(db_session, 1)
    await _rejects(db_session, _section_row(set_id, major=0), "ck_prompt_section_semvers_parts_range")
    await _rejects(db_session, _section_row(set_id, level="huge"), "ck_prompt_section_semvers_level_values")


# ── 유니크(경합 방어) ────────────────────────────────────────────────────────
async def test_one_base_is_used_once_and_a_chain_number_once(db_session: AsyncSession) -> None:
    """한 판은 다음 판의 기준이 한 번만 되고, 체인 안 같은 번호는 한 번뿐이다. 깨지는 시나리오: 같은 기준판을 읽은 동시
    게시 둘이 1.0.1 과 1.1.0 으로 갈려 둘 다 저장돼 판 사슬이 두 갈래가 된다."""
    base_id, first_id, second_id = await _published_sets(db_session, 3)
    db_session.add_all(
        [
            _chain_row(base_id),
            _chain_row(first_id, patch=1, level="patch", base_set_id=base_id),
        ]
    )
    await db_session.flush()

    await _rejects(
        db_session,
        _chain_row(second_id, minor=1, level="minor", base_set_id=base_id),
        "ix_prompt_set_semvers_base_set_id",
    )
    await _rejects(
        db_session,
        _chain_row(second_id, patch=1, level="patch", base_set_id=first_id),
        "ix_prompt_set_semvers_chain_semver",
    )


# ── 삭제 ────────────────────────────────────────────────────────────────────
async def test_deleting_a_set_removes_its_semvers_but_a_set_used_as_a_base_cannot_be_deleted(
    db_session: AsyncSession,
) -> None:
    """판 행은 세트와 함께 지워지고(백필만 있는 체인을 통째로 지우는 코드가 판 표를 몰라도 된다), 다음 판의 기준이 된 세트는
    그 판을 남긴 채 지울 수 없다. 깨지는 시나리오: 판 표를 모르는 체인 삭제 코드가 FK 위반으로 500 이 되거나, 기준판만
    지워져 판 사슬이 끊긴다."""
    base_id, set_id = await _published_sets(db_session, 2)
    db_session.add_all(
        [
            _chain_row(base_id),
            _chain_row(set_id, patch=1, level="patch", base_set_id=base_id),
            _section_row(base_id),
            _section_row(set_id, patch=1, level="patch"),
        ]
    )
    await db_session.flush()

    with pytest.raises(IntegrityError, match="prompt_set_semvers_base_set_id_fkey"):
        async with db_session.begin_nested():
            await db_session.execute(sa.delete(PromptSet).where(PromptSet.id == base_id))

    await db_session.execute(sa.delete(PromptSet).where(PromptSet.id == set_id))
    await db_session.execute(sa.delete(PromptSet).where(PromptSet.lane == _CHAIN[0], PromptSet.model == _CHAIN[1]))
    left = (
        await db_session.scalar(
            sa.select(sa.func.count()).select_from(PromptSetSemver).where(PromptSetSemver.model == _CHAIN[1])
        ),
        await db_session.scalar(
            sa.select(sa.func.count())
            .select_from(PromptSectionSemver)
            .where(PromptSectionSemver.prompt_set_id.in_([base_id, set_id]))
        ),
    )
    assert left == (0, 0)


# ── 백필·왕복 ──────────────────────────────────────────────────────────────
_SNAPSHOT_SETS = sa.text("SELECT id, version FROM prompt_sets ORDER BY id")
_SNAPSHOT_SECTIONS = sa.text(
    "SELECT md5(string_agg(concat_ws('|', prompt_set_id, channel, scope, slot, variant, body, conditional, \"order\"),"
    " E'\\n' ORDER BY prompt_set_id, channel, scope, slot, variant)) FROM prompt_sections"
)
_ACTIVE_LANES = ("story", "character", "publish_filter", "novel", "novel_screen")


async def _semver_state(connection: AsyncConnection) -> tuple[set[tuple[object, ...]], set[tuple[object, ...]]]:
    chains = {
        tuple(row)
        for row in await connection.execute(
            sa.text("SELECT prompt_set_id, lane, model, major, minor, patch, level, base_set_id FROM prompt_set_semvers")
        )
    }
    sections = {
        tuple(row)
        for row in await connection.execute(
            sa.text("SELECT prompt_set_id, channel, major, minor, patch, level FROM prompt_section_semvers")
        )
    }
    return chains, sections


async def _expected_backfill(connection: AsyncConnection) -> tuple[set[tuple[object, ...]], set[tuple[object, ...]]]:
    """백필이 매겨야 할 행을 SQL 이 아니라 파이썬으로 따로 계산한다 — 체인마다 `published_at` 이 가장 늦은(같으면 id 가 큰)
    게시 세트, 그 세트의 채널마다와 화자 라벨 묶음."""
    published = (
        await connection.execute(
            sa.text("SELECT id, lane, model, published_at FROM prompt_sets WHERE status = 'published'")
        )
    ).all()
    latest: dict[tuple[str, str], tuple[datetime, uuid.UUID]] = {}
    for set_id, lane, model, published_at in published:
        if lane not in _ACTIVE_LANES:
            continue
        key = (published_at, set_id)
        if (lane, model) not in latest or key > latest[(lane, model)]:
            latest[(lane, model)] = key
    chains: set[tuple[object, ...]] = {
        (set_id, lane, model, 1, 0, 0, None, None) for (lane, model), (_, set_id) in latest.items()
    }
    sections: set[tuple[object, ...]] = set()
    for (_, set_id) in latest.values():
        channels = (
            await connection.execute(
                sa.text("SELECT DISTINCT channel FROM prompt_sections WHERE prompt_set_id = :id"), {"id": set_id}
            )
        ).scalars()
        sections |= {(set_id, channel, 1, 0, 0, None) for channel in [*channels, "speaker_labels"]}
    return chains, sections


async def test_backfill_marks_only_each_chains_active_set_and_leaves_existing_rows_untouched(
    ddl_engine: AsyncEngine,
) -> None:
    """체인마다 활성 세트 하나와 그 섹션·화자 라벨만 1.0.0 이고, legacy 는 빠지며, 정수 번호와 섹션 내용은 그대로다. 깨지는
    시나리오: 백필이 가장 오래된 게시본을 활성으로 집거나, legacy 를 매기거나, 기존 행을 고쳐 정수 번호·내용 해시로 대조하는
    측정 도구가 어긋난다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _undo_later_seeds(connection)
            head_state = await _semver_state(connection)
            sets_before = (await connection.execute(_SNAPSHOT_SETS)).all()
            sections_before = await connection.scalar(_SNAPSHOT_SECTIONS)

            await _run(connection, _M.downgrade)
            await _run(connection, _M.upgrade)
            state = await _semver_state(connection)
            expected = await _expected_backfill(connection)
            legacy_rows = await connection.scalar(
                sa.text("SELECT count(*) FROM prompt_set_semvers WHERE lane = 'legacy'")
            )
            sets_after = (await connection.execute(_SNAPSHOT_SETS)).all()
            sections_after = await connection.scalar(_SNAPSHOT_SECTIONS)
        finally:
            await transaction.rollback()

    assert len(expected[0]) == 13  # 테스트 DB 의 legacy 아닌 체인 수(레인·모델 쌍)
    assert {row[1:] for row in state[0]} == {row[1:] for row in expected[0]}
    assert state[0] == expected[0]
    assert state[1] == expected[1]
    assert legacy_rows == 0
    assert state == head_state
    assert sets_after == sets_before
    assert sections_after == sections_before


async def test_backfill_picks_the_latest_published_set_even_when_an_older_one_has_the_larger_version(
    ddl_engine: AsyncEngine,
) -> None:
    """한 체인에서 정수 번호는 더 크지만 더 일찍 게시된 세트와, 번호는 작지만 더 늦게 게시된 세트가 있으면 백필은 늦게 게시된
    쪽(서빙이 활성으로 쓰는 쪽)에만 1.0.0 을 준다. 깨지는 시나리오: 백필이 정수 번호 최대를 활성판으로 집어, 서빙 중인 세트에는
    판이 없고 서빙하지 않는 세트가 다음 게시의 기준판이 된다."""
    chain = ("story", "semver-backfill-order")
    later_id, earlier_id = uuid.uuid4(), uuid.uuid4()
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _undo_later_seeds(connection)
            await _run(connection, _M.downgrade)
            for set_id, version, published_at in (
                (later_id, "99001", datetime(2026, 1, 2, tzinfo=UTC)),
                (earlier_id, "99002", datetime(2026, 1, 1, tzinfo=UTC)),
            ):
                await connection.execute(
                    sa.text(
                        "INSERT INTO prompt_sets (id, version, status, lane, model, user_label, story_assistant_label,"
                        " story_example_label, character_assistant_label, note, published_at) VALUES (:id, :version,"
                        " 'published', :lane, :model, '사용자', '진행자', '서술자', '캐릭터', '', :published_at)"
                    ),
                    {
                        "id": set_id,
                        "version": version,
                        "lane": chain[0],
                        "model": chain[1],
                        "published_at": published_at,
                    },
                )
            await _run(connection, _M.upgrade)
            numbered = (
                await connection.execute(
                    sa.text("SELECT prompt_set_id, major, minor, patch FROM prompt_set_semvers WHERE model = :model"),
                    {"model": chain[1]},
                )
            ).all()
        finally:
            await transaction.rollback()

    assert [tuple(row) for row in numbered] == [(later_id, 1, 0, 0)]


async def test_downgrade_refuses_once_a_publish_assigned_a_semver_and_round_trips_otherwise(
    ddl_engine: AsyncEngine,
) -> None:
    """게시로 매긴 판(단계 있음)이 하나라도 있으면 downgrade 가 아무것도 지우기 전에 멈추고, 없으면 내렸다 올려도 백필 결과가
    같다. 깨지는 시나리오: downgrade 가 어드민 게시가 쌓은 판 이력을 조용히 지운다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _undo_later_seeds(connection)
            session = AsyncSession(bind=connection)
            head_state = await _semver_state(connection)
            base_id = await connection.scalar(
                sa.text("SELECT prompt_set_id FROM prompt_set_semvers WHERE lane = 'story' AND model = 'gemini'")
            )
            (set_id,) = await _published_sets(session, 1, chain=("story", "gemini"))
            session.add(
                _chain_row(set_id, lane="story", model="gemini", patch=1, level="patch", base_set_id=base_id)
            )
            await session.flush()

            with pytest.raises(RuntimeError, match="판"):
                async with connection.begin_nested():
                    await _run(connection, _M.downgrade)
            kept = await connection.scalar(sa.text("SELECT count(*) FROM prompt_set_semvers"))

            await connection.execute(sa.text("DELETE FROM prompt_sets WHERE id = :id"), {"id": set_id})
            await _run(connection, _M.downgrade)
            tables_after_down = (
                await connection.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables"
                        " WHERE table_name IN ('prompt_set_semvers', 'prompt_section_semvers')"
                    )
                )
            ).all()
            await _run(connection, _M.upgrade)
            round_trip = await _semver_state(connection)
        finally:
            await transaction.rollback()

    assert kept == len(head_state[0]) + 1
    assert tables_after_down == []
    assert {row[1:] for row in round_trip[0]} == {row[1:] for row in head_state[0]}
    assert {row[0] for row in round_trip[0]} == {row[0] for row in head_state[0]}
    assert round_trip[1] == head_state[1]
