"""댓글 신고 증거와 현재 댓글, 운영 숨김과 제작자 숨김을 분리한다."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import AdminUser, Content, ContentVisibility, ModerationStatus, Notification, User
from api.db.models.comments import Comment, CommentMention, CommentMute, CommentReport
from api.db.models.moderation import AdminActionLog, ReportReasonCategory, ReportStatus
from factories import _count_queries, _create_admin, _get_genre, _login_as, _login_as_admin, _make_published_character, _make_user


async def setup_comment(db: AsyncSession) -> tuple[Comment, uuid.UUID, uuid.UUID]:
    creator, author, reader = _make_user(), _make_user(), _make_user()
    db.add_all([creator, author, reader])
    await db.flush()
    content = await _make_published_character(db, creator_user_id=creator.id, genre_id=(await _get_genre(db)).id)
    comment = Comment(
        content_id=content.id,
        author_user_id=author.id,
        body="신고 당시 원문",
        sticker_id="ddona-hello",
        request_id=uuid.uuid4(),
        request_fingerprint="fixture",
    )
    db.add(comment)
    await db.flush()
    db.add(CommentMention(comment_id=comment.id, user_id=creator.id))
    await db.commit()
    return comment, reader.id, creator.id


async def test_report_snapshot_stays_original_and_duplicate_does_not_extend_retention(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    comment, reader_id, creator_id = await setup_comment(db_session)
    await _login_as(db_client, reader_id)
    first = await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory": "spam"})
    assert first.status_code == 200
    report = await db_session.get(CommentReport, uuid.UUID(first.json()["reportId"]))
    assert report is not None
    assert report.evidence_body == "신고 당시 원문"
    assert report.evidence_sticker_id == "ddona-hello"
    assert report.evidence_mention_user_ids == [creator_id]
    assert report.evidence_expires_at == report.created_at + timedelta(days=90)
    original_expiry = report.evidence_expires_at
    comment.body = "신고 이후 수정"
    await db_session.commit()
    duplicate = await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory": "hate"})
    assert duplicate.json() == first.json()
    await db_session.refresh(report)
    assert report.evidence_body == "신고 당시 원문" and report.evidence_expires_at == original_expiry


@pytest.mark.parametrize("hidden", ["creator_hidden", "moderator_hidden", "deleted_at"])
async def test_hidden_or_deleted_comment_cannot_be_reported(
    db_client: httpx.AsyncClient, db_session: AsyncSession, hidden: str
) -> None:
    comment, reader_id, _ = await setup_comment(db_session)
    setattr(comment, hidden, datetime.now(UTC) if hidden == "deleted_at" else True)
    await db_session.commit()
    await _login_as(db_client, reader_id)
    response = await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory": "spam"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "COMMENT_NOT_FOUND"
    assert await db_session.scalar(select(CommentReport.id).where(CommentReport.comment_id == comment.id)) is None


async def test_private_owner_can_report_but_other_reader_cannot(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    comment, reader_id, creator_id = await setup_comment(db_session)
    from api.db.models import Content

    content = await db_session.get(Content, comment.content_id)
    assert content is not None
    content.visibility = ContentVisibility.PRIVATE
    await db_session.commit()
    await _login_as(db_client, reader_id)
    assert (await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory": "spam"})).status_code == 404
    await _login_as(db_client, creator_id)
    assert (await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory": "spam"})).status_code == 200


async def test_admin_evidence_expiry_redacts_before_purge(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    comment, reader_id, _ = await setup_comment(db_session)
    report = CommentReport(
        comment_id=comment.id,
        reporter_user_id=reader_id,
        reason_category=ReportReasonCategory.SPAM,
        status=ReportStatus.PENDING,
        evidence_body="만료 비밀",
        evidence_sticker_id="ddona-hello",
        evidence_mention_user_ids=[reader_id],
        evidence_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db_session.add(report)
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)
    response = await db_client.get(f"/admin/comment-reports/{report.id}")
    assert response.status_code == 200
    assert response.json()["evidence"] == {
        "expiresAt": report.evidence_expires_at.isoformat().replace("+00:00", "Z"),
        "available": False,
        "body": None,
        "stickerId": None,
        "mentionUserIds": [],
    }
    await db_session.refresh(report)
    assert report.evidence_body == "만료 비밀"


async def test_comment_moderation_keeps_creator_hidden_and_content_state(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    comment, reader_id, _ = await setup_comment(db_session)
    report = CommentReport(
        comment_id=comment.id,
        reporter_user_id=reader_id,
        reason_category=ReportReasonCategory.SPAM,
        status=ReportStatus.PENDING,
        evidence_body=comment.body,
    )
    db_session.add(report)
    admin = await _create_admin(db_session)
    comment.creator_hidden = True
    from api.db.models import Content

    content = await db_session.get(Content, comment.content_id)
    assert content is not None
    content.pinned_comment_id = comment.id
    await db_session.commit()
    await _login_as_admin(db_client, admin)
    for action in ("hide", "restore"):
        response = await db_client.post(
            f"/admin/comment-reports/{report.id}/actions", json={"action": action, "adminComment": "검토한 조치 사유"}
        )
        assert response.status_code == 200
    await db_session.refresh(comment)
    await db_session.refresh(content)
    assert comment.creator_hidden is True and comment.moderator_hidden is False
    assert content.moderation_status == ModerationStatus.NORMAL and content.pinned_comment_id is None
    logs = (
        await db_session.scalars(select(AdminActionLog).where(AdminActionLog.target_comment_id == comment.id))
    ).all()
    assert {x.action_type for x in logs} == {"comment-hide", "comment-restore"}
    notifications = (await db_session.scalars(select(Notification).where(Notification.comment_id == comment.id))).all()
    assert len(notifications) == 2 and all(x.type == "comment-moderated" for x in notifications)
    assert all(x.action_id is None and x.comment_action_id is not None for x in notifications)


async def test_notification_pagination_unread_mute_and_read_use_same_redaction(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    comment, reader_id, _ = await setup_comment(db_session)
    notice = Notification(
        user_id=reader_id,
        type="comment-mention",
        comment_id=comment.id,
        actor_user_id=comment.author_user_id,
        content_id=comment.content_id,
    )
    db_session.add(notice)
    db_session.add_all([Notification(user_id=reader_id, type="user-warned") for _ in range(21)])
    await db_session.commit()
    await _login_as(db_client, reader_id)
    first = await db_client.get("/notifications")
    assert first.status_code == 200
    assert len(first.json()["items"]) == 20 and first.json()["unreadCount"] == 22 and first.json()["nextCursor"]
    second = await db_client.get("/notifications", params={"cursor": first.json()["nextCursor"]})
    assert len(second.json()["items"]) == 2
    comment.is_spoiler = True
    await db_session.commit()
    read = await db_client.patch(f"/notifications/{notice.id}/read")
    assert read.status_code == 200
    assert read.json()["comment"]["bodyPreview"] is None and read.json()["comment"]["stickerName"] is None
    db_session.add(CommentMute(viewer_user_id=reader_id, target_user_id=comment.author_user_id))
    await db_session.commit()
    after = await db_client.get("/notifications")
    assert after.json()["unreadCount"] == 21
    assert str(notice.id) not in [x["id"] for x in after.json()["items"]]
    assert (await db_client.patch(f"/notifications/{notice.id}/read")).status_code == 404


async def test_comment_reporting_has_separate_rate_protection(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    comment, reader_id, _ = await setup_comment(db_session)
    await _login_as(db_client, reader_id)
    for _ in range(10):
        response = await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory":"spam"})
        assert response.status_code == 200
    limited = await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory":"spam"})
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "COMMENT_RATE_LIMITED"
    assert limited.json()["detail"]["retryAfterSeconds"] > 0
    assert int(limited.headers["Retry-After"]) > 0


@pytest.mark.parametrize("multiple_contents", [False, True])
async def test_comment_notification_query_count_does_not_grow_per_item(
    db_client: httpx.AsyncClient, db_session: AsyncSession, multiple_contents: bool
) -> None:
    comment, reader_id, creator_id = await setup_comment(db_session)
    db_session.add(Notification(user_id=reader_id, actor_user_id=creator_id,
        type="comment-mention", content_id=comment.content_id, comment_id=comment.id))
    await db_session.commit()
    await _login_as(db_client, reader_id)
    with _count_queries() as query_count:
        first = await db_client.get("/notifications")
    assert first.status_code == 200 and len(first.json()["items"]) == 1
    assert first.json()["items"][0]["comment"]["author"]["isCreator"] is False
    one_count = query_count()
    expected_badges = {str(comment.id): False}
    for index in range(5):
        content_id = comment.content_id
        if multiple_contents:
            content_id = (await _make_published_character(db_session,
                creator_user_id=reader_id if index % 2 else creator_id,
                genre_id=(await _get_genre(db_session)).id)).id
        other = Comment(content_id=content_id, author_user_id=creator_id, body=f"추가 알림 {index}",
            request_id=uuid.uuid4(), request_fingerprint="fixture")
        db_session.add(other)
        await db_session.flush()
        expected_badges[str(other.id)] = not multiple_contents or index % 2 == 0
        db_session.add(Notification(user_id=reader_id, actor_user_id=creator_id,
            type="comment-mention", content_id=content_id, comment_id=other.id))
    await db_session.commit()
    with _count_queries() as query_count:
        page = await db_client.get("/notifications")
    assert page.status_code == 200 and len(page.json()["items"]) == 6
    assert {item["comment"]["commentId"]: item["comment"]["author"]["isCreator"]
            for item in page.json()["items"]} == expected_badges
    print(f"multiple_contents={multiple_contents}; SQL one={one_count}, six={query_count()}")
    assert query_count() == one_count


@pytest.mark.parametrize("endpoint", ["report", "direct"])
@pytest.mark.parametrize("author_withdrawn", [False, True])
async def test_moderator_can_unhide_deleted_root_thread_without_restoring_original(
    db_client: httpx.AsyncClient, db_session: AsyncSession, endpoint: str, author_withdrawn: bool,
) -> None:
    """삭제된 원댓글의 운영 숨김만 해제하고 타인의 답글·독립 숨김·영구 파기를 보존한다."""
    root, reader_id, creator_id = await setup_comment(db_session)
    report = CommentReport(comment_id=root.id, reporter_user_id=reader_id,
        reason_category=ReportReasonCategory.SPAM, status=ReportStatus.PENDING,
        evidence_body="신고 당시 원문", evidence_sticker_id="ddona-hello")
    reply = Comment(content_id=root.content_id, author_user_id=reader_id, root_comment_id=root.id,
        reply_to_comment_id=root.id, body="보존할 타인의 답글", request_id=uuid.uuid4(), request_fingerprint="fixture")
    hidden_reply = Comment(content_id=root.content_id, author_user_id=reader_id, root_comment_id=root.id,
        reply_to_comment_id=root.id, body="별도로 숨긴 타인의 답글", moderator_hidden=True,
        request_id=uuid.uuid4(), request_fingerprint="fixture")
    db_session.add_all([report, reply, hidden_reply])
    root.deleted_at=datetime.now(UTC)
    root.body=None
    root.sticker_id=None
    root.creator_hidden=True
    root.moderator_hidden=True
    await db_session.execute(delete(CommentMention).where(CommentMention.comment_id==root.id))
    if author_withdrawn:
        author=await db_session.get(User,root.author_user_id)
        assert author is not None
        author.deleted_at=datetime.now(UTC)
        author.nickname=None
    admin=await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client,admin)
    if endpoint=="report":
        restored=await db_client.post(f"/admin/comment-reports/{report.id}/actions",
            json={"action":"restore","adminComment":"원문은 삭제 상태로 유지하며 스레드 운영 숨김만 해제"})
        assert restored.status_code==200
        current=restored.json()["comment"]
        assert current["body"] is None and current["sticker"] is None and current["author"] is None
        assert restored.json()["evidence"]["body"]=="신고 당시 원문"
    else:
        restored=await db_client.request("DELETE",f"/admin/comments/{root.id}/moderator-hidden",
            json={"adminComment":"원문은 삭제 상태로 유지하며 스레드 운영 숨김만 해제"})
        assert restored.status_code==204
    await db_session.refresh(root)
    await db_session.refresh(hidden_reply)
    assert root.deleted_at is not None and root.body is None and root.sticker_id is None
    assert root.creator_hidden is True and root.moderator_hidden is False
    assert hidden_reply.moderator_hidden is True
    content=await db_session.get(Content,root.content_id)
    assert content is not None and content.pinned_comment_id is None
    await _login_as(db_client,reader_id)
    assert (await db_client.get(f"/contents/{root.content_id}/comments")).json()["items"]==[]
    await _login_as(db_client,creator_id)
    assert (await db_client.delete(f"/comments/{root.id}/creator-hidden")).status_code==204
    listing=(await db_client.get(f"/contents/{root.content_id}/comments")).json()
    assert listing["visibleCommentCount"]==1
    assert listing["items"][0]["displayState"]=="deleted"
    assert listing["items"][0]["author"] is None and listing["items"][0]["body"] is None
    replies=(await db_client.get(f"/contents/{root.content_id}/comments/{root.id}/replies")).json()
    assert [item["id"] for item in replies["items"]]==[str(reply.id)]
    assert replies["items"][0]["body"]=="보존할 타인의 답글"
    logs=(await db_session.scalars(select(AdminActionLog).where(AdminActionLog.target_comment_id==root.id))).all()
    admin_id=await db_session.scalar(select(AdminUser.id).where(AdminUser.email==admin["email"]))
    assert len(logs)==1 and logs[0].action_type=="comment-restore" and logs[0].admin_id==admin_id


async def test_moderator_cannot_unhide_deleted_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession,
) -> None:
    """삭제된 대댓글은 원문 복원이나 숨김 해제를 허용하지 않는다."""
    root,reader_id,_=await setup_comment(db_session)
    reply=Comment(content_id=root.content_id,author_user_id=reader_id,root_comment_id=root.id,
        reply_to_comment_id=root.id,body=None,deleted_at=datetime.now(UTC),moderator_hidden=True,
        request_id=uuid.uuid4(),request_fingerprint="fixture")
    db_session.add(reply)
    await db_session.flush()
    report=CommentReport(comment_id=reply.id,reporter_user_id=reader_id,
        reason_category=ReportReasonCategory.SPAM,status=ReportStatus.PENDING,evidence_body="이전 신고 증거")
    db_session.add(report)
    admin=await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client,admin)
    response=await db_client.post(f"/admin/comment-reports/{report.id}/actions",
        json={"action":"restore","adminComment":"삭제된 대댓글은 복원할 수 없음"})
    assert response.status_code==409 and response.json()["detail"]["code"]=="COMMENT_DELETED"
    await db_session.refresh(reply)
    assert reply.body is None and reply.deleted_at is not None and reply.moderator_hidden is True
    assert (await db_session.scalars(select(AdminActionLog).where(AdminActionLog.target_comment_id==reply.id))).all()==[]


async def test_moderator_can_unhide_deleted_root_without_replies_while_publicly_unlisted(
    db_client: httpx.AsyncClient, db_session: AsyncSession,
) -> None:
    """답글 없는 삭제 원댓글의 flag를 해제해도 원문이 살아나거나 공개 목록에 나오지 않는다."""
    root,reader_id,_=await setup_comment(db_session)
    root.deleted_at=datetime.now(UTC)
    root.body=None
    root.sticker_id=None
    root.moderator_hidden=True
    await db_session.execute(delete(CommentMention).where(CommentMention.comment_id==root.id))
    admin=await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client,admin)
    response=await db_client.request("DELETE",f"/admin/comments/{root.id}/moderator-hidden",
        json={"adminComment":"삭제 원댓글의 운영 flag만 해제"})
    assert response.status_code==204
    await db_session.refresh(root)
    assert root.body is None and root.sticker_id is None and root.deleted_at is not None
    assert root.moderator_hidden is False
    await _login_as(db_client,reader_id)
    listing=(await db_client.get(f"/contents/{root.content_id}/comments")).json()
    assert listing["items"]==[] and listing["visibleCommentCount"]==0


async def test_author_cannot_report_own_comment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    comment, _, _ = await setup_comment(db_session)
    await _login_as(db_client, comment.author_user_id)
    listing = await db_client.get(f"/contents/{comment.content_id}/comments")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["canReport"] is False
    response = await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory": "spam"})
    assert response.status_code == 404
    count = await db_session.scalar(
        select(func.count()).select_from(CommentReport).where(CommentReport.comment_id == comment.id)
    )
    assert count == 0
