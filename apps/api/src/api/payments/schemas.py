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
    # 이 결제로 실제 지급한 유료·보너스 클로버 — 그 결제로 만든 구매 로트의 지급량이다(상품표나 주문 행의 사본이 아니다). 지급한
    # 상태(결제 완료·부분 취소)가 아니면 둘 다 null 이고, 보너스 없는 상품은 보너스가 0 이다. 부분 취소의 회수는 이 값을 줄이지
    # 않는다(내역이 회수를 보인다).
    granted_paid: int | None
    granted_bonus: int | None
