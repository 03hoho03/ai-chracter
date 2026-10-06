"""소설 묶음 구조 마이그레이션 두 리비전(`4a4af1ac1df8` 묶음·화·새 테이블, `3af53088351c` 작업 행·환불 CHECK)의 이관
함수와 downgrade 거부.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 이관 함수는 테스트마다 롤백되는 `db_session`
커넥션에 직접 부르고, 리비전의 upgrade·downgrade 를 실제로 돌려야 하는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션
안에서 돌린다(세션 스코프 스키마는 그대로 남는다)."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import Novel, NovelBatch, NovelChapter, NovelJob
from factories import _make_novel_tree, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_R1 = _load("4a4af1ac1df8")
_R2 = _load("3af53088351c")


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    """리비전의 upgrade·downgrade 를 이 커넥션에서 alembic `op` 가 쓰이도록 돌린다."""

    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _call(db_session: AsyncSession, fn: Callable[[Connection], Any]) -> Any:
    connection = await db_session.connection()
    return await connection.run_sync(fn)


async def _novel(db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    novel = Novel(user_id=user.id, content_id=uuid.uuid4(), content_type="story", content_title="원작")
    db_session.add(novel)
    await db_session.flush()
    return novel.id


def _segment(index: int) -> dict[str, Any]:
    at = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=index)
    return {
        "start_message_id": uuid.uuid4(),
        "start_message_created_at": at,
        "end_message_id": uuid.uuid4(),
        "end_message_created_at": at + timedelta(seconds=30),
        "assistant_message_count": index,
        "source_hash": f"{index:064d}",
    }


async def _old_chapter(db_session: AsyncSession, novel_id: uuid.UUID, ordinal: int) -> NovelChapter:
    """옛 코드가 넣는 모양의 화 — 묶음 칸을 모른다."""
    chapter = NovelChapter(novel_id=novel_id, ordinal=ordinal, **_segment(ordinal))
    db_session.add(chapter)
    await db_session.flush()
    return chapter


async def _chapter_batches(db_session: AsyncSession, novel_id: uuid.UUID) -> list[tuple[NovelChapter, NovelBatch]]:
    rows = await db_session.execute(
        sa.select(NovelChapter, NovelBatch)
        .join(NovelBatch, NovelBatch.id == NovelChapter.batch_id)
        .where(NovelChapter.novel_id == novel_id)
        .order_by(NovelChapter.ordinal)
        .execution_options(populate_existing=True)
    )
    return [(chapter, batch) for chapter, batch in rows.tuples()]


# ── 묶음 이관 ────────────────────────────────────────────────────────────────


async def test_backfill_gives_each_unbatched_chapter_its_own_batch(db_session: AsyncSession) -> None:
    novel_id = await _novel(db_session)
    chapters = [await _old_chapter(db_session, novel_id, ordinal) for ordinal in (1, 2, 3)]

    await _call(db_session, _R1._backfill_batches)

    pairs = await _chapter_batches(db_session, novel_id)
    assert [chapter.id for chapter, _ in pairs] == [chapter.id for chapter in chapters]
    assert len({batch.id for _, batch in pairs}) == 3
    for chapter, batch in pairs:
        assert batch.novel_id == novel_id
        assert batch.ordinal == chapter.ordinal
        assert batch.target_episode_count == 1
        assert chapter.episode_index == 0
        for column in _segment(0):
            assert getattr(batch, column) == getattr(chapter, column), column


async def test_backfill_twice_changes_nothing_the_second_time(db_session: AsyncSession) -> None:
    novel_id = await _novel(db_session)
    for ordinal in (1, 2):
        await _old_chapter(db_session, novel_id, ordinal)
    await _call(db_session, _R1._backfill_batches)
    first = [(chapter.id, batch.id) for chapter, batch in await _chapter_batches(db_session, novel_id)]

    filled = await _call(db_session, _R1._backfill_batches)

    assert filled == 0
    assert [(chapter.id, batch.id) for chapter, batch in await _chapter_batches(db_session, novel_id)] == first


async def test_backfill_leaves_batched_chapters_alone_and_numbers_new_batches_after_them(
    db_session: AsyncSession,
) -> None:
    """옛 이미지로 되돌린 동안 생긴 화를 나중에 채우는 경우 — 이미 화 둘짜리 묶음이 있는 소설에 옛 코드가 화 3을 넣었다.
    기존 묶음은 그대로이고, 새 묶음 번호는 화 번호(3)가 아니라 기존 묶음 번호 뒤(2)다."""
    tree_user = _make_user()
    db_session.add(tree_user)
    await db_session.flush()
    tree = await _make_novel_tree(db_session, tree_user.id)
    novel_id = tree.novel.id
    second = NovelChapter(
        novel_id=novel_id, ordinal=2, batch_id=tree.batch.id, episode_index=1, **_segment(1)
    )
    db_session.add(second)
    await db_session.flush()
    third = await _old_chapter(db_session, novel_id, 3)

    await _call(db_session, _R1._backfill_batches)

    pairs = await _chapter_batches(db_session, novel_id)
    assert [(chapter.id, batch.id, batch.ordinal) for chapter, batch in pairs] == [
        (tree.chapter.id, tree.batch.id, 1),
        (second.id, tree.batch.id, 1),
        (third.id, pairs[2][1].id, 2),
    ]
    assert pairs[2][1].id != tree.batch.id


async def test_backfill_drops_batches_emptied_by_old_chapter_delete(db_session: AsyncSession) -> None:
    """옛 이미지 동안: 마지막 장(화 2, 묶음 2) 삭제는 개정 → 장만 지워 빈 묶음 2가 남고, 옛 코드가 같은 번호로 장 2를
    다시 만든다. 다시 채우면 빈 묶음은 사라지고 새 장은 묶음 2를 받는다 — 지우지 않으면 묶음 3이 되고 지운 구간을 든
    빈 묶음 2가 영영 남는다."""
    novel_id = await _novel(db_session)
    for ordinal in (1, 2):
        await _old_chapter(db_session, novel_id, ordinal)
    await _call(db_session, _R1._backfill_batches)
    (_, first_batch), (removed, emptied_batch) = await _chapter_batches(db_session, novel_id)
    await db_session.execute(sa.delete(NovelChapter).where(NovelChapter.id == removed.id))
    recreated = await _old_chapter(db_session, novel_id, 2)

    await _call(db_session, _R1._backfill_batches)

    pairs = await _chapter_batches(db_session, novel_id)
    assert [(chapter.id, batch.ordinal) for chapter, batch in pairs] == [(pairs[0][0].id, 1), (recreated.id, 2)]
    assert pairs[0][1].id == first_batch.id
    batch_ids = (
        await db_session.scalars(sa.select(NovelBatch.id).where(NovelBatch.novel_id == novel_id))
    ).all()
    assert sorted(batch_ids) == sorted([first_batch.id, pairs[1][1].id])
    assert emptied_batch.id not in batch_ids


async def _batch_shape(db_session: AsyncSession, novel_ids: list[uuid.UUID]) -> list[list[tuple[Any, ...]]]:
    """소설마다 묶음 번호 순으로 (번호, 화 수 목표, 구간 칸, 그 묶음의 (화 번호, 묶음 안 순번)들). 묶음 id 는 무작위라
    빼고, 묶음 없는 화는 번호 None 의 묶음 하나로 모은다."""
    shapes: list[list[tuple[Any, ...]]] = []
    for novel_id in novel_ids:
        batches = (
            await db_session.scalars(
                sa.select(NovelBatch)
                .where(NovelBatch.novel_id == novel_id)
                .order_by(NovelBatch.ordinal)
                .execution_options(populate_existing=True)
            )
        ).all()
        chapters = (
            await db_session.scalars(
                sa.select(NovelChapter)
                .where(NovelChapter.novel_id == novel_id)
                .order_by(NovelChapter.ordinal)
                .execution_options(populate_existing=True)
            )
        ).all()
        shape: list[tuple[Any, ...]] = [
            (
                batch.ordinal,
                batch.target_episode_count,
                *(getattr(batch, column) for column in _segment(0)),
                [(c.ordinal, c.episode_index) for c in chapters if c.batch_id == batch.id],
            )
            for batch in batches
        ]
        shape.append((None, [c.ordinal for c in chapters if c.batch_id is None]))
        shapes.append(shape)
    return shapes


async def test_runtime_batch_fill_matches_the_migration_backfill(db_session: AsyncSession) -> None:
    """새 판 코드의 보정(`ensure_batches`)은 이관 함수와 같은 결과를 내야 한다 — 다르면 이미지 롤백 뒤 다시 올렸을 때
    마이그레이션으로 이관된 소설과 보정으로 채워진 소설의 묶음 모양이 갈린다. 처음 이관할 소설, 이미 여러 화 묶음이 있고
    옛 코드가 화를 더한 소설, 옛 코드의 삭제가 빈 묶음을 남긴 소설, 빈 묶음만 있는 소설을 한 상태에 두고 둘을 따로 돌린다."""
    from api.novelize.batches import ensure_batches

    # 이관을 한 번 거친 뒤 옛 코드가 마지막 장을 지우고 같은 번호로 다시 만든 소설 — 이관을 먼저 돌려야 해서 맨 앞에 둔다.
    emptied = await _novel(db_session)
    for ordinal in (1, 2):
        await _old_chapter(db_session, emptied, ordinal)
    await _call(db_session, _R1._backfill_batches)
    await db_session.execute(sa.delete(NovelChapter).where(NovelChapter.novel_id == emptied, NovelChapter.ordinal == 2))
    await _old_chapter(db_session, emptied, 2)

    fresh = await _novel(db_session)
    for ordinal in (1, 2, 3):
        await _old_chapter(db_session, fresh, ordinal)

    owner = _make_user()
    db_session.add(owner)
    await db_session.flush()
    tree = await _make_novel_tree(db_session, owner.id)
    db_session.add(
        NovelChapter(novel_id=tree.novel.id, ordinal=2, batch_id=tree.batch.id, episode_index=1, **_segment(1))
    )
    await db_session.flush()
    await _old_chapter(db_session, tree.novel.id, 3)

    only_empty = await _novel(db_session)
    db_session.add(NovelBatch(novel_id=only_empty, ordinal=1, target_episode_count=1, **_segment(9)))
    await db_session.flush()

    novel_ids = [fresh, tree.novel.id, emptied, only_empty]
    before = await _batch_shape(db_session, novel_ids)
    savepoint = await db_session.begin_nested()
    await _call(db_session, _R1._backfill_batches)
    by_migration = await _batch_shape(db_session, novel_ids)
    await savepoint.rollback()
    assert await _batch_shape(db_session, novel_ids) == before

    changed = [await ensure_batches(db_session, novel_id) for novel_id in novel_ids]

    assert await _batch_shape(db_session, novel_ids) == by_migration
    assert changed == [True, True, True, True]
    assert [await ensure_batches(db_session, novel_id) for novel_id in novel_ids] == [False] * 4


# ── R1 downgrade 거부 ────────────────────────────────────────────────────────


async def test_single_episode_batches_do_not_block_the_downgrade(db_session: AsyncSession) -> None:
    novel_id = await _novel(db_session)
    for ordinal in (1, 2):
        await _old_chapter(db_session, novel_id, ordinal)
    await _call(db_session, _R1._backfill_batches)

    await _call(db_session, _R1._assert_no_multi_episode_batch)


async def test_multi_episode_batch_blocks_the_downgrade_before_any_change(ddl_engine: AsyncEngine) -> None:
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            user = _make_user()
            session.add(user)
            await session.flush()
            tree = await _make_novel_tree(session, user.id)
            session.add(
                NovelChapter(
                    novel_id=tree.novel.id, ordinal=2, batch_id=tree.batch.id, episode_index=1, **_segment(1)
                )
            )
            await session.flush()

            with pytest.raises(RuntimeError, match="화가 둘 이상인 묶음이 1개"):
                await _run(connection, _R1.downgrade)
            still_there = await connection.scalar(sa.text("SELECT to_regclass('novel_batches') IS NOT NULL"))
        finally:
            await transaction.rollback()

    assert still_there


async def test_upgrade_after_downgrade_rebuilds_batches_from_old_chapters(ddl_engine: AsyncEngine) -> None:
    """두 리비전을 실제로 내린 뒤 옛 스키마에 화를 넣고 다시 올린다 — upgrade 가 이관까지 마친다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _run(connection, _R2.downgrade)
            await _run(connection, _R1.downgrade)
            session = AsyncSession(bind=connection)
            user = _make_user()
            session.add(user)
            await session.flush()
            novel_id = uuid.uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO novels (id, user_id, content_id, content_type, content_title)"
                    " VALUES (:id, :user_id, :content_id, 'story', '원작')"
                ),
                {"id": novel_id, "user_id": user.id, "content_id": uuid.uuid4()},
            )
            for ordinal in (1, 2):
                await connection.execute(
                    sa.text(
                        "INSERT INTO novel_chapters (id, novel_id, ordinal, start_message_id, start_message_created_at,"
                        " end_message_id, end_message_created_at, assistant_message_count, source_hash)"
                        " VALUES (:id, :novel_id, :ordinal, :start_message_id, :start_message_created_at,"
                        " :end_message_id, :end_message_created_at, :assistant_message_count, :source_hash)"
                    ),
                    {"id": uuid.uuid4(), "novel_id": novel_id, "ordinal": ordinal, **_segment(ordinal)},
                )

            await _run(connection, _R1.upgrade)
            await _run(connection, _R2.upgrade)
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT c.ordinal, b.ordinal, b.source_hash = c.source_hash FROM novel_chapters c"
                        " JOIN novel_batches b ON b.id = c.batch_id WHERE c.novel_id = :novel_id ORDER BY c.ordinal"
                    ),
                    {"novel_id": novel_id},
                )
            ).all()
        finally:
            await transaction.rollback()

    assert [tuple(row) for row in rows] == [(1, 1, True), (2, 2, True)]


# ── R2 환불 정리·백필·downgrade 거부 ──────────────────────────────────────────


async def test_refund_backfill_on_old_job_rows(ddl_engine: AsyncEngine) -> None:
    """옛 스키마의 작업 행으로 R2 upgrade 를 돌린다. 환불된 행은 금액이 차감액으로 채워지고, 차감 0 인데 환불 시각이
    찍힌 행은 시각이 비워져 새 CHECK 를 통과한다(비우지 않으면 upgrade 가 CHECK 위반으로 멈춘다)."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _run(connection, _R2.downgrade)
            session = AsyncSession(bind=connection)
            user = _make_user()
            session.add(user)
            await session.flush()
            novel_id = uuid.uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO novels (id, user_id, content_id, content_type, content_title)"
                    " VALUES (:id, :user_id, :content_id, 'story', '원작')"
                ),
                {"id": novel_id, "user_id": user.id, "content_id": uuid.uuid4()},
            )
            ids = {name: uuid.uuid4() for name in ("refunded", "zero_charge", "kept")}
            for name, status, charged, refunded in [
                ("refunded", "failed", 40, True),
                ("zero_charge", "failed", 0, True),
                ("kept", "succeeded", 40, False),
            ]:
                await connection.execute(
                    sa.text(
                        "INSERT INTO novel_jobs (id, novel_id, user_id, kind, status, charged_amount, refunded_at)"
                        " VALUES (:id, :novel_id, :user_id, 'chapter_generate', :status, :charged,"
                        " CASE WHEN :refunded THEN now() END)"
                    ),
                    {
                        "id": ids[name],
                        "novel_id": novel_id,
                        "user_id": user.id,
                        "status": status,
                        "charged": charged,
                        "refunded": refunded,
                    },
                )

            await _run(connection, _R2.upgrade)
            rows = {
                row[0]: (row[1] is not None, row[2])
                for row in await connection.execute(
                    sa.text("SELECT id, refunded_at, refunded_amount FROM novel_jobs WHERE novel_id = :novel_id"),
                    {"novel_id": novel_id},
                )
            }
        finally:
            await transaction.rollback()

    assert rows == {ids["refunded"]: (True, 40), ids["zero_charge"]: (False, None), ids["kept"]: (False, None)}


@pytest.mark.parametrize(
    ("overrides", "label"),
    [
        pytest.param(
            {"status": "succeeded", "charged_amount": 120, "refunded_amount": 40, "refunded_at": sa.func.now()},
            "성공 + 환불(부분 환불)",
            id="partial-refund",
        ),
        pytest.param({"kind": "chain_generate"}, "연쇄 부모(chain_generate)", id="chain-parent"),
        pytest.param(
            {"status": "failed", "failure_code": "malformed"},
            "실패 사유 malformed·episode_count_mismatch",
            id="malformed",
        ),
        pytest.param(
            {"status": "failed", "failure_code": "episode_count_mismatch"},
            "실패 사유 malformed·episode_count_mismatch",
            id="episode-count-mismatch",
        ),
        pytest.param({"parent_job_id": uuid.uuid4()}, "연쇄 자식(parent_job_id)", id="chain-child"),
    ],
)
async def test_each_new_job_shape_blocks_the_jobs_downgrade(
    db_session: AsyncSession, overrides: dict[str, Any], label: str
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    tree = await _make_novel_tree(db_session, user.id)
    assert await _call(db_session, _R2._downgrade_blockers) == {}

    values: dict[str, Any] = {
        "novel_id": tree.novel.id,
        "user_id": user.id,
        "kind": "chapter_generate",
        "status": "succeeded",
        "charged_amount": 0,
    }
    await db_session.execute(sa.insert(NovelJob).values({**values, **overrides}))

    assert await _call(db_session, _R2._downgrade_blockers) == {label: 1}
    with pytest.raises(RuntimeError, match="옛 스키마가 받을 수 없는 행"):
        await _call(db_session, _R2._assert_downgradable)
