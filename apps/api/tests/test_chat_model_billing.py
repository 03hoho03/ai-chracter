"""상위 모델 방의 턴 과금 — 게이트 갈래, 생성 모델의 출처, 상위 모델 가격의 환불.

Gemini 방의 갈래(면제 통과·본인인증 게이트·Redis 장애에도 차감)는 `test_clover_gate.py` 와 `test_user_rate_limit_gate.py`
가 지킨다. 여기서는 상위 모델 방이 그 갈래를 **타지 않는** 것을 본다 — 면제 계정도 내고, 하루 1회 확인을 묻지 않고, Redis 가
고장 나면 분당 상한 없이 열지 않고 거절한다.

셋업 관례는 `test_clover_gate.py` 와 같다(진짜 방, 상한은 `monkeypatch` 로 조인다, 잔액은 `refresh` 로 다시 읽는다).
"""

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat.prompt_builder import PromptRenderError
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.rate_limit_gate import charge_chat_turn
from api.db.models import User
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.clover import CloverLedger
from api.llm.client import LLMClientError, LLMPolicyViolationError
from factories import (
    _clear_llm_override,
    _clover_lots,
    _enable_chat_premium,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user_with_clover_lot,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
)

_OPUS = clover.CLOVER_MODEL_PRICES["opus"].chat_turn
_START = 1000


async def _user(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    balance: int = _START,
    exempt: bool = False,
    confirmed_today: bool = False,
) -> User:
    """채팅 상위 모델 스위치를 켠 일반 계정(명단·허용 행 없음). 오늘 확인은 기본으로 하지 않는다 — 상위 모델 턴이 확인을 묻지 않는 것을 보려면 그
    상태가 기본이어야 한다."""
    user = await _make_user_with_clover_lot(
        db_session,
        clover_balance=balance,
        rate_limit_exempt=exempt,
        clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC)) if confirmed_today else None,
    )
    await db_session.commit()
    _enable_chat_premium(monkeypatch)
    await _login_as(db_client, user.id)
    return user


async def _room(db_client: httpx.AsyncClient, db_session: AsyncSession, user: User, model: str | None) -> uuid.UUID:
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    assert resp.status_code == 201
    room_id = uuid.UUID(resp.json()["id"])
    await _set_model(db_session, room_id, model)
    return room_id


async def _set_model(db_session: AsyncSession, room_id: uuid.UUID, model: str | None) -> None:
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(chat_model=model))
    await db_session.commit()


async def _ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = (await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    return sorted((row.kind, row.amount) for row in rows)


async def _send(db_client: httpx.AsyncClient, room_id: uuid.UUID, fake: _FakeLLMClient | None = None) -> httpx.Response:
    _override_llm_client(fake or _FakeLLMClient(tokens=["응", "답"]))
    try:
        return await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()


async def _balance(db_session: AsyncSession, user: User) -> int:
    await db_session.refresh(user)
    return user.clover_balance


# ---- 게이트 갈래 ----


async def test_a_plain_account_picks_opus_and_its_turn_charges_the_opus_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치만 켜져 있으면 명단·허용 행 없는 계정도 모델 지정 라우트로 Opus 를 고르고, 그 방의 턴은 Opus 로 생성되며
    Opus 값을 낸다."""
    user = await _user(db_client, db_session, monkeypatch)
    room_id = await _room(db_client, db_session, user, None)
    fake = _FakeLLMClient(tokens=["응", "답"])

    assert (await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "opus"})).status_code == 200
    resp = await _send(db_client, room_id, fake)

    assert resp.status_code == 200
    assert await _ledger(db_session, user.id) == [("chat_spend", -_OPUS)]
    assert [u.model for u in fake.usages if u.call_site == "chat_generate"] == ["opus"]


async def test_premium_turn_charges_its_price_and_generates_with_that_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상위 모델 턴은 그 모델 가격을 낸다. 하루 1회 확인을 한 적이 없어도 묻지 않는다 — 모델을 고를 때 본 턴당 가격이
    확인이다."""
    user = await _user(db_client, db_session, monkeypatch)
    room_id = await _room(db_client, db_session, user, "opus")
    fake = _FakeLLMClient(tokens=["응", "답"])

    resp = await _send(db_client, room_id, fake)

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)][-1] == "done"
    assert await _balance(db_session, user) == _START - _OPUS
    assert await _ledger(db_session, user.id) == [("chat_spend", -_OPUS)]
    assert [u.model for u in fake.usages if u.call_site == "chat_generate"] == ["opus"]


async def test_premium_turn_charges_an_exempt_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """면제는 횟수 상한만 비켜 간다 — 상위 모델 턴의 값은 면제 계정도 낸다."""
    user = await _user(db_client, db_session, monkeypatch, exempt=True)
    room_id = await _room(db_client, db_session, user, "opus")

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200
    assert await _ledger(db_session, user.id) == [("chat_spend", -clover.CLOVER_MODEL_PRICES["opus"].chat_turn)]


async def test_premium_turn_without_enough_clover_is_the_clover_shortage_429(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini 가격으로는 낼 수 있는 잔액이어도 상위 모델 가격에 모자라면 부족이다."""
    user = await _user(db_client, db_session, monkeypatch, balance=_OPUS - 1)
    room_id = await _room(db_client, db_session, user, "opus")
    fake = _FakeLLMClient(tokens=["응"])

    resp = await _send(db_client, room_id, fake)

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "CLOVER_REQUIRED"
    assert resp.json()["detail"]["window"] == "clover"
    assert await _ledger(db_session, user.id) == []
    assert fake.usages == []


async def test_premium_turn_still_gets_the_burst_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(db_client, db_session, monkeypatch, exempt=True)
    room_id = await _room(db_client, db_session, user, "opus")
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429
    assert resp.json()["detail"]["window"] == "minute"
    assert await _ledger(db_session, user.id) == []


async def test_premium_turn_is_refused_when_redis_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini 방은 Redis 부분 장애에서도 분당 상한 없이 클로버로 내지만, 상위 모델 방은 분당 상한을 못 센 채 비싼 호출을 열지 않고
    503 으로 거절한다. 차감 전이라 원장도 그대로다."""
    user = await _user(db_client, db_session, monkeypatch)
    room_id = await _room(db_client, db_session, user, "opus")

    async def _down(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", _down)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)
    fake = _FakeLLMClient(tokens=["응"])

    resp = await _send(db_client, room_id, fake)

    assert resp.status_code == 503
    assert resp.json()["detail"] == {"code": "CHAT_MODEL_UNAVAILABLE"}
    assert await _ledger(db_session, user.id) == []
    assert fake.usages == []


async def test_revoked_premium_room_runs_as_gemini_at_gemini_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치를 끄면(1차 롤백) 상위 모델을 고른 방은 막히지 않고 Gemini 로, Gemini 가격으로 돈다."""
    user = await _user(db_client, db_session, monkeypatch, confirmed_today=True)
    room_id = await _room(db_client, db_session, user, "opus")
    monkeypatch.setattr(settings, "chat_premium_models_enabled", False)
    fake = _FakeLLMClient(tokens=["응"])

    resp = await _send(db_client, room_id, fake)

    assert resp.status_code == 200
    assert await _ledger(db_session, user.id) == [("chat_spend", -clover.CLOVER_MODEL_PRICES["gemini"].chat_turn)]
    assert [u.model for u in fake.usages if u.call_site == "chat_generate"] == ["gemini"]


async def test_chat_premium_works_for_an_account_without_novel_premium_access(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채팅·소설 허용은 따로다 — 소설 쪽 스위치가 켜져 있고 이 계정이 그 명단에 없어도 채팅 상위 모델 턴은 돈다."""
    monkeypatch.setattr(settings, "novelize_premium_models_enabled", True)
    monkeypatch.setattr(settings, "novelize_premium_model_allowlist", [uuid.uuid4()])
    user = await _user(db_client, db_session, monkeypatch)
    room_id = await _room(db_client, db_session, user, "opus")

    assert (await _send(db_client, room_id)).status_code == 200
    assert await _ledger(db_session, user.id) == [("chat_spend", -_OPUS)]


# ---- 생성 모델의 출처 ----


async def test_generation_uses_the_charged_model_even_if_the_room_changes_after_the_gate(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """게이트가 Opus 값을 받은 뒤 방을 Gemini 로 되돌리고 허용까지 거둬도, 그 턴은 값을 낸 Opus 로 생성한다. 생성
    직전에 방을 다시 읽으면 Opus 값을 내고 Gemini 글을 받는다."""
    user = await _user(db_client, db_session, monkeypatch)
    room_id = await _room(db_client, db_session, user, "opus")
    real_charge = charge_chat_turn

    async def _charge_then_switch(*args: Any, **kwargs: Any) -> Any:
        charge = await real_charge(*args, **kwargs)
        await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(chat_model=None))
        monkeypatch.setattr(settings, "chat_premium_models_enabled", False)
        return charge

    monkeypatch.setattr(chat_router, "charge_chat_turn", _charge_then_switch)
    fake = _FakeLLMClient(tokens=["응"])

    assert (await _send(db_client, room_id, fake)).status_code == 200

    assert await _ledger(db_session, user.id) == [("chat_spend", -_OPUS)]
    assert [u.model for u in fake.usages if u.call_site == "chat_generate"] == ["opus"]


# ---- 상위 모델 가격의 환불 ----


async def _failing_premium_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    surface: str,
    failure: str,
) -> tuple[User, httpx.Response]:
    """재생성·편집 대상인 첫 턴을 DB 에 심어 둔 뒤 방을 Opus 로 바꾸고 실패하는 턴을 보낸다. 원장에는 실패한 턴의 행만
    남는다 — 첫 턴을 API 로 보내면 그 Gemini 턴도 클로버로 나가 원장에 셋업 행이 남는다."""
    user = await _user(db_client, db_session, monkeypatch)
    if surface in ("regenerate", "edit"):
        room_id = (await _open_room(db_client, db_session, turns=1, user=user)).room_id
    else:
        room_id = await _room(db_client, db_session, user, None)
    await _set_model(db_session, room_id, "opus")

    if failure == "render":

        async def _raise(*args: Any, **kwargs: Any) -> Any:
            raise PromptRenderError("렌더 실패")

        monkeypatch.setattr(chat_router, "build_room_prompt", _raise)
        fake = _FakeLLMClient(tokens=["응"])
    elif failure == "llm":
        fake = _FakeLLMClient(error=LLMClientError("bedrock down"))
    else:
        fake = _FakeLLMClient(error=LLMPolicyViolationError("refusal"))

    _override_llm_client(fake)
    try:
        if surface == "regenerate":
            resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
        elif surface == "edit":
            message_id = await db_session.scalar(
                select(ChatMessage.id).where(
                    ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER
                )
            )
            resp = await db_client.patch(f"/chat-rooms/{room_id}/messages/{message_id}", json={"content": "고침"})
        else:
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    return user, resp


@pytest.mark.parametrize("surface", ["send", "edit", "regenerate"])
@pytest.mark.parametrize("failure", ["render", "llm"])
async def test_our_side_failure_refunds_the_premium_price(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    failure: str,
) -> None:
    """환불액은 상수가 아니라 영수증의 차감액이다 — Gemini 가격만 되돌리면 상위 모델 값의 차액이 사라진다."""
    user, resp = await _failing_premium_turn(db_client, db_session, monkeypatch, surface=surface, failure=failure)

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]
    assert await _balance(db_session, user) == _START
    assert await _ledger(db_session, user.id) == [("chat_refund", _OPUS), ("chat_spend", -_OPUS)]
    # 상위 모델 차감도 차감 id 를 들고 가 깎은 그 로트로 돌아간다(새 환급 로트가 생기지 않는다).
    assert await _clover_lots(db_session, user.id) == [("legacy_balance", _START)]


@pytest.mark.parametrize("surface", ["send", "edit", "regenerate"])
async def test_policy_violation_keeps_the_premium_charge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    """정책 차단(Claude 의 거절 포함)은 현행 매핑대로 소모로 둔다 — 사용자 입력이 원인이고 모델을 실제로 태웠다."""
    user, resp = await _failing_premium_turn(db_client, db_session, monkeypatch, surface=surface, failure="policy")

    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["policyWarning"]
    assert await _ledger(db_session, user.id) == [("chat_spend", -_OPUS)]


async def test_route_body_failure_before_the_first_event_refunds_the_premium_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(db_client, db_session, monkeypatch)
    room_id = await _room(db_client, db_session, user, "opus")

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("본문 실패")

    monkeypatch.setattr(chat_router, "ChatMessage", _boom)
    raised: BaseException | None = None
    try:
        await _send(db_client, room_id)
    except BaseException as exc:
        raised = exc

    assert raised is not None
    assert await _ledger(db_session, user.id) == [("chat_refund", _OPUS), ("chat_spend", -_OPUS)]


# ---- 의존성 순서 ----


def _dependencies(route: Any) -> list[Any]:
    return [
        param.default.dependency
        for param in inspect.signature(route).parameters.values()
        if hasattr(param.default, "dependency")
    ]


@pytest.mark.parametrize(
    ("route", "gate"),
    [
        pytest.param(chat_router.send_message, chat_router.enforce_room_send_charge, id="send"),
        pytest.param(chat_router.regenerate_message, chat_router.enforce_room_chat_charge, id="regenerate"),
        pytest.param(chat_router.edit_message, chat_router.enforce_room_edit_charge, id="edit"),
    ],
)
def test_room_turns_charge_last_with_the_room_gate(route: Any, gate: Any) -> None:
    """차감은 조회·검증 의존성 전부보다 뒤다 — 앞이면 404·400 에서 차감만 남는다. 세 턴 경로는 방의 모델을 읽는 게이트를
    쓴다(미리보기 게이트를 쓰면 상위 모델 방이 Gemini 값으로 상위 모델을 쓴다). 전송·편집 게이트는 자기 본문 모델을 받고 방
    게이트를 부른다."""
    dependencies = _dependencies(route)

    assert dependencies[-1] is gate
    assert chat_router.enforce_preview_chat_charge not in dependencies


def test_room_gate_reads_the_room_after_the_turn_lock_refreshed_it() -> None:
    """게이트가 보는 방은 락을 잡은 뒤 다시 읽은 방이어야 한다 — 락 전에 읽힌 값으로 모델을 정하면 앞 턴과 겹친 사이에
    바뀐 모델을 놓친다. 같은 요청 안에서 두 의존성은 한 번씩만 해석되므로, 시그니처에서 락이 방보다 앞이면 된다. 모델은 게이트와
    판정 세트 의존성이 같은 실효 모델 의존성에서 받는다(요청 스코프 캐시로 한 값)."""
    for function in (chat_router.enforce_room_chat_charge, chat_router._effective_room_model_dependency):
        dependencies = _dependencies(function)
        assert dependencies.index(chat_router._room_turn_lock_dependency) < dependencies.index(
            chat_router._playable_room_dependency
        )
    assert chat_router._effective_room_model_dependency in _dependencies(chat_router.enforce_room_chat_charge)
    assert chat_router._effective_room_model_dependency in _dependencies(chat_router._judgment_prompt_sets_dependency)


def test_preview_charges_last_with_the_preview_gate() -> None:
    """미리보기는 방이 없어 세션이 고른 모델을 읽는 자기 게이트를 맨 뒤에 쓴다. 게이트·생성 세트·판정 세트가 같은 실효 모델
    의존성에서 모델을 받는다(요청 스코프 캐시로 한 값)."""
    dependencies = _dependencies(chat_router.send_preview_message)

    assert dependencies[-1] is chat_router.enforce_preview_chat_charge
    for function in (
        chat_router.enforce_preview_chat_charge,
        chat_router._preview_generation_set_dependency,
        chat_router._preview_judgment_prompt_sets_dependency,
    ):
        assert chat_router._preview_effective_model_dependency in _dependencies(function)
