import uuid
from datetime import datetime, UTC

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import (
    Comment, CommentMention, CommentSticker, ContentType, ContentVisibility, Notification,
)
from comment_factories import _comment_payload, _make_comment, _make_comment_content
from factories import _login_as, _make_user


@pytest.mark.parametrize("content_type", [ContentType.CHARACTER, ContentType.STORY])
async def test_create_root_retry_keeps_one_comment_and_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession, content_type: ContentType
) -> None:
    """성공 후 네트워크 재시도가 댓글과 작가 알림을 다시 만들지 않는다."""
    creator, author = _make_user(nickname="작가"), _make_user(nickname="독자")
    db_session.add_all([creator, author])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id, content_type)
    await _login_as(db_client, author.id)
    payload = _comment_payload(body="<b>🙂</b>\n@작가 #태그")
    first = await db_client.post(f"/contents/{content.id}/comments", json=payload)
    assert first.status_code == 201
    saved = first.json()
    assert saved["body"] == payload["body"]
    assert saved["author"]["id"] == str(author.id)
    assert saved["author"]["isCreator"] is False
    retry = await db_client.post(f"/contents/{content.id}/comments", json=payload)
    assert retry.status_code == 200
    assert retry.json()["id"] == saved["id"]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(Comment)) == 1
    notifications = list((await db_session.scalars(sa.select(Notification))).all())
    assert [(n.user_id, n.type, n.actor_user_id) for n in notifications] == [
        (creator.id, "comment-created", author.id)
    ]
    changed = await db_client.post(f"/contents/{content.id}/comments", json={**payload, "body": "다른 내용"})
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "COMMENT_REQUEST_CONFLICT"


async def test_reply_to_reply_stays_flat_and_notifies_actual_target_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """B에 답한 C가 A의 같은 답글 목록에 저장되고 B에게만 답글 우선 알림을 보낸다."""
    creator, target_author, author = _make_user(), _make_user(), _make_user()
    db_session.add_all([creator, target_author, author])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id, is_spoiler=True)
    target = await _make_comment(
        db_session, content, target_author.id, root_comment_id=root.id, reply_to_comment_id=root.id
    )
    await _login_as(db_client, author.id)
    result = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        rootCommentId=str(root.id), replyToCommentId=str(target.id),
        mentionUserIds=[str(target_author.id)],
    ))
    assert result.status_code == 201
    assert result.json()["rootCommentId"] == str(root.id)
    assert result.json()["replyToCommentId"] == str(target.id)
    assert result.json()["replyTo"]["author"]["id"] == str(target_author.id)
    assert result.json()["effectiveSpoiler"] is True
    assert result.json()["inheritedSpoiler"] is True
    notifications = list((await db_session.scalars(sa.select(Notification))).all())
    assert [(n.user_id, n.type) for n in notifications] == [(target_author.id, "comment-reply")]


@pytest.mark.parametrize("invalid", ["other-content", "other-root", "deleted-target"])
async def test_reply_target_cannot_cross_thread_or_point_at_deleted_comment(
    db_client: httpx.AsyncClient, db_session: AsyncSession, invalid: str
) -> None:
    """조작한 root/target ID로 다른 작품·스레드 또는 삭제 댓글에 답하지 못한다."""
    author = _make_user()
    db_session.add(author)
    await db_session.flush()
    content = await _make_comment_content(db_session, author.id)
    root = await _make_comment(db_session, content, author.id)
    other_content = await _make_comment_content(db_session, author.id)
    target = await _make_comment(
        db_session, other_content if invalid == "other-content" else content, author.id
    )
    if invalid == "deleted-target":
        target.root_comment_id = root.id
        target.reply_to_comment_id = root.id
        target.deleted_at = datetime.now(UTC)
        target.body = None
        await db_session.flush()
    await _login_as(db_client, author.id)
    result = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        rootCommentId=str(root.id), replyToCommentId=str(target.id),
    ))
    assert result.status_code == (409 if invalid == "deleted-target" else 422)
    assert result.json()["detail"]["code"] == (
        "COMMENT_DELETED" if invalid == "deleted-target" else "COMMENT_REPLY_TARGET_INVALID"
    )


@pytest.mark.parametrize("body,sticker,code", [
    ("👨‍👩‍👧‍👦" * 1000, None, None),
    ("가\u0301" * 1001, None, "COMMENT_TEXT_TOO_LONG"),
    ("  \n", None, "COMMENT_EMPTY"),
    ("", "ddona-hello", None),
    ("🙂", "https://external/image.png", "COMMENT_STICKER_INVALID"),
], ids=["1000-family-emoji", "1001-combining-graphemes", "empty", "sticker-only", "external-sticker"])
async def test_grapheme_empty_and_official_sticker_validation(
    db_client: httpx.AsyncClient, db_session: AsyncSession,
    body: str, sticker: str | None, code: str | None,
) -> None:
    """문자열 코드포인트 길이 대신 grapheme 한도를 적용하고 빈 내용·임의 스티커를 막는다."""
    author = _make_user()
    db_session.add(author)
    await db_session.flush()
    content = await _make_comment_content(db_session, author.id)
    await _login_as(db_client, author.id)
    result = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        body=body, stickerId=sticker,
    ))
    if code is None:
        assert result.status_code == 201
        assert result.json()["body"] == body
        if sticker is not None:
            assert result.json()["sticker"]["imageUrl"].startswith(f"{settings.frontend_base_url}/comment-stickers/")
    else:
        assert result.status_code == 422
        assert result.json()["detail"]["code"] == code


async def test_mentions_are_selected_candidates_and_disabled_sticker_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """서비스 전체 계정 ID와 선택 중지 스티커는 정상 텍스트와 함께 보내도 새 댓글에 넣지 못한다."""
    creator, author, outsider = _make_user(), _make_user(), _make_user()
    db_session.add_all([creator, author, outsider])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    await _login_as(db_client, author.id)
    invalid = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        mentionUserIds=[str(outsider.id)],
    ))
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "COMMENT_MENTION_INVALID"
    sticker = await db_session.get(CommentSticker, "ddona-hello")
    assert sticker is not None
    sticker.is_selectable = False
    await db_session.flush()
    invalid_sticker = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        stickerId=sticker.id,
    ))
    assert invalid_sticker.status_code == 422
    assert invalid_sticker.json()["detail"]["code"] == "COMMENT_STICKER_INVALID"
    valid = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        mentionUserIds=[str(creator.id)],
    ))
    assert valid.status_code == 201
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CommentMention)) == 1


async def test_create_pause_private_and_auth_guards_keep_existing_comments(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작성 중지·private·비회원은 새 댓글을 쓰지 못하며 소유자도 예외가 아니다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    anonymous = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload())
    assert anonymous.status_code == 401
    await _login_as(db_client, creator.id)
    content.comments_enabled = False
    await db_session.flush()
    paused = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload())
    assert paused.status_code == 403
    assert paused.json()["detail"]["code"] == "COMMENTS_PAUSED"
    content.comments_enabled = True
    content.visibility = ContentVisibility.PRIVATE
    await db_session.flush()
    private = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload())
    assert private.status_code == 403
    assert private.json()["detail"]["code"] == "COMMENT_PARTICIPATION_UNAVAILABLE"


async def test_sixth_new_create_attempt_is_rate_limited_but_successful_retry_is_free(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 성공 재시도는 빈도를 소비하지 않고 여섯 번째 신규 시도에 재시도 시간을 돌려준다."""
    author = _make_user()
    db_session.add(author)
    await db_session.flush()
    content = await _make_comment_content(db_session, author.id)
    await _login_as(db_client, author.id)
    payload = _comment_payload()
    assert (await db_client.post(f"/contents/{content.id}/comments", json=payload)).status_code == 201
    for _ in range(3):
        assert (await db_client.post(f"/contents/{content.id}/comments", json=payload)).status_code == 200
    for _ in range(4):
        assert (await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(body=" "))).status_code == 422
    limited = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload())
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "COMMENT_RATE_LIMITED"
    assert 0 < limited.json()["detail"]["retryAfterSeconds"] <= 60
    assert limited.headers["retry-after"] == str(limited.json()["detail"]["retryAfterSeconds"])
