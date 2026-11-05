"""`/api` 라우트. 신원 검사는 라우트 의존성이라 경로 인자 검증보다 먼저 돈다 — 다른 신원은 꼴이 틀린 경로에도 422 가 아니라
404 를 받는다.

라우트는 앱 라우터에 바로 단다. 하위 라우터를 `include_router` 로 붙이면 앱 라우트 표에 묶음 하나만 보여, 접근 기록이 라우팅 전에
경로 틀을 맞춰 보지 못한다.
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from chat_lab_service.access_log import record_of
from chat_lab_service.auth import HEALTH_PATH, require_human, require_uploader
from chat_lab_service.bundles import (
    COMPRESSED_LIMIT,
    MIB,
    delete_run,
    inflate,
    list_runs,
    parse_bundle,
    read_limited,
    store_version,
    stored_body,
    versions_of,
)
from chat_lab_service.db import db_errors_as_503
from chat_lab_service.errors import ServiceHTTPError, not_found
from chat_lab_service.schemas import (
    RUN_ID_PATTERN,
    SHA256_PATTERN,
    DeleteResult,
    Health,
    RunList,
    ServiceError,
    UploadHeader,
    UploadResult,
    VersionList,
)

UPLOAD_HEADER = "X-Lab-Upload-Header"
# 머리는 불·수·hex 뿐이라 수백 바이트다.
UPLOAD_HEADER_LIMIT = 4 * 1024
DELETE_BODY_LIMIT = 4 * 1024
BUNDLE_PATH = "/api/runs/{runId}/versions/{sha256}/bundle"

RunId = Annotated[str, Path(alias="runId", pattern=RUN_ID_PATTERN)]
Sha256 = Annotated[str, Path(pattern=SHA256_PATTERN)]


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {status: {"model": ServiceError} for status in statuses}


# 422 는 이 서비스의 거부(reason 있음)와 FastAPI 요청 검증 오류(reason 없음)가 함께 온다.
_UNPROCESSABLE: dict[int | str, dict[str, Any]] = {
    422: {
        "description": "이 서비스의 거부(reason 있음) 또는 요청 검증 오류(reason 없음)",
        "content": {
            "application/json": {
                "schema": {
                    "anyOf": [
                        {"$ref": "#/components/schemas/ServiceError"},
                        {"$ref": "#/components/schemas/HTTPValidationError"},
                    ]
                }
            }
        },
    }
}
_BUNDLE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "측정 서버 통째 응답(RunBundle) 그대로. gzip 을 받는 쪽에는 올린 gzip 바이트 그대로"
        "(Content-Encoding: gzip), 아니면 풀어서 보낸다.",
        "content": {"application/json": {"schema": {"type": "object"}}},
    },
    **_errors(401, 404, 503),
}
_UPLOAD_EXTRA: dict[str, Any] = {
    "parameters": [
        {
            "name": UPLOAD_HEADER,
            "in": "header",
            "required": True,
            "description": "측정 서버 올리기 머리 응답 JSON 그대로({sourceCommit, provenance})",
            "schema": {"type": "string"},
        }
    ],
    "requestBody": {
        "required": True,
        "description": "측정 서버 통째 응답(RunBundle) JSON 바이트의 gzip",
        "content": {"application/gzip": {"schema": {"type": "string", "format": "binary"}}},
    },
}
_DELETE_EXTRA: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "경로와 같은 runId — 폼·text/plain 교차 사이트 요청으로는 지울 수 없게 JSON 본문을 요구한다",
        "content": {
            "application/json": {
                "schema": {"type": "object", "required": ["runId"], "properties": {"runId": {"type": "string"}}}
            }
        },
    }
}


def _upload_header(request: Request) -> UploadHeader:
    """본문을 읽기 전에 머리부터 본다."""
    values = request.headers.getlist(UPLOAD_HEADER)
    if not values:
        raise ServiceHTTPError(422, "noUploadHeader", f"{UPLOAD_HEADER} 머리가 없다")
    if len(values) > 1 or len(values[0]) > UPLOAD_HEADER_LIMIT:
        raise ServiceHTTPError(
            422, "badUploadHeader", f"{UPLOAD_HEADER} 머리는 {UPLOAD_HEADER_LIMIT}바이트 이하 하나여야 한다"
        )
    try:
        header = UploadHeader.model_validate_json(values[0])
    except ValidationError:
        raise ServiceHTTPError(422, "badUploadHeader", f"{UPLOAD_HEADER} 머리의 모양이 틀렸다") from None
    if not header.provenance.holds():
        raise ServiceHTTPError(422, "provenanceFailed", "출처 판정이 실패한 런은 받지 않는다")
    return header


def _accepts_gzip(accept_encoding: str | None) -> bool:
    """`Accept-Encoding` 이 gzip 을 받는가 — `q=0` 은 거절이고, 이름이 없으면 `*` 를 따른다."""
    star = False
    for item in (accept_encoding or "").split(","):
        name, _, params = item.partition(";")
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        coding = name.strip().lower()
        if coding == "gzip":
            return quality > 0
        if coding == "*":
            star = quality > 0
    return star


async def _check_delete_body(request: Request, run_id: str) -> None:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    body = await read_limited(request, DELETE_BODY_LIMIT) if media_type == "application/json" else None
    try:
        document = json.loads(body) if body is not None else None
    except (ValueError, RecursionError):
        document = None
    if not isinstance(document, dict) or document.get("runId") != run_id:
        raise ServiceHTTPError(422, "badDeleteBody", "본문은 경로와 같은 runId 를 담은 application/json 이어야 한다")


def add_routes(router: APIRouter, engine: AsyncEngine, clock: Callable[[], datetime]) -> None:
    @router.head(HEALTH_PATH)
    @router.get(HEALTH_PATH)
    async def health() -> Health:
        """살아 있음만 알린다 — DB·판·설정 어느 것도 싣지 않는다. 토큰을 보지 않는다."""
        return Health(status="ok")

    @router.get("/api/runs", dependencies=[Depends(require_human)], responses=_errors(401, 404, 503))
    async def get_runs() -> RunList:
        async with db_errors_as_503():
            return RunList(items=await list_runs(engine))

    @router.get("/api/runs/{runId}/versions", dependencies=[Depends(require_human)], responses=_errors(401, 404, 503))
    async def get_versions(run_id: RunId) -> VersionList:
        """지우지 않은 판, 최신 먼저. 지우지 않은 판이 없으면 404."""
        async with db_errors_as_503():
            versions = await versions_of(engine, run_id)
        if not versions:
            raise not_found()
        return VersionList(run_id=run_id, versions=versions)

    @router.head(
        BUNDLE_PATH, dependencies=[Depends(require_human)], response_class=Response, responses=_BUNDLE_RESPONSES
    )
    @router.get(
        BUNDLE_PATH, dependencies=[Depends(require_human)], response_class=Response, responses=_BUNDLE_RESPONSES
    )
    async def get_bundle(run_id: RunId, sha256: Sha256, request: Request) -> Response:
        async with db_errors_as_503():
            stored = await stored_body(engine, run_id, sha256)
        if stored is None:
            raise not_found()
        head_only = request.method == "HEAD"
        record = record_of(request.scope)
        record.sha256 = sha256
        record.raw_served = stored.raw and not head_only
        headers = {"Vary": "Accept-Encoding"}
        if _accepts_gzip(request.headers.get("accept-encoding")):
            headers |= {"Content-Encoding": "gzip", "Content-Length": str(len(stored.body))}
            return Response(b"" if head_only else stored.body, headers=headers, media_type="application/json")
        headers["Content-Length"] = str(stored.uncompressed_size)
        if head_only:
            return Response(headers=headers, media_type="application/json")
        # 32MiB 를 한꺼번에 들지 않게 조각으로 풀어 보낸다. 동기 생성기라 Starlette 가 스레드에서 돌린다.
        return StreamingResponse(inflate(stored.body), headers=headers, media_type="application/json")

    @router.post(
        "/api/runs/{runId}/versions",
        status_code=201,
        responses={
            200: {"model": UploadResult, "description": "같은 내용이 이미 있거나(exists) 지운 판을 되살렸다(restored)"},
            **_errors(401, 404, 413, 503),
            **_UNPROCESSABLE,
        },
        openapi_extra=_UPLOAD_EXTRA,
    )
    async def upload(
        run_id: RunId, request: Request, response: Response, uploader: Annotated[str, Depends(require_uploader)]
    ) -> UploadResult:
        """판 올리기 — 신원 → runId 꼴 → 머리(본문을 읽기 전) → 선언 길이 → 실제로 읽은 길이 → 풀기·sha·JSON → 묶음 모양 → DB."""
        header = _upload_header(request)
        declared = request.headers.get("content-length", "")
        too_large = ServiceHTTPError(413, "tooLarge", f"압축 묶음이 {COMPRESSED_LIMIT // MIB}MiB 를 넘는다")
        # 읽을 수 없는 선언 길이는 무시하고 실제로 읽은 바이트로 판정한다. `isdigit` 은 위 첨자 숫자(latin-1 `²`)에도 참이라
        # ASCII 를 함께 본다 — 없으면 `int()` 가 ValueError 로 500 이 된다.
        if declared.isascii() and declared.isdigit() and int(declared) > COMPRESSED_LIMIT:
            raise too_large
        compressed = await read_limited(request, COMPRESSED_LIMIT)
        if compressed is None:
            raise too_large
        parsed = await anyio.to_thread.run_sync(parse_bundle, compressed, run_id)
        async with db_errors_as_503():
            status, number = await store_version(
                engine,
                run_id=run_id,
                compressed=compressed,
                parsed=parsed,
                header=header,
                uploader=uploader,
                now=clock(),
            )
        record_of(request.scope).sha256 = parsed.sha256
        if status != "created":
            response.status_code = 200
        return UploadResult(run_id=run_id, sha256=parsed.sha256, status=status, version_number=number)

    @router.delete(
        "/api/runs/{runId}", responses={**_errors(401, 404, 503), **_UNPROCESSABLE}, openapi_extra=_DELETE_EXTRA
    )
    async def remove_run(
        run_id: RunId, request: Request, email: Annotated[str, Depends(require_human)]
    ) -> DeleteResult:
        """그 런의 살아 있는 판을 모두 지운다. 지울 판이 없으면 404."""
        await _check_delete_body(request, run_id)
        async with db_errors_as_503():
            count = await delete_run(engine, run_id, deleted_by=email, now=clock())
        if count == 0:
            raise not_found()
        return DeleteResult(run_id=run_id, deleted_versions=count)
