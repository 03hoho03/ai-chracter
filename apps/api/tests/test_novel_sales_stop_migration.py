"""판매 중단 칸 마이그레이션(`e9ad8ed93e90`)의 옛 이미지 호환·왕복 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 옛 이미지의 쓰기는 두 칸을 모르는 원시 SQL 로 흉내 낸다.
`alembic check` 는 `server_default` 를 비교하지 않으므로, 옛 INSERT 가 두 칸을 채우는지는 이 파일이 유일한 신호다.
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

from factories import _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("e9ad8ed93e90")


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _user_id(session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    session.add(user)
    await session.flush()
    return user.id


async def test_old_image_writes_leave_the_novel_on_sale_and_the_buyers_unkept(db_session: AsyncSession) -> None:
    """두 칸을 모르는 옛 이미지의 INSERT 는 공개 행을 판매 중(NULL)으로, 작품을 표식 없음(false)으로 채운다. 표식이 선 작품을
    옛 이미지가 해제(정상으로)해도 거부되지 않는다 — 표식에 제약이 없다. 깨지는 시나리오: 배포 겹침 동안 옛 이미지의 첫 공개·
    작품 만들기가 NOT NULL 위반 500 이 되거나, 공개하자마자 판매 중단으로 보이거나, 옛 이미지의 원작 해제가 500 이 된다."""
    publisher = await _user_id(db_session)
    novel = await _make_public_novel(db_session, publisher, batches=(1,))
    connection = await db_session.connection()
    await connection.execute(sa.text("DELETE FROM novel_chapter_publications WHERE novel_id = :id"), {"id": novel.novel_id})
    await connection.execute(sa.text("DELETE FROM novel_publications WHERE novel_id = :id"), {"id": novel.novel_id})

    await connection.execute(
        sa.text("INSERT INTO novel_publications (novel_id, visibility) VALUES (:id, 'public')"), {"id": novel.novel_id}
    )
    content_id = uuid.uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO contents (id, creator_user_id, type, hashtags, visibility, moderation_status)"
            " VALUES (:id, :creator, 'CHARACTER', '{}', 'PUBLIC', 'NORMAL')"
        ),
        {"id": content_id, "creator": publisher},
    )
    stopped_at = (
        await connection.execute(
            sa.text("SELECT sales_stopped_at FROM novel_publications WHERE novel_id = :id"), {"id": novel.novel_id}
        )
    ).scalar_one()
    kept = (
        await connection.execute(sa.text("SELECT novel_buyers_kept FROM contents WHERE id = :id"), {"id": content_id})
    ).scalar_one()
    await connection.execute(
        sa.text("UPDATE contents SET moderation_status = 'RESTRICTED', novel_buyers_kept = true WHERE id = :id"),
        {"id": content_id},
    )
    await connection.execute(sa.text("UPDATE contents SET moderation_status = 'NORMAL' WHERE id = :id"), {"id": content_id})

    assert (stopped_at, kept) == (None, False)


async def test_downgrade_drops_both_columns_and_upgrade_brings_them_back_empty(ddl_engine: AsyncEngine) -> None:
    """리비전을 내리면 두 칸이 사라지고, 다시 올리면 판매 중(NULL)·표식 없음(false)으로 돌아온다. 깨지는 시나리오: downgrade 가
    칸을 남겨 옛 스키마와 어긋나거나, 다시 올린 뒤 기존 행이 판매 중단·표식 참으로 보인다."""

    async def columns(connection: AsyncConnection) -> set[str]:
        rows = await connection.execute(
            sa.text(
                "SELECT table_name || '.' || column_name FROM information_schema.columns"
                " WHERE (table_name, column_name) IN"
                " (('novel_publications', 'sales_stopped_at'), ('contents', 'novel_buyers_kept'))"
            )
        )
        return set(rows.scalars().all())

    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            novel = await _make_public_novel(session, await _user_id(session), batches=(1,))
            await session.flush()

            await _run(connection, _M.downgrade)
            after_down = await columns(connection)
            await _run(connection, _M.upgrade)
            after_up = await columns(connection)
            values = (
                await connection.execute(
                    sa.text(
                        "SELECT np.sales_stopped_at, c.novel_buyers_kept FROM novel_publications np"
                        " JOIN novels n ON n.id = np.novel_id JOIN contents c ON c.id = n.content_id"
                        " WHERE np.novel_id = :id"
                    ),
                    {"id": novel.novel_id},
                )
            ).one()
        finally:
            await transaction.rollback()

    assert after_down == set()
    assert after_up == {"novel_publications.sales_stopped_at", "contents.novel_buyers_kept"}
    assert tuple(values) == (None, False)
