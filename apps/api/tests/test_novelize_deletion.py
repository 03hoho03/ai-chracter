import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    HomeNovelCuration,
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelCharacter,
    NovelComment,
    NovelBibleCommit,
    NovelCommentReport,
    NovelJob,
    NovelLike,
    NovelPublication,
    NovelReaderPosition,
    NovelReadingPosition,
    NovelReport,
    NovelScreening,
    NovelSnapshot,
    ReportReasonCategory,
    ReportStatus,
    User,
)
from api.db.session import engine
from api.novelize.deletion import delete_batch, delete_novels, strip_author_only_data
from factories import (
    NovelTree,
    _bible_row_counts,
    _make_novel_tree,
    _make_public_novel,
    _make_user,
    _plant_bible_rows,
    _plant_novel_extras,
)

# 정본 기억 표 열둘. 소설을 지우는 경로가 이 표들까지 비우는지 센다(`_bible_row_counts`).
_BIBLE_TABLES = (
    "novel_bible_commits",
    "novel_bible_jobs",
    "novel_bible_revisions",
    "novel_bible_entities",
    "novel_bible_evidence",
    "novel_bible_expirations",
    "novel_bible_findings",
    "novel_bible_adaptation_candidates",
    "novel_bible_events",
    "novel_bible_event_relations",
    "novel_bible_facts",
    "novel_bible_knowledge",
)


async def _make_owner(db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return user


async def _row_counts(db_session: AsyncSession, novel_id: uuid.UUID) -> dict[str, int]:
    chapter_ids = sa.select(NovelChapter.id).where(NovelChapter.novel_id == novel_id).scalar_subquery()
    queries = {
        "novels": sa.select(sa.func.count()).select_from(Novel).where(Novel.id == novel_id),
        "chapters": sa.select(sa.func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel_id),
        "revisions": sa.select(sa.func.count())
        .select_from(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id.in_(chapter_ids)),
        "jobs": sa.select(sa.func.count()).select_from(NovelJob).where(NovelJob.novel_id == novel_id),
        "batches": sa.select(sa.func.count()).select_from(NovelBatch).where(NovelBatch.novel_id == novel_id),
        "characters": sa.select(sa.func.count()).select_from(NovelCharacter).where(NovelCharacter.novel_id == novel_id),
        "appearances": sa.select(sa.func.count())
        .select_from(NovelChapterCharacter)
        .where(NovelChapterCharacter.chapter_id.in_(chapter_ids)),
        "snapshots": sa.select(sa.func.count()).select_from(NovelSnapshot).where(NovelSnapshot.novel_id == novel_id),
        "positions": sa.select(sa.func.count())
        .select_from(NovelReadingPosition)
        .where(NovelReadingPosition.novel_id == novel_id),
        "publications": sa.select(sa.func.count())
        .select_from(NovelPublication)
        .where(NovelPublication.novel_id == novel_id),
        "chapter_publications": sa.select(sa.func.count())
        .select_from(NovelChapterPublication)
        .where(NovelChapterPublication.novel_id == novel_id),
        "screenings": sa.select(sa.func.count()).select_from(NovelScreening).where(NovelScreening.novel_id == novel_id),
        "reader_positions": sa.select(sa.func.count())
        .select_from(NovelReaderPosition)
        .where(NovelReaderPosition.novel_id == novel_id),
        "likes": sa.select(sa.func.count()).select_from(NovelLike).where(NovelLike.novel_id == novel_id),
        "home_curations": sa.select(sa.func.count())
        .select_from(HomeNovelCuration)
        .where(HomeNovelCuration.novel_id == novel_id),
        "comments": sa.select(sa.func.count()).select_from(NovelComment).where(NovelComment.novel_id == novel_id),
    }
    counts = {name: (await db_session.scalar(query)) or 0 for name, query in queries.items()}
    return {**counts, **await _bible_row_counts(db_session, novel_id)}


_GONE = {
    "novels": 0,
    "chapters": 0,
    "revisions": 0,
    "jobs": 0,
    "batches": 0,
    "characters": 0,
    "appearances": 0,
    "snapshots": 0,
    "positions": 0,
    "publications": 0,
    "chapter_publications": 0,
    "screenings": 0,
    "reader_positions": 0,
    "likes": 0,
    "home_curations": 0,
    "comments": 0,
    **dict.fromkeys(_BIBLE_TABLES, 0),
}


async def test_delete_novels_removes_every_row_under_the_novel(db_session: AsyncSession) -> None:
    """작업이 화·기준 개정·자기가 만든 개정을, 되돌리기 개정이 앞 개정을 가리키는 소설도 묶음·인물·등장 인물·스냅샷·
    읽은 위치·정본 기억까지 한 번에 지워진다 — 순서가 틀리면 FK 위반이다."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)
    await _plant_novel_extras(db_session, tree)

    await delete_novels(db_session, [tree.novel.id], freed_storage_keys=[])

    assert await _row_counts(db_session, tree.novel.id) == _GONE


async def test_old_code_delete_order_still_leaves_no_rows_under_the_novel(db_session: AsyncSession) -> None:
    """이미지만 옛 판으로 되돌린 동안의 소설 삭제·탈퇴는 새 테이블을 모르고 작업 → 개정 → 화 → 소설 네 문장만 낸다. 새
    테이블이 부모를 따라 지워지지 않으면 그 DELETE 가 FK 위반으로 500 이 된다."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)
    await _plant_novel_extras(db_session, tree)
    novel_id = tree.novel.id
    chapter_ids = sa.select(NovelChapter.id).where(NovelChapter.novel_id == novel_id)

    await db_session.execute(sa.delete(NovelJob).where(NovelJob.novel_id == novel_id))
    await db_session.execute(sa.delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id.in_(chapter_ids)))
    await db_session.execute(sa.delete(NovelChapter).where(NovelChapter.novel_id == novel_id))
    await db_session.execute(sa.delete(Novel).where(Novel.id == novel_id))

    assert await _row_counts(db_session, novel_id) == _GONE


async def test_delete_novels_leaves_other_novels_untouched(db_session: AsyncSession) -> None:
    owner = await _make_owner(db_session)
    target = await _make_novel_tree(db_session, owner.id)
    other = await _make_novel_tree(db_session, owner.id)
    await _plant_novel_extras(db_session, other)

    await delete_novels(db_session, [target.novel.id], freed_storage_keys=[])

    assert await _row_counts(db_session, other.novel.id) == {
        "novels": 1,
        "chapters": 1,
        "revisions": 2,
        "jobs": 3,
        "batches": 1,
        "characters": 1,
        "appearances": 1,
        "snapshots": 1,
        "positions": 1,
        "publications": 1,
        "chapter_publications": 1,
        "screenings": 1,
        "reader_positions": 1,
        "likes": 1,
        "home_curations": 1,
        "comments": 1,
        **dict.fromkeys(_BIBLE_TABLES, 1),
    }


async def test_reports_outlive_the_novel_with_their_evidence(db_session: AsyncSession) -> None:
    """소설을 지워도 노벨·노벨 댓글 신고는 남는다 — 대상 칸만 비고 증거 사본은 보유 기간 동안 그대로다. 같은 신고자가 같은
    소설의 화 둘을 신고했어도 지우는 문장이 유니크에 걸리지 않는다(두 행 모두 (NULL, NULL, 신고자) 가 된다)."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)
    await _plant_novel_extras(db_session, tree)
    db_session.add(
        NovelReport(
            reporter_user_id=owner.id,
            publisher_user_id=owner.id,
            novel_id=tree.novel.id,
            reason_category=ReportReasonCategory.OTHER,
            status=ReportStatus.PENDING,
            evidence_title="소설 전체 신고",
        )
    )
    await db_session.flush()

    await delete_novels(db_session, [tree.novel.id], freed_storage_keys=[])

    reports = (
        await db_session.execute(
            sa.select(NovelReport.novel_id, NovelReport.chapter_id, NovelReport.chapter_ordinal, NovelReport.evidence_body)
            .where(NovelReport.publisher_user_id == owner.id)
            .order_by(NovelReport.chapter_ordinal.nulls_last())
        )
    ).all()
    assert [tuple(row) for row in reports] == [(None, None, 1, "신고된 화 본문"), (None, None, None, None)]
    comment_report = (
        await db_session.execute(
            sa.select(NovelCommentReport.comment_id, NovelCommentReport.novel_id, NovelCommentReport.evidence_body).where(
                NovelCommentReport.comment_author_user_id == owner.id
            )
        )
    ).one()
    assert tuple(comment_report) == (None, None, "댓글")


async def _first_revision_id(db_session: AsyncSession, chapter_id: uuid.UUID) -> uuid.UUID:
    revision_id = await db_session.scalar(
        sa.select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id == chapter_id)
    )
    assert revision_id is not None
    return revision_id


async def test_delete_batch_removes_only_the_bible_rows_of_its_chapters(db_session: AsyncSession) -> None:
    """마지막 묶음을 지우면 그 화들에서 나온 정본 기억(확정과 그 리비전에 매달린 항목·근거·만료·검사 결과)이 이력째 사라지고,
    앞 화의 것과 개체는 남는다. 깨지는 시나리오: 지운 화의 사실·사건 요지가 정본 기억에 남거나, 다른 화에도 나오는 개체가 함께
    지워진다."""
    owner = await _make_owner(db_session)
    novel = await _make_public_novel(db_session, owner.id, batches=(1, 1))
    for chapter_id in novel.chapter_ids:
        await _plant_bible_rows(
            db_session,
            novel_id=novel.novel_id,
            chapter_id=chapter_id,
            chapter_revision_id=await _first_revision_id(db_session, chapter_id),
        )

    await delete_batch(db_session, novel_id=novel.novel_id, batch_id=novel.batch_ids[1], freed_storage_keys=[])

    assert await _bible_row_counts(db_session, novel.novel_id) == {
        **dict.fromkeys(_BIBLE_TABLES, 1),
        "novel_bible_entities": 2,
    }
    kept = await db_session.scalars(
        sa.select(NovelBibleCommit.chapter_id).where(NovelBibleCommit.novel_id == novel.novel_id)
    )
    assert list(kept) == [novel.chapter_ids[0]]


async def test_old_code_batch_delete_still_removes_the_bible_rows_of_its_chapters(db_session: AsyncSession) -> None:
    """이미지만 옛 판으로 되돌린 동안의 마지막 묶음 삭제는 정본 기억 표를 모르고 작업의 화 참조를 비운 뒤 개정 → 화만 지운다.
    정본 기억 행이 화·개정을 따라 지워지지 않으면 그 DELETE 가 FK 위반으로 500 이 된다. 개체는 소설에 매달려 남는다."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)
    await _plant_bible_rows(
        db_session, novel_id=tree.novel.id, chapter_id=tree.chapter.id, chapter_revision_id=tree.first_revision.id
    )

    await db_session.execute(
        sa.update(NovelJob)
        .where(NovelJob.chapter_id == tree.chapter.id)
        .values(chapter_id=None, base_revision_id=None, result_revision_id=None)
    )
    await db_session.execute(sa.delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id == tree.chapter.id))
    await db_session.execute(sa.delete(NovelChapter).where(NovelChapter.id == tree.chapter.id))

    assert await _bible_row_counts(db_session, tree.novel.id) == {
        **dict.fromkeys(_BIBLE_TABLES, 0),
        "novel_bible_entities": 1,
    }


async def test_old_code_draft_revision_delete_still_removes_the_bible_rows_confirmed_from_it(
    db_session: AsyncSession,
) -> None:
    """옛 판의 숨긴 소설 정리는 화를 남긴 채 공개되지 않은 개정만 지운다. 그 개정을 확정한 정본 기억이 개정을 따라 지워지지
    않으면 개정 DELETE 가 FK 위반이다 — 화는 남으므로 화 cascade 로는 지워지지 않고 개정 cascade 만이 길이다."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)
    await _plant_bible_rows(
        db_session, novel_id=tree.novel.id, chapter_id=tree.chapter.id, chapter_revision_id=tree.reverting_revision.id
    )

    await db_session.execute(
        sa.delete(NovelChapterRevision).where(NovelChapterRevision.id == tree.reverting_revision.id)
    )

    assert await _bible_row_counts(db_session, tree.novel.id) == {
        **dict.fromkeys(_BIBLE_TABLES, 0),
        "novel_bible_entities": 1,
    }


@contextmanager
def _recorded_statements() -> Iterator[list[str]]:
    """이 블록 안에서 나간 SQL 문을 나간 순서대로 모은다."""
    statements: list[str] = []

    def _record(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        statements.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", _record)


def _first(statements: list[str], prefix: str) -> int | None:
    return next((index for index, statement in enumerate(statements) if statement.startswith(prefix)), None)


_Deleter = Callable[[AsyncSession, NovelTree], Awaitable[object]]


@pytest.mark.parametrize(
    ("delete", "tables"),
    [
        pytest.param(
            lambda db, tree: delete_novels(db, [tree.novel.id], freed_storage_keys=[]),
            _BIBLE_TABLES,
            id="delete-novels",
        ),
        pytest.param(
            lambda db, tree: strip_author_only_data(db, [tree.novel.id], freed_storage_keys=[]),
            _BIBLE_TABLES,
            id="strip-author-only-data",
        ),
        pytest.param(
            lambda db, tree: delete_batch(db, novel_id=tree.novel.id, batch_id=tree.batch.id, freed_storage_keys=[]),
            tuple(table for table in _BIBLE_TABLES if table != "novel_bible_entities"),
            id="delete-batch",
        ),
    ],
)
async def test_deletion_paths_delete_bible_rows_themselves_between_the_chapter_lock_and_the_revisions(
    db_session: AsyncSession, delete: _Deleter, tables: tuple[str, ...]
) -> None:
    """세 삭제 경로는 정본 기억 행을 cascade 에 맡기지 않고 표마다 직접 지운다 — 화 행을 잠근 뒤, 화 개정을 지우기 전에, 작업을
    확정보다 먼저. 깨지는 시나리오: 화 잠금 앞에서 지우면, 화에 키 공유 잠금을 쥐고 진행 중이던 정본 기억 쓰기가 그 뒤에 커밋한
    행을 보지 못한다(숨긴 소설 정리는 화·개정을 남겨 cascade 도 없다). 개정 DELETE 의 cascade 에 맡기면 확정 행이 작업 행보다 먼저
    잠겨, 정본 기억 작업 처리가 따를 작업 행 → 확정 행 순서와 엇갈린다."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)
    await _plant_bible_rows(
        db_session, novel_id=tree.novel.id, chapter_id=tree.chapter.id, chapter_revision_id=tree.first_revision.id
    )

    with _recorded_statements() as statements:
        await delete(db_session, tree)

    deleted = {table: _first(statements, f"DELETE FROM {table} ") for table in _BIBLE_TABLES}
    assert {table for table, index in deleted.items() if index is not None} == set(tables)
    positions = [index for index in deleted.values() if index is not None]
    lock = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("SELECT novel_chapters.id") and statement.endswith("FOR UPDATE")
    )
    revisions = _first(statements, "DELETE FROM novel_chapter_revisions ")
    assert revisions is not None
    assert lock < min(positions)
    assert max(positions) < revisions
    jobs, commits = deleted["novel_bible_jobs"], deleted["novel_bible_commits"]
    assert jobs is not None and commits is not None
    assert jobs < commits
