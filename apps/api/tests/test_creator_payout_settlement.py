"""크리에이터 정산 계산(`confirm_window`)과 신청·확정·내역 테이블의 제약.

금액 기대값은 손으로 계산한 값이다. 결제 단가는 상품 상수가 아니라 테스트가 만든 결제 행의 금액·수량에서 나오고, 여기
결제는 모두 1클로버 = 3원이라 비율 500bps 에서 유료 1클로버 = 3 × 500 / 11000 = 3/22 원이다.

시각은 사용처·환급 행의 `created_at` 을 직접 고쳐 만든다(한 트랜잭션 안의 `now()` 는 모두 같은 값이라). 결제별 계수는
"지금" 상태로 계산되므로, 여러 달을 잇는 경우는 그 달까지 일어난 일만 넣고 확정한 뒤 다음 달 일을 넣는다.

CHECK·부분 유니크·복합 PK 는 alembic 1.18.5 의 `alembic check` 가 비교하지 않아 아래 `IntegrityError` 행위 테스트가 유일한
검증이다 — 지우면 커버리지가 오히려 오르므로 커버리지로는 빠진 것을 알 수 없다.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import config
from api.core.clover import CloverKind, SpendUsage, refund_spend, revoke_purchase_lots, spend
from api.core.rate_limit import KST
from api.creator_payout import settlement
from api.creator_payout.settlement import confirm_window
from api.db.models.auth import User
from api.db.models.clover import CloverLot, CloverSpendAllocation, CloverSpendRefund, CloverSpendUsage
from api.db.models.content import Content
from api.db.models.creator_payout import (
    CreatorPayoutApplication,
    CreatorPayoutConfirmation,
    CreatorPayoutConfirmationLine,
)
from api.db.models.payment import Payment, PaymentCancellation
from factories import _create_admin, _make_draft_content, _make_payment, _make_user


def kst(month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0, *, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=KST)


def month_of(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=KST)
    end = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=KST)
    return start, end


APPROVED_BEFORE_OCTOBER = datetime(2026, 9, 1, tzinfo=KST)
OCT = month_of(2026, 10)
NOV = month_of(2026, 11)
DEC = month_of(2026, 12)


# ── 셋업 ─────────────────────────────────────────────────────────────────
async def _creator(
    db: AsyncSession, *, accrual_start_at: datetime | None = APPROVED_BEFORE_OCTOBER
) -> tuple[User, Content]:
    """작가와 그 작품 하나. `accrual_start_at` 이 있으면 그때부터 승인된 신청 행을 둔다(월 확정 시작도 같은 시각)."""
    creator = _make_user()
    db.add(creator)
    await db.flush()
    content = await _make_draft_content(db, creator_user_id=creator.id)
    if accrual_start_at is not None:
        await _application(db, creator.id, accrual_start_at=accrual_start_at)
    return creator, content


async def _application(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    accrual_start_at: datetime,
    monthly_from_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> CreatorPayoutApplication:
    application = CreatorPayoutApplication(
        user_id=user_id,
        status="approved" if revoked_at is None else "revoked",
        consented_at=accrual_start_at,
        privacy_version="2026-10-01",
        decided_at=accrual_start_at,
        accrual_start_at=accrual_start_at,
        monthly_from_at=monthly_from_at or accrual_start_at,
        revoked_at=revoked_at,
    )
    db.add(application)
    await db.flush()
    return application


@dataclass
class Player:
    user: User
    payment: Payment


async def _player(db: AsyncSession, *, amount_krw: int, paid: int, bonus: int = 0, free: int = 0) -> Player:
    """결제 하나로 유료(·보너스) 로트를 받은 플레이어. 무료 로트(`free`)는 결제와 무관한 출석 지급이다."""
    user = _make_user(clover_balance=free + bonus + paid)
    db.add(user)
    await db.flush()
    payment = await _make_payment(
        db, user_id=user.id, amount_krw=amount_krw, paid_amount=paid, bonus_amount=bonus, status="paid"
    )
    lots = [
        ("attendance_grant", free, None),
        ("purchase_bonus", bonus, payment.id),
        ("purchase_paid", paid, payment.id),
    ]
    for kind, amount, payment_id in lots:
        if amount:
            db.add(
                CloverLot(user_id=user.id, granted_amount=amount, remaining=amount, kind=kind, payment_id=payment_id)
            )
    await db.flush()
    return Player(user=user, payment=payment)


async def _use(
    db: AsyncSession,
    player: Player,
    content: Content | None,
    amount: int,
    at: datetime,
    *,
    usage: str = "chat",
) -> uuid.UUID:
    """플레이어가 `at` 에 `content` 에서 `amount` 를 쓴다. `usage` 가 `image` 면 사용처 없는 이미지 차감, `preview` 면
    빌더 미리보기다."""
    if usage == "image":
        spent = await spend(db, user_id=player.user.id, amount=amount, kind="image_spend")
    else:
        if usage == "chat":
            assert content is not None
            spend_usage = SpendUsage("chat", content_id=content.id, chat_room_id=uuid.uuid4())
        elif usage == "novel":
            assert content is not None
            spend_usage = SpendUsage("novel", content_id=content.id, novel_id=uuid.uuid4())
        else:
            spend_usage = SpendUsage("preview")
        kind: CloverKind = "novelize_spend" if usage == "novel" else "chat_spend"
        spent = await spend(db, user_id=player.user.id, amount=amount, kind=kind, usage=spend_usage)
        assert spent is not None
        await db.execute(
            update(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id == spent.ledger_id).values(created_at=at)
        )
    assert spent is not None
    return spent.ledger_id


async def _refund(db: AsyncSession, player: Player, ledger_id: uuid.UUID, amount: int, at: datetime) -> None:
    """그 차감에서 `amount` 를 `at` 에 돌려준다(실제 환급 경로 — 배분 역순, 환급 행)."""
    allocation_ids = select(CloverSpendAllocation.id).where(CloverSpendAllocation.spend_ledger_id == ledger_id)
    before = set((await db.scalars(select(CloverSpendRefund.id))).all())
    balance = await refund_spend(
        db, user_id=player.user.id, spend_ledger_id=ledger_id, amount=amount, kind="chat_refund"
    )
    assert balance is not None
    new = [
        refund_id
        for refund_id in (
            await db.scalars(select(CloverSpendRefund.id).where(CloverSpendRefund.allocation_id.in_(allocation_ids)))
        ).all()
        if refund_id not in before
    ]
    assert new
    await db.execute(update(CloverSpendRefund).where(CloverSpendRefund.id.in_(new)).values(created_at=at))


async def _console_cancel(db: AsyncSession, payment: Payment, amount_krw: int, at: datetime) -> None:
    """포트원 콘솔 취소가 `at` 에 성공한 상태를 결제 쪽 기록 방식대로 만든다 — 전액이면 남은 전부, 부분이면 취소액을
    단가로 나눈 수량(올림)까지 유료 먼저 회수하고, 성공 취소 행을 남기고, 결제의 취소 합계를 올린다."""
    full = payment.cancelled_amount_krw + amount_krw >= payment.amount_krw
    need = None if full else -(-amount_krw * payment.paid_amount // payment.amount_krw)
    paid, bonus = await revoke_purchase_lots(db, payment_id=payment.id, limit=need)
    db.add(
        PaymentCancellation(
            payment_id=payment.id,
            source="console",
            status="succeeded",
            amount_krw=amount_krw,
            clawback_paid=paid,
            clawback_bonus=bonus,
            completed_at=at,
        )
    )
    payment.cancelled_amount_krw += amount_krw
    await db.flush()


async def _admin_refund(db: AsyncSession, payment: Payment, amount_krw: int, at: datetime) -> None:
    """어드민 환불이 성공한 상태 — 남은 유료·보너스 전부를 회수하고 견적 금액을 돌려준다."""
    admin = await _create_admin(db)
    paid, bonus = await revoke_purchase_lots(db, payment_id=payment.id)
    db.add(
        PaymentCancellation(
            payment_id=payment.id,
            source="admin",
            status="succeeded",
            amount_krw=amount_krw,
            ratio_percent=100,
            request_received_on=at.date(),
            admin_id=admin["id"],
            clawback_paid=paid,
            clawback_bonus=bonus,
            completed_at=at,
        )
    )
    payment.cancelled_amount_krw += amount_krw
    await db.flush()


async def _monthly(
    db: AsyncSession,
    creator: User,
    month: tuple[datetime, datetime],
    windows: list[tuple[datetime, datetime]] | None = None,
) -> CreatorPayoutConfirmation | None:
    return await confirm_window(
        db,
        creator_id=creator.id,
        kind="monthly",
        period_month=month[0].date(),
        windows=[month] if windows is None else windows,
        cancel_adjust_month=month,
    )


async def _confirmed(db: AsyncSession, creator: User, month: tuple[datetime, datetime]) -> CreatorPayoutConfirmation:
    confirmation = await _monthly(db, creator, month)
    assert confirmation is not None
    return confirmation


async def _lines(db: AsyncSession, confirmation: CreatorPayoutConfirmation) -> list[CreatorPayoutConfirmationLine]:
    return list(
        (
            await db.scalars(
                select(CreatorPayoutConfirmationLine).where(
                    CreatorPayoutConfirmationLine.confirmation_id == confirmation.id
                )
            )
        ).all()
    )


def _d(value: str) -> Decimal:
    return Decimal(value)


# ── 유료·보너스·무료가 섞인 차감, 자기 플레이·미리보기·이미지 제외 ──────────────────────
async def test_counts_only_paid_allocations_of_others_play_on_own_content(db_session: AsyncSession) -> None:
    """B 의 로트는 무료 15·보너스 300·유료 3,300(9,900원). A 작품 방 65(무료 15 + 보너스 50) → 0, A 작품 소설 340(보너스
    250 + 유료 90) → 90, A 작품 방 40 → 40, B 자기 작품 10·미리보기 10·이미지 30 → A 에게 0. A = 130 × 3/22 = 17.7… →
    17원. B 자신의 정산(자기 작품에서 자기가 쓴 10)도 0원이다."""
    a, a_content = await _creator(db_session)
    b = await _player(db_session, amount_krw=9_900, paid=3_300, bonus=300, free=15)
    await _application(db_session, b.user.id, accrual_start_at=kst(9, 1))
    b_content = await _make_draft_content(db_session, creator_user_id=b.user.id)

    await _use(db_session, b, a_content, 65, kst(10, 2))
    await _use(db_session, b, a_content, 340, kst(10, 3), usage="novel")
    await _use(db_session, b, a_content, 40, kst(10, 4))
    await _use(db_session, b, b_content, 10, kst(10, 5))
    await _use(db_session, b, None, 10, kst(10, 6), usage="preview")
    await _use(db_session, b, None, 30, kst(10, 7), usage="image")

    a_row = await _confirmed(db_session, a, OCT)
    assert (a_row.gross_units, a_row.refunded_units, a_row.amount_krw) == (130, 0, 17)
    assert a_row.exact_krw == _d("17.7272727273")
    assert a_row.rate_bps == 500
    [line] = await _lines(db_session, a_row)
    assert (line.content_id, line.payment_id, line.net_units) == (a_content.id, b.payment.id, 130)

    b_row = await _confirmed(db_session, b.user, OCT)
    assert (b_row.gross_units, b_row.amount_krw) == (0, 0)


# ── 부분 환급, 월을 넘는 환급, 음수 달 ────────────────────────────────────────
async def test_refunds_count_in_the_month_they_happen_and_negative_month_truncates_toward_zero(
    db_session: AsyncSession,
) -> None:
    """D(3,300원·유료 1,100). 10월: 채팅 120, AI 수정 20 을 2분 뒤 전액 환급, 10-31 23:50 연쇄 240 선차감을 11-01 00:30
    에 80 환급. 10월 순 360 → 49.09 → 49원, 11월 −80 → −10.909 → −10원(0 쪽으로 버림). 합 39원."""
    c, content = await _creator(db_session)
    d = await _player(db_session, amount_krw=3_300, paid=1_100)

    for turn in range(12):
        await _use(db_session, d, content, 10, kst(10, 12, 9, turn))
    edit = await _use(db_session, d, content, 20, kst(10, 15, 10), usage="novel")
    await _refund(db_session, d, edit, 20, kst(10, 15, 10, 2))
    chain = await _use(db_session, d, content, 240, kst(10, 31, 23, 50), usage="novel")
    await _refund(db_session, d, chain, 80, kst(11, 1, 0, 30))

    october = await _confirmed(db_session, c, OCT)
    november = await _confirmed(db_session, c, NOV)

    assert (october.gross_units, october.refunded_units, october.amount_krw) == (380, 20, 49)
    assert (november.gross_units, november.refunded_units, november.amount_krw) == (0, 80, -10)
    assert november.exact_krw == _d("-10.9090909091")
    [line] = await _lines(db_session, november)
    assert line.net_units == -80


# ── 결제별 상한 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("cancel", "expected_krw"),
    [
        pytest.param(("console", 6_600), 81, id="console-6600-cap-1100-factor-1"),
        pytest.param(("console", 8_910), 45, id="console-8910-cap-330-factor-0.55"),
        pytest.param(("console", 9_900), 0, id="console-full-cap-0"),
        pytest.param(("admin", 7_200), 81, id="admin-refund-cap-900-factor-1"),
    ],
)
async def test_payment_cap_scales_creator_share_by_remaining_payment(
    db_session: AsyncSession, cancel: tuple[str, int], expected_krw: int
) -> None:
    """E(9,900원·유료 3,300·보너스 300)가 F 작품에서 10월에 900(보너스 300 + 유료 600)을 쓰고 11-02 에 결제가 취소된 뒤
    11-03 에 10월을 확정한다. 상한 = (9,900 − 취소액) × 3,300 / 9,900, 계수 = min(1, 상한 / 600)."""
    f, content = await _creator(db_session)
    e = await _player(db_session, amount_krw=9_900, paid=3_300, bonus=300)
    await _use(db_session, e, content, 900, kst(10, 10))

    source, amount = cancel
    if source == "console":
        await _console_cancel(db_session, e.payment, amount, kst(11, 2))
    else:
        await _admin_refund(db_session, e.payment, amount, kst(11, 2))

    october = await _confirmed(db_session, f, OCT)
    assert october.amount_krw == expected_krw
    assert october.gross_units == 600


# ── 정수 경계 ────────────────────────────────────────────────────────────
async def test_exactly_integer_share_is_not_lost_to_division(db_session: AsyncSession) -> None:
    """무료 8 + 유료 2 로 10, 이어 유료 10 두 번 → 유료 22 → 22 × 3/22 = 정확히 3원."""
    creator, content = await _creator(db_session)
    player = await _player(db_session, amount_krw=9_900, paid=3_300, free=8)
    for day in (1, 2, 3):
        await _use(db_session, player, content, 10, kst(10, day))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.gross_units, october.amount_krw, october.exact_krw) == (22, 3, _d("3"))


async def test_integer_share_through_repeating_factor_is_not_truncated_below(db_session: AsyncSession) -> None:
    """계수가 끝나지 않는 소수일 때도 참값이 정수면 그 정수다. 9,900원·유료 3,300 에서 990 을 쓰고(작가 작품 660, 남의
    작품 330) 8,910원 콘솔 취소 → 상한 330, 계수 330/990 = 1/3. 작가 몫 = 660 × 3/22 × 1/3 = 정확히 30원. 계수가 소수
    20자리에서 끊겨 나눗셈 결과는 29.999…97 이므로 10자리 반올림이 없으면 29원이 된다."""
    creator, content = await _creator(db_session)
    _, other_content = await _creator(db_session)
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, player, content, 660, kst(10, 1))
    await _use(db_session, player, other_content, 330, kst(10, 2))
    await _console_cancel(db_session, player.payment, 8_910, kst(10, 20))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.amount_krw, october.exact_krw) == (30, _d("30"))


# ── 소급과 첫 월 확정의 구간 경계 ──────────────────────────────────────────────
async def test_retro_and_first_monthly_split_at_cut_without_overlap(db_session: AsyncSession) -> None:
    """승인 12-10 12:00, 컷 C = 11:55. 소급 [C − 90일, C), 12월 [C, 01-01). C − 1초 → 소급, C 정각 → 12월, C − 90일 −
    1초 → 어디에도 없음, 12-05 → 소급에만. 사용은 각 22(= 3원)라 원 단위로 갈린다."""
    cut = kst(12, 10, 11, 55)
    retro_start = cut - timedelta(days=90)
    assert retro_start == kst(9, 11, 11, 55)
    creator, content = await _creator(db_session, accrual_start_at=None)
    await _application(db_session, creator.id, accrual_start_at=retro_start, monthly_from_at=cut)
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, player, content, 22, retro_start - timedelta(seconds=1))
    await _use(db_session, player, content, 22, retro_start)
    await _use(db_session, player, content, 22, kst(12, 5))
    await _use(db_session, player, content, 22, cut - timedelta(seconds=1))
    await _use(db_session, player, content, 22, cut)

    retro = await confirm_window(
        db_session,
        creator_id=creator.id,
        kind="retro",
        period_month=None,
        windows=[(retro_start, cut)],
        cancel_adjust_month=None,
    )
    december = await _monthly(db_session, creator, DEC, windows=[(cut, DEC[1])])

    assert retro is not None and december is not None
    assert (retro.gross_units, retro.amount_krw) == (66, 9)
    assert (retro.window_start, retro.window_end) == (retro_start, cut)
    assert (december.gross_units, december.amount_krw) == (22, 3)
    assert (december.window_start, december.window_end) == (cut, DEC[1])


# ── 확정 뒤 콘솔 취소 ─────────────────────────────────────────────────────────
async def _october_confirmed_before_cancel(db: AsyncSession) -> tuple[User, Content, Player]:
    """E(9,900원·유료 3,300·보너스 300)가 F 작품에서 10월에 유료 600(보너스 300 먼저)을 쓰고, 10월을 계수 1 로 확정."""
    f, content = await _creator(db)
    e = await _player(db, amount_krw=9_900, paid=3_300, bonus=300)
    await _use(db, e, content, 900, kst(10, 10))
    october = await _confirmed(db, f, OCT)
    assert (october.amount_krw, october.exact_krw) == (81, _d("81.8181818182"))
    [line] = await _lines(db, october)
    assert (line.net_units, line.exact_krw, line.cancel_adjust_krw) == (600, _d("81.8181818182"), _d("0"))
    return f, content, e


async def test_cancel_after_confirmation_readjusts_prior_share_every_month(db_session: AsyncSession) -> None:
    """11-10 콘솔 부분 취소 8,910원 → 계수 0.55. 11월에 G(취소 없는 결제)가 F 작품에서 유료 50. 11월 = G 6.818… + E 조정
    (45 − 81.818…) = −30.000… → −30원. 12-05 나머지 990원 취소(계수 0) → 12월 조정 = 0 − 45 = −45원. 잔액 81 − 30 − 45 =
    6원 = G 몫의 버림."""
    f, content, e = await _october_confirmed_before_cancel(db_session)
    await _console_cancel(db_session, e.payment, 8_910, kst(11, 10))
    g = await _player(db_session, amount_krw=900, paid=300)
    await _use(db_session, g, content, 50, kst(11, 15))

    november = await _confirmed(db_session, f, NOV)
    assert (november.amount_krw, november.exact_krw) == (-30, _d("-30"))
    lines = {line.payment_id: line for line in await _lines(db_session, november)}
    assert (lines[e.payment.id].net_units, lines[e.payment.id].cancel_adjust_krw) == (0, _d("-36.8181818182"))
    assert (lines[g.payment.id].net_units, lines[g.payment.id].exact_krw) == (50, _d("6.8181818182"))

    await _console_cancel(db_session, e.payment, 990, kst(12, 5))
    december = await _confirmed(db_session, f, DEC)
    assert (december.amount_krw, december.exact_krw) == (-45, _d("-45"))
    assert 81 + november.amount_krw + december.amount_krw == 6


async def test_cancel_succeeding_after_month_end_adjusts_older_lines_next_month(db_session: AsyncSession) -> None:
    """위와 같은 10월에서 8,910원 취소가 12-02(11월이 끝난 뒤, 11월 확정 전)에 성공하고 나머지 취소는 없다. 11월 확정은 그 결제의
    10월 줄을 건드리지 않아 G 몫만 → 6원. 12월 확정이 10월 줄을 맞춘다: 45 − 81.818… → −36원. 누계 81 + 6 − 36 = 51원."""
    f, content, e = await _october_confirmed_before_cancel(db_session)
    g = await _player(db_session, amount_krw=900, paid=300)
    await _use(db_session, g, content, 50, kst(11, 15))
    await _console_cancel(db_session, e.payment, 8_910, kst(12, 2))

    november = await _confirmed(db_session, f, NOV)
    assert (november.amount_krw, november.exact_krw) == (6, _d("6.8181818182"))
    december = await _confirmed(db_session, f, DEC)
    assert (december.amount_krw, december.exact_krw) == (-36, _d("-36.8181818182"))


# ── 취소 뒤 환급, 그 클로버를 다른 달에 재사용 ─────────────────────────────────────
async def test_reused_refund_after_cancel_does_not_exceed_payment_cap(db_session: AsyncSession) -> None:
    """11-10 취소(계수 0.55) 뒤 11-20 에 10월 사용 100 이 환급돼 계수 0.66. 11월 = −9.0 + (54 − 81.818…) → −36원. 12월에
    E 가 돌려받은 100 을 F 작품에서 다시 써 계수 0.55, 취소 없는 달이어도 조정 대상이다: 7.5 + (37.5 − 45) = 0원. 누계
    exact 45.0 = 상한 330 × 3/22, 원 단위 81 − 36 + 0 = 45원."""
    f, content, e = await _october_confirmed_before_cancel(db_session)
    october_spend = await db_session.scalar(
        select(CloverSpendUsage.spend_ledger_id).where(CloverSpendUsage.spender_user_id == e.user.id)
    )
    assert october_spend is not None
    await _console_cancel(db_session, e.payment, 8_910, kst(11, 10))
    await _refund(db_session, e, october_spend, 100, kst(11, 20))

    november = await _confirmed(db_session, f, NOV)
    [nov_line] = await _lines(db_session, november)
    assert (nov_line.net_units, nov_line.cancel_adjust_krw, nov_line.exact_krw) == (
        -100,
        _d("-27.8181818182"),
        _d("-36.8181818182"),
    )
    assert (november.refunded_units, november.amount_krw) == (100, -36)

    await _use(db_session, e, content, 100, kst(12, 10))
    december = await _confirmed(db_session, f, DEC)
    [dec_line] = await _lines(db_session, december)
    assert (dec_line.net_units, dec_line.cancel_adjust_krw, dec_line.exact_krw) == (100, _d("-7.5"), _d("0"))
    assert (december.amount_krw, december.exact_krw) == (0, _d("0"))

    total_exact = await db_session.scalar(
        select(func.sum(CreatorPayoutConfirmation.exact_krw)).where(CreatorPayoutConfirmation.user_id == f.id)
    )
    assert total_exact == _d("45")


async def test_factor_rising_after_capped_confirmation_never_adds_positive_adjustment(
    db_session: AsyncSession,
) -> None:
    """10-20 콘솔 취소 8,910원 뒤 10월 확정 → 계수 0.55 로 45원. 11-20 에 그 사용 100 이 환급돼 계수 0.66. 11월 = 환급 몫
    −100 × 0.66 × 3/22 = −9.0, 조정은 54 − 45 = +9 지만 양수는 반영하지 않아 0 → −9원."""
    f, content = await _creator(db_session)
    e = await _player(db_session, amount_krw=9_900, paid=3_300, bonus=300)
    ledger_id = await _use(db_session, e, content, 900, kst(10, 10))
    await _console_cancel(db_session, e.payment, 8_910, kst(10, 20))
    october = await _confirmed(db_session, f, OCT)
    assert (october.amount_krw, october.exact_krw) == (45, _d("45"))

    await _refund(db_session, e, ledger_id, 100, kst(11, 20))
    november = await _confirmed(db_session, f, NOV)
    [line] = await _lines(db_session, november)
    assert (line.cancel_adjust_krw, line.exact_krw) == (_d("0"), _d("-9"))
    assert november.amount_krw == -9


# ── 적립 구간 ───────────────────────────────────────────────────────────────────
async def test_owner_withdrawn_before_use_is_excluded_after_use_is_kept(db_session: AsyncSession) -> None:
    """소유자가 10-20 에 탈퇴했다. 10-15 사용(22)은 들어가고 10-25 사용(22)은 빠진다."""
    creator, content = await _creator(db_session)
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, player, content, 22, kst(10, 15))
    await _use(db_session, player, content, 22, kst(10, 25))
    creator.deleted_at = kst(10, 20)
    await db_session.flush()

    october = await _confirmed(db_session, creator, OCT)
    assert (october.gross_units, october.amount_krw) == (22, 3)


async def test_refund_of_spend_before_accrual_is_not_subtracted(db_session: AsyncSession) -> None:
    """적립은 10-10 부터다. 10-05 사용(적립 전)의 10-15 환급은 더한 적이 없으므로 빼지 않는다. 10-12 사용 44 → 6원."""
    creator, content = await _creator(db_session, accrual_start_at=kst(10, 10))
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    before = await _use(db_session, player, content, 44, kst(10, 5))
    await _use(db_session, player, content, 44, kst(10, 12))
    await _refund(db_session, player, before, 44, kst(10, 15))

    october = await _monthly(db_session, creator, OCT, windows=[(kst(10, 10), OCT[1])])
    assert october is not None
    assert (october.gross_units, october.refunded_units, october.amount_krw) == (44, 0, 6)


async def test_two_windows_in_a_month_skip_the_gap_and_insert_one_row(db_session: AsyncSession) -> None:
    """12-05 승인 취소, 12-20 재승인. 구간 [12-01, 12-05)·[12-20, 01-01). 12-03 사용 44 와 12-25 사용 22 는 들어가고, 틈의
    12-10 사용 22 와 12-03 사용을 12-10 에 22 환급한 것은 빠진다. 확정 행 하나, (작품, 결제) 줄 하나: 66 → 9원."""
    creator, content = await _creator(db_session, accrual_start_at=None)
    await _application(db_session, creator.id, accrual_start_at=kst(9, 1), revoked_at=kst(12, 5))
    await _application(db_session, creator.id, accrual_start_at=kst(12, 20))
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    early = await _use(db_session, player, content, 44, kst(12, 3))
    await _use(db_session, player, content, 22, kst(12, 10))
    await _refund(db_session, player, early, 22, kst(12, 10))
    await _use(db_session, player, content, 22, kst(12, 25))

    december = await _monthly(db_session, creator, DEC, windows=[(DEC[0], kst(12, 5)), (kst(12, 20), DEC[1])])
    assert december is not None
    assert (december.gross_units, december.refunded_units, december.amount_krw) == (66, 0, 9)
    assert (december.window_start, december.window_end) == (DEC[0], DEC[1])
    [line] = await _lines(db_session, december)
    assert line.net_units == 66


async def test_integer_total_over_several_lines_is_not_lost_to_per_line_rounding(db_session: AsyncSession) -> None:
    """세 플레이어가 각자 결제로 18·18·8 을 써 줄이 셋이다: 54/22 + 54/22 + 24/22 = 132/22 = 정확히 6원. 줄을 먼저 10자리로
    맞추면 2.4545454545 + 2.4545454545 + 1.0909090909 = 5.9999999999 → 5원이 되므로, 합계는 반올림 전 값에서 낸다."""
    creator, content = await _creator(db_session)
    for amount in (18, 18, 8):
        player = await _player(db_session, amount_krw=9_900, paid=3_300)
        await _use(db_session, player, content, amount, kst(10, 5))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.gross_units, october.amount_krw, october.exact_krw) == (44, 6, _d("6"))
    assert sorted(line.exact_krw for line in await _lines(db_session, october)) == [
        _d("1.0909090909"),
        _d("2.4545454545"),
        _d("2.4545454545"),
    ]


async def test_adjustment_against_several_rounded_prior_lines_keeps_integer_total(db_session: AsyncSession) -> None:
    """E 가 10월에 F 의 두 작품에 15 씩 써 줄이 둘(각 45/22 = 2.04545…, 저장값 2.0454545455)이고 10월은 4원이다. 11-10
    전액 콘솔 취소(계수 0)로 두 줄을 저장값만큼 되돌리고, G 가 11월에 96 을 쓴다. 11월 참값 = (96 − 30) × 3/22 = 정확히
    9원 — 저장값의 반올림 오차가 조정 줄 둘에 넘어와도 8원이 되지 않는다. 누계 13원 = G 몫 13.09… 의 버림."""
    f, x = await _creator(db_session)
    y = await _make_draft_content(db_session, creator_user_id=f.id)
    e = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, e, x, 15, kst(10, 5))
    await _use(db_session, e, y, 15, kst(10, 6))
    october = await _confirmed(db_session, f, OCT)
    assert october.amount_krw == 4

    await _console_cancel(db_session, e.payment, 9_900, kst(11, 10))
    g = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, g, x, 96, kst(11, 15))
    november = await _confirmed(db_session, f, NOV)
    assert november.amount_krw == 9
    assert len(await _lines(db_session, november)) == 3


async def test_true_fraction_just_below_an_integer_is_still_truncated(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정수 아래로 가장 가까운 정당한 원 미만도 버린다. 비율 1bps 에서 유료 3,666 = 3 × 3,666 / 11,000 = 0.99981818… →
    0원(정수에서 1/11000 떨어져 있어, 버리기 전 맞추는 자리가 이보다 거칠면 1원으로 올라간다)."""
    monkeypatch.setattr(config.settings, "creator_payout_rate_bps", 1)
    creator, content = await _creator(db_session)
    player = await _player(db_session, amount_krw=11_001, paid=3_667)
    await _use(db_session, player, content, 3_666, kst(10, 5))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.amount_krw, october.exact_krw) == (0, _d("0.9998181818"))


async def test_window_end_is_the_latest_end_even_if_an_earlier_window_ends_later(db_session: AsyncSession) -> None:
    creator, _content = await _creator(db_session)
    december = await _monthly(db_session, creator, DEC, windows=[(DEC[0], DEC[1]), (kst(12, 10), kst(12, 20))])
    assert december is not None
    assert (december.window_start, december.window_end) == DEC


async def test_fully_refunded_payment_leaves_no_line_but_counts_on_the_row(db_session: AsyncSession) -> None:
    """P 가 22 를 쓰고, Q 가 20 을 써 같은 달에 전액 돌려받았다. Q 결제의 (작품, 결제)는 순사용도 금액도 0 이라 줄을 넣지
    않지만, 확정 행의 차감·환급 합에는 들어간다: gross 42, refunded 20, 3원, 줄은 P 결제 하나."""
    creator, content = await _creator(db_session)
    p = await _player(db_session, amount_krw=9_900, paid=3_300)
    q = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, p, content, 22, kst(10, 5))
    refunded = await _use(db_session, q, content, 20, kst(10, 6))
    await _refund(db_session, q, refunded, 20, kst(10, 6, 0, 1))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.gross_units, october.refunded_units, october.amount_krw) == (42, 20, 3)
    assert [line.payment_id for line in await _lines(db_session, october)] == [p.payment.id]


async def test_overlapping_windows_count_a_spend_once(db_session: AsyncSession) -> None:
    """재승인 컷이 직전 취소보다 앞서 구간 [12-01, 12-15)·[12-10, 01-01) 이 겹친다. 12-12 사용 22 는 한 번만 → 3원."""
    creator, content = await _creator(db_session)
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, player, content, 22, kst(12, 12))

    december = await _monthly(db_session, creator, DEC, windows=[(DEC[0], kst(12, 15)), (kst(12, 10), DEC[1])])
    assert december is not None
    assert (december.gross_units, december.amount_krw) == (22, 3)


# ── 구간 없는 달·소급의 조정 ─────────────────────────────────────────────────────────
async def test_month_without_windows_inserts_nothing_unless_adjusting(db_session: AsyncSession) -> None:
    """적립 구간이 없는 달(승인 취소된 크리에이터)에 조정할 결제가 없으면 행이 없다. 10월을 계수 1 로 확정한 결제가 11-10 에 콘솔 취소(계수 0.55)되면 조정만
    있는 행이 생기고 구간은 그 달 전체다: −36.818… → −36원."""
    f, _content, e = await _october_confirmed_before_cancel(db_session)
    assert await _monthly(db_session, f, NOV, windows=[]) is None

    await _console_cancel(db_session, e.payment, 8_910, kst(11, 10))
    november = await _monthly(db_session, f, NOV, windows=[])
    assert november is not None
    assert (november.amount_krw, november.gross_units) == (-36, 0)
    assert (november.window_start, november.window_end) == NOV
    [line] = await _lines(db_session, november)
    assert (line.net_units, line.cancel_adjust_krw) == (0, _d("-36.8181818182"))


async def test_retro_never_adjusts_prior_lines(db_session: AsyncSession) -> None:
    """소급(`cancel_adjust_month=None`)은 조정 대상 결제와 앞선 줄이 있어도 조정 줄을 만들지 않는다."""
    f, _content, e = await _october_confirmed_before_cancel(db_session)
    await _console_cancel(db_session, e.payment, 8_910, kst(11, 10))

    retro = await confirm_window(
        db_session,
        creator_id=f.id,
        kind="retro",
        period_month=None,
        windows=[(kst(11, 11), kst(11, 12))],
        cancel_adjust_month=None,
    )
    assert retro is not None
    assert retro.amount_krw == 0
    assert await _lines(db_session, retro) == []


async def test_confirm_without_window_or_month_is_rejected(db_session: AsyncSession) -> None:
    creator, _content = await _creator(db_session)
    with pytest.raises(ValueError):
        await confirm_window(
            db_session, creator_id=creator.id, kind="retro", period_month=None, windows=[], cancel_adjust_month=None
        )


# ── 사용처 종류 ──────────────────────────────────────────────────────────────────
async def test_refund_follows_usage_kind_filter_not_the_lot(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정산 종류에서 빠진 사용은 그 환급도 빠진다 — 환급을 배분·로트로만 모으면 같은 유료 로트에서 나간 다른 종류 사용의
    환급이 정산액을 깎는다. 지금 정산 밖 종류(앞으로 생길 열람 사용 등)는 사용처 CHECK 가 받지 않으므로, 정산 종류를
    채팅 하나로 좁혀 소설 사용을 "정산 밖 종류"로 세운다: 채팅 44 + 소설 44(10-07 에 22 환급) → 채팅 44 → 6원."""
    assert settlement.SETTLED_USAGE_KINDS == ("chat", "novel")
    monkeypatch.setattr(settlement, "SETTLED_USAGE_KINDS", ("chat",))
    creator, content = await _creator(db_session)
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, player, content, 44, kst(10, 5))
    novel = await _use(db_session, player, content, 44, kst(10, 6), usage="novel")
    await _refund(db_session, player, novel, 22, kst(10, 7))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.gross_units, october.refunded_units, october.amount_krw) == (44, 0, 6)


async def test_refund_of_spend_without_usage_from_same_lot_is_ignored(db_session: AsyncSession) -> None:
    """같은 유료 로트에서 나간 이미지 차감(사용처 없음)의 환급은 작가 정산을 바꾸지 않는다. 채팅 44 → 6원."""
    creator, content = await _creator(db_session)
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, player, content, 44, kst(10, 5))
    image = await _use(db_session, player, None, 30, kst(10, 6), usage="image")
    await _refund(db_session, player, image, 30, kst(10, 7))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.refunded_units, october.amount_krw) == (0, 6)


async def test_rate_comes_from_settings_at_call_time(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """비율을 1,000bps 로 바꾸면 유료 22 → 6원이고, 확정 행에 그 비율이 남는다."""
    monkeypatch.setattr(config.settings, "creator_payout_rate_bps", 1_000)
    creator, content = await _creator(db_session)
    player = await _player(db_session, amount_krw=9_900, paid=3_300)
    await _use(db_session, player, content, 22, kst(10, 5))

    october = await _confirmed(db_session, creator, OCT)
    assert (october.rate_bps, october.amount_krw) == (1_000, 6)


# ── 멱등 유니크 ──────────────────────────────────────────────────────────────────
async def test_same_month_cannot_be_confirmed_twice(db_session: AsyncSession) -> None:
    creator, _content = await _creator(db_session)
    await _confirmed(db_session, creator, OCT)
    with pytest.raises(IntegrityError, match="ux_creator_payout_confirmations_monthly"):
        await _monthly(db_session, creator, OCT)


async def test_retro_cannot_be_confirmed_twice(db_session: AsyncSession) -> None:
    """소급은 크리에이터당 한 번이다 — 승인 취소 뒤 재승인해도 다시 소급하지 않는다."""
    creator, _content = await _creator(db_session)

    async def retro() -> CreatorPayoutConfirmation | None:
        return await confirm_window(
            db_session,
            creator_id=creator.id,
            kind="retro",
            period_month=None,
            windows=[(kst(9, 1), kst(10, 1))],
            cancel_adjust_month=None,
        )

    assert await retro() is not None
    with pytest.raises(IntegrityError, match="ux_creator_payout_confirmations_retro"):
        await retro()


# ── 설정 ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("env", "value"),
    [
        pytest.param({"CREATOR_PAYOUT_RATE_BPS": ""}, (500, 90), id="empty-is-default"),
        pytest.param({"CREATOR_PAYOUT_RATE_BPS": "10000", "CREATOR_PAYOUT_RETRO_DAYS": "1"}, (10_000, 1), id="bounds"),
    ],
)
def test_creator_payout_settings_accept(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], value: tuple[int, int]
) -> None:
    for key, raw in env.items():
        monkeypatch.setenv(key, raw)
    loaded = config.Settings()
    assert (loaded.creator_payout_rate_bps, loaded.creator_payout_retro_days) == value


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"CREATOR_PAYOUT_RATE_BPS": "0"}, id="rate-zero"),
        pytest.param({"CREATOR_PAYOUT_RATE_BPS": "10001"}, id="rate-over-100-percent"),
        pytest.param({"CREATOR_PAYOUT_RETRO_DAYS": "0"}, id="retro-zero"),
    ],
)
def test_creator_payout_settings_reject_out_of_range(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    """범위 밖이면 기동하지 않는다. 소급 0일은 소급 구간이 비어 확정 행의 구간 CHECK 에 걸리므로 막는다."""
    for key, raw in env.items():
        monkeypatch.setenv(key, raw)
    with pytest.raises(ValueError):
        config.Settings()


# ── 신청 CHECK·부분 유니크 ─────────────────────────────────────────────────────────
async def _insert_application(db: AsyncSession, user_id: uuid.UUID, **overrides: object) -> None:
    """정상 `approved` 신청을 기본값으로, `overrides` 로 칸을 틀어 넣는다."""
    values: dict[str, object] = {
        "user_id": user_id,
        "status": "approved",
        "consented_at": kst(10, 1),
        "privacy_version": "2026-10-01",
        "decided_at": kst(10, 2),
        "accrual_start_at": kst(7, 1),
        "monthly_from_at": kst(10, 2),
    }
    values.update(overrides)
    db.add(CreatorPayoutApplication(**values))
    await db.flush()


async def _bare_user(db: AsyncSession) -> User:
    user = _make_user()
    db.add(user)
    await db.flush()
    return user


_PENDING: dict[str, object] = {
    "status": "pending",
    "decided_at": None,
    "accrual_start_at": None,
    "monthly_from_at": None,
}
_REVOKED: dict[str, object] = {"status": "revoked", "revoked_at": kst(10, 20)}
_REJECTED: dict[str, object] = {"status": "rejected", "accrual_start_at": None, "monthly_from_at": None}


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="approved"),
        pytest.param(_PENDING, id="pending"),
        pytest.param(_REJECTED, id="rejected"),
        pytest.param(_REVOKED, id="revoked"),
        pytest.param({"accrual_start_at": kst(10, 2)}, id="reapproved-accrual-equals-monthly-from"),
    ],
)
async def test_valid_application_is_accepted(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    """대조군 — 아래 거부들이 셋업 탓이 아니라 그 값 탓임을 보인다."""
    await _insert_application(db_session, (await _bare_user(db_session)).id, **overrides)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({**_REJECTED, "status": "open"}, "ck_creator_payout_applications_status", id="unknown-status"),
        pytest.param(
            {**_PENDING, "decided_at": kst(10, 2)}, "ck_creator_payout_applications_decided", id="pending-decided"
        ),
        pytest.param(
            {"accrual_start_at": None}, "ck_creator_payout_applications_accrual", id="approved-without-accrual"
        ),
        pytest.param(
            {"monthly_from_at": None}, "ck_creator_payout_applications_monthly_from", id="approved-without-monthly-from"
        ),
        pytest.param(
            {"accrual_start_at": kst(10, 3)},
            "ck_creator_payout_applications_monthly_from",
            id="accrual-after-monthly-from",
        ),
        pytest.param({"status": "revoked"}, "ck_creator_payout_applications_revoked", id="revoked-without-revoked-at"),
    ],
)
async def test_application_check_constraints_reject(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    user = await _bare_user(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        await _insert_application(db_session, user.id, **overrides)


@pytest.mark.parametrize(
    ("first", "second", "rejected"),
    [
        pytest.param(_PENDING, _PENDING, True, id="pending-pending"),
        pytest.param(_REJECTED, _PENDING, False, id="rejected-then-pending"),
        pytest.param(_REVOKED, {}, False, id="revoked-then-approved"),
    ],
)
async def test_one_live_application_per_user(
    db_session: AsyncSession, first: dict[str, object], second: dict[str, object], rejected: bool
) -> None:
    user = await _bare_user(db_session)
    await _insert_application(db_session, user.id, **first)
    if rejected:
        with pytest.raises(IntegrityError, match="ux_creator_payout_applications_user_id_live"):
            await _insert_application(db_session, user.id, **second)
    else:
        await _insert_application(db_session, user.id, **second)


# ── 확정·내역 CHECK·유니크 ────────────────────────────────────────────────────────
async def _insert_confirmation(db: AsyncSession, user_id: uuid.UUID, **overrides: object) -> CreatorPayoutConfirmation:
    """정상 월 확정 행을 기본값으로, `overrides` 로 칸을 틀어 넣는다."""
    values: dict[str, object] = {
        "user_id": user_id,
        "kind": "monthly",
        "period_month": date(2026, 10, 1),
        "window_start": OCT[0],
        "window_end": OCT[1],
        "gross_units": 0,
        "refunded_units": 0,
        "rate_bps": 500,
        "exact_krw": Decimal(0),
        "amount_krw": 0,
    }
    values.update(overrides)
    confirmation = CreatorPayoutConfirmation(**values)
    db.add(confirmation)
    await db.flush()
    return confirmation


_RETRO: dict[str, object] = {"kind": "retro", "period_month": None}


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({**_RETRO, "kind": "weekly"}, "ck_creator_payout_confirmations_kind", id="unknown-kind"),
        pytest.param(
            {"period_month": None}, "ck_creator_payout_confirmations_period_month", id="monthly-without-month"
        ),
        pytest.param({"kind": "retro"}, "ck_creator_payout_confirmations_period_month", id="retro-with-month"),
        pytest.param({"window_end": OCT[0]}, "ck_creator_payout_confirmations_window", id="empty-window"),
        pytest.param({"gross_units": -1}, "ck_creator_payout_confirmations_units_non_negative", id="negative-gross"),
        pytest.param(
            {"refunded_units": -1}, "ck_creator_payout_confirmations_units_non_negative", id="negative-refunded"
        ),
        pytest.param({"rate_bps": 0}, "ck_creator_payout_confirmations_rate_bps", id="rate-zero"),
        pytest.param({"rate_bps": 10_001}, "ck_creator_payout_confirmations_rate_bps", id="rate-over"),
    ],
)
async def test_confirmation_check_constraints_reject(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    user = await _bare_user(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        await _insert_confirmation(db_session, user.id, **overrides)


@pytest.mark.parametrize(
    ("first", "second", "constraint"),
    [
        pytest.param({}, {}, "ux_creator_payout_confirmations_monthly", id="monthly-same-month"),
        pytest.param(_RETRO, _RETRO, "ux_creator_payout_confirmations_retro", id="retro-twice"),
        pytest.param(_RETRO, {}, None, id="retro-and-monthly-same-month"),
        pytest.param(
            {}, {"period_month": date(2026, 11, 1), "window_start": NOV[0], "window_end": NOV[1]}, None, id="next-month"
        ),
    ],
)
async def test_confirmation_uniqueness(
    db_session: AsyncSession, first: dict[str, object], second: dict[str, object], constraint: str | None
) -> None:
    user = await _bare_user(db_session)
    await _insert_confirmation(db_session, user.id, **first)
    if constraint is None:
        await _insert_confirmation(db_session, user.id, **second)
    else:
        with pytest.raises(IntegrityError, match=constraint):
            await _insert_confirmation(db_session, user.id, **second)


async def test_confirmation_line_key_is_confirmation_content_payment(db_session: AsyncSession) -> None:
    """같은 확정·작품의 다른 결제 줄은 들어가고, 같은 (확정, 작품, 결제) 두 번째 줄은 복합 PK 에 막힌다."""
    creator, content = await _creator(db_session)
    confirmation = await _insert_confirmation(db_session, creator.id)
    payments = [await _make_payment(db_session, user_id=creator.id) for _ in range(2)]

    def line(payment: Payment) -> CreatorPayoutConfirmationLine:
        return CreatorPayoutConfirmationLine(
            confirmation_id=confirmation.id,
            content_id=content.id,
            payment_id=payment.id,
            net_units=22,
            cancel_adjust_krw=Decimal(0),
            exact_krw=Decimal(3),
        )

    db_session.add_all([line(payments[0]), line(payments[1])])
    await db_session.flush()
    db_session.expunge_all()
    db_session.add(line(payments[0]))
    with pytest.raises(IntegrityError, match="creator_payout_confirmation_lines_pkey"):
        await db_session.flush()


async def test_confirmation_line_rejects_positive_cancel_adjustment(db_session: AsyncSession) -> None:
    creator, content = await _creator(db_session)
    confirmation = await _insert_confirmation(db_session, creator.id)
    payment = await _make_payment(db_session, user_id=creator.id)
    db_session.add(
        CreatorPayoutConfirmationLine(
            confirmation_id=confirmation.id,
            content_id=content.id,
            payment_id=payment.id,
            net_units=0,
            cancel_adjust_krw=Decimal("0.0000000001"),
            exact_krw=Decimal("0.0000000001"),
        )
    )
    with pytest.raises(IntegrityError, match="ck_creator_payout_confirmation_lines_cancel_adjust"):
        await db_session.flush()
