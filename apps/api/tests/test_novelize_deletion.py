import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Novel, NovelChapter, NovelChapterRevision, NovelJob, User
from api.novelize.deletion import delete_novels
from factories import _make_novel_tree, _make_user


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
    }
    return {name: (await db_session.scalar(query)) or 0 for name, query in queries.items()}


async def test_delete_novels_removes_jobs_revisions_chapters_and_the_novel(db_session: AsyncSession) -> None:
    """작업이 장·개정을, 되돌리기 개정이 앞 개정을 가리키는 소설도 한 번에 지워진다 — 순서가 틀리면 FK 위반이다."""
    owner = await _make_owner(db_session)
    tree = await _make_novel_tree(db_session, owner.id)

    await delete_novels(db_session, [tree.novel.id])

    assert await _row_counts(db_session, tree.novel.id) == {"novels": 0, "chapters": 0, "revisions": 0, "jobs": 0}


async def test_delete_novels_leaves_other_novels_untouched(db_session: AsyncSession) -> None:
    owner = await _make_owner(db_session)
    target = await _make_novel_tree(db_session, owner.id)
    other = await _make_novel_tree(db_session, owner.id)

    await delete_novels(db_session, [target.novel.id])

    assert await _row_counts(db_session, other.novel.id) == {"novels": 1, "chapters": 1, "revisions": 2, "jobs": 2}
