import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.media import Asset, AssetKind, AssetStatus


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
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def test_generated_images_requires_login(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()

    resp = await api_client.get("/me/generated-images")
    assert resp.status_code == 401


async def test_generated_images_empty_when_none_generated(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me/generated-images")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_generated_images_lists_own_ready_generated_assets_newest_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.commit()
    await _login_as(db_client, owner.id)

    now = datetime.now(timezone.utc)
    older_id = uuid.uuid4()
    newer_id = uuid.uuid4()
    db_session.add_all(
        [
            Asset(
                id=older_id,
                owner_user_id=owner.id,
                storage_key=f"assets/generated/{older_id}.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
                created_at=now - timedelta(minutes=5),
            ),
            Asset(
                id=newer_id,
                owner_user_id=owner.id,
                storage_key=f"assets/generated/{newer_id}.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
                created_at=now,
            ),
            # excluded: not GENERATED
            Asset(
                id=uuid.uuid4(),
                owner_user_id=owner.id,
                storage_key="assets/original/other.png",
                kind=AssetKind.ORIGINAL,
                status=AssetStatus.READY,
            ),
            # excluded: still pending
            Asset(
                id=uuid.uuid4(),
                owner_user_id=owner.id,
                storage_key="assets/generated/pending.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.PENDING,
            ),
            # excluded: another user's generated asset
            Asset(
                id=uuid.uuid4(),
                owner_user_id=other.id,
                storage_key="assets/generated/other-user.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
            ),
        ]
    )
    await db_session.commit()

    resp = await db_client.get("/me/generated-images")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["assetId"] for item in body] == [str(newer_id), str(older_id)]
    for item in body:
        assert item["imageUrl"].startswith("http")
        assert "createdAt" in item
