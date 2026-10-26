"""가격 버전 대조 — 화면이 본 가격표가 서버의 지금 가격표와 다르면 클로버를 깎기 전에 멈춘다.

이 파일이 검증하는 성질:

1. 공개 가격 응답이 지금 가격표의 버전(`priceVersion`)을 싣는다.
2. 채팅 턴(전송·재생성·편집·빌더 미리보기)과 이미지 생성 요청이 가격 버전을 실어 왔는데 서버 버전과 다르면, **클로버를 실제로
   깎을 요청에서만** 409 `CLOVER_PRICE_CHANGED` 와 그 요청의 지금 금액(`currentCost`)을 내고 아무것도 깎지 않는다. 채팅은 SSE
   라우트라 스트림이 열리기 전의 JSON 오류 응답이어야 한다.
3. 무료로 지나는 턴(하루 무료분 안, 면제 계정)과 토큰으로 내는 이미지는 버전이 달라도 그대로 지난다 — 깎지 않는 요청을 막으면
   가격이 바뀐 날 무료 사용자까지 이유 없이 멈춘다.
4. 버전을 싣지 않은 요청(가격 버전을 모르는 배포 전 화면)은 지금처럼 처리한다.
5. 가격표를 등록부로 옮겨도 화면에 나가는 금액은 그대로다(아래 "금액 고정" 절) — 옮기기 전 코드와 옮긴 뒤 코드에서 같은
   값이 나와야 한다.

잔액은 `db_session.refresh(user)` 로 다시 읽는다. 차감은 별도 세션·별도 트랜잭션에서 일어나 테스트 세션의 인스턴스는 낡아 있다.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover, rate_limit_gate
from api.core.rate_limit_gate import ChatCharge, charge_chat_turn, enforce_image_rate_limit
from api.db.models import User
from api.db.models.clover import CloverLedger
from api.images.schemas import GenerateImageRequest
from api.llm.chat_models import (
    CHAT_MODELS,
    ChatModelId,
    chat_turn_cost,
    novel_episode_outline_unit_price,
    novel_episode_unit_price,
    novel_outline_unit_price,
)
from api.novel_public.purchases import chapter_price
from api.novelize.billing import chain_price, job_price
from api.novelize.episodes import k_max
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _login_as,
    _make_user_with_clover_lot,
    _override_llm_client,
    _parse_sse_events,
    _prepare_paid_turn,
)

_START_BALANCE = 1000
_PRICE_CHANGED = "CLOVER_PRICE_CHANGED"


def _stale() -> int:
    """서버 가격표와 다른 버전 — 화면이 가격이 바뀌기 전에 받은 버전이다."""
    return clover.PRICE_VERSION + 1


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    # 차감은 자기 트랜잭션이다. 테스트 커넥션에 묶어 같은 트랜잭션 안에서 읽고 되돌린다(`db_client` 와 같은 방식).
    return async_sessionmaker(bind=db.bind, expire_on_commit=False)


async def _member(db: AsyncSession, *, confirmed: bool = True, **overrides: object) -> User:
    """잔액만큼의 로트를 가진 회원. `confirmed` 면 오늘치 클로버 사용 확인을 마친 상태다."""
    if confirmed:
        overrides["clover_spend_confirmed_on"] = clover.kst_today(datetime.now(UTC))
    user = await _make_user_with_clover_lot(db, clover_balance=_START_BALANCE, **overrides)
    await db.flush()
    return user


async def _charge(
    db: AsyncSession, user: User, *, model: ChatModelId = "gemini", price_version: int | None
) -> ChatCharge:
    # 게이트 판정만 보므로 작품이 필요 없는 미리보기 사용처를 넘긴다(사용처 기록은 `test_clover_spend_usage_sites.py`).
    return await charge_chat_turn(
        user.id,
        db,
        _factory(db),
        model=model,
        price=chat_turn_cost(model),
        usage=clover.SpendUsage("preview"),
        price_version=price_version,
    )


async def _conflict(call: Callable[[], Awaitable[object]]) -> object:
    with pytest.raises(HTTPException) as caught:
        await call()
    assert caught.value.status_code == 409
    return caught.value.detail


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = (await db.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    return [(row.kind, row.amount) for row in rows]


async def _balance(db: AsyncSession, user: User) -> int:
    await db.refresh(user)
    return user.clover_balance


# ── 공개 가격 응답 ──────────────────────────────────────────────────────────────
async def test_pricing_reports_the_current_price_version(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """응답의 버전은 요청 때 서버 버전을 읽는다. 깨지는 시나리오: 응답이 버전 칸을 빠뜨리거나 숫자 사본을 들고 있어, 가격을 바꾸고
    버전을 올려도 화면이 옛 버전을 실어 보내 모든 유료 요청이 409 로 멈춘다."""
    monkeypatch.setattr(clover, "PRICE_VERSION", 41)

    resp = await db_client.get("/clover/pricing")

    assert (resp.status_code, resp.json().get("priceVersion")) == (200, 41)


# ── 채팅 게이트 ────────────────────────────────────────────────────────────────
async def test_paid_gemini_turn_with_a_stale_version_is_409_and_spends_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """하루 무료분을 다 쓴 Gemini 턴은 클로버로 낸다 — 그 턴의 버전이 다르면 지금 턴 가격을 실어 409 이고 원장이 비어 있다."""
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    user = await _member(db_session)

    detail = await _conflict(lambda: _charge(db_session, user, price_version=_stale()))

    assert detail == {"code": _PRICE_CHANGED, "currentCost": chat_turn_cost("gemini")}
    assert await _balance(db_session, user) == _START_BALANCE
    assert await _ledger(db_session, user.id) == []


async def test_stale_version_is_checked_before_the_daily_spend_confirmation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """오늘치 확인을 아직 안 한 회원도 버전이 다르면 확인 429 가 아니라 409 다. 확인 모달은 화면이 가진 가격으로 "클로버 N 개를
    써요"를 묻는데, 그 가격이 옛 값이면 옛 가격에 동의를 받는 것이다."""
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    user = await _member(db_session, confirmed=False)

    detail = await _conflict(lambda: _charge(db_session, user, price_version=_stale()))

    assert detail == {"code": _PRICE_CHANGED, "currentCost": chat_turn_cost("gemini")}


@pytest.mark.parametrize(
    "price_version",
    [pytest.param("current", id="current-version"), pytest.param(None, id="no-version")],
)
async def test_paid_gemini_turn_with_the_current_or_no_version_spends(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, price_version: str | None
) -> None:
    """위 409 의 짝 — 셋업이 같고 버전만 맞거나 없다. 버전이 없는 요청은 버전을 모르는 배포 전 화면이라 지금처럼 깎는다."""
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    user = await _member(db_session)

    charge = await _charge(
        db_session, user, price_version=clover.PRICE_VERSION if price_version == "current" else None
    )

    assert (charge.source, charge.clover_amount) == ("clover", chat_turn_cost("gemini"))
    assert await _ledger(db_session, user.id) == [("chat_spend", -chat_turn_cost("gemini"))]


@pytest.mark.parametrize(
    ("exempt", "source"),
    [pytest.param(False, "free", id="daily-free"), pytest.param(True, "skipped", id="exempt")],
)
async def test_free_turn_ignores_a_stale_version(
    db_session: AsyncSession, exempt: bool, source: str
) -> None:
    """하루 무료분 안의 턴과 면제 계정의 턴은 아무것도 깎지 않으므로 버전이 달라도 지난다. 깨지는 시나리오: 대조를 게이트 맨 앞에
    두어, 가격이 바뀐 날 옛 화면을 연 무료 사용자의 대화가 전부 409 로 멈춘다."""
    user = await _member(db_session, rate_limit_exempt=exempt)

    charge = await _charge(db_session, user, price_version=_stale())

    assert charge.source == source
    assert await _ledger(db_session, user.id) == []


async def test_premium_turn_with_a_stale_version_is_409_and_spends_nothing(db_session: AsyncSession) -> None:
    """상위 모델 턴은 무료분 없이 늘 클로버로 낸다 — 버전이 다르면 그 모델의 지금 턴 가격으로 409 다."""
    user = await _member(db_session)

    detail = await _conflict(lambda: _charge(db_session, user, model="opus", price_version=_stale()))

    assert detail == {"code": _PRICE_CHANGED, "currentCost": chat_turn_cost("opus")}
    assert await _ledger(db_session, user.id) == []


async def test_unverified_member_turn_with_a_stale_version_is_409_and_spends_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """본인인증 게이트에 걸린 회원은 무료분이 0 이라 Gemini 턴도 클로버로 낸다 — 이 갈래도 버전이 다르면 409 다."""
    monkeypatch.setattr(rate_limit_gate, "is_identity_gated", lambda _user: True)
    user = await _member(db_session)

    detail = await _conflict(lambda: _charge(db_session, user, price_version=_stale()))

    assert detail == {"code": _PRICE_CHANGED, "currentCost": chat_turn_cost("gemini")}
    assert await _ledger(db_session, user.id) == []


# ── 채팅 라우트 ────────────────────────────────────────────────────────────────
_SURFACES = pytest.mark.parametrize("surface", ["send", "edit", "regenerate", "preview"])


def _with_version(body: dict[str, object] | None, version: int) -> dict[str, object]:
    return {**(body or {}), "priceVersion": version}


@_SURFACES
async def test_paid_chat_turn_with_a_stale_version_is_a_409_before_the_stream(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    """네 경로 모두 요청 본문의 버전을 게이트가 읽는다. 409 는 SSE 스트림이 아니라 JSON 오류 응답이다 — 스트림 안에서 오류를
    던지면 커넥션이 깨진다. 재생성은 원래 본문이 없는 요청이라 버전을 싣는 본문이 새로 생긴다."""
    user, method, path, body = await _prepare_paid_turn(
        db_client, db_session, monkeypatch, surface=surface, balance=_START_BALANCE
    )
    spent_in_setup = await _ledger(db_session, user.id)

    _override_llm_client(_FakeLLMClient(tokens=["안", "녕"]))
    try:
        resp = await db_client.request(method, path, json=_with_version(body, _stale()))
    finally:
        _clear_llm_override()

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": _PRICE_CHANGED, "currentCost": chat_turn_cost("gemini")}
    assert await _ledger(db_session, user.id) == spent_in_setup


@_SURFACES
async def test_paid_chat_turn_with_the_current_version_runs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    """위 409 의 짝 — 버전이 맞으면 턴이 끝까지 돌고 그 턴 가격을 깎는다. 재생성에 본문을 실어도 받는다."""
    user, method, path, body = await _prepare_paid_turn(
        db_client, db_session, monkeypatch, surface=surface, balance=_START_BALANCE
    )

    _override_llm_client(_FakeLLMClient(tokens=["안", "녕"]))
    try:
        resp = await db_client.request(method, path, json=_with_version(body, clover.PRICE_VERSION))
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert [event["type"] for event in _parse_sse_events(resp.text)][-1] == "done"
    assert ("chat_spend", -chat_turn_cost("gemini")) in await _ledger(db_session, user.id)


# ── 이미지 ────────────────────────────────────────────────────────────────────
def _image_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt": "a cat wizard",
        "model": "v1",
        "style": "soft_portrait",
        "aspectRatio": "1:1",
        "count": 2,
    }
    payload.update(overrides)
    return payload


async def test_clover_paid_image_with_a_stale_version_is_409_and_spends_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """무료 토큰을 다 써 클로버로 낼 이미지 요청의 버전이 다르면 그 요청의 지금 금액(장수 × 장당 가격)으로 409 다."""
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)
    user = await _member(db_session)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/images/generate", json=_image_request(priceVersion=_stale()))

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": _PRICE_CHANGED, "currentCost": 2 * clover.IMAGE_UNIT_COST}
    assert await _balance(db_session, user) == _START_BALANCE
    assert await _ledger(db_session, user.id) == []


async def test_token_paid_image_ignores_a_stale_version(db_session: AsyncSession) -> None:
    """무료 토큰으로 내는 이미지는 클로버를 깎지 않으므로 버전이 달라도 지난다."""
    user = await _member(db_session)

    charge = await enforce_image_rate_limit(
        GenerateImageRequest.model_validate(_image_request(priceVersion=_stale())),
        user_id=user.id,
        db=db_session,
        session_factory=_factory(db_session),
    )

    assert charge.source == "token"
    assert await _ledger(db_session, user.id) == []


@pytest.mark.parametrize(
    "price_version",
    [pytest.param("current", id="current-version"), pytest.param(None, id="no-version")],
)
async def test_clover_paid_image_with_the_current_or_no_version_spends(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, price_version: str | None
) -> None:
    """이미지 409 의 짝 — 버전이 맞거나 없으면 지금처럼 클로버로 낸다."""
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)
    user = await _member(db_session)
    overrides = {"priceVersion": clover.PRICE_VERSION} if price_version == "current" else {}

    charge = await enforce_image_rate_limit(
        GenerateImageRequest.model_validate(_image_request(**overrides)),
        user_id=user.id,
        db=db_session,
        session_factory=_factory(db_session),
    )

    assert (charge.source, charge.clover_amount) == ("clover", 2 * clover.IMAGE_UNIT_COST)


# ── 금액 고정 ─────────────────────────────────────────────────────────────────
# 가격표를 등록부 하나로 옮기는 변경은 값을 바꾸지 않는다. 아래 두 테스트는 옮기기 전 코드에서도 초록이어야 한다 — 그래서 상수
# 이름이 아니라 가격을 내는 함수와 응답만 본다. 방 응답·모델 목록의 턴 가격, 소설 상태·모델 선택지의 화 단가, 구성 흐름 모델
# 목록의 구성안 단가, 노벨 상태의 화 가격은 모두 아래 함수가 낸 값을 그대로 싣는다.
_MODEL_PRICES: dict[ChatModelId, tuple[int, int, int, int]] = {
    # (채팅 턴, 소설 화, 전체 구성안, 장면 구성안)
    "gemini": (10, 80, 190, 80),
    "sonnet": (60, 180, 330, 180),
    "opus": (200, 300, 690, 300),
}


def test_price_functions_return_the_policy_values() -> None:
    """모델 셋의 네 단가와, 그 단가로 계산하는 작업 금액(화 생성·다시 만들기·원고·구성안·장면 구성안·AI 수정·연쇄 묶음 하나),
    노벨 화 가격(앞 다섯 화 무료, 그 뒤 30)이 정한 값 그대로다."""
    assert {
        m.id: (
            chat_turn_cost(m.id),
            novel_episode_unit_price(m.id),
            novel_outline_unit_price(m.id),
            novel_episode_outline_unit_price(m.id),
        )
        for m in CHAT_MODELS
    } == _MODEL_PRICES
    for model, (_, episode, outline, episode_outline) in _MODEL_PRICES.items():
        assert job_price("chapter_generate", model, 3) == 3 * episode, model
        assert job_price("chapter_regenerate", model) == episode, model
        assert job_price("outline_chapter_generate", model) == episode, model
        assert job_price("outline_generate", model) == outline, model
        assert job_price("episode_outline_generate", model) == episode_outline, model
        assert job_price("ai_edit", model) == 30, model
        # 묶음 하나의 화 수 상한은 가격이 아니라 설정이라 그 값을 곱한다.
        assert chain_price(model, 1) == k_max(model) * episode, model
    assert [chapter_price(ordinal, 30) for ordinal in (1, 5, 6)] == [0, 0, 30]


async def test_pricing_response_amounts_are_the_policy_values(db_client: httpx.AsyncClient) -> None:
    """공개 가격 응답의 금액 칸이 정한 값 그대로다. 기능 스위치·상품·결제수단처럼 금액이 아닌 칸은 다른 테스트가 본다."""
    body = (await db_client.get("/clover/pricing")).json()

    amounts = {
        key: body[key]
        for key in (
            "chatTurnCost",
            "imageCost",
            "novelEpisodeCost",
            "novelAiEditCost",
            "dailyFreeChatTurns",
            "novelReadCost",
            "novelFreeChapterCount",
            "memorySummaryRegenerateCost",
        )
    }
    assert amounts == {
        "chatTurnCost": 10,
        "imageCost": 30,
        "novelEpisodeCost": 80,
        "novelAiEditCost": 30,
        "dailyFreeChatTurns": 15,
        "novelReadCost": 30,
        "novelFreeChapterCount": 5,
        "memorySummaryRegenerateCost": 10,
    }
    assert [(m["id"], m["chatTurnCost"], m["novelEpisodeCost"]) for m in body["models"]] == [
        ("gemini", 10, 80),
        ("opus", 200, 300),
    ]
