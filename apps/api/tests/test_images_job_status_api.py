import uuid
from datetime import timezone

import boto3
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.images.jobs import ImageGenerationJobStatus, create_job, update_job
from factories import _login_as, _make_user


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
    # 차단이 없으면 blocked 필드는 기본값(0/None)으로 내려야
    # 한다 — 안 그러면 FE의 exhaustive switch가 없는 차단을 있는 것으로 오판한다.
    assert body["blockedCount"] == 0
    assert body["blockedReason"] is None


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


async def test_get_job_reports_blocked_count_and_reason(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`ImageJobStatusResponse`가 blockedCount/blockedReason을
    camelCase로 내리지 않으면, 내부 잡 레코드가 차단을 정확히 집계해도 FE는 부분
    차단을 절대 알 수 없다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    job = await create_job(user.id, requested_count=2)
    await update_job(
        job.job_id,
        status=ImageGenerationJobStatus.SUCCEEDED,
        blocked_count=1,
        blocked_reason="image",
    )

    resp = await db_client.get(f"/images/jobs/{job.job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["blockedCount"] == 1
    assert body["blockedReason"] == "image"


async def test_get_job_reports_input_error_count_and_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """BE가 잡에 저장한 input_error_count/input_error가
    `inputErrorCount`/`inputError`로 camelCase 직렬화돼 FE까지 그대로 나가는지 지킨다 —
    `get_image_job`이 이 두 값을 응답에 배선하지 않으면 이 단언이 깨져야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    job = await create_job(user.id, requested_count=2)
    await update_job(
        job.job_id,
        status=ImageGenerationJobStatus.SUCCEEDED,
        input_error_count=1,
        input_error="too_long",
    )

    resp = await db_client.get(f"/images/jobs/{job.job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["inputErrorCount"] == 1
    assert body["inputError"] == "too_long"


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
