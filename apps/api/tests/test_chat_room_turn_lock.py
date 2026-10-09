"""같은 방에 진행 중인 턴이 있으면 그 방의 대화를 바꾸는 요청(보내기·수정·재생성·초기화·메시지 삭제)을 409 로 거절한다.

턴은 LLM 을 기다리는 동안 DB 트랜잭션을 쥐지 않는다. 그래서 같은 방에 두 턴이 겹치면(두 탭, 떠났다 돌아온 탭) 서로의
스탯 변화를 못 본 채 판정하고, 초기화된 방에 앞 턴의 응답이 붙는다. 이를 Redis 의 방 단위 락으로 막는다.

🔴 거절 단언의 셋업: 잔액 100 + 오늘치 클로버 동의 + `CHAT_DAILY_LIMIT` 0. 이 조합에서 차감 게이트가 한 번이라도
돌면 클로버가 깎이므로 "잔액·원장 그대로"는 락이 게이트보다 앞이라는 뜻이다. 같은 셋업에서 락이 비어 있으면 깎인다는
짝 테스트(`test_the_same_setup_without_a_held_lock_spends_clover`)가 그 단언을 셋업 탓이 아니게 만든다.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message

from api.chat import router as chat_router
from api.chat import turn_lock
from api.chat.memory_rewind import rewind_memory
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models import ChatMessage, User
from api.db.models.clover import CloverLedger
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.main import app
from factories import (
    Room,
    _clear_llm_override,
    _call_until_disconnect,
    _FakeLLMClient,
    _HangingLLMClient,
    _make_user_with_clover_lot,
    _NeverCalledLLMClient,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
)

_BUSY = {"detail": {"code": "CHAT_TURN_IN_PROGRESS"}}


def _lock_key(room_id: uuid.UUID) -> str:
    return f"chat_room:turn_lock:{room_id}"


async def _clover_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[User, Room]:
    """클로버를 낼 수밖에 없는 사용자(잔액 100, 오늘치 동의)의 캐릭터 방. 한 턴이 심어져 있다(재생성·수정 대상)."""
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    room = await _open_room(db_client, db_session, turns=1, user=user)
    return user, room


async def _message_count(db_session: AsyncSession, room_id: uuid.UUID) -> int:
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    )
    return count or 0


async def _ledger_count(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(CloverLedger).where(CloverLedger.user_id == user_id)
    )
    return count or 0


_Call = Callable[[httpx.AsyncClient, Room], Awaitable[httpx.Response]]


async def _send(client: httpx.AsyncClient, room: Room) -> httpx.Response:
    return await client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "다음 말"})


async def _edit(client: httpx.AsyncClient, room: Room) -> httpx.Response:
    return await client.patch(
        f"/chat-rooms/{room.room_id}/messages/{room.turns[1][0].id}", json={"content": "고친 말"}
    )


async def _regenerate(client: httpx.AsyncClient, room: Room) -> httpx.Response:
    return await client.post(f"/chat-rooms/{room.room_id}/regenerate")


async def _reset(client: httpx.AsyncClient, room: Room) -> httpx.Response:
    return await client.post(f"/chat-rooms/{room.room_id}/reset")


async def _delete_message(client: httpx.AsyncClient, room: Room) -> httpx.Response:
    return await client.delete(f"/chat-rooms/{room.room_id}/messages/{room.turns[1][1].id}")


_STREAM_ROUTES = [
    pytest.param(_send, id="send"),
    pytest.param(_edit, id="edit"),
    pytest.param(_regenerate, id="regenerate"),
]
_ALL_ROUTES = [*_STREAM_ROUTES, pytest.param(_reset, id="reset"), pytest.param(_delete_message, id="delete-message")]


@pytest.mark.parametrize("call", _ALL_ROUTES)
async def test_route_is_refused_while_another_turn_holds_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, call: _Call
) -> None:
    user, room = await _clover_room(db_client, db_session)
    await redis_client.set(_lock_key(room.room_id), "다른 턴", px=60_000)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_NeverCalledLLMClient())
    try:
        resp = await call(db_client, room)
    finally:
        _clear_llm_override()

    assert resp.status_code == 409
    assert resp.json() == _BUSY
    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_count(db_session, user.id) == 0
    # 분당 버스트 카운터도 올라가지 않았다 — 거절된 요청은 상한을 쓰지 않는다.
    assert await redis_client.keys(f"rate_limit:chat_burst:{user.id}") == []
    assert await _message_count(db_session, room.room_id) == 3  # 오프닝 + 한 턴, 그대로
    # 남의 락은 건드리지 않는다.
    assert await redis_client.get(_lock_key(room.room_id)) == "다른 턴"


async def test_the_same_setup_without_a_held_lock_spends_clover(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """위 테스트의 짝 — 셋업이 같고 락만 비어 있으면 게이트가 돌아 클로버가 깎인다."""
    user, room = await _clover_room(db_client, db_session)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_FakeLLMClient(tokens=["응답"]))
    try:
        resp = await _send(db_client, room)
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.clover_balance == 100 - clover.CHAT_TURN_COST


class _LockObservingLLMClient(LLMClient):
    """생성이 도는 동안 방 락 키의 값과 남은 TTL 을 본다. `error` 가 있으면 생성 대신 던진다."""

    def __init__(self, room_id: uuid.UUID, *, error: Exception | None = None) -> None:
        self._room_id = room_id
        self._error = error
        self.seen: list[tuple[bytes | str | None, int]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        key = _lock_key(self._room_id)
        self.seen.append((await redis_client.get(key), await redis_client.pttl(key)))
        if self._error is not None:
            raise self._error
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("이 시나리오에는 판정 호출이 없다")


@pytest.mark.parametrize("call", _STREAM_ROUTES)
async def test_turn_holds_the_room_while_generating_and_frees_it_after_done(
    db_client: httpx.AsyncClient, db_session: AsyncSession, call: _Call
) -> None:
    _, room = await _clover_room(db_client, db_session)

    fake = _LockObservingLLMClient(room.room_id)
    _override_llm_client(fake)
    try:
        resp = await call(db_client, room)
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert [event["type"] for event in _parse_sse_events(resp.text)][-1] == "done"
    [(holder, ttl_ms)] = fake.seen
    assert holder is not None
    # TTL 은 60초 고정이다 — 운영 최장 턴(약 21초)의 약 세 배.
    assert 55_000 < ttl_ms <= 60_000
    assert await redis_client.exists(_lock_key(room.room_id)) == 0


async def test_turn_that_ends_with_an_error_event_frees_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, room = await _clover_room(db_client, db_session)

    fake = _LockObservingLLMClient(room.room_id, error=LLMClientError("boom"))
    _override_llm_client(fake)
    try:
        resp = await _send(db_client, room)
    finally:
        _clear_llm_override()

    assert [event["type"] for event in _parse_sse_events(resp.text)] == ["error"]
    assert fake.seen[0][0] is not None
    assert await redis_client.exists(_lock_key(room.room_id)) == 0


async def test_request_refused_by_a_later_dependency_frees_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """락 뒤의 검증(없는 메시지 수정 404)과 차감 게이트(분당 상한 429)가 거절해도 락이 남지 않는다."""
    _, room = await _clover_room(db_client, db_session)
    key = _lock_key(room.room_id)

    _override_llm_client(_NeverCalledLLMClient())
    try:
        missing = await db_client.patch(
            f"/chat-rooms/{room.room_id}/messages/{uuid.uuid4()}", json={"content": "고친 말"}
        )
        assert missing.status_code == 404
        assert await redis_client.exists(key) == 0

        monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)
        limited = await _send(db_client, room)
        assert limited.status_code == 429
        assert await redis_client.exists(key) == 0
    finally:
        _clear_llm_override()


@pytest.mark.parametrize("call", [pytest.param(_reset, id="reset"), pytest.param(_delete_message, id="delete-message")])
async def test_reset_and_message_delete_take_and_free_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, call: _Call
) -> None:
    _, room = await _clover_room(db_client, db_session)
    seen: list[bytes | str | None] = []

    async def _observing_rewind(*args: Any, **kwargs: Any) -> None:
        seen.append(await redis_client.get(_lock_key(room.room_id)))
        await rewind_memory(*args, **kwargs)

    monkeypatch.setattr(chat_router, "rewind_memory", _observing_rewind)

    resp = await call(db_client, room)

    assert resp.status_code in (200, 204)
    assert len(seen) == 1 and seen[0] is not None
    assert await redis_client.exists(_lock_key(room.room_id)) == 0


async def test_room_is_freed_before_the_memory_fold_runs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """요약 접기(턴 뒤 background, LLM 호출)는 락 밖이다 — 접는 동안 다음 턴이 409 를 받으면 안 된다. 의존성 정리만으로
    풀면 FastAPI 가 그 정리를 스트림과 background 가 다 끝난 뒤에 돌리므로 이 테스트가 빨개진다."""
    _, room = await _clover_room(db_client, db_session)
    seen_during_fold: list[int] = []

    async def _observing_fold(*_args: Any, **_kwargs: Any) -> None:
        seen_during_fold.append(await redis_client.exists(_lock_key(room.room_id)))

    monkeypatch.setattr(chat_router, "fold_memory", _observing_fold)

    _override_llm_client(_FakeLLMClient(tokens=["응답"]))
    try:
        resp = await _send(db_client, room)
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert seen_during_fold == [0]


class _LockStealingLLMClient(LLMClient):
    """생성 도중 락의 주인이 바뀐 상황(TTL 이 지나 다른 턴이 새로 잡음)을 만든다."""

    def __init__(self, room_id: uuid.UUID) -> None:
        self._room_id = room_id

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        await redis_client.set(_lock_key(self._room_id), "뒤에 온 턴", px=60_000)
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("이 시나리오에는 판정 호출이 없다")


async def test_turn_that_outlived_its_lock_leaves_the_new_holder_alone_and_warns(
    db_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    _, room = await _clover_room(db_client, db_session)

    _override_llm_client(_LockStealingLLMClient(room.room_id))
    try:
        with caplog.at_level(logging.WARNING, logger=turn_lock.__name__):
            resp = await _send(db_client, room)
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert await redis_client.get(_lock_key(room.room_id)) == "뒤에 온 턴"
    warnings = [r for r in caplog.records if r.name == turn_lock.__name__ and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(room.room_id) in warnings[0].getMessage()


@pytest.mark.parametrize("call", [pytest.param(_send, id="send"), pytest.param(_reset, id="reset")])
async def test_redis_failure_lets_the_request_through_without_a_lock(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, call: _Call
) -> None:
    """Redis 장애면 락 없이 진행한다(fail-open) — 락이 지키는 것은 판정 품질이지 돈·심사가 아니고, 바로 뒤의 채팅
    차감 게이트도 같은 쪽이다."""
    _, room = await _clover_room(db_client, db_session)

    async def _broken(*_args: Any, **_kwargs: Any) -> str | None:
        raise RedisError("redis down")

    monkeypatch.setattr(turn_lock, "try_acquire_lock", _broken)

    _override_llm_client(_FakeLLMClient(tokens=["응답"]))
    try:
        resp = await call(db_client, room)
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    if call is _send:
        assert [event["type"] for event in _parse_sse_events(resp.text)][-1] == "done"


async def test_client_disconnect_mid_stream_frees_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """생성 도중 연결이 끊기면 스트림이 취소된다 — 그래도 락이 남지 않는다(남으면 그 사용자는 TTL 동안 409 를 본다).
    끊김은 `_call_until_disconnect` 가 만든다."""
    _, room = await _clover_room(db_client, db_session)
    started = asyncio.Event()

    _override_llm_client(_HangingLLMClient(started))
    try:
        sent = await _call_until_disconnect(
            db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "다음 말"}, started
        )
    finally:
        _clear_llm_override()

    assert started.is_set()
    assert sent[0]["status"] == 200
    assert await redis_client.exists(_lock_key(room.room_id)) == 0
