import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Comment, CommentLike, CommentMention, CommentMute
from comment_factories import _make_comment, _make_comment_content
from factories import _make_user


@pytest.mark.parametrize("violation", ["missing-target", "own-root", "own-target"])
async def test_invalid_reply_references_fail_at_database(
    db_session: AsyncSession, violation: str
) -> None:
    """직접 DB 삽입이 API 검사를 우회해도 불가능한 답글 참조를 저장하지 못한다."""
    author = _make_user()
    db_session.add(author)
    await db_session.flush()
    content = await _make_comment_content(db_session, author.id)
    root = await _make_comment(db_session, content, author.id)
    comment_id = uuid.uuid4()
    root_id = comment_id if violation == "own-root" else root.id
    target_id = None if violation == "missing-target" else (
        comment_id if violation == "own-target" else root.id
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(sa.insert(Comment).values(
                id=comment_id, content_id=content.id, author_user_id=author.id,
                root_comment_id=root_id, reply_to_comment_id=target_id,
                body="위조", request_id=uuid.uuid4(), request_fingerprint="invalid",
            ))


async def test_self_mute_fails_at_database(db_session: AsyncSession) -> None:
    """설정 API를 우회한 자기 mute 행도 DB에서 거부한다."""
    author = _make_user()
    db_session.add(author)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(sa.insert(CommentMute).values(
                viewer_user_id=author.id, target_user_id=author.id,
            ))


@pytest.mark.parametrize("table", ["mention", "like", "mute"])
async def test_duplicate_composite_key_fails_at_database(
    db_session: AsyncSession, table: str
) -> None:
    """중복 mention/like/mute를 직접 삽입해도 관계가 두 행으로 늘어나지 않는다."""
    author, viewer = _make_user(), _make_user()
    db_session.add_all([author, viewer])
    await db_session.flush()
    content = await _make_comment_content(db_session, author.id)
    comment = await _make_comment(db_session, content, author.id)
    if table == "mute":
        statement = sa.insert(CommentMute).values(viewer_user_id=viewer.id, target_user_id=author.id)
    else:
        model = CommentMention if table == "mention" else CommentLike
        statement = sa.insert(model).values(comment_id=comment.id, user_id=viewer.id)
    await db_session.execute(statement)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(statement)
