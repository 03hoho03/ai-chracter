from typing import Literal

from api.clover.products import ProductKey
from api.core.schema import CamelModel
from api.db.models.payment import PaymentStatus


class CreatePaymentRequest(CamelModel):
    product_key: ProductKey
    # 유료 조건(청약철회 제한 고지·환불정책)에 동의했는가. 동의하지 않은 주문은 만들지 않는다.
    agreed: Literal[True]


class CreatePaymentResponse(CamelModel):
    """브라우저가 포트원 결제창에 그대로 넘기는 값. 상점 id·채널키는 웹 빌드에 넣지 않고 이 응답으로만 내린다."""

    payment_id: str
    store_id: str
    channel_key: str
    order_name: str
    total_amount: int
    currency: Literal["KRW"]


class CompletePaymentResponse(CamelModel):
    """`pending` 이면 포트원이 아직 결제를 확정하지 않았다 — 화면은 "확인 중"을 안내하고 잔액을 다시 읽는다."""

    status: PaymentStatus
    balance: int
