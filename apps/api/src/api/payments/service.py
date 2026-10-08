"""결제 동기화 — 브라우저의 결제 완료 알림(`POST /payments/{paymentId}/complete`)과 포트원 웹훅이 **같은 함수**를 부른다.

어느 쪽이든 요청이 말하는 상태를 믿지 않고 늘 포트원을 다시 조회해, 그 결과와 주문 행을 맞춘다. 두 경로가 겹쳐도
주문 행 `FOR UPDATE` 에서 줄을 서고, 뒤쪽은 이미 끝난 상태를 보고 아무것도 하지 않는다.

이중 지급을 막는 겹은 셋이다 — ① 잠근 주문 행의 상태(이미 지급했으면 아무것도 하지 않는다) ② 원장 멱등키(유료·보너스가
각각 다른 키, 전역 유니크) ③ 로트의 `(payment_id, kind)` 부분 유니크. ①이 정상 경로이고 ②③은 ①이 뚫렸을 때의 그물이다.

락 순서는 payments → users → clover_lots 다(지급·회수 공통). users 를 쥔 채 payments 를 잠그는 경로는 만들지 않는다.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from portone_server_sdk.payment import (
    CancelledPayment,
    FailedPayment,
    PaidPayment,
    PartialCancelledPayment,
    PayPendingPayment,
    ReadyPayment,
    VirtualAccountIssuedPayment,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.clover import grant, purchase_lot_expiry
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.payment import Payment, PaymentStatus
from api.payments.errors import PaymentMismatchError, PaymentOwnerWithdrawnError
from api.payments.portone import PortOneGateway
from api.payments.refund import apply_remote_cancellations

logger = logging.getLogger(__name__)

# - not_ours: 우리 주문이 아니다(다른 상점·테스트 잔재). already: 이미 끝난 주문이라 아무것도 하지 않았다.
# - granted: 지금 클로버를 지급했다. mismatch: 결제 완료인데 주문과 맞지 않아 지급하지 않았다(수동 처리).
# - owner_withdrawn: 결제 완료인데 주문자가 이미 탈퇴해 지급하지 않았다(수동 환불).
# - failed / cancelled: 지급 전에 실패·전액 취소됐다. pending: 포트원이 아직 결제를 확정하지 않았다.
# - reconciled: 지급 뒤의 취소를 취소 기록에 맞췄다(일부 취소이거나 이미 맞춰져 있었다).
# - unchanged: 맞출 것이 없거나 아직 맞추지 못하는 상태라 주문 행을 그대로 두었다.
SyncResult = Literal[
    "not_ours",
    "already",
    "granted",
    "mismatch",
    "owner_withdrawn",
    "failed",
    "cancelled",
    "reconciled",
    "pending",
    "unchanged",
]

# 지급했거나 사람이 볼 건으로 넘겨 다시 지급 판단을 하지 않는 상태.
_SETTLED: frozenset[PaymentStatus] = frozenset(
    {"paid", "partially_cancelled", "cancelled", "mismatch", "owner_withdrawn"}
)
# 지급 전 상태. 여기서 전액 취소가 오면 회수할 것 없이 cancelled 로 맞춘다.
_NOT_CREDITED: frozenset[PaymentStatus] = frozenset({"pending", "failed"})


@dataclass(frozen=True)
class SyncOutcome:
    result: SyncResult
    # 동기화 뒤 주문 상태. 우리 주문이 아니면 `None`.
    status: PaymentStatus | None
    # 응답 뒤 디스코드로 보낼 문구(지급했을 때만).
    notification: str | None = None


def payment_paid_message(payment: Payment) -> str:
    """결제 완료 알림 문구. 상품·금액·상태만 싣는다 — 회원 id·주문 id 는 조각도 넣지 않는다(외부 채널로 개인을 다시
    알아볼 단서를 보내지 않는다)."""
    return f"{payment.order_name} {payment.amount_krw:,}원 결제 완료"


def _mismatch_field(order: Payment, remote: PaidPayment) -> str | None:
    """포트원 결제가 이 주문의 결제인지 대조한다. 어긋난 첫 항목 이름(개인정보 없음)을 돌려준다."""
    if remote.store_id != settings.portone_store_id:
        return "store"
    if remote.channel.key is None or remote.channel.key != order.channel_key:
        return "channel"
    if remote.currency != "KRW":
        return "currency"
    if remote.amount.total != order.amount_krw:
        return "amount"
    return None


async def _mark_mismatch(db: AsyncSession, order: Payment, field: str) -> SyncOutcome:
    order.status = "mismatch"
    order.status_reason = field
    order.updated_at = datetime.now(UTC)
    await db.commit()
    logger.warning("payment %s needs manual review: %s", order.id, field)
    capture_dependency_failure(PaymentMismatchError(field), dependency="payment")
    return SyncOutcome("mismatch", "mismatch")


async def _owner_withdrawn(db: AsyncSession, order: Payment) -> bool:
    """주문자가 탈퇴했는가. 사용자 행을 `FOR SHARE` 로 읽어, 지급을 커밋할 때까지 탈퇴(사용자 행 `FOR UPDATE`)가 끼어들지
    못하게 한다 — 락 순서는 payments → users 그대로다."""
    deleted_at = await db.scalar(select(User.deleted_at).where(User.id == order.user_id).with_for_update(read=True))
    return deleted_at is not None


async def _mark_owner_withdrawn(db: AsyncSession, order: Payment) -> SyncOutcome:
    """탈퇴 계정에 지급하면 아무도 쓸 수 없는 잔액·로트가 남는다(탈퇴 소멸이 지키는 불변식이 깨진다). 지급하지 않고
    운영자 환불로 넘긴다. 이상 건이라 디스코드 완료 알림이 아니라 Bugsink 에만 남긴다."""
    order.status = "owner_withdrawn"
    order.updated_at = datetime.now(UTC)
    await db.commit()
    logger.warning("payment %s was paid after its owner withdrew; refund it at the PortOne console", order.id)
    capture_dependency_failure(PaymentOwnerWithdrawnError(), dependency="payment")
    return SyncOutcome("owner_withdrawn", "owner_withdrawn")


async def _grant_purchase(db: AsyncSession, order: Payment, remote: PaidPayment) -> SyncOutcome:
    paid_at = datetime.fromisoformat(remote.paid_at)
    expires_at = purchase_lot_expiry(paid_at)
    order_id, status_before = order.id, order.status
    try:
        # SAVEPOINT 안에서 지급한다 — 멱등 그물에 걸리면 지급만 되감고 주문 행 잠금은 커밋으로 놓는다.
        async with db.begin_nested():
            await _grant_lots(db, order, expires_at)
    except IntegrityError:
        # 상태 검사를 지나쳤는데 이 결제의 지급 기록이 이미 있다 — 지급하지 않는다.
        await db.commit()
        logger.warning("payment %s was already granted; the duplicate grant was rolled back", order_id)
        return SyncOutcome("already", status_before)
    order.status = "paid"
    order.status_reason = None
    order.paid_at = paid_at
    order.transaction_id = remote.transaction_id
    order.updated_at = datetime.now(UTC)
    notification = payment_paid_message(order)
    await db.commit()
    return SyncOutcome("granted", "paid", notification)


async def _grant_lots(db: AsyncSession, order: Payment, expires_at: datetime) -> None:
    """유료와 보너스를 서로 다른 원장 멱등키로 지급한다(키가 전역 유니크라 하나로는 두 행을 못 만든다)."""
    order_id = order.id
    await grant(
        db,
        user_id=order.user_id,
        amount=order.paid_amount,
        kind="purchase_paid",
        idempotency_key=f"purchase:{order_id}:paid",
        expires_at=expires_at,
        payment_id=order_id,
    )
    # 보너스가 없는 상품은 보너스 로트·원장을 만들지 않는다(원장에 0 행을 남기지 않는다).
    if order.bonus_amount > 0:
        await grant(
            db,
            user_id=order.user_id,
            amount=order.bonus_amount,
            kind="purchase_bonus",
            idempotency_key=f"purchase:{order_id}:bonus",
            expires_at=expires_at,
            payment_id=order_id,
        )


async def sync_payment(db: AsyncSession, gateway: PortOneGateway, payment_id: str) -> SyncOutcome:
    """포트원 결제 하나를 다시 조회해 주문 행을 맞춘다. 커밋한다. 포트원 조회 실패는 `PortOneUnavailableError` 로
    그대로 올린다(호출부가 재시도할 수 있는 실패로 다룬다)."""
    order = await db.scalar(select(Payment).where(Payment.payment_id == payment_id))
    if order is None:
        return SyncOutcome("not_ours", None)
    order_id = order.id
    # 외부 호출을 기다리는 동안 커넥션과 행 락을 쥐지 않는다.
    await db.commit()
    remote = await gateway.get_payment(payment_id)

    order = await db.scalar(
        select(Payment).where(Payment.id == order_id).with_for_update().execution_options(populate_existing=True)
    )
    assert order is not None  # 결제 행은 지우지 않는다
    status = order.status

    if isinstance(remote, PaidPayment):
        if status in _SETTLED:
            await db.commit()
            return SyncOutcome("already", status)
        field = _mismatch_field(order, remote)
        if field is not None:
            return await _mark_mismatch(db, order, field)
        if await _owner_withdrawn(db, order):
            return await _mark_owner_withdrawn(db, order)
        return await _grant_purchase(db, order, remote)

    if isinstance(remote, FailedPayment):
        if status != "pending":
            await db.commit()
            return SyncOutcome("unchanged", status)
        order.status = "failed"
        order.updated_at = datetime.now(UTC)
        await db.commit()
        return SyncOutcome("failed", "failed")

    if isinstance(remote, (PayPendingPayment, ReadyPayment, VirtualAccountIssuedPayment)):
        await db.commit()
        return SyncOutcome("pending", status)

    if isinstance(remote, (CancelledPayment, PartialCancelledPayment)):
        if status in ("paid", "partially_cancelled", "owner_withdrawn"):
            # 지급 뒤(또는 탈퇴로 지급하지 않은 결제)의 취소: 취소 행을 맞추고, 콘솔에서 직접 한 취소면 남은 구매 로트를
            # 회수한다(어드민 환불과 같은 대사 경로).
            notifications = await apply_remote_cancellations(db, order, remote)
            if status == "owner_withdrawn" and isinstance(remote, CancelledPayment):
                order.status = "cancelled"
            await db.commit()
            result: SyncResult = "cancelled" if order.status == "cancelled" else "reconciled"
            return SyncOutcome(result, order.status, "\n".join(notifications) or None)
        if status in _NOT_CREDITED:
            if isinstance(remote, PartialCancelledPayment):
                # 지급 전에 일부만 취소된 결제는 지급할 양을 정할 규칙이 없다 — 사람이 본다.
                return await _mark_mismatch(db, order, "partial_cancel")
            order.status = "cancelled"
            order.updated_at = datetime.now(UTC)
            await db.commit()
            return SyncOutcome("cancelled", "cancelled")
        await db.commit()
        return SyncOutcome("already", status)

    await db.commit()
    return SyncOutcome("unchanged", status)
