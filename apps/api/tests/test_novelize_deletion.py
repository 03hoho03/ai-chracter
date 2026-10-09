import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelCharacter,
    NovelJob,
    NovelPublication,
    NovelReadingPosition,
    NovelScreening,
    NovelSnapshot,
    User,
)
from api.novelize.deletion import delete_novels
from factories import _make_novel_tree, _make_user, _plant_novel_extras


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
    }
    return {name: (await db_session.scalar(query)) or 0 for name, query in queries.items()}


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
}


async def test_delete_novels_removes_every_row_under_the_novel(db_session: AsyncSession) -> None:
    """작업이 화·기준 개정·자기가 만든 개정을, 되돌리기 개정이 앞 개정을 가리키는 소설도 묶음·인물·등장 인물·스냅샷·
    읽은 위치까지 한 번에 지워진다 — 순서가 틀리면 FK 위반이다."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)
    await _plant_novel_extras(db_session, tree)

    await delete_novels(db_session, [tree.novel.id])

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

    await delete_novels(db_session, [target.novel.id])

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
    }
