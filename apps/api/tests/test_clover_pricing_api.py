"""공개 `GET /clover/pricing` — 클로버 충전 상품과 모든 사용처·모델의 사용 단가.

이 파일이 검증하는 성질:

1. 로그인하지 않은 요청도 200이다 — 세션·재동의 게이트가 붙으면 비로그인 방문자가 상품 안내를 못 본다.
2. 응답은 요청 시점의 상품 목록과 `core/clover.py` 단가 상수를 따른다 — 상수를 바꾼 뒤 응답이 따라오는지로 확인한다.
   응답을 오늘의 상수 값과 비교만 하면 라우트가 숫자 사본을 들고 있어도 통과하므로 그렇게 쓰지 않는다.
3. 상위 모델 단가와 소설 단가(화·AI 수정)도 응답에 실린다 — 구매 전 안내에 없는 사용처 가격은 숨은 가격으로 읽힌다.
   모델 레지스트리의 모든 모델이 실리고, 허용된 계정만 쓰는 사용처는 그 사실이 함께 실린다.
   노벨 화 소장 가격과 무료 화 수도 싣는다.
4. 상품 정의가 지금의 가격 규칙을 지킨다(아래 테스트 docstring).

`db_client` 를 쓰는 이유는 DB 가 아니라 쿠키다 — 세션 스코프 `api_client` 는 앞 테스트의 세션 쿠키를 들고 있을 수
있는데, `db_client` 가 쿠키를 비운 채로 넘겨준다.
"""

import uuid

import httpx
import pytest

from api.clover import products
from api.core.config import settings
from api.clover.products import CloverProduct
from api.core import clover, rate_limit_gate
from api.llm.chat_models import CHAT_MODELS

# 지금 상품표 이전에 팔던 상품의 키. 결제 행(`payments.product_key`)이 이 키를 그대로 갖고 있고 어드민이 그 값을
# 보여 주므로, 같은 키를 다른 가격의 상품에 다시 쓰면 과거 결제와 새 결제가 한 상품으로 섞여 보인다.
_RETIRED_PRODUCT_KEYS = {"starter", "basic", "plus", "pro"}


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
            CloverProduct(key="max", name="가짜 상품 하나", price_krw=1234, paid_amount=411, bonus_amount=7),
            CloverProduct(key="mini", name="가짜 상품 둘", price_krw=5678, paid_amount=1892, bonus_amount=0),
        ),
    )
    monkeypatch.setattr(clover, "CHAT_TURN_COST", 997)
    monkeypatch.setattr(clover, "IMAGE_UNIT_COST", 998)
    monkeypatch.setattr(clover, "NOVEL_READ_COST", 996)
    monkeypatch.setattr(clover, "NOVEL_FREE_CHAPTER_COUNT", 995)

    resp = await db_client.get("/clover/pricing")

    assert resp.status_code == 200
    body = resp.json()
    # 결제 여부·결제수단은 결제 테스트(`test_payments_api.py`)가, 모델별·소설 단가와 무료 대화 수는 아래 테스트가 본다.
    for key in (
        "paymentsEnabled",
        "payMethods",
        "identityGateEnabled",
        "models",
        "novelAiEditCost",
        "novelRestricted",
        "dailyFreeChatTurns",
    ):
        del body[key]
    assert body == {
        "products": [
            {"key": "max", "name": "가짜 상품 하나", "priceKrw": 1234, "paidAmount": 411, "bonusAmount": 7},
            {"key": "mini", "name": "가짜 상품 둘", "priceKrw": 5678, "paidAmount": 1892, "bonusAmount": 0},
        ],
        "chatTurnCost": 997,
        "imageCost": 998,
        "novelReadCost": 996,
        "novelFreeChapterCount": 995,
    }


async def test_every_model_and_novel_cost_is_exposed(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """모든 단가 상수와 무료 대화 수를 서로 겹치지 않는 표지 값으로 바꿔 두면 응답이 그 값을 모델별로 그대로 싣는다.
    모델 목록은 레지스트리 전체를 레지스트리 순서대로 담는다 — 레지스트리에 모델을 더하고 응답에 빠뜨리면 깨진다.
    기본 모델만 누구나 쓰고, 상위 모델과 소설은 허용된 계정 전용이다(`llm/model_access.py`·`novelize/access.py`)."""
    sentinels = {
        "CHAT_TURN_COST": 910_001,
        "CHAT_TURN_COST_SONNET": 910_002,
        "CHAT_TURN_COST_OPUS": 910_003,
        "NOVELIZE_EPISODE_COST": 910_004,
        "NOVELIZE_EPISODE_COST_SONNET": 910_005,
        "NOVELIZE_EPISODE_COST_OPUS": 910_006,
        "NOVELIZE_AI_EDIT_COST": 910_007,
    }
    for name, value in sentinels.items():
        monkeypatch.setattr(clover, name, value)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 910_008)

    resp = await db_client.get("/clover/pricing")

    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body["models"]] == [m.id for m in CHAT_MODELS]
    assert body["models"] == [
        {
            "id": "gemini",
            "name": "Gemini",
            "isDefault": True,
            "restricted": False,
            "chatTurnCost": 910_001,
            "novelEpisodeCost": 910_004,
        },
        {
            "id": "sonnet",
            "name": "Claude Sonnet 4.6",
            "isDefault": False,
            "restricted": True,
            "chatTurnCost": 910_002,
            "novelEpisodeCost": 910_005,
        },
        {
            "id": "opus",
            "name": "Claude Opus 4.6",
            "isDefault": False,
            "restricted": True,
            "chatTurnCost": 910_003,
            "novelEpisodeCost": 910_006,
        },
    ]
    assert body["chatTurnCost"] == sentinels["CHAT_TURN_COST"]
    assert body["novelAiEditCost"] == 910_007
    assert body["novelRestricted"] is True
    assert body["dailyFreeChatTurns"] == 910_008


@pytest.mark.parametrize(
    ("switch", "allowlist"),
    [
        pytest.param("chat_premium_models_enabled", "chat_premium_model_allowlist", id="chat-premium"),
        pytest.param("novelize_premium_models_enabled", "novelize_premium_model_allowlist", id="novel-premium"),
        pytest.param("novelize_enabled", "novelize_grant_allowlist", id="novelize"),
    ],
)
async def test_restricted_marks_do_not_reveal_switches(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, switch: str, allowlist: str
) -> None:
    """허용 전용 표시는 구조에서 오는 값이라 스위치를 켜고 명단을 채워도 그대로다. 스위치에 따라 값이 바뀌면 비로그인
    방문자가 기능이 켜졌는지 알게 된다 — 소설 라우트가 꺼짐·미허용을 한 가지 거부로 내는 것과 같은 이유다."""
    before = (await db_client.get("/clover/pricing")).json()
    monkeypatch.setattr(settings, switch, True)
    monkeypatch.setattr(settings, allowlist, [uuid.uuid4()])

    after = (await db_client.get("/clover/pricing")).json()

    assert after == before


def test_products_follow_the_pricing_rule() -> None:
    """상품마다 가격이 5만 원 미만이고, 유료 수량이 0보다 크고, 보너스가 0 이상 유료 수량의 20% 이하이며, 가격이 유료
    수량 × 3원이다. 키는 서로 다르고 예전 상품의 키를 다시 쓰지 않는다.

    5만 원 미만은 결제대행사의 충전형 상품 한도를 넘지 않으려는 보수적 상한이다. 유료 수량이 0이면 환불 견적이 결제액을
    유료 수량으로 나눌 때 0으로 나누고, 주문 행은 CHECK 제약에 걸려 500이 된다. 보너스 20%
    상한은 보너스가 가장 많은 상품에서도 상위 모델 사용 원가가 판매가 안에 드는 선이다. "가격 = 유료 수량 × 3" 은
    1클로버를 3원(부가세 포함)으로 잡은 환산이라, 그 환산을 바꾸면 이 단언이 깨지는 게 맞다 — 그때는 새 규칙에 맞게
    이 테스트를 고친다.
    """
    assert products.CLOVER_PRODUCTS
    keys = [product.key for product in products.CLOVER_PRODUCTS]
    assert len(keys) == len(set(keys))
    assert not set(keys) & _RETIRED_PRODUCT_KEYS
    for product in products.CLOVER_PRODUCTS:
        assert product.price_krw < 50_000, product.key
        assert product.paid_amount > 0, product.key
        assert product.bonus_amount >= 0, product.key
        assert product.bonus_amount * 100 <= product.paid_amount * 20, product.key
        assert product.price_krw == product.paid_amount * 3, product.key


@pytest.mark.parametrize("gate", [pytest.param(False, id="gate-off"), pytest.param(True, id="gate-on")])
async def test_pricing_exposes_the_identity_gate_switch(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, gate: bool
) -> None:
    """로그인하지 않은 방문자의 정책 문장이 이 값으로 갈린다 — `GET /me` 의 게이트 값과 같은 판정이다."""
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "identity_gate_enabled", gate)

    assert (await db_client.get("/clover/pricing")).json()["identityGateEnabled"] is gate
