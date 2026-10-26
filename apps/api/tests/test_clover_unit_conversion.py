"""클로버 단위 전환(1클로버 = 3원 → 1원) 마이그레이션과 그 되돌림 스크립트(`ops/revert_clover_unit.py`).

전환은 클로버 수량 칼럼을 모두 세 배로 하고, 잔액이 있는 회원마다 원장에 전환 행 하나를, 단위 기록 표에 전환 행 하나를
남긴다. 이 파일이 고정하는 성질:

1. 돈의 원화 값이 그대로다 — 결제마다 환불 견적(원)이 전환 전후 같고(7일 안·뒤·회사 귀책 × 보너스 사용·미사용 × 부분 취소
   이력), 크리에이터 정산의 적립과 확정 뒤 취소 조정(원)도 같다. 깨지는 시나리오: 결제 사본·로트·배분 중 하나만 세 배가 되어
   환불이 세 배나 3분의 1이 된다.
2. 불변식이 그대로 선다 — 잔액 = 로트 합, 마지막 원장 행의 잔액 = 잔액(한 트랜잭션에 여러 행), 구매 로트 지급량 = 결제 사본,
   배분의 환급 ≤ 차감. 소설 작업 행은 CHECK 를 모두 지키며 칸마다 정확히 세 배이고 빈 칸은 비어 있다.
3. 전환 뒤 끝나는 옛 일 — 대기 주문이 완료되면 새 상품표 수량을, 진행 중 환불 시도가 포트원 거절로 되돌아오면 세 배 단위를
   돌려준다.
4. 한 번만 돈다 — 두 번째 실행은 아무것도 바꾸지 않고 멈추고, 단위 기록이 있거나·진행 중 소설 작업이 있거나·돈 데이터가 있는데
   정지 스위치가 꺼져 있으면 시작 전에 멈춘다. downgrade 는 돈 데이터가 있던 전환이면 멈추고, 빈 DB 의 전환이면 기록만 지운다.
5. 되돌림은 전환 전 수량으로 정확히 돌아가고 원장에는 되돌림 행만 더한다. 전제(수량이 모두 3의 배수, 전환 뒤 콘솔 취소 없음,
   전환 뒤 옛 영수증 환급 없음)를 어기면 아무것도 쓰지 않는다.

세션 DB 에는 마이그레이션이 쓴 전환 기록이 이미 있으므로 테스트마다 롤백되는 연결에서 기록 표를 비우고 시작한다. 전환과 그
뒤의 쓰기는 각자 저장점 안에서 해, 행을 넣은 트랜잭션 번호가 실제 운영처럼 전환 앞뒤로 갈리게 한다.
"""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.environment import EnvironmentContext
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

import ops.revert_clover_unit as revert_script
from api.clover import products
from api.core import clover
from api.core.clover import refund_spend, revoke_purchase_lots, spend
from api.core.rate_limit import KST
from api.creator_payout.settlement import confirm_window
from api.db.base import Base
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendAllocation, CloverUnitEvent
from api.db.models.creator_payout import CreatorPayoutConfirmationLine
from api.db.models.novel import Novel, NovelJob
from api.db.models.payment import Payment, PaymentCancellation
from api.payments import refund
from api.payments.service import _grant_lots
from factories import (
    Player,
    _application,
    _console_cancel,
    _create_admin,
    _make_draft_content,
    _make_payment,
    _make_player,
    _make_user,
    _use,
    kst,
)

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_APPS_API_DIR = Path(__file__).resolve().parents[1]


def _load_migration() -> ModuleType:
    (path,) = _VERSIONS_DIR.glob("*_clover_unit_conversion.py")
    spec = importlib.util.spec_from_file_location("_migration_clover_unit_conversion", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_migration()

# 정수 칼럼 가운데 세 배 하지 않는 것 — 원화·비율·건수·순서·토큰 수, 그리고 클로버 수량이지만 기록으로만 남는 원장·턴 영수증과
# 무료·유료 표지로만 읽는 화 공개 가격. 새 정수 칼럼이 생기면 아래 전수 테스트가 어느 쪽인지 정하라고 멈춘다.
_LEFT_AS_IS: dict[str, tuple[str, ...]] = {
    "assets": ("width", "height", "frame_count"),
    "chat_memory_embeddings": ("dims",),
    "chat_memory_episodes": ("ordinal", "start_turn", "end_turn", "importance"),
    "chat_memory_extractions": (
        "attempts",
        "prompt_tokens",
        "cached_tokens",
        "output_tokens",
        "thoughts_tokens",
        "episode_count",
    ),
    "chat_memory_fact_extractions": (
        "attempts",
        "prompt_tokens",
        "cached_tokens",
        "output_tokens",
        "thoughts_tokens",
        "fact_count",
    ),
    "chat_memory_facts": ("ordinal", "importance", "start_turn", "end_turn"),
    "chat_rooms": ("turn_count", "ending_reached_at_turn", "memory_version", "memory_forget_generation"),
    # 턴 영수증은 분석용 기록이다 — 돈을 움직이는 코드가 읽지 않고, 원가 보고는 전환 기록의 시각으로 나눠 읽는다.
    "chat_turns": ("turn_number", "clover_amount"),
    # 원장은 append-only 기록이다 — 과거 행의 금액을 읽어 돈을 움직이는 코드가 없고, 전환 행이 잔액을 새 단위로 잇는다.
    "clover_ledger": ("amount", "balance_after"),
    "clover_spend_allocations": ("seq",),
    "clover_unit_events": ("money_rows",),
    "content_versions": ("version_number",),
    "contents": ("view_count", "like_count", "chat_count"),
    "creator_payout_batch_runs": (
        "creator_count",
        "total_amount_krw",
        "unattributed_spend_count",
        "refund_event_mismatch_count",
    ),
    "creator_payout_confirmations": ("rate_bps", "amount_krw"),
    "creator_payouts": ("amount_krw", "income_tax_rate_bps", "income_tax_krw", "local_tax_krw", "net_amount_krw"),
    "discarded_responses": ("discarded_count",),
    "ending_rule_groups": ("order",),
    "ending_rules": ("order",),
    "endings": ("turn_count_gate", "order"),
    "genres": ("sort_order",),
    "home_novel_curations": ("position",),
    "image_generation_requests": ("requested_count", "completed_count", "blocked_count", "input_error_count"),
    "keyword_notes": ("order", "sticky_turns"),
    "media_book_people": ("order",),
    "media_book_scenes": ("order",),
    "novel_batches": ("ordinal", "assistant_message_count", "target_episode_count"),
    "novel_chapter_editions": ("edition",),
    "novel_chapter_illustrations": ("sort_order",),
    # 화 공개 가격은 0(무료)인지만 읽는다 — 유료 화는 언제나 지금 단가로 판다.
    "novel_chapter_publications": ("ordinal", "edition", "price"),
    "novel_chapter_revisions": ("revision_no",),
    "novel_chapters": ("ordinal", "assistant_message_count", "episode_index"),
    "novel_episode_outlines": ("revision",),
    "novel_free_ordinals": ("ordinal",),
    "novel_jobs": ("paragraph_start", "paragraph_end", "episode_count_target", "planned_batches", "batch_k_max"),
    "novel_outlines": ("revision",),
    "novel_publications": ("like_count", "view_count"),
    "novel_purchases": ("chapter_ordinal", "edition"),
    "novel_reader_positions": ("paragraph_index", "paragraph_count", "edition"),
    "novel_reading_positions": ("paragraph_index", "paragraph_count"),
    "novel_reports": ("chapter_ordinal",),
    "novel_screenings": ("chapter_ordinal",),
    "novel_source_sections": ("assistant_message_count",),
    "novel_source_selections": ("revision",),
    "payment_cancellations": ("amount_krw", "ratio_percent"),
    "payments": ("amount_krw", "cancelled_amount_krw"),
    "prompt_route_revisions": ("number",),
    "prompt_section_semvers": ("major", "minor", "patch"),
    "prompt_sections": ("order",),
    "prompt_set_semvers": ("major", "minor", "patch"),
    "publish_filter_text_section_backups": ("order",),
    "situation_notes": ("order",),
    "situational_images": ("order",),
    "starting_setups": ("order",),
    "stat_defs": ("min_value", "max_value", "initial_value", "per_turn_delta", "max_change_per_turn", "order"),
    "stat_rules": ("delta", "order"),
}

_Rows = dict[str, dict[tuple[Any, ...], tuple[Any, ...]]]


@pytest_asyncio.fixture(autouse=True)
async def _no_unit_events(db_session: AsyncSession) -> None:
    """세션 DB 의 전환 기록(마이그레이션이 쓴 것)을 이 테스트의 롤백되는 트랜잭션 안에서만 비운다. 같은 세션의 다른 테스트가
    커밋해 남긴 진행 중 소설 작업도 이 트랜잭션 안에서만 옛 코드 실패 꼴로 닫는다 — 남아 있으면 전환이 시작 전 거절로 멈춰 이
    파일의 결과가 실행 순서에 따라 갈린다."""
    await db_session.execute(sa.delete(CloverUnitEvent))
    await db_session.execute(
        sa.update(NovelJob)
        .where(NovelJob.status.in_(("queued", "running")))
        .values(status="failed", refunded_at=sa.func.now())
    )
    await db_session.flush()


# ── 실행 도우미 ──────────────────────────────────────────────────────────────
async def _in_savepoint(db: AsyncSession, step: Callable[[Connection], Any]) -> Any:
    """`step` 을 저장점 안에서 이 테스트의 연결로 돌린다. 예외면 저장점만 되감는다."""
    await db.flush()
    connection = await db.connection()
    async with db.begin_nested():
        result = await connection.run_sync(step)
    return result


async def _convert(db: AsyncSession, *, paused: bool = True) -> None:
    await _in_savepoint(db, lambda c: _M.convert_clover_unit(c, ledger_paused=paused))


async def _revert(db: AsyncSession) -> revert_script.RevertReport:
    report: revert_script.RevertReport = await _in_savepoint(db, revert_script.revert_clover_unit)
    return report


async def _quantities(db: AsyncSession) -> _Rows:
    """세 배 하는 칼럼 전부를 표·기본키별로. 전환 전후·되돌림 뒤를 비교하는 스냅숏이다."""
    out: _Rows = {}
    connection = await db.connection()
    for table, columns in _M.CONVERTED_COLUMNS:
        keys = [column.name for column in Base.metadata.tables[table].primary_key.columns]
        rows = await connection.execute(sa.text(f"SELECT {', '.join(keys)}, {', '.join(columns)} FROM {table}"))
        out[table] = {tuple(row[: len(keys)]): tuple(row[len(keys) :]) for row in rows}
    return out


def _tripled(before: _Rows) -> _Rows:
    return {
        table: {key: tuple(None if value is None else value * 3 for value in values) for key, values in rows.items()}
        for table, rows in before.items()
    }


async def _ledger(db: AsyncSession) -> dict[uuid.UUID, tuple[Any, ...]]:
    rows = await db.execute(
        sa.select(
            CloverLedger.id,
            CloverLedger.user_id,
            CloverLedger.amount,
            CloverLedger.balance_after,
            CloverLedger.kind,
            CloverLedger.idempotency_key,
        )
    )
    return {row[0]: tuple(row[1:]) for row in rows}


async def _events(db: AsyncSession) -> list[CloverUnitEvent]:
    return list((await db.scalars(sa.select(CloverUnitEvent).order_by(CloverUnitEvent.occurred_at))).all())


async def _user(db: AsyncSession, *, balance: int = 0) -> User:
    user = _make_user(clover_balance=balance)
    db.add(user)
    await db.flush()
    return user


async def _paid_player(db: AsyncSession, *, amount_krw: int, paid: int, bonus: int = 0, free: int = 0) -> Player:
    player = await _make_player(db, amount_krw=amount_krw, paid=paid, bonus=bonus, free=free)
    player.payment.paid_at = datetime(2026, 10, 10, 3, tzinfo=UTC)
    await db.flush()
    return player


async def _invariant_breaks(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[str, int]:
    """이 테스트가 만든 회원만 본 불변식 위반 수. 마이그레이션 자신의 사후 검사와 따로 센다."""
    params = {"ids": user_ids}
    queries = {
        "balance_ne_lots": """
            SELECT count(*) FROM users u
            LEFT JOIN (SELECT user_id, sum(remaining) AS r FROM clover_lots GROUP BY user_id) l ON l.user_id = u.id
             WHERE u.id = ANY(:ids) AND u.clover_balance <> coalesce(l.r, 0)""",
        # 한 트랜잭션의 원장 행은 created_at 이 같아 순서를 못 가린다 — 가장 늦은 시각의 행 중 하나라도 맞으면 맞다.
        "last_ledger_ne_balance": """
            SELECT count(*) FROM users u
              JOIN (SELECT user_id, max(created_at) AS last_at FROM clover_ledger GROUP BY user_id) m ON m.user_id = u.id
             WHERE u.id = ANY(:ids) AND NOT EXISTS (
                   SELECT 1 FROM clover_ledger g
                    WHERE g.user_id = u.id AND g.created_at = m.last_at AND g.balance_after = u.clover_balance)""",
        "purchase_lot_ne_copy": """
            SELECT count(*) FROM clover_lots l JOIN payments p ON p.id = l.payment_id
             WHERE l.user_id = ANY(:ids)
               AND ((l.kind = 'purchase_paid' AND l.granted_amount <> p.paid_amount)
                 OR (l.kind = 'purchase_bonus' AND l.granted_amount <> p.bonus_amount))""",
        "refunded_gt_amount": """
            SELECT count(*) FROM clover_spend_allocations a JOIN clover_lots l ON l.id = a.lot_id
             WHERE l.user_id = ANY(:ids) AND a.refunded_amount > a.amount""",
    }
    return {name: int((await db.execute(sa.text(sql), params)).scalar_one()) for name, sql in queries.items()}


# ── 대상 칼럼 ────────────────────────────────────────────────────────────────
def test_every_integer_column_is_either_converted_or_explicitly_left_as_is() -> None:
    """깨지는 시나리오: 새 클로버 수량 칼럼이 생겼는데 전환 목록에 없어, 전환 뒤 그 칼럼만 옛 단위로 남는다."""
    converted = {(table, column) for table, columns in _M.CONVERTED_COLUMNS for column in columns}
    left = {(table, column) for table, columns in _LEFT_AS_IS.items() for column in columns}
    integers = {
        (table.name, column.name)
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, sa.Integer)
    }

    assert converted & left == set()
    assert converted | left == integers


def test_the_revert_script_carries_the_same_columns_and_lock_order_as_the_migration() -> None:
    """마이그레이션은 앱 코드를 import 하지 않아 되돌림 스크립트와 목록을 나눠 가질 수 없다 — 두 사본이 같아야 되돌림이 전환한
    칼럼을 빠짐없이 나누고, 같은 순서로 잠가 교착이 없다."""
    assert revert_script.CONVERTED_COLUMNS == _M.CONVERTED_COLUMNS
    assert revert_script.LOCK_ORDER == _M.LOCK_ORDER


def test_tables_are_locked_payments_first_then_users_before_any_other_quantity_table() -> None:
    """돈을 움직이는 모든 경로는 결제 행, 그다음 회원 행을 먼저 잠근다. 전환이 같은 순서로 잡아야 그 경로와 교착하지 않는다."""
    order = _M.LOCK_ORDER
    assert order[:3] == ("payments", "payment_cancellations", "users")
    assert {table for table, _ in _M.CONVERTED_COLUMNS} | {"clover_ledger", "clover_unit_events"} == set(order)


# ── 환불 견적(원)이 그대로 ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("received_on", "company_fault"),
    [
        pytest.param(date(2026, 10, 12), False, id="within-7-days"),
        pytest.param(date(2026, 10, 20), False, id="after-7-days"),
        pytest.param(date(2026, 10, 20), True, id="company-fault"),
    ],
)
@pytest.mark.parametrize("bonus_used", [False, True], ids=["bonus-unused", "bonus-used"])
@pytest.mark.parametrize("partially_cancelled", [False, True], ids=["no-cancel", "partially-cancelled"])
async def test_refund_quote_in_won_is_the_same_before_and_after(
    db_session: AsyncSession, received_on: date, company_fault: bool, bonus_used: bool, partially_cancelled: bool
) -> None:
    # 보너스를 안 쓰는 갈래는 무료 로트가 차감을 먼저 받는다(차감 순서: 무료 → 보너스 → 유료).
    player = await _paid_player(db_session, amount_krw=4_500, paid=1_500, bonus=75, free=0 if bonus_used else 100)
    await _use(db_session, player, None, 100, kst(10, 11), usage="image")
    if partially_cancelled:
        await _console_cancel(db_session, player.payment, 1_000, kst(10, 11))
        player.payment.status = "partially_cancelled"
    await db_session.flush()

    async def quote() -> refund.RefundQuote:
        order = await db_session.get(Payment, player.payment.id, populate_existing=True)
        assert order is not None
        return await refund.quote_refund(
            db_session, order, received_on=received_on, company_fault=company_fault, today=received_on
        )

    before = await quote()
    await _convert(db_session)
    after = await quote()

    assert (before.bonus_used > 0) is bonus_used
    assert (after.refund_krw, after.ratio_percent, after.cancellable_krw) == (
        before.refund_krw,
        before.ratio_percent,
        before.cancellable_krw,
    )
    assert (after.paid_remaining, after.bonus_used, after.clawback_paid, after.clawback_bonus) == (
        before.paid_remaining * 3,
        before.bonus_used * 3,
        before.clawback_paid * 3,
        before.clawback_bonus * 3,
    )


async def test_two_thousand_three_hundred_held_three_hundred_used_still_refunds_six_thousand_won(
    db_session: AsyncSession,
) -> None:
    """3원 단위 2,300 결제(6,900원)에서 300 을 쓰면 남은 2,000 × 3원 = 6,000원. 전환 뒤에는 6,900 중 900 을 쓴 것이고 남은
    6,000 × 1원 = 6,000원이다."""
    player = await _paid_player(db_session, amount_krw=6_900, paid=2_300)
    await _use(db_session, player, None, 300, kst(10, 11), usage="image")
    on = date(2026, 10, 12)

    async def refund_krw() -> tuple[int, int]:
        order = await db_session.get(Payment, player.payment.id, populate_existing=True)
        assert order is not None
        quote = await refund.quote_refund(db_session, order, received_on=on, company_fault=False, today=on)
        return quote.paid_remaining, quote.refund_krw

    assert await refund_krw() == (2_000, 6_000)
    await _convert(db_session)
    assert await refund_krw() == (6_000, 6_000)


# ── 정산(원)이 그대로 ─────────────────────────────────────────────────────────
async def test_settlement_share_and_post_confirmation_cancel_adjustment_are_the_same_before_and_after(
    db_session: AsyncSession,
) -> None:
    """10월에 E(9,900원/3,300)가 작가 작품에서 600 을 써 확정, 11-10 콘솔 부분 취소 8,910원으로 계수가 내려가고 11월에 G 가
    50 을 쓴다. 11월 확정의 적립·조정(원)이 전환 전후 같다 — 확정 줄의 순사용과 결제 사본이 함께 세 배라 계수와 단가가 상쇄된다.
    깨지는 시나리오: 확정 줄 순사용만 옛 단위로 남아 조정이 3분의 1이 된다."""
    creator = await _user(db_session)
    content = await _make_draft_content(db_session, creator_user_id=creator.id)
    await _application(db_session, creator.id, accrual_start_at=datetime(2026, 9, 1, tzinfo=KST))
    october = (datetime(2026, 10, 1, tzinfo=KST), datetime(2026, 11, 1, tzinfo=KST))
    november = (datetime(2026, 11, 1, tzinfo=KST), datetime(2026, 12, 1, tzinfo=KST))
    e = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, e, content, 600, kst(10, 15))
    confirmed = await confirm_window(
        db_session,
        creator_id=creator.id,
        kind="monthly",
        period_month=october[0].date(),
        windows=[october],
        cancel_adjust_month=october,
    )
    assert confirmed is not None
    await _console_cancel(db_session, e.payment, 8_910, kst(11, 10))
    g = await _make_player(db_session, amount_krw=900, paid=300)
    await _use(db_session, g, content, 50, kst(11, 15))

    async def november_confirmation() -> tuple[Any, ...]:
        async with db_session.begin_nested() as savepoint:
            row = await confirm_window(
                db_session,
                creator_id=creator.id,
                kind="monthly",
                period_month=november[0].date(),
                windows=[november],
                cancel_adjust_month=november,
            )
            assert row is not None
            lines = (
                await db_session.scalars(
                    sa.select(CreatorPayoutConfirmationLine).where(
                        CreatorPayoutConfirmationLine.confirmation_id == row.id
                    )
                )
            ).all()
            result = (
                row.amount_krw,
                row.exact_krw,
                row.gross_units,
                {line.payment_id: (line.net_units, line.cancel_adjust_krw, line.exact_krw) for line in lines},
            )
            await savepoint.rollback()
        return result

    before = await november_confirmation()
    await _convert(db_session)
    after = await november_confirmation()

    assert before[:2] == (-30, Decimal("-30"))
    assert before[3][e.payment.id][1] == Decimal("-36.8181818182")
    assert after[:2] == before[:2]
    assert after[2] == before[2] * 3
    assert {k: (v[0] // 3, v[1], v[2]) for k, v in after[3].items()} == before[3]


# ── 불변식·원장 전환 행·기록 ───────────────────────────────────────────────────
async def test_invariants_hold_and_every_holder_gets_one_conversion_row(db_session: AsyncSession) -> None:
    """실제 지급·차감·환급 경로로 만든 회원들 — 구매 지급(유료·보너스 두 원장 행이 한 트랜잭션), 차감 후 일부 환급, 잔액 0.
    전환 뒤 네 불변식이 서고, 잔액이 있는 회원마다 전환 행이 정확히 하나(+2b, 잔액 3b, 멱등키), 잔액 0 회원은 없다."""
    buyer = await _user(db_session)
    order = await _make_payment(db_session, user_id=buyer.id, amount_krw=9_900, paid_amount=3_300, bonus_amount=330)
    await _grant_lots(db_session, order, datetime(2027, 10, 10, tzinfo=UTC))
    spent = await spend(db_session, user_id=buyer.id, amount=500, kind="chat_spend")
    assert spent is not None
    await refund_spend(db_session, user_id=buyer.id, spend_ledger_id=spent.ledger_id, amount=200, kind="chat_refund")
    gifted = await _user(db_session)
    await clover.grant(db_session, user_id=gifted.id, amount=100, kind="admin_grant")
    empty = await _user(db_session)
    ids = [buyer.id, gifted.id, empty.id]
    ledger_before = await _ledger(db_session)
    holders_before = int(
        (await db_session.execute(sa.text("SELECT count(*) FROM users WHERE clover_balance > 0"))).scalar_one()
    )

    await _convert(db_session)

    assert await _invariant_breaks(db_session, ids) == {
        "balance_ne_lots": 0,
        "last_ledger_ne_balance": 0,
        "purchase_lot_ne_copy": 0,
        "refunded_gt_amount": 0,
    }
    balances = {
        user_id: balance
        for user_id, balance in (
            await db_session.execute(sa.select(User.id, User.clover_balance).where(User.id.in_(ids)))
        ).all()
    }
    assert balances == {buyer.id: (3_630 - 500 + 200) * 3, gifted.id: 300, empty.id: 0}
    ledger_after = await _ledger(db_session)
    added = {key: row for key, row in ledger_after.items() if key not in ledger_before}
    assert set(ledger_before) <= set(ledger_after)
    assert all(ledger_after[key] == row for key, row in ledger_before.items())
    assert len(added) == holders_before
    mine = sorted((row for row in added.values() if row[0] in ids), key=lambda row: str(row[0]))
    assert mine == sorted(
        [
            (user_id, balance * 2 // 3, balance, "unit_conversion", f"unit-conversion:{user_id}")
            for user_id, balance in balances.items()
            if balance > 0
        ],
        key=lambda row: str(row[0]),
    )
    (event,) = await _events(db_session)
    assert (event.action, event.written_by) == ("convert", _M.revision)
    assert event.lock_started_at <= event.occurred_at
    conversion_times = set(
        (
            await db_session.scalars(sa.select(CloverLedger.created_at).where(CloverLedger.kind == "unit_conversion"))
        ).all()
    )
    assert conversion_times == {event.occurred_at}


async def test_money_rows_on_the_record_are_holders_plus_payment_rows(db_session: AsyncSession) -> None:
    """downgrade 가 멈출지를 이 값으로 정한다 — 전환할 때 센 잔액 있는 회원 수 + 결제 행 수."""
    expected = int(
        (
            await db_session.execute(
                sa.text(
                    "SELECT (SELECT count(*) FROM users WHERE clover_balance > 0) + (SELECT count(*) FROM payments)"
                )
            )
        ).scalar_one()
    )
    await _convert(db_session)
    (event,) = await _events(db_session)
    assert event.money_rows == expected


# ── 결제 경로의 옛 일 ─────────────────────────────────────────────────────────
async def test_a_pending_order_completed_after_conversion_grants_the_new_product_amounts(
    db_session: AsyncSession,
) -> None:
    """전환 때 대기 중이던 라이트 주문(옛 사본 1,500+75)이 전환 뒤 완료되면 새 상품표와 같은 4,500+225 를 받는다. 깨지는
    시나리오: 대기 주문 사본이 옛 단위로 남아 같은 4,500원에 3분의 1을 받는다."""
    buyer = await _user(db_session)
    order = await _make_payment(
        db_session, user_id=buyer.id, product_key="lite", amount_krw=4_500, paid_amount=1_500, bonus_amount=75
    )

    await _convert(db_session)

    fresh = await db_session.get(Payment, order.id, populate_existing=True)
    assert fresh is not None
    await _grant_lots(db_session, fresh, datetime(2027, 10, 10, tzinfo=UTC))
    lots = dict(
        (
            await db_session.execute(
                sa.select(CloverLot.kind, CloverLot.granted_amount).where(CloverLot.payment_id == order.id)
            )
        )
        .tuples()
        .all()
    )
    (lite,) = [product for product in products.CLOVER_PRODUCTS if product.key == "lite"]
    assert lots == {"purchase_paid": 4_500, "purchase_bonus": 225}
    assert (lite.paid_amount, lite.bonus_amount) == (4_500, 225)


async def test_a_requested_refund_refused_by_portone_after_conversion_restores_in_the_new_unit(
    db_session: AsyncSession,
) -> None:
    """어드민 환불 시도가 남은 구매분(3,300+330)을 회수해 쥔 채 전환을 맞고, 그 뒤 포트원이 거절하면 세 배 단위(9,900+990)로
    돌려받아 로트가 지급량까지 찬다. 깨지는 시나리오: 시도 행의 회수량이 옛 단위로 남아 3분의 1만 돌아온다."""
    admin = await _create_admin(db_session)
    player = await _paid_player(db_session, amount_krw=9_900, paid=3_300, bonus=330)
    paid, bonus = await revoke_purchase_lots(db_session, payment_id=player.payment.id)
    attempt = PaymentCancellation(
        payment_id=player.payment.id,
        source="admin",
        status="requested",
        amount_krw=9_900,
        ratio_percent=100,
        request_received_on=date(2026, 10, 12),
        admin_id=admin["id"],
        clawback_paid=paid,
        clawback_bonus=bonus,
    )
    db_session.add(attempt)
    await db_session.flush()

    await _convert(db_session)

    order = await db_session.get(Payment, player.payment.id, populate_existing=True)
    row = await db_session.get(PaymentCancellation, attempt.id, populate_existing=True)
    assert order is not None and row is not None
    assert (row.clawback_paid, row.clawback_bonus) == (9_900, 990)
    await refund._fail(db_session, order, row, portone_cancellation_id=None)
    lots = (
        (
            await db_session.execute(
                sa.select(CloverLot.kind, CloverLot.granted_amount, CloverLot.remaining)
                .where(CloverLot.payment_id == order.id)
                .execution_options(populate_existing=True)
            )
        )
        .tuples()
        .all()
    )
    assert sorted(lots) == [("purchase_bonus", 990, 990), ("purchase_paid", 9_900, 9_900)]
    balance = await db_session.scalar(
        sa.select(User.clover_balance).where(User.id == player.user.id).execution_options(populate_existing=True)
    )
    assert balance == 10_890


# ── 소설 작업 ────────────────────────────────────────────────────────────────
async def test_novel_jobs_keep_every_check_and_are_exactly_tripled(db_session: AsyncSession) -> None:
    """성공(환불 없음)·성공 부분 환불·새 코드 실패(환불 = 선차감 − 쓴 몫)·옛 코드 실패(환불 시각만, 금액 없음)·연쇄 부모 성공과
    실패. 넷 칼럼을 한 문장에서 함께 세 배 하므로 행마다 같은 CHECK 가 서고, 빈 칸은 비어 있다. 깨지는 시나리오: 칼럼을 따로
    바꿔 중간 상태에서 CHECK 가 마이그레이션을 멈추거나, 연쇄 단가가 옛 단위로 남아 다음 묶음이 3분의 1을 쓴 것으로 적힌다."""
    owner = await _user(db_session)
    novel = Novel(
        user_id=owner.id, content_id=uuid.uuid4(), content_type="character", content_title="원작", character_name="인물"
    )
    db_session.add(novel)
    await db_session.flush()
    at = datetime(2026, 10, 20, tzinfo=UTC)
    shapes: dict[str, dict[str, Any]] = {
        "succeeded": {"kind": "chapter_generate", "status": "succeeded", "charged_amount": 80},
        "succeeded-partial-refund": {
            "kind": "chapter_generate",
            "status": "succeeded",
            "charged_amount": 240,
            "refunded_at": at,
            "refunded_amount": 80,
        },
        "failed": {
            "kind": "chapter_generate",
            "status": "failed",
            "charged_amount": 80,
            "refunded_at": at,
            "refunded_amount": 80,
        },
        "failed-old-code": {"kind": "chapter_generate", "status": "failed", "charged_amount": 80, "refunded_at": at},
        "chain-succeeded": {
            "kind": "chain_generate",
            "status": "succeeded",
            "charged_amount": 480,
            "consumed_amount": 240,
            "refunded_at": at,
            "refunded_amount": 240,
            "planned_batches": 2,
            "batch_k_max": 3,
            "unit_price": 80,
        },
        "chain-failed": {
            "kind": "chain_generate",
            "status": "failed",
            "charged_amount": 480,
            "consumed_amount": 160,
            "refunded_at": at,
            "refunded_amount": 320,
            "planned_batches": 2,
            "batch_k_max": 3,
            "unit_price": 80,
        },
    }
    jobs = {name: NovelJob(novel_id=novel.id, user_id=owner.id, **values) for name, values in shapes.items()}
    db_session.add_all(jobs.values())
    await db_session.flush()

    def amounts(job: NovelJob) -> tuple[int | None, ...]:
        return (job.charged_amount, job.refunded_amount, job.consumed_amount, job.unit_price)

    before = {name: amounts(job) for name, job in jobs.items()}
    await _convert(db_session)
    after: dict[str, tuple[int | None, ...]] = {}
    for name, job in jobs.items():
        fresh = await db_session.get(NovelJob, job.id, populate_existing=True)
        assert fresh is not None
        after[name] = amounts(fresh)

    assert after == {name: tuple(None if v is None else v * 3 for v in values) for name, values in before.items()}
    assert after["failed-old-code"][1] is None and after["succeeded"][3] is None


# ── 한 번만 · 사전 거절 ───────────────────────────────────────────────────────
async def test_a_second_run_stops_before_touching_anything(db_session: AsyncSession) -> None:
    """같은 DB 에서 두 번째 전환은 기록이 이미 있어 멈추고, 데이터는 첫 전환 뒤와 같다(아홉 배가 되지 않는다)."""
    await _paid_player(db_session, amount_krw=900, paid=300)
    await _convert(db_session)
    once = await _quantities(db_session)
    ledger_once = await _ledger(db_session)

    with pytest.raises(RuntimeError, match="단위 기록"):
        await _convert(db_session)

    assert await _quantities(db_session) == once
    assert await _ledger(db_session) == ledger_once
    assert len(await _events(db_session)) == 1


@pytest.mark.parametrize(
    ("has_events", "active_novel_jobs", "money_rows", "paused", "refused"),
    [
        pytest.param(False, 0, 0, False, None, id="empty-db-without-switch"),
        pytest.param(False, 0, 5, True, None, id="money-with-switch"),
        pytest.param(True, 0, 0, True, "단위 기록", id="already-recorded"),
        pytest.param(False, 1, 0, True, "진행 중인 소설", id="active-novel-job"),
        pytest.param(False, 0, 5, False, "정지 스위치", id="money-without-switch"),
    ],
)
def test_refusal_table(
    has_events: bool, active_novel_jobs: int, money_rows: int, paused: bool, refused: str | None
) -> None:
    reason = _M.refusal_reason(
        has_events=has_events, active_novel_jobs=active_novel_jobs, money_rows=money_rows, ledger_paused=paused
    )
    assert reason is None if refused is None else (reason is not None and refused in reason)


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_an_active_novel_job_stops_the_conversion(db_session: AsyncSession, status: str) -> None:
    """연쇄 실행은 실행 중에 쓴 몫을 누적한다 — 전환과 겹치면 옛 값 위에 새 값을 더해 금액이 어긋난다."""
    owner = await _user(db_session)
    novel = Novel(
        user_id=owner.id, content_id=uuid.uuid4(), content_type="character", content_title="원작", character_name="인물"
    )
    db_session.add(novel)
    await db_session.flush()
    db_session.add(
        NovelJob(novel_id=novel.id, user_id=owner.id, kind="chapter_generate", status=status, charged_amount=80)
    )
    await db_session.flush()
    before = await _quantities(db_session)

    with pytest.raises(RuntimeError, match="진행 중인 소설"):
        await _convert(db_session)

    assert await _quantities(db_session) == before
    assert await _events(db_session) == []


async def test_money_data_with_the_pause_switch_off_stops_the_conversion(db_session: AsyncSession) -> None:
    """돈 데이터가 있는 DB 에서 정지 스위치가 꺼져 있으면 평상시 배포가 실수로 돌린 것이다 — 겹친 옛 코드가 세 배 잔액을 옛
    가격으로 깎지 않게 시작 전에 멈춘다."""
    await _paid_player(db_session, amount_krw=900, paid=300)
    before = await _quantities(db_session)

    with pytest.raises(RuntimeError, match="정지 스위치"):
        await _convert(db_session, paused=False)

    assert await _quantities(db_session) == before


def _environment(sync_connection: Connection, attributes: dict[str, object]) -> MigrationContext:
    config = Config(str(_APPS_API_DIR / "alembic.ini"))
    config.attributes.update(attributes)
    environment = EnvironmentContext(config, ScriptDirectory.from_config(config))
    return MigrationContext.configure(sync_connection, environment_context=environment)


@pytest.mark.parametrize(("attributes", "refused"), [({}, True), ({"clover_ledger_paused": True}, False)])
async def test_upgrade_reads_the_pause_switch_from_the_alembic_config(
    db_session: AsyncSession, attributes: dict[str, object], refused: bool
) -> None:
    """리비전은 앱 설정을 import 하지 않는다 — `migrations/env.py` 가 넘긴 설정 값을 읽고, 값이 없으면 꺼짐으로 본다."""
    await _paid_player(db_session, amount_krw=900, paid=300)

    def upgrade(sync_connection: Connection) -> None:
        with Operations.context(_environment(sync_connection, attributes)):
            _M.upgrade()

    if refused:
        with pytest.raises(RuntimeError, match="정지 스위치"):
            await _in_savepoint(db_session, upgrade)
    else:
        await _in_savepoint(db_session, upgrade)
        assert [event.action for event in await _events(db_session)] == ["convert"]


# ── downgrade ──────────────────────────────────────────────────────────────
async def _downgrade(db: AsyncSession) -> None:
    def step(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            _M.downgrade()

    await _in_savepoint(db, step)


async def test_downgrade_stops_when_the_conversion_had_money_data(db_session: AsyncSession) -> None:
    at = datetime(2026, 11, 1, tzinfo=UTC)
    db_session.add(
        CloverUnitEvent(action="convert", lock_started_at=at, occurred_at=at, money_rows=3, written_by=_M.revision)
    )

    with pytest.raises(RuntimeError, match="되돌리지 않는다"):
        await _downgrade(db_session)

    assert len(await _events(db_session)) == 1


async def test_downgrade_after_an_empty_database_conversion_clears_every_record(db_session: AsyncSession) -> None:
    """테스트 세션 정리(`downgrade base`)가 이 길을 탄다 — 빈 DB 의 전환과 테스트가 남긴 되돌림 기록을 모두 지워야 기록 표를
    만든 앞 리비전의 downgrade 가 멈추지 않는다."""
    at = datetime(2026, 11, 1, tzinfo=UTC)
    db_session.add_all(
        [
            CloverUnitEvent(action="convert", lock_started_at=at, occurred_at=at, money_rows=0, written_by=_M.revision),
            CloverUnitEvent(
                action="revert",
                lock_started_at=at + timedelta(days=1),
                occurred_at=at + timedelta(days=1),
                money_rows=4,
                written_by="revert_clover_unit",
            ),
        ]
    )

    await _downgrade(db_session)

    assert await _events(db_session) == []


# ── 되돌림 스크립트 ───────────────────────────────────────────────────────────
async def _seed_for_revert(db: AsyncSession) -> list[uuid.UUID]:
    """되돌림이 다시 나눌 갈래들: 결제 지급과 차감·환급, 부분 콘솔 취소(올림 회수량), 어드민 지급, 잔액 0."""
    buyer = await _user(db)
    order = await _make_payment(
        db, user_id=buyer.id, amount_krw=9_900, paid_amount=3_300, bonus_amount=330, status="paid"
    )
    await _grant_lots(db, order, datetime(2027, 10, 10, tzinfo=UTC))
    spent = await spend(db, user_id=buyer.id, amount=410, kind="chat_spend")
    assert spent is not None
    await refund_spend(db, user_id=buyer.id, spend_ledger_id=spent.ledger_id, amount=10, kind="chat_refund")
    canceller = await _paid_player(db, amount_krw=4_500, paid=1_500, bonus=75)
    await _console_cancel(db, canceller.payment, 1_000, kst(10, 11))
    gifted = await _user(db)
    await clover.grant(db, user_id=gifted.id, amount=100, kind="admin_grant")
    empty = await _user(db)
    await db.flush()
    return [buyer.id, canceller.user.id, gifted.id, empty.id]


def _after(event: CloverUnitEvent) -> datetime:
    return event.lock_started_at + timedelta(seconds=1)


async def test_revert_returns_every_quantity_and_only_adds_revert_rows(db_session: AsyncSession) -> None:
    ids = await _seed_for_revert(db_session)
    original = await _quantities(db_session)
    await _convert(db_session)
    converted_ledger = await _ledger(db_session)
    holders = sum(1 for values in (await _quantities(db_session))["users"].values() if values[0] > 0)

    report = await _revert(db_session)

    assert report.violations == {}
    assert report.reverted and report.target_users == holders
    assert await _quantities(db_session) == original
    ledger = await _ledger(db_session)
    added = [row for key, row in ledger.items() if key not in converted_ledger]
    assert all(ledger[key] == row for key, row in converted_ledger.items())
    assert len(added) == holders and {row[3] for row in added} == {"unit_conversion_revert"}
    balances = dict(
        (await db_session.execute(sa.select(User.id, User.clover_balance).where(User.id.in_(ids)))).tuples().all()
    )
    mine = sorted((row for row in added if row[0] in ids), key=lambda row: str(row[0]))
    assert mine == sorted(
        [
            (user_id, -2 * balance, balance, "unit_conversion_revert", f"unit-conversion-revert:{user_id}")
            for user_id, balance in balances.items()
            if balance > 0
        ],
        key=lambda row: str(row[0]),
    )
    assert await _invariant_breaks(db_session, ids) == {
        "balance_ne_lots": 0,
        "last_ledger_ne_balance": 0,
        "purchase_lot_ne_copy": 0,
        "refunded_gt_amount": 0,
    }
    assert [(event.action, event.written_by) for event in await _events(db_session)] == [
        ("convert", _M.revision),
        ("revert", revert_script.SCRIPT_NAME),
    ]


async def test_a_second_revert_stops_and_writes_nothing(db_session: AsyncSession) -> None:
    await _seed_for_revert(db_session)
    await _convert(db_session)
    await _revert(db_session)
    once = await _quantities(db_session)
    ledger_once = await _ledger(db_session)

    report = await _revert(db_session)

    assert report.violations == {"latest_event_not_convert": 1}
    assert not report.reverted
    assert await _quantities(db_session) == once
    assert await _ledger(db_session) == ledger_once


async def _converted_then(db: AsyncSession, write: Callable[[CloverUnitEvent], Any]) -> tuple[_Rows, Any]:
    """전환한 뒤 `write` 로 전환 뒤의 쓰기를 하나 만들고(저장점 — 전환보다 늦은 트랜잭션 번호), 그 시점의 스냅숏을 돌려준다."""
    await _convert(db)
    (event,) = await _events(db)
    async with db.begin_nested():
        await write(event)
        await db.flush()
    return await _quantities(db), await _ledger(db)


async def test_revert_refuses_quantities_that_are_not_multiples_of_three(db_session: AsyncSession) -> None:
    """정지가 새 새 가격(20)으로 깎은 차감이 끼면 나눗셈이 정확하지 않다 — 아무것도 쓰지 않고 멈춘다."""
    player = await _paid_player(db_session, amount_krw=900, paid=300)

    async def leak(event: CloverUnitEvent) -> None:
        spent = await spend(db_session, user_id=player.user.id, amount=20, kind="chat_spend")
        assert spent is not None
        await db_session.execute(
            sa.update(CloverLedger).where(CloverLedger.id == spent.ledger_id).values(created_at=_after(event))
        )

    snapshot, ledger = await _converted_then(db_session, leak)
    report = await _revert(db_session)

    assert report.violations.get("not_multiple_of_3:users.clover_balance", 0) > 0
    assert report.violations.get("ledger_not_multiple_of_3_after_conversion", 0) > 0
    assert not report.reverted
    assert await _quantities(db_session) == snapshot and await _ledger(db_session) == ledger


async def test_revert_refuses_a_console_cancel_after_conversion(db_session: AsyncSession) -> None:
    """전환 뒤 반영된 콘솔 취소는 새 단위로 회수했다 — 전액 취소라 수량이 3의 배수여도 멈춘다."""
    player = await _paid_player(db_session, amount_krw=900, paid=300)

    async def cancel(event: CloverUnitEvent) -> None:
        order = await db_session.get(Payment, player.payment.id, populate_existing=True)
        assert order is not None
        await _console_cancel(db_session, order, 900, _after(event))
        await db_session.execute(
            sa.update(PaymentCancellation)
            .where(PaymentCancellation.payment_id == order.id)
            .values(created_at=_after(event))
        )
        await db_session.execute(
            sa.update(CloverLedger)
            .where(CloverLedger.user_id == player.user.id, CloverLedger.kind == "purchase_revoke")
            .values(created_at=_after(event))
        )

    snapshot, ledger = await _converted_then(db_session, cancel)
    report = await _revert(db_session)

    assert report.violations.get("console_cancel_after_conversion", 0) == 1
    assert not any(key.startswith("not_multiple_of_3") for key in report.violations)
    assert not report.reverted
    assert await _quantities(db_session) == snapshot and await _ledger(db_session) == ledger


async def test_revert_refuses_an_old_receipt_refund_after_conversion(db_session: AsyncSession) -> None:
    """전환 전에 깎은 이미지 30(옛 단위)을 전환 뒤 옛 영수증으로 30 돌려주면 수량은 모두 3의 배수로 남지만 회원은 60 을 잃었다
    — 환급 kind 로 잡아 멈춘다."""
    player = await _paid_player(db_session, amount_krw=900, paid=300)
    spent = await spend(db_session, user_id=player.user.id, amount=30, kind="image_spend")
    assert spent is not None

    async def late_refund(event: CloverUnitEvent) -> None:
        await refund_spend(
            db_session, user_id=player.user.id, spend_ledger_id=spent.ledger_id, amount=30, kind="image_refund"
        )
        await db_session.execute(
            sa.update(CloverLedger)
            .where(CloverLedger.user_id == player.user.id, CloverLedger.kind == "image_refund")
            .values(created_at=_after(event))
        )

    snapshot, ledger = await _converted_then(db_session, late_refund)
    report = await _revert(db_session)

    assert report.violations.get("old_receipt_refund_after_conversion", 0) == 1
    assert not any(key.startswith("not_multiple_of_3") for key in report.violations)
    assert not report.reverted
    assert await _quantities(db_session) == snapshot and await _ledger(db_session) == ledger


@pytest.mark.parametrize(
    ("reverted", "apply", "finish", "code"),
    [
        pytest.param(True, False, "rollback", 0, id="dry-run"),
        pytest.param(True, True, "commit", 0, id="apply"),
        pytest.param(False, True, "rollback", 1, id="violation-never-commits"),
    ],
)
def test_only_an_applied_clean_revert_commits(reverted: bool, apply: bool, finish: str, code: int) -> None:
    report = revert_script.RevertReport(
        checks={} if reverted else {"latest_event_not_convert": 1}, target_users=1, reverted=reverted
    )
    assert revert_script.finish(report, apply=apply) == finish
    assert revert_script.exit_code(report) == code


def test_the_printed_summary_carries_counts_only() -> None:
    report = revert_script.RevertReport(
        checks={"console_cancel_after_conversion": 2, "old_receipt_refund_after_conversion": 0},
        target_users=7,
        reverted=False,
    )
    assert revert_script.render(report) == (
        "console_cancel_after_conversion=2\nold_receipt_refund_after_conversion=0\ntarget_users=7\nreverted=false"
    )
