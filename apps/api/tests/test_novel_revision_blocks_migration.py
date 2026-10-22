"""화 개정 블록 칸 마이그레이션(`17f49714e5ca`)의 백필과 왕복.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 백필 함수는 테스트마다 롤백되는 `db_session` 커넥션에
직접 부르고, downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다. 개정은 블록 칸을
비운 채(이 칸 이전 이미지가 쓴 행처럼) 생성자로 넣는다."""

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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import NovelChapterRevision
from api.db.models.novel import NovelRevisionSource
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


_M = _load("17f49714e5ca")


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _tree(db: AsyncSession, body: str) -> NovelTree:
    """화 하나에 생성 개정(1)과 그것을 되돌린 개정(2). 두 본문을 `body` 로 맞춘다."""
    user = _make_user()
    db.add(user)
    await db.flush()
    tree = await _make_novel_tree(db, user.id)
    await db.execute(
        sa.update(NovelChapterRevision).where(NovelChapterRevision.chapter_id == tree.chapter.id).values(body=body)
    )
    return tree


async def _stack(db: AsyncSession, tree: NovelTree, revision_no: int, body: str, source: NovelRevisionSource) -> None:
    db.add(NovelChapterRevision(chapter_id=tree.chapter.id, revision_no=revision_no, body=body, source=source))
    await db.flush()


async def _ids(db: AsyncSession, tree: NovelTree) -> list[list[uuid.UUID]]:
    rows = await db.execute(
        sa.select(NovelChapterRevision.block_ids, NovelChapterRevision.body, NovelChapterRevision.content_hash)
        .where(NovelChapterRevision.chapter_id == tree.chapter.id)
        .order_by(NovelChapterRevision.revision_no)
        .execution_options(populate_existing=True)
    )
    result: list[list[uuid.UUID]] = []
    for block_ids, body, content_hash in rows.all():
        assert block_ids is not None
        normalized = "\n\n".join(part.strip() for part in body.split("\n\n") if part.strip())
        assert content_hash == hashlib.sha256(normalized.encode()).hexdigest()
        assert len(set(block_ids)) == len(block_ids)
        result.append(list(block_ids))
    return result


async def test_backfill_copies_reverts_inherits_same_text_from_the_previous_revision_and_renews_regenerations(
    db_session: AsyncSession,
) -> None:
    """생성(1) → 되돌리기(2, 1 복제) → 직접 수정(3, 둘째 고치고 넷째 더함) → 다시 만들기(4, 같은 글) → AI 수정(5, 다섯째
    더함) → 되돌리기(6, 1 복제 — 바로 앞 개정과 글이 다르다). 깨지는 시나리오: 되돌리기가 원본 대신 직전 개정에서 잇거나, 직전 대신 첫 개정과 맞추거나, 다시 만들기가 글자가
    같다고 id 를 잇는다."""
    tree = await _tree(db_session, "가.\n\n나.\n\n다.")
    await _stack(db_session, tree, 3, "가.\n\n고친 나.\n\n다.\n\n라.", "manual_edit")
    await _stack(db_session, tree, 4, "가.\n\n고친 나.\n\n다.\n\n라.", "regenerate")
    await _stack(db_session, tree, 5, "가.\n\n고친 나.\n\n다.\n\n라.\n\n마.", "ai_edit")
    db_session.add(
        NovelChapterRevision(
            chapter_id=tree.chapter.id,
            revision_no=6,
            body="가.\n\n나.\n\n다.",
            source="revert",
            reverted_from_revision_id=tree.first_revision.id,
        )
    )
    await db_session.flush()
    connection = await db_session.connection()

    assert await connection.run_sync(_M.backfill_block_ids) == 6

    first, reverted, edited, regenerated, revised, reverted_again = await _ids(db_session, tree)
    assert len(first) == 3 and reverted == first
    assert (edited[0], edited[2]) == (first[0], first[2])
    assert edited[1] not in first and edited[3] not in first
    assert set(regenerated).isdisjoint(edited)
    assert revised[:4] == regenerated and revised[4] not in regenerated
    assert reverted_again == first


async def test_backfill_inherits_from_the_remaining_previous_revision_when_the_revert_source_is_gone(
    db_session: AsyncSession,
) -> None:
    """탈퇴 작가 정리 뒤 모양 — 되돌리기 원본 칸이 비고 중간 번호가 빠져 있다. 개정 5 는 남은 바로 앞(2)과 맞춘다.
    깨지는 시나리오: 번호 하나 앞(4)을 찾다 못 찾아 전부 새 id 가 되거나, 원본 칸이 빈 되돌리기에서 멈춘다."""
    tree = await _tree(db_session, "가.\n\n나.")
    await db_session.execute(
        sa.update(NovelChapterRevision)
        .where(NovelChapterRevision.id == tree.reverting_revision.id)
        .values(reverted_from_revision_id=None, body="가.\n\n바꾼 나.")
    )
    await _stack(db_session, tree, 5, "가.\n\n바꾼 나.\n\n더한 다.", "manual_edit")
    connection = await db_session.connection()

    await connection.run_sync(_M.backfill_block_ids)

    first, second, fifth = await _ids(db_session, tree)
    assert second[0] == first[0] and second[1] not in first
    assert fifth[:2] == second and fifth[2] not in second


async def test_backfill_fills_only_empty_rows_and_a_rerun_changes_nothing(db_session: AsyncSession) -> None:
    """이미 id 가 있는 개정은 그대로 두고 그 id 를 다음 개정이 잇는다. 다시 돌리면 채우는 행이 없고 값도 그대로다.
    깨지는 시나리오: `block_ids IS NULL` 조건이 빠져 새 코드가 쓴 id 나 앞 실행의 id 를 다시 매긴다."""
    tree = await _tree(db_session, "가.\n\n나.")
    written = [uuid.uuid4(), uuid.uuid4()]
    await db_session.execute(
        sa.update(NovelChapterRevision)
        .where(NovelChapterRevision.id == tree.first_revision.id)
        .values(block_ids=written, content_hash=hashlib.sha256("가.\n\n나.".encode()).hexdigest())
    )
    connection = await db_session.connection()

    assert await connection.run_sync(_M.backfill_block_ids) == 1
    filled = await _ids(db_session, tree)
    assert await connection.run_sync(_M.backfill_block_ids) == 0
    again = await _ids(db_session, tree)

    assert filled == [written, written]
    assert again == filled


async def test_downgrade_drops_the_columns_and_upgrade_fills_them_again(ddl_engine: AsyncEngine) -> None:
    """깨지는 시나리오: downgrade 가 칸을 남겨 옛 스키마와 어긋나거나, upgrade 가 칸만 더하고 있는 개정을 비워 둔다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            tree = await _tree(session, "가.\n\n나.")
            await session.flush()

            await _run(connection, _M.downgrade)
            columns_after_down = (
                await connection.execute(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'novel_chapter_revisions'"
                        " AND column_name IN ('block_ids', 'content_hash')"
                    )
                )
            ).scalar_one()
            await _run(connection, _M.upgrade)
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT block_ids, content_hash FROM novel_chapter_revisions WHERE chapter_id = :id"
                        " ORDER BY revision_no"
                    ),
                    {"id": tree.chapter.id},
                )
            ).all()
        finally:
            await transaction.rollback()

    assert columns_after_down == 0
    (first_ids, first_hash), (second_ids, second_hash) = rows
    assert len(first_ids) == 2 and second_ids == first_ids
    assert first_hash == second_hash == hashlib.sha256("가.\n\n나.".encode()).hexdigest()


def test_the_migrations_paragraph_split_matches_the_runtime_one() -> None:
    """백필이 매긴 id 수는 런타임 응답이 같은 본문을 나눈 문단 수와 같아야 한다(어긋나면 그 개정 조회가 실패한다). 공백 경계
    입력으로 두 나누기를 맞대 본다. 깨지는 시나리오: 한쪽 사본만 고쳐 `\\r\\n`·전각 공백·탭 줄을 다르게 나눈다."""
    bodies = [
        "가.\n\n나.",
        "  가.\n \t \n나.\n다.\n\n\n\n라.  ",
        "가.\r\n\r\n나.",
        "가.\n　\n나.　",
        "\n\n\n",
        "가.\n\t\n\t나.\n\n \n\n다.",
    ]

    assert [_M._split_paragraphs(body) for body in bodies] == [split_paragraphs(body) for body in bodies]
