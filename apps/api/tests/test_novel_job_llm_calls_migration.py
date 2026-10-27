"""소설 작업 호출 기록 칸 마이그레이션(`d59bf28caea5`)의 옛 이미지 호환·왕복 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 옛 이미지의 쓰기는 새 칸을 모르는 원시 SQL 로 흉내 낸다 — 옛
매퍼는 이 칸을 몰라 INSERT 에 싣지 않는다. `alembic check` 는 `server_default` 를 비교하지 않으므로, 칸을 모르는 INSERT 가 기본값
`[]` 을 받는지는 이 파일이 유일한 신호다. downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서
돌린다."""

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

from api.db.models import Novel
from factories import _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("d59bf28caea5")


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _old_image_job(session: AsyncSession) -> uuid.UUID:
    """칸을 모르는 쓰기로 넣은 끝난(실패) 구성안 작업 하나. 소설은 방 없이 행만 넣는다."""
    user = _make_user()
    session.add(user)
    await session.flush()
    novel = Novel(
        user_id=user.id,
        chat_room_id=None,
        content_id=uuid.uuid4(),
        content_type="character",
        content_title="원작",
        character_name="캐릭터",
    )
    session.add(novel)
    await session.flush()
    job_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO novel_jobs (id, novel_id, user_id, kind, status, charged_amount, failure_code, finished_at)"
            " VALUES (:id, :novel, :user, 'outline_generate', 'failed', 0, 'internal', now())"
        ),
        {"id": job_id, "novel": novel.id, "user": user.id},
    )
    return job_id


async def _calls(connection: AsyncConnection, job_id: uuid.UUID) -> object:
    return (
        await connection.execute(sa.text("SELECT llm_calls FROM novel_jobs WHERE id = :id"), {"id": job_id})
    ).scalar_one()


async def test_an_insert_that_does_not_know_the_column_gets_an_empty_list(db_session: AsyncSession) -> None:
    """칸을 모르는 옛 이미지의 작업 INSERT 는 칸을 비운 채 들어가고 서버 기본값 `[]` 을 받는다(NULL 이 아니다). 깨지는 시나리오:
    배포 겹침 동안 옛 이미지의 작업 생성이 NOT NULL 위반으로 500 이 되거나, 기본값이 빠져 원가 보고가 NULL 을 읽는다."""
    job_id = await _old_image_job(db_session)

    assert await _calls(await db_session.connection(), job_id) == []


async def test_downgrade_drops_the_column_and_upgrade_brings_it_back_empty(ddl_engine: AsyncEngine) -> None:
    """내리면 칸이 사라지고(기록은 버린다), 다시 올리면 있던 행이 `[]` 로 칸을 다시 받는다. 깨지는 시나리오: downgrade 가 칸을
    남겨 다시 올릴 때 칸 추가가 실패하거나, upgrade 가 기본값 없이 칸을 더해 있던 행에서 NOT NULL 위반이 난다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            job_id = await _old_image_job(session)
            await session.flush()
            await connection.execute(
                sa.text("UPDATE novel_jobs SET llm_calls = CAST(:calls AS jsonb) WHERE id = :id"),
                {"calls": '[{"callSite": "novelize_outline"}]', "id": job_id},
            )

            await _run(connection, _M.downgrade)
            after_down = (
                await connection.execute(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns"
                        " WHERE table_name = 'novel_jobs' AND column_name = 'llm_calls'"
                    )
                )
            ).scalar_one()
            await _run(connection, _M.upgrade)
            after_up = await _calls(connection, job_id)
        finally:
            await transaction.rollback()

    assert after_down == 0
    assert after_up == []
