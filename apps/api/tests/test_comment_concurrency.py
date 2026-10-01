import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.comments import actions, write
from api.comments.access import lock_active_user
from api.core import clover
from api.core.security import hash_withdrawn_email
from api.db.models import (
    CharacterVersionDetail, Comment, CommentLike, CommentMention, CommentModerationAction,
    CommentMute, CommentNotificationPreference, CommentReport, Content, ContentVersion,
    Notification, User, WithdrawnEmail,
)
from api.db.session import get_db_session
from api.main import app
from api.session.store import revoke_user_sessions
from comment_factories import _comment_payload, _make_comment, _make_comment_content
from factories import _login_as, _make_user


@dataclass
class _Committed:
    factory: async_sessionmaker[AsyncSession]
    creator: User
    author: User
    content: Content
    root: Comment


@pytest_asyncio.fixture
async def committed_comments(db_engine: AsyncEngine) -> AsyncGenerator[_Committed, None]:
    """잠금 검증은 rollback 공유 connection을 우회하고 실제 별도 connection들에서 commit한다."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    creator, author = _make_user(), _make_user()
    original_emails = [creator.email, author.email]
    async with factory() as db:
        db.add_all([creator, author])
        await db.flush()
        content = await _make_comment_content(db, creator.id)
        root = await _make_comment(db, content, creator.id)
        await db.commit()
    try:
        yield _Committed(factory, creator, author, content, root)
    finally:
        async with factory() as db:
            ids = sa.select(Comment.id).where(Comment.content_id == content.id)
            await db.execute(sa.delete(Notification).where(Notification.content_id == content.id))
            await db.execute(sa.delete(CommentModerationAction).where(CommentModerationAction.comment_id.in_(ids)))
            await db.execute(sa.delete(CommentReport).where(CommentReport.comment_id.in_(ids)))
            await db.execute(sa.delete(CommentMention).where(CommentMention.comment_id.in_(ids)))
            await db.execute(sa.delete(CommentLike).where(CommentLike.comment_id.in_(ids)))
            await db.execute(sa.update(Content).where(Content.id == content.id).values(pinned_comment_id=None, current_published_version_id=None))
            await db.execute(sa.delete(Comment).where(Comment.content_id == content.id))
            versions = sa.select(ContentVersion.id).where(ContentVersion.content_id == content.id)
            await db.execute(sa.delete(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id.in_(versions)))
            await db.execute(sa.delete(ContentVersion).where(ContentVersion.content_id == content.id))
            await db.execute(sa.delete(Content).where(Content.id == content.id))
            user_ids = [creator.id, author.id]
            await db.execute(sa.delete(CommentMute).where(sa.or_(CommentMute.viewer_user_id.in_(user_ids), CommentMute.target_user_id.in_(user_ids))))
            await db.execute(sa.delete(CommentNotificationPreference).where(CommentNotificationPreference.user_id.in_(user_ids)))
            await db.execute(sa.delete(WithdrawnEmail).where(WithdrawnEmail.email_hmac.in_([hash_withdrawn_email(e) for e in original_emails])))
            await db.execute(sa.delete(User).where(User.id.in_(user_ids)))
            await db.commit()
        for user_id in (creator.id, author.id):
            await revoke_user_sessions(user_id)


def _client(*, raise_app_exceptions: bool = False) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions), base_url="http://testserver")


@pytest.mark.parametrize("action", ["create", "like", "pin"])
async def test_same_desired_request_on_independent_connections_is_idempotent(
    committed_comments: _Committed, action: str
) -> None:
    """서로 다른 DB connection의 동일 요청이 중복 댓글·알림·좋아요나 고정 실패를 만들지 않는다."""
    fixture = committed_comments
    async with _client() as client:
        await _login_as(client, fixture.creator.id if action == "pin" else fixture.author.id)
        payload = _comment_payload()
        async def submit() -> httpx.Response:
            if action == "create":
                return await client.post(f"/contents/{fixture.content.id}/comments", json=payload)
            if action == "like":
                return await client.put(f"/comments/{fixture.root.id}/like")
            return await client.put(f"/contents/{fixture.content.id}/pinned-comment", json={"commentId": str(fixture.root.id)})
        responses = await asyncio.gather(*(submit() for _ in range(5)))
        assert [r.status_code for r in responses].count(201) == (1 if action == "create" else 0)
        assert all(r.status_code in (200, 201) for r in responses)
    async with fixture.factory() as db:
        if action == "create":
            assert await db.scalar(sa.select(sa.func.count()).select_from(Comment).where(Comment.author_user_id == fixture.author.id)) == 1
            assert await db.scalar(sa.select(sa.func.count()).select_from(Notification).where(Notification.content_id == fixture.content.id)) == 1
        elif action == "like":
            assert await db.scalar(sa.select(sa.func.count()).select_from(CommentLike).where(CommentLike.comment_id == fixture.root.id)) == 1
        else:
            assert await db.scalar(sa.select(Content.pinned_comment_id).where(Content.id == fixture.content.id)) == fixture.root.id


@pytest.mark.parametrize("action", ["create", "like"])
async def test_withdraw_rejects_participation_already_authenticated_before_commit(
    committed_comments: _Committed, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """파기 이후에 늦게 저장되려는 댓글·좋아요가 탈퇴 commit 뒤 active 재검사로 거부된다."""
    fixture = committed_comments
    entered, release = asyncio.Event(), asyncio.Event()
    actor_lock_entered = asyncio.Event()
    real_burn = clover.burn_all
    real_actor_lock = lock_active_user

    async def observed_actor_lock(*args: Any, **kwargs: Any) -> User:
        actor_lock_entered.set()
        return await real_actor_lock(*args, **kwargs)

    async def stopped_burn(*args: Any, **kwargs: Any) -> None:
        entered.set()
        await release.wait()
        await real_burn(*args, **kwargs)

    monkeypatch.setattr(clover, "burn_all", stopped_burn)
    monkeypatch.setattr(write if action == "create" else actions, "lock_active_user", observed_actor_lock)
    async with _client() as withdrawing, _client() as participating:
        await _login_as(withdrawing, fixture.author.id)
        await _login_as(participating, fixture.author.id)
        withdrawal = asyncio.create_task(withdrawing.delete("/me"))
        await asyncio.wait_for(entered.wait(), 3)
        participation = asyncio.create_task(
            participating.post(f"/contents/{fixture.content.id}/comments", json=_comment_payload())
            if action == "create" else participating.put(f"/comments/{fixture.root.id}/like")
        )
        try:
            await asyncio.wait_for(actor_lock_entered.wait(), 3)
            assert not participation.done()
            release.set()
            removed, rejected = await asyncio.wait_for(asyncio.gather(withdrawal, participation), 5)
            assert removed.status_code == 204
            assert rejected.status_code == 401
        finally:
            release.set()
            await asyncio.gather(withdrawal, participation, return_exceptions=True)
    async with fixture.factory() as db:
        assert await db.scalar(sa.select(sa.func.count()).select_from(Comment).where(Comment.author_user_id == fixture.author.id, Comment.deleted_at.is_(None))) == 0
        assert await db.scalar(sa.select(sa.func.count()).select_from(CommentLike).where(CommentLike.user_id == fixture.author.id)) == 0


async def test_creator_withdraw_and_other_author_creation_notification_do_not_deadlock(
    committed_comments: _Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content 보유 댓글 생성의 알림 FK와 제작자 탈퇴의 회원→Content 잠금이 교착하지 않는다."""
    fixture = committed_comments
    entered, release = asyncio.Event(), asyncio.Event()
    real_notifications = write._creation_notifications
    pids: dict[str, int] = {}

    async def session_override(request: Request) -> AsyncGenerator[AsyncSession, None]:
        async with fixture.factory() as db:
            pids[request.headers["x-test-role"]] = await db.scalar(sa.select(sa.func.pg_backend_pid())) or 0
            yield db

    async def stopped_notifications(*args: Any, **kwargs: Any) -> None:
        entered.set()
        await release.wait()
        await real_notifications(*args, **kwargs)

    monkeypatch.setattr(write, "_creation_notifications", stopped_notifications)
    app.dependency_overrides[get_db_session] = session_override
    try:
        async with _client(raise_app_exceptions=True) as creating, _client(raise_app_exceptions=True) as withdrawing:
            await _login_as(creating, fixture.author.id)
            await _login_as(withdrawing, fixture.creator.id)
            creation = asyncio.create_task(creating.post(f"/contents/{fixture.content.id}/comments", json=_comment_payload(), headers={"x-test-role": "create"}))
            await asyncio.wait_for(entered.wait(), 3)
            withdrawal = asyncio.create_task(withdrawing.delete("/me", headers={"x-test-role": "withdraw"}))
            try:
                async with asyncio.timeout(3), fixture.factory() as observer:
                    while True:
                        await observer.execute(sa.text("SELECT pg_stat_clear_snapshot()"))
                        waits = await observer.scalar(sa.text(
                            "SELECT wait_event_type='Lock' AND query LIKE '%contents%' FROM pg_stat_activity WHERE pid=:pid"
                        ), {"pid": pids.get("withdraw", 0)})
                        if waits:
                            break
                        await asyncio.sleep(0.01)
                release.set()
                created, removed = await asyncio.wait_for(asyncio.gather(creation, withdrawal, return_exceptions=True), 8)
                assert isinstance(created, httpx.Response), repr(created)
                assert isinstance(removed, httpx.Response), repr(removed)
                assert created.status_code == 201
                assert removed.status_code == 204
            finally:
                release.set()
                await asyncio.gather(creation, withdrawal, return_exceptions=True)
    finally:
        app.dependency_overrides.pop(get_db_session, None)
