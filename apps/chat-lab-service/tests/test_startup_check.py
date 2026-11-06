"""기동 점검: DB 의 마이그레이션 판이 코드가 기대하는 판과 다르면 서비스가 뜨지 않는다.

마이그레이션을 빠뜨린 배포가 요청마다 500 으로 흩어지지 않고 기동 실패 하나로 드러나게 하려는 것이다. 테스트는 시험 DB 의 판
표를 잠깐 바꾸고, 끝나면 세션 끝의 내리기가 돌 수 있게 원래대로 되돌린다.
"""

from __future__ import annotations

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from chat_lab_service.db import SCHEMA_REVISION, VERSION_TABLE, StartupCheckError
from harness import SV_ROOT, Db, Lab, OpenLab

OTHER_REVISION = "0000deadbeef"
MOVED_TABLE = f"{VERSION_TABLE}_moved_away"

SCHEMA_STATES = {
    "other-revision": f"UPDATE {VERSION_TABLE} SET version_num = '{OTHER_REVISION}'",
    "two-rows": f"INSERT INTO {VERSION_TABLE} (version_num) VALUES ('{OTHER_REVISION}')",
    "empty": f"DELETE FROM {VERSION_TABLE}",
    "missing-table": f"ALTER TABLE {VERSION_TABLE} RENAME TO {MOVED_TABLE}",
}


@pytest.mark.parametrize("state", sorted(SCHEMA_STATES))
async def test_startup_fails_when_schema_revision_differs(open_lab: OpenLab, db: Db, state: str) -> None:
    originals = [row["version_num"] for row in await db.fetch(f"SELECT version_num FROM {VERSION_TABLE}")]
    assert originals == [SCHEMA_REVISION]
    await db.execute(SCHEMA_STATES[state])
    try:
        with pytest.raises(StartupCheckError) as raised:
            async with open_lab():
                pytest.fail("판이 다른 DB 로 기동이 끝났다")
    finally:
        if state == "missing-table":
            await db.execute(f"ALTER TABLE {MOVED_TABLE} RENAME TO {VERSION_TABLE}")
        else:
            await db.execute(f"DELETE FROM {VERSION_TABLE}")
            await db.execute(f"INSERT INTO {VERSION_TABLE} (version_num) VALUES (:revision)", revision=SCHEMA_REVISION)
    if state != "missing-table":
        # 운영자가 무엇을 돌려야 하는지 알게 기대한 판을 알린다.
        assert SCHEMA_REVISION in str(raised.value)


def test_schema_revision_is_migration_head() -> None:
    # 마이그레이션을 더하고 코드의 판을 올리지 않으면, `upgrade head` 를 돌린 DB 로도 서비스가 뜨지 않는다.
    config = Config(str(SV_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SV_ROOT / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == [SCHEMA_REVISION]


async def test_engine_pool_fits_role_connection_limit(lab: Lab) -> None:
    """앱 엔진은 풀 2 + 넘침 1 = 3 접속까지만 연다 — DB 역할 접속 상한 5 에서 마이그레이션 1·여유 1 을 뺀 몫이다."""
    engines = [
        value
        for middleware in lab.app.user_middleware
        for value in middleware.kwargs.values()
        if isinstance(value, AsyncEngine)
    ]
    assert engines, "앱이 미들웨어에 넘긴 엔진을 찾지 못했다"
    for engine in engines:
        pool = engine.sync_engine.pool
        assert isinstance(pool, QueuePool), type(pool)
        assert (pool.size(), pool._max_overflow) == (2, 1)
