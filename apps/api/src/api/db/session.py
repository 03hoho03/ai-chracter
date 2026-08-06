from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.core.config import settings

# pool_pre_ping: 풀에 남아 있던 커넥션이 죽어 있으면(서버 재기동, 유휴 타임아웃, SSE 스트림이
# 중간에 취소되며 망가진 채 반환된 asyncpg 커넥션) 체크아웃 시점에 한 번 찔러보고 조용히
# 새 커넥션으로 교체한다 — 없으면 그 커넥션을 집어간 다음 요청이 InterfaceError로 500이 난다.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
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
