import uuid
from datetime import datetime, timezone, UTC

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import AssetStatus
from factories import _login_as, _make_asset, _make_user


async def test_get_user_profile_returns_nickname_bio_and_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(bio="안녕하세요")
    db_session.add(user)
    await db_session.flush()
    asset = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    user.profile_image_asset_id = asset.id
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body.pop("profileImageUrl").startswith("http")
    assert body == {
        "nickname": "테스터",
        "bio": "안녕하세요",
        "profileImageAssetId": str(asset.id),
    }


async def test_get_user_profile_works_without_login(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/profile")
    assert resp.status_code == 200
    assert resp.json()["profileImageUrl"] is None


async def test_get_user_profile_returns_404_for_unknown_user(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/users/{uuid.uuid4()}/profile")
    assert resp.status_code == 404


async def test_get_user_profile_returns_404_for_deleted_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(deleted_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/profile")
    assert resp.status_code == 404


async def test_update_my_profile_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(
        "/me/profile", json={"nickname": "새이름", "bio": None, "profileImageAssetId": None}
    )
    assert resp.status_code == 401


async def test_update_my_profile_updates_own_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(
        "/me/profile",
        json={"nickname": "새이름", "bio": "새소개", "profileImageAssetId": str(asset.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.pop("profileImageUrl").startswith("http")
    assert body == {
        "nickname": "새이름",
        "bio": "새소개",
        "profileImageAssetId": str(asset.id),
    }

    other_view = await db_client.get(f"/users/{user.id}/profile")
    assert other_view.json()["nickname"] == "새이름"


async def test_update_my_profile_rejects_asset_owned_by_another_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    other = _make_user()
    db_session.add_all([user, other])
    await db_session.flush()
    other_asset = await _make_asset(db_session, other.id, status=AssetStatus.READY)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(
        "/me/profile",
        json={"nickname": "새이름", "bio": None, "profileImageAssetId": str(other_asset.id)},
    )
    assert resp.status_code == 400


async def test_update_my_profile_rejects_pending_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    pending_asset = await _make_asset(db_session, user.id, status=AssetStatus.PENDING)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(
        "/me/profile",
        json={"nickname": "새이름", "bio": None, "profileImageAssetId": str(pending_asset.id)},
    )
    assert resp.status_code == 400
