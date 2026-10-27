"""기동 가드 — 이 코드의 클로버 단위와 DB 의 마지막 단위 전환 기록이 다르면 요청을 받기 전에 기동을 멈춘다.

이 파일이 검증하는 성질:

1. 판정 표: 전환 전 단위(3원) 코드는 기록 없음·되돌림이면 통과하고 전환이면 멈춘다. 새 단위(1원) 코드는 그 반대로 전환일 때만
   통과한다. 깨지는 시나리오: 옛 단위 코드가 전환된 DB 위에서 떠 1클로버 = 3원으로 환불을 계산한다(환불 세 배).
2. 실제 표를 읽는다 — 마지막 기록은 `occurred_at` 이 가장 늦은 행이고, 표가 없는 DB(이 표보다 옛 백업으로 복원한 DB)는 기록
   없음이다.
3. `main.lifespan` 이 가드를 맨 먼저 부르고, 가드가 멈추면 정지 표지 재구축·소설화 정리를 시작하지 않는다.

이벤트는 롤백되는 연결에서만 쓴다(`test_clover_unit_ledger.py` 머리말과 같은 이유).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.clover import unit
from api.core import clover
from api.db.models.clover import CloverUnitEvent

_T = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("unit_krw", "action", "refused"),
    [
        pytest.param(3, None, False, id="old-unit-no-record"),
        pytest.param(3, "convert", True, id="old-unit-converted"),
        pytest.param(3, "revert", False, id="old-unit-reverted"),
        pytest.param(1, None, True, id="new-unit-no-record"),
        pytest.param(1, "convert", False, id="new-unit-converted"),
        pytest.param(1, "revert", True, id="new-unit-reverted"),
    ],
)
def test_unit_check_table(unit_krw: int, action: unit.UnitAction | None, refused: bool) -> None:
    if refused:
        with pytest.raises(RuntimeError, match="기동을 멈춘다"):
            unit.check_unit_matches(action, unit_krw=unit_krw)
    else:
        unit.check_unit_matches(action, unit_krw=unit_krw)


def test_this_code_is_the_new_unit() -> None:
    """이 코드는 전환 뒤 단위(1클로버 = 1원)다 — 전환 기록이 있는 DB 에서만 뜬다. 교체 스크립트는 이 이름이 있는 이미지를
    "가드 있음"으로 본다."""
    assert clover.CLOVER_UNIT_KRW == 1


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db.bind, expire_on_commit=False)


async def _events(db: AsyncSession, *events: tuple[str, datetime]) -> None:
    await db.execute(delete(CloverUnitEvent))
    db.add_all(
        CloverUnitEvent(action=action, lock_started_at=at, occurred_at=at, money_rows=0, written_by="test")
        for action, at in events
    )
    await db.commit()


@pytest.mark.parametrize(
    ("events", "refused"),
    [
        pytest.param((), True, id="no-record"),
        pytest.param((("convert", _T),), False, id="converted"),
        pytest.param((("convert", _T), ("revert", _T + timedelta(days=1))), True, id="reverted"),
        # 행을 넣은 순서가 아니라 `occurred_at` 으로 마지막을 고른다.
        pytest.param((("revert", _T + timedelta(days=1)), ("convert", _T)), True, id="reverted-inserted-first"),
        pytest.param(
            (("convert", _T), ("revert", _T + timedelta(days=1)), ("convert", _T + timedelta(days=2))),
            False,
            id="converted-again",
        ),
    ],
)
async def test_guard_reads_the_latest_record_from_the_table(
    db_session: AsyncSession, events: tuple[tuple[str, datetime], ...], refused: bool
) -> None:
    await _events(db_session, *events)

    if refused:
        with pytest.raises(RuntimeError, match="기동을 멈춘다"):
            await unit.assert_clover_unit_matches(_factory(db_session))
    else:
        await unit.assert_clover_unit_matches(_factory(db_session))


async def test_a_database_without_the_table_has_no_record(ddl_engine: AsyncEngine) -> None:
    """표가 생기기 전 백업으로 복원한 DB 는 기록 없음이다 — 전환한 적이 없으므로 옛 단위 코드만 그 위에서 뜬다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text("DROP TABLE clover_unit_events"))
            action = await unit.latest_unit_action(AsyncSession(bind=connection))
        finally:
            await transaction.rollback()

    assert action is None


async def test_lifespan_runs_the_guard_before_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    """가드가 멈추면 기동이 실패하고 그 뒤의 기동 작업은 시작하지 않는다 — 요청을 받기 전에 멈춰야 평상시 교체에서 새 색만
    실패하고 옛 색이 계속 서빙한다."""
    from api import main

    started: list[str] = []

    async def refuse(_factory: object) -> None:
        started.append("guard")
        raise RuntimeError("기동을 멈춘다")

    async def record(name: str) -> None:
        started.append(name)

    async def markers(_factory: object) -> None:
        await record("markers")

    async def cleanup(_factory: object) -> None:
        await record("cleanup")

    monkeypatch.setattr(main, "assert_clover_unit_matches", refuse)
    monkeypatch.setattr(main, "rebuild_suspended_user_markers", markers)
    monkeypatch.setattr(main, "expire_stale_jobs_after_startup", cleanup)

    with pytest.raises(RuntimeError, match="기동을 멈춘다"):
        async with main.lifespan(main.app):
            pass

    assert started == ["guard"]
