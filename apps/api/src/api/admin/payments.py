"""어드민 결제 조회와 환불. 셀프 환불은 없다 — 환불은 운영자가 이 경로로만 시작한다(포트원 콘솔 취소는 웹훅이 맞춘다).

환불의 순서·멱등 단위·회수 시점은 `payments/refund.py` 에 있다.
"""

import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminRefundQuoteResponse,
    AdminRefundRequest,
    AdminRefundResponse,
    AdminUserPaymentItem,
    AdminUserPaymentListResponse,
)
from api.db.models.payment import Payment, PaymentCancellation
from api.db.session import get_db_session
from api.payments import refund
from api.payments.notify import PaymentNotifier, get_payment_notifier
from api.payments.portone import PortOneGateway, get_portone_gateway

router = APIRouter(tags=["admin"])

ADMIN_USER_PAYMENT_LIMIT = 20


def _refused(exc: refund.RefundRefusedError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code})


async def _find_order(db: AsyncSession, payment_id: str) -> Payment:
    order = await db.scalar(select(Payment).where(Payment.payment_id == payment_id))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PAYMENT_NOT_FOUND"})
    return order


@router.get("/admin/users/{user_id}/payments")
async def list_user_payments(
    user_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserPaymentListResponse:
    """그 회원의 최근 주문(모든 상태). 진행 중 환불 시도가 있는 주문은 `refundPending` 이 참이다."""
    pending = exists().where(
        PaymentCancellation.payment_id == Payment.id, PaymentCancellation.status == "requested"
    )
    rows = (
        await db.execute(
            select(Payment, pending.label("refund_pending"))
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc(), Payment.id)
            .limit(ADMIN_USER_PAYMENT_LIMIT)
        )
    ).all()
    return AdminUserPaymentListResponse(
        items=[
            AdminUserPaymentItem(
                payment_id=order.payment_id,
                product_key=order.product_key,
                order_name=order.order_name,
                amount_krw=order.amount_krw,
                status=order.status,
                paid_at=order.paid_at,
                cancelled_amount_krw=order.cancelled_amount_krw,
                refund_pending=refund_pending,
                created_at=order.created_at,
            )
            for order, refund_pending in rows
        ]
    )


@router.get("/admin/payments/{payment_id}/refund-quote")
async def get_refund_quote(
    payment_id: str,
    received_on: date = Query(alias="receivedOn"),
    company_fault: bool = Query(False, alias="companyFault"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminRefundQuoteResponse:
    """환불 견적. 신청 접수일(KST)이 결제일 전이거나 오늘 뒤면 422 `REFUND_RECEIVED_ON_INVALID`, 환불할 수 있는 상태가
    아니면 422 `PAYMENT_NOT_REFUNDABLE`. 아무것도 쓰지 않는다."""
    order = await _find_order(db, payment_id)
    try:
        quote = await refund.quote_refund(
            db, order, received_on=received_on, company_fault=company_fault, today=refund.kst_today()
        )
    except refund.RefundRefusedError as exc:
        raise _refused(exc) from None
    return AdminRefundQuoteResponse(
        refund_krw=quote.refund_krw,
        ratio_percent=quote.ratio_percent,
        paid_remaining=quote.paid_remaining,
        bonus_used=quote.bonus_used,
        clawback_paid=quote.clawback_paid,
        clawback_bonus=quote.clawback_bonus,
        cancellable_krw=quote.cancellable_krw,
        paid_at=quote.paid_at,
    )


@router.post(
    "/admin/payments/{payment_id}/refund",
    responses={status.HTTP_202_ACCEPTED: {"model": AdminRefundResponse}},
)
async def refund_payment(
    payment_id: str,
    body: AdminRefundRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    gateway: PortOneGateway = Depends(get_portone_gateway),
    notifier: PaymentNotifier = Depends(get_payment_notifier),
) -> AdminRefundResponse:
    """환불을 실행하거나, 진행 중 시도가 있으면 그 시도를 마무리한다.

    - 200 `succeeded`: 포트원 취소 확인. 디스코드에 알린다.
    - 202 `requested`: 클로버는 회수했고 포트원 결과가 확정되지 않았다(응답 없음·시간 초과·PG 비동기 처리). 같은 경로로
      다시 부르면 포트원을 재조회해 마무리한다.
    - 422 `REFUND_REJECTED`: 포트원이 취소를 거절해 회수한 클로버를 되돌렸다.
    - 409 `REFUND_QUOTE_CHANGED`: 실행 시점 견적이 다이얼로그의 견적과 다르다. 422 `REFUND_AMOUNT_ZERO`·
      `REFUND_RECEIVED_ON_INVALID`·`PAYMENT_NOT_REFUNDABLE`: 시작하지 않았다.
    """
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="reason is required")
    order = await _find_order(db, payment_id)
    try:
        outcome = await refund.execute_refund(
            db,
            gateway,
            order_id=order.id,
            admin_id=admin_id,
            reason=reason,
            expected_refund_krw=body.expected_refund_krw,
            received_on=body.received_on,
            company_fault=body.company_fault,
            today=refund.kst_today(),
        )
    except refund.RefundRefusedError as exc:
        raise _refused(exc) from None
    for message in outcome.notifications:
        background_tasks.add_task(notifier, message)
    if outcome.status == "failed":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "REFUND_REJECTED"})
    if outcome.status == "requested":
        response.status_code = status.HTTP_202_ACCEPTED
    return AdminRefundResponse(
        status=outcome.status,
        amount_krw=outcome.amount_krw,
        clawback_paid=outcome.clawback_paid,
        clawback_bonus=outcome.clawback_bonus,
    )
