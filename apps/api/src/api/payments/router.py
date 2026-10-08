"""클로버 구매의 HTTP 표면: 주문 생성, 브라우저의 결제 완료 알림, 포트원 웹훅.

결제 완료 알림과 웹훅은 요청이 말하는 결제 상태를 믿지 않는다 — 둘 다 같은 동기화(`payments/service.py`)가 포트원을
다시 조회해 주문 행과 맞춘다.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from portone_server_sdk import webhook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover import products
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.payment import Payment
from api.db.session import get_db_session
from api.legal.dependencies import _latest_published_legal_version, require_legal_consent
from api.payments.config import payments_active
from api.payments.errors import PaymentWebhookConfigError, PortOneUnavailableError
from api.payments.notify import PaymentNotifier, get_payment_notifier
from api.payments.portone import PortOneGateway, get_portone_gateway
from api.payments.schemas import CompletePaymentResponse, CreatePaymentRequest, CreatePaymentResponse
from api.payments.service import SyncOutcome, sync_payment
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

# 웹훅이 동기화하는 이벤트. 나머지(결제 준비·가상계좌·분쟁 등)는 받기만 하고 200 이다.
_SYNCED_WEBHOOKS = (
    webhook.WebhookTransactionPaid,
    webhook.WebhookTransactionFailed,
    webhook.WebhookTransactionCancelledCancelled,
    webhook.WebhookTransactionCancelledPartialCancelled,
)


def _payments_unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "PAYMENTS_UNAVAILABLE"})


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_payment(
    body: CreatePaymentRequest,
    _consent: None = Depends(require_legal_consent),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CreatePaymentResponse:
    """주문을 만든다. 금액은 서버가 상품 키로 정하고 주문 행에 복사해 둔다 — 브라우저가 금액을 바꿔 결제해도 동기화의
    금액 대조가 지급을 막는다. 포트원 사전 등록은 하지 않는다(주문마다 외부 호출 실패 지점이 하나 늘 뿐, 막는 것은 같다).

    결제가 꺼져 있으면 503 `PAYMENTS_UNAVAILABLE`. 결제는 본인인증과 만 19세 확인을 거쳐야 하므로, 그 판정을 이 플래그
    판정 바로 뒤(주문 행을 만들기 전)에 둔다.
    """
    if not payments_active():
        raise _payments_unavailable()
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # 상품은 요청 시점에 모듈 속성으로 읽는다(테스트의 monkeypatch 가 통하게).
    product = next((p for p in products.CLOVER_PRODUCTS if p.key == body.product_key), None)
    if product is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "PRODUCT_NOT_FOUND"})
    terms_version = await _latest_published_legal_version(db, "terms")
    refund_policy_version = await _latest_published_legal_version(db, "refund-policy")
    if terms_version is None or refund_policy_version is None:
        # 동의 기록에 남길 게시본이 없으면 유료 조건 동의가 성립하지 않는다.
        raise _payments_unavailable()

    order = Payment(
        payment_id=f"clv{uuid.uuid4().hex}",
        user_id=user_id,
        product_key=product.key,
        order_name=f"클로버 {product.name}",
        amount_krw=product.price_krw,
        paid_amount=product.paid_amount,
        bonus_amount=product.bonus_amount,
        channel_key=settings.portone_payment_channel_key,
        status="pending",
        consented_at=datetime.now(UTC),
        terms_version=terms_version,
        refund_policy_version=refund_policy_version,
    )
    db.add(order)
    await db.commit()
    return CreatePaymentResponse(
        payment_id=order.payment_id,
        store_id=settings.portone_store_id,
        channel_key=order.channel_key,
        order_name=order.order_name,
        total_amount=order.amount_krw,
        currency="KRW",
    )


def _notify_after_response(outcome: SyncOutcome, background_tasks: BackgroundTasks, notifier: PaymentNotifier) -> None:
    if outcome.notification is not None:
        background_tasks.add_task(notifier, outcome.notification)


@router.post("/{payment_id}/complete")
async def complete_payment(
    payment_id: str,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    gateway: PortOneGateway = Depends(get_portone_gateway),
    notifier: PaymentNotifier = Depends(get_payment_notifier),
) -> CompletePaymentResponse:
    """브라우저가 결제창이 끝났다고 알린다. 자기 주문만(아니면 404 `PAYMENT_NOT_FOUND`).

    재동의·결제 플래그 게이트를 걸지 않는다 — 이미 돈이 나간 결제의 동기화를 막으면 안 된다. 포트원 조회가 실패하면
    502 `PORTONE_UNAVAILABLE`(다시 시도하면 되고, 웹훅도 같은 결제를 맞춘다).
    """
    owner = await db.scalar(select(Payment.user_id).where(Payment.payment_id == payment_id))
    if owner != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PAYMENT_NOT_FOUND"})
    try:
        outcome = await sync_payment(db, gateway, payment_id)
    except PortOneUnavailableError as exc:
        logger.warning("payment complete could not reach portone: %s", exc)
        capture_dependency_failure(exc, dependency="portone")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail={"code": "PORTONE_UNAVAILABLE"}
        ) from None
    assert outcome.status is not None  # 위에서 이 사용자의 주문임을 확인했다
    _notify_after_response(outcome, background_tasks, notifier)
    balance = await db.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return CompletePaymentResponse(status=outcome.status, balance=balance)


@router.post("/portone/webhook", include_in_schema=False)
async def portone_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    gateway: PortOneGateway = Depends(get_portone_gateway),
    notifier: PaymentNotifier = Depends(get_payment_notifier),
) -> Response:
    """포트원 웹훅(Standard Webhooks 서명). 서버 간 호출이라 스키마에서 뺀다.

    응답 코드가 포트원의 재시도를 정한다(2xx 가 아니면 재시도한다): 서명이 틀리면 401(다시 보내도 같다), 웹훅 비밀이
    비었거나 형식이 틀리면 503(설정 사고 — Bugsink 에 남기고 고친 뒤의 재시도를 받는다), 포트원 조회가 실패하면 503,
    그 밖에는 처리했든 무관한 이벤트든 200. DB 오류는 그대로 500 이라 역시 재시도된다.

    결제 플래그가 꺼져 있어도 비밀이 있으면 처리한다 — 끄기 전에 시작한 결제와 콘솔 취소를 맞춰야 한다.
    """
    # 원문 그대로 검증한다 — 본문 모델로 받아 다시 직렬화하면 서명이 깨진다.
    payload = (await request.body()).decode("utf-8", errors="replace")
    secret = settings.portone_webhook_secret
    if not secret:
        capture_dependency_failure(PaymentWebhookConfigError("webhook secret is empty"), dependency="payment")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        event = webhook.verify(secret, payload, request.headers)
    except webhook.WebhookVerificationError as exc:
        logger.warning("portone webhook rejected: %s", exc.reason)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
    except webhook.InvalidInputError:
        capture_dependency_failure(PaymentWebhookConfigError("webhook secret is malformed"), dependency="payment")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from None

    if not isinstance(event, _SYNCED_WEBHOOKS) or event.data.store_id != settings.portone_store_id:
        return Response(status_code=status.HTTP_200_OK)
    try:
        outcome = await sync_payment(db, gateway, event.data.payment_id)
    except PortOneUnavailableError as exc:
        logger.warning("portone webhook could not reach portone: %s", exc)
        capture_dependency_failure(exc, dependency="portone")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from None
    _notify_after_response(outcome, background_tasks, notifier)
    return Response(status_code=status.HTTP_200_OK)
