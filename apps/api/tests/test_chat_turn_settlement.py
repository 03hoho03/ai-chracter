"""끊긴 채팅 턴의 정산(`chat/turn_settlement.py`)을 실제 uvicorn 서버의 끊김으로 고정한다.

끊김이 제너레이터에 닿는 길은 둘이고 둘 다 환급해야 한다. 제너레이터가 `yield` 에 멈춰 있으면(토큰이 흐르는 중)
나중에 종료 훅이 `GeneratorExit` 를 던지고, `await` 중이면 그 자리에서 `CancelledError` 가 나며 anyio 취소가 같은
범위의 다음 `await` 도 다시 취소한다. 탐침 라우트는 실제 라우트와 같은 `TurnSettlement.guard()` 로 본문을 감싸고,
환급 래퍼는 가짜로 바꿔 몇 번 불렸는지만 센다(래퍼 자신은 `test_core_clover.py` 가 본다).
"""

import asyncio
import gc
import sys
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import turn_settlement
from api.chat.turn_settlement import TurnSettlement
from api.core import clover
from api.core.rate_limit_gate import ChatCharge
from factories import _open_room
from sse_harness import Recorder, run_probe

_COST = 10


class _FakeRefund:
    """환급 래퍼 대역. `checkpoints` 만큼 `await` 한 뒤에야 기록한다 — 그 사이 취소되면 기록되지 않는다."""

    def __init__(self, *, checkpoints: int = 0) -> None:
        self.checkpoints = checkpoints
        self.amounts: list[int] = []

    async def __call__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID,
        spend_ledger_id: uuid.UUID | None,
        amount: int,
        kind: str,
    ) -> None:
        for _ in range(self.checkpoints):
            await asyncio.sleep(0)
        self.amounts.append(amount)


def _install_fake_refund(monkeypatch: pytest.MonkeyPatch, *, checkpoints: int = 0) -> _FakeRefund:
    fake = _FakeRefund(checkpoints=checkpoints)
    monkeypatch.setattr(clover, "refund_spend_in_new_transaction", fake)
    return fake


def _settlement(session_factory: async_sessionmaker[AsyncSession] | None = None) -> TurnSettlement:
    return TurnSettlement(
        charge=ChatCharge(source="clover", clover_amount=_COST, spend_ledger_id=uuid.uuid4()),
        user_id=uuid.uuid4(),
        session_factory=session_factory if session_factory is not None else async_sessionmaker(),
    )


def _probe_app(
    recorder: Recorder, settlement: TurnSettlement, body: Callable[[], AsyncIterator[dict[str, str]]]
) -> FastAPI:
    app = FastAPI()

    @app.post("/probe", response_class=EventSourceResponse)
    async def probe() -> AsyncIterator[dict[str, str]]:
        try:
            async with settlement.guard():
                async for event in body():
                    yield event
        except BaseException as exc:
            recorder.events.append(f"gen:{type(exc).__name__}")
            raise

    return app


async def _until(predicate: Callable[[], bool], *, seconds: float = 5.0) -> None:
    """참이 될 때까지 기다린다. `GeneratorExit` 갈래는 제너레이터가 수거될 때 일어나므로 순환 참조까지 거둔다."""
    async with asyncio.timeout(seconds):
        while not predicate():
            gc.collect()
            await asyncio.sleep(0.02)


async def test_disconnect_while_the_generator_waits_at_yield_refunds_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """판정 기준: 토큰을 쉬지 않고 내는 제너레이터(본문에 `await` 가 없어 `yield` 에서만 멈춘다)가 끊기면 `GeneratorExit`
    갈래로 끝나고 환급이 정확히 한 번 일어난다. `CancelledError` 만 잡는 가드면 0번이다."""
    refund = _install_fake_refund(monkeypatch)
    recorder = Recorder()
    settlement = _settlement()

    async def body() -> AsyncIterator[dict[str, str]]:
        while True:
            yield {"type": "token"}

    await run_probe(_probe_app(recorder, settlement, body), recorder, disconnect_on="token")
    await _until(lambda: bool(recorder.events))

    assert recorder.events == ["gen:GeneratorExit"]
    assert refund.amounts == [_COST]


async def test_yield_disconnect_refunds_once_whichever_generator_the_collector_closes_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """끊긴 라우트 제너레이터는 순환 참조 수거로 닫히고, 같은 순환에 묶인 다른 비동기 제너레이터와 닫히는 순서는 정해져
    있지 않다. 다른 것이 먼저 닫혀도 라우트는 `GeneratorExit` 갈래로 끝나고 환급은 한 번이어야 한다 — 가드가 제 비동기
    제너레이터를 가지면, 그것이 먼저 닫힌 뒤 라우트를 닫을 때 `RuntimeError` 가 난다. 순서를 직접 만들려고 이 구간에서
    시작된 비동기 제너레이터를 전부 가로채 라우트보다 먼저 닫는다."""
    refund = _install_fake_refund(monkeypatch)
    recorder = Recorder()
    settlement = _settlement()

    async def body() -> AsyncIterator[dict[str, str]]:
        while True:
            yield {"type": "token"}

    async def route() -> AsyncGenerator[dict[str, str], None]:
        try:
            async with settlement.guard():
                async for event in body():
                    yield event
        except BaseException as exc:
            recorder.events.append(f"gen:{type(exc).__name__}")
            raise

    started: list[AsyncGenerator[object, None]] = []
    firstiter, finalizer = sys.get_asyncgen_hooks()

    def capture(agen: AsyncGenerator[object, None]) -> None:
        started.append(agen)
        if firstiter is not None:
            firstiter(agen)

    sys.set_asyncgen_hooks(firstiter=capture, finalizer=finalizer)
    try:
        stream = route()
        await anext(stream)
    finally:
        sys.set_asyncgen_hooks(firstiter=firstiter, finalizer=finalizer)
    for other in started:
        if other is not stream:
            await other.aclose()
    await stream.aclose()

    assert recorder.events == ["gen:GeneratorExit"]
    assert refund.amounts == [_COST]


async def test_disconnect_while_the_generator_awaits_refunds_through_the_shield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """판정 기준: `await` 중 끊기면 `CancelledError` 갈래다. 환급이 `await` 를 다섯 번 거친 뒤에야 기록되는데도 기록돼야
    한다 — 차폐가 없으면 첫 `await` 에서 다시 취소돼 0번이다."""
    refund = _install_fake_refund(monkeypatch, checkpoints=5)
    recorder = Recorder()
    settlement = _settlement()
    never = asyncio.Event()

    async def body() -> AsyncIterator[dict[str, str]]:
        yield {"type": "token"}
        await never.wait()

    await run_probe(_probe_app(recorder, settlement, body), recorder, disconnect_on="token")
    await _until(lambda: bool(recorder.events))

    assert recorder.events == ["gen:CancelledError"]
    assert refund.amounts == [_COST]


async def test_disconnect_after_the_turn_is_settled_does_not_refund(monkeypatch: pytest.MonkeyPatch) -> None:
    refund = _install_fake_refund(monkeypatch)
    recorder = Recorder()
    settlement = _settlement()
    never = asyncio.Event()

    async def body() -> AsyncIterator[dict[str, str]]:
        settlement.mark_settled()
        yield {"type": "done"}
        await never.wait()

    await run_probe(_probe_app(recorder, settlement, body), recorder, disconnect_on="done")
    await _until(lambda: bool(recorder.events))

    assert recorder.events == ["gen:CancelledError"]
    assert refund.amounts == []


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        pytest.param("saved", [], id="reply-saved"),
        pytest.param("missing", [_COST], id="reply-missing"),
        pytest.param("room-gone", [], id="room-deleted"),
    ],
)
async def test_unsettled_turn_with_a_pending_reply_refunds_only_when_the_reply_is_missing(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    reply: str,
    expected: list[int],
) -> None:
    """응답을 세션에 올린 뒤 커밋이 돌아오기 전에 끝난 턴. 응답 행이 있으면 저장된 것이라 환급하지 않고, 없으면 환급한다.
    방이 그사이 지워졌으면 사용자가 지운 것이라 환급하지 않는다."""
    refund = _install_fake_refund(monkeypatch)
    room = await _open_room(db_client, db_session, turns=1)
    connection = db_session.bind
    settlement = _settlement(async_sessionmaker(bind=connection, expire_on_commit=False))
    saved_reply = room.turns[1][1].id
    room_id = uuid.uuid4() if reply == "room-gone" else room.room_id
    message_id = saved_reply if reply == "saved" else uuid.uuid4()

    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as request_session:
        settlement.set_pending_message(request_session, room_id, message_id)
        await settlement.refund_if_unsettled()

    assert refund.amounts == expected
    assert settlement.settled


async def test_disconnect_during_the_reply_check_still_refunds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준: 응답 확인(새 세션의 `await` 여러 번)이 끊김으로 취소된 범위 안에서 돌아도 환급이 한 번 일어난다.
    확인을 차폐 밖에 두면 그 첫 `await` 에서 다시 취소돼 0번이다."""
    refund = _install_fake_refund(monkeypatch)
    room = await _open_room(db_client, db_session, turns=1)
    connection = db_session.bind
    settlement = _settlement(async_sessionmaker(bind=connection, expire_on_commit=False))
    recorder = Recorder()
    never = asyncio.Event()

    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as request_session:

        async def body() -> AsyncIterator[dict[str, str]]:
            yield {"type": "token"}
            settlement.set_pending_message(request_session, room.room_id, uuid.uuid4())
            await never.wait()

        await run_probe(_probe_app(recorder, settlement, body), recorder, disconnect_on="token")
        await _until(lambda: bool(recorder.events))

    assert recorder.events == ["gen:CancelledError"]
    assert refund.amounts == [_COST]


async def test_settlement_gives_up_after_its_time_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """정산이 상한 안에 끝나지 않으면 거기서 멈추고 남긴다 — 종료 중인 프로세스가 끊긴 턴 하나로 멈추지 않게 한다."""
    captured: list[str] = []
    monkeypatch.setattr(
        turn_settlement, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    monkeypatch.setattr(turn_settlement, "SETTLE_TIMEOUT_SECONDS", 0.05)

    async def _hang(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(clover, "refund_spend_in_new_transaction", _hang)
    settlement = _settlement()

    async with asyncio.timeout(5):
        await settlement.refund_if_unsettled()

    assert captured == ["clover"]
