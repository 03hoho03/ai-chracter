import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine


def _table_names(sync_conn: Connection) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


async def test_migration_creates_expected_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as connection:
        tables = await connection.run_sync(_table_names)

    assert {
        "users",
        "assets",
        "guardian_consents",
        "admin_users",
        "genres",
        "contents",
        "content_versions",
        "character_version_details",
        "situational_images",
        "story_version_details",
        "starting_setups",
        "stat_defs",
    } <= tables


async def test_users_profile_image_fk_points_to_assets(db_engine: AsyncEngine) -> None:
    def _fk_targets(sync_conn: Connection) -> set[str]:
        fks = sa.inspect(sync_conn).get_foreign_keys("users")
        return {fk["referred_table"] for fk in fks if "profile_image_asset_id" in fk["constrained_columns"]}

    async with db_engine.connect() as connection:
        targets = await connection.run_sync(_fk_targets)

    assert targets == {"assets"}


async def test_contents_current_published_version_fk_points_to_content_versions(
    db_engine: AsyncEngine,
) -> None:
    def _fk_targets(sync_conn: Connection) -> set[str]:
        fks = sa.inspect(sync_conn).get_foreign_keys("contents")
        return {
            fk["referred_table"]
            for fk in fks
            if "current_published_version_id" in fk["constrained_columns"]
        }

    async with db_engine.connect() as connection:
        targets = await connection.run_sync(_fk_targets)

    assert targets == {"content_versions"}


async def test_situational_images_id_and_entity_id_are_distinct_columns(
    db_engine: AsyncEngine,
) -> None:
    def _column_names(sync_conn: Connection) -> set[str]:
        return {col["name"] for col in sa.inspect(sync_conn).get_columns("situational_images")}

    async with db_engine.connect() as connection:
        columns = await connection.run_sync(_column_names)

    assert {"id", "entity_id", "order"} <= columns


async def test_stat_defs_fk_points_to_starting_setups(db_engine: AsyncEngine) -> None:
    def _fk_targets(sync_conn: Connection) -> set[str]:
        fks = sa.inspect(sync_conn).get_foreign_keys("stat_defs")
        return {fk["referred_table"] for fk in fks if "starting_setup_id" in fk["constrained_columns"]}

    async with db_engine.connect() as connection:
        targets = await connection.run_sync(_fk_targets)

    assert targets == {"starting_setups"}
