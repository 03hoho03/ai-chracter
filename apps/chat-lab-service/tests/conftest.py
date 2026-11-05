"""시험 DB·공개키 흉내·앱 픽스처.

환경 변수는 `TEST_DATABASE_URL` 하나만 읽는다. 세션이 그 DB 를 지우고 다시 만든 뒤 마이그레이션을 끝까지 올리고, 끝나면
끝까지 내린 다음 지운다 — 그래서 이름이 `_test` 로 끝나는 DB 만 받는다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import jwt.api_jwk
import jwt.jwk_set_cache
import jwt.jwks_client
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from jwt import PyJWKClient
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from harness import ASSET_JS, INDEX_HTML, SV_ROOT, Db, FakeClock, FakeMonotonic, Lab, OpenLab, make_settings
from keys import JwksServer

_DATABASE_NAME = re.compile(r"[A-Za-z0-9_]+_test")


def _test_database_url() -> tuple[str, URL]:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        raise pytest.UsageError(
            "TEST_DATABASE_URL 이 없다 — 이름이 _test 로 끝나는 시험 DB 주소를 준다(예: …/chat_lab_service_test)."
        )
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError):
        # 주소 원문에는 비밀번호가 들어 있어 오류 글에 싣지 않는다.
        raise pytest.UsageError("TEST_DATABASE_URL 을 URL 로 읽지 못했다.") from None
    if url.database is None or not _DATABASE_NAME.fullmatch(url.database):
        raise pytest.UsageError(
            f"시험 DB 이름 {url.database!r} 를 받지 않는다 — 세션이 그 DB 를 지우고 다시 만들므로 영문·숫자·밑줄로 된 "
            "_test 로 끝나는 이름만 쓴다."
        )
    return raw, url


def pytest_configure(config: pytest.Config) -> None:
    _test_database_url()


async def _run_on_maintenance_db(url: URL, *statements: str) -> None:
    connection = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
    )
    try:
        for statement in statements:
            await connection.execute(statement)
    finally:
        await connection.close()


def _alembic_config(raw_url: str) -> Config:
    config = Config(str(SV_ROOT / "alembic.ini"))
    # 명령을 친 자리와 무관하게 서비스 폴더의 마이그레이션을 쓴다.
    config.set_main_option("script_location", str(SV_ROOT / "migrations"))
    # 주소는 ini 옵션이 아니라 attributes 로 넘긴다 — ini 값은 ConfigParser 보간을 거쳐 비밀번호의 `%` 에서 깨진다.
    config.attributes["database_url"] = raw_url
    return config


def _reenable_loggers() -> None:
    # 마이그레이션 env.py 의 `fileConfig` 는 이미 만들어진 로거를 꺼 버린다(`disable_existing_loggers` 기본값). 이 프로세스는
    # 마이그레이션 뒤에도 앱을 돌리므로, 앱 로거의 경고·오류를 테스트가 볼 수 있게 다시 켠다.
    for existing in logging.Logger.manager.loggerDict.values():
        if isinstance(existing, logging.Logger):
            existing.disabled = False


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    raw_url, url = _test_database_url()
    name = url.database
    asyncio.run(
        _run_on_maintenance_db(url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', f'CREATE DATABASE "{name}"')
    )
    config = _alembic_config(raw_url)
    finished = False
    try:
        command.upgrade(config, "head")
        _reenable_loggers()
        yield raw_url
        command.downgrade(config, "base")
        finished = True
    finally:
        # 올리기·내리기가 실패해도 만든 DB 를 남기지 않는다. 정상 종료에서는 FORCE 없이 지운다 — 앱 엔진은 lifespan 이 끝날 때,
        # 시험 엔진은 먼저 정리되므로 남은 접속이 있으면 여기서 실패해 드러난다. 실패한 경우에는 그 마이그레이션이 남겼을 수
        # 있는 접속까지 끊고 지운다.
        drop = f'DROP DATABASE "{name}"' if finished else f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
        asyncio.run(_run_on_maintenance_db(url, drop))


@pytest_asyncio.fixture(scope="session")
async def db_engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine: AsyncEngine) -> Db:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE bundle_versions, access_log RESTART IDENTITY"))
    return Db(db_engine)


@pytest.fixture(scope="session")
def jwks_server() -> Iterator[JwksServer]:
    server = JwksServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def jwks(jwks_server: JwksServer) -> JwksServer:
    jwks_server.reset()
    return jwks_server


@pytest.fixture(autouse=True)
def fake_monotonic(monkeypatch: pytest.MonkeyPatch) -> FakeMonotonic:
    """PyJWT 의 공개키 캐시 수명·모르는 kid 쿨다운이 읽는 시계를 가짜로 둔다.

    세 모듈이 각자 `import time` 뒤 `time.monotonic()` 을 부르고 생성자로 시계를 받는 자리가 없다. 전역
    `time.monotonic` 을 바꾸면 asyncio 루프가 깨지므로 그 모듈들의 `time` 속성만 바꾼다. `setattr` 이 기본으로 없는 속성에
    실패하므로 라이브러리가 바뀌면 여기서 시끄럽게 깨진다.
    """
    fake = FakeMonotonic()
    for module in (jwt.jwks_client, jwt.jwk_set_cache, jwt.api_jwk):
        monkeypatch.setattr(module, "time", fake)
    return fake


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_bytes(INDEX_HTML)
    (root / "assets" / "app.js").write_bytes(ASSET_JS)
    return root


def mock_jwks_client(server: JwksServer) -> PyJWKClient:
    """운영 기본값과 같은 캐시 수명(300초)·쿨다운(기본 30초)으로 흉내 주소를 가리킨다."""
    return PyJWKClient(server.url, cache_jwk_set=True, lifespan=300, timeout=5)


@pytest.fixture
def open_lab(db: Db, jwks: JwksServer, clock: FakeClock, web_dir: Path) -> OpenLab:
    """앱을 만들고 lifespan 안에서 ASGI 클라이언트를 연다.

    httpx 의 `ASGITransport` 는 lifespan 을 보내지 않으므로 직접 들어간다 — 운영과 같은 기동 점검·정리 작업을 테스트도
    거친다. `keys_client="default"` 면 공개키 클라이언트를 넘기지 않아 앱이 기본 클라이언트를 만든다.
    """

    @asynccontextmanager
    async def _open(*, keys_client: Any = "mock", settings: Any = None) -> AsyncIterator[Lab]:
        from chat_lab_service.app import create_app

        chosen_settings = settings if settings is not None else make_settings(web_dir)
        if keys_client == "default":
            app = create_app(chosen_settings, clock=clock, web_dir=web_dir)
        else:
            client_for_keys = mock_jwks_client(jwks) if keys_client == "mock" else keys_client
            app = create_app(chosen_settings, jwks_client=client_for_keys, clock=clock, web_dir=web_dir)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield Lab(client=client, app=app, clock=clock, jwks=jwks, web_dir=web_dir)

    return _open


@pytest_asyncio.fixture
async def lab(open_lab: OpenLab) -> AsyncIterator[Lab]:
    async with open_lab() as opened:
        yield opened
