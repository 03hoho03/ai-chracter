from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from api.db.session import engine

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
