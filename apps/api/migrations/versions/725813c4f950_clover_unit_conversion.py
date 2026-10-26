"""clover unit conversion

Revision ID: 725813c4f950
Revises: 65205c06e037
Create Date: 2026-10-26 18:10:00.000000

클로버 단위를 1클로버 = 3원에서 1원으로 바꾼다. 데이터만 바꾸고 스키마는 그대로다.

1. 클로버 수량 칼럼 전부(`CONVERTED_COLUMNS`)를 세 배로 한다 — 상태·삭제 여부와 무관하게 모든 행(대기·실패 결제의 사본, 진행 중
   환불 시도의 회수량, 확정된 정산 줄까지). 한 표의 칼럼은 한 UPDATE 문으로 함께 바꾼다 — 같은 행의 CHECK 가 칼럼끼리 비교해서
   따로 바꾸면 중간 상태에서 CHECK 가 멈춘다. 빈 칸은 빈 채로 남는다. 원화 칼럼은 그대로라 환불 견적과 정산 원화는 단가와
   수량이 함께 세 배가 되어 정수 내림까지 같다. 원장(`clover_ledger`)과 턴 영수증(`chat_turns.clover_amount`)의 과거 금액은
   바꾸지 않는다 — append-only 기록이고 돈을 움직이는 코드가 과거 행의 금액을 읽지 않는다. 화 공개 가격
   (`novel_chapter_publications.price`)은 0(무료)인지만 읽혀 바꾸지 않는다.
2. 잔액이 있는 회원마다 원장에 전환 행 하나(`unit_conversion`, 증감 +2b, 잔액 3b, 멱등키 `unit-conversion:{user_id}`)를 남겨
   과거 행의 잔액 사슬을 새 단위로 잇는다. 잔액 0 회원에게는 쓰지 않는다(0 원장 행을 남기지 않는 관례). 행의 `created_at` 은
   모든 잠금을 잡은 뒤 시각이라 잠금 전에 커밋된 행보다 늘 뒤에 놓인다.
3. 단위 기록 표(`clover_unit_events`)에 전환 행을 쓴다 — 돈 데이터가 없는 새 DB 에서도 쓴다. 새 단위 코드의 기동 가드는 이
   기록이 있어야 뜬다.

**잠금.** 첫 문장 `SET LOCAL lock_timeout = '500ms'`, 첫 표 잠금 앞 시각(`lock_started_at`)을 잰 뒤 `LOCK_ORDER` 순서로 표마다
`EXCLUSIVE` 잠금 — 일반 SELECT 는 통과하고 쓰기와 `FOR UPDATE` 는 이 트랜잭션이 끝날 때까지 줄을 선다. 돈을 움직이는 모든
경로가 결제 행, 그다음 회원 행을 다른 수량 표보다 먼저 잠그므로 같은 순서로 잡으면 교착이 없다. 회원 표를 잡은 뒤 커밋까지
5초를 넘기면 스스로 멈춘다 — 이 잠금에 막힌 채팅·이미지 환급은 10초 안에 끝나지 못하면 포기되고 차감이 남는다
(`core/clover.py` 의 `refund_spend_in_new_transaction`). 정상이면 정지 스위치로 쓰기가 0 이라 실제 대기도 0 이다. 마지막
문장은 `SET LOCAL lock_timeout = DEFAULT` 다 — 같은 트랜잭션에서 뒤에 도는 리비전이 500ms 를 물려받지 않게 한다.

**시작 전 거절**(하나라도 맞으면 아무것도 바꾸기 전에 `RuntimeError`, 트랜잭션 전체 롤백):
- 단위 기록이 이미 있다. 첫 전환은 빈 기록 표에서만 한다 — 같은 리비전을 두 번 돌려 아홉 배가 되는 길을 여기서 막는다.
- 진행 중인 소설 작업(`queued`·`running`)이 있다. 연쇄 실행은 실행 중에 쓴 몫을 누적해, 전환과 겹치면 옛 값 위에 새 값을 더한다.
- 돈 데이터(잔액이 있는 회원 또는 결제 행)가 있는데 정지 스위치(`CLOVER_LEDGER_PAUSED`)가 꺼져 있다. 평상시 배포가 실수로 이
  리비전을 돌리면 겹침 동안 옛 코드가 세 배 잔액을 옛 가격으로 깎는다 — 그 배포를 멈추고 옛 색이 계속 서빙하게 한다. 값은
  `migrations/env.py` 가 alembic 설정(`config.attributes`)으로 넘긴 것을 읽고, 없으면 꺼짐으로 본다. 운영 마이그레이션은 새
  이미지와 운영 `.env` 로 도므로 그 `.env` 의 값이다. 시드가 있는 dev·워크트리 DB 도 이 리비전을 돌릴 때는 `.env` 에 스위치를
  켠다.

**사후 검사**(어기면 `RuntimeError`): 불변식 넷(잔액 = 로트 합, 회원별 마지막 원장 행의 잔액 = 잔액, 구매 로트 지급량 = 결제
사본, 배분의 환급 ≤ 차감)의 위반 수가 전환 전보다 늘지 않았다. 잔액이 있는 회원마다 잔액과 같은 전환 행이 있다.

**배포 겹침** — 옛 코드가 새 단위 수량을 옛 단위로 읽는 위험한 데이터 변경이라 겹침 없는 교체로만 배포하고, 그 전에 정지
스위치를 켜고 소설화 워커를 비운다. 절차와 되돌리는 법은 `DEPLOY.md` 의 "BE → GCE VM" 절 "클로버 단위 전환" 단락이다.

**downgrade** — 수량은 절대 되돌리지 않는다. 전환할 때 돈 데이터가 있었으면(이 리비전이 쓴 기록의 `money_rows` 가 0 보다
크면) `RuntimeError` 로 멈춘다 — 되돌림은 운영 되돌림 스크립트(`scripts/ops/revert_clover_unit.py`)가 전제를 확인한 뒤에만 한다.
돈 데이터가 없던 전환이면 단위 기록을 모두 지우고 통과한다 — 테스트 세션 정리(`downgrade base`)가 이 길을 타고, 테스트가
되돌림 스크립트로 남긴 되돌림 기록까지 지워야 기록 표를 만든 앞 리비전의 downgrade 가 멈추지 않는다. 판정은 지금 데이터가 아니라
전환할 때 센 값이다 — 지금 데이터로 정하면 세션 동안 커밋된 행 때문에 세션 정리가 멈춘다. 한계: 시드 없이 만든 dev DB 에서
전환한 뒤 데이터를 쌓았다면 이 downgrade 는 멈추지 않고 기록만 지운다 — 그 DB 의 수량은 이미 1원 단위이고 되돌리지 않는다.

**되돌린 뒤 다시 전환할 때.** 이 리비전은 이미 적용 기록이 남아 다시 돌지 않는다. 그때는 새 리비전을 더해, 마지막 기록이
되돌림이면 이 파일과 같은 일(사본 — 리비전은 자기 완결)을 멱등키에 회차를 붙여(`unit-conversion:{user_id}:2`) 하고, 마지막
기록이 전환이면 아무것도 하지 않고, 기록이 없으면 멈춘다. 그 리비전의 downgrade 도 같은 꼴(자기 기록이 돈 데이터 전환이면
멈춤, 아니면 자기 행만 지움)이다. alembic 기록을 이 리비전 앞으로 되돌려 찍는 길은 쓰지 않는다 — 그러면 고장 난 같은 태그를
실수로 다시 배포했을 때 전환이 다시 돈다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 대상 칼럼과 잠금 순서는 되돌림 스크립트에도 사본이 있고, 두 사본이
같은지는 `tests/test_clover_unit_conversion.py` 가 본다.
"""
from collections.abc import Sequence
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = '725813c4f950'
down_revision: str | Sequence[str] | None = '65205c06e037'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 세 배 하는 칼럼. 표 순서는 아래 잠금 순서와 같다.
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

# 결제 행을 쓰는 경로는 모두 결제 행을 먼저 잠그고, 클로버를 움직이는 경로는 모두 회원 행을 다른 수량 표보다 먼저 잠근다. 그래서
# 결제 → 결제 취소 → 회원 순으로 잡으면, 이 트랜잭션이 기다리는 표를 쥔 쪽은 다음 표를 기다리지 않고 끝까지 간다. 회원 뒤 표들
# 사이의 순서는 교착과 무관하다(그 표를 쥐는 쓰기는 회원 표에서 먼저 막힌다).
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

# 불변식 위반 수. 원장의 "마지막 행"은 행을 넣은 트랜잭션 번호(`xmin`)가 가장 큰 행 묶음이다 — `created_at` 은 트랜잭션 시작
# 시각이라 전환 잠금에 막혔다가 전환 뒤에 쓴 행이 전환 행보다 앞에 놓여 거짓 위반이 된다. 원장은 append-only 라 행의 `xmin` 이 곧
# 그 행을 넣은 트랜잭션이고, 한 트랜잭션이 여러 행(구매의 유료·보너스, 콘솔 회수)을 쓰므로 그 묶음 중 하나라도 잔액과 같으면 맞다로
# 센다. 트랜잭션 번호는 운영 진단값이라 이 검사에만 쓰고 앱 코드에는 쓰지 않는다.
INVARIANTS: dict[str, str] = {
    "balance_ne_lots": """
        SELECT count(*) FROM users u
        LEFT JOIN (SELECT user_id, sum(remaining) AS remaining FROM clover_lots GROUP BY user_id) l ON l.user_id = u.id
         WHERE u.clover_balance <> coalesce(l.remaining, 0)""",
    "last_ledger_ne_balance": """
        SELECT count(*) FROM users u
          JOIN (SELECT user_id, max(xmin::text::bigint) AS last_xid FROM clover_ledger GROUP BY user_id) m ON m.user_id = u.id
         WHERE NOT EXISTS (SELECT 1 FROM clover_ledger g
                            WHERE g.user_id = u.id AND g.xmin::text::bigint = m.last_xid
                              AND g.balance_after = u.clover_balance)""",
    "purchase_lot_ne_copy": """
        SELECT count(*) FROM clover_lots l JOIN payments p ON p.id = l.payment_id
         WHERE (l.kind = 'purchase_paid' AND l.granted_amount <> p.paid_amount)
            OR (l.kind = 'purchase_bonus' AND l.granted_amount <> p.bonus_amount)""",
    "refunded_gt_amount": "SELECT count(*) FROM clover_spend_allocations WHERE refunded_amount > amount",
}

_MONEY_ROWS_SQL = "SELECT (SELECT count(*) FROM users WHERE clover_balance > 0) + (SELECT count(*) FROM payments)"


def _scalar(connection: Connection, sql: str, **params: object) -> object:
    return connection.execute(sa.text(sql), params).scalar_one()


def _clock(connection: Connection) -> datetime:
    value = _scalar(connection, "SELECT clock_timestamp()")
    assert isinstance(value, datetime)
    return value


def invariant_counts(connection: Connection) -> dict[str, int]:
    return {name: int(str(_scalar(connection, sql))) for name, sql in INVARIANTS.items()}


def refusal_reason(*, has_events: bool, active_novel_jobs: int, money_rows: int, ledger_paused: bool) -> str | None:
    """전환을 시작하지 않을 이유. 없으면 `None`."""
    if has_events:
        return "클로버 단위 기록이 이미 있다 — 첫 전환은 빈 기록 표에서만 한다(되돌린 뒤 다시 전환은 새 리비전으로)."
    if active_novel_jobs:
        return (
            f"진행 중인 소설 작업이 {active_novel_jobs}개 있다 — 연쇄 실행이 쓴 몫을 누적하는 중에 전환하면 금액이 어긋난다."
            " 소설화 워커를 비운 뒤 다시 돌린다."
        )
    if money_rows and not ledger_paused:
        return (
            f"돈 데이터가 {money_rows}행 있는데 클로버 정지 스위치(CLOVER_LEDGER_PAUSED)가 꺼져 있다 — 겹친 옛 코드가 세 배"
            " 잔액을 옛 가격으로 깎지 않게, 스위치를 켠 교체 뒤 겹침 없는 배포로만 전환한다."
        )
    return None


def convert_clover_unit(connection: Connection, *, ledger_paused: bool) -> None:
    """한 트랜잭션(호출자의 것) 안에서 전환한다. 어기면 `RuntimeError` — 호출자의 트랜잭션이 통째로 롤백된다."""
    connection.execute(sa.text("SET LOCAL lock_timeout = '500ms'"))
    lock_started_at = _clock(connection)
    users_locked_at = lock_started_at
    for table in LOCK_ORDER:
        connection.execute(sa.text(f"LOCK TABLE {table} IN EXCLUSIVE MODE"))
        if table == "users":
            users_locked_at = _clock(connection)
    occurred_at = _clock(connection)

    money_rows = int(str(_scalar(connection, _MONEY_ROWS_SQL)))
    reason = refusal_reason(
        has_events=bool(_scalar(connection, "SELECT EXISTS (SELECT 1 FROM clover_unit_events)")),
        active_novel_jobs=int(
            str(_scalar(connection, "SELECT count(*) FROM novel_jobs WHERE status IN ('queued', 'running')"))
        ),
        money_rows=money_rows,
        ledger_paused=ledger_paused,
    )
    if reason is not None:
        raise RuntimeError(reason)
    before = invariant_counts(connection)

    for table, columns in CONVERTED_COLUMNS:
        assignments = ", ".join(f"{column} = {column} * 3" for column in columns)
        connection.execute(sa.text(f"UPDATE {table} SET {assignments}"))
    # `clover_balance` 는 위에서 이미 세 배다 — 증감 +2b, 잔액 3b. 원장 id 는 DB 기본값이 없어 여기서 만든다.
    connection.execute(
        sa.text(
            "INSERT INTO clover_ledger (id, user_id, amount, balance_after, kind, idempotency_key, created_at)"
            " SELECT gen_random_uuid(), id, clover_balance / 3 * 2, clover_balance, 'unit_conversion',"
            " 'unit-conversion:' || id::text, :occurred_at FROM users WHERE clover_balance > 0"
        ),
        {"occurred_at": occurred_at},
    )
    connection.execute(
        sa.text(
            "INSERT INTO clover_unit_events (action, lock_started_at, occurred_at, money_rows, written_by)"
            " VALUES ('convert', :lock_started_at, :occurred_at, :money_rows, :written_by)"
        ),
        {
            "lock_started_at": lock_started_at,
            "occurred_at": occurred_at,
            "money_rows": money_rows,
            "written_by": revision,
        },
    )

    after = invariant_counts(connection)
    worse = {name: (before[name], after[name]) for name in INVARIANTS if after[name] > before[name]}
    if worse:
        raise RuntimeError(f"전환 뒤 불변식 위반이 늘었다(전, 후): {worse}")
    unmatched = int(
        str(
            _scalar(
                connection,
                "SELECT count(*) FROM users u WHERE u.clover_balance > 0 AND NOT EXISTS ("
                " SELECT 1 FROM clover_ledger g WHERE g.idempotency_key = 'unit-conversion:' || u.id::text"
                " AND g.kind = 'unit_conversion' AND g.balance_after = u.clover_balance)",
            )
        )
    )
    if unmatched:
        raise RuntimeError(f"잔액이 있는데 잔액과 같은 전환 원장 행이 없는 회원이 {unmatched}명이다")
    if _scalar(connection, "SELECT clock_timestamp() - :at > interval '5 seconds'", at=users_locked_at):
        raise RuntimeError(
            "회원 표를 잡은 뒤 5초를 넘겼다 — 이 잠금에 막힌 환급이 포기되기 전에 놓는다. 막고 있던 트랜잭션을 확인한 뒤 다시 돌린다."
        )
    connection.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def _ledger_paused() -> bool:
    config = op.get_context().config
    return config is not None and config.attributes.get("clover_ledger_paused") is True


def upgrade() -> None:
    """Upgrade schema."""
    convert_clover_unit(op.get_bind(), ledger_paused=_ledger_paused())


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    money_rows = bind.execute(
        sa.text("SELECT max(money_rows) FROM clover_unit_events WHERE written_by = :revision"), {"revision": revision}
    ).scalar()
    if money_rows:
        raise RuntimeError(
            f"클로버 단위 전환은 수량이 있는 DB 에서 마이그레이션으로 되돌리지 않는다(전환 때 돈 데이터 {money_rows}행). 되돌림은"
            " 운영 되돌림 스크립트가 모든 수량이 3의 배수이고 전환 뒤 콘솔 취소가 없음을 확인한 뒤에만 한다 — 정지 해제 뒤에는"
            " 3의 배수가 아닌 차감이 쌓여 나누기가 정확하지 않다."
        )
    bind.execute(sa.text("DELETE FROM clover_unit_events"))
