"""테스트가 함께 쓰는 자리·시계·DB 도우미와 응답 단언."""

from __future__ import annotations

import os
import tracemalloc
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from keys import AUD, ISSUER, READ_EMAILS_SETTING, UPLOAD_CLIENT_IDS_SETTING, JwksServer

SV_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SV_ROOT.parents[1]
MEASUREMENT_OPENAPI = REPO_ROOT / "apps" / "chat-lab" / "openapi.json"
SERVICE_OPENAPI = REPO_ROOT / "apps" / "chat-lab" / "service-openapi.json"

MIB = 1024 * 1024
# 올리기 상한 — 압축 바이트 8MiB, 푼 JSON 32MiB. 상한과 같은 크기는 받고 1바이트라도 넘으면 413 이다.
COMPRESSED_LIMIT = 8 * MIB
UNCOMPRESSED_LIMIT = 32 * MIB

CLOCK_START = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)

INDEX_HTML = b"<!doctype html><title>chat-lab</title>\n"
ASSET_JS = b"console.log('chat-lab');\n"

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "frame-ancestors 'none'",
    "referrer-policy": "no-referrer",
}


def database_url_for_tests() -> str:
    """conftest 가 기동 때 이미 확인한 시험 DB 주소."""
    return os.environ["TEST_DATABASE_URL"]


def make_settings(web_dir: Path, **overrides: Any) -> Any:
    """시험 설정 — 환경 변수·env 파일을 읽지 않게 모든 칸을 직접 준다. 목록 칸은 env 와 같은 쉼표 구분 꼴이다."""
    from chat_lab_service.settings import Settings

    values: dict[str, Any] = {
        "database_url": database_url_for_tests(),
        "access_issuer": ISSUER,
        "access_aud": AUD,
        "read_emails": READ_EMAILS_SETTING,
        "upload_client_ids": UPLOAD_CLIENT_IDS_SETTING,
        "web_dir": web_dir,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class FakeClock:
    """서비스 시계 — 올린 때·지운 때·접근 기록 시각·90일 정리 기준이 이 값을 쓴다."""

    def __init__(self, start: datetime = CLOCK_START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> datetime:
        self.now = self.now + timedelta(**delta)
        return self.now


class FakeMonotonic:
    """PyJWT 공개키 캐시·쿨다운이 읽는 `time` 모듈 자리. `monotonic` 하나만 있으면 된다."""

    def __init__(self) -> None:
        self.value = 1000.0

    def monotonic(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class Db:
    """시험 DB 를 직접 읽고 쓴다 — 앱을 거치지 않고 표의 실제 상태를 본다."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def fetch(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            return [dict(row._mapping) for row in result]

    async def scalar(self, sql: str, **params: Any) -> Any:
        async with self.engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def execute(self, sql: str, **params: Any) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def access_rows(self) -> list[dict[str, Any]]:
        return await self.fetch("SELECT * FROM access_log ORDER BY id")

    async def insert_access_row(self, at: datetime, *, route: str = "/api/runs") -> None:
        await self.execute(
            "INSERT INTO access_log (at, identity_kind, method, route, status) VALUES (:at, 'none', 'GET', :route, 401)",
            at=at,
            route=route,
        )

    async def last_access_row(self) -> dict[str, Any]:
        rows = await self.fetch("SELECT * FROM access_log ORDER BY id DESC LIMIT 1")
        assert rows, "접근 기록이 한 행도 없다"
        return rows[0]


@dataclass
class Lab:
    """lifespan 안에서 연 앱 하나와 그 앱이 쥔 시계·공개키 흉내."""

    client: httpx.AsyncClient
    app: Any
    clock: FakeClock
    jwks: JwksServer
    web_dir: Path


OpenLab = Callable[..., AbstractAsyncContextManager[Lab]]


def assert_security_headers(response: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, (name, response.request.url.path, response.headers.get(name))


def assert_error(response: httpx.Response, status: int, reason: str) -> dict[str, Any]:
    """오류 응답은 `{"detail": str, "reason": …}` 이고 보안 머리와 `no-store` 를 단다."""
    assert response.status_code == status, (response.status_code, response.text[:500])
    body = response.json()
    assert set(body) == {"detail", "reason"}, body
    assert isinstance(body["detail"], str)
    assert body["reason"] == reason, body
    assert response.headers.get("cache-control") == "no-store"
    assert_security_headers(response)
    return dict(body)


def assert_request_validation_error(response: httpx.Response) -> None:
    """FastAPI 요청 검증 422 — `reason` 이 없고 항목은 `loc`·`msg`·`type` 만 싣는다(받은 값·검증 맥락은 뺀다)."""
    assert response.status_code == 422, (response.status_code, response.text[:500])
    body = response.json()
    assert "reason" not in body, body
    assert isinstance(body["detail"], list) and body["detail"], body
    for item in body["detail"]:
        assert set(item) == {"loc", "msg", "type"}, item
    assert response.headers.get("cache-control") == "no-store"
    assert_security_headers(response)


async def measure_peak(action: Callable[[], Awaitable[httpx.Response]]) -> tuple[httpx.Response, int]:
    """요청 하나 동안의 파이썬 할당 정점(바이트). 요청 전에 만든 테스트 쪽 바이트는 세지 않는다."""
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    tracemalloc.reset_peak()
    baseline, _ = tracemalloc.get_traced_memory()
    try:
        response = await action()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if not was_tracing:
            tracemalloc.stop()
    return response, peak - baseline
