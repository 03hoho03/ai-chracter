"""앱 팩토리.

미들웨어 순서(바깥→안): `Boundary`(접근 기록·보안 머리·마지막 500) → `AuthMiddleware`(토큰·신원) → FastAPI 예외 처리 → 라우터.
라우터에는 `/api` 라우트만 있고, 맞는 라우트가 없는 `/api/` 밖 경로는 라우터의 기본 처리기가 정적 웹으로 넘긴다 — 정적 웹을
`/` 에 마운트하면 그 마운트가 모든 경로에 맞아 `/api` 의 405 를 가로챈다.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from jwt import PyJWKClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from chat_lab_service.access_log import purge_daily, purge_logging_failure, record_of
from chat_lab_service.auth import AuthMiddleware, default_jwks_client
from chat_lab_service.boundary import Boundary, is_api_path
from chat_lab_service.db import check_schema, make_engine
from chat_lab_service.errors import NOT_FOUND_DETAIL, ServiceHTTPError, error_response
from chat_lab_service.routes import add_routes
from chat_lab_service.settings import Settings

TITLE = "chat-lab-service"
VERSION = "1"
# 요청 검증 오류 항목에서 남기는 칸 — FastAPI 기본은 받은 값(`input`)과 검증 맥락(`ctx`)을 되돌린다.
VALIDATION_KEYS = ("loc", "msg", "type")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _static_or_not_found(static: StaticFiles) -> ASGIApp:
    async def serve(scope: Scope, receive: Receive, send: Send) -> None:
        if is_api_path(scope["path"]):
            raise StarletteHTTPException(404)
        await static(scope, receive, send)

    return serve


def create_app(
    settings: Settings,
    *,
    jwks_client: PyJWKClient | None = None,
    clock: Callable[[], datetime] = utc_now,
    web_dir: Path | None = None,
) -> FastAPI:
    """`clock` 은 접근 기록 시각·올린 때·지운 때·90일 정리 기준이다. 엔진은 만들기만 하고 접속은 기동 점검 때 한다."""
    engine = make_engine(settings)
    keys = default_jwks_client(settings.access_issuer) if jwks_client is None else jwks_client
    # 폴더가 없어도 앱은 만든다 — 스키마만 떨굴 때는 정적 웹이 없다.
    static = StaticFiles(directory=web_dir or settings.web_dir, html=True, check_dir=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await check_schema(engine)
            await purge_logging_failure(engine, clock)
            purging = asyncio.create_task(purge_daily(engine, clock))
            try:
                yield
            finally:
                purging.cancel()
                with suppress(asyncio.CancelledError):
                    await purging
        finally:
            await engine.dispose()

    # 스키마는 파일로만 내보낸다(`openapi_text`). 슬래시만 다른 경로를 리다이렉트하지 않는다.
    app = FastAPI(
        title=TITLE,
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    add_routes(app.router, engine, clock)
    app.router.default = _static_or_not_found(static)

    @app.exception_handler(ServiceHTTPError)
    async def service_error(request: Request, error: ServiceHTTPError) -> Response:
        record_of(request.scope).reason = error.reason
        return error_response(error.status, error.reason, error.detail)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> Response:
        # 맞는 라우트가 없는 /api 경로와 없는 정적 파일 — 다른 404 와 같은 본문.
        if error.status_code == 404:
            record_of(request.scope).reason = "notFound"
            return error_response(404, "notFound", NOT_FOUND_DETAIL)
        return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> Response:
        detail = [{key: item[key] for key in VALIDATION_KEYS if key in item} for item in error.errors()]
        return JSONResponse({"detail": detail}, status_code=422)

    # 마지막에 더한 것이 가장 바깥이다.
    app.add_middleware(
        AuthMiddleware,
        jwks_client=keys,
        issuer=settings.access_issuer,
        audience=settings.access_aud,
        read_emails=settings.read_emails,
        upload_client_ids=settings.upload_client_ids,
    )
    app.add_middleware(Boundary, engine=engine, clock=clock, router=app.router)
    return app
