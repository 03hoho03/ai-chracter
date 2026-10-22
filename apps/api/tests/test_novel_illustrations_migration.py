"""삽화 스키마 마이그레이션(`b871b88d2a90`)의 제약·옛 이미지 호환·왕복.

세션 스코프 스키마가 이미 `upgrade head` 를 했다. 옛 이미지의 쓰기는 새 칸·새 표를 모르는 원시 SQL 로 흉내 낸다. CHECK·부분
유니크·복합 PK 는 `alembic check` 가 비교하지 않으므로 이 파일의 `IntegrityError` 테스트가 유일한 신호다. downgrade·upgrade 를
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

from api.db.models import (
    AssetKind,
    AssetStatus,
    NovelChapterIllustration,
    NovelIllustrationScreenPass,
    NovelScreening,
)
from api.novelize.blocks import build_revision, copied_ids
from factories import NovelTree, _make_asset, _make_novel_tree, _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("b871b88d2a90")


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _tree_and_asset(db: AsyncSession) -> tuple[NovelTree, uuid.UUID]:
    user = _make_user()
    db.add(user)
    await db.flush()
    tree = await _make_novel_tree(db, user.id)
    asset = await _make_asset(db, user.id, kind=AssetKind.GENERATED, status=AssetStatus.READY)
    return tree, asset.id


def _placement(revision_id: uuid.UUID, asset_id: uuid.UUID, **overrides: object) -> NovelChapterIllustration:
    values: dict[str, object] = {
        "revision_id": revision_id,
        "anchor_block_id": uuid.uuid4(),
        "placement": "after",
        "sort_order": 0,
        "asset_id": asset_id,
        "source": "generated",
    }
    values.update(overrides)
    return NovelChapterIllustration(**values)


async def _rejects(db: AsyncSession, row: object, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with db.begin_nested():
            db.add(row)
            await db.flush()


# ── 제약 ────────────────────────────────────────────────────────────────────
async def test_a_placement_names_a_side_and_a_source_and_a_slot_order(db_session: AsyncSession) -> None:
    """앞/뒤·출처는 정해진 값만, 순서는 0 이상만 받는다. 경계: 순서 0 은 통과. 깨지는 시나리오: 화면이 모르는 자리·출처 값이나
    음수 순서가 저장돼 읽기 응답이 검증에서 500 이 되거나 그림 순서가 뒤집힌다."""
    tree, asset_id = await _tree_and_asset(db_session)
    db_session.add(_placement(tree.first_revision.id, asset_id))
    await db_session.flush()

    await _rejects(db_session, _placement(tree.first_revision.id, asset_id, placement="inside"), "ck_novel_chapter_illustrations_placement")
    await _rejects(db_session, _placement(tree.first_revision.id, asset_id, source="ai"), "ck_novel_chapter_illustrations_source")
    await _rejects(
        db_session,
        _placement(tree.first_revision.id, asset_id, sort_order=-1),
        "ck_novel_chapter_illustrations_sort_order_nonnegative",
    )


async def test_an_anchor_and_its_side_are_both_set_or_both_empty(db_session: AsyncSession) -> None:
    """둘 다 빈 행(위치 확인 필요)은 받고, 한쪽만 빈 행은 거부한다. 깨지는 시나리오: 앵커 없이 앞/뒤만 있는 행이 생겨 읽기가
    그림을 놓을 문단을 찾지 못하거나, 위치 확인 필요 목록에서 빠진다."""
    tree, asset_id = await _tree_and_asset(db_session)
    db_session.add(_placement(tree.first_revision.id, asset_id, anchor_block_id=None, placement=None))
    await db_session.flush()

    await _rejects(
        db_session,
        _placement(tree.first_revision.id, asset_id, anchor_block_id=None),
        "ck_novel_chapter_illustrations_anchor_pair",
    )
    await _rejects(
        db_session, _placement(tree.first_revision.id, asset_id, placement=None), "ck_novel_chapter_illustrations_anchor_pair"
    )


async def test_one_slot_holds_one_picture_per_order_but_unplaced_pictures_may_share_order(db_session: AsyncSession) -> None:
    """같은 개정·같은 앵커·같은 쪽·같은 순서는 한 행이다. 위치 확인 필요 행(앵커 없음)끼리는 순서가 같아도 된다. 다른 개정이면
    같은 자리도 따로 가진다. 깨지는 시나리오: 두 요청이 같은 자리 같은 순서에 그림을 넣어 화면 순서가 정해지지 않거나, 앵커를
    잃은 그림 둘이 한 개정으로 이어지지 못해 승계가 500 이 된다."""
    tree, asset_id = await _tree_and_asset(db_session)
    anchor = uuid.uuid4()
    db_session.add_all(
        [
            _placement(tree.first_revision.id, asset_id, anchor_block_id=anchor),
            _placement(tree.reverting_revision.id, asset_id, anchor_block_id=anchor),
            _placement(tree.first_revision.id, asset_id, anchor_block_id=None, placement=None),
            _placement(tree.first_revision.id, asset_id, anchor_block_id=None, placement=None),
        ]
    )
    await db_session.flush()

    await _rejects(
        db_session, _placement(tree.first_revision.id, asset_id, anchor_block_id=anchor), "ux_novel_chapter_illustrations_slot"
    )


async def test_a_pass_is_remembered_once_per_bytes_model_and_prompt_version(db_session: AsyncSession) -> None:
    """통과 기억의 키는 바이트 sha·모델·문안 판 셋이다 — 하나만 달라도 따로 쌓이고, 셋이 같으면 거부한다. 깨지는 시나리오: 문안
    판이 키에서 빠져 새 문안으로 심사해야 할 그림이 옛 통과 기억에 걸려 건너뛰거나, 같은 기억이 겹쳐 쌓인다."""
    sha = "a" * 64
    db_session.add_all(
        [
            NovelIllustrationScreenPass(content_sha256=sha, model="m1", prompt_version="v1"),
            NovelIllustrationScreenPass(content_sha256=sha, model="m2", prompt_version="v1"),
            NovelIllustrationScreenPass(content_sha256=sha, model="m1", prompt_version="v2"),
        ]
    )
    await db_session.flush()

    await _rejects(
        db_session,
        NovelIllustrationScreenPass(content_sha256=sha, model="m1", prompt_version="v1"),
        "novel_illustration_screen_passes_pkey",
    )


async def test_revisions_and_screenings_take_the_illustration_value(db_session: AsyncSession) -> None:
    """넓힌 두 CHECK 가 `illustration` 을 받고, 여전히 모르는 값은 거부한다. 깨지는 시나리오: 배치 변경 개정이나 삽화 거부 기록을
    쓰는 순간 CHECK 위반 500 이 되거나, CHECK 가 통째로 풀려 아무 값이나 저장된다."""
    tree, _asset_id = await _tree_and_asset(db_session)
    revision = build_revision(
        chapter_id=tree.chapter.id,
        revision_no=3,
        body=tree.first_revision.body,
        source="illustration",
        block_ids=copied_ids(tree.first_revision),
    )
    db_session.add(revision)
    db_session.add(
        NovelScreening(
            novel_id=tree.novel.id,
            user_id=tree.novel.user_id,
            outcome="rejected",
            flagged_parts=["illustration"],
            model="m",
        )
    )
    await db_session.flush()

    with pytest.raises(IntegrityError, match="ck_novel_chapter_revisions_source"):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.text("UPDATE novel_chapter_revisions SET source = 'drawing' WHERE id = :id"), {"id": revision.id}
            )
    with pytest.raises(IntegrityError, match="ck_novel_screenings_flagged_parts"):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.text("UPDATE novel_screenings SET flagged_parts = '{picture}' WHERE novel_id = :id"), {"id": tree.novel.id}
            )


# ── 옛 이미지 호환 ──────────────────────────────────────────────────────────
async def test_old_image_writes_leave_the_screened_marks_empty_and_its_revision_delete_takes_the_placements(
    db_session: AsyncSession,
) -> None:
    """두 칸을 모르는 옛 이미지의 공개본·판 INSERT 는 삽화 심사 시각을 비워 두고, 배치 표를 모르는 옛 이미지의 개정 DELETE 는
    배치 행을 함께 지운다. 깨지는 시나리오: 겹침 동안 옛 이미지가 얼린 공개본이 심사한 것으로 보여 그림이 독자에게 나가거나, 옛
    이미지의 소설·묶음 삭제가 배치 FK 위반 500 이 된다."""
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id, batches=(1,))
    connection = await db_session.connection()
    chapter_id = novel.chapter_ids[0]
    revision_id, ordinal = (
        await connection.execute(
            sa.text("SELECT revision_id, ordinal FROM novel_chapter_publications WHERE chapter_id = :id"), {"id": chapter_id}
        )
    ).one()
    await connection.execute(sa.text("DELETE FROM novel_chapter_editions WHERE chapter_id = :id"), {"id": chapter_id})
    await connection.execute(sa.text("DELETE FROM novel_chapter_publications WHERE chapter_id = :id"), {"id": chapter_id})
    await connection.execute(
        sa.text(
            "INSERT INTO novel_chapter_publications (chapter_id, novel_id, ordinal, revision_id)"
            " VALUES (:chapter, :novel, :ordinal, :revision)"
        ),
        {"chapter": chapter_id, "novel": novel.novel_id, "ordinal": ordinal, "revision": revision_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO novel_chapter_editions (chapter_id, edition, novel_id, revision_id)"
            " VALUES (:chapter, 1, :novel, :revision)"
        ),
        {"chapter": chapter_id, "novel": novel.novel_id, "revision": revision_id},
    )
    marks = (
        await connection.execute(
            sa.text(
                "SELECT p.illustrations_screened_at, e.illustrations_screened_at FROM novel_chapter_publications p"
                " JOIN novel_chapter_editions e ON e.chapter_id = p.chapter_id WHERE p.chapter_id = :id"
            ),
            {"id": chapter_id},
        )
    ).one()
    asset = await _make_asset(db_session, publisher.id, kind=AssetKind.GENERATED, status=AssetStatus.READY)
    db_session.add(_placement(revision_id, asset.id))
    await db_session.flush()

    await connection.execute(sa.text("DELETE FROM novel_chapter_publications WHERE chapter_id = :id"), {"id": chapter_id})
    await connection.execute(sa.text("DELETE FROM novel_chapter_editions WHERE chapter_id = :id"), {"id": chapter_id})
    await connection.execute(sa.text("DELETE FROM novel_chapter_revisions WHERE id = :id"), {"id": revision_id})
    left = (
        await connection.execute(
            sa.text("SELECT count(*) FROM novel_chapter_illustrations WHERE revision_id = :id"), {"id": revision_id}
        )
    ).scalar_one()

    assert tuple(marks) == (None, None)
    assert left == 0


# ── 왕복 ────────────────────────────────────────────────────────────────────
async def test_downgrade_refuses_while_a_placement_exists_and_round_trips_on_an_empty_schema(ddl_engine: AsyncEngine) -> None:
    """배치 행이 하나라도 있으면 downgrade 가 아무것도 바꾸기 전에 멈추고, 지운 뒤에는 내렸다 올려도 새 표·칸이 돌아온다.
    깨지는 시나리오: downgrade 가 작가의 삽화를 조용히 지우거나, 옛 스키마와 어긋난 채 남는다."""

    async def tables(connection: AsyncConnection) -> set[str]:
        rows = await connection.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN"
                " ('novel_chapter_illustrations', 'novel_illustration_screen_passes', 'novel_illustration_takedowns')"
            )
        )
        return set(rows.scalars().all())

    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            tree, asset_id = await _tree_and_asset(session)
            session.add(_placement(tree.first_revision.id, asset_id))
            await session.flush()

            with pytest.raises(RuntimeError, match="배치 행 1행"):
                async with connection.begin_nested():
                    await _run(connection, _M.downgrade)
            still = await tables(connection)
            await connection.execute(sa.text("DELETE FROM novel_chapter_illustrations"))
            await _run(connection, _M.downgrade)
            after_down = await tables(connection)
            await _run(connection, _M.upgrade)
            after_up = await tables(connection)
        finally:
            await transaction.rollback()

    expected = {"novel_chapter_illustrations", "novel_illustration_screen_passes", "novel_illustration_takedowns"}
    assert still == expected
    assert after_down == set()
    assert after_up == expected
