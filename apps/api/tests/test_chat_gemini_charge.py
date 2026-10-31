"""Gemini 턴은 면제 계정 밖에서 첫 턴부터 클로버로 낸다 — 하루 무료 대화가 없고, 출석 보상이 그 자리를 맡는다.

이 파일이 검증하는 성질:

1. 면제 계정 밖의 Gemini 턴(빌더 미리보기 포함)은 첫 턴부터 클로버로 낸다. 하루 창을 세지 않고, 하루 1회 확인도 묻지 않는다 —
   무료분이 없으니 "무료분을 다 쓴 순간"이 없고, 확인은 그 순간에 묻던 것이다.
2. 잔액이 모자라면 인증 회원은 429 `CLOVER_REQUIRED`, 본인인증 게이트에 걸린 회원은 403 `IDENTITY_VERIFICATION_REQUIRED` 다.
3. 버스트 검사가 Redis 장애로 깨져도 무료로 통과시키지 않는다(차감은 Redis 를 쓰지 않는다). 면제 계정은 장애 중에도 내지 않고,
   상위 모델 턴은 503 이다.
4. 정지 스위치와 가격 버전 대조는 클로버로 내는 다른 갈래와 같은 자리에서 막는다.
5. 이미지의 하루 1회 확인은 그대로다.

차감 단언이 셋업만으로 통과하지 않음은 같은 셋업의 면제 계정이 `skipped`·잔액 그대로인 것(`test_exempt_member_is_not_charged`)이
보인다.

채팅 차감 판정은 `charge_chat_turn` 을 직접 부른다(LLM·방 없이 판정만). 실제 방 전송의 턴 기록은 `test_clover_gate.py` 가 본다.
본인인증 설정은 로컬 `.env` 가 아니라 아래 autouse 픽스처가 채운다 — 게이트는 그 설정이 있어야 켜진다.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.router import enforce_preview_chat_charge
from api.chat.schemas import ChatMessageCreateRequest
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.rate_limit import check_rate_limit, seconds_until_kst_midnight
from api.core.rate_limit_gate import ChatCharge, charge_chat_turn, enforce_image_rate_limit
from api.db.models.auth import User
from api.db.models.clover import CloverLedger
from api.images.schemas import GenerateImageRequest
from api.llm.chat_models import DEFAULT_CHAT_MODEL, ChatModelId, chat_turn_cost
from factories import _make_user_with_clover_lot

_PRICE = chat_turn_cost(DEFAULT_CHAT_MODEL)


@pytest.fixture(autouse=True)
def _identity_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """미인증 회원 게이트는 끈 채로 시작한다(게이트를 켜는 경우는 그 테스트가 켠다)."""
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "identity_gate_enabled", False)


async def _member(db: AsyncSession, **overrides: object) -> User:
    """`balance` 를 주면 그만큼의 로트도 함께 만든다(차감이 로트에서 깎는다). 오늘치 확인 칸은 비워 둔다 — 새 회원의 참값이고,
    확인 없이 깎인다는 단언이 셋업으로 통과하지 않게 한다."""
    balance = overrides.pop("balance", 0)
    assert isinstance(balance, int)
    user = await _make_user_with_clover_lot(db, clover_balance=balance, **overrides)
    await db.flush()
    return user


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    # 차감은 자기 트랜잭션이다. 테스트 커넥션에 묶어 같은 트랜잭션 안에서 읽고 되돌린다(`db_client` 와 같은 방식).
    return async_sessionmaker(bind=db.bind, expire_on_commit=False)


async def _charge(
    db: AsyncSession, user: User, *, model: ChatModelId = DEFAULT_CHAT_MODEL, price_version: int | None = None
) -> ChatCharge:
    # 게이트 판정만 보므로 작품이 필요 없는 미리보기 사용처를 넘긴다.
    return await charge_chat_turn(
        user.id,
        db,
        _factory(db),
        model=model,
        price=chat_turn_cost(model),
        usage=clover.SpendUsage("preview"),
        price_version=price_version,
    )


@pytest.fixture
def scopes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """채팅 게이트가 센 Redis 창의 이름. 버스트 창 하나뿐이면 하루 무료 카운터 같은 다른 창은 세지 않았다."""
    seen: list[str] = []

    async def spy(scope: str, key: str, limit: int, *, window_seconds: int) -> int:
        seen.append(scope)
        return await check_rate_limit(scope, key, limit, window_seconds=window_seconds)

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", spy)
    return seen


def _redis_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """버스트 검사가 Redis 장애로 깨진다. 장애 보고 간격 기록도 비워 다른 테스트의 보고와 섞이지 않게 한다."""

    async def down(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", down)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)


async def _balance(db: AsyncSession, user: User) -> int:
    await db.refresh(user)
    return user.clover_balance


async def _ledger_kinds(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return list((await db.scalars(select(CloverLedger.kind).where(CloverLedger.user_id == user_id))).all())


async def _refused(call: Callable[[], Awaitable[object]]) -> tuple[int, object]:
    with pytest.raises(HTTPException) as caught:
        await call()
    return caught.value.status_code, caught.value.detail


# ── 클로버로 낸다 ────────────────────────────────────────────────────────────
async def test_gemini_turn_spends_clover_without_confirmation(db_session: AsyncSession, scopes: list[str]) -> None:
    """오늘 확인하지 않은 인증 회원의 첫 Gemini 턴이 무료가 아니라 클로버로 나가고, 버스트 밖의 창은 세지 않는다."""
    user = await _member(db_session, balance=100)

    charge = await _charge(db_session, user)

    assert (charge.source, charge.clover_amount) == ("clover", _PRICE)
    assert scopes == ["chat_burst"]
    assert await _balance(db_session, user) == 100 - _PRICE


async def test_builder_preview_spends_clover_without_confirmation(db_session: AsyncSession) -> None:
    """빌더 미리보기도 같은 게이트다 — 작가의 시험 턴에도 하루 무료분이 없다."""
    user = await _member(db_session, balance=100)

    charge = await enforce_preview_chat_charge(
        user_id=user.id,
        db=db_session,
        session_factory=_factory(db_session),
        model="gemini",
        payload=ChatMessageCreateRequest(content="안녕"),
    )

    assert (charge.source, charge.clover_amount) == ("clover", _PRICE)
    assert await _balance(db_session, user) == 100 - _PRICE


async def test_unverified_member_spends_without_confirmation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """본인인증 게이트에 걸린 회원도 확인 없이 낸다 — 확인을 묻는 이유가 모두에게 같이 사라졌다."""
    monkeypatch.setattr(settings, "identity_gate_enabled", True)
    user = await _member(db_session, balance=100)

    charge = await _charge(db_session, user)

    assert (charge.source, charge.clover_amount) == ("clover", _PRICE)
    assert await _balance(db_session, user) == 100 - _PRICE


# ── 잔액 부족 ────────────────────────────────────────────────────────────────
async def test_unverified_member_without_clover_gets_identity_403(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """미인증 회원이 풀 길은 인증이라 잔액 부족은 403 이다."""
    monkeypatch.setattr(settings, "identity_gate_enabled", True)
    user = await _member(db_session, balance=0)

    assert await _refused(lambda: _charge(db_session, user)) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})
    assert await _ledger_kinds(db_session, user.id) == []


async def test_verified_member_without_clover_gets_the_clover_required_429(db_session: AsyncSession) -> None:
    """인증 회원의 잔액 부족은 무료분을 다 쓴 사람과 같은 모양의 429 다. `retryAfterSeconds`(자정까지)는 계약 모양을 지키려고
    싣는 값이다 — 자정에 돌아오는 무료분은 없다."""
    user = await _member(db_session, balance=0)

    status, detail = await _refused(lambda: _charge(db_session, user))

    assert status == 429
    assert isinstance(detail, dict)
    assert (detail["code"], detail["window"]) == ("CLOVER_REQUIRED", "clover")
    assert set(detail) == {"code", "window", "retryAfterSeconds"}
    assert detail["retryAfterSeconds"] == pytest.approx(seconds_until_kst_midnight(datetime.now(UTC)), abs=5)
    assert await _ledger_kinds(db_session, user.id) == []


# ── Redis 장애 ───────────────────────────────────────────────────────────────
async def test_redis_failure_still_charges_gemini_turns(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """무료 턴이 없는데 장애 중에 통과시키면 장애가 무료 턴을 만든다. 차감은 Redis 를 쓰지 않아 장애 중에도 그대로 한다."""
    user = await _member(db_session, balance=100)
    _redis_down(monkeypatch)

    charge = await _charge(db_session, user)

    assert (charge.source, charge.clover_amount) == ("clover", _PRICE)
    assert await _balance(db_session, user) == 100 - _PRICE


async def test_redis_failure_charges_unverified_members_without_confirmation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """장애 갈래의 미인증 회원 차감도 정상 갈래와 같이 확인을 묻지 않는다."""
    monkeypatch.setattr(settings, "identity_gate_enabled", True)
    user = await _member(db_session, balance=100)
    _redis_down(monkeypatch)

    charge = await _charge(db_session, user)

    assert (charge.source, charge.clover_amount) == ("clover", _PRICE)
    assert await _balance(db_session, user) == 100 - _PRICE


async def test_redis_failure_lets_exempt_members_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """면제 계정은 정상 때 내지 않으므로 장애 때만 내게 되면 안 된다."""
    user = await _member(db_session, balance=0, rate_limit_exempt=True)
    _redis_down(monkeypatch)

    charge = await _charge(db_session, user)

    assert charge.source == "skipped"
    assert await _ledger_kinds(db_session, user.id) == []


async def test_redis_failure_refuses_premium_turns(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """상위 모델 턴은 분당 상한 없이 열 수 없어 장애 중 503 이다 — Gemini 턴의 장애 갈래가 차감으로 바뀐 것과 무관하다."""
    user = await _member(db_session, balance=1_000)
    _redis_down(monkeypatch)

    status, detail = await _refused(lambda: _charge(db_session, user, model="opus"))

    assert (status, detail) == (503, {"code": "CHAT_MODEL_UNAVAILABLE"})
    assert await _ledger_kinds(db_session, user.id) == []


# ── 면제 ─────────────────────────────────────────────────────────────────────
async def test_exempt_member_is_not_charged(db_session: AsyncSession) -> None:
    """무료분이 없어져도 면제 계정은 차감 대상이 아니다."""
    user = await _member(db_session, balance=100, rate_limit_exempt=True)

    charge = await _charge(db_session, user)

    assert charge.source == "skipped"
    assert await _balance(db_session, user) == 100


# ── 정지·가격 버전 ───────────────────────────────────────────────────────────
async def test_paused_ledger_refuses_gemini_turns(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """무료분이 없으니 Gemini 턴도 클로버로 내는 턴이고, 정지 중에는 깎을 수 없어 503 이다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", True)
    user = await _member(db_session, balance=100)

    status, detail = await _refused(lambda: _charge(db_session, user))

    assert status == 503
    assert isinstance(detail, dict) and detail["code"] == "CLOVER_PAUSED"
    assert await _balance(db_session, user) == 100


async def test_paused_ledger_refuses_gemini_turns_during_redis_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """장애 갈래도 클로버로 내는 갈래라 정지 검사를 지난다 — 장애가 정지를 비켜 가는 무료 통과가 되지 않는다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", True)
    user = await _member(db_session, balance=100)
    _redis_down(monkeypatch)

    status, detail = await _refused(lambda: _charge(db_session, user))

    assert status == 503
    assert isinstance(detail, dict) and detail["code"] == "CLOVER_PAUSED"
    assert await _balance(db_session, user) == 100


async def test_stale_price_version_is_refused_before_charging(db_session: AsyncSession) -> None:
    """화면이 옛 가격표로 보낸 턴은 깎기 전에 지금 금액과 함께 409 로 돌려보낸다(클로버로 내는 다른 갈래와 같다)."""
    user = await _member(db_session, balance=100)

    status, detail = await _refused(lambda: _charge(db_session, user, price_version=clover.PRICE_VERSION - 1))

    assert (status, detail) == (409, {"code": "CLOVER_PRICE_CHANGED", "currentCost": _PRICE})
    assert await _balance(db_session, user) == 100


# ── 이미지 ───────────────────────────────────────────────────────────────────
async def test_image_overflow_still_asks_for_confirmation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이미지 무료분은 시간당 토큰이라 채팅 하루 무료분과 함께 없어지지 않는다 — 토큰을 다 쓴 순간의 하루 1회 확인도 그대로다."""
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)
    user = await _member(db_session, balance=clover.IMAGE_UNIT_COST)
    request = GenerateImageRequest.model_validate(
        {"prompt": "a cat wizard", "model": "v1", "style": "soft_portrait", "aspectRatio": "1:1", "count": 1}
    )

    status, detail = await _refused(
        lambda: enforce_image_rate_limit(request, user_id=user.id, db=db_session, session_factory=_factory(db_session))
    )

    assert status == 429
    assert isinstance(detail, dict)
    assert (detail["code"], detail["window"]) == ("CLOVER_CONFIRM_REQUIRED", "image")
    assert await _balance(db_session, user) == clover.IMAGE_UNIT_COST
