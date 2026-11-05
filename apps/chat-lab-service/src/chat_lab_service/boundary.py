"""가장 바깥 미들웨어: 요청마다 접근 기록 한 행, 보안 머리·Cache-Control, 처리되지 않은 예외의 500.

Starlette 의 `ServerErrorMiddleware` 는 사용자 미들웨어 바깥이라 거기서 나는 500 에는 기록·머리가 빠진다 — 그래서 마지막 500 도
여기서 낸다.
"""

import ipaddress
import logging
import re
from collections.abc import Callable, Iterable
from datetime import datetime

from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.routing import Match, Router
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from chat_lab_service.access_log import AccessRecord, write_access_row
from chat_lab_service.errors import error_response
from chat_lab_service.schemas import RUN_ID_PATTERN

logger = logging.getLogger(__name__)

STATIC_ROUTE = "/{static}"
UNMATCHED_ROUTE = "unmatched"

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"referrer-policy", b"no-referrer"),
]
_REPLACED = {name for name, _ in _SECURITY_HEADERS} | {b"cache-control"}
_RUN_ID = re.compile(RUN_ID_PATTERN)


def is_api_path(path: str) -> bool:
    return path.startswith("/api/")


def _client_ip(scope: Scope) -> str | None:
    values = [value for name, value in scope["headers"] if name == b"cf-connecting-ip"]
    if len(values) != 1:
        return None
    try:
        return str(ipaddress.ip_address(values[0].decode("latin-1").strip()))
    except ValueError:
        return None


def _with_policy_headers(headers: Iterable[tuple[bytes, bytes]], cache_control: bytes) -> list[tuple[bytes, bytes]]:
    kept = [(name, value) for name, value in headers if name.lower() not in _REPLACED]
    return [*kept, *_SECURITY_HEADERS, (b"cache-control", cache_control)]


class Boundary:
    def __init__(self, app: ASGIApp, *, engine: AsyncEngine, clock: Callable[[], datetime], router: Router) -> None:
        self.app = app
        self.engine = engine
        self.clock = clock
        self.router = router

    def _route_of(self, scope: Scope) -> tuple[str, str | None]:
        """(경로 틀, runId). 라우팅 전에 앱의 라우트 표로 미리 맞춰 본다 — 인증에서 끝나 라우터까지 가지 않은 요청에도 남기려고.
        메서드만 다른 경로(405)도 그 경로의 틀이다."""
        partial: tuple[APIRoute, Scope] | None = None
        for route in self.router.routes:
            if not isinstance(route, APIRoute):
                continue
            match, child = route.matches(scope)
            if match is Match.FULL:
                return self._template(route, child)
            if match is Match.PARTIAL and partial is None:
                partial = (route, child)
        if partial is not None:
            return self._template(*partial)
        return (UNMATCHED_ROUTE if is_api_path(scope["path"]) else STATIC_ROUTE), None

    @staticmethod
    def _template(route: APIRoute, child: Scope) -> tuple[str, str | None]:
        run_id = child.get("path_params", {}).get("runId")
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            run_id = None
        return route.path_format, run_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        route, run_id = self._route_of(scope)
        record = AccessRecord(
            at=self.clock(), method=scope["method"], route=route, run_id=run_id, client_ip=_client_ip(scope)
        )
        # httpx 의 ASGI 전송은 `state` 를 주지 않고, uvicorn 은 요청마다 새 dict 를 준다.
        scope.setdefault("state", {})["access"] = record
        static = not is_api_path(scope["path"])
        started = False

        async def send_with_policy(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                record.status = message["status"]
                # 해시 없는 index.html 이 옛 판으로 남지 않게 정적 파일은 매번 다시 확인시키고(ETag), API 와 오류는 남기지 않는다.
                cache_control = b"no-cache" if static and record.status < 400 else b"no-store"
                message = {**message, "headers": _with_policy_headers(message.get("headers", []), cache_control)}
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_policy)
            except Exception as error:
                # 예외 글에는 토큰·SQL·바인드 값이 섞일 수 있다.
                logger.error("처리하지 못한 예외: %s", type(error).__name__)
                record.reason = "internal"
                if not started:
                    await error_response(500, "internal", "서버 오류")(scope, receive, send_with_policy)
        finally:
            # 응답을 다 보낸 뒤가 거부까지 모든 상태를 아는 유일한 때다. 실패해도 이미 나간 응답은 바꾸지 않는다 — DB 가
            # 죽었으면 데이터 경로는 이미 503 이다.
            try:
                await write_access_row(self.engine, record)
            except Exception as error:
                logger.error("접근 기록을 쓰지 못했다: %s", type(error).__name__)
