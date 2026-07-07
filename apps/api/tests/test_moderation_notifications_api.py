import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    AdminUser,
    Content,
    ContentTarget,
    ContentType,
    ContentVisibility,
    Genre,
    ModerationAction,
    ModerationActionType,
    ModerationStatus,
    Notification,
    User,
)


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(timezone.utc),
        "privacy_agreed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_admin(**overrides: object) -> AdminUser:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password_hash": "hashed",
    }
    defaults.update(overrides)
    return AdminUser(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    """Logs in via the existing dev session-echo endpoint (no real /auth/login yet)."""
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _make_content(db_session: AsyncSession, creator_user_id: uuid.UUID) -> Content:
    genre = (await db_session.execute(sa.select(Genre).limit(1))).scalars().one()
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def _make_action(db_session: AsyncSession, content: Content) -> ModerationAction:
    admin = _make_admin()
    db_session.add(admin)
    await db_session.flush()
    action = ModerationAction(
        content_id=content.id, admin_id=admin.id, action=ModerationActionType.RESTRICT
    )
    db_session.add(action)
    await db_session.flush()
    return action


async def _make_notification(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: Content,
    action: ModerationAction,
    created_at: datetime | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        content_id=content.id,
        action_id=action.id,
        reason_category="adult",
        admin_comment="부적절한 콘텐츠로 판단되어 이용제한 처리되었습니다.",
    )
    db_session.add(notification)
    await db_session.flush()
    if created_at is not None:
        await db_session.execute(
            sa.update(Notification).where(Notification.id == notification.id).values(created_at=created_at)
        )
        await db_session.refresh(notification)
    return notification


async def test_list_notifications_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/notifications")
    assert resp.status_code == 401


async def test_list_notifications_returns_empty_list_when_none_exist(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_notifications_returns_own_notifications_newest_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, user.id)
    action = await _make_action(db_session, content)

    now = datetime.now(timezone.utc)
    older = await _make_notification(
        db_session, user_id=user.id, content=content, action=action, created_at=now - timedelta(hours=1)
    )
    newer = await _make_notification(
        db_session, user_id=user.id, content=content, action=action, created_at=now
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200

    body = resp.json()
    assert [item["id"] for item in body] == [str(newer.id), str(older.id)]
    first = body[0]
    assert first["type"] == "moderation-action"
    assert first["contentId"] == str(content.id)
    assert first["actionId"] == str(action.id)
    assert first["reasonCategory"] == "adult"
    assert first["adminComment"]
    assert first["read"] is False


async def test_list_notifications_excludes_other_users_notifications(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_content(db_session, other.id)
    action = await _make_action(db_session, content)
    await _make_notification(db_session, user_id=other.id, content=content, action=action)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_mark_notification_read_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(f"/notifications/{uuid.uuid4()}/read")
    assert resp.status_code == 401


async def test_mark_notification_read_marks_own_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, user.id)
    action = await _make_action(db_session, content)
    notification = await _make_notification(db_session, user_id=user.id, content=content, action=action)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(f"/notifications/{notification.id}/read")
    assert resp.status_code == 200
    assert resp.json()["read"] is True

    await db_session.refresh(notification)
    assert notification.read is True


async def test_mark_notification_read_rejects_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_content(db_session, owner.id)
    action = await _make_action(db_session, content)
    notification = await _make_notification(db_session, user_id=owner.id, content=content, action=action)
    await db_session.commit()

    await _login_as(db_client, other.id)
    resp = await db_client.patch(f"/notifications/{notification.id}/read")
    assert resp.status_code == 403

    await db_session.refresh(notification)
    assert notification.read is False


async def test_mark_notification_read_unknown_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(f"/notifications/{uuid.uuid4()}/read")
    assert resp.status_code == 404
