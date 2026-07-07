from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from api.db.session import engine
from api.main import app

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


@pytest.fixture(scope="session")
def api_client() -> Generator[TestClient, None, None]:
    """Session-scoped so the ASGI lifespan (and any pooled async clients it creates,
    e.g. Redis) stays bound to one portal/event loop for the whole test session —
    same reasoning as the session-scoped asyncio loop above, applied to TestClient's
    own background portal.
    """
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db_engine() -> AsyncEngine:
    return engine


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Each test runs inside its own transaction that is rolled back afterward."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
