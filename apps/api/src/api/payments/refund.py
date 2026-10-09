"""어드민 환불과 포트원 취소 대사.

**환불 시도의 멱등 단위는 그 결제의 `requested` 취소 행이다**(한 결제에 하나뿐 — 부분 유니크). 클라이언트 키를 두지
않는다: 행이 DB 에 있으므로 다이얼로그를 닫았다 열어도, 다른 어드민이 눌러도 같은 시도를 이어받는다.

실행 순서는 DB → 포트원 → DB 다.
1. 결제 행을 잠그고, 사용자 행을 잠근 채 견적을 다시 계산하고, **그 구매의 남은 유료·보너스를 회수**하고, `requested`
   행과 감사 기록을 쓰고 커밋한다. 회수를 포트원 호출 앞에 두는 이유: 뒤에 두면 호출 중·결과 모름 구간에 사용자가 환불
   대상 유료를 다 쓰고도 돈을 받는다. 앞에 두면 그 구간의 최악은 "돈은 아직인데 클로버도 없다"이고, 확정 결과가 오면
   성공(그대로) 또는 복원으로 반드시 끝난다. DB 를 먼저 쓰는 이유: 포트원 취소가 성공한 뒤 DB 쓰기가 실패해도 `requested`
   행이 남아 대사가 정확히 그 건으로 마무리한다(포트원을 먼저 부르면 돈이 나간 흔적이 우리 쪽에 하나도 없다).
2. 잠금 없이 포트원 취소를 부른다.
3. 결제 행을 다시 잠그고 포트원이 돌려준 취소를 대사와 같은 함수로 반영한다 — 그사이 웹훅이 먼저 반영했으면 취소 id 로
   맞아 아무것도 하지 않는다.

`payments.cancelled_amount_krw` 는 그 결제의 `succeeded` 행 금액 합으로만 정한다(누적하지 않는다). 어드민 경로와 웹훅이 같은
취소를 반영해도 행이 하나라 합이 하나다.

락 순서는 payments → users → clover_lots 로 지급과 같다.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from portone_server_sdk.payment import (
    CancelledPayment,
    FailedPaymentCancellation,
    PaidPayment,
    PartialCancelledPayment,
    Payment as PortOnePayment,
    PaymentCancellation as PortOneCancellation,
    RequestedPaymentCancellation,
    SucceededPaymentCancellation,
)
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.admin.action_log import record_admin_action
from api.core.clover import restore_purchase_lots, revoke_purchase_lots
from api.core.rate_limit import KST
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.clover import CloverLot, CloverSpendAllocation
from api.db.models.payment import Payment, PaymentCancellation, PaymentCancellationStatus
from api.payments import portone
from api.payments.errors import (
    PaymentConsolePartialCancelError,
    PaymentRefundStuckError,
    PortOneCancelRejectedError,
    PortOneUnavailableError,
)
from api.payments.portone import PortOneGateway

logger = logging.getLogger(__name__)

# 접수일이 결제일(KST) 다음 날부터 이 날수째 안이면 전액, 그 뒤는 줄인 비율이다(환불정책).
FULL_REFUND_DAYS = 7
FULL_REFUND_PERCENT = 100
REDUCED_REFUND_PERCENT = 90
# 재시도가 같은 시도를 다시 보내지 않는 시간(초). 포트원 호출 하나의 상한보다 길어야 "첫 전송이 아직 응답을 기다린다"를
# 덮는다 — 상한의 세 배로 둬 DB 왕복·커밋 시간까지 넉넉히 덮는다.
SEND_CLAIM_SECONDS = portone.PORTONE_TIMEOUT_SECONDS * 3
# 포트원에 넘기는 취소 사유. 어드민이 적은 사유는 내부 감사용이라 결제대행사로 보내지 않는다.
PORTONE_CANCEL_REASON = "클로버 구매 환불"

_REFUNDABLE = ("paid", "partially_cancelled")
# 이 거절은 "우리 취소가 이미 처리됐다"일 수 있다(이중 클릭·웹훅 경합). 실패로 확정하기 전에 포트원을 다시 조회한다.
_MAYBE_ALREADY_CANCELLED = frozenset(
    {
        "CancellableAmountConsistencyBrokenError",
        "CancelAmountExceedsCancellableAmountError",
        "PaymentAlreadyCancelledError",
    }
)


def refunded_purchase_lot() -> ColumnElement[bool]:
    """`CloverLot` 이 이미 결제 환불(취소)이 걸린 구매에서 나온 로트인가 — SQL 조건. 그 결제에 진행 중(`requested`)이거나
    성공한(`succeeded`) 취소 행이 하나라도 있으면 참이다. 진행 중도 넣는 이유: 그 시도는 이미 남은 클로버를 회수했고 포트원
    결과만 기다리는 중이라, 이 사이에 로트로 클로버를 되돌리면 취소가 성공했을 때 돈과 클로버를 함께 돌려받는다. 실패로
    확정된 취소(`failed`)만 있는 결제는 환불되지 않은 결제다. 무료 지급 로트는 결제가 없어 늘 거짓이다.

    노벨 삭제 환급이 `refund_spend(skip_lot=…)` 로 넘겨, 결제 환불된 구매분에서 나간 몫을 다시 돌려주지 않게 한다."""
    return exists(
        select(PaymentCancellation.id).where(
            PaymentCancellation.payment_id == CloverLot.payment_id,
            PaymentCancellation.status.in_(("requested", "succeeded")),
        )
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def kst_today() -> date:
    """오늘(KST). 접수일 검증의 상한이다. 테스트는 `_utcnow` 를 바꿔 처리일을 고정한다."""
    return _utcnow().astimezone(KST).date()


class RefundRefusedError(Exception):
    """환불을 시작하지 않았다(아무것도 쓰지 않았다). 라우트가 `status_code` 와 `code` 로 응답한다."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class RefundQuote:
    refund_krw: int
    ratio_percent: int
    paid_remaining: int
    bonus_used: int
    clawback_paid: int
    clawback_bonus: int
    cancellable_krw: int
    paid_at: datetime


@dataclass(frozen=True)
class RefundOutcome:
    """환불 시도 행의 지금 상태와, 응답 뒤 디스코드로 보낼 문구."""

    status: PaymentCancellationStatus
    amount_krw: int
    clawback_paid: int
    clawback_bonus: int
    notifications: tuple[str, ...] = ()


def payment_refunded_message(order: Payment, amount_krw: int) -> str:
    """환불 완료 알림 문구. 결제 완료 알림과 같은 이유로 상품·금액·상태만 싣는다(회원·주문 id 는 조각도 넣지 않는다)."""
    return f"{order.order_name} {amount_krw:,}원 환불 완료"


def refund_ratio_percent(*, paid_on: date, received_on: date, company_fault: bool) -> int:
    """환불 비율. 처리한 날이 아니라 **신청을 받은 날**로 판정한다 — 처리가 늦어져도 제때 신청한 사용자가 손해 보지 않게.
    결제일은 세지 않는다(다음 날이 1일째). 회사 귀책이면 날짜와 무관하게 전액이다."""
    if company_fault or received_on <= paid_on + timedelta(days=FULL_REFUND_DAYS):
        return FULL_REFUND_PERCENT
    return REDUCED_REFUND_PERCENT


def audit_reason(*, received_on: date, company_fault: bool, reason: str) -> str:
    """감사 로그에는 숫자·날짜 칸이 없어 접수일·귀책을 사유 앞머리에 문자열로 남긴다(원본 값은 취소 행에 있다)."""
    tag = f"접수 {received_on.isoformat()}" + (" · 회사 귀책" if company_fault else "")
    return f"[{tag}] {reason}"


async def quote_refund(
    db: AsyncSession, order: Payment, *, received_on: date, company_fault: bool, today: date
) -> RefundQuote:
    """환불 견적: `(남은 유료 − 그 구매에서 쓴 보너스) × 구매 단가 × 비율`, 0원 하한, 취소 가능 잔액 상한.

    쓴 보너스는 차감 배분에서 센다(차감액 − 이미 환급된 몫). `지급량 − 남은 양` 으로 세면 만료·탈퇴 소멸처럼 쓰지 않은
    감소까지 사용으로 잡힌다. 실행 경로는 사용자 행을 잠근 뒤 이 함수를 불러, 견적의 남은 유료와 회수량이 같은 잠금
    아래에서 정해지게 한다.
    """
    if order.status not in _REFUNDABLE:
        raise RefundRefusedError(422, "PAYMENT_NOT_REFUNDABLE")
    assert order.paid_at is not None  # 지급한 주문은 결제 시각이 있다
    paid_on = order.paid_at.astimezone(KST).date()
    if received_on < paid_on or received_on > today:
        raise RefundRefusedError(422, "REFUND_RECEIVED_ON_INVALID")

    lots = {
        lot.kind: lot
        for lot in (
            await db.scalars(
                select(CloverLot)
                .where(CloverLot.payment_id == order.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    paid_lot, bonus_lot = lots.get("purchase_paid"), lots.get("purchase_bonus")
    paid_remaining = paid_lot.remaining if paid_lot is not None else 0
    bonus_remaining = bonus_lot.remaining if bonus_lot is not None else 0
    bonus_used = 0
    if bonus_lot is not None:
        bonus_used = int(
            await db.scalar(
                select(
                    func.coalesce(func.sum(CloverSpendAllocation.amount - CloverSpendAllocation.refunded_amount), 0)
                ).where(CloverSpendAllocation.lot_id == bonus_lot.id)
            )
            or 0
        )
    units = max(0, paid_remaining - bonus_used)
    ratio = refund_ratio_percent(paid_on=paid_on, received_on=received_on, company_fault=company_fault)
    cancellable = order.amount_krw - order.cancelled_amount_krw
    refund = min(units * order.amount_krw * ratio // (order.paid_amount * 100), cancellable)
    return RefundQuote(
        refund_krw=refund,
        ratio_percent=ratio,
        paid_remaining=paid_remaining,
        bonus_used=bonus_used,
        clawback_paid=paid_remaining,
        clawback_bonus=bonus_remaining,
        cancellable_krw=cancellable,
        paid_at=order.paid_at,
    )


async def _lock_order(db: AsyncSession, order_id: uuid.UUID) -> Payment:
    order = await db.scalar(
        select(Payment).where(Payment.id == order_id).with_for_update().execution_options(populate_existing=True)
    )
    assert order is not None  # 결제 행은 지우지 않는다
    return order


async def _pending_attempt(db: AsyncSession, order_id: uuid.UUID) -> PaymentCancellation | None:
    attempt: PaymentCancellation | None = await db.scalar(
        select(PaymentCancellation)
        .where(PaymentCancellation.payment_id == order_id, PaymentCancellation.status == "requested")
        .execution_options(populate_existing=True)
    )
    return attempt


async def _attempt_outcome(
    db: AsyncSession, attempt_id: uuid.UUID, notifications: tuple[str, ...] = ()
) -> RefundOutcome:
    attempt = await db.scalar(
        select(PaymentCancellation)
        .where(PaymentCancellation.id == attempt_id)
        .execution_options(populate_existing=True)
    )
    assert attempt is not None
    outcome = RefundOutcome(
        attempt.status, attempt.amount_krw, attempt.clawback_paid, attempt.clawback_bonus, notifications
    )
    await db.commit()
    return outcome


async def _settle_totals(db: AsyncSession, order: Payment) -> None:
    """취소액을 `succeeded` 행 합으로 다시 정하고 지급한 주문의 상태를 맞춘다. 잠근 주문 행에서만 부른다."""
    total = int(
        await db.scalar(
            select(func.coalesce(func.sum(PaymentCancellation.amount_krw), 0)).where(
                PaymentCancellation.payment_id == order.id, PaymentCancellation.status == "succeeded"
            )
        )
        or 0
    )
    order.cancelled_amount_krw = total
    if order.status in _REFUNDABLE and total > 0:
        order.status = "cancelled" if total >= order.amount_krw else "partially_cancelled"
    order.updated_at = _utcnow()


async def _match_row(
    db: AsyncSession, order: Payment, cancellation: PortOneCancellation, attempt_id: uuid.UUID | None
) -> PaymentCancellation | None:
    """포트원 취소 하나에 맞는 우리 행.

    1. 포트원 취소 id 가 같은 행.
    2. `attempt_id` 가 주어지면(우리 취소 요청에 대한 직접 응답) 그 시도 행 — 아직 `requested` 이고 id 를 모를 때만. 어느
       시도의 응답인지 이미 알므로 금액으로 찾지 않는다(포트원 금액이 요청액과 다르게 와도 그 시도가 남지 않는다).
    3. 그 밖에는 성공·대기 취소만, id 를 아직 모르는 `requested` 어드민 행 중 금액이 같은 것(우리 응답보다 웹훅이 먼저 온
       경우). **실패 취소는 금액으로 맞추지 않는다** — 앞서 거절된 시도의 실패 내역이 같은 금액의 새 시도를 실패로 닫아,
       새 취소가 진행 중인데 클로버를 되돌려 주게 된다.
    """
    assert not isinstance(cancellation, dict)
    row: PaymentCancellation | None = await db.scalar(
        select(PaymentCancellation)
        .where(PaymentCancellation.portone_cancellation_id == cancellation.id)
        .execution_options(populate_existing=True)
    )
    if row is not None:
        return row
    if attempt_id is not None:
        attempt = await db.get(PaymentCancellation, attempt_id, populate_existing=True)
        assert attempt is not None
        if attempt.status == "requested" and attempt.portone_cancellation_id is None:
            return attempt
        return None
    if isinstance(cancellation, FailedPaymentCancellation):
        return None
    by_amount: PaymentCancellation | None = await db.scalar(
        select(PaymentCancellation)
        .where(
            PaymentCancellation.payment_id == order.id,
            PaymentCancellation.status == "requested",
            PaymentCancellation.portone_cancellation_id.is_(None),
            PaymentCancellation.amount_krw == cancellation.total_amount,
        )
        .execution_options(populate_existing=True)
    )
    return by_amount


async def _record_console_cancel(
    db: AsyncSession, order: Payment, cancellation: SucceededPaymentCancellation
) -> None:
    """우리 쪽 시도와 맞지 않는 성공 취소 = 포트원 콘솔에서 직접 한 취소. 그 구매의 클로버를 회수해 `console` 행으로 남긴다.

    - 이 취소로 결제가 전액 취소되면 남은 전부를 회수한다. 부분 취소면 취소 금액을 구매 단가로 나눈 만큼(올림)만,
      유료 먼저·모자라면 같은 구매의 보너스에서 회수한다 — 돈을 돌려준 만큼만 가져간다. 부분 환불은 어드민 환불로 하는
      것이 운영 규칙이라 Bugsink 에 남긴다.
    - 진행 중인 어드민 시도가 클로버를 회수해 쥐고 있으면 그 몫에서 먼저 옮겨 온다(원장은 이미 회수로 적혀 있어 새 행을
      쓰지 않는다). 그 시도가 뒤에 거절되면 복원은 남은 몫만 한다 — 옮기지 않으면 돈으로 돌려준 클로버까지 되돌려 준다.
    """
    already = int(
        await db.scalar(
            select(func.coalesce(func.sum(PaymentCancellation.amount_krw), 0)).where(
                PaymentCancellation.payment_id == order.id, PaymentCancellation.status == "succeeded"
            )
        )
        or 0
    )
    full = already + cancellation.total_amount >= order.amount_krw
    # 남은 회수 수량. 전액 취소면 상한이 없다.
    need: int | None = None if full else -(-cancellation.total_amount * order.paid_amount // order.amount_krw)
    if not full:
        logger.warning("payment %s was partially cancelled at the PortOne console", order.id)
        capture_dependency_failure(PaymentConsolePartialCancelError(), dependency="payment")

    paid = bonus = 0
    holder = await _pending_attempt(db, order.id)
    if holder is not None:
        paid = holder.clawback_paid if need is None else min(holder.clawback_paid, need)
        need = None if need is None else need - paid
        bonus = holder.clawback_bonus if need is None else min(holder.clawback_bonus, need)
        need = None if need is None else need - bonus
        holder.clawback_paid -= paid
        holder.clawback_bonus -= bonus
    if need is None or need > 0:
        lot_paid, lot_bonus = await revoke_purchase_lots(db, payment_id=order.id, limit=need)
        paid, bonus = paid + lot_paid, bonus + lot_bonus
    db.add(
        PaymentCancellation(
            payment_id=order.id,
            source="console",
            status="succeeded",
            amount_krw=cancellation.total_amount,
            clawback_paid=paid,
            clawback_bonus=bonus,
            portone_cancellation_id=cancellation.id,
            completed_at=_utcnow(),
        )
    )
    await db.flush()


async def _apply_cancellation(
    db: AsyncSession, order: Payment, cancellation: PortOneCancellation, *, attempt_id: uuid.UUID | None = None
) -> list[str]:
    """포트원 취소 하나를 우리 취소 행에 반영한다. 잠근 주문 행에서만 부른다. 새로 성공한 취소의 알림 문구를 돌려준다.
    행 맞추기는 `_match_row`, 맞는 행이 없는 성공 취소는 `_record_console_cancel`."""
    if isinstance(cancellation, dict):
        logger.warning("payment %s has a cancellation of unknown shape", order.id)
        return []
    row = await _match_row(db, order, cancellation, attempt_id)
    now = _utcnow()

    if isinstance(cancellation, SucceededPaymentCancellation):
        if row is None:
            await _record_console_cancel(db, order, cancellation)
            return [payment_refunded_message(order, cancellation.total_amount)]
        if row.status == "requested":
            row.status = "succeeded"
            row.portone_cancellation_id = cancellation.id
            row.completed_at = now
            await db.flush()
            return [payment_refunded_message(order, row.amount_krw)]
        if row.status == "failed":
            # 실패로 확정해 회수분을 되돌린 취소를 포트원이 성공이라고 한다 — 돈과 클로버가 둘 다 사용자에게 있다.
            logger.warning("payment %s: a cancellation recorded as failed succeeded at PortOne", order.id)
            capture_dependency_failure(PaymentRefundStuckError(), dependency="payment")
        return []

    if isinstance(cancellation, RequestedPaymentCancellation):
        # PG 가 비동기로 처리 중이다. id 만 적어 두면 성공·실패 웹훅이 id 로 이 행을 맞춘다.
        if row is not None and row.portone_cancellation_id is None:
            row.portone_cancellation_id = cancellation.id
            await db.flush()
        return []

    assert isinstance(cancellation, FailedPaymentCancellation)
    if row is not None and row.status == "requested":
        await _fail(db, order, row, portone_cancellation_id=cancellation.id)
    return []


async def _fail(
    db: AsyncSession, order: Payment, row: PaymentCancellation, *, portone_cancellation_id: str | None
) -> None:
    """포트원이 취소하지 않았음이 확정이다 — 시도를 실패로 닫고 회수한 클로버를 그 구매의 로트로 되돌린다."""
    row.status = "failed"
    if portone_cancellation_id is not None:
        row.portone_cancellation_id = portone_cancellation_id
    row.completed_at = _utcnow()
    await restore_purchase_lots(db, payment_id=order.id, paid=row.clawback_paid, bonus=row.clawback_bonus)
    await db.flush()


async def apply_remote_cancellations(db: AsyncSession, order: Payment, remote: PortOnePayment) -> list[str]:
    """포트원 결제 조회 결과의 취소 내역 전부를 반영하고 취소액·상태를 맞춘다. 잠근 주문 행에서만 부르고 커밋은 호출자가
    한다. 결제 동기화(웹훅·결제 완료 알림)와 어드민 재시도가 공유하는 유일한 대사 경로다."""
    if isinstance(remote, dict):
        logger.warning("payment %s: PortOne returned a payment of unknown shape", order.id)
        return []
    # 결제가 아직 `PAID` 여도 대기·실패 취소는 그 결제의 취소 내역에 보인다(성공한 취소가 생겨야 상태가 바뀐다). 이것을
    # 버리면 PG 가 비동기 취소를 실패시킨 시도가 영영 `requested` 로 남고, 대기 중인 시도를 "포트원에 안 닿음"으로 보고
    # 다시 보낸다.
    cancellations: list[PortOneCancellation] = []
    if isinstance(remote, (CancelledPayment, PartialCancelledPayment)):
        cancellations = remote.cancellations
    elif isinstance(remote, PaidPayment):
        cancellations = remote.cancellations or []
    notifications: list[str] = []
    for cancellation in cancellations:
        notifications += await _apply_cancellation(db, order, cancellation)
    await _settle_totals(db, order)
    if order.cancelled_amount_krw != remote.amount.cancelled:
        logger.warning("payment %s: our cancelled total differs from PortOne's", order.id)
        capture_dependency_failure(PaymentRefundStuckError(), dependency="payment")
    return notifications


async def reconcile_refund(db: AsyncSession, gateway: PortOneGateway, order_id: uuid.UUID, *, resend: bool) -> list[str]:
    """포트원을 다시 조회해 그 결제의 취소를 맞춘다. 커밋한다. 포트원 조회 실패는 `PortOneUnavailableError` 로 올린다.

    `resend` 는 어드민 재시도에서만 켠다: 대사 뒤에도 포트원 취소 id 를 모르는 `requested` 행이 남았으면 우리 취소가 PG 에
    닿지 않은 것이라 같은 취소를 다시 보낸다(이중 취소는 취소 가능 잔액 가드가 포트원에서 막는다). 단 그 시도를 최근
    `SEND_CLAIM_SECONDS` 안에 보내기 시작했으면 보내지 않는다 — 첫 전송이 아직 응답을 기다리는 중일 수 있다. 웹훅·결제 완료
    알림은 다시 보내지 않는다 — 돈을 내보내는 호출은 어드민 조작에서만 나간다.
    """
    order = await db.get(Payment, order_id)
    assert order is not None
    portone_payment_id = order.payment_id
    # 외부 호출을 기다리는 동안 커넥션과 행 락을 쥐지 않는다.
    await db.commit()
    remote = await gateway.get_payment(portone_payment_id)
    order = await _lock_order(db, order_id)
    notifications = await apply_remote_cancellations(db, order, remote)
    to_send: uuid.UUID | None = None
    if resend:
        attempt = await _pending_attempt(db, order_id)
        if attempt is not None and attempt.source == "admin" and attempt.portone_cancellation_id is None:
            now = _utcnow()
            if attempt.last_sent_at is None or now - attempt.last_sent_at > timedelta(seconds=SEND_CLAIM_SECONDS):
                # 결제 행 잠금 아래에서 전송을 차지한다 — 같은 순간의 다른 재시도는 이 값을 보고 보내지 않는다.
                attempt.last_sent_at = now
                to_send = attempt.id
    await db.commit()
    if to_send is not None:
        outcome = await _send_cancel(db, gateway, order_id=order_id, attempt_id=to_send)
        notifications += outcome.notifications
    return notifications


async def _send_cancel(
    db: AsyncSession, gateway: PortOneGateway, *, order_id: uuid.UUID, attempt_id: uuid.UUID
) -> RefundOutcome:
    """`requested` 행의 취소를 포트원에 보내고 결과를 반영한다. 커밋한다."""
    order = await db.get(Payment, order_id)
    attempt = await db.get(PaymentCancellation, attempt_id)
    assert order is not None and attempt is not None
    succeeded_total = order.cancelled_amount_krw
    portone_payment_id, amount, total = order.payment_id, attempt.amount_krw, order.amount_krw
    await db.commit()
    try:
        cancellation = await gateway.cancel_payment(
            portone_payment_id,
            amount=amount,
            current_cancellable_amount=total - succeeded_total,
            reason=PORTONE_CANCEL_REASON,
        )
    except PortOneUnavailableError as exc:
        # 결과를 모른다. 회수한 채로 `requested` 를 둔다 — 포트원이 처리했으면 웹훅이, 아니면 어드민 재시도가 끝낸다.
        logger.warning("refund cancel could not reach portone: %s", exc)
        capture_dependency_failure(exc, dependency="portone")
        return await _attempt_outcome(db, attempt_id)
    except PortOneCancelRejectedError as exc:
        logger.warning("refund cancel was rejected: %s", exc.reason)
        notifications: list[str] = []
        if exc.reason in _MAYBE_ALREADY_CANCELLED:
            try:
                notifications = await reconcile_refund(db, gateway, order_id, resend=False)
            except PortOneUnavailableError as lookup_exc:
                logger.warning("refund rejection could not be checked at portone: %s", lookup_exc)
                capture_dependency_failure(lookup_exc, dependency="portone")
                return await _attempt_outcome(db, attempt_id)
        order = await _lock_order(db, order_id)
        row = await db.get(PaymentCancellation, attempt_id, populate_existing=True)
        assert row is not None
        if row.status == "requested":
            await _fail(db, order, row, portone_cancellation_id=None)
        await db.commit()
        return await _attempt_outcome(db, attempt_id, tuple(notifications))

    if isinstance(cancellation, dict):
        logger.warning("refund cancel returned a cancellation of unknown shape")
        return await _attempt_outcome(db, attempt_id)
    order = await _lock_order(db, order_id)
    notifications = await _apply_cancellation(db, order, cancellation, attempt_id=attempt_id)
    await _settle_totals(db, order)
    await db.commit()
    return await _attempt_outcome(db, attempt_id, tuple(notifications))


async def execute_refund(
    db: AsyncSession,
    gateway: PortOneGateway,
    *,
    order_id: uuid.UUID,
    admin_id: uuid.UUID,
    reason: str,
    expected_refund_krw: int,
    received_on: date,
    company_fault: bool,
    today: date,
) -> RefundOutcome:
    """어드민 환불을 실행한다(모듈 docstring 의 순서). 커밋한다.

    그 결제에 `requested` 시도가 이미 있으면 새로 만들지 않고 그 시도를 대사로 마무리한다(요청 본문의 견적·접수일은
    쓰지 않는다). 시작 전 거절은 `RefundRefusedError` — 아무것도 쓰지 않았다.
    """
    order = await _lock_order(db, order_id)
    attempt = await _pending_attempt(db, order_id)
    if attempt is not None:
        attempt_id = attempt.id
        await db.commit()
        try:
            notifications = await reconcile_refund(db, gateway, order_id, resend=True)
        except PortOneUnavailableError as exc:
            logger.warning("refund retry could not reach portone: %s", exc)
            capture_dependency_failure(exc, dependency="portone")
            return await _attempt_outcome(db, attempt_id)
        return await _attempt_outcome(db, attempt_id, tuple(notifications))

    try:
        # 사용자 행을 먼저 잠근다 — 차감·환급도 사용자 행부터 잠그므로, 견적이 읽은 남은 유료가 회수까지 바뀌지 않는다.
        await db.execute(select(User.id).where(User.id == order.user_id).with_for_update())
        quote = await quote_refund(db, order, received_on=received_on, company_fault=company_fault, today=today)
        if quote.refund_krw != expected_refund_krw:
            raise RefundRefusedError(409, "REFUND_QUOTE_CHANGED")
        if quote.refund_krw == 0:
            raise RefundRefusedError(422, "REFUND_AMOUNT_ZERO")
    except RefundRefusedError:
        # 쓴 것이 없다 — 잠금만 놓는다.
        await db.commit()
        raise

    paid, bonus = await revoke_purchase_lots(db, payment_id=order_id)
    attempt = PaymentCancellation(
        payment_id=order_id,
        source="admin",
        status="requested",
        amount_krw=quote.refund_krw,
        ratio_percent=quote.ratio_percent,
        request_received_on=received_on,
        company_fault=company_fault,
        clawback_paid=paid,
        clawback_bonus=bonus,
        admin_id=admin_id,
        reason=reason,
        last_sent_at=_utcnow(),
    )
    db.add(attempt)
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-payment-refund",
        target_user_id=order.user_id,
        reason_text=audit_reason(received_on=received_on, company_fault=company_fault, reason=reason),
    )
    await db.flush()
    attempt_id = attempt.id
    await db.commit()
    return await _send_cancel(db, gateway, order_id=order_id, attempt_id=attempt_id)

