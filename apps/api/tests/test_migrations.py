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
        "keyword_notes",
        "shortcuts",
        "endings",
        "ending_rule_groups",
        "ending_rules",
        "chat_rooms",
        "chat_messages",
        "chat_room_stats",
        "story_ending_unlocks",
        "character_image_exposures",
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


async def test_ending_rule_groups_has_no_self_referential_fk(db_engine: AsyncEngine) -> None:
    """techspec-db-schema.md §5: groups allow only one level of nesting (no group-in-group)."""

    def _fk_targets(sync_conn: Connection) -> set[str]:
        fks = sa.inspect(sync_conn).get_foreign_keys("ending_rule_groups")
        return {fk["referred_table"] for fk in fks}

    async with db_engine.connect() as connection:
        targets = await connection.run_sync(_fk_targets)

    assert "ending_rule_groups" not in targets


async def test_ending_rules_has_exactly_one_parent_check_constraint(db_engine: AsyncEngine) -> None:
    def _check_constraint_names(sync_conn: Connection) -> set[str]:
        checks = sa.inspect(sync_conn).get_check_constraints("ending_rules")
        return {c["name"] for c in checks if c["name"] is not None}

    async with db_engine.connect() as connection:
        names = await connection.run_sync(_check_constraint_names)

    assert "ck_ending_rules_exactly_one_parent" in names


async def test_chat_room_stats_composite_pk(db_engine: AsyncEngine) -> None:
    def _pk_columns(sync_conn: Connection) -> set[str]:
        pk = sa.inspect(sync_conn).get_pk_constraint("chat_room_stats")
        return set(pk["constrained_columns"])

    async with db_engine.connect() as connection:
        columns = await connection.run_sync(_pk_columns)

    assert columns == {"chat_room_id", "stat_entity_id"}


async def test_story_ending_unlocks_composite_pk(db_engine: AsyncEngine) -> None:
    def _pk_columns(sync_conn: Connection) -> set[str]:
        pk = sa.inspect(sync_conn).get_pk_constraint("story_ending_unlocks")
        return set(pk["constrained_columns"])

    async with db_engine.connect() as connection:
        columns = await connection.run_sync(_pk_columns)

    assert columns == {"user_id", "starting_setup_entity_id", "ending_entity_id"}


async def test_character_image_exposures_composite_pk(db_engine: AsyncEngine) -> None:
    def _pk_columns(sync_conn: Connection) -> set[str]:
        pk = sa.inspect(sync_conn).get_pk_constraint("character_image_exposures")
        return set(pk["constrained_columns"])

    async with db_engine.connect() as connection:
        columns = await connection.run_sync(_pk_columns)

    assert columns == {"user_id", "content_id", "image_entity_id"}
