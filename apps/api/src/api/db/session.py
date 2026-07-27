from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.core.config import settings

engine = create_async_engine(settings.database_url)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """FastAPI dependency for code that must open its own DB session outside a
    request's lifetime (e.g. asyncio background tasks scheduled via
    `api.images.jobs.enqueue_generation`) — the request's `Depends(get_db_session)`
    session is closed once the response is built, before a scheduled background
    task actually runs. Overridden in tests to bind to the test's own
    rolled-back connection (see `db_client` in conftest.py)."""
    return async_session_factory
