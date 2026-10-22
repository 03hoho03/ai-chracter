"""화 개정 블록 칸을 NOT NULL 로 좁히는 마이그레이션(`211f81f33be5`)의 첫머리 채우기와 왕복.

세션 스코프 스키마가 이미 `upgrade head` 를 해 두 칸이 NOT NULL 이다. 비어 있는 행을 만들려고 테스트마다 롤백되는 `db_session`
커넥션에서 이 리비전의 downgrade(NOT NULL 해제)를 먼저 돌린다 — DDL 도 그 트랜잭션과 함께 롤백된다."""

import hashlib
import importlib.util
import uuid
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from api.db.models import NovelChapterRevision
from api.novelize.blocks import content_hash
from api.novelize.text import split_paragraphs
from factories import NovelTree, _make_novel_tree, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("211f81f33be5")

# 앞뒤 공백·탭 줄·연달은 빈 줄이 섞인 본문 — 채운 id 수와 해시가 런타임의 문단 나누기와 같아야 한다.
_ROUGH_BODY = "  가.\n \t \n나.\n다.\n\n\n\n라.  "


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _nullable(connection: AsyncConnection) -> dict[str, str]:
    rows = await connection.execute(
        sa.text(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'novel_chapter_revisions' AND column_name IN ('block_ids', 'content_hash')"
        )
    )
    return {name: nullable for name, nullable in rows.all()}


async def _tree(db: AsyncSession) -> NovelTree:
    user = _make_user()
    db.add(user)
    await db.flush()
    return await _make_novel_tree(db, user.id)


async def _row(db: AsyncSession, revision_id: uuid.UUID) -> tuple[list[uuid.UUID] | None, str | None]:
    row = (
        await db.execute(
            sa.select(NovelChapterRevision.block_ids, NovelChapterRevision.content_hash)
            .where(NovelChapterRevision.id == revision_id)
            .execution_options(populate_existing=True)
        )
    ).one()
    return row.block_ids, row.content_hash


async def test_fill_gives_empty_rows_an_id_per_paragraph_and_a_missing_hash_without_touching_ids(
    db_session: AsyncSession,
) -> None:
    """두 칸이 빈 개정은 문단마다 겹치지 않는 새 id 와 해시를, 해시만 빈 개정은 id 를 그대로 둔 채 해시를 받는다. 다 찬
    개정은 그대로고, 다시 돌리면 채울 행이 없다. 깨지는 시나리오: 해시만 빈 행을 건너뛰어 NOT NULL 이 배포를 멈추거나, 이미
    쓴 id 를 새로 매기거나, 문단 나누기가 런타임과 달라 그 개정 조회가 실패한다."""
    connection = await db_session.connection()
    await _run(connection, _M.downgrade)
    tree = await _tree(db_session)
    first_ids, first_hash = await _row(db_session, tree.first_revision.id)
    await db_session.execute(
        sa.update(NovelChapterRevision)
        .where(NovelChapterRevision.id == tree.first_revision.id)
        .values(content_hash=None)
    )
    await db_session.execute(
        sa.update(NovelChapterRevision)
        .where(NovelChapterRevision.id == tree.reverting_revision.id)
        .values(body=_ROUGH_BODY, block_ids=None, content_hash=None)
    )
    untouched = uuid.uuid4()
    await db_session.execute(
        sa.insert(NovelChapterRevision).values(
            id=untouched,
            chapter_id=tree.chapter.id,
            revision_no=3,
            body="그대로.",
            source="manual_edit",
            block_ids=[uuid.uuid4()],
            content_hash="0" * 64,
        )
    )
    before_untouched = await _row(db_session, untouched)

    assert await connection.run_sync(_M.fill_missing_blocks) == 2
    assert await connection.run_sync(_M.fill_missing_blocks) == 0

    assert await _row(db_session, tree.first_revision.id) == (first_ids, first_hash)
    filled_ids, filled_hash = await _row(db_session, tree.reverting_revision.id)
    assert filled_ids is not None
    assert len(filled_ids) == len(split_paragraphs(_ROUGH_BODY)) == len(set(filled_ids))
    assert filled_hash == content_hash(_ROUGH_BODY)
    assert await _row(db_session, untouched) == before_untouched


async def test_downgrade_only_lifts_not_null_and_upgrade_fills_what_was_left_empty_then_tightens(
    db_session: AsyncSession,
) -> None:
    """downgrade 는 NOT NULL 만 풀고 칸·값을 남긴다. 그 사이 칸을 모르는 이미지가 쓴 것 같은 빈 개정이 생겨도 upgrade 가
    먼저 채우고 두 칸을 NOT NULL 로 좁힌다. 깨지는 시나리오: downgrade 가 칸을 지워 떠 있는 새 코드가 깨지거나, upgrade 가
    채우기 전에 좁혀 빈 행에서 멈추거나, 한 칸만 좁힌다."""
    connection = await db_session.connection()
    tree = await _tree(db_session)
    kept = await _row(db_session, tree.first_revision.id)

    await _run(connection, _M.downgrade)
    after_down = await _nullable(connection)
    kept_after_down = await _row(db_session, tree.first_revision.id)
    await db_session.execute(
        sa.insert(NovelChapterRevision).values(
            chapter_id=tree.chapter.id, revision_no=3, body="옛 이미지.\n\n본문.", source="manual_edit"
        )
    )
    await _run(connection, _M.upgrade)

    assert after_down == {"block_ids": "YES", "content_hash": "YES"}
    assert kept_after_down == kept
    assert await _nullable(connection) == {"block_ids": "NO", "content_hash": "NO"}
    empty = await connection.execute(
        sa.text("SELECT count(*) FROM novel_chapter_revisions WHERE block_ids IS NULL OR content_hash IS NULL")
    )
    assert empty.scalar_one() == 0
    filled = await connection.execute(
        sa.text("SELECT block_ids, content_hash FROM novel_chapter_revisions WHERE chapter_id = :id AND revision_no = 3"),
        {"id": tree.chapter.id},
    )
    (block_ids, digest), = filled.all()
    assert len(block_ids) == 2
    assert digest == hashlib.sha256("옛 이미지.\n\n본문.".encode()).hexdigest()
