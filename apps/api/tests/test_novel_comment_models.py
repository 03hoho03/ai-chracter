"""노벨 화 댓글·노벨 신고 테이블의 CHECK 와, 묶음 삭제가 그 화의 댓글을 지우고 신고는 남기는지. CHECK 는 `alembic check` 가
비교하지 않아 이 행위 테스트가 유일한 검증이다."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    NovelBatch,
    NovelChapter,
    NovelChapterRevision,
    NovelComment,
    NovelReport,
    ReportReasonCategory,
    ReportStatus,
)
from api.novelize.deletion import delete_batch
from factories import NovelTree, _make_novel_tree, _make_user


async def _tree(db_session: AsyncSession) -> NovelTree:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return await _make_novel_tree(db_session, user.id)


def _comment(tree: NovelTree, **overrides: Any) -> NovelComment:
    values: dict[str, Any] = {"chapter_id": tree.chapter.id, "body": "댓글", **overrides}
    return NovelComment(novel_id=tree.novel.id, author_user_id=tree.novel.user_id, **values)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param(
            {"body": None, "deleted_at": datetime.now(UTC), "deleted_by": "someone"},
            "ck_novel_comments_deleted_by",
            id="unknown-deleter",
        ),
        pytest.param({"body": None, "deleted_at": datetime.now(UTC)}, "ck_novel_comments_deleted_pair", id="no-deleter"),
        pytest.param({"deleted_by": "author"}, "ck_novel_comments_deleted_pair", id="no-deleted-at"),
        pytest.param(
            {"deleted_at": datetime.now(UTC), "deleted_by": "author"},
            "ck_novel_comments_body_until_deleted",
            id="deleted-keeps-body",
        ),
        pytest.param({"body": None}, "ck_novel_comments_body_until_deleted", id="live-without-body"),
    ],
)
async def test_comment_deletion_state_must_be_consistent(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    tree = await _tree(db_session)
    db_session.add(_comment(tree, **overrides))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


@pytest.mark.parametrize("deleted_by", ["author", "publisher", "moderator"])
async def test_a_deleted_comment_has_no_body_and_names_who_deleted_it(db_session: AsyncSession, deleted_by: str) -> None:
    """짝 — 위 거부가 지운 댓글 자체를 막아서 나는 것이 아님을 본다."""
    tree = await _tree(db_session)
    db_session.add(_comment(tree, body=None, deleted_at=datetime.now(UTC), deleted_by=deleted_by))
    await db_session.flush()


async def test_a_chapter_report_keeps_its_ordinal(db_session: AsyncSession) -> None:
    """화 칸이 있으면 화 번호도 있어야 한다 — 화가 지워져 칸이 비어도 화 신고였다는 것을 번호로 읽는다."""
    tree = await _tree(db_session)
    db_session.add(
        NovelReport(
            reporter_user_id=tree.novel.user_id,
            publisher_user_id=tree.novel.user_id,
            novel_id=tree.novel.id,
            chapter_id=tree.chapter.id,
            reason_category=ReportReasonCategory.SPAM,
            status=ReportStatus.PENDING,
        )
    )
    with pytest.raises(IntegrityError, match="ck_novel_reports_chapter_ordinal"):
        await db_session.flush()


async def test_deleting_the_last_batch_removes_its_comments_and_keeps_the_reports(db_session: AsyncSession) -> None:
    """마지막 묶음을 지우면 그 화의 댓글만 지워지고 앞 화의 댓글은 남는다. 지운 화의 신고는 화 칸만 비고 남는다 — 같은 신고자가
    그 묶음의 화 둘을 신고했어도 유니크에 걸리지 않는다."""
    tree = await _tree(db_session)
    now = datetime.now(UTC)
    segment: dict[str, Any] = {
        "start_message_id": tree.chapter.start_message_id,
        "start_message_created_at": now + timedelta(minutes=1),
        "end_message_id": tree.chapter.end_message_id,
        "end_message_created_at": now + timedelta(minutes=2),
        "assistant_message_count": 1,
        "source_hash": "0" * 64,
    }
    last_batch = NovelBatch(novel_id=tree.novel.id, ordinal=2, target_episode_count=2, **segment)
    db_session.add(last_batch)
    await db_session.flush()
    doomed = []
    for index, ordinal in enumerate((2, 3)):
        chapter = NovelChapter(
            novel_id=tree.novel.id, ordinal=ordinal, batch_id=last_batch.id, episode_index=index, **segment
        )
        db_session.add(chapter)
        await db_session.flush()
        db_session.add(NovelChapterRevision(chapter_id=chapter.id, revision_no=1, body="본문", source="generate"))
        doomed.append(chapter)
    kept = _comment(tree)
    db_session.add_all([kept, *(_comment(tree, chapter_id=chapter.id) for chapter in doomed)])
    db_session.add_all(
        [
            NovelReport(
                reporter_user_id=tree.novel.user_id,
                publisher_user_id=tree.novel.user_id,
                novel_id=tree.novel.id,
                chapter_id=chapter.id,
                chapter_ordinal=chapter.ordinal,
                reason_category=ReportReasonCategory.SPAM,
                status=ReportStatus.PENDING,
            )
            for chapter in doomed
        ]
    )
    await db_session.flush()

    await delete_batch(db_session, novel_id=tree.novel.id, batch_id=last_batch.id)

    comments = await db_session.scalars(sa.select(NovelComment.id).where(NovelComment.novel_id == tree.novel.id))
    assert list(comments) == [kept.id]
    reports = await db_session.execute(
        sa.select(NovelReport.novel_id, NovelReport.chapter_id, NovelReport.chapter_ordinal).order_by(
            NovelReport.chapter_ordinal
        )
    )
    assert [tuple(row) for row in reports] == [(tree.novel.id, None, 2), (tree.novel.id, None, 3)]
