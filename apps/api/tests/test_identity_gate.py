"""미인증 회원 게이트: 채팅 무료분 0(빌더 미리보기 포함)·출석·미션 수령 차단, `/me/clover` 의 두 필드, 탈퇴한 같은 사람의
1회성 미션 재수령 차단.

**스위치가 꺼져 있으면 지금과 같다** — 그래서 게이트가 거는 자리마다 같은 입력으로 스위치만 바꾼 꺼짐/켜짐 쌍을 둔다. 꺼짐
쪽이 기존 동작이고, 두 쪽 결과가 갈리는 것으로 게이트가 그 스위치 하나에 묶여 있음을 본다. 스위치는 로컬 `.env` 가 아니라
아래 autouse 픽스처가 정한다(꺼짐). 포트원 키도 테스트가 정한다 — 게이트는 본인인증 설정이 있어야 켜진다.

채팅 차감 판정은 `charge_chat_turn` 을 직접 부른다(LLM·방 없이 판정만). 403 이 실제 라우트까지 나가는지는 방 전송과 빌더
미리보기 게이트에서 따로 본다.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.withdrawal import erase_account
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.rate_limit import check_rate_limit
from api.core.rate_limit_gate import ChatCharge, charge_chat_turn, enforce_chat_rate_limit
from api.core.security import hash_identity_ci
from api.db.models.auth import User, WithdrawnIdentity
from api.db.models.clover import CloverLedger
from api.llm.chat_models import DEFAULT_CHAT_MODEL
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_payment,
    _make_published_character,
    _make_user_with_clover_lot,
    _open_room,
    _override_llm_client,
)

_GATE = pytest.mark.parametrize("gate", [pytest.param(False, id="gate-off"), pytest.param(True, id="gate-on")])


@pytest.fixture(autouse=True)
def _identity_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "identity_gate_enabled", False)


def _set_gate(monkeypatch: pytest.MonkeyPatch, gate: bool) -> None:
    monkeypatch.setattr(settings, "identity_gate_enabled", gate)


def _verified() -> dict[str, object]:
    return {"identity_ci_hmac": f"ci-{uuid.uuid4().hex}", "identity_verified_at": datetime.now(UTC)}


def _confirmed_today() -> dict[str, object]:
    """클로버 차감에는 오늘치 확인이 앞선다 — "차감이 일어난다"를 보는 셋업은 그 조건을 명시한다."""
    return {"clover_spend_confirmed_on": clover.kst_today(datetime.now(UTC))}


async def _member(db: AsyncSession, **overrides: object) -> User:
    """`balance` 를 주면 그만큼의 로트도 함께 만든다(차감이 로트에서 깎는다)."""
    balance = overrides.pop("balance", 0)
    assert isinstance(balance, int)
    user = await _make_user_with_clover_lot(db, clover_balance=balance, **overrides)
    await db.flush()
    return user


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    # 차감은 자기 트랜잭션이다. 테스트 커넥션에 묶어 같은 트랜잭션 안에서 읽고 되돌린다(`db_client` 와 같은 방식).
    return async_sessionmaker(bind=db.bind, expire_on_commit=False)


async def _charge(db: AsyncSession, user: User) -> ChatCharge:
    return await charge_chat_turn(
        user.id, db, _factory(db), model=DEFAULT_CHAT_MODEL, price=clover.CHAT_TURN_COST
    )


@pytest.fixture
def scopes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """채팅 게이트가 센 Redis 창의 이름. 일일 창(`chat_day`)이 없으면 그 회원의 무료 카운터는 올라가지 않았다."""
    seen: list[str] = []
    async def spy(scope: str, key: str, limit: int, *, window_seconds: int) -> int:
        seen.append(scope)
        return await check_rate_limit(scope, key, limit, window_seconds=window_seconds)

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", spy)
    return seen


async def _balance(db: AsyncSession, user: User) -> int:
    await db.refresh(user)
    return user.clover_balance


async def _ledger_kinds(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return list((await db.scalars(select(CloverLedger.kind).where(CloverLedger.user_id == user_id))).all())


async def _forbidden(call: Callable[[], Awaitable[object]]) -> dict[str, object]:
    with pytest.raises(HTTPException) as caught:
        await call()
    assert caught.value.status_code == 403
    assert isinstance(caught.value.detail, dict)
    return caught.value.detail


# ── 채팅 ─────────────────────────────────────────────────────────────────
@_GATE
async def test_unverified_free_turn_becomes_a_clover_turn(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, scopes: list[str], gate: bool
) -> None:
    """무료분이 남은 미인증 회원(확인 완료, 잔액 있음). 꺼짐: 지금처럼 무료로 지나고 일일 창을 센다. 켜짐: 무료분이 0 이라
    클로버로 내고, 일일 창을 세지 않는다(인증한 날도 0/30 에서 시작한다)."""
    _set_gate(monkeypatch, gate)
    user = await _member(db_session, balance=100, **_confirmed_today())

    charge = await _charge(db_session, user)

    if gate:
        assert (charge.source, charge.clover_amount) == ("clover", clover.CHAT_TURN_COST)
        assert scopes == ["chat_burst"]
        assert await _balance(db_session, user) == 100 - clover.CHAT_TURN_COST
    else:
        assert charge.source == "free"
        assert scopes == ["chat_burst", "chat_day"]
        assert await _balance(db_session, user) == 100


@_GATE
async def test_daily_quota_sequence_is_unchanged_when_the_gate_is_off(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool
) -> None:
    """꺼짐: 30번째까지 무료, 31번째부터 클로버(지금 흐름 그대로). 켜짐: 첫 턴부터 클로버."""
    _set_gate(monkeypatch, gate)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 100)
    user = await _member(db_session, balance=1_000, **_confirmed_today())

    sources = [(await _charge(db_session, user)).source for _ in range(rate_limit_gate.CHAT_DAILY_LIMIT + 1)]

    expected_free = 0 if gate else rate_limit_gate.CHAT_DAILY_LIMIT
    assert sources == ["free"] * expected_free + ["clover"] * (len(sources) - expected_free)


@_GATE
async def test_unverified_without_clover_gets_identity_403(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool
) -> None:
    """켜짐: 0원 미인증 회원은 `CLOVER_REQUIRED` 429(자정에 무료분이 돌아온다는 거짓)가 아니라 인증 요구 403. 꺼짐: 무료."""
    _set_gate(monkeypatch, gate)
    user = await _member(db_session, balance=0, **_confirmed_today())

    if gate:
        assert await _forbidden(lambda: _charge(db_session, user)) == {"code": "IDENTITY_VERIFICATION_REQUIRED"}
    else:
        assert (await _charge(db_session, user)).source == "free"
    assert await _ledger_kinds(db_session, user.id) == []


async def test_unverified_with_clover_is_asked_to_confirm_first(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """오늘 확인하지 않았으면 깎기 전에 묻는다(무료분을 다 쓴 사람과 같은 확인 429). 아무것도 깎이지 않는다."""
    _set_gate(monkeypatch, True)
    user = await _member(db_session, balance=100)

    with pytest.raises(HTTPException) as caught:
        await _charge(db_session, user)

    assert caught.value.status_code == 429
    assert isinstance(caught.value.detail, dict)
    assert caught.value.detail["code"] == "CLOVER_CONFIRM_REQUIRED"
    assert await _balance(db_session, user) == 100


async def test_verified_member_keeps_the_free_quota(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """게이트가 켜져도 인증한 회원은 지금과 같다 — 게이트가 미인증 회원만 겨냥한다는 대조군."""
    _set_gate(monkeypatch, True)
    user = await _member(db_session, balance=100, **_confirmed_today(), **_verified())

    assert (await _charge(db_session, user)).source == "free"
    assert await _balance(db_session, user) == 100


async def test_exempt_member_bypasses_the_gate(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_gate(monkeypatch, True)
    user = await _member(db_session, balance=0, rate_limit_exempt=True)

    assert (await _charge(db_session, user)).source == "skipped"


@_GATE
async def test_redis_failure_does_not_give_unverified_members_free_turns(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool
) -> None:
    """버스트 검사가 Redis 장애로 깨지면 지금은 무료로 통과시킨다(꺼짐). 켜짐: 원래 무료 턴이 없는 미인증 회원은 Redis 를
    쓰지 않는 차감으로 낸다 — 장애가 그들에게 무료 턴을 주지 않는다."""
    _set_gate(monkeypatch, gate)
    user = await _member(db_session, balance=100, **_confirmed_today())

    async def down(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", down)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)

    charge = await _charge(db_session, user)

    if gate:
        assert charge.source == "clover"
        assert await _balance(db_session, user) == 100 - clover.CHAT_TURN_COST
    else:
        assert charge.source == "skipped"
        assert await _balance(db_session, user) == 100


async def test_redis_failure_with_no_clover_is_still_refused(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_gate(monkeypatch, True)
    user = await _member(db_session, balance=0, **_confirmed_today())

    async def down(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", down)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)

    assert await _forbidden(lambda: _charge(db_session, user)) == {"code": "IDENTITY_VERIFICATION_REQUIRED"}


async def test_builder_preview_is_gated_too(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """빌더 미리보기도 같은 게이트다 — 미인증 작가는 무료 미리보기 턴이 없고, 가진 클로버로는 미리보기를 할 수 있다."""
    _set_gate(monkeypatch, True)
    broke = await _member(db_session, balance=0, **_confirmed_today())
    funded = await _member(db_session, balance=100, **_confirmed_today())

    detail = await _forbidden(
        lambda: enforce_chat_rate_limit(user_id=broke.id, db=db_session, session_factory=_factory(db_session))
    )
    charge = await enforce_chat_rate_limit(user_id=funded.id, db=db_session, session_factory=_factory(db_session))

    assert detail == {"code": "IDENTITY_VERIFICATION_REQUIRED"}
    assert charge.source == "clover"


async def test_room_send_returns_the_identity_403(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """403 이 방 전송 라우트까지 그 모양 그대로 나간다(스트림을 열기 전, `Depends` 자리)."""
    user = await _member(db_session, balance=0, **_confirmed_today())
    room = await _open_room(db_client, db_session, turns=0, user=user)
    _set_gate(monkeypatch, True)

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})


# ── 출석 ─────────────────────────────────────────────────────────────────
@_GATE
async def test_attendance_is_gated(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool
) -> None:
    _set_gate(monkeypatch, gate)
    user = await _member(db_session)
    await _login_as(db_client, user.id)

    resp = await db_client.post("/me/clover/attendance")

    if gate:
        assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})
        assert await _ledger_kinds(db_session, user.id) == []
    else:
        assert resp.json() == {"granted": True, "balance": clover.ATTENDANCE_GRANT_AMOUNT}


async def test_attendance_already_claimed_today_is_still_403(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 날 검사보다 앞이라 "이미 받음"(`granted=false`)을 보이지 않는다."""
    _set_gate(monkeypatch, True)
    user = await _member(db_session, clover_attendance_granted_on=clover.kst_today(datetime.now(UTC)))
    await _login_as(db_client, user.id)

    resp = await db_client.post("/me/clover/attendance")

    assert resp.status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [pytest.param(_verified(), id="verified"), pytest.param({"rate_limit_exempt": True}, id="exempt")],
)
async def test_attendance_passes_verified_and_exempt_members(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    _set_gate(monkeypatch, True)
    user = await _member(db_session, **overrides)
    await _login_as(db_client, user.id)

    resp = await db_client.post("/me/clover/attendance")

    assert resp.json() == {"granted": True, "balance": clover.ATTENDANCE_GRANT_AMOUNT}


# ── /me/clover ───────────────────────────────────────────────────────────
@_GATE
@pytest.mark.parametrize("verified", [pytest.param(False, id="unverified"), pytest.param(True, id="verified")])
async def test_attendance_claimable_means_a_press_would_pay(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool, verified: bool
) -> None:
    """`attendanceClaimable` 은 "누르면 지급된다"다 — 게이트에 걸린 회원에게 참이면 보이는 버튼이 403 을 받는다."""
    _set_gate(monkeypatch, gate)
    user = await _member(db_session, **(_verified() if verified else {}))
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me/clover")

    assert resp.json()["attendanceClaimable"] is (verified or not gate)


async def test_paid_balance_counts_only_purchased_lots(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """탈퇴 경고가 쓰는 값이다 — 구매로 받은 유료·보너스의 남은 양만 세고, 출석 같은 무료 지급은 세지 않는다."""
    user = await _member(db_session, balance=0)
    order = await _make_payment(db_session, user_id=user.id, status="paid", paid_at=datetime.now(UTC))
    await clover.grant(db_session, user_id=user.id, amount=1_000, kind="purchase_paid", payment_id=order.id)
    await clover.grant(db_session, user_id=user.id, amount=150, kind="purchase_bonus", payment_id=order.id)
    await clover.grant(db_session, user_id=user.id, amount=100, kind="attendance_grant")
    await db_session.flush()
    await _login_as(db_client, user.id)

    body = (await db_client.get("/me/clover")).json()

    assert (body["balance"], body["paidBalance"]) == (1_250, 1_150)


# ── GET /me ──────────────────────────────────────────────────────────────
@_GATE
@pytest.mark.parametrize("verified", [pytest.param(False, id="unverified"), pytest.param(True, id="verified")])
@pytest.mark.parametrize("exempt", [pytest.param(False, id="normal"), pytest.param(True, id="exempt")])
async def test_me_identity_gated_matches_the_route_gate(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    gate: bool,
    verified: bool,
    exempt: bool,
) -> None:
    """화면이 미션 받기를 잠그는 값이다 — 스위치·인증·면제를 라우트 게이트와 같게 판정해야 면제 회원을 잘못 잠그지 않는다."""
    _set_gate(monkeypatch, gate)
    overrides: dict[str, object] = {"rate_limit_exempt": exempt, **(_verified() if verified else {})}
    user = await _member(db_session, **overrides)
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me")

    assert resp.status_code == 200
    assert resp.json()["identityGated"] is (gate and not verified and not exempt)


async def test_me_paid_clover_balance_equals_me_clover(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """탈퇴 경고가 재동의 게이트 밖에서 읽는 값이다 — `/me/clover` 의 `paidBalance` 와 같아야 한다(구매 로트만)."""
    user = await _member(db_session, balance=0)
    order = await _make_payment(db_session, user_id=user.id, status="paid", paid_at=datetime.now(UTC))
    await clover.grant(db_session, user_id=user.id, amount=1_000, kind="purchase_paid", payment_id=order.id)
    await clover.grant(db_session, user_id=user.id, amount=150, kind="purchase_bonus", payment_id=order.id)
    await clover.grant(db_session, user_id=user.id, amount=100, kind="attendance_grant")
    await db_session.flush()
    await _login_as(db_client, user.id)

    me = (await db_client.get("/me")).json()
    me_clover = (await db_client.get("/me/clover")).json()

    assert me["paidCloverBalance"] == me_clover["paidBalance"] == 1_150


async def test_me_paid_clover_balance_is_readable_while_reconsent_is_pending(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재동의가 남은 회원도 탈퇴할 수 있고(재동의 모달의 "동의하지 않고 탈퇴") 그때 환불 경고가 필요하다 — `/me/clover` 는
    403 이어도 `/me` 는 유료 잔액을 준다."""
    # 시드된 약관 게시본(재동의 필요)보다 옛 버전에 동의한 회원.
    user = await _member(db_session, balance=0, terms_version="2000-01-01")
    order = await _make_payment(db_session, user_id=user.id, status="paid", paid_at=datetime.now(UTC))
    await clover.grant(db_session, user_id=user.id, amount=500, kind="purchase_paid", payment_id=order.id)
    await db_session.flush()
    await _login_as(db_client, user.id)

    assert (await db_client.get("/me/clover")).status_code == 403
    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json()["paidCloverBalance"] == 500


async def test_me_daily_free_chat_turns_is_the_gate_constant(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화면 문구의 무료 대화 수는 게이트가 쓰는 상수 그 자체다 — 상수를 바꾸면 문구도 따라간다."""
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 7)
    user = await _member(db_session)
    await _login_as(db_client, user.id)

    assert (await db_client.get("/me")).json()["dailyFreeChatTurns"] == 7


@pytest.mark.parametrize(
    ("verified", "age", "expected"),
    [
        pytest.param(False, 30, "identity_required", id="unverified"),
        pytest.param(True, 18, "age_restricted", id="verified-eighteen"),
        pytest.param(True, 19, None, id="verified-nineteen"),
    ],
)
async def test_me_purchase_block_reason_matches_order_creation(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    verified: bool,
    age: int,
    expected: str | None,
) -> None:
    """허브가 다이얼로그를 열기 전에 보는 구매 가능 여부 — 주문 생성과 같은 판정이다(인증 먼저, 그다음 만 19세). 게이트
    스위치와 무관하다(꺼진 채로 본다). 1월 1일생이라 올해 생일이 이미 지났다."""
    _set_gate(monkeypatch, False)
    born = date(datetime.now(UTC).date().year - age, 1, 1)
    user = await _member(db_session, birth_date=born, **(_verified() if verified else {}))
    await _login_as(db_client, user.id)

    assert (await db_client.get("/me")).json()["purchaseBlockReason"] == expected


# ── 미션 ─────────────────────────────────────────────────────────────────
async def _publisher(db: AsyncSession, client: httpx.AsyncClient, **overrides: object) -> User:
    """첫 발행 미션을 달성한 회원(발행된 작품 하나)."""
    user = await _member(db, **overrides)
    genre = await _get_genre(db)
    await _make_published_character(db, creator_user_id=user.id, genre_id=genre.id)
    await db.flush()
    await _login_as(client, user.id)
    return user


@_GATE
async def test_mission_claim_is_gated_before_achievement(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool
) -> None:
    """켜짐: 달성 여부(422)보다 먼저 403. 꺼짐: 지금처럼 달성한 미션을 받는다."""
    _set_gate(monkeypatch, gate)
    await _publisher(db_session, db_client)

    resp = await db_client.post("/me/clover/missions/first_publish/claim")

    if gate:
        assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})
    else:
        assert resp.json()["granted"] is True


async def test_mission_claim_by_an_exempt_member_passes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_gate(monkeypatch, True)
    await _publisher(db_session, db_client, rate_limit_exempt=True)

    resp = await db_client.post("/me/clover/missions/first_publish/claim")

    assert resp.json()["granted"] is True


async def _keep(storage_key: str) -> None:
    return None


async def test_same_person_cannot_reclaim_a_one_time_mission_after_withdrawal(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 사람이 탈퇴 → 재가입 → 재인증해도 앞 계정에서 받은 1회성 보상은 다시 받지 못한다(이미 받은 것과 같은 응답).
    받지 않은 미션은 받는다."""
    _set_gate(monkeypatch, True)
    ci_hmac = hash_identity_ci("same-person-ci")
    first = await _publisher(db_session, db_client, identity_ci_hmac=ci_hmac, identity_verified_at=datetime.now(UTC))
    assert (await db_client.post("/me/clover/missions/first_publish/claim")).json()["granted"] is True
    await erase_account(db_session, first, delete_storage_object=_keep)

    second = await _publisher(db_session, db_client, identity_ci_hmac=ci_hmac, identity_verified_at=datetime.now(UTC))
    resp = await db_client.post("/me/clover/missions/first_publish/claim")
    missions = (await db_client.get("/me/clover/missions")).json()["missions"]

    assert resp.json() == {"granted": False, "balance": 0}
    assert await _ledger_kinds(db_session, second.id) == []
    assert {m["key"]: m["claimed"] for m in missions}["first_publish"] is True


@pytest.mark.parametrize(
    ("withdrawn_days_ago", "keys", "granted"),
    [
        pytest.param(30, ["first_publish"], False, id="recent-same-key"),
        pytest.param(400, ["first_publish"], True, id="past-retention"),
        pytest.param(30, ["first_message"], True, id="other-key"),
    ],
)
async def test_withdrawn_claim_record_is_matched_by_key_and_retention(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    withdrawn_days_ago: int,
    keys: list[str],
    granted: bool,
) -> None:
    _set_gate(monkeypatch, True)
    ci_hmac = hash_identity_ci("same-person-ci")
    db_session.add(
        WithdrawnIdentity(
            ci_hmac=ci_hmac,
            withdrawn_at=datetime.now(UTC) - timedelta(days=withdrawn_days_ago),
            claimed_mission_keys=keys,
        )
    )
    await _publisher(db_session, db_client, identity_ci_hmac=ci_hmac, identity_verified_at=datetime.now(UTC))

    resp = await db_client.post("/me/clover/missions/first_publish/claim")

    assert resp.json()["granted"] is granted
