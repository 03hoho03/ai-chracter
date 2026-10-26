"""클로버 단위 전환(1클로버 = 3원 → 1원)을 데이터로 되돌린다 — 수량 칼럼을 3으로 나누고, 잔액이 있는 회원마다 원장에 되돌림 행을,
단위 기록 표에 되돌림 행을 남긴다. 한 트랜잭션이다.

    # 운영 VM — 돌고 있는 api 컨테이너 안에서(기본은 건조 실행). 서빙하는 색이 없으면 `exec` 대신
    # `run --rm --no-deps -T api_<색>` 으로 일회성 컨테이너에서 돌린다.
    cd /opt/ddona/app && sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \\
        exec -T api_$(sudo bash ops/active-color.sh) python scripts/ops/revert_clover_unit.py [--apply]

**기본은 건조 실행이다** — 아래를 전부 실제로 하고 사후 검사까지 본 뒤 롤백한다. `--apply` 일 때만 커밋한다. 화면에는 전제
항목별 위반 수·대상 회원 수·불변식 위반 수만 나간다(행 원문 없음). 위반이 하나라도 있으면 아무것도 쓰지 않고 종료 코드 1 이다.

순서:
1. 전환 마이그레이션과 같은 `lock_timeout`(500ms)과 같은 표 잠금 순서. 회원 표를 잡은 뒤 5초를 넘기면 멈춘다(같은 이유 —
   이 잠금에 막힌 환급이 포기되기 전에 놓는다).
2. 마지막 단위 기록이 전환이 아니면 멈춘다(두 번째 되돌림도 여기서 멈춘다). 경계는 그 기록의 `lock_started_at`(첫 표 잠금 앞
   시각)이다 — 전환 잠금에 막혔다가 전환 뒤에 들어간 쓰기도 그 범위에 든다. 같은 검사를 행을 넣은 트랜잭션 번호(`xmin` 이 전환
   기록 행의 것보다 큼)로도 세어 두 기준의 수가 다르면 멈춘다.
3. 전제(전부 0 이어야 한다):
   - 수량 칼럼마다 3의 배수가 아닌 행 수 — 나눗셈이 정확해야 한다.
   - 경계 뒤의 콘솔 취소 행 — 전환 뒤 새 단위로 회수했다. 부분 취소의 올림 회수량은 3의 배수가 아닐 수 있고, 전액 취소도 규칙을
     단순하게 하려고 막는다.
   - 경계 뒤의 원장 행 가운데 증감이나 잔액이 3의 배수가 아닌 행(전환·되돌림 행 제외) — 정지가 새 새 가격(20·200)으로 깎은 차감.
   - 경계 뒤의 채팅·이미지·요약 환급 원장 행 — 메모리 영수증 환급이라 전환 전 차감을 옛 단위로 돌려준 것이다. 이미지 30 처럼
     3의 배수인 경우가 있어 위 검사가 못 잡는다(30 은 나누어지지만 회원은 60 을 잃었다).
4. 회원별 되돌림 행(증감 −2/3 × 잔액, 잔액 1/3, 멱등키 `unit-conversion-revert:{user_id}`, 두 번째 되돌림부터 `:{회차}`) →
   수량 칼럼 ÷ 3(한 표 한 문장) → 되돌림 기록 → 사후 검사(불변식 넷의 위반 수가 늘지 않았다, 되돌림 행 수 = 잔액 있는 회원 수).

대상 칼럼과 잠금 순서는 전환 마이그레이션(`migrations/versions/725813c4f950_clover_unit_conversion.py`)의 사본이다 — 리비전은 앱
코드를 import 하지 않아 사본이 불가피하고, 두 사본이 같은지는 `tests/test_clover_unit_conversion.py` 가 본다.

되돌린 뒤 떠 있는 새 단위 프로세스는 새 상수로 옛 단위 데이터를 다룬다(기동 가드는 기동 때만 본다). 커밋한 다음 명령은 다른 작업
없이 곧바로 옛 단위 이미지로의 교체이고, 그동안 정지 스위치를 끄지 않는다(`DEPLOY.md` 의 "BE → GCE VM" 절 "클로버 단위 전환"
단락).

이 파일은 같은 폴더의 크론 스크립트와 달리 VM 의 시스템 python3 가 아니라 api 이미지 안에서 돈다(`api` 패키지를 쓴다).
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

from api.db.session import engine

SCRIPT_NAME = "revert_clover_unit"

CONVERTED_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("payments", ("paid_amount", "bonus_amount")),
    ("payment_cancellations", ("clawback_paid", "clawback_bonus")),
    ("users", ("clover_balance",)),
    ("novel_jobs", ("charged_amount", "refunded_amount", "consumed_amount", "unit_price")),
    ("novel_purchases", ("price", "refunded_amount")),
    ("clover_spend_allocations", ("amount", "refunded_amount")),
    ("clover_spend_refunds", ("amount",)),
    ("clover_lots", ("granted_amount", "remaining")),
    ("creator_payout_confirmations", ("gross_units", "refunded_units")),
    ("creator_payout_confirmation_lines", ("net_units",)),
)

LOCK_ORDER: tuple[str, ...] = (
    "payments",
    "payment_cancellations",
    "users",
    "novel_jobs",
    "novel_purchases",
    "clover_spend_allocations",
    "clover_spend_refunds",
    "clover_lots",
    "clover_ledger",
    "creator_payout_confirmations",
    "creator_payout_confirmation_lines",
    "clover_unit_events",
)

# 메모리 영수증으로 돌려주는 환급 kind. 정지 중에는 새 차감이 없으므로 전환 뒤의 이 행은 전부 전환 전 차감의 환급이다.
_RECEIPT_REFUND_KINDS = ("chat_refund", "image_refund", "memory_summary_refund")

# 전환 마이그레이션의 사후 검사와 같은 불변식 넷. 원장의 "마지막 행"은 가장 늦은 시각의 행 중 하나라도 잔액과 같으면 맞다.
_INVARIANTS: dict[str, str] = {
    "balance_ne_lots": """
        SELECT count(*) FROM users u
        LEFT JOIN (SELECT user_id, sum(remaining) AS remaining FROM clover_lots GROUP BY user_id) l ON l.user_id = u.id
         WHERE u.clover_balance <> coalesce(l.remaining, 0)""",
    "last_ledger_ne_balance": """
        SELECT count(*) FROM users u
          JOIN (SELECT user_id, max(created_at) AS last_at FROM clover_ledger GROUP BY user_id) m ON m.user_id = u.id
         WHERE NOT EXISTS (SELECT 1 FROM clover_ledger g
                            WHERE g.user_id = u.id AND g.created_at = m.last_at AND g.balance_after = u.clover_balance)""",
    "purchase_lot_ne_copy": """
        SELECT count(*) FROM clover_lots l JOIN payments p ON p.id = l.payment_id
         WHERE (l.kind = 'purchase_paid' AND l.granted_amount <> p.paid_amount)
            OR (l.kind = 'purchase_bonus' AND l.granted_amount <> p.bonus_amount)""",
    "refunded_gt_amount": "SELECT count(*) FROM clover_spend_allocations WHERE refunded_amount > amount",
}

# 경계 뒤에 생긴 행을 세는 전제. (표, 조건) — 경계는 시각과 트랜잭션 번호 두 기준으로 따로 붙인다.
_AFTER_CONVERSION: dict[str, tuple[str, str]] = {
    "console_cancel_after_conversion": ("payment_cancellations", "source = 'console'"),
    "ledger_not_multiple_of_3_after_conversion": (
        "clover_ledger",
        "kind NOT IN ('unit_conversion', 'unit_conversion_revert') AND (amount % 3 <> 0 OR balance_after % 3 <> 0)",
    ),
    "old_receipt_refund_after_conversion": (
        "clover_ledger",
        "kind IN (" + ", ".join(f"'{kind}'" for kind in _RECEIPT_REFUND_KINDS) + ")",
    ),
}


@dataclass(frozen=True)
class RevertReport:
    """`checks` 는 전제 항목별 위반 수(0 포함), `invariants` 는 되돌림 전 불변식 위반 수(정보)다."""

    checks: dict[str, int]
    target_users: int
    reverted: bool
    invariants: dict[str, int] = field(default_factory=dict)

    @property
    def violations(self) -> dict[str, int]:
        return {name: count for name, count in self.checks.items() if count}


def _count(connection: Connection, sql: str, **params: object) -> int:
    return int(connection.execute(text(sql), params).scalar_one())


def _clock(connection: Connection) -> datetime:
    value = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    assert isinstance(value, datetime)
    return value


def _invariants(connection: Connection) -> dict[str, int]:
    return {name: _count(connection, sql) for name, sql in _INVARIANTS.items()}


def revert_clover_unit(connection: Connection) -> RevertReport:
    """호출자의 트랜잭션 안에서 되돌린다. 전제를 어기면 아무것도 쓰지 않고 `reverted=False` 보고를 돌려준다. 쓰기를 시작한 뒤
    사후 검사가 어긋나면 `RuntimeError` — 호출자가 롤백한다."""
    connection.execute(text("SET LOCAL lock_timeout = '500ms'"))
    lock_started_at = _clock(connection)
    users_locked_at = lock_started_at
    for table in LOCK_ORDER:
        connection.execute(text(f"LOCK TABLE {table} IN EXCLUSIVE MODE"))
        if table == "users":
            users_locked_at = _clock(connection)
    reverted_at = _clock(connection)

    latest = connection.execute(
        text(
            "SELECT action, lock_started_at, xmin::text::bigint AS xid FROM clover_unit_events"
            " ORDER BY occurred_at DESC LIMIT 1"
        )
    ).first()
    if latest is None or latest.action != "convert":
        return RevertReport(checks={"latest_event_not_convert": 1}, target_users=0, reverted=False)

    checks: dict[str, int] = {}
    for table, columns in CONVERTED_COLUMNS:
        for column in columns:
            checks[f"not_multiple_of_3:{table}.{column}"] = _count(
                connection, f"SELECT count(*) FROM {table} WHERE {column} % 3 <> 0"
            )
    for name, (table, condition) in _AFTER_CONVERSION.items():
        by_time = _count(
            connection,
            f"SELECT count(*) FROM {table} WHERE {condition} AND created_at >= :boundary",
            boundary=latest.lock_started_at,
        )
        by_xid = _count(
            connection,
            f"SELECT count(*) FROM {table} WHERE {condition} AND xmin::text::bigint > :xid",
            xid=latest.xid,
        )
        checks[name] = max(by_time, by_xid)
        checks[f"boundary_mismatch:{name}"] = abs(by_time - by_xid)
    invariants = _invariants(connection)
    holders = _count(connection, "SELECT count(*) FROM users WHERE clover_balance > 0")
    if any(checks.values()):
        return RevertReport(checks=checks, target_users=holders, reverted=False, invariants=invariants)

    rounds = _count(connection, "SELECT count(*) FROM clover_unit_events WHERE action = 'revert'") + 1
    suffix = "" if rounds == 1 else f":{rounds}"
    # 나누기 전 잔액 기준이라 원장 행을 먼저 쓴다 — 증감 −2b, 잔액 b(b = 지금 잔액 ÷ 3).
    written = connection.execute(
        text(
            "INSERT INTO clover_ledger (id, user_id, amount, balance_after, kind, idempotency_key, created_at)"
            " SELECT gen_random_uuid(), id, -(clover_balance / 3 * 2), clover_balance / 3, 'unit_conversion_revert',"
            " 'unit-conversion-revert:' || id::text || :suffix, :reverted_at FROM users WHERE clover_balance > 0"
        ),
        {"suffix": suffix, "reverted_at": reverted_at},
    ).rowcount
    for table, columns in CONVERTED_COLUMNS:
        assignments = ", ".join(f"{column} = {column} / 3" for column in columns)
        connection.execute(text(f"UPDATE {table} SET {assignments}"))
    connection.execute(
        text(
            "INSERT INTO clover_unit_events (action, lock_started_at, occurred_at, money_rows, written_by)"
            " VALUES ('revert', :lock_started_at, :reverted_at,"
            " (SELECT count(*) FROM users WHERE clover_balance > 0) + (SELECT count(*) FROM payments), :written_by)"
        ),
        {"lock_started_at": lock_started_at, "reverted_at": reverted_at, "written_by": SCRIPT_NAME},
    )

    after = _invariants(connection)
    worse = {name: (invariants[name], after[name]) for name in _INVARIANTS if after[name] > invariants[name]}
    if worse:
        raise RuntimeError(f"되돌림 뒤 불변식 위반이 늘었다(전, 후): {worse}")
    if written != holders:
        raise RuntimeError(f"되돌림 원장 행 {written}개가 잔액 있는 회원 수 {holders}와 다르다")
    if connection.execute(
        text("SELECT clock_timestamp() - :at > interval '5 seconds'"), {"at": users_locked_at}
    ).scalar_one():
        raise RuntimeError("회원 표를 잡은 뒤 5초를 넘겼다 — 막고 있던 트랜잭션을 확인한 뒤 다시 돌린다.")
    connection.execute(text("SET LOCAL lock_timeout = DEFAULT"))
    return RevertReport(checks=checks, target_users=holders, reverted=True, invariants=invariants)


def finish(report: RevertReport, *, apply: bool) -> Literal["commit", "rollback"]:
    """`--apply` 이고 되돌림을 끝까지 했을 때만 커밋한다. 건조 실행과 전제 위반은 늘 롤백이다."""
    return "commit" if apply and report.reverted else "rollback"


def exit_code(report: RevertReport) -> int:
    return 0 if report.reverted else 1


def render(report: RevertReport) -> str:
    """화면에 내는 요약 — 항목 이름과 수뿐이다."""
    lines = [f"{name}={count}" for name, count in report.checks.items()]
    lines += [f"invariant:{name}={count}" for name, count in report.invariants.items()]
    lines += [f"target_users={report.target_users}", f"reverted={'true' if report.reverted else 'false'}"]
    return "\n".join(lines)


async def run(*, apply: bool) -> RevertReport:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            report = await connection.run_sync(revert_clover_unit)
        except BaseException:
            await transaction.rollback()
            raise
        if finish(report, apply=apply) == "commit":
            await transaction.commit()
        else:
            await transaction.rollback()
    await engine.dispose()
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="되돌림을 커밋한다(없으면 끝까지 해 본 뒤 롤백)")
    args = parser.parse_args(argv)
    report = asyncio.run(run(apply=args.apply))
    print(render(report))
    print("committed" if finish(report, apply=args.apply) == "commit" else "rolled back", file=sys.stderr)
    raise SystemExit(exit_code(report))


if __name__ == "__main__":
    main()
