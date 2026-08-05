import asyncio
import atexit
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
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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
# multi-threaded code), not the `mock_aws()` decorator: `object_exists`/
# `generate_presigned_put_url` run inside FastAPI's anyio threadpool worker
# threads via `run_in_threadpool`, and empirically `mock_aws()`'s patch of
# `botocore.client.BaseClient._make_api_call` does not reliably apply inside
# those threads once `api.main` (and its module-level `s3_client`) has been
# imported — HeadObject calls silently fall through to real AWS and get a real
# 403. A real server has no such gap: every client, any thread, hits one socket.
# Must start (and know its port) BEFORE importing `api.main` below, since
# `api.core.s3`'s module-level `s3_client` reads `settings.s3_endpoint_url` at
# import time.
from moto.server import ThreadedMotoServer  # noqa: E402

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

from api.core.config import settings  # noqa: E402
from api.db.session import engine  # noqa: E402
from api.db.session import get_db_session, get_session_factory  # noqa: E402
from api.main import app  # noqa: E402

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
    yield
    command.downgrade(config, "base")


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
