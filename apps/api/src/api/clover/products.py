"""클로버 충전 상품 정의.

DB 테이블·어드민 관리 화면을 두지 않는다(목록은 코드로만 바꾼다). 공개 가격 안내(`clover/router.py`의 `GET /clover/pricing`)가
이 목록을 그대로 내보내고, 웹은 가격 숫자의 사본을 갖지 않는다. 결제를 붙이면 서버가 결제 금액을 상품 키의 가격과
대조해야 하므로 상품의 원본은 이 파일 하나다.

라우트는 이 목록을 **요청 시점에 모듈 속성으로** 읽는다(`products.CLOVER_PRODUCTS`) — `from … import` 로 묶어 두면
`monkeypatch.setattr` 가 통하지 않는다(`core/clover.py` 단가 상수와 같은 규칙).
"""

from dataclasses import dataclass
from typing import Literal

# 결제 행(`payments.product_key`)이 이 키를 자유 텍스트로 저장하고 어드민이 그대로 보여 주므로, 상품을 바꿀 때는 새
# 키를 쓰고 예전 키(`starter`·`basic`·`plus`·`pro`)를 다른 가격의 상품에 다시 쓰지 않는다 — 같은 키가 두 가격을
# 가리키면 과거 결제와 새 결제의 표시·분석이 섞인다. 환불·정산은 결제 행의 금액·수량을 쓰므로 키를 다시 찾지 않는다.
ProductKey = Literal["mini", "lite", "basic_v2", "plus_v2", "max"]


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
# 확정가다. 유료 수량 = 판매가 ÷ 3 — 1클로버를 3원(부가세 포함)으로 환산했고, 이 환산은 단가 상수(`core/clover.py`)처럼
# 실측 원가가 아니라 정책값이다. 유료 수량은 0보다 커야 한다 — 환불 견적(`payments/refund.py`)이 결제액을 유료 수량으로
# 나눠 클로버 하나의 값을 구하고, 결제 행의 CHECK 제약도 0을 거부한다. 모든 상품을 5만 원 미만으로 둔 것은 결제대행사가 충전형 상품에 거는 결제 한도를 넘지 않으려는 보수적
# 상한이다. 보너스는 비싼 상품일수록 5%p씩 늘려 최대 20%이고, 그 상품에서도 상위 모델 사용 원가가 판매가 안에
# 든다(추정 원가 기준 — 상위 모델을 켜기 전에 실측으로 다시 본다). 가장 싼 상품은 첫 결제 한정이 아니라 상시 판매다.
CLOVER_PRODUCTS: tuple[CloverProduct, ...] = (
    CloverProduct(key="mini", name="미니", price_krw=900, paid_amount=300, bonus_amount=0),
    CloverProduct(key="lite", name="라이트", price_krw=4_500, paid_amount=1_500, bonus_amount=75),
    CloverProduct(key="basic_v2", name="베이직", price_krw=9_900, paid_amount=3_300, bonus_amount=330),
    CloverProduct(key="plus_v2", name="플러스", price_krw=30_000, paid_amount=10_000, bonus_amount=1_500),
    CloverProduct(key="max", name="맥스", price_krw=49_500, paid_amount=16_500, bonus_amount=3_300),
)
