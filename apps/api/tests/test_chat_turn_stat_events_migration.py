"""턴 기록의 스탯 판정 이벤트 칸(`chat_turns.stat_events`)의 옛 이미지 호환과 왕복.

downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다."""

import importlib.util
import uuid
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
    (path,) = _VERSIONS_DIR.glob("*_chat_turn_stat_events.py")
    spec = importlib.util.spec_from_file_location("_migration_chat_turn_stat_events", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_migration()

# 이 칸을 모르는 옛 이미지의 턴 기록 INSERT 와 같은 칸 목록 — 이벤트 칸은 싣지 않는다.
_OLD_IMAGE_INSERT = sa.text(
    "INSERT INTO chat_turns (id, chat_room_id, assistant_message_id, kind, turn_number, chat_model, charge_source,"
    " clover_amount, stat_changes) VALUES (:id, :room_id, :message_id, 'send', 1, 'gemini', 'free', 0,"
    " '{}'::jsonb)"
)


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _room_id(connection: AsyncConnection) -> uuid.UUID:
    session = AsyncSession(bind=connection)
    user = _make_user()
    session.add(user)
    await session.flush()
    genre = await _get_genre(session)
    content = await _make_published_character(session, creator_user_id=user.id, genre_id=genre.id)
    room_id = await connection.scalar(
        sa.insert(ChatRoom)
        .values(user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id)
        .returning(ChatRoom.id)
    )
    assert room_id is not None
    return room_id


async def test_an_old_image_turn_insert_gets_an_empty_list_and_the_column_round_trips(ddl_engine: AsyncEngine) -> None:
    """칸을 모르는 옛 이미지의 턴 기록 INSERT 는 서버 기본값 `[]` 을 받는다(배포 겹침 동안 턴이 500 으로 끝나지 않음). 내리면
    칸이 사라지고 다시 올리면 있던 행도 `[]` 로 돌아온다. 깨지는 시나리오: 기본값 없이 NOT NULL 로 더해 옛 이미지의 모든 턴
    기록 쓰기가 실패하고, 그 커밋에 함께 실린 응답 저장까지 되감긴다."""
    columns = sa.text(
        "SELECT count(*) FROM information_schema.columns"
        " WHERE table_name = 'chat_turns' AND column_name = 'stat_events'"
    )
    events = sa.text("SELECT stat_events FROM chat_turns WHERE id = :id")
    turn_id = uuid.uuid4()
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            room_id = await _room_id(connection)
            await connection.execute(
                _OLD_IMAGE_INSERT, {"id": turn_id, "room_id": room_id, "message_id": uuid.uuid4()}
            )
            inserted = await connection.scalar(events, {"id": turn_id})
            await _run(connection, _M.downgrade)
            after_down = await connection.scalar(columns)
            await _run(connection, _M.upgrade)
            after_up = await connection.scalar(events, {"id": turn_id})
        finally:
            await transaction.rollback()

    assert (inserted, after_down, after_up) == ([], 0, [])
