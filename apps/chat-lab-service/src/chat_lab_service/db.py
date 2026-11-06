"""DB 엔진과 기동 점검, DB 오류를 503 으로 바꾸는 자리."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from chat_lab_service.errors import ServiceHTTPError
from chat_lab_service.settings import Settings

logger = logging.getLogger(__name__)

# 표 이름만 보고도 어느 앱의 마이그레이션 판인지 알 수 있게 alembic 기본 이름(`alembic_version`)을 쓰지 않는다.
VERSION_TABLE = "chat_lab_alembic_version"
# 이 코드가 기대하는 마이그레이션 판. 마이그레이션을 더하면 함께 올린다 — 어긋나면 서비스가 뜨지 않는다.
SCHEMA_REVISION = "5c1e0a7d9b24"

# 서비스 풀 3(풀 2 + 넘침 1)은 서비스 README.md 「2. DB·역할 만들기(VM, 사람)」의 DB 역할 접속 상한 5 에서
# 마이그레이션 1·여유 1 을 뺀 몫이다.
POOL_SIZE = 2
POOL_OVERFLOW = 1

# DB 를 쓸 수 없다(503)로 읽는 예외 — SQLAlchemy 오류(풀 대기 시간 초과 포함), 접속 거부·끊김, 드라이버가 접속 단계에서
# SQLAlchemy 가 감싸지 않은 채 내는 오류.
DB_ERRORS: tuple[type[Exception], ...] = (SQLAlchemyError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)


class StartupCheckError(RuntimeError):
    """기동 점검 실패 — 마이그레이션을 빠뜨린 배포가 요청마다 500 이 아니라 기동 실패로 드러나게 한다."""


def make_engine(settings: Settings) -> AsyncEngine:
    """접속은 첫 사용 때 한다 — 스키마만 떨굴 때는 DB 에 닿지 않는다."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=POOL_SIZE,
        max_overflow=POOL_OVERFLOW,
        # DB 가 다시 뜬 뒤 첫 요청이 풀에 남은 끊긴 접속을 꺼내 503 을 받지 않게 꺼내기 전에 확인한다.
        pool_pre_ping=True,
    )


async def check_schema(engine: AsyncEngine) -> None:
    try:
        async with engine.connect() as conn:
            found = list((await conn.execute(text(f"SELECT version_num FROM {VERSION_TABLE}"))).scalars())
    except DB_ERRORS as error:
        # 오류 글에는 SQL·접속 대상이 실린다. 접속을 시도했는지는 예외 이름으로 알 수 있다.
        raise StartupCheckError(f"DB 의 마이그레이션 판을 읽지 못했다: {type(error).__name__}") from None
    if found != [SCHEMA_REVISION]:
        raise StartupCheckError(
            f"DB 의 마이그레이션 판 {found} 이 코드가 기대하는 {SCHEMA_REVISION} 과 다르다 — "
            "`alembic upgrade head` 를 먼저 돌린다"
        )


@asynccontextmanager
async def db_errors_as_503() -> AsyncIterator[None]:
    try:
        yield
    except DB_ERRORS as error:
        # SQLAlchemy 오류 글에는 SQL 과 바인드 값이, 드라이버 접속 오류 글에는 접속 대상이 실린다.
        logger.error("DB 오류: %s", type(error).__name__)
        raise ServiceHTTPError(503, "dbUnavailable", f"DB 를 쓰지 못했다: {type(error).__name__}") from None
