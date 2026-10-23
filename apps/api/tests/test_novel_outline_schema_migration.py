"""구성 흐름 스키마(작업 종류 셋·작업 대상 칸·화의 장면 구성안 칸, 표 `novel_outlines`·`novel_episode_outlines`·
`novel_scene_blocks`)의 제약·삭제 경로·옛 이미지 호환·왕복.

CHECK 는 `alembic check` 가 비교하지 않으므로 이 파일의 `IntegrityError` 테스트가 유일한 신호다. 옛 이미지의 삭제는 새 표를 모르는
원시 SQL 로 흉내 낸다. downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
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
    Novel,
    NovelChapter,
    NovelChapterPublication,
    NovelEpisodeOutline,
    NovelJob,
    NovelOutline,
    NovelSceneBlock,
)
from api.db.models.novel import NovelJobKind
from api.novelize.deletion import delete_batch, delete_novels, strip_author_only_data
from factories import NovelTree, _make_novel_tree, _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load_schema_migration() -> ModuleType:
    (path,) = _VERSIONS_DIR.glob("*_novel_outline_schema.py")
    spec = importlib.util.spec_from_file_location("_migration_novel_outline_schema", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_schema_migration()


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _rejects(db: AsyncSession, row: object, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with db.begin_nested():
            db.add(row)
            await db.flush()


def _job(novel_id: uuid.UUID, user_id: uuid.UUID, kind: str, **overrides: object) -> NovelJob:
    values: dict[str, object] = {
        "novel_id": novel_id,
        "user_id": user_id,
        "kind": kind,
        "status": "succeeded",
        "charged_amount": 1,
    }
    values.update(overrides)
    return NovelJob(**values)


async def _tree(db: AsyncSession) -> NovelTree:
    user = _make_user()
    db.add(user)
    await db.flush()
    return await _make_novel_tree(db, user.id)


async def _outline_rows(db: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID) -> uuid.UUID:
    """구성안 한 판, 그 한 화의 장면 구성안, 그 화(`chapter_id`)의 장면 블록 둘. 장면 구성안 id 를 돌려준다."""
    outline = NovelOutline(novel_id=novel_id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[])
    db.add(outline)
    await db.flush()
    episode = NovelEpisodeOutline(
        novel_id=novel_id, outline_id=outline.id, episode_key=uuid.uuid4(), revision=1, source="generate", scenes=[]
    )
    db.add(episode)
    await db.flush()
    db.add_all(
        [
            NovelSceneBlock(block_id=uuid.uuid4(), chapter_id=chapter_id, episode_outline_id=episode.id, scene_id="s1"),
            NovelSceneBlock(block_id=uuid.uuid4(), chapter_id=chapter_id, episode_outline_id=episode.id, scene_id="s2"),
        ]
    )
    await db.execute(sa.update(NovelChapter).where(NovelChapter.id == chapter_id).values(episode_outline_id=episode.id))
    await db.flush()
    return episode.id


async def _left(db: AsyncSession, novel_id: uuid.UUID) -> tuple[int, int, int]:
    async def count(statement: sa.Select[tuple[int]]) -> int:
        return int(await db.scalar(statement) or 0)

    return (
        await count(sa.select(sa.func.count()).select_from(NovelOutline).where(NovelOutline.novel_id == novel_id)),
        await count(
            sa.select(sa.func.count()).select_from(NovelEpisodeOutline).where(NovelEpisodeOutline.novel_id == novel_id)
        ),
        await count(
            sa.select(sa.func.count())
            .select_from(NovelSceneBlock)
            .join(NovelEpisodeOutline, NovelEpisodeOutline.id == NovelSceneBlock.episode_outline_id)
            .where(NovelEpisodeOutline.novel_id == novel_id)
        ),
    )


# ── 제약 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind", ["outline_generate", "episode_outline_generate", "outline_chapter_generate"])
async def test_the_widened_kind_check_takes_the_outline_flow_kinds_with_their_targets(
    db_session: AsyncSession, kind: NovelJobKind
) -> None:
    """작업 종류 CHECK 가 구성 흐름 셋을 받는다(대상 칸이 찬 행). 깨지는 시나리오: 구성안 작업 INSERT 가 CHECK 위반으로 500 이
    되고 차감이 롤백돼 버튼이 영영 안 먹는다."""
    tree = await _tree(db_session)

    db_session.add(
        _job(
            tree.novel.id,
            tree.novel.user_id,
            kind,
            outline_id=uuid.uuid4(),
            outline_episode_key=uuid.uuid4(),
            episode_outline_id=uuid.uuid4(),
        )
    )
    await db_session.flush()


async def test_the_kind_check_still_rejects_an_unknown_kind(db_session: AsyncSession) -> None:
    """넓힌 목록도 목록이다 — 모르는 종류는 거절한다. 깨지는 시나리오: CHECK 를 지우고 다시 걸지 않아 오타 종류가 저장되고,
    응답 검증이 그 행을 읽을 때마다 500 이 된다."""
    tree = await _tree(db_session)

    await _rejects(db_session, _job(tree.novel.id, tree.novel.user_id, "outline_regenerate"), "ck_novel_jobs_kind")


@pytest.mark.parametrize(
    ("kind", "missing"),
    [
        pytest.param("episode_outline_generate", "outline_id", id="scene-outline-without-outline"),
        pytest.param("episode_outline_generate", "outline_episode_key", id="scene-outline-without-episode"),
        pytest.param("outline_chapter_generate", "episode_outline_id", id="manuscript-without-scene-outline"),
        pytest.param("outline_chapter_generate", "outline_episode_key", id="manuscript-without-episode"),
    ],
)
async def test_an_outline_flow_job_must_carry_its_target(db_session: AsyncSession, kind: str, missing: str) -> None:
    """장면 구성안 작업은 구성안·화 키를, 원고는 장면 구성안 리비전·화 키를 갖는다. 옛 종류는 대상 칸 없이 들어간다. 깨지는
    시나리오: 대상 칸이 빈 원고가 저장돼 하루 상한·중복 확인이 NULL 비교로 조용히 통과한다."""
    tree = await _tree(db_session)
    targets: dict[str, object] = {
        "outline_id": uuid.uuid4(),
        "outline_episode_key": uuid.uuid4(),
        "episode_outline_id": uuid.uuid4(),
    }
    targets[missing] = None

    await _rejects(db_session, _job(tree.novel.id, tree.novel.user_id, kind, **targets), "ck_novel_jobs_outline_target")
    db_session.add(_job(tree.novel.id, tree.novel.user_id, "chapter_generate"))
    await db_session.flush()


async def test_outline_revisions_are_positive_unique_and_generate_or_edit(db_session: AsyncSession) -> None:
    """구성안 리비전은 소설마다, 장면 구성안 리비전은 소설·화 키마다 1부터 한 번씩이고, 출처는 생성·편집 둘이다. 같은 화 키라도
    다른 소설이면 겹쳐도 된다. 깨지는 시나리오: 두 탭이 같은 다음 리비전을 동시에 저장해 둘 다 남거나, 모르는 출처가 저장돼
    화면이 그 판을 그리지 못한다."""
    tree = await _tree(db_session)
    other = await _tree(db_session)
    novel_id = tree.novel.id
    outline = NovelOutline(novel_id=novel_id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[])
    db_session.add(outline)
    await db_session.flush()
    key = uuid.uuid4()

    def outline_row(**overrides: object) -> NovelOutline:
        values: dict[str, object] = {"novel_id": novel_id, "revision": 2, "source": "edit", "selection_id": uuid.uuid4()}
        values.update(overrides)
        return NovelOutline(episodes=[], **values)

    def episode_row(**overrides: object) -> NovelEpisodeOutline:
        values: dict[str, object] = {
            "novel_id": novel_id,
            "outline_id": outline.id,
            "episode_key": key,
            "revision": 1,
            "source": "generate",
        }
        values.update(overrides)
        return NovelEpisodeOutline(scenes=[], **values)

    await _rejects(db_session, outline_row(revision=1), "ux_novel_outlines_novel_id_revision")
    await _rejects(db_session, outline_row(revision=0), "ck_novel_outlines_revision_positive")
    await _rejects(db_session, outline_row(source="regenerate"), "ck_novel_outlines_source")
    db_session.add(episode_row())
    await db_session.flush()
    await _rejects(db_session, episode_row(), "ux_novel_episode_outlines_novel_id_episode_key_revision")
    await _rejects(db_session, episode_row(revision=0), "ck_novel_episode_outlines_revision_positive")
    await _rejects(db_session, episode_row(revision=2, source="manual"), "ck_novel_episode_outlines_source")
    other_outline = NovelOutline(
        novel_id=other.novel.id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[]
    )
    db_session.add(other_outline)
    await db_session.flush()
    db_session.add(episode_row(novel_id=other.novel.id, outline_id=other_outline.id))
    await db_session.flush()


# ── 지우는 길 ───────────────────────────────────────────────────────────────
async def test_deleting_a_novel_takes_its_outlines_scene_outlines_and_scene_blocks(db_session: AsyncSession) -> None:
    """소설 삭제·탈퇴의 한 길(`delete_novels`)이 구성안·장면 구성안·장면 블록을 지운다. 깨지는 시나리오: 소설은 사라졌는데 값을
    치른 구성안이 남는다(작가 전용 데이터의 수명 = 소설)."""
    tree = await _tree(db_session)
    await _outline_rows(db_session, tree.novel.id, tree.chapter.id)

    await delete_novels(db_session, [tree.novel.id], freed_storage_keys=[])

    assert await _left(db_session, tree.novel.id) == (0, 0, 0)


async def test_the_old_image_delete_order_still_takes_the_outline_rows(db_session: AsyncSession) -> None:
    """새 표를 모르는 옛 이미지의 소설 삭제는 작업 → 개정 → 화 → 소설 순서의 원시 DELETE 만 낸다. 화·소설·구성안 FK 가 CASCADE
    라 그 DELETE 가 장면 블록·장면 구성안·구성안을 함께 지운다. 깨지는 시나리오: 배포 겹침이나 이미지 롤백 동안 옛 이미지의 소설
    삭제·탈퇴·마지막 묶음 삭제가 FK 위반으로 500 이 된다."""
    tree = await _tree(db_session)
    novel_id = tree.novel.id
    await _outline_rows(db_session, novel_id, tree.chapter.id)
    connection = await db_session.connection()

    await connection.execute(sa.text("DELETE FROM novel_jobs WHERE novel_id = :id"), {"id": novel_id})
    await connection.execute(
        sa.text(
            "DELETE FROM novel_chapter_revisions WHERE chapter_id IN (SELECT id FROM novel_chapters WHERE novel_id = :id)"
        ),
        {"id": novel_id},
    )
    await connection.execute(sa.text("DELETE FROM novel_chapters WHERE novel_id = :id"), {"id": novel_id})
    blocks_after_chapters = (await _left(db_session, novel_id))[2]
    await connection.execute(sa.text("DELETE FROM novels WHERE id = :id"), {"id": novel_id})

    assert blocks_after_chapters == 0
    assert await _left(db_session, novel_id) == (0, 0, 0)


async def test_deleting_the_last_batch_takes_its_chapters_scene_blocks(db_session: AsyncSession) -> None:
    """마지막 묶음 삭제(`delete_batch`)는 그 화의 장면 블록을 지우고 구성안·장면 구성안은 남긴다 — 화를 지운 뒤 같은 장면
    구성안으로 다시 원고를 쓸 수 있다. 깨지는 시나리오: 화가 사라졌는데 장면 블록이 남거나(새 코드는 cascade 에 기대지 않는다),
    구성안까지 지워 다시 사야 한다."""
    tree = await _tree(db_session)
    await _outline_rows(db_session, tree.novel.id, tree.chapter.id)

    await delete_batch(db_session, novel_id=tree.novel.id, batch_id=tree.batch.id, freed_storage_keys=[])

    assert await _left(db_session, tree.novel.id) == (1, 1, 0)


async def test_stripping_a_withdrawn_authors_kept_novel_takes_the_outlines_but_keeps_the_chapters_readers_read(
    db_session: AsyncSession,
) -> None:
    """판매돼 숨겨 남긴 소설의 작가 전용 데이터 정리가 구성안·장면 구성안·남는 화의 장면 블록을 지우고, 공개된 화는 그대로 둔다
    (화가 장면 구성안을 FK 없이 가리켜 정리가 막히지 않는다). 다시 불러도 바꿀 것이 없다. 깨지는 시나리오: 소설 행이 남아
    CASCADE 가 걸리지 않으니 탈퇴한 작가의 구성안이 보유 기한 없이 남거나, 화 → 장면 구성안 FK 때문에 탈퇴가 500 이 된다."""
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id, batches=(2,))
    await _outline_rows(db_session, novel.novel_id, novel.chapter_ids[0])

    changed = await strip_author_only_data(db_session, [novel.novel_id], freed_storage_keys=[])
    again = await strip_author_only_data(db_session, [novel.novel_id], freed_storage_keys=[])
    published = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(NovelChapterPublication)
        .where(NovelChapterPublication.novel_id == novel.novel_id)
    )
    chapters = await db_session.scalar(
        sa.select(sa.func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel.novel_id)
    )

    assert await _left(db_session, novel.novel_id) == (0, 0, 0)
    assert changed > 0 and again == 0
    assert (published, chapters) == (2, 2)
    assert await db_session.get(Novel, novel.novel_id) is not None


# ── 왕복 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("leftover", ["outline_job", "outline"])
async def test_downgrade_refuses_while_outline_flow_rows_exist_and_round_trips_on_an_empty_schema(
    ddl_engine: AsyncEngine, leftover: str
) -> None:
    """구성 흐름 작업 행이나 구성안(장면 구성안·장면 블록과 함께) 행이 하나라도 있으면 downgrade 가 아무것도 바꾸기 전에 멈추고, 지운 뒤에는 내렸다
    올려도 표·칸·넓힌 CHECK 가 돌아온다. 내린 사이에는 옛 CHECK 가 구성 흐름 종류를 다시 거절한다. 깨지는 시나리오: downgrade 가
    값을 치른 구성안과 그 차감 기록을 조용히 지우거나, 좁힌 CHECK 를 걸다 실패해 반쯤 내린 스키마가 남는다."""

    async def tables(connection: AsyncConnection) -> set[str]:
        rows = await connection.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN"
                " ('novel_outlines', 'novel_episode_outlines', 'novel_scene_blocks')"
            )
        )
        return set(rows.scalars().all())

    async def kind_check(connection: AsyncConnection) -> str:
        return str(
            await connection.scalar(
                sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_novel_jobs_kind'")
            )
        )

    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            tree = await _tree(session)
            if leftover == "outline_job":
                session.add(_job(tree.novel.id, tree.novel.user_id, "outline_generate"))
                await session.flush()
            else:
                await _outline_rows(session, tree.novel.id, tree.chapter.id)

            with pytest.raises(RuntimeError, match="남아 있다"):
                async with connection.begin_nested():
                    await _run(connection, _M.downgrade)
            still = await tables(connection)
            await connection.execute(sa.text("DELETE FROM novel_jobs WHERE kind = 'outline_generate'"))
            await connection.execute(sa.text("DELETE FROM novel_outlines"))
            await _run(connection, _M.downgrade)
            after_down = (await tables(connection), await kind_check(connection))
            await _run(connection, _M.upgrade)
            after_up = (await tables(connection), await kind_check(connection))
        finally:
            await transaction.rollback()

    expected = {"novel_outlines", "novel_episode_outlines", "novel_scene_blocks"}
    assert still == expected
    assert after_down[0] == set() and "outline_generate" not in after_down[1]
    assert after_up[0] == expected and "outline_chapter_generate" in after_up[1]
