import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine


def _table_names(sync_conn: Connection) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


async def test_migration_creates_expected_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as connection:
        tables = await connection.run_sync(_table_names)

    assert {"users", "assets", "guardian_consents", "admin_users"} <= tables


async def test_users_profile_image_fk_points_to_assets(db_engine: AsyncEngine) -> None:
    def _fk_targets(sync_conn: Connection) -> set[str]:
        fks = sa.inspect(sync_conn).get_foreign_keys("users")
        return {fk["referred_table"] for fk in fks if "profile_image_asset_id" in fk["constrained_columns"]}

    async with db_engine.connect() as connection:
        targets = await connection.run_sync(_fk_targets)

    assert targets == {"assets"}
