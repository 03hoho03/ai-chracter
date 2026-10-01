import uuid
from datetime import datetime, timedelta, UTC

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import CommentLike, CommentMute, ContentVisibility, ModerationStatus
from comment_factories import _make_comment, _make_comment_content
from factories import _login_as, _make_user


@pytest.mark.parametrize("state", ["private", "unpublished", "restricted", "deleted"])
async def test_unavailable_content_is_guarded_on_every_read_surface(
    db_client: httpx.AsyncClient, db_session: AsyncSession, state: str
) -> None:
    """상세 API의 응답 여부와 관계없이 댓글 읽기 다섯 표면에서 접근 불가 작품 원문을 막는다."""
    creator, viewer = _make_user(), _make_user()
    db_session.add_all([creator, viewer])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id, body="보이면 안 되는 원문")
    if state == "private":
        content.visibility = ContentVisibility.PRIVATE
    elif state == "unpublished":
        content.current_published_version_id = None
    else:
        content.moderation_status = ModerationStatus(state)
    await db_session.flush()
    await _login_as(db_client, viewer.id)
    for path in [
        f"/contents/{content.id}/comments",
        f"/contents/{content.id}/comments/{root.id}/replies",
        f"/contents/{content.id}/comments/{root.id}/location",
        f"/contents/{content.id}/comment-mention-candidates",
        f"/contents/{content.id}/comments/hidden",
    ]:
        result = await db_client.get(path)
        assert result.status_code == 404
        assert result.json()["detail"]["code"] == "CONTENT_UNAVAILABLE"
        assert "보이면 안 되는 원문" not in result.text


async def test_anonymous_reads_and_private_owner_management_flags(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """공개 비회원과 private 소유자의 읽기는 허용하되 참여·관리 권한을 구분한다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id)
    public = await db_client.get(f"/contents/{content.id}/comments")
    assert public.status_code == 200
    assert public.json()["visibleCommentCount"] == 1
    assert public.json()["canParticipate"] is False
    assert public.json()["items"][0]["canLike"] is False
    assert public.json()["items"][0]["author"]["isCreator"] is True
    content.visibility = ContentVisibility.PRIVATE
    await db_session.flush()
    await _login_as(db_client, creator.id)
    private = await db_client.get(f"/contents/{content.id}/comments")
    assert private.status_code == 200
    assert private.json()["canManage"] is True
    assert private.json()["canParticipate"] is False
    item = private.json()["items"][0]
    assert item["id"] == str(root.id)
    assert item["canDelete"] is True
    assert item["canReport"] is True
    assert item["canLike"] is False
    assert item["canReply"] is False


@pytest.mark.parametrize("placeholder", ["deleted", "muted"])
async def test_placeholder_root_preserves_other_reply_but_redacts_identity_and_target(
    db_client: httpx.AsyncClient, db_session: AsyncSession, placeholder: str
) -> None:
    """삭제·mute 원댓글의 신원·원문 없이 다른 작성자의 답글과 상속 스포일러는 남긴다."""
    creator, root_author, reply_author, viewer = (_make_user() for _ in range(4))
    db_session.add_all([creator, root_author, reply_author, viewer])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, root_author.id, body="비밀 원문", is_spoiler=True)
    reply = await _make_comment(
        db_session, content, reply_author.id, root_comment_id=root.id,
        reply_to_comment_id=root.id, inherited_spoiler=True,
    )
    if placeholder == "deleted":
        root.deleted_at = datetime.now(UTC)
        root.body = None
    else:
        db_session.add(CommentMute(viewer_user_id=viewer.id, target_user_id=root_author.id))
    await db_session.flush()
    await _login_as(db_client, viewer.id)
    listing = await db_client.get(f"/contents/{content.id}/comments")
    assert listing.status_code == 200
    assert listing.json()["visibleCommentCount"] == 1
    item = listing.json()["items"][0]
    assert item["displayState"] == placeholder
    assert item["author"] is None
    assert item["body"] is None
    assert item["sticker"] is None
    assert item["canReply"] is False
    assert item["replyCount"] == 1
    location = await db_client.get(f"/contents/{content.id}/comments/{reply.id}/location")
    assert location.status_code == 200
    target = location.json()["target"]
    assert target["effectiveSpoiler"] is True
    assert target["replyTo"]["author"] is None
    assert target["replyTo"]["bodyPreview"] is None
    root_location = await db_client.get(f"/contents/{content.id}/comments/{root.id}/location")
    assert root_location.status_code == 404
    assert root_location.json()["detail"]["code"] == "COMMENT_NOT_FOUND"


async def test_creator_hidden_thread_is_excluded_and_owner_hidden_list_is_redacted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작가가 숨긴 스레드는 일반 조회에서 사라지고 복원 목록에도 원문·스티커는 나오지 않는다."""
    creator, author = _make_user(), _make_user()
    db_session.add_all([creator, author])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, author.id, creator_hidden=True, body="숨긴 원문")
    reply = await _make_comment(db_session, content, author.id, root_comment_id=root.id, reply_to_comment_id=root.id)
    listing = await db_client.get(f"/contents/{content.id}/comments")
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    assert listing.json()["visibleCommentCount"] == 0
    location = await db_client.get(f"/contents/{content.id}/comments/{reply.id}/location")
    assert location.status_code == 404
    await _login_as(db_client, creator.id)
    hidden = await db_client.get(f"/contents/{content.id}/comments/hidden")
    assert hidden.status_code == 200
    assert hidden.json()["totalCount"] == 1
    item = hidden.json()["items"][0]
    assert item["id"] == str(root.id)
    assert item["body"] is None and item["sticker"] is None and item["mentions"] == []
    assert item["canCreatorRestore"] is True


async def test_root_and_reply_pages_use_tie_breakers_and_location_reaches_last_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """동시각의 20개 초과 댓글·답글이 페이지에서 누락·중복되지 않고 마지막 위치도 찾는다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    same_time = datetime.now(UTC) - timedelta(days=1)
    roots = [await _make_comment(db_session, content, creator.id, created_at=same_time) for _ in range(23)]
    pinned = max(roots, key=lambda c: c.id)
    content.pinned_comment_id = pinned.id
    replies = [await _make_comment(
        db_session, content, creator.id, root_comment_id=pinned.id,
        reply_to_comment_id=pinned.id, created_at=same_time,
    ) for _ in range(43)]
    await db_session.flush()
    first = await db_client.get(f"/contents/{content.id}/comments")
    assert first.status_code == 200
    assert first.json()["pinnedComment"]["id"] == str(pinned.id)
    assert len(first.json()["items"]) == 20
    second = await db_client.get(f"/contents/{content.id}/comments", params={"cursor": first.json()["nextCursor"]})
    ids = [i["id"] for i in first.json()["items"] + second.json()["items"]]
    assert len(ids) == len(set(ids)) == 22
    assert str(pinned.id) not in ids
    invalid_sort = await db_client.get(f"/contents/{content.id}/comments", params={"sort": "popular", "cursor": first.json()["nextCursor"]})
    assert invalid_sort.status_code == 422
    assert invalid_sort.json()["detail"]["code"] == "COMMENT_CURSOR_INVALID"
    last = max(replies, key=lambda c: c.id)
    located = await db_client.get(f"/contents/{content.id}/comments/{last.id}/location")
    assert located.status_code == 200
    assert last.id == uuid.UUID(located.json()["target"]["id"])
    page = located.json()["replies"]
    assert len(page["items"]) == 20
    assert str(last.id) in {i["id"] for i in page["items"]}
    assert page["previousCursor"] is not None
    assert page["nextCursor"] is None
    previous = await db_client.get(f"/contents/{content.id}/comments/{pinned.id}/replies", params={"direction": "before", "cursor": page["previousCursor"]})
    assert previous.status_code == 200
    assert len(previous.json()["items"]) == 20
    assert not ({i["id"] for i in previous.json()["items"]} & {i["id"] for i in page["items"]})


async def test_popular_sort_uses_actual_like_rows_and_mention_candidates_do_not_search_all_users(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """좋아요 행 수로 인기순을 정하고 후보는 정상 보이는 참여자·작가로 제한한다."""
    creator, participant, outsider, viewer = (_make_user(nickname="동명") for _ in range(4))
    db_session.add_all([creator, participant, outsider, viewer])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    popular = await _make_comment(db_session, content, participant.id)
    await _make_comment(db_session, content, creator.id)
    db_session.add(CommentLike(comment_id=popular.id, user_id=viewer.id))
    await db_session.flush()
    await _login_as(db_client, viewer.id)
    listing = await db_client.get(f"/contents/{content.id}/comments", params={"sort": "popular"})
    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == str(popular.id)
    assert listing.json()["items"][0]["isLiked"] is True
    candidates = await db_client.get(f"/contents/{content.id}/comment-mention-candidates", params={"q": "동명"})
    assert candidates.status_code == 200
    assert {i["id"] for i in candidates.json()["items"]} == {str(creator.id), str(participant.id)}
    db_session.add(CommentMute(viewer_user_id=viewer.id, target_user_id=participant.id))
    await db_session.flush()
    muted = await db_client.get(f"/contents/{content.id}/comment-mention-candidates")
    assert muted.status_code == 200
    assert {i["id"] for i in muted.json()["items"]} == {str(creator.id)}
