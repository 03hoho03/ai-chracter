"""클로버 단위 전환 기록(`clover_unit_events`)과 내역 응답의 단위 표시.

이 파일이 검증하는 성질:

1. 단위 전환 범주 — 전환·되돌림 원장 행은 사용·획득·소멸 어느 탭을 불러도 경계 줄로 함께 실리고, `category=conversion` 은
   그 행만 돌려준다. 다른 범주의 행은 섞이지 않는다.
2. `legacyUnit` — 행이 적힌 시각에 단위가 전환 전이었는가. 전환한 적이 없으면 모든 행이 지금 단위라 거짓이고, 전환 뒤에는
   전환 전에 적힌 행만 참이다. 되돌린 뒤의 행은 다시 옛 단위다. 전환·되돌림 행 자신은 늘 거짓이다(자기 설명을 갖는다).
   어드민 원장도 같은 함수로 싣는다.
3. 이벤트 표의 CHECK 와 이 표를 만든 리비전의 `downgrade()` 두 갈래(행 있음 → 멈춤, 없음 → 지움).

이벤트는 롤백되는 연결(`db_session`·`ddl_engine` 트랜잭션)에서만 쓴다 — 커밋하면 같은 세션의 다른 테스트(기동 가드 포함)가 그
상태를 보고 세션 끝 `downgrade base` 도 멈춘다. 각 테스트는 표가 비어 있다고 가정하지 않고 먼저 비운 뒤 필요한 이벤트를 넣는다
(전환 마이그레이션이 들어온 뒤에는 세션 DB 에 이미 전환 행이 있다).
"""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverUnitEvent
from factories import _create_admin, _login_as, _login_as_admin, _make_user

_T = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)


async def _logged_in(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def _events(db: AsyncSession, *events: tuple[str, datetime]) -> None:
    """표를 비우고 주어진 이벤트만 남긴다. 롤백되는 연결이라 테스트가 끝나면 원래대로 돌아간다."""
    await db.execute(delete(CloverUnitEvent))
    db.add_all(
        CloverUnitEvent(
            action=action, lock_started_at=at - timedelta(seconds=1), occurred_at=at, money_rows=0, written_by="test"
        )
        for action, at in events
    )
    await db.commit()


def _row(user_id: uuid.UUID, kind: str, created_at: datetime, amount: int = 10) -> CloverLedger:
    return CloverLedger(user_id=user_id, amount=amount, balance_after=100, kind=kind, created_at=created_at)


async def _ledger(db_client: httpx.AsyncClient, category: str) -> list[tuple[str, bool]]:
    resp = await db_client.get("/me/clover/ledger", params={"category": category})
    assert resp.status_code == 200
    return [(item["kind"], item["legacyUnit"]) for item in resp.json()["items"]]


# ── 단위 전환 범주 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("category", "own_kind"),
    [
        pytest.param("use", "chat_spend", id="use"),
        pytest.param("earn", "mission_grant", id="earn"),
        pytest.param("expire", "expire_burn", id="expire"),
    ],
)
async def test_conversion_rows_ride_along_in_every_tab(
    db_client: httpx.AsyncClient, db_session: AsyncSession, category: str, own_kind: str
) -> None:
    """깨지는 시나리오: 전환 행이 어느 탭에도 안 나와, 잔액이 갑자기 세 배가 된 이유를 사용자 화면이 설명하지 못한다. 다른 범주의
    행은 그 탭에 섞이지 않는다."""
    user = await _logged_in(db_client, db_session)
    await _events(db_session)
    db_session.add_all(
        [
            _row(user.id, "unit_conversion", _T + timedelta(hours=3), amount=200),
            _row(user.id, "unit_conversion_revert", _T + timedelta(hours=2), amount=-200),
            _row(user.id, own_kind, _T + timedelta(hours=1)),
            *(
                _row(user.id, other, _T)
                for other in ("chat_spend", "mission_grant", "expire_burn")
                if other != own_kind
            ),
        ]
    )
    await db_session.commit()

    kinds = [kind for kind, _ in await _ledger(db_client, category)]

    assert kinds == ["unit_conversion", "unit_conversion_revert", own_kind]


async def test_conversion_category_returns_only_conversion_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in(db_client, db_session)
    await _events(db_session)
    db_session.add_all([_row(user.id, "unit_conversion", _T, amount=200), _row(user.id, "chat_spend", _T)])
    await db_session.commit()

    resp = await db_client.get("/me/clover/ledger", params={"category": "conversion"})

    assert [(item["kind"], item["category"]) for item in resp.json()["items"]] == [("unit_conversion", "conversion")]


# ── legacyUnit ─────────────────────────────────────────────────────────────────
async def test_without_a_conversion_no_row_is_legacy(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """전환한 적이 없으면 모든 행이 하나뿐인 지금 단위다. 깨지는 시나리오: "그 시각의 상태가 전환됨이 아니다"만으로 판정해, 전환
    전 배포에서 모든 내역에 옛 단위 표시가 붙는다."""
    user = await _logged_in(db_client, db_session)
    await _events(db_session)
    db_session.add_all([_row(user.id, "chat_spend", _T), _row(user.id, "chat_spend", _T - timedelta(days=30))])
    await db_session.commit()

    assert await _ledger(db_client, "use") == [("chat_spend", False), ("chat_spend", False)]


async def test_rows_written_before_the_conversion_are_legacy(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """전환 시각(`occurred_at`) 이전에 적힌 행만 옛 단위다. 같은 시각에 적힌 전환 행 자신은 옛 단위가 아니다. 경계는 포함 — 전환
    행은 `occurred_at` 을 `created_at` 으로 받으므로 같은 시각의 행은 전환 뒤다."""
    user = await _logged_in(db_client, db_session)
    await _events(db_session, ("convert", _T))
    db_session.add_all(
        [
            _row(user.id, "chat_spend", _T + timedelta(minutes=1)),
            _row(user.id, "unit_conversion", _T, amount=200),
            _row(user.id, "image_spend", _T),
            _row(user.id, "chat_spend", _T - timedelta(microseconds=1)),
        ]
    )
    await db_session.commit()

    assert await _ledger(db_client, "use") == [
        ("chat_spend", False),
        ("unit_conversion", False),
        ("image_spend", False),
        ("chat_spend", True),
    ]


async def test_rows_after_a_revert_are_legacy_again(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """전환 → 되돌림이면 구간마다 단위가 다르다: 전환 전과 되돌림 뒤는 옛 단위, 그 사이는 새 단위. 깨지는 시나리오: 가장 최근
    이벤트 하나로 모든 행을 판정해 전환 구간의 행까지 옛 단위로 보인다."""
    user = await _logged_in(db_client, db_session)
    await _events(db_session, ("convert", _T), ("revert", _T + timedelta(days=1)))
    db_session.add_all(
        [
            _row(user.id, "chat_spend", _T + timedelta(days=2)),
            _row(user.id, "unit_conversion_revert", _T + timedelta(days=1), amount=-200),
            _row(user.id, "chat_spend", _T + timedelta(hours=1)),
            _row(user.id, "chat_spend", _T - timedelta(hours=1)),
        ]
    )
    await db_session.commit()

    assert await _ledger(db_client, "use") == [
        ("chat_spend", True),
        ("unit_conversion_revert", False),
        ("chat_spend", False),
        ("chat_spend", True),
    ]


async def test_admin_ledger_marks_legacy_rows_the_same_way(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """환불 조사 때 단위가 섞인 숫자를 같은 눈금으로 읽게 어드민 원장도 같은 판정을 싣는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _events(db_session, ("convert", _T))
    db_session.add_all([_row(user.id, "chat_spend", _T + timedelta(hours=1)), _row(user.id, "chat_spend", _T - timedelta(hours=1))])
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)

    resp = await db_client.get(f"/admin/users/{user.id}/clover-ledger?page=1")

    assert [item["legacyUnit"] for item in resp.json()["items"]] == [False, True]


# ── 표 제약 ────────────────────────────────────────────────────────────────────
async def test_unit_event_action_check_accepts_the_two_actions(db_session: AsyncSession) -> None:
    for action in ("convert", "revert"):
        async with db_session.begin_nested():
            db_session.add(
                CloverUnitEvent(action=action, lock_started_at=_T, occurred_at=_T, money_rows=0, written_by="test")
            )


async def test_unit_event_action_check_rejects_another_word(db_session: AsyncSession) -> None:
    """번갈아 쓰기는 쓰는 쪽이 지키지만 값 자체는 둘뿐이다 — 오타(`converted`)가 들어가면 가드가 "전환됨"으로 읽지 못한다."""
    with pytest.raises(IntegrityError, match="ck_clover_unit_events_action"):
        async with db_session.begin_nested():
            db_session.add(
                CloverUnitEvent(action="converted", lock_started_at=_T, occurred_at=_T, money_rows=0, written_by="test")
            )


# ── 이 표를 만든 리비전의 downgrade ─────────────────────────────────────────────
def _load_unit_events_revision() -> ModuleType:
    (path,) = (Path(__file__).resolve().parents[1] / "migrations" / "versions").glob("65205c06e037_*.py")
    spec = importlib.util.spec_from_file_location("_migration_65205c06e037", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_UNIT_EVENTS_REVISION = _load_unit_events_revision()


def _downgrade(sync_connection: Connection) -> None:
    with Operations.context(MigrationContext.configure(sync_connection)):
        _UNIT_EVENTS_REVISION.downgrade()


async def test_unit_events_block_the_downgrade_before_any_change(ddl_engine: AsyncEngine) -> None:
    """단위를 바꾼 기록이 있으면 표를 지우지 않고 멈춘다 — 지우면 가드가 "전환한 적 없음"으로 읽어 옛 단위 코드가 뜬다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text(
                    "INSERT INTO clover_unit_events (action, lock_started_at, occurred_at, money_rows, written_by)"
                    " VALUES ('convert', now(), now(), 0, 'test')"
                )
            )
            with pytest.raises(RuntimeError, match="단위를 바꾼 적이 있는 DB"):
                await connection.run_sync(_downgrade)
            still_there = await connection.scalar(text("SELECT count(*) FROM clover_unit_events"))
        finally:
            await transaction.rollback()

    assert still_there is not None and still_there >= 1


async def test_empty_unit_events_table_is_dropped_by_the_downgrade(ddl_engine: AsyncEngine) -> None:
    """빈 표는 지운다 — 테스트 세션 정리(`downgrade base`)가 이 갈래를 탄다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text("DELETE FROM clover_unit_events"))
            await connection.run_sync(_downgrade)
            remaining = await connection.scalar(text("SELECT to_regclass('clover_unit_events')"))
        finally:
            await transaction.rollback()

    assert remaining is None
