"""화 가격 칸 마이그레이션(`3b4b814583dc`)의 CHECK·백필·옛 코드 쓰기·왕복 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 백필 함수는 테스트마다 롤백되는 `db_session` 커넥션에
직접 부르고, downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다. `alembic check` 는
CHECK 제약과 `server_default` 를 비교하지 않으므로 이 파일이 그 둘의 유일한 신호다."""

import importlib.util
import uuid
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import NovelChapterPublication
from api.db.models.novel import NovelPublication
from factories import _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("3b4b814583dc")


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


async def _prices(db_session: AsyncSession, novel_id: uuid.UUID) -> list[int]:
    rows = await db_session.scalars(
        sa.select(NovelChapterPublication.price)
        .where(NovelChapterPublication.novel_id == novel_id)
        .order_by(NovelChapterPublication.ordinal)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


# ── CHECK ───────────────────────────────────────────────────────────────────
async def test_a_chapter_price_is_never_negative_but_zero_is_free(db_session: AsyncSession) -> None:
    """가격은 0(무료) 이상이다. 경계: -1 은 거부, 0 은 통과. 깨지는 시나리오: 음수 가격이 저장돼 구매가 클로버를 더해 주거나
    무료 판정(0)을 빠져나간다."""
    novel = await _make_public_novel(db_session, await _user_id(db_session), batches=(6,))
    sixth = NovelChapterPublication.chapter_id == novel.chapter_ids[5]

    await db_session.execute(sa.update(NovelChapterPublication).where(sixth).values(price=0))
    with pytest.raises(IntegrityError, match="ck_novel_chapter_publications_price_nonnegative"):
        async with db_session.begin_nested():
            await db_session.execute(sa.update(NovelChapterPublication).where(sixth).values(price=-1))


# ── 백필 ────────────────────────────────────────────────────────────────────
async def test_backfill_frees_the_front_chapters_of_every_publication_and_a_rerun_changes_nothing(
    db_session: AsyncSession,
) -> None:
    """칸을 더한 직후처럼 모든 행이 30 인 상태에서 백필하면 앞 5화만 0 이 된다 — 공개 중·거둠·승인 대기 행 모두. 6화 이후의
    값(유료 30, 무료로 공개한 0)은 건드리지 않고, 다시 돌리면 바꾸는 행이 없다. 깨지는 시나리오: 백필이 거둔·대기 행을
    빠뜨려 그 소설이 다시 열릴 때 칸이 틀리거나, 6화 이후까지 0 으로 만들어 유료 화가 되돌릴 수 없는 무료가 된다."""
    publisher = await _user_id(db_session)
    public = await _make_public_novel(db_session, publisher, batches=(7,))
    withdrawn = await _make_public_novel(db_session, publisher, batches=(6,))
    pending = await _make_public_novel(db_session, publisher, batches=(2,))
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == withdrawn.novel_id).values(visibility="withdrawn")
    )
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == pending.novel_id)
        .values(visibility="withdrawn", review_status="pending")
    )
    novel_ids = [public.novel_id, withdrawn.novel_id, pending.novel_id]
    await db_session.execute(
        sa.update(NovelChapterPublication).where(NovelChapterPublication.novel_id.in_(novel_ids)).values(price=30)
    )
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == public.chapter_ids[6])
        .values(price=0)
    )
    connection = await db_session.connection()

    assert await connection.run_sync(_M.backfill_free_chapter_price) == 5 + 5 + 2
    assert await _prices(db_session, public.novel_id) == [0, 0, 0, 0, 0, 30, 0]
    assert await _prices(db_session, withdrawn.novel_id) == [0, 0, 0, 0, 0, 30]
    assert await _prices(db_session, pending.novel_id) == [0, 0]
    assert await connection.run_sync(_M.backfill_free_chapter_price) == 0


# ── 옛 코드 쓰기 ────────────────────────────────────────────────────────────
async def test_old_code_inserts_without_the_price_get_the_paid_default_and_republish_keeps_it(
    db_session: AsyncSession,
) -> None:
    """가격 칸을 모르는 옛 코드 꼴의 화 공개본 INSERT(원시 SQL)는 기본값 30 을 받고 무료 시각은 비어 있다. 옛 코드의 다시 공개
    UPDATE 는 칸을 건드리지 않는다. 깨지는 시나리오: 기본값이 없어 옛 이미지의 공개가 500 이거나, 기본값이 0 이라 겹침 동안
    옛 이미지가 공개한 6화 이후가 되돌릴 수 없는 무료로 저장된다."""
    novel = await _make_public_novel(db_session, await _user_id(db_session), batches=(7,))
    seventh = novel.chapter_ids[6]
    revision_id = await db_session.scalar(
        sa.select(NovelChapterPublication.revision_id).where(NovelChapterPublication.chapter_id == seventh)
    )
    await db_session.execute(sa.delete(NovelChapterPublication).where(NovelChapterPublication.chapter_id == seventh))
    connection = await db_session.connection()
    await connection.execute(
        sa.text(
            "INSERT INTO novel_chapter_publications (chapter_id, novel_id, ordinal, revision_id, title)"
            " VALUES (:chapter_id, :novel_id, 7, :revision_id, NULL)"
        ),
        {"chapter_id": seventh, "novel_id": novel.novel_id, "revision_id": revision_id},
    )
    await connection.execute(
        sa.text("UPDATE novel_chapter_publications SET price = 0 WHERE chapter_id = :chapter_id"),
        {"chapter_id": novel.chapter_ids[5]},
    )
    await connection.execute(
        sa.text(
            "UPDATE novel_chapter_publications SET title = '다시 공개', edition = edition + 1, published_at = now()"
            " WHERE novel_id = :novel_id"
        ),
        {"novel_id": novel.novel_id},
    )

    rows = (
        await db_session.execute(
            sa.select(NovelChapterPublication.ordinal, NovelChapterPublication.price, NovelChapterPublication.price_changed_at)
            .where(NovelChapterPublication.ordinal >= 6, NovelChapterPublication.novel_id == novel.novel_id)
            .order_by(NovelChapterPublication.ordinal)
            .execution_options(populate_existing=True)
        )
    ).tuples()
    assert list(rows) == [(6, 0, None), (7, 30, None)]


# ── 왕복 ────────────────────────────────────────────────────────────────────
async def _scalar(connection: AsyncConnection, sql: str, **params: object) -> Any:
    return (await connection.execute(sa.text(sql), params)).scalar_one()


async def test_downgrade_drops_the_price_and_upgrade_restores_the_rule(ddl_engine: AsyncEngine) -> None:
    """리비전을 내리면 두 칸과 CHECK 가 사라지고, 다시 올리면 기존 행이 지금 규칙(앞 5화 0, 나머지 30)으로 채워지며 CHECK 가
    돌아온다. 깨지는 시나리오: downgrade 가 칸을 남겨 옛 스키마와 어긋나거나, 다시 올린 뒤 앞 화가 30 으로 남아 칸만 보는
    읽기가 무료 화를 잠근다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            novel = await _make_public_novel(session, await _user_id(session), batches=(7,))
            await session.flush()

            await _run(connection, _M.downgrade)
            columns_after_down = await _scalar(
                connection,
                "SELECT count(*) FROM information_schema.columns WHERE table_name = 'novel_chapter_publications'"
                " AND column_name IN ('price', 'price_changed_at')",
            )
            await _run(connection, _M.upgrade)
            prices = (
                await connection.execute(
                    sa.text(
                        "SELECT price FROM novel_chapter_publications WHERE novel_id = :novel_id ORDER BY ordinal"
                    ),
                    {"novel_id": novel.novel_id},
                )
            ).scalars().all()
            savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError, match="ck_novel_chapter_publications_price_nonnegative"):
                await connection.execute(
                    sa.text("UPDATE novel_chapter_publications SET price = -1 WHERE novel_id = :novel_id"),
                    {"novel_id": novel.novel_id},
                )
            await savepoint.rollback()
        finally:
            await transaction.rollback()

    assert columns_after_down == 0
    assert list(prices) == [0, 0, 0, 0, 0, 30, 30]
