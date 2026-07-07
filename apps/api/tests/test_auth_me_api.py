import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code
from api.core.security import verify_password
from api.db.models import (
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    User,
)


def _signup_payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "테스터",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
    }
    defaults.update(overrides)
    return defaults


async def _signup_and_login(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    payload = _signup_payload(**overrides)
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    verify_resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert verify_resp.status_code == 200

    login_resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204
    return payload


async def test_change_password_updates_hash_and_allows_relogin(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)

    resp = await db_client.patch(
        "/me/password",
        json={"currentPassword": payload["password"], "newPassword": "newpassword456"},
    )
    assert resp.status_code == 204

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.password_hash is not None
    assert verify_password("newpassword456", user.password_hash)

    old_password_login = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert old_password_login.status_code == 401

    new_password_login = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": "newpassword456"}
    )
    assert new_password_login.status_code == 204


async def test_change_password_rejects_wrong_current_password(db_client: httpx.AsyncClient) -> None:
    await _signup_and_login(db_client)

    resp = await db_client.patch(
        "/me/password",
        json={"currentPassword": "wrong-password", "newPassword": "newpassword456"},
    )
    assert resp.status_code == 400


async def test_change_password_requires_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(
        "/me/password",
        json={"currentPassword": "password123", "newPassword": "newpassword456"},
    )
    assert resp.status_code == 401


async def test_withdraw_soft_deletes_hides_content_and_deletes_own_chat_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    genre = (await db_session.execute(sa.select(Genre).limit(1))).scalar_one()

    content = Content(
        creator_user_id=user.id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    published_version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(timezone.utc),
        detail_description="설명",
    )
    draft_version = ContentVersion(
        content_id=content.id,
        version_number=None,
        published_at=None,
        detail_description="초안",
    )
    db_session.add_all([published_version, draft_version])
    await db_session.flush()

    own_room = ChatRoom(
        user_id=user.id, content_id=content.id, content_version_id=published_version.id
    )
    db_session.add(own_room)
    await db_session.flush()
    db_session.add(
        ChatMessage(chat_room_id=own_room.id, role=ChatMessageRole.USER, content="안녕하세요")
    )
    db_session.add(
        ChatRoomStat(chat_room_id=own_room.id, stat_entity_id=uuid.uuid4(), current_value=1)
    )

    other_user = User(
        email=f"viewer-{uuid.uuid4()}@example.com",
        nickname="뷰어",
        birth_date=date(2000, 1, 1),
        terms_agreed_at=datetime.now(timezone.utc),
        privacy_agreed_at=datetime.now(timezone.utc),
    )
    db_session.add(other_user)
    await db_session.flush()
    other_room = ChatRoom(
        user_id=other_user.id, content_id=content.id, content_version_id=published_version.id
    )
    db_session.add(other_room)
    await db_session.commit()

    own_room_id = own_room.id
    other_room_id = other_room.id
    content_id = content.id
    draft_version_id = draft_version.id

    resp = await db_client.delete("/me")
    assert resp.status_code == 204

    reloaded_user = await db_session.scalar(select(User).where(User.id == user.id))
    assert reloaded_user is not None
    assert reloaded_user.deleted_at is not None

    reloaded_content = await db_session.get(Content, content_id)
    assert reloaded_content is not None
    assert reloaded_content.visibility == ContentVisibility.PRIVATE

    # The draft (unpublished) version is preserved, not deleted.
    assert await db_session.get(ContentVersion, draft_version_id) is not None

    assert await db_session.get(ChatRoom, own_room_id) is None
    remaining_messages = (
        await db_session.execute(
            select(ChatMessage).where(ChatMessage.chat_room_id == own_room_id)
        )
    ).scalars().all()
    assert remaining_messages == []
    remaining_stats = (
        await db_session.execute(
            select(ChatRoomStat).where(ChatRoomStat.chat_room_id == own_room_id)
        )
    ).scalars().all()
    assert remaining_stats == []

    # Another user's chat room against the same (now-private) content survives.
    assert await db_session.get(ChatRoom, other_room_id) is not None

    me_after = await db_client.get("/me")
    assert me_after.status_code == 401

    login_after = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_after.status_code == 401


async def test_withdraw_requires_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.delete("/me")
    assert resp.status_code == 401
