import asyncio
import atexit
import logging
import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import asyncpg
import boto3
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# boto3 resolves and caches credentials once, at client-construction time (see
# api/core/s3.py's module-level `s3_client`) — these must be set before that
# module is first imported (via `from api.main import app` below), or presigned
# URL signing fails with NoCredentialsError even under moto in individual tests.
#
# Overwritten, not `setdefault`: `uv run --env-file .env pytest` puts the developer's
# real object-storage credentials in the environment, and combined with the same
# leak on S3_ENDPOINT_URL below that pointed the whole suite at a live Cloudflare R2
# bucket. Tests must only ever talk to their own moto server.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

# A real local S3-compatible server (moto's own recommended approach for
# multi-threaded code), not the `mock_aws()` decorator: `get_object_size`/
# `generate_presigned_put_url` run inside FastAPI's anyio threadpool worker
# threads via `run_in_threadpool`, and empirically `mock_aws()`'s patch of
# `botocore.client.BaseClient._make_api_call` does not reliably apply inside
# those threads once `api.main` (and its module-level `s3_client`) has been
# imported — HeadObject calls silently fall through to real AWS and get a real
# 403. A real server has no such gap: every client, any thread, hits one socket.
# Must start (and know its port) BEFORE importing `api.main` below, since
# `api.core.s3`'s module-level `s3_client` reads `settings.s3_endpoint_url` at
# import time.
from moto.server import ThreadedMotoServer

_moto_server = ThreadedMotoServer(port=0)
_moto_server.start()
atexit.register(_moto_server.stop)
_moto_host, _moto_port = _moto_server.get_host_and_port()
# Overwritten, not `setdefault` — see the credentials note above: `.env`'s endpoint
# would otherwise win and send the suite at whatever storage the developer is
# currently pointed at (the dev moto container at best, production R2 at worst).
os.environ["S3_ENDPOINT_URL"] = f"http://{_moto_host}:{_moto_port}"

# Tests get their own database and Redis index inside the same local Postgres/Redis
# as dev. `_migrated_schema` below ends every session with `alembic downgrade base`,
# which drops every table it finds — aimed at the dev database that wipes the local
# workspace, and the app then 500s on its first query until someone re-runs
# `alembic upgrade head` and the seed.
#
# Direct assignment, not `setdefault`: `uv run --env-file .env pytest` injects the
# dev DATABASE_URL into the process environment before this file is imported, and
# `setdefault` would silently keep it. Real env vars also outrank `.env` in
# pydantic-settings, so this beats the file too. Both must be set before
# `api.core.config` is imported below, since `settings` is read at import time by
# `api.db.session`'s engine and `api.core.redis`'s client.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_character_chat_test",
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")

# pytest-xdist (`-n`) workers are separate processes that each run the session fixtures —
# sharing one database, every worker's `alembic downgrade base` would drop tables under the
# others, and the Redis flush fixtures below delete by key pattern, which would wipe keys
# another worker's test is using. So each worker gets its own database (`…_gw0_test`, still
# ending in `_test` for the guard below) and its own Redis index (base index + worker number;
# Redis ships 16 indexes, so this holds up to `-n 15` on the default `/1`).
_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _xdist_worker is not None:
    _db_url = make_url(os.environ["DATABASE_URL"])
    _db_name = _db_url.database or ""
    _db_name = f"{_db_name.removesuffix('_test')}_{_xdist_worker}_test"
    os.environ["DATABASE_URL"] = _db_url.set(database=_db_name).render_as_string(hide_password=False)
    _redis_base, _, _redis_index = os.environ["REDIS_URL"].rpartition("/")
    os.environ["REDIS_URL"] = f"{_redis_base}/{int(_redis_index) + int(_xdist_worker.removeprefix('gw'))}"

from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
from api.content.publish_filter_memo import PASSED_KEY_PREFIX
from api.core.config import settings
from api.core.redis import redis_client
from api.db.session import engine
from api.llm.usage_store import USAGE_KEY_PREFIX
from api.db.session import get_db_session, get_session_factory
from api.main import app

APPS_API_DIR = Path(__file__).resolve().parents[1]


def _create_test_database_if_missing() -> None:
    """`CREATE DATABASE` the test database unless it already exists.

    Postgres has no `CREATE DATABASE IF NOT EXISTS` and refuses to run the
    statement inside a transaction, so this goes through a raw asyncpg connection
    to the `postgres` maintenance database rather than the app's engine. Only the
    database *shell* is managed here — it is never dropped; `_migrated_schema`
    owns the tables inside it.
    """
    url = make_url(settings.database_url)
    if url.database is None or not url.database.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against database {url.database!r}: this session ends "
            "with `alembic downgrade base`, which drops every table in it. The test "
            "database name must end with '_test' (override via TEST_DATABASE_URL)."
        )

    async def _create() -> None:
        connection = await asyncpg.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            database="postgres",
        )
        try:
            exists = await connection.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", url.database
            )
            if exists is None:
                await connection.execute(f'CREATE DATABASE "{url.database}"')
        finally:
            await connection.close()

    asyncio.run(_create())


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema() -> Generator[None, None, None]:
    """Apply every migration before the test session, then fully unwind them after.

    This is the executable proof (not just a manual check) that `alembic upgrade
    head` / `downgrade base` both work end-to-end against a real Postgres.
    """
    _create_test_database_if_missing()
    config = Config(str(APPS_API_DIR / "alembic.ini"))
    command.upgrade(config, "head")
    # `migrations/env.py` calls `fileConfig(alembic.ini)`, whose default
    # `disable_existing_loggers=True` disables every *already-created* logger not
    # explicitly named in alembic.ini's `[loggers]` (root/sqlalchemy/alembic only) —
    # a classic stdlib logging gotcha. By this point `from api.main import app` above
    # has already imported every `src/api/**` module, so every one of their
    # `logging.getLogger(__name__)` loggers already exists and just got silently
    # disabled (`Logger.disabled = True`, which makes `.warning()`/`.info()` complete
    # no-ops — confirmed empirically, not just theoretically). This never bites
    # production (there, migrations run as a separate one-off process, not inside the
    # long-lived server), but inside this single test process it would otherwise mean
    # `caplog`-based assertions on any app-code `logger.warning(...)` (e.g. this diff's
    # Redis-failure warnings) silently see nothing. Re-enabling here undoes only that
    # side effect.
    for existing_logger in logging.Logger.manager.loggerDict.values():
        if isinstance(existing_logger, logging.Logger):
            existing_logger.disabled = False
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture(autouse=True)
async def _flush_prompt_set_cache() -> None:
    """`prompt_set:active:{lane}`는 고정 키라 나머지 Redis 모듈과 달리 세션ID/잡ID 같은 랜덤 값으로 테스트끼리
    격리되지 않는다 — `db_session`은 테스트마다 롤백되지만 Redis는 그대로다. 한 테스트가
    캐싱한 세트를 다음 테스트가 그대로 보게 되므로 매 테스트 전에 지운다.

    아래 `_flush_rate_limit_keys`와 같은 이유로 glob이다 — 레인이 늘 때 하드코딩된 키
    나열 중 한쪽만 갱신되는 사고를 막는다."""
    keys = await redis_client.keys(f"{ACTIVE_PROMPT_SET_KEY_PREFIX}*")
    if keys:
        await redis_client.delete(*keys)


@pytest_asyncio.fixture(autouse=True)
async def _flush_rate_limit_keys() -> None:
    """`rate_limit:*` 키도 위 `_flush_prompt_set_cache`와 같은
    범주다 — IP 기반 키(`rate_limit:signup_ip:...` 등)는 `httpx.ASGITransport`의 client
    기본값이 모든 테스트에서 `('127.0.0.1', 123)`이라 랜덤 값(email/session_id/token)으로
    자연 격리되지 않는다. 안 지우면 무관한 테스트가 쌓아둔 IP 카운터 때문에 뒤에 실행되는
    테스트가 실행 순서에 따라 간헐적으로 429를 받는다."""
    keys = await redis_client.keys("rate_limit:*")
    if keys:
        await redis_client.delete(*keys)


@pytest_asyncio.fixture(autouse=True)
async def _flush_llm_usage_keys() -> None:
    """LLM 사용량 집계는 날짜 하나에 해시 하나라 랜덤 값으로 격리되지 않는다 — 실제
    `GeminiLLMClient` 를 쓰는 테스트가 오늘 해시에 쌓은 수가 다음 테스트의 단언에 섞인다."""
    keys = await redis_client.keys(f"{USAGE_KEY_PREFIX}*")
    if keys:
        await redis_client.delete(*keys)


@pytest_asyncio.fixture(autouse=True)
async def _flush_publish_filter_passes() -> None:
    """발행 심사 통과 기억은 키에 콘텐츠 id 가 들어가 테스트끼리 자연히 갈리지만, Redis 는 테스트마다
    롤백되지 않으므로 앞 테스트가 남긴 기억이 쌓이지 않게 지운다."""
    keys = await redis_client.keys(f"{PASSED_KEY_PREFIX}*")
    if keys:
        await redis_client.delete(*keys)


@pytest_asyncio.fixture(autouse=True)
async def _flush_local_image_keys() -> None:
    """이미지 생성 대기열·생성 락은 모든 워커가 함께 보는 고정 키라 테스트끼리 자연히 갈리지 않는다.
    잡을 돌리지 않는 테스트가 admit 한 칸은 반납되지 않은 채 남으므로(만료까지 60초) 지우지
    않으면 다음 테스트가 `QUEUE_FULL` 을 받는다."""
    keys = await redis_client.keys("local_image:*")
    if keys:
        await redis_client.delete(*keys)


@pytest_asyncio.fixture(scope="session")
async def api_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Session-scoped, `ASGITransport`-based (not `TestClient`): `TestClient`
    dispatches every call through its own background-thread event loop ("portal"),
    a *different* loop than this session's pytest-asyncio loop. Module-level
    singletons with their own connection pools (`redis_client`, the DB `engine`)
    get bound to whichever loop first uses them — mixing the two loops across the
    test session corrupts those pools (cross-loop "Future attached to a different
    loop" errors), confirmed empirically. `ASGITransport` calls the ASGI app as a
    coroutine directly on the caller's loop, so every test in this session shares
    the one loop.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(scope="session")
def s3_bucket() -> None:
    """Creates the app's S3 bucket once against the session's moto server."""
    client = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    client.create_bucket(
        Bucket=settings.s3_bucket_name,
        # boto3-stubs wants a region Literal; settings.aws_region is a plain str.
        CreateBucketConfiguration={"LocationConstraint": settings.aws_region},  # type: ignore[typeddict-item]
    )
    return None


@pytest.fixture
def db_engine() -> AsyncEngine:
    return engine


@pytest_asyncio.fixture
async def ddl_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """마이그레이션 함수(DDL)를 롤백되는 트랜잭션 안에서 직접 돌리는 테스트용 엔진. 공용 풀 밖에서 돌린다 — 공용 풀
    커넥션에 남은 준비된 문장 캐시가 롤백으로 사라진 테이블·타입 OID 를 가리키지 않게 하려고 풀 없는 엔진을 따로
    만든다. 잠금을 기다리다 멈추지 않게 `lock_timeout` 을 건다."""
    ddl = create_async_engine(
        db_engine.url.render_as_string(hide_password=False),
        poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "5s"}},
    )
    yield ddl
    await ddl.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Each test runs inside its own transaction that is rolled back afterward.

    Session's default `join_transaction_mode="conditional_savepoint"` means a
    `commit()` issued by application code (e.g. inside a router) only releases a
    SAVEPOINT here, not the real outer transaction — verified empirically, not
    just assumed. So writes made through this session are visible everywhere
    that shares its connection, but never survive past this fixture's rollback.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


@pytest_asyncio.fixture
async def db_client(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """`api_client`, but with the app's real DB dependency overridden to this
    test's own rolled-back `db_session` — so API requests and test setup code
    (e.g. inserting a user row to log in as) share one transaction and nothing
    written during the test ever persists.

    Also overrides `get_session_factory` (used by code that opens its own DB
    session outside a request's lifetime, e.g. `api.images.router`'s asyncio
    background task) with a sessionmaker bound to the *same* connection as
    `db_session` — verified empirically that sessions sharing a connection
    share its transaction (conditional_savepoint join mode), so writes made
    through it are visible to `db_session` assertions and still roll back.
    """

    async def _get_db_session_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    app.dependency_overrides[get_db_session] = _get_db_session_override
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    api_client.cookies.clear()
    try:
        yield api_client
    finally:
        del app.dependency_overrides[get_db_session]
        del app.dependency_overrides[get_session_factory]


@pytest_asyncio.fixture
async def committing_request_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[None, None]:
    """요청 세션의 커밋이 진짜 경계가 되게 한다. `db_session` 은 바깥 트랜잭션에 그대로 얹혀 커밋이 아무것도 확정하지
    않고 롤백은 테스트 셋업까지 지운다 — 그 위에서는 "중간 커밋이 있었는지"가 결과에 드러나지 않는다. 여기서는 요청마다
    같은 커넥션 위에 SAVEPOINT 로 새 세션을 열어, 커밋은 그 SAVEPOINT 를 확정하고 실패한 요청은 운영처럼 세션이 닫히며
    마지막 커밋 뒤의 쓰기만 되돌린다. 셋업과 단언은 여전히 `db_session` 으로 같은 커넥션을 본다."""
    connection = db_session.bind

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: async_sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield
    # `db_client` 가 끝나며 두 키를 지우므로 되돌릴 것이 없다.
