"""집필권 잠금 마이그레이션(`e05462d680f0`)의 백필·CHECK·작품 소설화 허락 기본값 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 백필 함수는 테스트마다 롤백되는 `db_session`
커넥션에 직접 부르고, 리비전의 downgrade·upgrade 를 실제로 돌려야 하는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션
안에서 돌린다(세션 스코프 스키마는 그대로 남는다). `alembic check` 는 CHECK 제약도 서버 기본값도 비교하지 않으므로 이
파일의 테스트가 그 둘의 유일한 신호다."""

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import Novel, NovelChapter, NovelJob, NovelJobKind, NovelJobStatus
from factories import _get_genre, _make_published_character, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("e05462d680f0")

_T0 = datetime(2026, 10, 1, tzinfo=UTC)

_LockRow = tuple[datetime | None, str | None, str | None, uuid.UUID | None]
_UNLOCKED: _LockRow = (None, None, None, None)


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    """리비전의 upgrade·downgrade 를 이 커넥션에서 alembic `op` 가 쓰이도록 돌린다."""

    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _backfill(db_session: AsyncSession) -> int:
    connection = await db_session.connection()
    locked: int = await connection.run_sync(_M.backfill_writing_locks)
    return locked


async def _novel(db_session: AsyncSession, user_id: uuid.UUID, **lock: Any) -> uuid.UUID:
    novel = Novel(user_id=user_id, content_id=uuid.uuid4(), content_type="story", content_title="원작", **lock)
    db_session.add(novel)
    await db_session.flush()
    return novel.id


async def _chapter(db_session: AsyncSession, novel_id: uuid.UUID, ordinal: int, created_at: datetime) -> None:
    db_session.add(
        NovelChapter(
            novel_id=novel_id,
            ordinal=ordinal,
            start_message_id=uuid.uuid4(),
            start_message_created_at=_T0,
            end_message_id=uuid.uuid4(),
            end_message_created_at=_T0,
            assistant_message_count=1,
            source_hash="0" * 64,
            created_at=created_at,
        )
    )
    await db_session.flush()


async def _job(
    db_session: AsyncSession,
    novel_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: NovelJobKind,
    status: NovelJobStatus,
    finished_at: datetime,
) -> None:
    chain_plan = {"planned_batches": 1, "batch_k_max": 1, "unit_price": 1} if kind == "chain_generate" else {}
    db_session.add(
        NovelJob(
            novel_id=novel_id,
            user_id=user_id,
            kind=kind,
            status=status,
            charged_amount=0,
            finished_at=finished_at,
            **chain_plan,
        )
    )
    await db_session.flush()


async def _locks(db_session: AsyncSession, novel_ids: list[uuid.UUID]) -> dict[uuid.UUID, _LockRow]:
    rows = await db_session.execute(
        sa.select(
            Novel.id,
            Novel.writing_locked_at,
            Novel.writing_lock_source,
            Novel.writing_lock_permission,
            Novel.writing_lock_content_version_id,
        ).where(Novel.id.in_(novel_ids))
    )
    return {
        novel_id: (locked_at, source, permission, version_id)
        for novel_id, locked_at, source, permission, version_id in rows.tuples()
    }


async def test_backfill_locks_only_novels_whose_first_chapter_was_ever_saved(db_session: AsyncSession) -> None:
    """화가 있는 소설은 가장 이른 화 생성 시각으로, 화를 다 지웠어도 성공한 화 생성 작업이 있는 소설은 그 작업의 끝난
    시각으로 잠그고, 출처는 백필·허락과 원작 버전은 알 수 없음(NULL)이다. 빈 소설, 실패한 화 생성 작업만 있는 소설, 연쇄
    부모만 성공한 소설은 잠그지 않는다. 깨지는 시나리오: 첫 화를 만든 적 없는 소설이 잠겨 작가가 막은 원작으로 계속
    쓰거나, 배포 전에 화를 지운 소설이 잠기지 않아 이어 쓰기가 막힌다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    with_chapters = await _novel(db_session, user.id)
    await _chapter(db_session, with_chapters, 2, _T0 + timedelta(hours=1))
    await _chapter(db_session, with_chapters, 1, _T0)
    chapters_deleted = await _novel(db_session, user.id)
    await _job(db_session, chapters_deleted, user.id, "chapter_generate", "failed", _T0 - timedelta(days=1))
    await _job(db_session, chapters_deleted, user.id, "chapter_generate", "succeeded", _T0 + timedelta(days=1))
    empty = await _novel(db_session, user.id)
    failed_only = await _novel(db_session, user.id)
    await _job(db_session, failed_only, user.id, "chapter_generate", "failed", _T0)
    chain_parent_only = await _novel(db_session, user.id)
    await _job(db_session, chain_parent_only, user.id, "chain_generate", "succeeded", _T0)

    await _backfill(db_session)

    assert await _locks(db_session, [with_chapters, chapters_deleted, empty, failed_only, chain_parent_only]) == {
        with_chapters: (_T0, "backfill", None, None),
        chapters_deleted: (_T0 + timedelta(days=1), "backfill", None, None),
        empty: _UNLOCKED,
        failed_only: _UNLOCKED,
        chain_parent_only: _UNLOCKED,
    }


async def test_backfill_run_again_changes_no_lock(db_session: AsyncSession) -> None:
    """두 번째 실행은 아무 소설도 고치지 않고, 첫 화 저장이 이미 남긴 잠금도 덮지 않는다. 옛 이미지가 다 내려간 뒤 같은
    문장을 한 번 더 돌리는 절차가 이 성질에 기댄다. 깨지는 시나리오: 재실행이 첫 화 저장의 허락 사본을 지우거나 잠긴
    시각을 앞당긴다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    backfilled = await _novel(db_session, user.id)
    await _chapter(db_session, backfilled, 1, _T0)
    version_id = uuid.uuid4()
    locked_at_first_chapter = await _novel(
        db_session,
        user.id,
        writing_locked_at=_T0 + timedelta(days=2),
        writing_lock_source="first_chapter",
        writing_lock_permission="private",
        writing_lock_content_version_id=version_id,
    )
    await _chapter(db_session, locked_at_first_chapter, 1, _T0)
    await _backfill(db_session)
    first = await _locks(db_session, [backfilled, locked_at_first_chapter])

    assert await _backfill(db_session) == 0

    assert await _locks(db_session, [backfilled, locked_at_first_chapter]) == first
    assert first[locked_at_first_chapter] == (_T0 + timedelta(days=2), "first_chapter", "private", version_id)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        pytest.param(
            {"writing_lock_permission": "unknown"}, "ck_novels_writing_lock_permission", id="unknown-permission"
        ),
        pytest.param(
            {"writing_lock_permission": "PRIVATE"}, "ck_novels_writing_lock_permission", id="uppercase-permission"
        ),
        pytest.param(
            {"writing_locked_at": _T0, "writing_lock_source": "manual"},
            "ck_novels_writing_lock_source",
            id="unknown-source",
        ),
        pytest.param(
            {"writing_locked_at": _T0, "writing_lock_source": "BACKFILL"},
            "ck_novels_writing_lock_source",
            id="uppercase-source",
        ),
        pytest.param({"writing_locked_at": _T0}, "ck_novels_writing_lock_complete", id="time-without-source"),
        pytest.param({"writing_lock_source": "backfill"}, "ck_novels_writing_lock_complete", id="source-without-time"),
    ],
)
async def test_writing_lock_rejects_out_of_range_or_half_written_values(
    db_session: AsyncSession, values: dict[str, Any], constraint: str
) -> None:
    """허락 사본과 출처는 정해진 값만, 잠긴 시각과 출처는 함께 있거나 함께 없다. 깨지는 시나리오: 출처 없는 잠금이 생겨
    알 수 없는 잠금과 첫 화 잠금을 가를 수 없거나, 모르는 허락 값이 사본으로 남는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    novel_id = await _novel(db_session, user.id)

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(**values))


async def test_writing_lock_accepts_both_sources_and_unknown_permission(db_session: AsyncSession) -> None:
    """위 CHECK 들이 정상 모양을 막지 않는다 — 첫 화 잠금, 허락을 알 수 없는 백필 잠금, 원작 행이 사라져 허락 사본이 빈
    첫 화 잠금. 깨지는 시나리오: 너무 좁은 CHECK 가 값을 치른 첫 화 저장 전체를 실패시킨다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    locks: list[dict[str, Any]] = [
        {
            "writing_lock_source": "first_chapter",
            "writing_lock_permission": "forbidden",
            "writing_lock_content_version_id": uuid.uuid4(),
        },
        {"writing_lock_source": "backfill"},
        {"writing_lock_source": "first_chapter"},
    ]
    for lock in locks:
        await _novel(db_session, user.id, writing_locked_at=_T0, **lock)


async def test_upgrade_keeps_existing_permissions_and_defaults_new_works_to_forbidden(ddl_engine: AsyncEngine) -> None:
    """리비전을 실제로 내린 뒤 옛 기본값으로 작품을 하나 넣고, 옛 스키마에 화 있는 소설을 넣고 다시 올린다. 기존 작품의
    허락은 그대로이고 그 뒤 허락 없이 넣은 작품은 "허용 안 함"이며, upgrade 가 백필까지 마친다. 깨지는 시나리오: 기본값
    변경이 기존 작품을 함께 고쳐 작가가 고른 적 없는 거절이 퍼지거나, 새 작품이 여전히 남의 소설화를 연다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _run(connection, _M.downgrade)
            session = AsyncSession(bind=connection)
            author = _make_user()
            session.add(author)
            await session.flush()
            genre = await _get_genre(session)
            existing = await _make_published_character(session, creator_user_id=author.id, genre_id=genre.id)
            novel_id = uuid.uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO novels (id, user_id, content_id, content_type, content_title)"
                    " VALUES (:id, :user_id, :content_id, 'story', '원작')"
                ),
                {"id": novel_id, "user_id": author.id, "content_id": existing.id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO novel_chapters (id, novel_id, ordinal, start_message_id, start_message_created_at,"
                    " end_message_id, end_message_created_at, assistant_message_count, source_hash, created_at)"
                    " VALUES (:id, :novel_id, 1, :message_id, :at, :message_id, :at, 1, :source_hash, :at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "novel_id": novel_id,
                    "message_id": uuid.uuid4(),
                    "at": _T0,
                    "source_hash": "0" * 64,
                },
            )
            permission_sql = sa.text("SELECT novel_permission FROM contents WHERE id = :id")
            before = await connection.scalar(permission_sql, {"id": existing.id})

            await _run(connection, _M.upgrade)
            created_after = await _make_published_character(session, creator_user_id=author.id, genre_id=genre.id)
            after = await connection.scalar(permission_sql, {"id": existing.id})
            new_default = await connection.scalar(permission_sql, {"id": created_after.id})
            lock = (
                await connection.execute(
                    sa.text("SELECT writing_locked_at, writing_lock_source FROM novels WHERE id = :id"),
                    {"id": novel_id},
                )
            ).one()
        finally:
            await transaction.rollback()

    assert (before, after, new_default) == ("private", "private", "forbidden")
    assert tuple(lock) == (_T0, "backfill")
