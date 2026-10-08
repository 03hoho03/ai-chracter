"""공개 `GET /clover/pricing` — 클로버 충전 상품과 기본 모델 기준 사용 단가.

이 파일이 검증하는 성질:

1. 로그인하지 않은 요청도 200이다 — 세션·재동의 게이트가 붙으면 비로그인 방문자가 상품 안내를 못 본다.
2. 응답은 요청 시점의 상품 목록과 `core/clover.py` 단가 상수를 따른다 — 상수를 바꾼 뒤 응답이 따라오는지로 확인한다.
   응답을 오늘의 상수 값과 비교만 하면 라우트가 숫자 사본을 들고 있어도 통과하므로 그렇게 쓰지 않는다.
3. 상위 모델 단가와 소설 단가는 응답에 없다 — 상위 모델은 허용 계정만 쓰고 소설은 허용 명단 전용이라 공개하지 않는다.
4. 상품 정의가 지금의 가격 규칙을 지킨다(아래 테스트 docstring).

`db_client` 를 쓰는 이유는 DB 가 아니라 쿠키다 — 세션 스코프 `api_client` 는 앞 테스트의 세션 쿠키를 들고 있을 수
있는데, `db_client` 가 쿠키를 비운 채로 넘겨준다.
"""

import json

import httpx
import pytest

from api.clover import products
from api.clover.products import CloverProduct
from api.core import clover


async def test_anonymous_request_returns_pricing(db_client: httpx.AsyncClient) -> None:
    assert not db_client.cookies

    resp = await db_client.get("/clover/pricing")

    assert resp.status_code == 200
    body = resp.json()
    assert [p["key"] for p in body["products"]] == [p.key for p in products.CLOVER_PRODUCTS]


async def test_response_follows_products_and_cost_constants(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        products,
        "CLOVER_PRODUCTS",
        (
            CloverProduct(key="pro", name="가짜 상품 하나", price_krw=1234, paid_amount=411, bonus_amount=7),
            CloverProduct(key="starter", name="가짜 상품 둘", price_krw=5678, paid_amount=1892, bonus_amount=0),
        ),
    )
    monkeypatch.setattr(clover, "CHAT_TURN_COST", 997)
    monkeypatch.setattr(clover, "IMAGE_UNIT_COST", 998)

    resp = await db_client.get("/clover/pricing")

    assert resp.status_code == 200
    assert resp.json() == {
        "products": [
            {"key": "pro", "name": "가짜 상품 하나", "priceKrw": 1234, "paidAmount": 411, "bonusAmount": 7},
            {"key": "starter", "name": "가짜 상품 둘", "priceKrw": 5678, "paidAmount": 1892, "bonusAmount": 0},
        ],
        "chatTurnCost": 997,
        "imageCost": 998,
    }


async def test_premium_and_novel_costs_are_not_exposed(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """공개하지 않는 단가를 다른 어떤 값과도 겹치지 않는 표지 값으로 바꿔 두고, 응답 어디에도 그 값이 없음을 본다 —
    키 이름을 바꿔 실어도 값으로 잡힌다."""
    hidden = {
        "CHAT_TURN_COST_SONNET": 910_001,
        "CHAT_TURN_COST_OPUS": 910_002,
        "NOVELIZE_EPISODE_COST": 910_003,
        "NOVELIZE_EPISODE_COST_SONNET": 910_004,
        "NOVELIZE_EPISODE_COST_OPUS": 910_005,
        "NOVELIZE_AI_EDIT_COST": 910_006,
    }
    for name, value in hidden.items():
        monkeypatch.setattr(clover, name, value)

    resp = await db_client.get("/clover/pricing")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"products", "chatTurnCost", "imageCost"}
    raw = json.dumps(body)
    for value in hidden.values():
        assert str(value) not in raw


def test_products_follow_the_provisional_pricing_rule() -> None:
    """상품마다 가격이 5만 원 미만이고, 보너스가 음수가 아니며, 가격이 유료 수량 × 3원이다.

    5만 원 미만은 결제대행사의 충전형 상품 한도를 넘지 않으려는 보수적 상한이다. "가격 = 유료 수량 × 3" 은 1클로버를
    3원(부가세 포함)으로 잡은 **임시 가격 규칙**을 고정하는 것이라, 원가를 다시 재서 그 환산을 바꾸면 이 단언이 깨지는 게
    맞다 — 그때는 새 규칙에 맞게 이 테스트를 고친다.
    """
    assert products.CLOVER_PRODUCTS
    for product in products.CLOVER_PRODUCTS:
        assert product.price_krw < 50_000, product.key
        assert product.bonus_amount >= 0, product.key
        assert product.price_krw == product.paid_amount * 3, product.key
