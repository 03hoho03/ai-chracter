import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import (
    AdminUser,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    User,
)

DAY0 = date(2030, 3, 10)
DAY1 = DAY0 + timedelta(days=1)
DAY2 = DAY0 + timedelta(days=2)


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


async def _make_chat_room(db_session: AsyncSession, *, user_id: uuid.UUID) -> ChatRoom:
    content = Content(
        creator_user_id=user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(content_id=content.id, detail_description="설명")
    db_session.add(version)
    await db_session.flush()

    room = ChatRoom(user_id=user_id, content_id=content.id, content_version_id=version.id)
    db_session.add(room)
    await db_session.flush()
    return room


def _message(room_id: uuid.UUID, *, day: date, role: ChatMessageRole = ChatMessageRole.USER) -> ChatMessage:
    return ChatMessage(
        chat_room_id=room_id,
        role=role,
        content="메시지",
        created_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
    )


async def _create_admin(db_session: AsyncSession, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password": "adminpassword123",
    }
    defaults.update(overrides)
    admin = AdminUser(
        email=str(defaults["email"]), password_hash=hash_password(str(defaults["password"]))
    )
    db_session.add(admin)
    await db_session.flush()
    return defaults


async def _login_as_admin(db_client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


async def test_usage_metrics_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/admin/usage-metrics?from={DAY0.isoformat()}&to={DAY2.isoformat()}")
    assert resp.status_code == 401


async def test_regular_user_session_cannot_access_usage_metrics(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    resp = await db_client.post("/dev/session-echo", json={"data": {"user_id": str(user.id)}})
    assert resp.status_code == 201

    resp = await db_client.get(f"/admin/usage-metrics?from={DAY0.isoformat()}&to={DAY2.isoformat()}")
    assert resp.status_code == 401


async def test_usage_metrics_computes_per_user_averages_and_trend(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_a = _make_user()
    user_b = _make_user()
    db_session.add_all([user_a, user_b])
    await db_session.flush()
    room_a = await _make_chat_room(db_session, user_id=user_a.id)
    room_b = await _make_chat_room(db_session, user_id=user_b.id)

    db_session.add_all(
        [
            # DAY0: user_a sends 2 messages (plus an assistant reply that must not count)
            _message(room_a.id, day=DAY0),
            _message(room_a.id, day=DAY0),
            _message(room_a.id, day=DAY0, role=ChatMessageRole.ASSISTANT),
            # DAY1: user_b sends 1 message
            _message(room_b.id, day=DAY1),
            # DAY2: both users send 1 message each
            _message(room_a.id, day=DAY2),
            _message(room_b.id, day=DAY2),
            # outside the queried range entirely
            _message(room_a.id, day=DAY0 - timedelta(days=5)),
            _message(room_b.id, day=DAY2 + timedelta(days=5)),
        ]
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/usage-metrics?from={DAY0.isoformat()}&to={DAY2.isoformat()}")
    assert resp.status_code == 200
    body = resp.json()

    # total 5 user messages / 2 active users / 3 days in range
    assert body["dailyAveragePerUser"] == 5 / 2 / 3
    assert body["monthlyAveragePerUser"] == (5 / 2 / 3) * 30
    assert body["trend"] == [
        {"date": DAY0.isoformat(), "messageCount": 2},
        {"date": DAY1.isoformat(), "messageCount": 1},
        {"date": DAY2.isoformat(), "messageCount": 2},
    ]


async def test_usage_metrics_rejects_inverted_range(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/usage-metrics?from={DAY2.isoformat()}&to={DAY0.isoformat()}")
    assert resp.status_code == 400


async def test_usage_metrics_returns_zero_for_no_activity(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/usage-metrics?from={DAY0.isoformat()}&to={DAY0.isoformat()}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dailyAveragePerUser"] == 0.0
    assert body["monthlyAveragePerUser"] == 0.0
    assert body["trend"] == [{"date": DAY0.isoformat(), "messageCount": 0}]
