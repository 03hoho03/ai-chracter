"""SSE 제너레이터 라우트에서 `BackgroundTasks`가 언제 실행되고 언제 유실되는지 고정한다.

채팅 턴 뒤 후처리(예: 긴 대화 요약)를 제너레이터 본문 안, 턴 커밋 직후에 예약하려면 세 가지를
알아야 한다. ① 정상 종료 시 실행되는가 ② 클라이언트가 `done` 전에 끊으면 어떻게 되는가
③ `done` 뒤에 끊으면 어떻게 되는가. 이 저장소의 기존 `BackgroundTasks` 사용처는 전부 일반 JSON
라우트라 이 답을 주지 못한다.

하네스가 실제 uvicorn 서버와 실제 소켓인 이유: httpx `ASGITransport`는 앱이 끝날 때까지 응답을
모았다가 돌려주고, `receive()`가 응답이 끝난 뒤에만 `http.disconnect`를 준다 — 스트림 중간의
끊김을 원리적으로 만들 수 없다. 프로덕션과 같은 httptools 프로토콜을 고른다(Starlette의
`StreamingResponse`는 서버가 알리는 ASGI `spec_version`에 따라 끊김 처리 경로가 갈린다 —
2.4 미만이면 끊김 감시 태스크가 스트림을 취소하고 background를 실행하고, 2.4 이상이면 송신
실패가 예외로 올라가 background를 건너뛴다).

결론(이 테스트들이 지키는 것):
- 정상 종료: 제너레이터가 끝까지 돈 뒤 background가 실행된다. `done` 뒤에 예약한 것도 실행된다.
- 끊김(시점 무관): 끊김이 처리되기 **전에** 예약된 것만 실행되고, 그다음 제너레이터가 취소된다.
  그래서 후처리는 `done`을 내보내기 **전에** 예약해야 한다 — `done` 뒤 코드는 끊김 한 번에
  예약 자체가 사라진다.
- uvicorn을 올려 서버가 `spec_version` 2.4 이상을 알리기 시작하면 끊김 시 background가 돌지 않아
  끊김 테스트 둘이 빨개진다 — 그때 이 결론을 다시 본다.
"""

import asyncio
import socket
from collections.abc import AsyncIterator, Callable

import uvicorn
from fastapi import BackgroundTasks, FastAPI
from fastapi.sse import EventSourceResponse
from starlette.types import Receive, Scope, Send

_TIMEOUT_SECONDS = 5.0


class _Recorder:
    """제너레이터와 background 태스크가 남기는 사건 순서. `finished`는 ASGI 호출이 반환됐다는
    신호다 — 응답·background·요청 정리(제너레이터 취소 포함)가 전부 그 안에서 끝난다."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.finished = asyncio.Event()

    def task(self, name: str) -> Callable[[], None]:
        def run() -> None:
            self.events.append(f"task:{name}")

        return run


def _build_app(recorder: _Recorder, body: Callable[[BackgroundTasks], AsyncIterator[dict[str, str]]]) -> FastAPI:
    app = FastAPI()

    @app.post("/probe", response_class=EventSourceResponse)
    async def probe(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        try:
            async for event in body(background_tasks):
                yield event
            recorder.events.append("gen:end")
        except asyncio.CancelledError:
            recorder.events.append("gen:cancelled")
            raise

    return app


async def _run(app: FastAPI, recorder: _Recorder, *, disconnect_on: str | None) -> list[str]:
    """실제 uvicorn(httptools)으로 앱을 띄우고 POST 한 번을 보낸다. `disconnect_on`이 주어지면
    그 문자열이 든 SSE 이벤트를 받는 즉시 소켓을 닫는다. 받은 `data:` 줄들을 돌려준다."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await app(scope, receive, send)
        finally:
            recorder.finished.set()

    config = uvicorn.Config(asgi, http="httptools", lifespan="off", log_level="warning")
    server = uvicorn.Server(config)
    # 서버가 뜨기 전에 listen 해 두면 연결이 백로그에서 기다리므로 기동 완료를 폴링할 필요가 없다.
    sock.listen()
    serve_task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"POST /probe HTTP/1.1\r\nHost: probe\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()

        received: list[str] = []
        async with asyncio.timeout(_TIMEOUT_SECONDS):
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text.startswith("data:"):
                    received.append(text)
                    if disconnect_on is not None and disconnect_on in text:
                        break
                # 청크 인코딩의 마지막 청크(`0`) 뒤 빈 줄 = 응답 끝.
                if text == "0":
                    break
        writer.close()
        await writer.wait_closed()

        await asyncio.wait_for(recorder.finished.wait(), _TIMEOUT_SECONDS)
        return received
    finally:
        server.should_exit = True
        await asyncio.wait_for(serve_task, _TIMEOUT_SECONDS)


async def test_background_runs_after_the_generator_finishes_on_normal_completion() -> None:
    recorder = _Recorder()

    async def body(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        yield {"type": "token"}
        # 첫 yield 뒤(응답이 이미 시작된 뒤) 제너레이터 본문 안에서 예약해도 된다.
        background_tasks.add_task(recorder.task("before-done"))
        yield {"type": "done"}
        background_tasks.add_task(recorder.task("after-done"))

    received = await _run(_build_app(recorder, body), recorder, disconnect_on=None)

    assert [line for line in received if "done" in line] != []
    assert recorder.events == ["gen:end", "task:before-done", "task:after-done"]


async def test_disconnect_before_done_runs_only_tasks_scheduled_before_it() -> None:
    """턴 커밋 뒤 예약까지 마쳤는데 `done`이 가기 전에 클라이언트가 떠난 경우와, 예약 지점에
    닿기 전에 떠난 경우. 앞의 것은 실행되고 뒤의 것은 예약 자체가 일어나지 않는다."""
    recorder = _Recorder()
    never = asyncio.Event()

    async def body(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        background_tasks.add_task(recorder.task("scheduled"))
        yield {"type": "token"}
        # 끊긴 뒤에도 제너레이터가 알아서 여기를 지나가지 않는다는 것을 보이려고 영영 기다린다.
        await never.wait()
        background_tasks.add_task(recorder.task("never-scheduled"))
        yield {"type": "done"}

    received = await _run(_build_app(recorder, body), recorder, disconnect_on="token")

    assert all("done" not in line for line in received)
    # background는 제너레이터가 취소되기 **전에** 돈다(요청 정리가 background 뒤에 온다).
    assert recorder.events == ["task:scheduled", "gen:cancelled"]


async def test_disconnect_after_done_runs_tasks_scheduled_before_done_and_drops_later_ones() -> None:
    recorder = _Recorder()
    never = asyncio.Event()

    async def body(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        yield {"type": "token"}
        background_tasks.add_task(recorder.task("before-done"))
        yield {"type": "done"}
        # `done` 뒤 코드는 클라이언트가 떠나면 실행 기회를 잃는다.
        await never.wait()
        background_tasks.add_task(recorder.task("after-done"))

    received = await _run(_build_app(recorder, body), recorder, disconnect_on="done")

    assert [line for line in received if "done" in line] != []
    assert recorder.events == ["task:before-done", "gen:cancelled"]
