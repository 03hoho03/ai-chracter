import asyncio
from logging.config import fileConfig
from typing import Any, Literal

from sqlalchemy import pool
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from alembic.autogenerate.api import AutogenContext

from api.core.config import settings
from api.db import models
from api.db.base import Base
from api.db.types import HalfVec

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# database URL comes from api.core.config.settings (env vars / .env), not alembic.ini,
# so there's a single source of truth shared with the app's own async engine.
config.set_main_option("sqlalchemy.url", settings.database_url)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# 확장 타입은 SQLAlchemy 의 Postgres 방언이 모른다. 반영(reflection)이 `halfvec` 칸을 알아보게 이름을 등록해 둔다 — 없으면
# `alembic check` 가 그 칸을 타입 미상으로 보고 타입 비교를 건너뛴다(모델의 칸 타입이 바뀌어도 초록).
ischema_names["halfvec"] = HalfVec


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    """autogenerate 가 `HalfVec` 칸을 import 없이 `api.db.types.HalfVec()` 로 적어 그 파일이 로드되지 않는 것을 막는다.
    import 를 함께 적어 두지만, 리비전 파일은 `api.*` 를 import 하지 않는 관례라 손으로 고칠 때 파일 안 타입으로 바꾼다."""
    if type_ == "type" and isinstance(obj, HalfVec):
        autogen_context.imports.add("from api.db.types import HalfVec")
        return "HalfVec()"
    return False


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_item=render_item)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
