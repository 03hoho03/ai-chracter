import uuid
from datetime import date, datetime, timezone

import boto3
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.auth import User
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.images.jobs import ImageGenerationJobStatus, create_job, update_job


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


async def test_get_job_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/images/jobs/{uuid.uuid4().hex}")
    assert resp.status_code == 401


async def test_get_job_unknown_id_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.get(f"/images/jobs/{uuid.uuid4().hex}")
    assert resp.status_code == 404


async def test_get_job_owned_by_another_user_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.commit()

    job = await create_job(owner.id, requested_count=1)

    await _login_as(db_client, other.id)
    resp = await db_client.get(f"/images/jobs/{job.job_id}")
    assert resp.status_code == 404


async def test_get_job_in_progress_reports_partial_state(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    job = await create_job(user.id, requested_count=2)
    await update_job(job.job_id, status=ImageGenerationJobStatus.RUNNING)

    resp = await db_client.get(f"/images/jobs/{job.job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["requestedCount"] == 2
    assert body["completedCount"] == 0
    assert body["images"] == []
    assert body["error"] is None


async def test_get_job_succeeded_returns_presigned_image_urls(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    job = await create_job(user.id, requested_count=1)
    asset_id = uuid.uuid4()
    storage_key = f"assets/generated/{asset_id}.png"
    db_session.add(
        Asset(
            id=asset_id,
            owner_user_id=user.id,
            storage_key=storage_key,
            kind=AssetKind.GENERATED,
            status=AssetStatus.READY,
        )
    )
    await db_session.commit()

    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=b"fake-png-bytes", ContentType="image/png")

    await update_job(job.job_id, status=ImageGenerationJobStatus.RUNNING)
    await update_job(job.job_id, completed_increment=1, asset_id=asset_id)
    await update_job(job.job_id, status=ImageGenerationJobStatus.SUCCEEDED)

    resp = await db_client.get(f"/images/jobs/{job.job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["completedCount"] == 1
    assert len(body["images"]) == 1
    assert body["images"][0]["assetId"] == str(asset_id)
    assert body["images"][0]["imageUrl"].startswith("http")


async def test_get_job_failed_reports_error(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    job = await create_job(user.id, requested_count=1)
    await update_job(
        job.job_id, status=ImageGenerationJobStatus.FAILED, error="이미지 생성에 모두 실패했습니다"
    )

    resp = await db_client.get(f"/images/jobs/{job.job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["images"] == []
    assert body["error"] == "이미지 생성에 모두 실패했습니다"
