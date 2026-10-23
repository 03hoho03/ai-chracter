"""여러 문단 수정 칸(`novel_jobs.block_edit`)의 제약·옛 이미지 호환·왕복.

CHECK 는 `alembic check` 가 비교하지 않으므로 이 파일의 `IntegrityError` 테스트가 유일한 신호다. downgrade·upgrade 를 실제로 돌리는
테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다."""

import importlib.util
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

from api.db.models import NovelJob
from factories import NovelTree, _make_novel_tree, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load_schema_migration() -> ModuleType:
    (path,) = _VERSIONS_DIR.glob("*_novel_block_edit_schema.py")
    spec = importlib.util.spec_from_file_location("_migration_novel_block_edit_schema", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_schema_migration()

_PENDING = {"v": 1, "targets": [], "sceneId": None, "patches": [{"id": "p", "state": "pending"}], "bundles": []}
_FINISHED = {"v": 1, "targets": [], "sceneId": None, "patches": [{"id": "p", "state": "dismissed"}], "bundles": []}


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _tree(db: AsyncSession) -> NovelTree:
    user = _make_user()
    db.add(user)
    await db.flush()
    tree = await _make_novel_tree(db, user.id)
    # 소설당 진행 중 작업은 하나다 — 진행 중 패치 작업을 넣을 자리를 비운다.
    tree.active_job.status = "succeeded"
    await db.flush()
    return tree


def _job(tree: NovelTree, **overrides: object) -> NovelJob:
    values: dict[str, object] = {
        "novel_id": tree.novel.id,
        "user_id": tree.novel.user_id,
        "kind": "ai_edit",
        "status": "succeeded",
        "charged_amount": 1,
        "chapter_id": tree.chapter.id,
        "block_edit": _PENDING,
    }
    values.update(overrides)
    return NovelJob(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"kind": "chapter_generate"}, id="other-kind"),
        pytest.param({"result_text": "장 전체 본문"}, id="whole-body"),
        pytest.param({"paragraph_start": 0, "paragraph_end": 0}, id="range"),
    ],
)
async def test_a_patch_job_is_an_ai_edit_without_a_range_or_a_whole_body(
    db_session: AsyncSession, overrides: dict[str, object]
) -> None:
    """패치 칸이 있는 행은 AI 수정이고 범위·결과 본문이 비어 있다(`ck_novel_jobs_block_edit`). 깨지는 시나리오: 패치 작업에 결과
    본문이 채워지면 옛 낡은 미리보기 비우기가 그 작업을 골라 패치 하나 적용 뒤 남은 패치의 지시문까지 지우고, 범위가 채워지면
    옛 적용이 그 범위로 화를 덮어쓴다."""
    tree = await _tree(db_session)
    with pytest.raises(IntegrityError, match="ck_novel_jobs_block_edit"):
        async with db_session.begin_nested():
            db_session.add(_job(tree, **overrides))
            await db_session.flush()
    db_session.add(_job(tree))
    await db_session.flush()


@pytest.mark.parametrize("leftover", ["pending_patch", "running_patch_job"])
async def test_downgrade_refuses_while_a_patch_could_still_hold_text_and_round_trips_after(
    ddl_engine: AsyncEngine, leftover: str
) -> None:
    """대기 패치가 남은 행이나 진행 중인 패치 작업(끝나면 대기 패치가 생긴다)이 있으면 downgrade 가 아무것도 바꾸기 전에 멈춘다.
    끝난 패치 작업(상태·id 만 남은 기록)만 있으면 칸과 함께 버리고 내려가며, 다시 올리면 칸과 CHECK 가 돌아온다. 깨지는 시나리오:
    칸을 지운 옛 스키마에서 지운 화의 본문 조각을 가진 대기 패치가 아무도 못 지우는 사본으로 남거나(옛 코드는 그 칸을 모른다),
    끝난 기록 하나 때문에 되돌리기가 영영 막힌다."""

    async def has_column(connection: AsyncConnection) -> bool:
        return bool(
            await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM information_schema.columns"
                    " WHERE table_name = 'novel_jobs' AND column_name = 'block_edit'"
                )
            )
        )

    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            tree = await _tree(session)
            if leftover == "pending_patch":
                session.add(_job(tree))
            else:
                session.add(_job(tree, status="running", block_edit={**_PENDING, "patches": []}))
            await session.flush()
            session.add(_job(tree, status="failed", block_edit=_FINISHED))
            await session.flush()

            with pytest.raises(RuntimeError, match="남아 있다"):
                async with connection.begin_nested():
                    await _run(connection, _M.downgrade)
            still = await has_column(connection)
            await connection.execute(
                sa.text("DELETE FROM novel_jobs WHERE block_edit IS NOT NULL AND status <> 'failed'")
            )
            await _run(connection, _M.downgrade)
            after_down = await has_column(connection)
            await _run(connection, _M.upgrade)
            after_up = await has_column(connection)
            constraint = await connection.scalar(
                sa.text("SELECT count(*) FROM pg_constraint WHERE conname = 'ck_novel_jobs_block_edit'")
            )
        finally:
            await transaction.rollback()

    assert (still, after_down, after_up, constraint) == (True, False, True, 1)


async def test_the_old_image_dismiss_on_a_patch_job_passes_the_check(db_session: AsyncSession) -> None:
    """칸을 모르는 옛 이미지의 버리기(버린 시각 + 지시문·결과 본문 NULL)는 패치 작업 행에서도 CHECK 를 통과한다(500 없음)."""
    tree = await _tree(db_session)
    job = _job(tree, instruction="더 쓸쓸하게")
    db_session.add(job)
    await db_session.flush()
    connection = await db_session.connection()

    await connection.execute(
        sa.text("UPDATE novel_jobs SET dismissed_at = now(), instruction = NULL, result_text = NULL WHERE id = :id"),
        {"id": job.id},
    )

    assert await connection.scalar(sa.text("SELECT dismissed_at IS NOT NULL FROM novel_jobs WHERE id = :id"), {"id": job.id})
