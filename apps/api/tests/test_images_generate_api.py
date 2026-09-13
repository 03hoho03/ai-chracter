import asyncio
import io
import logging
import uuid
from collections.abc import Callable
from datetime import timezone
from typing import Literal

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
from api.llm.local_image import LocalCapabilities, LocalImageBlockedError, ModelCapability
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
    # guard-techspec.md GT-3 표 1행: 차단이 없으면 blocked 필드는 기본값(0/None)이다.
    assert job.blocked_count == 0
    assert job.blocked_reason is None

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
    # guard-techspec.md GT-3 표 4행: 차단이 아닌 순수 실패는 오늘의 문구 그대로여야
    # 하고, blocked 필드는 기본값(0/None)으로 남아야 한다.
    assert job.error == "이미지 생성에 모두 실패했습니다"
    assert job.blocked_count == 0
    assert job.blocked_reason is None


async def test_generate_partial_block_succeeds_with_blocked_count_and_reason(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """guard-techspec.md GT-3 표 2행: 2장 중 1장이 이미지 가드에 차단되면 잡은
    SUCCEEDED로 끝나되 blockedCount/blockedReason에 그 사실이 남아야 한다 — 안
    남으면 사용자는 왜 1장만 받았는지 알 방법이 없다(guard-goal-prompt.md G-3)."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    call_count = {"n": 0}

    def generate() -> tuple[bytes, str]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise LocalImageBlockedError(reason="image")
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
    assert job.blocked_count == 1
    assert job.blocked_reason == "image"
    assert job.error is None


async def test_generate_all_blocked_marks_job_failed_with_null_error(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """guard-techspec.md GT-3 표 3행 + I-1의 `any(results)` 지뢰: `_generate_and_store_one`의
    반환이 3치로 넓어지면 파이썬에서는 non-bool 멤버가 전부 truthy이므로,
    `router.py:111`의 `if any(results):`를 그대로 두면 전부 차단인데도 잡이
    SUCCEEDED로 끝난다. 두 장 모두 차단시켜 FAILED로 끝나는지, 그리고 G-6에 따라
    서버가 한국어 문구를 넣지 않아 error가 null인지 고정한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    def generate() -> tuple[bytes, str]:
        raise LocalImageBlockedError(reason="prompt")

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
    assert job.blocked_count == 2
    assert job.blocked_reason == "prompt"
    assert job.error is None


async def test_generate_mixed_blocked_reasons_logs_warning(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """guard-goal-prompt.md G-6/guard-techspec.md GT-3: 프롬프트 가드는 결정적이라
    한 잡 안에서 사유가 섞일 수 없다 — 섞이면 로컬이 계약(LC-4b)을 어긴 것이므로,
    조용히 넘기지 않고 WARNING이 남아야 원인을 추적할 수 있다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    call_count = {"n": 0}

    def generate() -> tuple[bytes, str]:
        call_count["n"] += 1
        reason: Literal["prompt", "image"] = "prompt" if call_count["n"] == 1 else "image"
        raise LocalImageBlockedError(reason=reason)

    _override_image_client(generate)
    try:
        with caplog.at_level(logging.WARNING):
            resp = await db_client.post("/images/generate", json=_generate_payload(count=2))
            job = await _wait_for_job_completion(resp.json()["jobId"], user.id)
    finally:
        _clear_image_override()

    assert job.status == ImageGenerationJobStatus.FAILED
    router_warnings = [
        record
        for record in caplog.records
        if record.name == "api.images.router" and record.levelno >= logging.WARNING
    ]
    # 사유가 섞이지 않은 차단은 경고 하나(guard-goal-prompt.md G-5의 "차단 시" 로그)
    # 뿐이다 — 여기서 최소 2건을 요구해야, 섞였을 때만 추가로 남아야 하는 GT-3의
    # 계약-위반 경고가 실제로 구현됐는지(누락 시 이 단언만 깨진다) 확인할 수 있다.
    assert len(router_warnings) >= 2


async def test_generate_blocked_alongside_genuine_failure_logs_a_distinct_warning(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """guard-progress.md 적대적 리뷰 발견 사항(GT-3에 셀이 없던 조합): `count=2`에서
    하나는 차단, 다른 하나는 정책과 무관한 진짜 회귀(`LLMClientError`가 아닌 예기치
    못한 예외)로 실패하면, 집계는 `succeeded=0, blocked=1`만 보고 순수 전부-차단
    잡과 구분 불가능하게 FAILED+error=None으로 끝난다. 진짜 회귀의 유일한 흔적이
    `print()`뿐이라면, 운영자는 정책 차단 소음만 보고 다른 무언가가 깨졌다는 사실을
    영원히 놓친다 — 이 조합에서만 나야 하는 별개의 WARNING을 고정한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    call_count = {"n": 0}

    def generate() -> tuple[bytes, str]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise LocalImageBlockedError(reason="prompt")
        raise ValueError("boom")  # LLMClientError가 아닌, 정책과 무관한 회귀

    _override_image_client(generate)
    try:
        with caplog.at_level(logging.WARNING):
            resp = await db_client.post("/images/generate", json=_generate_payload(count=2))
            job = await _wait_for_job_completion(resp.json()["jobId"], user.id)
    finally:
        _clear_image_override()

    assert job.status == ImageGenerationJobStatus.FAILED
    assert job.blocked_count == 1
    assert job.blocked_reason == "prompt"
    assert job.error is None  # 사용자 화면은 그대로 정책 차단으로 보인다 — 이건 운영 신호일 뿐이다

    router_warnings = [
        record
        for record in caplog.records
        if record.name == "api.images.router" and record.levelno >= logging.WARNING
    ]
    # 사유가 하나뿐이라(섞임 없음) 오늘 코드라면 경고가 하나(일상적인 차단 경고)
    # 뿐이다 — 최소 2건을 요구해야, "차단과 무관한 진짜 실패가 같은 잡에 섞였다"는
    # 것을 알리는 별개의 경고가 실제로 추가됐는지 확인할 수 있다.
    assert len(router_warnings) >= 2


async def test_generate_blocked_log_omits_user_id_and_prompt_text(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """guard-goal-prompt.md G-5: 차단 로그에 사용자 id나 프롬프트 원문이 남으면
    서버 로그 자체가 "누가 무엇을 시도했는가"의 기록이 된다 — 사유만 남아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _stub_capabilities_ready(monkeypatch)

    secret_prompt = "극비-마커-프롬프트-XYZ789"

    def generate() -> tuple[bytes, str]:
        raise LocalImageBlockedError(reason="prompt")

    _override_image_client(generate)
    try:
        with caplog.at_level(logging.WARNING):
            resp = await db_client.post(
                "/images/generate", json=_generate_payload(prompt=secret_prompt, count=1)
            )
            job = await _wait_for_job_completion(resp.json()["jobId"], user.id)
    finally:
        _clear_image_override()

    assert job.status == ImageGenerationJobStatus.FAILED
    assert job.blocked_reason == "prompt"
    router_warnings = [record for record in caplog.records if record.name == "api.images.router"]
    assert router_warnings  # GT-5가 실제로 경고를 남기는지도 같이 고정한다
    for record in router_warnings:
        message = record.getMessage()
        assert secret_prompt not in message
        assert str(user.id) not in message


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
