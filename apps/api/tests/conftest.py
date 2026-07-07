import atexit
import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import boto3
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

# boto3 resolves and caches credentials once, at client-construction time (see
# api/core/s3.py's module-level `s3_client`) — these must be set before that
# module is first imported (via `from api.main import app` below), or presigned
# URL signing fails with NoCredentialsError even under moto in individual tests.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

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
os.environ.setdefault("S3_ENDPOINT_URL", f"http://{_moto_host}:{_moto_port}")

from api.core.config import settings  # noqa: E402
from api.db.session import engine  # noqa: E402
from api.db.session import get_db_session  # noqa: E402
from api.main import app  # noqa: E402

APPS_API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema() -> Generator[None, None, None]:
    """Apply every migration before the test session, then fully unwind them after.

    This is the executable proof (not just a manual check) that `alembic upgrade
    head` / `downgrade base` both work end-to-end against a real Postgres.
    """
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
    """

    async def _get_db_session_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _get_db_session_override
    api_client.cookies.clear()
    try:
        yield api_client
    finally:
        del app.dependency_overrides[get_db_session]
