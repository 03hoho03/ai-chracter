"""방 모델별 단계 배정 표(`prompt_routes`)와 저장 이력 표(`prompt_route_revisions`)의 제약과 downgrade 가드·왕복.

`alembic check` 는 CHECK 제약과 부분 인덱스 술어를 비교하지 않으므로, 아래 `IntegrityError` 테스트가 그 제약의 유일한 신호다.
downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다."""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import PromptRoute, PromptRouteRevision
from factories import _create_admin

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load_schema_migration() -> ModuleType:
    (path,) = _VERSIONS_DIR.glob("*_prompt_routes.py")
    spec = importlib.util.spec_from_file_location("_migration_prompt_routes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_schema_migration()


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


def _route(stage: str, *, chain_model: str | None, call_model: str, **overrides: str) -> PromptRoute:
    values: dict[str, str | None] = {
        "lane": "story",
        "room_model": "opus",
        "stage": stage,
        "chain_model": chain_model,
        "call_model": call_model,
        "backend": "anthropic",
    }
    values.update(overrides)
    return PromptRoute(**values)


async def _revision(db: AsyncSession, number: int, rows: list[dict[str, str | None]] | None = None) -> None:
    admin = await _create_admin(db)
    db.add(PromptRouteRevision(number=number, rows=rows or [], admin_id=admin["id"]))
    await db.flush()


# ── 설정 표 ──────────────────────────────────────────────────────────────────
async def test_a_generation_route_must_not_name_a_chain(db_session: AsyncSession) -> None:
    """생성 행은 체인을 두지 않는다. 깨지는 시나리오: 생성 행에 다른 체인이 저장돼, 그 행을 믿는 코드가 방 모델과 다른 문안으로
    글을 쓴다."""
    await _rejects(
        db_session,
        _route("chat_generate", chain_model="gemini", call_model="opus"),
        "ck_prompt_routes_generation_has_no_chain",
    )


async def test_a_judgment_route_must_name_a_chain(db_session: AsyncSession) -> None:
    """판정 행은 체인을 반드시 둔다. 깨지는 시나리오: 체인 없는 판정 행이 저장돼 판정이 어느 문안을 읽을지 정해지지 않는다."""
    await _rejects(
        db_session,
        _route("stat_judgment", chain_model=None, call_model="haiku"),
        "ck_prompt_routes_generation_has_no_chain",
    )


async def test_a_generation_route_must_call_the_room_model(db_session: AsyncSession) -> None:
    """생성 호출 모델은 방 모델과 같다. 깨지는 시나리오: 비싼 방 모델 단가로 차감하면서 다른 모델을 불러 값과 원가가 어긋난다."""
    await _rejects(
        db_session,
        _route("chat_generate", chain_model=None, call_model="gemini", backend="gemini"),
        "ck_prompt_routes_generation_calls_room_model",
    )


async def test_a_judgment_route_may_read_one_chain_and_call_another_model(db_session: AsyncSession) -> None:
    """판정 행은 한 체인을 읽고 다른 모델을 부를 수 있고, 생성 행은 체인 없이 방 모델을 부르면 들어간다. 깨지는 시나리오:
    CHECK 를 너무 좁게 써서 판정 모델만 바꾸는 저장과 평범한 생성 행 저장이 500 이 된다."""
    db_session.add_all(
        [
            _route("stat_judgment", chain_model="haiku", call_model="gemini", backend="gemini"),
            _route("chat_generate", chain_model=None, call_model="opus"),
        ]
    )
    await db_session.flush()


async def test_one_route_per_lane_room_model_and_stage(db_session: AsyncSession) -> None:
    """같은 (레인, 방 모델, 단계)는 한 행뿐이다. 깨지는 시나리오: 같은 키 두 행이 저장돼 어느 배정을 따를지 조회마다 달라진다."""
    db_session.add(_route("ending_judgment", chain_model="opus", call_model="opus"))
    await db_session.flush()

    await _rejects(
        db_session,
        _route("ending_judgment", chain_model="haiku", call_model="haiku"),
        "ix_prompt_routes_lane_room_model_stage",
    )


async def test_the_same_stage_takes_one_route_per_room_model_and_per_lane(db_session: AsyncSession) -> None:
    """유니크 범위는 (레인, 방 모델, 단계) 셋이다. 깨지는 시나리오: 유니크를 단계만으로 걸어 방 모델별·레인별 배정을 저장할 수
    없다."""
    db_session.add_all(
        [
            _route("stat_judgment", chain_model="gemini", call_model="gemini", room_model="gemini", backend="gemini"),
            _route("stat_judgment", chain_model="haiku", call_model="haiku"),
            _route(
                "memory_fact",
                chain_model="gemini",
                call_model="gemini",
                lane="character",
                room_model="gemini",
                backend="gemini",
            ),
        ]
    )
    await db_session.flush()


# ── 이력 표 ──────────────────────────────────────────────────────────────────
async def test_revision_numbers_are_positive_and_unique(db_session: AsyncSession) -> None:
    """저장 순번은 양수이고 겹치지 않는다. 깨지는 시나리오: 동시 저장 둘이 같은 번호를 계산해 이력 두 행이 같은 번호로 남아
    되돌릴 대상이 모호해진다."""
    admin = await _create_admin(db_session)
    await _rejects(
        db_session,
        PromptRouteRevision(number=0, rows=[], admin_id=admin["id"]),
        "ck_prompt_route_revisions_number_positive",
    )
    db_session.add_all(
        [
            PromptRouteRevision(number=1, rows=[], admin_id=admin["id"]),
            PromptRouteRevision(number=2, rows=[], admin_id=admin["id"]),
        ]
    )
    await db_session.flush()
    await _rejects(
        db_session,
        PromptRouteRevision(number=2, rows=[], admin_id=admin["id"]),
        "ix_prompt_route_revisions_number",
    )


# ── 왕복 ────────────────────────────────────────────────────────────────────
async def _tables(connection: AsyncConnection) -> set[str]:
    rows = await connection.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables WHERE table_name IN"
            " ('prompt_routes', 'prompt_route_revisions')"
        )
    )
    return set(rows.scalars().all())


async def test_downgrade_refuses_once_an_admin_saved_a_route_and_round_trips_on_an_empty_history(
    ddl_engine: AsyncEngine,
) -> None:
    """이력이 한 행이라도 있으면 downgrade 가 아무것도 지우기 전에 멈추고, 이력이 없으면 내렸다 올려도 두 표가 돌아온다. 깨지는
    시나리오: downgrade 가 어드민이 저장한 배정과 그 이력을 조용히 지운다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            session.add(_route("chat_generate", chain_model=None, call_model="opus"))
            await _revision(
                session,
                1,
                [
                    {
                        "lane": "story",
                        "roomModel": "opus",
                        "stage": "chat_generate",
                        "chainModel": None,
                        "callModel": "opus",
                        "backend": "anthropic",
                    }
                ],
            )

            with pytest.raises(RuntimeError, match="이력"):
                async with connection.begin_nested():
                    await _run(connection, _M.downgrade)
            still = await _tables(connection)
            kept = (
                await connection.scalar(sa.text("SELECT count(*) FROM prompt_routes")),
                await connection.scalar(sa.text("SELECT count(*) FROM prompt_route_revisions")),
            )

            await connection.execute(sa.text("DELETE FROM prompt_route_revisions"))
            await _run(connection, _M.downgrade)
            after_down = await _tables(connection)
            await _run(connection, _M.upgrade)
            after_up = await _tables(connection)
        finally:
            await transaction.rollback()

    expected = {"prompt_routes", "prompt_route_revisions"}
    assert still == expected
    assert kept == (1, 1)
    assert after_down == set()
    assert after_up == expected


async def test_saving_an_empty_table_still_counts_as_written(ddl_engine: AsyncEngine) -> None:
    """설정 표가 비어 있어도 빈 스냅샷 이력 한 행이 있으면 downgrade 가 멈춘다. 깨지는 시나리오: 가드가 설정 표 행 수로 판정해,
    어드민이 표를 비워 전부 환경 변수 규칙으로 돌린 저장 기록을 지운다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            await _revision(session, 1)

            with pytest.raises(RuntimeError, match="이력"):
                async with connection.begin_nested():
                    await _run(connection, _M.downgrade)
            still = await _tables(connection)
        finally:
            await transaction.rollback()

    assert still == {"prompt_routes", "prompt_route_revisions"}
