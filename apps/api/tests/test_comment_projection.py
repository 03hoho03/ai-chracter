import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import CommentMention
from comment_factories import _make_comment, _make_comment_content
from factories import _login_as, _make_user


async def test_hidden_reply_redacts_even_its_normal_reply_target_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """숨김 대댓글의 관리 DTO는 정상인 대상의 작성자·본문 preview도 함께 비운다."""
    creator, author = _make_user(), _make_user()
    db_session.add_all([creator, author])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id, body="답글 대상 원문")
    reply = await _make_comment(db_session, content, author.id, creator_hidden=True,
                                root_comment_id=root.id, reply_to_comment_id=root.id)
    db_session.add(CommentMention(comment_id=reply.id, user_id=creator.id))
    await db_session.flush()
    await _login_as(db_client, creator.id)
    hidden = await db_client.get(f"/contents/{content.id}/comments/hidden")
    assert hidden.status_code == 200
    item = hidden.json()["items"][0]
    assert item["body"] is None and item["author"] is None and item["mentions"] == []
    assert item["replyTo"]["author"] is None
    assert item["replyTo"]["bodyPreview"] is None
