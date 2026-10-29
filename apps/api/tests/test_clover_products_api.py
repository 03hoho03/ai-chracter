"""공개 `GET /clover/products` — 충전 허브가 한 번에 읽는 상품·결제·정책 값.

이 파일이 검증하는 성질:

1. 로그인하지 않은 요청도 200이다 — 결제 전에 상품을 봐야 한다.
2. 응답은 요청 시점의 상품 목록·결제수단·스위치·정책 상수를 따른다 — 상수를 표지 값으로 바꾼 뒤 응답이 따라오는지로
   확인한다(오늘의 값과 비교만 하면 라우트가 숫자 사본을 들고 있어도 통과한다). 상품의 총량은 유료와 보너스의 합이다.
3. DB 를 읽지 않는다 — 허브가 화면을 열 때마다 부르는 공개 응답이라, 쿼리가 하나라도 생기면 비로그인 트래픽이 그대로 DB
   부하가 된다.
"""

import httpx
import pytest

from api.clover import products
from api.clover import router as clover_router
from api.clover.products import CloverProduct
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.payments import refund
from api.payments.methods import PAY_METHODS
from factories import _count_queries


async def test_anonymous_request_returns_products(db_client: httpx.AsyncClient) -> None:
    assert not db_client.cookies

    resp = await db_client.get("/clover/products")

    assert resp.status_code == 200
    assert [p["key"] for p in resp.json()["products"]] == [p.key for p in products.CLOVER_PRODUCTS]


async def test_products_response_follows_the_source_values(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """깨지는 시나리오: 허브가 이 응답의 유효기간·환불 비율로 안내 문장을 쓰는데 라우트가 값을 사본으로 들고 있어, 정책을 바꿔도
    허브가 옛 숫자를 보인다. 결제수단·결제 스위치·본인인증 스위치는 공개 가격 응답과 같은 판정 함수를 쓴다."""
    monkeypatch.setattr(
        products,
        "CLOVER_PRODUCTS",
        (
            CloverProduct(key="max", name="가짜 상품 하나", price_krw=1234, paid_amount=411, bonus_amount=7),
            CloverProduct(key="mini", name="가짜 상품 둘", price_krw=5678, paid_amount=1892, bonus_amount=0),
        ),
    )
    monkeypatch.setattr(clover, "PRICE_VERSION", 920_001)
    monkeypatch.setattr(clover, "PURCHASE_LOT_YEARS", 920_002)
    monkeypatch.setattr(refund, "FULL_REFUND_DAYS", 920_003)
    monkeypatch.setattr(refund, "REDUCED_REFUND_PERCENT", 920_004)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 920_005)
    # 두 스위치는 로컬 env 의 포트원 설정에 따라 갈리므로 판정 함수를 거짓으로 고정한다(참 갈래는 아래 테스트).
    monkeypatch.setattr(clover_router, "payments_active", lambda: False)
    monkeypatch.setattr(clover_router, "identity_gate_active", lambda: False)

    resp = await db_client.get("/clover/products")

    assert resp.status_code == 200
    assert resp.json() == {
        "products": [
            {
                "key": "max",
                "name": "가짜 상품 하나",
                "priceKrw": 1234,
                "paidAmount": 411,
                "bonusAmount": 7,
                "totalAmount": 418,
            },
            {
                "key": "mini",
                "name": "가짜 상품 둘",
                "priceKrw": 5678,
                "paidAmount": 1892,
                "bonusAmount": 0,
                "totalAmount": 1892,
            },
        ],
        "payMethods": [{"payMethod": m.pay_method, "easyPayProvider": m.easy_pay_provider} for m in PAY_METHODS],
        "paymentsEnabled": False,
        "identityGateEnabled": False,
        "dailyFreeChatTurns": 920_005,
        "policy": {
            "purchaseValidityYears": 920_002,
            "fullRefundDays": 920_003,
            "reducedRefundPercent": 920_004,
        },
        "priceVersion": 920_001,
    }


@pytest.mark.parametrize(
    ("judge", "key"),
    [
        pytest.param("payments_active", "paymentsEnabled", id="payments"),
        pytest.param("identity_gate_active", "identityGateEnabled", id="identity-gate"),
    ],
)
async def test_products_switches_follow_the_shared_judges(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, judge: str, key: str
) -> None:
    """두 스위치는 공개 가격 응답과 같은 판정 함수의 값이다. 깨지는 시나리오: 허브가 결제를 열었다고 보이는데 주문 생성은 503."""
    monkeypatch.setattr(clover_router, judge, lambda: True)

    assert (await db_client.get("/clover/products")).json()[key] is True


async def test_daily_free_chat_turns_is_zero_when_the_attendance_board_is_on(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """출석판 스위치가 켜지면 하루 무료 대화가 없어져 허브 안내 값도 0 이다. 상수를 표지 값으로 둔 채 0 이 나오는 것으로, 응답이
    상수를 그대로 싣지 않고 스위치를 읽는다는 것을 본다."""
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 920_005)
    monkeypatch.setattr(settings, "attendance_board_enabled", True)

    assert (await db_client.get("/clover/products")).json()["dailyFreeChatTurns"] == 0


async def test_products_does_not_touch_the_database(db_client: httpx.AsyncClient) -> None:
    with _count_queries() as get_count:
        resp = await db_client.get("/clover/products")

    assert resp.status_code == 200
    assert get_count() == 0
