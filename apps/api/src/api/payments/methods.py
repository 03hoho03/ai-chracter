"""구매 화면에 내보이는 결제수단 목록 — 이 목록의 유일한 자리다. 웹은 사본을 갖지 않고 `GET /clover/pricing` 응답으로
받는다. 값은 포트원 브라우저 SDK 의 `payMethod`·`easyPay.easyPayProvider` 값 그대로다.

결제대행사(KG이니시스) 심사가 끝난 수단만 남겨 둔다. 가상계좌·정기결제는 받지 않는다.
"""

from dataclasses import dataclass
from typing import Literal

PayMethod = Literal["CARD", "EASY_PAY"]


@dataclass(frozen=True)
class PayMethodOption:
    pay_method: PayMethod
    # 간편결제일 때 그 제공자. 카드 일반결제는 `None`.
    easy_pay_provider: str | None = None


PAY_METHODS: tuple[PayMethodOption, ...] = (
    PayMethodOption("CARD"),
    PayMethodOption("EASY_PAY", "KAKAOPAY"),
    PayMethodOption("EASY_PAY", "NAVERPAY"),
    PayMethodOption("EASY_PAY", "TOSSPAY"),
    PayMethodOption("EASY_PAY", "SSGPAY"),
    PayMethodOption("EASY_PAY", "LPAY"),
    PayMethodOption("EASY_PAY", "SAMSUNGPAY"),
    PayMethodOption("EASY_PAY", "APPLEPAY"),
    PayMethodOption("EASY_PAY", "PAYCO"),
)
