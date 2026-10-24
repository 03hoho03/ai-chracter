"""방의 잊기 세대 칸(`chat_rooms.memory_forget_generation`)의 옛 이미지 호환과 왕복.

downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다."""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import ChatRoom
from factories import _get_genre, _make_published_character, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load_migration() -> ModuleType:
    (path,) = _VERSIONS_DIR.glob("*_chat_room_memory_forget_generation.py")
    spec = importlib.util.spec_from_file_location("_migration_chat_room_memory_forget_generation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_migration()


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _room_values(session: AsyncSession) -> dict[str, object]:
    """방 하나를 만들 칸 — 잊기 세대 칸은 넣지 않는다(그 칸을 모르는 옛 이미지의 INSERT 와 같다)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    genre = await _get_genre(session)
    content = await _make_published_character(session, creator_user_id=user.id, genre_id=genre.id)
    return {"user_id": user.id, "content_id": content.id, "content_version_id": content.current_published_version_id}


async def test_an_insert_without_the_column_gets_zero_and_the_column_round_trips(ddl_engine: AsyncEngine) -> None:
    """칸을 모르는 옛 이미지의 방 INSERT 는 서버 기본값 0 을 받는다(배포 겹침 동안 500 없음). 내리면 칸이 사라지고 다시 올리면
    있던 방도 0 으로 돌아온다. 깨지는 시나리오: 기본값 없이 NOT NULL 로 더해 옛 이미지의 방 만들기가 전부 실패한다."""
    columns = sa.text(
        "SELECT count(*) FROM information_schema.columns"
        " WHERE table_name = 'chat_rooms' AND column_name = 'memory_forget_generation'"
    )
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            values = await _room_values(session)
            room_id = await connection.scalar(sa.insert(ChatRoom).values(**values).returning(ChatRoom.id))
            inserted = await connection.scalar(
                sa.text("SELECT memory_forget_generation FROM chat_rooms WHERE id = :id"), {"id": room_id}
            )
            await _run(connection, _M.downgrade)
            after_down = await connection.scalar(columns)
            await _run(connection, _M.upgrade)
            after_up = await connection.scalar(
                sa.text("SELECT memory_forget_generation FROM chat_rooms WHERE id = :id"), {"id": room_id}
            )
        finally:
            await transaction.rollback()

    assert (inserted, after_down, after_up) == (0, 0, 0)
