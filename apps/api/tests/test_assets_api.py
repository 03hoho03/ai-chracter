import uuid
from datetime import date, datetime, timezone

import boto3
import httpx
import pytest
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.schemas import UPLOAD_SIZE_LIMIT_BYTES, AssetPurpose
from api.core.config import settings
from api.db.models.auth import User
from api.db.models.media import Asset, AssetStatus


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


async def test_presigned_upload_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    assert resp.status_code == 401


async def test_presigned_upload_returns_url_and_creates_pending_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["uploadUrl"].startswith("http")
    assert body["expiresAt"]

    asset = await db_session.get(Asset, uuid.UUID(body["assetId"]))
    assert asset is not None
    assert asset.owner_user_id == user.id
    assert asset.status == AssetStatus.PENDING


async def test_complete_marks_asset_ready_once_object_is_uploaded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    presign_resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    asset_id = presign_resp.json()["assetId"]

    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=b"fake-image-bytes")

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 200
    assert complete_resp.json() == {"assetId": asset_id, "status": "ready"}

    await db_session.refresh(asset)
    assert asset.status == AssetStatus.READY


async def test_complete_rejects_oversized_object_and_cleans_up(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    presign_resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    asset_id = presign_resp.json()["assetId"]

    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    storage_key = asset.storage_key
    max_bytes = UPLOAD_SIZE_LIMIT_BYTES[AssetPurpose.PROFILE_IMAGE]
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=b"x" * (max_bytes + 1))

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 400
    assert complete_resp.json()["detail"] == {"maxBytes": max_bytes, "actualBytes": max_bytes + 1}

    with pytest.raises(ClientError) as exc_info:
        s3.head_object(Bucket=settings.s3_bucket_name, Key=storage_key)
    assert exc_info.value.response["Error"]["Code"] == "404"
    assert await db_session.get(Asset, uuid.UUID(asset_id)) is None


async def test_complete_before_upload_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    presign_resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    asset_id = presign_resp.json()["assetId"]

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 409


async def test_complete_rejects_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add(owner)
    db_session.add(other)
    await db_session.flush()

    await _login_as(db_client, owner.id)
    presign_resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    asset_id = presign_resp.json()["assetId"]

    await _login_as(db_client, other.id)
    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 403


async def test_complete_unknown_asset_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/assets/{uuid.uuid4()}/complete")
    assert resp.status_code == 404
