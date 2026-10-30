"""로컬 측정 서버(chat-lab)의 FastAPI 앱. 응답은 `chat_lab.schemas` 의 모델이고, 값은 라이브러리 함수(`chat_lab.report`)가 낸
그대로다 — 서버가 결합·지표를 따로 계산하지 않는다.

운영 앱에 붙지 않는 개발 PC 도구라 인증이 없다. 그래서 위험면은 그 PC 의 브라우저와 같은 망이고, 가드는 넷이다.
- 바인드는 127.0.0.1 만(진입 스크립트). 같은 망의 다른 기기를 막는다.
- Host 허용 목록(127.0.0.1·localhost). 악성 페이지가 자기 도메인을 127.0.0.1 로 다시 풀게 하는 DNS rebinding 은 브라우저가 그
  도메인 이름을 Host 로 보내므로 여기서 막힌다(CORS 는 rebinding 을 막지 못한다).
- CORS 는 측정 웹 dev 오리진만. 다른 오리진의 페이지는 응답을 읽지 못한다.
- POST 는 JSON 본문만. 폼·`text/plain` POST 는 브라우저가 사전 요청 없이 어느 사이트에서나 보내므로(CSRF) 라우팅 전에 415 로
  끊는다. JSON 이면 브라우저가 사전 요청을 거치고, 그것은 CORS 가 막는다.
묶음 id 는 루트 기준 상대 경로를 감싼 것이고 되돌릴 때 루트 밖·링크를 거부한다(`chat_lab.run_id`). 쓰기는 턴 기록 내보내기
하나뿐이고 `archive/` 아래를 거부한다(`chat_lab.export_turns`).

DB 는 내보내기 때만 연다. 앱을 만들 때 로컬 DB 가드만 걸고 엔진은 첫 내보내기 요청 때 만든다 — 목록·상세·기동은 DB·Redis
어디에도 접속하지 않고 LLM 클라이언트도 만들지 않는다. 운영 설정을 읽는 DB 세션 모듈(`api.db.session`)은 import 하지 않는다
(import 만으로 운영 설정의 엔진을 만든다). 앱을 만들 때 파일 시스템도 보지 않는다 — 스키마만 떨굴 때 런 루트가 없어도 된다.

오류 본문은 모두 `LabError`(`detail` 글 + `reason` 종류)다. FastAPI 의 요청 검증 오류(422)만 기본 모양(`detail` 이 목록, `reason`
없음)으로 남아, 웹은 `reason` 이 있는지로 둘을 가른다. 경로마다 실제로 내는 상태 코드를 스키마에 적는다."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, Query, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from chat_lab.catalog import BundleOpenError, RunCatalog, RunNotFoundError
from chat_lab.export_turns import ExportRefusal, ExportRefusedError, export_chat_turns, read_only_engine
from chat_lab.join import JoinedRun
from chat_lab.report import run_bundle, run_detail, run_metrics, turn_detail
from chat_lab.schemas import (
    ExportTurnsRequest,
    ExportTurnsResult,
    Health,
    LabError,
    LabErrorReason,
    RunBundle,
    RunDetail,
    RunList,
    RunMetrics,
    TurnDetail,
)
from replay.local_db import ensure_local_database

TITLE = "chat-lab"
VERSION = "1"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
# 측정 웹 dev 서버(포트 고정)의 오리진.
LAB_WEB_ORIGINS = ("http://127.0.0.1:5291", "http://localhost:5291")
# 본문을 바꾸는 메서드 — 이 서버에는 POST 하나뿐이지만 경로가 늘어도 같은 가드가 걸리게 메서드로 판정한다.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# 내보내기 거부 → 상태 코드. 409 는 "이미 있음" 하나다 — 웹이 강제로 다시 내보내기를 권하는 것은 이 경우뿐이어야 해서(링크·폴더가
# 그 자리에 있으면 강제로도 못 쓴다). 보관 폴더는 403, 나머지는 이 묶음·이 DB 로는 내보낼 수 없다는 422(상세의 "지원 안 함"과 같다).
EXPORT_STATUS: dict[ExportRefusal, int] = {
    "archived": 403,
    "exists": 409,
    "notFile": 422,
    "unsupported": 422,
    "multipleRooms": 422,
    "noRoom": 422,
    "noRows": 422,
}

RunId = Annotated[str, PathParam(alias="runId")]

_LAB_ERROR: dict[str, Any] = {"model": LabError}
# 422 는 이 서버의 거부(`LabError`)와 FastAPI 의 요청 검증 오류가 함께 온다 — 둘 다 적는다. 검증 오류 스키마는 FastAPI 가 넣는다.
_UNPROCESSABLE: dict[str, Any] = {
    "description": "이 서버의 거부(reason 있음) 또는 요청 검증 오류(reason 없음)",
    "content": {
        "application/json": {
            "schema": {
                "anyOf": [
                    {"$ref": "#/components/schemas/LabError"},
                    {"$ref": "#/components/schemas/HTTPValidationError"},
                ]
            }
        }
    },
}
_READ_ERRORS: dict[int | str, dict[str, Any]] = {404: _LAB_ERROR, 422: _UNPROCESSABLE}
_EXPORT_ERRORS: dict[int | str, dict[str, Any]] = {
    403: _LAB_ERROR,
    404: _LAB_ERROR,
    409: _LAB_ERROR,
    415: _LAB_ERROR,
    422: _UNPROCESSABLE,
    503: _LAB_ERROR,
}


class LabHTTPError(Exception):
    def __init__(self, status: int, reason: LabErrorReason, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.reason = reason
        self.detail = detail


def _error_response(status: int, reason: LabErrorReason, detail: str) -> JSONResponse:
    return JSONResponse(
        LabError(detail=detail, reason=reason).model_dump(mode="json", by_alias=True), status_code=status
    )


class JsonWritesOnly:
    """본문을 바꾸는 요청은 `Content-Type: application/json` 만 받는다(라우팅 전, 없는 경로여도)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in WRITE_METHODS:
            media_type = Headers(scope=scope).get("content-type", "").split(";")[0].strip().lower()
            if media_type != "application/json":
                response = _error_response(415, "notJson", "본문은 application/json 이어야 한다")
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _default_sessions(database_url: str) -> SessionFactory:
    """첫 요청 때 읽기 전용 엔진을 만드는 세션 팩토리."""
    made: list[async_sessionmaker[AsyncSession]] = []

    def open_session() -> AbstractAsyncContextManager[AsyncSession]:
        if not made:
            made.append(async_sessionmaker(read_only_engine(database_url), expire_on_commit=False))
        return made[0]()

    return open_session


def create_app(*, root: Path, database_url: str | None, session_factory: SessionFactory | None = None) -> FastAPI:
    """`database_url` 이 로컬 DB 가 아니면 `SystemExit`(만들지 않는다). `session_factory` 를 주면 내보내기가 그 세션을 쓴다
    (테스트가 자기 트랜잭션을 넣는 자리). 둘 다 없으면 내보내기는 503 이다(스키마만 떨구는 앱)."""
    if database_url is not None:
        ensure_local_database(database_url, tool="chat-lab")
    sessions = session_factory
    if sessions is None and database_url is not None:
        sessions = _default_sessions(database_url)
    catalog = RunCatalog(root)

    app = FastAPI(title=TITLE, version=VERSION)
    # 마지막에 더한 것이 가장 바깥이다 — Host 를 먼저 보고, CORS, 그다음 본문 형식.
    app.add_middleware(JsonWritesOnly)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LAB_WEB_ORIGINS),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS), www_redirect=False)

    @app.exception_handler(LabHTTPError)
    async def lab_error(request: Request, error: LabHTTPError) -> JSONResponse:
        return _error_response(error.status, error.reason, error.detail)

    def joined(run_id: str) -> JoinedRun:
        try:
            return catalog.joined(run_id)
        except RunNotFoundError as error:
            raise LabHTTPError(404, "notFound", "그런 묶음이 없다") from error
        except BundleOpenError as error:
            raise LabHTTPError(422, error.reason, f"이 묶음은 열지 않는다: {error}") from error

    @app.get("/health")
    def health() -> Health:
        return Health(status="ok")

    @app.get("/runs")
    def list_runs(refresh: Annotated[bool, Query()] = False) -> RunList:
        """런 목록. 처음 부를 때와 `refresh` 일 때 루트를 훑는다(실데이터에서 수십 초)."""
        return catalog.runs(refresh=refresh)

    @app.get("/runs/{runId}", responses=_READ_ERRORS)
    def get_run(run_id: RunId) -> RunDetail:
        return run_detail(joined(run_id))

    @app.get("/runs/{runId}/turns/{clientTurn}", responses=_READ_ERRORS)
    def get_turn(run_id: RunId, client_turn: Annotated[int, PathParam(alias="clientTurn")]) -> TurnDetail:
        run = joined(run_id)
        try:
            return turn_detail(run, client_turn)
        except KeyError as error:
            raise LabHTTPError(404, "notFound", "그런 턴이 없다") from error

    @app.get("/runs/{runId}/metrics", responses=_READ_ERRORS)
    def get_metrics(run_id: RunId) -> RunMetrics:
        return run_metrics(joined(run_id))

    @app.get("/runs/{runId}/bundle", responses=_READ_ERRORS)
    def get_bundle(run_id: RunId, raw: Annotated[bool, Query()]) -> RunBundle:
        """정적 HTML 내보내기용 통째 응답. `raw` 가 거짓이면 프롬프트·지시문·기억 스냅숏 본문을 뺀다."""
        return run_bundle(joined(run_id), raw=raw)

    @app.post("/runs/{runId}/export-turns", responses=_EXPORT_ERRORS)
    async def export_turns(run_id: RunId, request: Annotated[ExportTurnsRequest, Body()]) -> ExportTurnsResult:
        """로컬 DB 에서 이 묶음 방의 턴 기록을 묶음 폴더의 `chat-turns.jsonl` 로 쓴다. LLM 호출은 없다."""
        try:
            bundle = await run_in_threadpool(catalog.find, run_id)
        except RunNotFoundError as error:
            raise LabHTTPError(404, "notFound", "그런 묶음이 없다") from error
        if sessions is None:
            raise LabHTTPError(503, "dbUnavailable", "이 서버에는 DB 가 설정되지 않았다")
        try:
            async with sessions() as session:
                written = await export_chat_turns(session, bundle, force=request.force)
        except ExportRefusedError as error:
            raise LabHTTPError(EXPORT_STATUS[error.reason], error.reason, str(error)) from error
        except (SQLAlchemyError, OSError) as error:
            raise LabHTTPError(
                503, "dbUnavailable", f"내보내기를 마치지 못했다(DB 접속·파일 쓰기): {type(error).__name__}: {error}"
            ) from error
        entry = await run_in_threadpool(catalog.entry, run_id)
        return ExportTurnsResult(path=written.relative_to(bundle.root).as_posix(), run=entry)

    return app
