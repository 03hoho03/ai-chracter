"""SSE 라우트를 실제 uvicorn 서버와 실제 소켓으로 부르고, 원하는 이벤트에서 클라이언트 쪽 연결을 끊는 하네스.

httpx `ASGITransport`는 앱이 끝날 때까지 응답을 모았다가 돌려주고, `receive()`가 응답이 끝난 뒤에만 `http.disconnect`를
준다 — 스트림 중간의 끊김을 원리적으로 만들 수 없다. 프로덕션과 같은 httptools 프로토콜을 고른다(Starlette의
`StreamingResponse`는 서버가 알리는 ASGI `spec_version`에 따라 끊김 처리 경로가 갈린다 — 2.4 미만이면 끊김 감시 태스크가
스트림을 취소하고 background를 실행하고, 2.4 이상이면 송신 실패가 예외로 올라가 background를 건너뛴다).

탐침 앱은 `POST /probe` 하나를 가진다.
"""

import asyncio
import socket
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

TIMEOUT_SECONDS = 5.0


class Recorder:
    """제너레이터와 background 태스크가 남기는 사건 순서. `finished`는 ASGI 호출이 반환됐다는
    신호다 — 응답·background·요청 정리(제너레이터 취소 포함)가 전부 그 안에서 끝난다."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.finished = asyncio.Event()

    def task(self, name: str) -> Callable[[], None]:
        def run() -> None:
            self.events.append(f"task:{name}")

        return run


async def run_probe(app: FastAPI, recorder: Recorder, *, disconnect_on: str | None) -> list[str]:
    """실제 uvicorn(httptools)으로 앱을 띄우고 POST 한 번을 보낸다. `disconnect_on`이 주어지면
    그 문자열이 든 SSE 이벤트를 받는 즉시 소켓을 닫는다. 받은 `data:` 줄들을 돌려준다. 돌아올 때 서버는 내려가 있다."""
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
        async with asyncio.timeout(TIMEOUT_SECONDS):
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

        await asyncio.wait_for(recorder.finished.wait(), TIMEOUT_SECONDS)
        return received
    finally:
        server.should_exit = True
        await asyncio.wait_for(serve_task, TIMEOUT_SECONDS)
