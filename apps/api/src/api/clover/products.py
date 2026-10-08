"""클로버 충전 상품 정의.

DB 테이블·어드민 관리 화면을 두지 않는다(4종 고정). 공개 가격 안내(`clover/router.py`의 `GET /clover/pricing`)가
이 목록을 그대로 내보내고, 웹은 가격 숫자의 사본을 갖지 않는다. 결제를 붙이면 서버가 결제 금액을 상품 키의 가격과
대조해야 하므로 상품의 원본은 이 파일 하나다.

라우트는 이 목록을 **요청 시점에 모듈 속성으로** 읽는다(`products.CLOVER_PRODUCTS`) — `from … import` 로 묶어 두면
`monkeypatch.setattr` 가 통하지 않는다(`core/clover.py` 단가 상수와 같은 규칙).
"""

from dataclasses import dataclass
from typing import Literal

ProductKey = Literal["starter", "basic", "plus", "pro"]


@dataclass(frozen=True)
class CloverProduct:
    key: ProductKey
    # 화면에 보이는 상품 이름.
    name: str
    # 부가세를 포함한 판매가(원).
    price_krw: int
    # 결제로 받는 유료 클로버 수량과, 그 위에 얹어 주는 보너스 클로버 수량.
    paid_amount: int
    bonus_amount: int


# 순서가 곧 표시 순서다 — 싼 상품이 맨 앞. 키 목록과 값 딕셔너리를 따로 두지 않고 상품 하나에 필드를 모은 튜플
# 하나로 둔다(둘로 나누면 한쪽에만 상품을 더하는 실수가 생긴다).
#
# **임시 가격이다.** 1클로버를 3원(부가세 포함)으로 환산했는데, 이 환산은 단가 상수(`core/clover.py`)처럼 실측 원가가
# 아니라 정책값이라 원가를 다시 재면 바뀔 수 있다. 그때 이 값들을 함께 고친다. 모든 상품을 5만 원 미만으로 둔 것은
# 결제대행사가 충전형 상품에 거는 결제 한도를 넘지 않으려는 보수적 상한이며, 실제 한도는 결제대행사와 계약할 때 확인한다.
# 보너스는 비싼 상품일수록 늘려 최대 약 15%다.
CLOVER_PRODUCTS: tuple[CloverProduct, ...] = (
    CloverProduct(key="starter", name="스타터", price_krw=3_300, paid_amount=1_100, bonus_amount=0),
    CloverProduct(key="basic", name="베이직", price_krw=9_900, paid_amount=3_300, bonus_amount=300),
    CloverProduct(key="plus", name="플러스", price_krw=33_000, paid_amount=11_000, bonus_amount=1_500),
    CloverProduct(key="pro", name="프로", price_krw=49_500, paid_amount=16_500, bonus_amount=2_500),
)
