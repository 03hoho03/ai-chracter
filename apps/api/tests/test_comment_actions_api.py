from datetime import datetime, timedelta, UTC

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    CommentLike, CommentMention, CommentReport, CommentSticker, ContentVisibility,
    Notification, ReportReasonCategory, ReportStatus,
)
from comment_factories import _comment_payload, _make_comment, _make_comment_content
from factories import _login_as, _make_user


async def test_later_spoiler_propagates_through_reply_target_chain_and_survives_delete_mute(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """B에 뒤늦게 켠 스포일러가 C→D까지 이어지고 B 삭제·개인 mute 후에도 유지된다."""
    creator, author, viewer = _make_user(), _make_user(), _make_user()
    db_session.add_all([creator, author, viewer])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id)
    b = await _make_comment(db_session, content, author.id, root_comment_id=root.id, reply_to_comment_id=root.id)
    c = await _make_comment(db_session, content, creator.id, root_comment_id=root.id, reply_to_comment_id=b.id)
    d = await _make_comment(db_session, content, creator.id, root_comment_id=root.id, reply_to_comment_id=c.id)
    await _login_as(db_client, author.id)
    update: dict[str, object] = {"body": "수정한 전개", "stickerId": None, "isSpoiler": True, "mentionUserIds": []}
    edited = await db_client.patch(f"/comments/{b.id}", json=update)
    assert edited.status_code == 200 and edited.json()["isEdited"] is True
    await _login_as(db_client, creator.id)
    for target in (c, d):
        location = await db_client.get(f"/contents/{content.id}/comments/{target.id}/location")
        assert location.status_code == 200
        assert location.json()["target"]["effectiveSpoiler"] is True
        assert location.json()["target"]["inheritedSpoiler"] is True
    unset = await db_client.patch(f"/comments/{d.id}", json={**update, "isSpoiler": False})
    assert unset.status_code == 200 and unset.json()["effectiveSpoiler"] is True
    await _login_as(db_client, viewer.id)
    assert (await db_client.put(f"/me/comment-mutes/{author.id}")).status_code == 204
    muted = await db_client.get(f"/contents/{content.id}/comments/{d.id}/location")
    assert muted.json()["target"]["effectiveSpoiler"] is True
    await _login_as(db_client, author.id)
    assert (await db_client.delete(f"/comments/{b.id}")).status_code == 204
    deleted = await db_client.get(f"/contents/{content.id}/comments/{d.id}/location")
    assert deleted.json()["target"]["effectiveSpoiler"] is True


async def test_delete_clears_public_content_likes_mentions_pin_and_keeps_other_reply_evidence(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원댓글 삭제가 공개 원문을 파기하고 타인의 답글·신고 증거를 보존한다."""
    creator, author, other = _make_user(), _make_user(), _make_user()
    db_session.add_all([creator, author, other])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, author.id, sticker_id="ddona-hello")
    reply = await _make_comment(db_session, content, other.id, root_comment_id=root.id, reply_to_comment_id=root.id)
    content.pinned_comment_id = root.id
    db_session.add_all([
        CommentLike(comment_id=root.id, user_id=other.id),
        CommentMention(comment_id=root.id, user_id=creator.id),
        CommentReport(reporter_user_id=other.id, comment_id=root.id, reason_category=ReportReasonCategory.SPAM,
                      status=ReportStatus.PENDING, evidence_body="신고 당시 원문", evidence_sticker_id="ddona-hello"),
    ])
    await db_session.flush()
    await _login_as(db_client, other.id)
    denied = await db_client.delete(f"/comments/{root.id}")
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "COMMENT_OWNER_REQUIRED"
    await _login_as(db_client, author.id)
    for _ in range(2):
        assert (await db_client.delete(f"/comments/{root.id}")).status_code == 204
    await db_session.refresh(root)
    await db_session.refresh(content)
    assert root.body is None and root.sticker_id is None and root.deleted_at is not None
    assert content.pinned_comment_id is None
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CommentLike)) == 0
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CommentMention)) == 0
    report = await db_session.scalar(sa.select(CommentReport))
    assert report is not None and report.evidence_body == "신고 당시 원문"
    listing = await db_client.get(f"/contents/{content.id}/comments")
    assert listing.json()["visibleCommentCount"] == 1
    assert listing.json()["items"][0]["displayState"] == "deleted"
    location = await db_client.get(f"/contents/{content.id}/comments/{reply.id}/location")
    assert location.status_code == 200


async def test_like_desired_state_pause_and_private_guards(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 좋아요 재요청은 count를 늘리지 않고 중지는 좋아요 허용·private는 차단한다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id)
    await _login_as(db_client, creator.id)
    for method, expected in [("PUT", 1), ("PUT", 1), ("DELETE", 0), ("DELETE", 0)]:
        result = await db_client.request(method, f"/comments/{root.id}/like")
        assert result.status_code == 200
        assert result.json()["likeCount"] == expected
        assert result.json()["isLiked"] is (method == "PUT")
    pause = await db_client.patch(f"/contents/{content.id}/comment-settings", json={"commentsPaused": True})
    assert pause.status_code == 200 and pause.json()["commentsPaused"] is True
    assert (await db_client.put(f"/comments/{root.id}/like")).status_code == 200
    content.visibility = ContentVisibility.PRIVATE
    await db_session.flush()
    private = await db_client.put(f"/comments/{root.id}/like")
    assert private.status_code == 403
    assert private.json()["detail"]["code"] == "COMMENT_PARTICIPATION_UNAVAILABLE"


async def test_creator_pin_hide_restore_and_ownership_keep_moderator_state_independent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작가 숨김은 고정을 해제하며 복원이 운영 숨김을 풀거나 이전 고정을 되살리지 않는다."""
    creator, author = _make_user(), _make_user()
    db_session.add_all([creator, author])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, author.id)
    reply = await _make_comment(db_session, content, author.id, root_comment_id=root.id, reply_to_comment_id=root.id)
    await _login_as(db_client, author.id)
    unauthorized = await db_client.put(f"/comments/{root.id}/creator-hidden")
    assert unauthorized.status_code == 403 and unauthorized.json()["detail"]["code"] == "COMMENT_OWNER_REQUIRED"
    await _login_as(db_client, creator.id)
    invalid = await db_client.put(f"/contents/{content.id}/pinned-comment", json={"commentId": str(reply.id)})
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "COMMENT_PIN_INVALID"
    pinned = await db_client.put(f"/contents/{content.id}/pinned-comment", json={"commentId": str(root.id)})
    assert pinned.status_code == 200 and pinned.json()["pinnedComment"]["id"] == str(root.id)
    assert (await db_client.put(f"/comments/{root.id}/creator-hidden")).status_code == 204
    await db_session.refresh(content)
    assert content.pinned_comment_id is None
    root.moderator_hidden = True
    await db_session.flush()
    assert (await db_client.delete(f"/comments/{root.id}/creator-hidden")).status_code == 204
    await db_session.refresh(root)
    assert root.creator_hidden is False and root.moderator_hidden is True
    listing = await db_client.get(f"/contents/{content.id}/comments")
    assert listing.json()["items"] == []
    assert (await db_client.delete(f"/contents/{content.id}/pinned-comment")).json()["pinnedComment"] is None


@pytest.mark.parametrize("removal", ["delete", "withdraw"])
async def test_creator_can_unhide_deleted_root_only_without_restoring_content_or_child_flags(
    db_client: httpx.AsyncClient, db_session: AsyncSession, removal: str
) -> None:
    """삭제·탈퇴된 root의 관리 진입과 작가 flag만 해제하며 타인 답글·독립 숨김은 보존한다."""
    creator, author, other = _make_user(), _make_user(), _make_user()
    db_session.add_all([creator, author, other])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, author.id, sticker_id="ddona-hello", is_spoiler=True)
    reply = await _make_comment(db_session, content, other.id, root_comment_id=root.id, reply_to_comment_id=root.id)
    hidden_reply = await _make_comment(db_session, content, other.id, root_comment_id=root.id, reply_to_comment_id=root.id)
    leaf = await _make_comment(db_session, content, author.id, root_comment_id=root.id, reply_to_comment_id=reply.id)
    root.creator_hidden = root.moderator_hidden = hidden_reply.creator_hidden = leaf.creator_hidden = True
    content.pinned_comment_id = root.id
    db_session.add(CommentMention(comment_id=root.id, user_id=other.id))
    await db_session.flush()
    await _login_as(db_client, author.id)
    assert (await db_client.delete("/me" if removal == "withdraw" else f"/comments/{root.id}")).status_code == 204
    if removal == "delete":
        assert (await db_client.delete(f"/comments/{leaf.id}")).status_code == 204
    await _login_as(db_client, creator.id)
    before = await db_client.get(f"/contents/{content.id}/comments")
    assert before.json()["hiddenCommentCount"] == 2 and before.json()["items"] == []
    hidden = await db_client.get(f"/contents/{content.id}/comments/hidden")
    items = {item["id"]: item for item in hidden.json()["items"]}
    assert set(items) == {str(root.id), str(hidden_reply.id)}
    tombstone = items[str(root.id)]
    assert tombstone["displayState"] == "deleted" and tombstone["canCreatorRestore"] is True
    assert tombstone["author"] is None and tombstone["body"] is None and tombstone["sticker"] is None and tombstone["mentions"] == []
    assert (await db_client.put(f"/comments/{root.id}/creator-hidden")).status_code == 409
    assert (await db_client.delete(f"/comments/{leaf.id}/creator-hidden")).status_code == 409
    await _login_as(db_client, other.id)
    denied = await db_client.delete(f"/comments/{root.id}/creator-hidden")
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "COMMENT_OWNER_REQUIRED"
    await _login_as(db_client, creator.id)
    for _ in range(2):
        assert (await db_client.delete(f"/comments/{root.id}/creator-hidden")).status_code == 204
    await db_session.refresh(root)
    await db_session.refresh(content)
    assert root.creator_hidden is False and root.moderator_hidden is True
    assert root.body is None and root.sticker_id is None and root.deleted_at is not None
    assert content.pinned_comment_id is None
    assert (await db_client.get(f"/contents/{content.id}/comments")).json()["items"] == []
    root.moderator_hidden = False
    await db_session.flush()
    after = await db_client.get(f"/contents/{content.id}/comments")
    assert after.json()["visibleCommentCount"] == 1 and after.json()["hiddenCommentCount"] == 1
    assert after.json()["items"][0]["displayState"] == "deleted"
    replies = await db_client.get(f"/contents/{content.id}/comments/{root.id}/replies")
    assert [item["id"] for item in replies.json()["items"]] == [str(reply.id)]
    assert replies.json()["items"][0]["effectiveSpoiler"] is True
    await _login_as(db_client, other.id)
    assert (await db_client.put(f"/comments/{root.id}/like")).status_code == 409
    blocked = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        rootCommentId=str(root.id), replyToCommentId=str(root.id)
    ))
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "COMMENT_DELETED"
    continued = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        rootCommentId=str(root.id), replyToCommentId=str(reply.id)
    ))
    assert continued.status_code == 201 and continued.json()["effectiveSpoiler"] is True
    await _login_as(db_client, author.id)
    edited = await db_client.patch(f"/comments/{root.id}", json={
        "body": "복원 불가", "stickerId": None, "isSpoiler": False, "mentionUserIds": [],
    })
    assert edited.status_code == (401 if removal == "withdraw" else 409)


async def test_creator_can_unhide_deleted_root_without_replies_while_public_stays_empty(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """답글 없는 삭제 root도 작가 숨김만 해제하며 공개 목록·원문을 되살리지 않는다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id, body=None,
                               deleted_at=datetime.now(UTC), creator_hidden=True)
    await _login_as(db_client, creator.id)
    hidden = await db_client.get(f"/contents/{content.id}/comments/hidden")
    assert [item["id"] for item in hidden.json()["items"]] == [str(root.id)]
    assert hidden.json()["items"][0]["canCreatorRestore"] is True
    assert (await db_client.delete(f"/comments/{root.id}/creator-hidden")).status_code == 204
    await db_session.refresh(root)
    assert root.creator_hidden is False and root.body is None and root.deleted_at is not None
    listed = (await db_client.get(f"/contents/{content.id}/comments")).json()
    assert listed["items"] == [] and listed["visibleCommentCount"] == 0 and listed["hiddenCommentCount"] == 0


async def test_edit_preserves_disabled_sticker_and_private_retained_mentions_without_new_notifications(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """선택 중지 스티커·기존 private 멘션은 유지 가능하지만 새 멘션/비활성 스티커 삽입은 막는다."""
    creator, author = _make_user(), _make_user()
    db_session.add_all([creator, author])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    own = await _make_comment(db_session, content, creator.id, sticker_id="ddona-hello")
    await _make_comment(db_session, content, author.id)
    db_session.add(CommentMention(comment_id=own.id, user_id=author.id))
    sticker = await db_session.get(CommentSticker, "ddona-hello")
    assert sticker is not None
    sticker.is_selectable = False
    content.visibility = ContentVisibility.PRIVATE
    await db_session.flush()
    await _login_as(db_client, creator.id)
    payload = {"body": "수정", "stickerId": "ddona-hello", "isSpoiler": False, "mentionUserIds": [str(author.id)]}
    kept = await db_client.patch(f"/comments/{own.id}", json=payload)
    assert kept.status_code == 200 and kept.json()["sticker"]["isSelectable"] is False
    repeated = await db_client.patch(f"/comments/{own.id}", json=payload)
    assert repeated.status_code == 200 and repeated.json()["updatedAt"] == kept.json()["updatedAt"]
    other_sticker = await db_session.get(CommentSticker, "ddona-thanks")
    assert other_sticker is not None
    other_sticker.is_selectable = False
    await db_session.flush()
    disabled = await db_client.patch(f"/comments/{own.id}", json={**payload, "stickerId": "ddona-thanks"})
    assert disabled.status_code == 422 and disabled.json()["detail"]["code"] == "COMMENT_STICKER_INVALID"
    added = await db_client.patch(f"/comments/{own.id}", json={**payload, "mentionUserIds": [str(author.id), str(creator.id)]})
    assert added.status_code == 403 and added.json()["detail"]["code"] == "COMMENT_PARTICIPATION_UNAVAILABLE"
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(Notification)) == 0


async def test_eleventh_edit_attempt_is_account_rate_limited_without_consuming_create_quota(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """서로 다른 댓글 수정도 계정별 10회 제한을 공유하고 작성·다른 계정의 한도는 분리한다."""
    author, other = _make_user(), _make_user()
    db_session.add_all([author, other])
    await db_session.flush()
    content = await _make_comment_content(db_session, author.id)
    comments = [await _make_comment(db_session, content, author.id) for _ in range(2)]
    other_comment = await _make_comment(db_session, content, other.id)
    await _login_as(db_client, author.id)
    payload: dict[str, object] = {"body": "수정", "stickerId": None, "isSpoiler": False, "mentionUserIds": []}
    for attempt in range(10):
        edited = await db_client.patch(f"/comments/{comments[attempt % 2].id}", json={**payload, "body": f"수정 {attempt}"})
        assert edited.status_code == 200
    limited = await db_client.patch(f"/comments/{comments[0].id}", json={**payload, "body": "한도 초과 원문"})
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "COMMENT_RATE_LIMITED"
    assert 0 < limited.json()["detail"]["retryAfterSeconds"] <= 60
    assert limited.headers["retry-after"] == str(limited.json()["detail"]["retryAfterSeconds"])
    await db_session.refresh(comments[0])
    assert comments[0].body == "수정 8"
    created = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload())
    assert created.status_code == 201
    await _login_as(db_client, other.id)
    assert (await db_client.patch(f"/comments/{other_comment.id}", json=payload)).status_code == 200


async def test_mute_settings_and_preferences_control_creation_and_allow_inverse_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """개인 숨김·알림 설정은 수신에 적용하고 상대의 답글 작성 자체를 막지 않는다."""
    creator, author = _make_user(), _make_user()
    db_session.add_all([creator, author])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, creator.id)
    await _login_as(db_client, creator.id)
    defaults = await db_client.get("/me/comment-notification-preferences")
    assert defaults.status_code == 200 and defaults.json() == {"newComment": True, "reply": True, "mention": True}
    settings = {"newComment": False, "reply": False, "mention": True}
    assert (await db_client.put("/me/comment-notification-preferences", json=settings)).json() == settings
    self_mute = await db_client.put(f"/me/comment-mutes/{creator.id}")
    assert self_mute.status_code == 422 and self_mute.json()["detail"]["code"] == "COMMENT_MUTE_INVALID"
    assert (await db_client.put(f"/me/comment-mutes/{author.id}")).status_code == 204
    muted = await db_client.get("/me/comment-mutes")
    assert muted.status_code == 200 and [i["id"] for i in muted.json()["items"]] == [str(author.id)]
    await _login_as(db_client, author.id)
    inverse = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        rootCommentId=str(root.id), replyToCommentId=str(root.id), mentionUserIds=[str(creator.id)]
    ))
    assert inverse.status_code == 201
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(Notification)) == 0
    await _login_as(db_client, creator.id)
    assert (await db_client.delete(f"/me/comment-mutes/{author.id}")).status_code == 204
    await _login_as(db_client, author.id)
    notified = await db_client.post(f"/contents/{content.id}/comments", json=_comment_payload(
        rootCommentId=str(root.id), replyToCommentId=str(root.id), mentionUserIds=[str(creator.id)]
    ))
    assert notified.status_code == 201
    notifications = list((await db_session.scalars(sa.select(Notification))).all())
    assert [n.type for n in notifications] == ["comment-mention"]


async def test_withdraw_erases_authored_comments_likes_identity_and_keeps_other_reply_report(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴 본문·스티커·멘션·좋아요·고정을 제거하고 타인의 답글과 기간 내 신고 증거는 남긴다."""
    creator, author, other = _make_user(), _make_user(), _make_user()
    db_session.add_all([creator, author, other])
    await db_session.flush()
    content = await _make_comment_content(db_session, creator.id)
    root = await _make_comment(db_session, content, author.id, sticker_id="ddona-hello")
    reply = await _make_comment(db_session, content, other.id, root_comment_id=root.id, reply_to_comment_id=root.id)
    content.pinned_comment_id = root.id
    db_session.add_all([
        CommentLike(comment_id=root.id, user_id=other.id), CommentLike(comment_id=reply.id, user_id=author.id),
        CommentMention(comment_id=root.id, user_id=creator.id), CommentMention(comment_id=reply.id, user_id=author.id),
        CommentReport(reporter_user_id=other.id, comment_id=root.id, reason_category=ReportReasonCategory.SPAM,
                      status=ReportStatus.PENDING, evidence_body="보존 증거", evidence_expires_at=datetime.now(UTC)+timedelta(days=90)),
    ])
    await db_session.flush()
    await _login_as(db_client, author.id)
    result = await db_client.delete("/me")
    assert result.status_code == 204
    await db_session.refresh(root)
    await db_session.refresh(content)
    assert root.body is None and root.sticker_id is None and root.deleted_at is not None
    assert content.pinned_comment_id is None
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CommentLike)) == 0
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CommentMention)) == 0
    report = await db_session.scalar(sa.select(CommentReport))
    assert report is not None and report.evidence_body == "보존 증거"
    await _login_as(db_client, other.id)
    target = await db_client.get(f"/contents/{content.id}/comments/{reply.id}/location")
    assert target.status_code == 200 and target.json()["root"]["author"] is None
