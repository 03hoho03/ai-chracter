import asyncio
import io
import uuid
from collections.abc import Callable
from datetime import timezone

import boto3
import httpx
import pytest
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.s3 import build_thumbnail_key
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.images.jobs import ImageGenerationJob, ImageGenerationJobStatus, get_job
from api.llm.client import LLMClientError
from api.llm.dependencies import get_image_client
from api.llm.image import ImageClient, ImageStylePreset
from api.llm.local_image import LocalCapabilities, ModelCapability
from api.main import app
from factories import _login_as, _make_user


def _png_bytes(width: int = 64, height: int = 64) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 40, 200)).save(output, format="PNG")
    return output.getvalue()


class _FakeImageClient(ImageClient):
    """`generate`가 매 호출마다 (bytes, mime)을 만들거나 지정된 예외를 던진다 — 파이프라인
    (라우터→잡→S3→썸네일) 테스트가 성공/부분실패/전체실패/예기치 못한 오류 네 시나리오를
    이 콜백 하나로 표현한다. `tests/test_seed_image_prompts.py`의 `_FakeImageClient` 패턴을
    따르되, 여기는 호출마다 다른 결과가 필요해 콜백을 받는다."""

    def __init__(self, model_id: str, *, generate: Callable[[], tuple[bytes, str]]) -> None:
        self._model_id = model_id
        self._generate = generate

    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        return self._generate()


def _override_image_client(generate: Callable[[], tuple[bytes, str]]) -> None:
    # get_image_client는 모델 id → ImageClient 팩토리를 반환한다. 테스트는 모델과 무관하게
    # 같은 fake 콜백을 쓰는 팩토리로 오버라이드한다.
    app.dependency_overrides[get_image_client] = lambda: (
        lambda model_id: _FakeImageClient(model_id, generate=generate)
    )


def _clear_image_override() -> None:
    app.dependency_overrides.pop(get_image_client, None)


_READY_CAPABILITIES = LocalCapabilities(
    ready=True,
    models=(
        ModelCapability(
            model_id="v1",
            styles=("base",),
            aspect_ratios=("1:1", "4:3", "3:4", "16:9", "9:16", "2:3"),
        ),
    ),
)


def _stub_capabilities_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """local-image-gen-techspec.md LT-6: `generate_images`가 가용성 사전 확인을 맨 앞에
    두므로, 이 확인을 통과시키지 않으면 아래 파이프라인 테스트들이 202 대신 전부 503을
    받는다. `api.images.router.get_capabilities`(라우터가 직접 import한 이름)를
    monkeypatch로 갈아끼운다 — 외부 HTTP를 타지 않는다."""

    async def fake_get_capabilities() -> LocalCapabilities:
        return _READY_CAPABILITIES

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)


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
        "model": "v1",
        "style": "base",
        "aspectRatio": "1:1",
        "count": 1,
    }
    payload.update(overrides)
    return payload


async def test_generate_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/images/generate", json=_generate_payload())
    assert resp.status_code == 401


async def test_generate_rejects_aspect_ratio_not_supported_by_local_capabilities(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True, models=(ModelCapability(model_id="v1", styles=("base",), aspect_ratios=("1:1",)),)
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    # 16:9는 유효한 Literal이지만 이번 capabilities 응답은 1:1만 지원한다고 보고한다 →
    # 400(생성 착수 전 방어). 이제 이 축의 단일 소스는 정적 모델 레지스트리가 아니라 로컬
    # capabilities다(local-image-gen-techspec.md LT-4/LT-6) — 모델이 하나뿐이라 "모델이
    # 지원하지 않는 비율" 시나리오는 로컬이 지금 보고하지 않는 비율로 표현한다.
    resp = await db_client.post("/images/generate", json=_generate_payload(aspectRatio="16:9"))
    assert resp.status_code == 400


async def test_generate_rejects_style_the_local_does_not_serve_under_the_wire_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local-image-gen-goal-prompt.md LG-19: `router.py:203`의 style 400 분기 — 홈PC가
    지금 서빙하는 화풍이 바뀌면(재개편 등) 제출 시점에 400을 받아야 한다. 안 그러면 잡이
    만들어지고 나중에 일반 실패 메시지로 끝난다. 여기서 로컬이 보고하는 문자열이 우연히
    공개 id("base")와 같아도, 지금 설정된 와이어 style("default")과 다르면 지원하지
    않는 것으로 취급해야 한다 — 매핑 없이 원문을 그대로 비교하면(구 동작) 이 우연한
    문자열 일치 때문에 잘못 통과시킨다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    monkeypatch.setattr(settings, "local_image_style_wire_id", "default")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True, models=(ModelCapability(model_id="v1", styles=("base",), aspect_ratios=("1:1",)),)
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    resp = await db_client.post("/images/generate", json=_generate_payload())
    assert resp.status_code == 400


async def test_generate_returns_503_and_creates_no_job_when_local_capabilities_unavailable(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local-image-gen-goal-prompt.md LG-8의 사전 차단이 이 라우터의 기본 동작이 됐다 —
    capabilities를 스텁하지 않은 요청은 (실제 httpx 호출도 없이) 503으로 막혀야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/images/generate", json=_generate_payload())
    assert resp.status_code == 503


async def test_list_image_models_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/images/models")
    assert resp.status_code == 401


async def test_list_image_models_returns_capabilities(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    resp = await db_client.get("/images/models")
    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is True
    assert set(models["v1"]["supportedAspectRatios"]) == {"1:1", "4:3", "3:4", "16:9", "9:16", "2:3"}
    assert models["v1"]["styles"] == [{"id": "base", "name": "기본"}]


async def test_generate_creates_assets_and_completes_job(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    _override_image_client(lambda: (_png_bytes(), "image/png"))
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
        assert s3_object["Body"].read() == _png_bytes()
        thumb_object = s3.get_object(
            Bucket=settings.s3_bucket_name, Key=build_thumbnail_key(asset.storage_key)
        )
        with Image.open(io.BytesIO(thumb_object["Body"].read())) as thumb:
            assert thumb.format == "WEBP"


async def test_generate_partial_failure_still_succeeds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    call_count = {"n": 0}

    def generate() -> tuple[bytes, str]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise LLMClientError("temporary blip")
        return _png_bytes(), "image/png"

    _override_image_client(generate)
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
    _stub_capabilities_ready(monkeypatch)

    def generate() -> tuple[bytes, str]:
        raise LLMClientError("unavailable")

    _override_image_client(generate)
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


async def test_generate_undecodable_image_counts_as_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    _override_image_client(lambda: (b"not-a-decodable-image", "image/png"))
    try:
        resp = await db_client.post("/images/generate", json=_generate_payload(count=1))
    finally:
        _clear_image_override()
    assert resp.status_code == 202

    # 썸네일 생성 실패는 그 이미지의 실패다 — Asset이 READY로 남지 않는다.
    job = await _wait_for_job_completion(resp.json()["jobId"], user.id)
    assert job.status == ImageGenerationJobStatus.FAILED
    assert job.completed_count == 0
    assert job.asset_ids == []


async def test_generate_unexpected_error_marks_job_failed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    def generate() -> tuple[bytes, str]:
        raise ValueError("boom")  # LLMClientError가 아닌 예기치 못한 오류

    _override_image_client(generate)
    try:
        resp = await db_client.post("/images/generate", json=_generate_payload(count=1))
    finally:
        _clear_image_override()
    assert resp.status_code == 202

    # 예기치 못한 예외라도 잡이 running에 멈추지 않고 FAILED로 끝나야 한다(hang 방지).
    job = await _wait_for_job_completion(resp.json()["jobId"], user.id)
    assert job.status == ImageGenerationJobStatus.FAILED
