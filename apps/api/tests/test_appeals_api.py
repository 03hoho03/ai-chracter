import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Appeal, AppealStatus, AppealTargetKind, User


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


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    """Logs in via the existing dev session-echo endpoint (no real /auth/login yet)."""
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def test_create_appeal_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/appeals",
        json={"targetKind": "publish-rejection", "targetId": str(uuid.uuid4()), "reasonText": "오탐입니다."},
    )
    assert resp.status_code == 401


async def test_create_appeal_for_publish_rejection_stores_pending_appeal(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    content_id = uuid.uuid4()
    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/appeals",
        json={"targetKind": "publish-rejection", "targetId": str(content_id), "reasonText": "오탐입니다."},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    appeal_id = uuid.UUID(body["appealId"])

    appeal = await db_session.get(Appeal, appeal_id)
    assert appeal is not None
    assert appeal.user_id == user.id
    assert appeal.target_kind == AppealTargetKind.PUBLISH_REJECTION
    assert appeal.target_id == content_id
    assert appeal.reason_text == "오탐입니다."
    assert appeal.status == AppealStatus.PENDING


async def test_create_appeal_for_moderation_action(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    action_id = uuid.uuid4()
    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/appeals",
        json={"targetKind": "moderation-action", "targetId": str(action_id), "reasonText": "이의 있습니다."},
    )
    assert resp.status_code == 201

    appeal = await db_session.scalar(sa.select(Appeal).where(Appeal.user_id == user.id))
    assert appeal is not None
    assert appeal.target_kind == AppealTargetKind.MODERATION_ACTION
    assert appeal.target_id == action_id


async def test_create_appeal_rejects_blank_reason_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/appeals",
        json={"targetKind": "publish-rejection", "targetId": str(uuid.uuid4()), "reasonText": ""},
    )
    assert resp.status_code == 422
