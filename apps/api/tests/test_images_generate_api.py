import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import boto3
import httpx
import pytest
import sqlalchemy as sa
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.auth import User
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.images.jobs import ImageGenerationJob, ImageGenerationJobStatus, get_job
from api.llm.dependencies import get_image_client
from api.llm.image import GeminiImageClient
from api.main import app


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


def _make_image_client(monkeypatch: pytest.MonkeyPatch, generate_content: Any) -> GeminiImageClient:
    client = GeminiImageClient(api_key="test-key")
    fake_client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(client, "_client", fake_client)
    return client


def _image_response(data: bytes = b"fake-png-bytes", mime_type: str = "image/png") -> SimpleNamespace:
    return SimpleNamespace(
        prompt_feedback=None,
        candidates=[
            genai_types.Candidate(
                finish_reason=genai_types.FinishReason.STOP,
                content=genai_types.Content(
                    parts=[genai_types.Part(inline_data=genai_types.Blob(data=data, mime_type=mime_type))]
                ),
            )
        ],
    )


def _api_error() -> genai_errors.APIError:
    return genai_errors.APIError(code=503, response_json={"error": {"message": "unavailable"}})


def _override_image_client(client: GeminiImageClient) -> None:
    app.dependency_overrides[get_image_client] = lambda: client


def _clear_image_override() -> None:
    app.dependency_overrides.pop(get_image_client, None)


async def _wait_for_job_completion(job_id: str, owner_user_id: uuid.UUID) -> ImageGenerationJob:
    for _ in range(200):
        job = await get_job(job_id, owner_user_id)
        assert job is not None
        if job.status in (ImageGenerationJobStatus.SUCCEEDED, ImageGenerationJobStatus.FAILED):
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("job did not complete in time")


def _generate_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt": "a cat wizard",
        "style": "anime",
        "aspectRatio": "1:1",
        "count": 1,
    }
    payload.update(overrides)
    return payload


async def test_generate_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/images/generate", json=_generate_payload())
    assert resp.status_code == 401


async def test_generate_rejects_empty_prompt(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/images/generate", json=_generate_payload(prompt=""))
    assert resp.status_code == 422


async def test_generate_rejects_count_out_of_range(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/images/generate", json=_generate_payload(count=5))
    assert resp.status_code == 422


async def test_generate_rejects_unknown_style(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/images/generate", json=_generate_payload(style="cubism"))
    assert resp.status_code == 422


async def test_generate_rejects_unknown_aspect_ratio(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/images/generate", json=_generate_payload(aspectRatio="2:1"))
    assert resp.status_code == 422


async def test_generate_creates_assets_and_completes_job(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    async def generate_content(**_: Any) -> SimpleNamespace:
        return _image_response()

    client = _make_image_client(monkeypatch, generate_content)
    _override_image_client(client)
    try:
        resp = await db_client.post("/images/generate", json=_generate_payload(count=2))
    finally:
        _clear_image_override()
    assert resp.status_code == 202
    job_id = resp.json()["jobId"]

    job = await _wait_for_job_completion(job_id, user.id)
    assert job.status == ImageGenerationJobStatus.SUCCEEDED
    assert job.completed_count == 2
    assert len(job.asset_ids) == 2

    assets = (
        (await db_session.execute(sa.select(Asset).where(Asset.id.in_(job.asset_ids))))
        .scalars()
        .all()
    )
    assert len(assets) == 2
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    for asset in assets:
        assert asset.owner_user_id == user.id
        assert asset.kind == AssetKind.GENERATED
        assert asset.status == AssetStatus.READY
        s3_object = s3.get_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key)
        assert s3_object["Body"].read() == b"fake-png-bytes"


async def test_generate_partial_failure_still_succeeds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    call_count = {"n": 0}

    async def generate_content(**_: Any) -> SimpleNamespace:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise _api_error()
        return _image_response()

    client = _make_image_client(monkeypatch, generate_content)
    _override_image_client(client)
    try:
        resp = await db_client.post("/images/generate", json=_generate_payload(count=2))
    finally:
        _clear_image_override()
    assert resp.status_code == 202
    job_id = resp.json()["jobId"]

    job = await _wait_for_job_completion(job_id, user.id)
    assert job.status == ImageGenerationJobStatus.SUCCEEDED
    assert job.completed_count == 1
    assert len(job.asset_ids) == 1


async def test_generate_total_failure_marks_job_failed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    async def generate_content(**_: Any) -> SimpleNamespace:
        raise _api_error()

    client = _make_image_client(monkeypatch, generate_content)
    _override_image_client(client)
    try:
        resp = await db_client.post("/images/generate", json=_generate_payload(count=2))
    finally:
        _clear_image_override()
    assert resp.status_code == 202
    job_id = resp.json()["jobId"]

    job = await _wait_for_job_completion(job_id, user.id)
    assert job.status == ImageGenerationJobStatus.FAILED
    assert job.completed_count == 0
    assert job.asset_ids == []
    assert job.error is not None
