"""`GET /images/models`의 정적 레지스트리 ↔ 로컬 capabilities 교차(LT-6)와
`POST /images/generate`의 가용성/대기열 사전 차단(LG-8/LT-3/LT-6).

capabilities 소스는 `mock.patch`가 아니라 `api.images.router.get_capabilities`(라우터가
직접 import한 이름)를 `monkeypatch.setattr`로 갈아끼운다 — 외부 HTTP를 실제로 타지 않고
router가 그 결과를 어떻게 쓰는지만 본다. 503/429로 끝나는 사전 차단 테스트는 `create_job`
이전에 막히므로 `app.dependency_overrides[get_image_client]`가 필요 없다 — admission이
잡 완료 시 반납되는지 보는 테스트만 예외로 그 오버라이드를 쓴다(아래 참고).

admission(P2-R 결함 수정, LT-3)도 같은 이름-패치 규칙을 따른다: 라우터는
`try_admit`/`release_admission`을 `api.llm.local_image`에서 이름으로 import해야
`monkeypatch.setattr("api.images.router.try_admit", ...)`가 먹는다.
"""

import asyncio
import logging
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import User
from api.images.jobs import ImageGenerationJob, ImageGenerationJobStatus, get_job
from api.llm.client import LLMClientError
from api.llm.dependencies import get_image_client
from api.llm.image import ImageClient, ImageStylePreset
from api.llm.local_image import LocalCapabilities, ModelCapability
from api.main import app
from factories import _login_as, _make_user


async def _authed_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


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


_READY_MATCHING_LOCAL = LocalCapabilities(
    ready=True,
    models=(ModelCapability(model_id="v1", styles=("base",), aspect_ratios=("1:1",)),),
)


# ---- GET /images/models 교차 (LT-6) ------------------------------------------


async def test_registry_model_missing_from_local_capabilities_is_marked_unavailable(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LC-1: 로컬이 정적 레지스트리의 `v1`을 응답에서 빼면(꺼짐·재개편 등) 그 모델은
    `available: false`로 내려가야 한다 — 안 그러면 FE가 죽은 모델을 선택 가능하게 그린다.
    불일치는 조용한 기능 축소로 나타나므로 WARNING 로그가 유일한 신호다(contract LC-1)."""
    await _authed_user(db_client, db_session)

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(ready=True, models=())

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    with caplog.at_level(logging.WARNING):
        resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is False
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


async def test_local_model_unknown_to_static_registry_is_ignored(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """서버가 모르는 id가 로컬 응답에 섞여 오면(구 BE가 새 로컬 체크포인트를 아직 모르는
    배포 과도기) 그대로 노출하지 않고 무시해야 한다 — 안 그러면 FE가 서버 정적 검증을
    거치지 않은 id로 요청을 보내 방어 검증(400)에 걸린다."""
    await _authed_user(db_client, db_session)

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(
                ModelCapability(model_id="v1", styles=("base",), aspect_ratios=("1:1",)),
                ModelCapability(model_id="unknown-future-model", styles=("base",), aspect_ratios=("1:1",)),
            ),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()}
    assert ids == {"v1"}


async def test_models_endpoint_maps_wire_capability_back_to_public_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local-image-gen-goal-prompt.md LG-19: 홈PC는 와이어 id(`sdxl-anime-v1`/`default`)만
    보고한다. 교차 참조가 공개 id로 그대로 조회하면(매핑 전 동작) 매치가 안 나 존재하는
    모델이 `available: false`로 내려간다 — 공개→와이어로 조회하고 돌아온 `styles`를
    와이어→공개로 되매핑해야 FE가 `v1`을 쓸 수 있고 style id도 렌더 가능해진다."""
    await _authed_user(db_client, db_session)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "sdxl-anime-v1")
    monkeypatch.setattr(settings, "local_image_style_wire_id", "default")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(ModelCapability(model_id="sdxl-anime-v1", styles=("default",), aspect_ratios=("1:1",)),),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is True
    # image-refact-techspec.md IT-1/IT-2/IT-3: 레지스트리 4종은 항상 전부 내려가고
    # (순서도 레지스트리 순서 그대로), 이 매핑에서 서빙되는 건 `base`(표시명 "순정")
    # 하나뿐이라 나머지 3종은 `available: false`다.
    assert models["v1"]["styles"] == [
        {"id": "base", "name": "순정", "available": True},
        {"id": "line", "name": "극화", "available": False},
        {"id": "water", "name": "수채", "available": False},
        {"id": "real", "name": "반실사", "available": False},
    ]


async def test_registry_entry_unavailable_when_capability_has_no_style_that_maps(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """local-image-gen-goal-prompt.md LG-17: `available`이 `_style_items()`의 결과와
    무관하게 `capability_for()`의 존재만으로 정해지면, 홈PC가 와이어 style을 하나도
    서빙하지 않을 때도 `available: true, styles: []`가 나가 FE의 제출 버튼이 눌려도
    아무 일도 일어나지 않고 사용자는 이유를 알 방법이 없다(불일치는 조용한 기능 축소이므로
    WARNING이 유일한 신호다, contract LC-1/techspec LT-2)."""
    await _authed_user(db_client, db_session)

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(ModelCapability(model_id="v1", styles=("unmapped-style",), aspect_ratios=("1:1",)),),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    with caplog.at_level(logging.WARNING):
        resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is False
    assert any(
        record.name == "api.images.router" and record.levelno >= logging.WARNING for record in caplog.records
    )


async def test_registry_entry_unavailable_when_local_does_not_report_the_wire_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local-image-gen-goal-prompt.md LG-19: 매핑이 걸리면 조회 키가 공개 id가 아니라
    와이어 id다. 홈PC가 옛 공개 id(`v1`)를 그대로 보고해도(와이어 id를 안 보고하면) 더
    이상 매치가 아니어야 한다 — 매핑을 건너뛰고 공개 id로 계속 조회하면 이 불일치를
    놓치고 `available: true`를 잘못 내린다(그 뒤 실제 생성 요청은 홈PC의 400으로 끝난다)."""
    await _authed_user(db_client, db_session)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "sdxl-anime-v1")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True, models=(ModelCapability(model_id="v1", styles=("base",), aspect_ratios=("1:1",)),)
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is False


async def test_models_endpoint_does_not_warn_when_wire_id_matches_and_model_is_available(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """local-image-gen-goal-prompt.md LG-19 / techspec LT-2: `missing` 계산이 여전히
    공개 id로 로컬 id 집합과 비교하면, 와이어 id가 공개 id와 다른 프로덕션에서는 모델이
    실제로 가용한데도 이 WARNING이 매 요청 상시로 운다 — 그러면 이 로그가 잡아야 할
    진짜 불일치가 소음에 묻힌다(LT-2가 "조용한 기능 축소의 유일한 신호"라 부르는 그
    로그다). 같은 요청 중 다른 로거가 WARNING을 내도 무관하므로 `api.images.router`
    로거 한정으로 부재를 확인한다."""
    await _authed_user(db_client, db_session)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "sdxl-anime-v1")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(ModelCapability(model_id="sdxl-anime-v1", styles=("base",), aspect_ratios=("1:1",)),),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    with caplog.at_level(logging.WARNING):
        resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is True
    assert not any(record.name == "api.images.router" for record in caplog.records)


# ---- POST /images/generate 사전 차단 (LG-8/LT-3) -----------------------------


async def test_generate_returns_503_and_creates_no_job_when_local_unavailable(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LG-8: 집 PC가 꺼져 있으면 생성 시도 전에 막아야 한다 — 사전 차단이 없으면 "눌렀는데
    실패"가 기본 경험이 된다. 잡이 실제로 생성되지 않는 것까지 확인한다(생성 후 실패라면
    잡이 Redis에 남아 FE가 폴링하다 실패로 끝나는 것과는 다른 경로다)."""
    await _authed_user(db_client, db_session)

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(ready=False, models=())

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    create_job_calls = {"n": 0}

    async def fake_create_job(*args: object, **kwargs: object) -> None:
        create_job_calls["n"] += 1

    monkeypatch.setattr("api.images.router.create_job", fake_create_job)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 503
    assert create_job_calls["n"] == 0


async def test_generate_returns_202_when_capability_lookup_uses_the_wire_model_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local-image-gen-goal-prompt.md LG-19: 홈PC는 와이어 id만 보고한다 — 이 가용성
    게이트가 공개 id(`payload.model`)로 조회하면, 공개 id와 와이어 id가 실제로 다른
    프로덕션에서는 이 확인이 항상 실패해 모든 생성 요청이 503으로 막힌다(이 단계가
    존재하는 이유 그 자체). 실제 생성 결과는 이 테스트의 관심사가 아니다 — 빈
    `local_image_base_url`을 향한 백그라운드 태스크는 안전하게 실패하고 잡은 나중에
    FAILED로 끝나지만(이미 확인된 경로), 게이트가 202를 냈는지만 고정한다."""
    await _authed_user(db_client, db_session)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "sdxl-anime-v1")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(ModelCapability(model_id="sdxl-anime-v1", styles=("base",), aspect_ratios=("1:1",)),),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 202
    assert "jobId" in resp.json()


async def test_generate_returns_429_and_creates_no_job_when_admission_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-3: `try_admit()`이 상한에서 거절하면 잡을 만들지 않고 429여야 한다 — 안 그러면
    한 사용자가 GPU 직렬 처리량을 몇 분씩 독점한다(LG-7 근거표). 로컬은 가용·요청도
    유효해서 이 단계까지 통과해야 한다. (P2-R로 카운터의 주체가 `current_queue_depth`
    고정값 패치에서 `try_admit` 고정 반환값으로 바뀌었다 — 실제 동시성 회귀는
    `test_concurrent_requests_admit_no_more_than_the_queue_limit`가 별도로 잡는다.)"""
    await _authed_user(db_client, db_session)

    async def fake_get_capabilities() -> LocalCapabilities:
        return _READY_MATCHING_LOCAL

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)
    monkeypatch.setattr("api.images.router.try_admit", lambda: False)

    create_job_calls = {"n": 0}

    async def fake_create_job(*args: object, **kwargs: object) -> None:
        create_job_calls["n"] += 1

    monkeypatch.setattr("api.images.router.create_job", fake_create_job)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 429
    assert create_job_calls["n"] == 0


async def test_concurrent_requests_admit_no_more_than_the_queue_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2-R 결함: 검사(구 `current_queue_depth`)와 증가가 서로 다른 시점에 있었다 — 증가는
    백그라운드 태스크가 `generate_image`에 진입해서야 일어났는데, 그 사이 진짜 await
    (`create_job`)가 있어 동시 도착 요청이 전부 증가 이전 값을 읽고 전부 통과했다(실제
    모듈로 재현된 수치: admitted=10 rejected=0 limit=4). 카운터를 고정값으로 monkeypatch
    하는 429 테스트는 이 경합을 볼 수 없다 — 여기는 실제 admission 경로를 실제 동시 요청
    10개로 통과시켜 상한(4)을 정확히 지키는지 본다. `enqueue_generation`을 stub해 이
    테스트를 admission 판정 자체에만 좁힌다(생성 파이프라인은 다른 테스트가 다룬다).
    `_queue_depth`는 프로세스 전역이라(모듈 최상단 정수) 이 테스트가 admit한 4건이
    저절로 반납되지 않는다 — 시작 값을 0으로 monkeypatch해 다른 테스트의 잔여 상태와
    격리하고, 이 테스트가 남긴 값은 monkeypatch가 teardown에서 되돌린다."""
    await _authed_user(db_client, db_session)
    monkeypatch.setattr("api.llm.local_image._queue_depth", 0)

    async def fake_get_capabilities() -> LocalCapabilities:
        return _READY_MATCHING_LOCAL

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)
    monkeypatch.setattr(settings, "local_image_queue_limit", 4)

    created_job_ids: list[str] = []

    async def fake_create_job(owner_user_id: uuid.UUID, requested_count: int) -> ImageGenerationJob:
        job = ImageGenerationJob(
            job_id=uuid.uuid4().hex,
            owner_user_id=owner_user_id,
            status=ImageGenerationJobStatus.QUEUED,
            requested_count=requested_count,
        )
        created_job_ids.append(job.job_id)
        return job

    monkeypatch.setattr("api.images.router.create_job", fake_create_job)

    async def fake_enqueue_generation(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("api.images.router.enqueue_generation", fake_enqueue_generation)

    responses = await asyncio.gather(
        *[db_client.post("/images/generate", json=_generate_payload()) for _ in range(10)]
    )

    statuses = [resp.status_code for resp in responses]
    assert statuses.count(202) == 4
    assert statuses.count(429) == 6
    assert len(created_job_ids) == 4


async def test_admission_is_released_when_create_job_raises_so_the_gate_does_not_wedge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admit과 백그라운드 인계 사이(`create_job`)에서 예외가 나면 admission을 반드시
    반납해야 한다 — 안 그러면 실패한 요청이 슬롯을 영구 점유해 상한(1)에서 게이트가
    영원히 막히고 이후 모든 요청이 429가 된다. `release_admission`이 정확히 한 번
    불리는지로 직접 고정하고, 다음 요청이 실제로 admit되는지까지 확인한다. spy는 호출
    횟수만 세는 게 아니라 실제 `release_admission`으로 위임한다 — 안 그러면 진짜
    admission 카운터가 절대 안 줄어 뒤이은 202 단언이 통과할 수 없다."""
    from api.llm.local_image import release_admission as real_release_admission

    await _authed_user(db_client, db_session)
    monkeypatch.setattr("api.llm.local_image._queue_depth", 0)

    async def fake_get_capabilities() -> LocalCapabilities:
        return _READY_MATCHING_LOCAL

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)
    monkeypatch.setattr(settings, "local_image_queue_limit", 1)

    async def failing_create_job(*args: object, **kwargs: object) -> None:
        raise RuntimeError("redis blip")

    monkeypatch.setattr("api.images.router.create_job", failing_create_job)

    release_calls = {"n": 0}

    def fake_release_admission() -> None:
        release_calls["n"] += 1
        real_release_admission()

    monkeypatch.setattr("api.images.router.release_admission", fake_release_admission)

    with pytest.raises(RuntimeError):
        await db_client.post("/images/generate", json=_generate_payload())

    assert release_calls["n"] == 1

    async def succeeding_create_job(owner_user_id: uuid.UUID, requested_count: int) -> ImageGenerationJob:
        return ImageGenerationJob(
            job_id=uuid.uuid4().hex,
            owner_user_id=owner_user_id,
            status=ImageGenerationJobStatus.QUEUED,
            requested_count=requested_count,
        )

    monkeypatch.setattr("api.images.router.create_job", succeeding_create_job)

    async def fake_enqueue_generation(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("api.images.router.enqueue_generation", fake_enqueue_generation)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 202


class _ImmediatelyFailingImageClient(ImageClient):
    """실제 생성을 하지 않고 즉시 실패한다 — 이 테스트가 보는 것은 생성 결과가 아니라
    잡이 끝났을 때 admission이 반납되는지다."""

    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        raise LLMClientError("stub - no real generation in this test")


async def _wait_for_job_to_finish(job_id: str, owner_user_id: uuid.UUID) -> None:
    for _ in range(200):
        job = await get_job(job_id, owner_user_id)
        assert job is not None
        if job.status in (ImageGenerationJobStatus.SUCCEEDED, ImageGenerationJobStatus.FAILED):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish in time")


async def test_admission_is_released_when_the_job_finishes_so_a_later_request_is_admitted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_run_generation`이 끝날 때(성공/실패 모두) admission을 finally로 반납하지 않으면
    상한(1)에서 첫 잡이 끝난 뒤에도 다음 요청이 계속 429를 받는다. `release_admission`이
    잡 완료 시 정확히 한 번 불리는지로 직접 고정하고, 그 뒤 요청이 admit되는지까지
    확인한다. spy는 호출 횟수만 세는 게 아니라 실제 `release_admission`으로 위임한다 —
    안 그러면 진짜 admission 카운터가 절대 안 줄어 뒤이은 202 단언이 통과할 수 없다."""
    from api.llm.local_image import release_admission as real_release_admission

    user = await _authed_user(db_client, db_session)
    monkeypatch.setattr("api.llm.local_image._queue_depth", 0)

    async def fake_get_capabilities() -> LocalCapabilities:
        return _READY_MATCHING_LOCAL

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)
    monkeypatch.setattr(settings, "local_image_queue_limit", 1)

    release_calls = {"n": 0}

    def fake_release_admission() -> None:
        release_calls["n"] += 1
        real_release_admission()

    monkeypatch.setattr("api.images.router.release_admission", fake_release_admission)

    app.dependency_overrides[get_image_client] = lambda: (
        lambda model_id: _ImmediatelyFailingImageClient()
    )
    try:
        first = await db_client.post("/images/generate", json=_generate_payload())
        assert first.status_code == 202
        await _wait_for_job_to_finish(first.json()["jobId"], user.id)

        assert release_calls["n"] == 1

        second = await db_client.post("/images/generate", json=_generate_payload())
    finally:
        app.dependency_overrides.pop(get_image_client, None)

    assert second.status_code == 202
