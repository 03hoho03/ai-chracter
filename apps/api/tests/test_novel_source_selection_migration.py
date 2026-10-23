"""구간 선택 스키마(`novel_source_selections`·`novel_source_sections`)의 제약·삭제 경로·옛 이미지 호환·왕복.

구간 선택은 사용자가 소설로 옮길 대화 구간을 고른 기록이다 — 고정한 방 끝 키 하나와, 소설에 넣을(include)·참고로만 보낼(context)
구간 행들(양 끝 메시지 키·AI 응답 수·원문 해시). 고르지 않은 나머지가 뺄(exclude) 구간이라 행으로 두지 않는다. 원문 사본은 없다.

CHECK·부분 유니크는 `alembic check` 가 비교하지 않으므로 이 파일의 `IntegrityError` 테스트가 유일한 신호다. 옛 이미지의 삭제는 새
표를 모르는 원시 SQL 로 흉내 낸다. downgrade·upgrade 를 실제로 돌리는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서 돌린다."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import Novel, NovelChapter, NovelChapterPublication, NovelSourceSection, NovelSourceSelection
from api.novelize.deletion import delete_novels, strip_author_only_data
from factories import _make_novel_tree, _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_BASE = datetime(2026, 10, 1, tzinfo=UTC)


def _load_selection_migration() -> ModuleType:
    (path,) = _VERSIONS_DIR.glob("*_novel_source_selections.py")
    spec = importlib.util.spec_from_file_location("_migration_novel_source_selections", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_selection_migration()


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


def _selection(novel_id: uuid.UUID, **overrides: object) -> NovelSourceSelection:
    values: dict[str, object] = {
        "novel_id": novel_id,
        "revision": 1,
        "room_end_message_id": uuid.uuid4(),
        "room_end_message_created_at": _BASE + timedelta(hours=1),
    }
    values.update(overrides)
    return NovelSourceSelection(**values)


def _section(selection_id: uuid.UUID, **overrides: object) -> NovelSourceSection:
    values: dict[str, object] = {
        "selection_id": selection_id,
        "mode": "include",
        "start_message_id": uuid.UUID(int=1),
        "start_message_created_at": _BASE,
        "end_message_id": uuid.UUID(int=2),
        "end_message_created_at": _BASE + timedelta(minutes=1),
        "assistant_message_count": 1,
        "source_hash": "0" * 64,
    }
    values.update(overrides)
    return NovelSourceSection(**values)


async def _rejects(db: AsyncSession, row: object, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with db.begin_nested():
            db.add(row)
            await db.flush()


async def _novel_with_selection(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """소설 하나(화·묶음·작업이 있는 나무)와 그 소설의 구간 선택 하나(include·context 구간 둘). (소설 id, 선택 id)."""
    user = _make_user()
    db.add(user)
    await db.flush()
    tree = await _make_novel_tree(db, user.id)
    selection = _selection(tree.novel.id)
    db.add(selection)
    await db.flush()
    db.add_all(
        [
            _section(selection.id),
            _section(
                selection.id,
                mode="context",
                start_message_created_at=_BASE + timedelta(minutes=2),
                end_message_created_at=_BASE + timedelta(minutes=3),
            ),
        ]
    )
    await db.flush()
    return tree.novel.id, selection.id


async def _left(db: AsyncSession, novel_id: uuid.UUID, selection_id: uuid.UUID) -> tuple[int, int]:
    selections = await db.scalar(
        sa.select(sa.func.count()).select_from(NovelSourceSelection).where(NovelSourceSelection.novel_id == novel_id)
    )
    sections = await db.scalar(
        sa.select(sa.func.count()).select_from(NovelSourceSection).where(NovelSourceSection.selection_id == selection_id)
    )
    return int(selections or 0), int(sections or 0)


# ── 제약 ────────────────────────────────────────────────────────────────────
async def test_a_section_is_include_or_context_with_its_start_not_after_its_end(db_session: AsyncSession) -> None:
    """구간은 include·context 둘 중 하나이고(exclude 는 행이 아니다), 시작 키가 끝 키보다 뒤일 수 없으며(같은 메시지 하나짜리
    구간은 받는다 — 시각이 같으면 id 로 가른다), AI 응답 수는 0 이상이다. 깨지는 시나리오: exclude 행이나 뒤집힌 구간이 저장돼
    관문이 빈 구간을 읽고 해시가 늘 어긋나거나, 화면이 모르는 값으로 응답 검증이 500 이 된다."""
    _, selection_id = await _novel_with_selection(db_session)
    same = uuid.UUID(int=7)
    db_session.add(
        _section(
            selection_id,
            start_message_id=same,
            end_message_id=same,
            start_message_created_at=_BASE + timedelta(minutes=5),
            end_message_created_at=_BASE + timedelta(minutes=5),
            assistant_message_count=0,
        )
    )
    await db_session.flush()

    fresh = {"start_message_created_at": _BASE + timedelta(minutes=6), "end_message_created_at": _BASE + timedelta(minutes=7)}
    await _rejects(db_session, _section(selection_id, mode="exclude", **fresh), "ck_novel_source_sections_mode")
    await _rejects(
        db_session,
        _section(selection_id, start_message_created_at=_BASE + timedelta(minutes=9), end_message_created_at=_BASE),
        "ck_novel_source_sections_key_order",
    )
    await _rejects(
        db_session,
        _section(
            selection_id,
            start_message_created_at=_BASE + timedelta(minutes=8),
            end_message_created_at=_BASE + timedelta(minutes=8),
            start_message_id=uuid.UUID(int=9),
            end_message_id=uuid.UUID(int=8),
        ),
        "ck_novel_source_sections_key_order",
    )
    await _rejects(
        db_session,
        _section(selection_id, assistant_message_count=-1, **fresh),
        "ck_novel_source_sections_assistant_message_count",
    )


async def test_a_selection_revision_is_positive_and_unique_per_novel_and_a_start_key_once_per_selection(
    db_session: AsyncSession,
) -> None:
    """리비전은 1 이상이고 소설마다 한 번, 한 선택 안에서 같은 시작 키의 구간은 하나다. 다른 소설은 같은 리비전 번호를 쓴다.
    깨지는 시나리오: 두 탭이 같은 다음 리비전을 동시에 저장해 둘 다 남거나, 같은 구간이 두 번 실려 원문이 겹쳐 간다."""
    novel_id, selection_id = await _novel_with_selection(db_session)
    other_novel_id, _ = await _novel_with_selection(db_session)
    db_session.add(_selection(novel_id, revision=2))
    await db_session.flush()

    await _rejects(db_session, _selection(novel_id, revision=2), "ux_novel_source_selections_novel_id_revision")
    await _rejects(db_session, _selection(novel_id, revision=0), "ck_novel_source_selections_revision_positive")
    await _rejects(db_session, _section(selection_id, mode="context"), "ux_novel_source_sections_selection_id_start")
    db_session.add(_selection(other_novel_id, revision=2))
    await db_session.flush()


# ── 지우는 길 ───────────────────────────────────────────────────────────────
async def test_deleting_a_novel_takes_its_selections_and_sections(db_session: AsyncSession) -> None:
    """소설 삭제·탈퇴의 한 길(`delete_novels`)이 구간 선택과 구간을 지운다. 깨지는 시나리오: 소설은 사라졌는데 사용자가 고른 대화
    구간 기록이 남는다(작가 전용 데이터의 수명 = 소설)."""
    novel_id, selection_id = await _novel_with_selection(db_session)

    await delete_novels(db_session, [novel_id], freed_storage_keys=[])

    assert await _left(db_session, novel_id, selection_id) == (0, 0)


async def test_the_old_image_delete_order_still_takes_the_selections(db_session: AsyncSession) -> None:
    """새 표를 모르는 옛 이미지의 소설 삭제는 작업 → 개정 → 화 → 소설 순서의 원시 DELETE 만 낸다. 소설 FK 와 선택 FK 가 CASCADE
    라 그 마지막 DELETE 가 선택·구간을 함께 지운다. 깨지는 시나리오: 배포 겹침이나 이미지 롤백 동안 옛 이미지의 소설 삭제·탈퇴가
    FK 위반으로 500 이 된다."""
    novel_id, selection_id = await _novel_with_selection(db_session)
    connection = await db_session.connection()

    await connection.execute(sa.text("DELETE FROM novel_jobs WHERE novel_id = :id"), {"id": novel_id})
    await connection.execute(
        sa.text(
            "DELETE FROM novel_chapter_revisions WHERE chapter_id IN (SELECT id FROM novel_chapters WHERE novel_id = :id)"
        ),
        {"id": novel_id},
    )
    await connection.execute(sa.text("DELETE FROM novel_chapters WHERE novel_id = :id"), {"id": novel_id})
    await connection.execute(sa.text("DELETE FROM novels WHERE id = :id"), {"id": novel_id})

    assert await _left(db_session, novel_id, selection_id) == (0, 0)


async def test_stripping_a_withdrawn_authors_kept_novel_takes_the_selections_but_keeps_what_readers_read(
    db_session: AsyncSession,
) -> None:
    """판매돼 숨겨 남긴 소설의 작가 전용 데이터 정리가 구간 선택을 지우고(바꾼 행으로 센다), 공개된 화는 그대로 둔다. 다시 불러도
    바꿀 것이 없다. 깨지는 시나리오: 소설 행이 남아 CASCADE 가 걸리지 않으니, 정리가 이 표를 모르면 탈퇴한 작가가 고른 대화 구간
    기록이 보유 기한 없이 남는다."""
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id, batches=(2,))
    selection = _selection(novel.novel_id)
    db_session.add(selection)
    await db_session.flush()
    db_session.add(_section(selection.id))
    await db_session.flush()

    changed = await strip_author_only_data(db_session, [novel.novel_id], freed_storage_keys=[])
    again = await strip_author_only_data(db_session, [novel.novel_id], freed_storage_keys=[])
    published = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(NovelChapterPublication)
        .where(NovelChapterPublication.novel_id == novel.novel_id)
    )

    assert await _left(db_session, novel.novel_id, selection.id) == (0, 0)
    assert changed > 0 and again == 0
    assert published == 2
    assert await db_session.get(Novel, novel.novel_id) is not None
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel.novel_id)) == 2


# ── 왕복 ────────────────────────────────────────────────────────────────────
async def test_downgrade_refuses_while_a_selection_exists_and_round_trips_on_an_empty_schema(
    ddl_engine: AsyncEngine,
) -> None:
    """선택 행이 하나라도 있으면 downgrade 가 아무것도 바꾸기 전에 멈추고, 지운 뒤에는 내렸다 올려도 두 표가 돌아온다. 깨지는
    시나리오: downgrade 가 사용자가 고른 구간(다음 유료 생성의 근거)을 조용히 지우거나, 옛 스키마와 어긋난 채 남는다."""

    async def tables(connection: AsyncConnection) -> set[str]:
        rows = await connection.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN"
                " ('novel_source_selections', 'novel_source_sections')"
            )
        )
        return set(rows.scalars().all())

    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            await _novel_with_selection(session)

            with pytest.raises(RuntimeError, match="구간 선택 1행"):
                async with connection.begin_nested():
                    await _run(connection, _M.downgrade)
            still = await tables(connection)
            await connection.execute(sa.text("DELETE FROM novel_source_selections"))
            await _run(connection, _M.downgrade)
            after_down = await tables(connection)
            await _run(connection, _M.upgrade)
            after_up = await tables(connection)
        finally:
            await transaction.rollback()

    expected = {"novel_source_selections", "novel_source_sections"}
    assert still == expected
    assert after_down == set()
    assert after_up == expected
