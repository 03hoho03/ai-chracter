"""공개 `GET /clover/pricing` — 클로버 충전 상품과 일반 회원이 쓸 수 있는 모든 사용처·채팅에서 고를 수 있는 모델의 사용 단가.

이 파일이 검증하는 성질:

1. 로그인하지 않은 요청도 200이다 — 세션·재동의 게이트가 붙으면 비로그인 방문자가 상품 안내를 못 본다.
2. 응답은 요청 시점의 상품 목록과 `core/clover.py` 의 가격 등록부·단가 상수를 따른다 — 상수를 바꾼 뒤 응답이 따라오는지로 확인한다.
   응답을 오늘의 상수 값과 비교만 하면 라우트가 숫자 사본을 들고 있어도 통과하므로 그렇게 쓰지 않는다.
3. 상위 모델 단가와 소설 단가(화·AI 수정)도 응답에 실린다 — 구매 전 안내에 없는 사용처 가격은 숨은 가격으로 읽힌다.
   모델 목록은 채팅에서 고를 수 있는 모델만 싣고, 베타 표시는 스위치와 무관한 고정 값이다. 허용된 계정만 쓰는 소설은
   그 사실이 함께 실린다. 소설 상위 모델의 화 단가는 일반 회원이 살 수 없어 따로 싣지 않는다. 노벨 화 소장 가격과
   무료 화 수, 대화방 요약 다시 만들기 가격도 싣는다.
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
from factories import _set_model_price

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
    _set_model_price(monkeypatch, "gemini", chat_turn=997)
    monkeypatch.setattr(clover, "IMAGE_UNIT_COST", 998)
    monkeypatch.setattr(clover, "NOVEL_READ_COST", 996)
    monkeypatch.setattr(clover, "NOVEL_FREE_CHAPTER_COUNT", 995)
    monkeypatch.setattr(clover, "MEMORY_SUMMARY_REGENERATE_COST", 994)

    resp = await db_client.get("/clover/pricing")

    assert resp.status_code == 200
    body = resp.json()
    # 결제 여부·결제수단은 결제 테스트(`test_payments_api.py`)가, 모델별·소설 단가와 무료 대화 수는 아래 테스트가, 노벨 켜짐
    # 여부는 노벨 독자 테스트(`test_webnovel_reading.py`)가 본다.
    for key in (
        "paymentsEnabled",
        "novelPublicEnabled",
        "novelPublicPolicyV2Enabled",
        "novelIllustrationsEnabled",
        "novelizeOutlineFlowEnabled",
        "novelizeMultiBlockEditEnabled",
        "payMethods",
        "identityGateEnabled",
        "models",
        "novelAiEditCost",
        "novelRestricted",
        "novelEpisodeCost",
        "dailyFreeChatTurns",
    ):
        del body[key]
    assert body == {
        "products": [
            {"key": "max", "name": "가짜 상품 하나", "priceKrw": 1234, "paidAmount": 411, "bonusAmount": 7},
            {"key": "mini", "name": "가짜 상품 둘", "priceKrw": 5678, "paidAmount": 1892, "bonusAmount": 0},
        ],
        "priceVersion": clover.PRICE_VERSION,
        "chatTurnCost": 997,
        "imageCost": 998,
        "novelReadCost": 996,
        "novelFreeChapterCount": 995,
        "memorySummaryRegenerateCost": 994,
    }


async def test_chat_selectable_models_and_novel_cost_are_exposed(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """모든 단가 상수와 무료 대화 수를 서로 겹치지 않는 표지 값으로 바꿔 두면 응답이 그 값을 모델별로 그대로 싣는다.
    모델 목록은 레지스트리에서 채팅에서 고를 수 있는 모델만 레지스트리 순서대로 담는다 — 이 목록은 채팅 모델 안내라 채팅에서
    고를 수 없는 Sonnet 을 실으면 채팅에서 살 수 없는 선택지가 보이고, 고를 수 있는 모델을 빠뜨리면 숨은 가격이 된다.
    Sonnet 은 소설 상위 모델로 쓰이지만 별도 허용 명단에 든 계정만 써서 일반 회원은 살 수 없으므로 그 화 단가도 따로 싣지
    않는다. 행에 허용 전용 표시는 없고 베타 표시가 있다. 모델별 소설 화 단가 칸은 그 칸을 가드 없이 읽는 옛 화면을 위해
    남아 있어 Opus 행의 소설 화 단가는 계속 보이고, 기본 모델의 소설 화 단가는 최상위 칸에도 실린다."""
    _set_model_price(monkeypatch, "gemini", chat_turn=910_001, novel_episode=910_004)
    _set_model_price(monkeypatch, "sonnet", chat_turn=910_002, novel_episode=910_005)
    _set_model_price(monkeypatch, "opus", chat_turn=910_003, novel_episode=910_006)
    monkeypatch.setattr(clover, "NOVELIZE_AI_EDIT_COST", 910_007)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 910_008)

    resp = await db_client.get("/clover/pricing")

    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body["models"]] == [m.id for m in CHAT_MODELS if m.chat_selectable] == ["gemini", "opus"]
    assert body["models"] == [
        {
            "id": "gemini",
            "name": "Gemini",
            "isDefault": True,
            "beta": False,
            "chatTurnCost": 910_001,
            "novelEpisodeCost": 910_004,
        },
        {
            "id": "opus",
            "name": "Claude Opus 5.5",
            "isDefault": False,
            "beta": True,
            "chatTurnCost": 910_003,
            "novelEpisodeCost": 910_006,
        },
    ]
    assert body["chatTurnCost"] == 910_001
    assert body["novelEpisodeCost"] == 910_004
    assert body["novelAiEditCost"] == 910_007
    assert body["novelRestricted"] is True
    assert body["dailyFreeChatTurns"] == 910_008


@pytest.mark.parametrize(
    ("switch", "allowlist"),
    [
        pytest.param("chat_premium_models_enabled", None, id="chat-premium"),
        pytest.param("novelize_premium_models_enabled", "novelize_premium_model_allowlist", id="novel-premium"),
        pytest.param("novelize_enabled", "novelize_grant_allowlist", id="novelize"),
    ],
)
async def test_pricing_does_not_reveal_switches(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, switch: str, allowlist: str | None
) -> None:
    """비로그인 응답은 스위치를 켜고 명단을 채워도 그대로다(채팅 상위 모델은 명단이 없다) — 모델 행과 베타 표시, 소설의
    허용 전용 표시는 모두 고정 값이다. 스위치에 따라 값이 바뀌면 비로그인 방문자가 기능이 켜졌는지 알게 된다 — 소설
    라우트가 꺼짐·미허용을 한 가지 거부로 내는 것과 같은 이유다."""
    before = (await db_client.get("/clover/pricing")).json()
    monkeypatch.setattr(settings, switch, True)
    if allowlist is not None:
        monkeypatch.setattr(settings, allowlist, [uuid.uuid4()])

    after = (await db_client.get("/clover/pricing")).json()

    assert after == before
    assert [m["id"] for m in after["models"]] == ["gemini", "opus"]
    assert all("restricted" not in m for m in after["models"])


def test_products_follow_the_pricing_rule() -> None:
    """상품마다 가격이 5만 원 미만이고, 유료 수량이 0보다 크고, 보너스가 0 이상 유료 수량의 20% 이하이며, 가격이 유료
    수량 × 클로버 단위(`CLOVER_UNIT_KRW`, 원)다. 키는 서로 다르고 예전 상품의 키를 다시 쓰지 않는다.

    5만 원 미만은 결제대행사의 충전형 상품 한도를 넘지 않으려는 보수적 상한이다. 유료 수량이 0이면 환불 견적이 결제액을
    유료 수량으로 나눌 때 0으로 나누고, 주문 행은 CHECK 제약에 걸려 500이 된다. 보너스 20%
    상한은 정책값이다 — 보너스가 붙을수록 1클로버로 원가에 쓸 수 있는 돈이 줄어든다. 가격과 유료 수량은 이 코드의 클로버
    단위로 환산한 값이라 단위를 바꾸면 상품표도 함께 바뀌어야 한다 — 한쪽만 바뀌면 결제액과 지급량이 어긋난다.
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
        assert product.price_krw == product.paid_amount * clover.CLOVER_UNIT_KRW, product.key


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


@pytest.mark.parametrize("switch", [pytest.param(False, id="policy-off"), pytest.param(True, id="policy-on")])
async def test_pricing_exposes_the_novel_public_policy_switch(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, switch: bool
) -> None:
    """노벨 구매 전 고지와 작가의 공개 거두기 안내(거두거나 제재되면 산 사람이 계속 읽는가, 환급받는가)가 이 값으로 갈린다 —
    노벨 정책 스위치 그대로다. 깨지는 시나리오: 스위치를 켰는데 구매 화면이 "공개가 끝나도 돌려드리지 않아요"라는 옛 약관
    문장을 그대로 보인다."""
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", switch)

    resp = await db_client.get("/clover/pricing")

    assert (resp.status_code, resp.json().get("novelPublicPolicyV2Enabled")) == (200, switch)


@pytest.mark.parametrize("switch", [pytest.param(False, id="off"), pytest.param(True, id="on")])
async def test_pricing_exposes_the_novel_illustrations_switch(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, switch: bool
) -> None:
    """작가 화면의 삽화 붙이기 진입이 이 값으로 열린다 — 삽화 스위치 그대로다. 깨지는 시나리오: 스위치가 꺼졌는데 화면이 붙이기
    버튼을 보여 누르는 족족 404 가 나거나, 켰는데 진입이 보이지 않는다."""
    monkeypatch.setattr(settings, "novel_illustrations_enabled", switch)

    resp = await db_client.get("/clover/pricing")

    assert (resp.status_code, resp.json().get("novelIllustrationsEnabled")) == (200, switch)


@pytest.mark.parametrize("switch", [pytest.param(False, id="off"), pytest.param(True, id="on")])
async def test_pricing_exposes_the_novel_outline_flow_switch(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, switch: bool
) -> None:
    """작가 화면이 구간 선택·구성안 흐름으로 들어갈지를 이 값으로 가른다 — 구성 흐름 스위치 그대로다. 깨지는 시나리오: 스위치가
    꺼졌는데 화면이 새 흐름 진입을 보여 누르는 족족 404 가 나거나, 켰는데 옛 흐름만 보인다."""
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", switch)

    resp = await db_client.get("/clover/pricing")

    assert (resp.status_code, resp.json().get("novelizeOutlineFlowEnabled")) == (200, switch)


@pytest.mark.parametrize("switch", [pytest.param(False, id="off"), pytest.param(True, id="on")])
async def test_pricing_exposes_the_novel_multi_block_edit_switch(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, switch: bool
) -> None:
    """작가 화면이 여러 문단을 골라 고치는 입력으로 들어갈지를 이 값으로 가른다 — 여러 문단 수정 스위치 그대로다. 깨지는 시나리오:
    스위치가 꺼졌는데 화면이 새 선택을 보여 맡기는 족족 404 가 나거나, 켰는데 옛 연속 범위 선택만 보인다."""
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", switch)

    resp = await db_client.get("/clover/pricing")

    assert (resp.status_code, resp.json().get("novelizeMultiBlockEditEnabled")) == (200, switch)
