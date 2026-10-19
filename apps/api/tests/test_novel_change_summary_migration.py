"""변경 요약 마이그레이션(`f89a3d8ed3a8`)의 제약·옛 이미지 호환·왕복 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 옛 이미지의 쓰기는 새 칸을 모르는 원시 SQL 로 흉내 낸다.
`alembic check` 는 CHECK 를 비교하지 않으므로 요약 길이와 심사 자리 CHECK 는 이 파일이 유일한 신호다. downgrade·upgrade 를
실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다."""

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

from factories import PublicNovel, _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("f89a3d8ed3a8")


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


_COPY_EDITION = sa.text(
    "INSERT INTO novel_chapter_editions (chapter_id, edition, novel_id, revision_id, title, author_note)"
    " SELECT chapter_id, edition, novel_id, revision_id, title, author_note FROM novel_chapter_publications"
    " WHERE chapter_id = :c"
)


async def _novel(session: AsyncSession) -> PublicNovel:
    """한 화짜리 공개 소설과 그 화의 1판 판 행 — 판 행은 새 칸을 모르는 옛 이미지의 쓰기처럼 칸을 생략해 넣는다."""
    user = _make_user()
    session.add(user)
    await session.flush()
    novel = await _make_public_novel(session, user.id, batches=(1,))
    await session.flush()
    await session.execute(_COPY_EDITION, {"c": novel.chapter_ids[0]})
    return novel


async def _set_summary(connection: AsyncConnection, novel: PublicNovel, summary: str) -> None:
    await connection.execute(
        sa.text("UPDATE novel_chapter_editions SET change_summary = :summary WHERE chapter_id = :chapter"),
        {"summary": summary, "chapter": novel.chapter_ids[0]},
    )


async def _screening(connection: AsyncConnection, novel: PublicNovel, parts: list[str]) -> uuid.UUID:
    row_id = uuid.uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO novel_screenings (id, novel_id, user_id, outcome, flagged_parts, model)"
            " VALUES (:id, :novel, :user, 'rejected', :parts, 'm')"
        ),
        {"id": row_id, "novel": novel.novel_id, "user": novel.publisher_id, "parts": parts},
    )
    return row_id


@pytest.mark.parametrize(
    "summary",
    [pytest.param("", id="empty"), pytest.param("가" * 101, id="101-chars")],
)
async def test_an_edition_summary_must_be_one_to_a_hundred_characters(db_session: AsyncSession, summary: str) -> None:
    """판 행의 요약은 비어 있거나(NULL) 1~100자다. 깨지는 시나리오: 요청 검증을 거치지 않은 쓰기가 빈 요약이나 긴 글을 남겨
    판 고르기 한 줄을 깨뜨린다."""
    novel = await _novel(db_session)
    connection = await db_session.connection()

    with pytest.raises(IntegrityError, match="ck_novel_chapter_editions_change_summary_length"):
        async with connection.begin_nested():
            await _set_summary(connection, novel, summary)


async def test_old_image_edition_writes_leave_the_summary_empty_and_a_hundred_characters_fit(
    db_session: AsyncSession,
) -> None:
    """새 칸을 모르는 옛 이미지의 판 행 INSERT 는 요약을 비운 채(NULL) 들어가고, 100자 요약은 들어간다. 깨지는 시나리오: 배포
    겹침 동안 옛 이미지의 공개가 판 행 쓰기에서 500 이 되거나, 상한 그대로의 요약이 거부된다."""
    novel = await _novel(db_session)
    connection = await db_session.connection()

    left = (
        await connection.execute(
            sa.text("SELECT change_summary FROM novel_chapter_editions WHERE chapter_id = :c"), {"c": novel.chapter_ids[0]}
        )
    ).scalar_one()
    await _set_summary(connection, novel, "가" * 100)

    assert left is None


async def test_screening_records_take_the_summary_part_but_no_unknown_part(db_session: AsyncSession) -> None:
    """심사 기록은 새 자리(`change_summary`)를 받고 모르는 자리는 여전히 거부한다. 깨지는 시나리오: 요약만 걸린 거부를 남기는
    쓰기가 500 이 되거나, 넓히면서 자리 검사가 사라진다."""
    novel = await _novel(db_session)
    connection = await db_session.connection()

    await _screening(connection, novel, ["change_summary"])
    with pytest.raises(IntegrityError, match="ck_novel_screenings_flagged_parts"):
        async with connection.begin_nested():
            await _screening(connection, novel, ["change_summary", "cover"])


async def test_downgrade_drops_the_summary_part_from_records_and_upgrade_brings_the_column_back_empty(
    ddl_engine: AsyncEngine,
) -> None:
    """리비전을 내리면 심사 기록에서 요약 자리만 빠지고(다른 자리는 남는다) 좁은 CHECK 가 돌아오며 요약 칸이 사라진다. 다시
    올리면 칸이 빈 채로 돌아오고 새 자리를 다시 받는다. 깨지는 시나리오: 요약 자리가 찍힌 기록 때문에 downgrade 가 CHECK
    재생성에서 실패하거나, 내린 뒤에도 새 자리가 들어가 옛 코드가 그 기록을 읽다 500 이 된다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            novel = await _novel(session)
            await session.flush()
            await _set_summary(connection, novel, "결말을 바꿨어요.")
            only_summary = await _screening(connection, novel, ["change_summary"])
            mixed = await _screening(connection, novel, ["chapter_body", "change_summary"])

            await _run(connection, _M.downgrade)
            rows = await connection.execute(
                sa.text("SELECT id, flagged_parts FROM novel_screenings WHERE id IN (:a, :b)"),
                {"a": only_summary, "b": mixed},
            )
            parts = {row_id: flagged for row_id, flagged in rows.all()}
            column_after_down = (
                await connection.execute(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns"
                        " WHERE table_name = 'novel_chapter_editions' AND column_name = 'change_summary'"
                    )
                )
            ).scalar_one()
            with pytest.raises(IntegrityError, match="ck_novel_screenings_flagged_parts"):
                async with connection.begin_nested():
                    await _screening(connection, novel, ["change_summary"])

            await _run(connection, _M.upgrade)
            summary_after_up = (
                await connection.execute(
                    sa.text("SELECT change_summary FROM novel_chapter_editions WHERE chapter_id = :c"),
                    {"c": novel.chapter_ids[0]},
                )
            ).scalar_one()
            await _screening(connection, novel, ["change_summary"])
        finally:
            await transaction.rollback()

    assert parts == {only_summary: [], mixed: ["chapter_body"]}
    assert column_after_down == 0
    assert summary_after_up is None
