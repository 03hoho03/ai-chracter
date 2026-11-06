"""마이그레이션 실행 환경.

DB 주소는 호출한 쪽이 `config.attributes["database_url"]` 로 주거나(테스트), 없으면 `LAB_DATABASE_URL` 하나만 읽는다 — Access
설정 없이 돈다. 주소는 ini 옵션(`sqlalchemy.url`)으로 넘기지 않고 엔진에 바로 준다. ini 값은 ConfigParser 보간을 거쳐, 비밀번호에
`%` 가 있으면 보간 오류 글에 값 전체가 실린다.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from chat_lab_service.db import VERSION_TABLE
from chat_lab_service.models import metadata
from chat_lab_service.settings import DatabaseSettings

config = context.config

if config.config_file_name is not None:
    # 같은 프로세스에서 이미 만든 로거(앱·테스트)를 끄지 않는다 — 기본값은 끈다.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    given = config.attributes.get("database_url")
    if isinstance(given, str):
        return given
    return DatabaseSettings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """`--sql` 로 DDL 만 찍는다."""
    context.configure(
        url=_database_url(),
        target_metadata=metadata,
        version_table=VERSION_TABLE,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, version_table=VERSION_TABLE)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
