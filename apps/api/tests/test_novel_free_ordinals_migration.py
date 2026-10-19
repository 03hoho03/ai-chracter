"""무료 번호 표 마이그레이션(`2975c3a6fa6f`)의 복합 PK·CHECK·CASCADE·백필·왕복 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 백필 함수는 테스트마다 롤백되는 `db_session` 커넥션에
직접 부르고, downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다. `alembic check` 는
복합 PK 와 CHECK 제약을 비교하지 않으므로 이 파일이 그 둘의 유일한 신호다."""

import importlib.util
import uuid
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import Novel, NovelChapterPublication, NovelFreeOrdinal
from factories import _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("2975c3a6fa6f")


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _user_id(db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return user.id


async def _remembered(db_session: AsyncSession, novel_id: uuid.UUID) -> list[int]:
    rows = await db_session.scalars(
        sa.select(NovelFreeOrdinal.ordinal).where(NovelFreeOrdinal.novel_id == novel_id).order_by(NovelFreeOrdinal.ordinal)
    )
    return list(rows.all())


async def _set_prices(db_session: AsyncSession, chapter_ids: list[uuid.UUID], price: int) -> None:
    await db_session.execute(
        sa.update(NovelChapterPublication).where(NovelChapterPublication.chapter_id.in_(chapter_ids)).values(price=price)
    )


# ── 제약 ────────────────────────────────────────────────────────────────────
async def test_a_novel_remembers_each_ordinal_once(db_session: AsyncSession) -> None:
    """같은 소설의 같은 번호는 한 행이고, 다른 소설은 같은 번호를 따로 가진다. 깨지는 시나리오: 기록이 겹쳐 쌓여 상태 응답의
    번호가 중복되거나, PK 가 번호만이라 두 번째 소설의 기록이 거부된다."""
    publisher = await _user_id(db_session)
    first = await _make_public_novel(db_session, publisher, batches=(1,))
    second = await _make_public_novel(db_session, publisher, batches=(1,))
    db_session.add_all([NovelFreeOrdinal(novel_id=first.novel_id, ordinal=6), NovelFreeOrdinal(novel_id=second.novel_id, ordinal=6)])
    await db_session.flush()

    with pytest.raises(IntegrityError, match="novel_free_ordinals_pkey"):
        async with db_session.begin_nested():
            db_session.add(NovelFreeOrdinal(novel_id=first.novel_id, ordinal=6))
            await db_session.flush()


async def test_a_remembered_ordinal_is_a_chapter_number(db_session: AsyncSession) -> None:
    """번호는 1 이상이다. 경계: 0 은 거부, 1 은 통과. 깨지는 시나리오: 없는 화 번호가 기억돼 화면이 "무료 고정"을 그린다."""
    novel = await _make_public_novel(db_session, await _user_id(db_session), batches=(1,))
    db_session.add(NovelFreeOrdinal(novel_id=novel.novel_id, ordinal=1))
    await db_session.flush()

    with pytest.raises(IntegrityError, match="ck_novel_free_ordinals_ordinal_positive"):
        async with db_session.begin_nested():
            db_session.add(NovelFreeOrdinal(novel_id=novel.novel_id, ordinal=0))
            await db_session.flush()


async def test_deleting_the_novel_row_takes_its_remembered_ordinals_with_it(db_session: AsyncSession) -> None:
    """이 표를 모르는 옛 코드 꼴의 소설 DELETE(원시 SQL)가 FK 위반 없이 기억도 함께 지운다. 깨지는 시나리오: 배포 겹침 동안
    옛 이미지의 소설 삭제·숨긴 소설 파기가 500 이 된다."""
    novel = await _make_public_novel(db_session, await _user_id(db_session), batches=(1,))
    db_session.add(NovelFreeOrdinal(novel_id=novel.novel_id, ordinal=7))
    await db_session.flush()
    connection = await db_session.connection()

    await connection.execute(sa.text("DELETE FROM novel_chapter_publications WHERE novel_id = :id"), {"id": novel.novel_id})
    await connection.execute(sa.text("DELETE FROM novel_publications WHERE novel_id = :id"), {"id": novel.novel_id})
    await connection.execute(sa.text("DELETE FROM novel_chapter_revisions WHERE chapter_id = ANY(:ids)"), {"ids": novel.chapter_ids})
    await connection.execute(sa.text("DELETE FROM novel_chapters WHERE novel_id = :id"), {"id": novel.novel_id})
    await connection.execute(sa.text("DELETE FROM novel_batches WHERE novel_id = :id"), {"id": novel.novel_id})
    await connection.execute(sa.text("DELETE FROM novels WHERE id = :id"), {"id": novel.novel_id})

    assert await db_session.scalar(sa.select(sa.func.count()).select_from(Novel).where(Novel.id == novel.novel_id)) == 0
    assert await _remembered(db_session, novel.novel_id) == []


# ── 백필 ────────────────────────────────────────────────────────────────────
async def test_backfill_remembers_free_chapters_after_the_front_ones_and_a_rerun_adds_nothing(
    db_session: AsyncSession,
) -> None:
    """6화 이후 무료(0)인 화 공개본의 번호만 남긴다 — 앞 화(0)와 유료(30)는 남기지 않는다. 다시 돌리면 더하는 행이 없다.
    깨지는 시나리오: 앞 화까지 남겨 상태 응답이 상수로 지키는 번호를 "무료 고정"으로 중복해 알리거나, 유료 화를 남겨 그
    번호가 다시 만들면 무료가 된다."""
    publisher = await _user_id(db_session)
    novel = await _make_public_novel(db_session, publisher, batches=(8,))
    await _set_prices(db_session, novel.chapter_ids[:5], 0)
    await _set_prices(db_session, [novel.chapter_ids[5], novel.chapter_ids[7]], 0)
    connection = await db_session.connection()

    assert await connection.run_sync(_M.backfill_free_ordinals) == 2
    assert await _remembered(db_session, novel.novel_id) == [6, 8]
    assert await connection.run_sync(_M.backfill_free_ordinals) == 0


# ── 왕복 ────────────────────────────────────────────────────────────────────
async def test_downgrade_drops_the_table_and_upgrade_backfills_it(ddl_engine: AsyncEngine) -> None:
    """리비전을 내리면 표가 사라지고, 다시 올리면 무료로 공개된 6화 이후 번호가 백필되며 PK 가 돌아온다. 깨지는 시나리오:
    downgrade 가 표를 남겨 옛 스키마와 어긋나거나, upgrade 가 기존 무료 화를 기억하지 못해 지우고 다시 만들면 유료로 낼 수
    있다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            novel = await _make_public_novel(session, await _user_id(session), batches=(7,))
            await _set_prices(session, [novel.chapter_ids[6]], 0)
            await session.flush()

            await _run(connection, _M.downgrade)
            tables_after_down = (
                await connection.execute(sa.text("SELECT to_regclass('novel_free_ordinals') IS NOT NULL"))
            ).scalar_one()
            await _run(connection, _M.upgrade)
            remembered = (
                await connection.execute(
                    sa.text("SELECT ordinal FROM novel_free_ordinals WHERE novel_id = :id ORDER BY ordinal"),
                    {"id": novel.novel_id},
                )
            ).scalars().all()
            savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError, match="novel_free_ordinals_pkey"):
                await connection.execute(
                    sa.text("INSERT INTO novel_free_ordinals (novel_id, ordinal) VALUES (:id, 7)"), {"id": novel.novel_id}
                )
            await savepoint.rollback()
        finally:
            await transaction.rollback()

    assert tables_after_down is False
    assert list(remembered) == [7]
