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

limit-goal-prompt.md RL-5/RL-11/RL-13/RL-16(S6)의 유저별 상한 — 토큰 버킷(장수만큼 차감) ·
유저별 큐 1칸 · 429 바디 통일(`USER_LIMIT`/`QUEUE_FULL`) · 202 전 실패의 환불 — 도 같은
엔드포인트의 **사전 차단**이라 이 파일에 둔다(`test_user_rate_limit_gate.py`는 채팅 4경로 전용).
정책 상수는 `api.core.rate_limit_gate`의 모듈 전역이라 `monkeypatch.setattr`로 낮춘다.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from contextlib import AsyncExitStack
from typing import cast

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models import User
from api.db.models.clover import CloverLedger
from api.images.jobs import ImageGenerationJob, ImageGenerationJobStatus, get_job
from api.llm import local_image
from api.llm.client import LLMClientError
from api.llm.dependencies import get_image_client
from api.llm.image import ImageClient, ImageStylePreset
from api.llm.local_image import LocalCapabilities, ModelCapability
from api.main import app
from factories import _login_as, _make_user, _make_user_with_clover_lot


async def _authed_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession, **overrides: object
) -> User:
    """clover-page-goal-prompt.md CE-35 — `clover_balance`가 있으면 매칭 로트도 함께 만든다.
    이미지 게이트가 실제로 image_spend를 태우는 테스트가 로트 0행 상태에서
    `CloverLotShortfallError`를 맞지 않도록."""
    balance = overrides.pop("clover_balance", 0)
    assert isinstance(balance, int)
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance, **overrides)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


def _generate_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt": "a cat wizard",
        "model": "v1",
        "style": "soft_portrait",
        "aspectRatio": "1:1",
        "count": 1,
    }
    payload.update(overrides)
    return payload


_READY_MATCHING_LOCAL = LocalCapabilities(
    ready=True,
    models=(ModelCapability(model_id="v1", styles=("soft_portrait",), aspect_ratios=("1:1",)),),
)


def _stub_ready_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_capabilities() -> LocalCapabilities:
        return _READY_MATCHING_LOCAL

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)


def _reset_admission(monkeypatch: pytest.MonkeyPatch, *, queue_limit: int) -> None:
    """전역 깊이·유저별 깊이 둘 다 프로세스 전역이라(모듈 최상단 정수 + dict) 다른 테스트가
    admit한 채 남긴 값과 격리해야 한다. monkeypatch가 teardown에서 원래 값(과 원래 dict
    **객체**)을 되돌리므로 이 테스트들이 반납하지 않고 끝나도 뒤 테스트에 새지 않는다."""
    monkeypatch.setattr("api.llm.local_image._queue_depth", 0)
    monkeypatch.setattr("api.llm.local_image._user_queue_depth", {})
    monkeypatch.setattr(settings, "local_image_queue_limit", queue_limit)


def _stub_job_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`create_job`/`enqueue_generation`을 stub해 게이트 판정에만 좁힌다(생성 파이프라인은
    `test_images_generate_api.py`가 다룬다). 반환 리스트에 만들어진 잡 id가 쌓이므로 "거절된
    요청은 잡을 만들지 않았다"까지 같은 자리에서 본다. 잡이 안 돌아 admission이 저절로
    반납되지 않는다 — 한 테스트 안에서 "이미 한 칸 차 있다"를 만드는 수단이기도 하다."""
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

    async def fake_enqueue_generation(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("api.images.router.create_job", fake_create_job)
    monkeypatch.setattr("api.images.router.enqueue_generation", fake_enqueue_generation)
    return created_job_ids


async def _extra_logged_in_client(
    stack: AsyncExitStack, db_session: AsyncSession, **overrides: object
) -> httpx.AsyncClient:
    """`db_client`의 유저와 **다른 유저**로 동시에 요청할 클라이언트. 유저별 큐 1칸(RL-5)은
    유저가 여럿이어야 전역 상한과 구분되는데, 세션 쿠키는 클라이언트 단위라(요청 단위
    `cookies=`는 httpx 0.28에서 deprecated) 유저마다 클라이언트를 따로 연다.

    `app.dependency_overrides`는 전역이라 이 클라이언트도 `db_client`와 **같은 DB 세션·같은
    트랜잭션**을 쓴다 — 그래서 여기서 만든 유저 행이 라우트에도 보이고 테스트 끝에 함께
    롤백된다(`db_client` 픽스처를 함께 받아야 그 오버라이드가 설치돼 있다)."""
    user = _make_user(**overrides)
    db_session.add(user)
    await db_session.commit()
    client = await stack.enter_async_context(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    )
    await _login_as(client, user.id)
    return client


_IMAGE_TOKEN_KEY = "rate_limit:image_tokens:{user_id}"


async def _bucket_tokens(user_id: uuid.UUID) -> float | None:
    """토큰 버킷 키를 직접 읽는다 — 차감도 환불도 응답 본문에 드러나지 않아 Redis를 보는 것
    말고는 "환불됐다"를 관측할 방법이 없다. 키가 아예 없으면 None(= 차감 자체가 없었다)이라
    "차감 안 함"과 "차감 후 환불"이 구분된다."""
    raw = cast(str | None, await redis_client.get(_IMAGE_TOKEN_KEY.format(user_id=user_id)))
    if raw is None:
        return None
    return float(json.loads(raw)["tokens"])


async def _set_bucket_tokens(user_id: uuid.UUID, tokens: float) -> None:
    """`core/rate_limit.py`의 `_TokenBucket` 직렬화 형식 그대로 버킷을 심는다."""
    await redis_client.set(
        _IMAGE_TOKEN_KEY.format(user_id=user_id),
        json.dumps({"tokens": tokens, "updated_at": time.time()}),
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


async def test_models_endpoint_maps_wire_model_id_back_to_the_public_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local-image-gen-goal-prompt.md LG-19: 홈PC는 와이어 id(`opaque-wire-id`)만
    보고한다. 교차 참조가 공개 id로 그대로 조회하면(매핑 전 동작) 매치가 안 나 존재하는
    모델이 `available: false`로 내려간다 — 공개→와이어로 조회해야 FE가 `v1`을 쓸 수 있다.

    image-style-7-goal-prompt.md IS-2: style 축은 이 레포에 별도 와이어 매핑이 없다 —
    공개 id와 와이어 id가 같다. 그 가용성은
    `test_partial_serving_produces_exact_availability_vector_for_all_seven_styles`가
    이미 담당하므로, 여기서는 model 축 와이어 매핑(살아있는 기능)만 검증한다."""
    await _authed_user(db_client, db_session)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "opaque-wire-id")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(
                ModelCapability(model_id="opaque-wire-id", styles=("soft_portrait",), aspect_ratios=("1:1",)),
            ),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is True


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
    monkeypatch.setattr(settings, "local_image_model_wire_id", "opaque-wire-id")

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
    monkeypatch.setattr(settings, "local_image_model_wire_id", "opaque-wire-id")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(
                ModelCapability(model_id="opaque-wire-id", styles=("soft_portrait",), aspect_ratios=("1:1",)),
            ),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    with caplog.at_level(logging.WARNING):
        resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert models["v1"]["available"] is True
    assert not any(record.name == "api.images.router" for record in caplog.records)


async def test_partial_serving_produces_exact_availability_vector_for_all_seven_styles(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """image-style-7-goal-prompt.md IS-5: 가용성 판정은 style 집합 원소별이어야 한다.
    7종 중 **정확히 2종**(`chapel_glass`=2번째, `watercolor`=5번째)만 서빙하는 픽스처로
    응답 7개의 `available`을 순서까지 포함해 통째로 단언한다.

    **왜 이 픽스처인가**: 7종을 전부 서빙하는 픽스처도, 전무 서빙하는 픽스처도 검출력이
    0이다 — 두 버그 유형이 그런 픽스처에서 **우연히 정답 벡터와 일치한다**: ①
    `served`를 bool로 만들어 "하나라도 서빙되면 전부 available"이 되는 버그(전부
    서빙에서 우연히 맞는다), ② 특정 슬롯을 하드코딩하는 버그(전무 서빙에서 그 슬롯도
    False가 되어 우연히 맞는다). 정확히 2종을, 그것도 "자연스러운 기본값"이 아닌
    위치(2·5번째)로 골라야 두 버그 유형 모두에서 벡터가 어긋난다. `_style_items`는
    같은 종류의 항진명제로 이미 한 번 물렸다(image-refact-techspec.md IT-4:
    `available=bool(styles)`가 IT-3 이후 항상 참이 된 사건 — `router.py`의
    `_style_items` 호출부 주석 참고).
    """
    await _authed_user(db_client, db_session)

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(
                ModelCapability(model_id="v1", styles=("chapel_glass", "watercolor"), aspect_ratios=("1:1",)),
            ),
        )

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    resp = await db_client.get("/images/models")

    assert resp.status_code == 200
    models = {m["id"]: m for m in resp.json()}
    assert [(s["id"], s["available"]) for s in models["v1"]["styles"]] == [
        ("soft_portrait", False),
        ("chapel_glass", True),
        ("royal_drama", False),
        ("sparkle_night", False),
        ("watercolor", True),
        ("pixel_art", False),
        ("deco_cute", False),
    ]


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
    monkeypatch.setattr(settings, "local_image_model_wire_id", "opaque-wire-id")

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(
            ready=True,
            models=(
                ModelCapability(model_id="opaque-wire-id", styles=("soft_portrait",), aspect_ratios=("1:1",)),
            ),
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
    monkeypatch.setattr("api.images.router.try_admit", lambda _user_id: False)

    create_job_calls = {"n": 0}

    async def fake_create_job(*args: object, **kwargs: object) -> None:
        create_job_calls["n"] += 1

    monkeypatch.setattr("api.images.router.create_job", fake_create_job)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 429
    assert create_job_calls["n"] == 0


async def test_four_distinct_users_fill_the_global_queue_and_a_fifth_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2-R 결함(검사와 증가가 서로 다른 await 경계에 걸쳐 있어 동시 도착 요청이 전부 증가
    이전 값을 읽고 통과했다 — 실측 admitted=10 rejected=0 limit=4)의 회귀 가드였던
    `test_concurrent_requests_admit_no_more_than_the_queue_limit`의 후신이다. 유저별 큐가
    1칸이 되면서(RL-5) 같은 유저 10건으로는 전역 상한(4)을 더 이상 관측할 수 없다 — 두 번째
    요청부터 유저별 칸에서 먼저 걸리기 때문이다. 서로 다른 유저 5명이 **동시에** 도착해야
    전역 상한이 판정에 관여한다.

    이 배치가 잡는 회귀가 하나 더 있다: `_queue_depth`(전역 정수)를 유저별 dict로 **교체**해
    버리면 유저마다 1칸씩 무제한으로 열려 GPU 직렬 처리량(LG-6) 방어가 통째로 사라진다 —
    그때 5번째 유저가 429가 아니라 202를 받는다."""
    await _authed_user(db_client, db_session)
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    created_job_ids = _stub_job_pipeline(monkeypatch)

    async with AsyncExitStack() as stack:
        others = [await _extra_logged_in_client(stack, db_session) for _ in range(4)]
        responses = await asyncio.gather(
            db_client.post("/images/generate", json=_generate_payload()),
            *[client.post("/images/generate", json=_generate_payload()) for client in others],
        )

    statuses = [resp.status_code for resp in responses]
    assert statuses.count(202) == 4
    assert statuses.count(429) == 1
    assert len(created_job_ids) == 4
    rejected = next(resp for resp in responses if resp.status_code == 429)
    assert rejected.json()["detail"]["code"] == "QUEUE_FULL"


async def test_same_user_second_concurrent_request_is_queue_full_while_another_user_passes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-5: 유저별 큐는 1칸이다 — 한 사용자가 잡 두 개를 동시에 큐에 세울 수 없다.

    짝이 되는 **다른 유저의 202**가 없으면 이 테스트는 "전역 상한이 1"과 구분되지 않는다
    (전역만 1로 낮춘 구현에서도 똑같이 초록이다). 전역 상한은 4로 열어 두고 같은 순간에 다른
    유저가 통과하는 것까지 함께 단언해야 유저별 칸이 실제로 존재한다는 뜻이 된다."""
    await _authed_user(db_client, db_session)
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    created_job_ids = _stub_job_pipeline(monkeypatch)

    async with AsyncExitStack() as stack:
        other_client = await _extra_logged_in_client(stack, db_session)
        first, second, other = await asyncio.gather(
            db_client.post("/images/generate", json=_generate_payload()),
            db_client.post("/images/generate", json=_generate_payload()),
            other_client.post("/images/generate", json=_generate_payload()),
        )

    assert sorted([first.status_code, second.status_code]) == [202, 429]
    assert other.status_code == 202
    rejected = first if first.status_code == 429 else second
    assert rejected.json()["detail"]["code"] == "QUEUE_FULL"
    # 거절된 쪽은 잡을 만들지 않는다 — 통과한 A 1건 + B 1건뿐이다.
    assert len(created_job_ids) == 2


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

    def fake_release_admission(user_id: uuid.UUID) -> None:
        release_calls["n"] += 1
        real_release_admission(user_id)

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


async def test_non_http_failure_before_202_refunds_the_charged_tokens(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-16: 환불 조건은 "202 전에 끝났다"이지 "`HTTPException`으로 끝났다"가 아니다.
    차감 이후 202 전에는 `HTTPException`이 아닌 예외를 내는 지점이 둘 있다 —
    `create_job`(Redis)과 `session.commit()`(Postgres). 바로 위 테스트가 그 경로에서
    큐 칸 반납만 보므로, 토큰까지 보는 테스트가 없으면 환불이 `HTTPException`에만 걸린
    구현이 초록으로 남는다(그때 사용자는 500만 보고 하루치가 조용히 깎인다).

    `raise_app_exceptions=False` 클라이언트를 따로 여는 이유는 상태 코드를 보기 위해서다 —
    기본 `db_client`는 앱 예외를 그대로 올려서 응답이 만들어지지 않는다(바로 위 테스트가
    `pytest.raises(RuntimeError)`를 쓰는 이유)."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)

    async def failing_create_job(*args: object, **kwargs: object) -> None:
        raise RuntimeError("redis blip")

    monkeypatch.setattr("api.images.router.create_job", failing_create_job)

    user = await _authed_user(db_client, db_session)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
        cookies=db_client.cookies,
    ) as client:
        resp = await client.post("/images/generate", json=_generate_payload(count=2))

    assert resp.status_code == 500
    assert await _bucket_tokens(user.id) == pytest.approx(
        float(rate_limit_gate.IMAGE_TOKEN_CAPACITY), abs=0.01
    )


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

    def fake_release_admission(user_id: uuid.UUID) -> None:
        release_calls["n"] += 1
        real_release_admission(user_id)

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


# ---- 유저별 토큰 버킷 · 429 바디 통일 · 환불 (RL-5/RL-11/RL-13/RL-16, S6) ----


async def test_images_generate_returns_user_limit_body_when_token_bucket_is_empty(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-5/RL-11: 토큰이 없으면 큐에 자리가 있어도 429이고, 잡은 만들어지지
    않는다. 용량을 0으로 낮춰 만든다 — 실제로 10장을 생성해 소진시키면 그 비용이 이 스위트에
    그대로 붙는다(`test_user_rate_limit_gate.py`의 같은 결정).

    🔴 **클로버 도입으로 `code`가 바뀌었다**(clover-techspec.md CT-8 이미지 행). 토큰이 없으면
    클로버가 대신 내므로, **낼 클로버도 없을 때** 나가는 것이 이 429다. `_authed_user`의 기본
    잔액이 0이라 이 셋업이 곧 "낼 것이 없는 사용자"다.
    ⇒ **이미지에서 `USER_LIMIT`은 이제 도달할 수 없다** — 토큰 부족은 전부 클로버 분기로 넘어간다.
    `window`는 `"image"`를 유지하고(둘을 가르는 축은 `code`다) `retryAfterSeconds`도 `take_tokens`가
    준 값 그대로다 — 자정까지 초를 쓰면 최대 24시간짜리 거짓값이 된다."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    created_job_ids = _stub_job_pipeline(monkeypatch)
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)

    user = await _authed_user(db_client, db_session)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "CLOVER_REQUIRED"
    assert detail["window"] == "image"
    # 다음 토큰이 찰 때까지의 초. 0이면 FE가 "지금 다시" 하라는 뜻으로 읽어 무한 재시도가 된다.
    assert detail["retryAfterSeconds"] >= 1
    assert created_job_ids == []
    # 큐 칸은 건드리지 않았다 — 게이트가 `Depends`라 라우트 본문(try_admit) 전에 끊는다(RL-13).
    assert local_image._user_queue_depth == {}
    assert await _bucket_tokens(user.id) is None


async def test_global_queue_429_now_uses_the_structured_detail_body(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-11: 전역 큐 거절의 detail은 평문 문자열("Too many generation requests are queued")
    이었다 — 유저 상한 429와 본문 모양이 달라 FE가 둘을 가를 수 없고 재시도 시점도 모른다.
    두 429를 `code`로 가르고 `retryAfterSeconds`를 함께 싣는다."""
    await _authed_user(db_client, db_session)
    _stub_ready_capabilities(monkeypatch)
    monkeypatch.setattr("api.images.router.try_admit", lambda _user_id: False)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "QUEUE_FULL"
    # 큐 길이 추정이 아니라 **잡 한 건의 최대 소요**(30초/장 × count 상한 2)를 고정값으로 준다.
    assert detail["retryAfterSeconds"] == 60


async def test_queue_full_refunds_the_charged_tokens(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-16: 토큰은 잡이 실제로 생성(202)될 때만 소모된다. 차감은 `Depends`에서 일어나고
    큐 거절은 그 뒤 라우트 본문이라, 환불이 없으면 **생성되지도 않은 이미지 2장**이 사용자의
    하루치에서 사라진다(그 상태로 큐가 붐비면 상한이 실제 생성량보다 훨씬 빨리 마른다).

    키가 아예 없으면(None) 차감 자체가 없었다는 뜻이라 이 단언은 "차감 후 환불"만 통과시킨다
    — 환불이 빠지면 8.0, 차감이 빠지면 None이다."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    monkeypatch.setattr("api.images.router.try_admit", lambda _user_id: False)

    user = await _authed_user(db_client, db_session)

    resp = await db_client.post("/images/generate", json=_generate_payload(count=2))

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "QUEUE_FULL"
    assert await _bucket_tokens(user.id) == pytest.approx(
        float(rate_limit_gate.IMAGE_TOKEN_CAPACITY), abs=0.01
    )


async def test_unavailable_503_refunds_the_charged_tokens(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-16a: 환불은 `QUEUE_FULL` 전용이 아니다 — 차감 이후 202 전에 끝나는 경로는 전부
    같다. 집 PC가 꺼져 있으면(503) 사용자는 이미지를 한 장도 못 받는데, 환불이 큐 거절에만
    걸려 있으면 홈서버가 다운된 동안 재시도할 때마다 하루치가 조용히 깎인다."""
    _reset_admission(monkeypatch, queue_limit=4)

    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(ready=False, models=())

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)

    user = await _authed_user(db_client, db_session)

    resp = await db_client.post("/images/generate", json=_generate_payload(count=2))

    assert resp.status_code == 503
    assert await _bucket_tokens(user.id) == pytest.approx(
        float(rate_limit_gate.IMAGE_TOKEN_CAPACITY), abs=0.01
    )


async def test_exempt_user_skips_token_bucket_but_still_has_one_queue_slot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-10/RL-18: 예외 계정이 면제받는 것은 **토큰 버킷뿐**이다. 유저별 큐 1칸은 그대로
    받는다 — 큐는 쿼터가 아니라 GPU 직렬 처리량(LG-6) 보호라서 예외 계정에 열어 줄 이유가
    없다. 짝은 바로 위
    `test_images_generate_returns_user_limit_body_when_token_bucket_is_empty`다(같은
    `IMAGE_TOKEN_CAPACITY=0`에서 비면제 계정은 `USER_LIMIT` 429를 받는다) — 그 짝이 없으면
    이 202는 "면제가 먹혔다"가 아니라 "이 셋업에서는 원래 아무도 안 걸린다"일 수 있다."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    created_job_ids = _stub_job_pipeline(monkeypatch)
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)

    await _authed_user(db_client, db_session, rate_limit_exempt=True)

    first, second = await asyncio.gather(
        db_client.post("/images/generate", json=_generate_payload()),
        db_client.post("/images/generate", json=_generate_payload()),
    )

    assert sorted([first.status_code, second.status_code]) == [202, 429]
    rejected = first if first.status_code == 429 else second
    assert rejected.json()["detail"]["code"] == "QUEUE_FULL"
    assert len(created_job_ids) == 1


async def test_token_charge_equals_requested_image_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RL-5: 토큰 1개 = 이미지 1장이다. 요청당 1씩 깎으면 `count=2`로 보내는 사용자가 상한을
    두 배로 쓴다 — 비용은 장수에 붙는다(LG-6: 집 PC가 장당 한 번씩 돈다).

    뒷부분은 부분 차감 금지다: 남은 토큰(1)이 요청 장수(2)보다 적으면 1장만 만들지 않고
    통째로 429다 — 부분 생성은 사용자에게 "2장 요청했는데 1장"으로 보이고 환불 회계도
    두 갈래가 된다."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    created_job_ids = _stub_job_pipeline(monkeypatch)

    user = await _authed_user(db_client, db_session)

    accepted = await db_client.post("/images/generate", json=_generate_payload(count=2))

    assert accepted.status_code == 202
    assert await _bucket_tokens(user.id) == pytest.approx(
        float(rate_limit_gate.IMAGE_TOKEN_CAPACITY) - 2, abs=0.01
    )

    # 같은 유저의 두 번째 요청이라 유저별 큐 1칸이 아직 차 있다(잡이 stub이라 반납되지 않는다).
    # 그 칸을 비워야 아래 429가 `QUEUE_FULL`이 아니라 토큰 부족 때문임이 확실해진다.
    local_image._user_queue_depth.clear()
    await _set_bucket_tokens(user.id, 1.0)

    rejected = await db_client.post("/images/generate", json=_generate_payload(count=2))

    assert rejected.status_code == 429
    # 토큰 부족 + 잔액 0 → CT-8 이미지 행. `QUEUE_FULL`이 아니라는 것이 이 단언의 내용이다.
    assert rejected.json()["detail"]["code"] == "CLOVER_REQUIRED"
    assert len(created_job_ids) == 1
    # 부족하면 **부분 차감 없이** 거절이다 — 남은 1이 그대로 있어야 한다.
    assert await _bucket_tokens(user.id) == pytest.approx(1.0, abs=0.01)


# ---- 이미지 클로버 분기 (clover-techspec.md CT-7·CT-8 이미지 행, §3-4-1) ----


async def test_token_exhaustion_spends_clover_and_creates_the_job(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """clover-goal-prompt.md CL-1: 이미지도 무료 토큰버킷을 다 쓴 뒤에는 클로버가 대신 낸다.
    차감량은 **장수 × 단가**다(`count`가 2면 두 배) — 비용이 요청 수가 아니라 장수에 붙는
    것과 같은 이유다(RL-5)."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    created_job_ids = _stub_job_pipeline(monkeypatch)
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)

    # clover-goal-prompt.md CL-19 — 차감에는 **오늘치 동의**가 선행한다(게이트가 미확인이면
    # `CLOVER_CONFIRM_REQUIRED`로 끊는다). 차감량을 보는 테스트라 그 선행 조건을 셋업에 명시한다.
    user = await _authed_user(
        db_client,
        db_session,
        clover_balance=100,
        clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC)),
    )

    resp = await db_client.post("/images/generate", json=_generate_payload(count=2))

    assert resp.status_code == 202
    assert len(created_job_ids) == 1

    await db_session.refresh(user)
    assert user.clover_balance == 100 - 2 * clover.IMAGE_UNIT_COST

    rows = list(
        (
            await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user.id))
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].kind == "image_spend"
    assert rows[0].amount == -2 * clover.IMAGE_UNIT_COST


async def test_image_clover_rejection_uses_the_refill_retry_after_not_midnight(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 clover-techspec.md CT-8: 이미지 무료분은 **시간당 충전**이지 자정 리셋이 아니다.
    `retryAfterSeconds`에 자정까지 초를 실으면 **최대 24시간짜리 거짓값**이 나간다 —
    `take_tokens`가 돌려준 값(다음 토큰까지 남은 초)을 그대로 써야 참이다.

    충전 주기를 작은 값으로 낮춰 두 값이 **실제로 갈리게** 만든다. 그렇게 하지 않으면
    자정까지 초와 충전 초가 우연히 같은 범위에 들어 이 단언이 항진명제가 된다."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    _stub_job_pipeline(monkeypatch)
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_REFILL_SECONDS", 120)

    await _authed_user(db_client, db_session, clover_balance=0)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "CLOVER_REQUIRED"
    assert detail["window"] == "image"
    # 충전 주기(120초) 안이다. 자정까지 초였다면 이 값을 훌쩍 넘는다(최대 86400).
    assert 1 <= detail["retryAfterSeconds"] <= 120


async def test_image_exempt_user_does_not_spend_clover(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """clover-goal-prompt.md CL-2: 면제 판정이 토큰·클로버보다 앞이라 예외 계정은 잔액이
    깎이지 않는다(`ImageCharge.source == "skipped"`)."""
    _reset_admission(monkeypatch, queue_limit=4)
    _stub_ready_capabilities(monkeypatch)
    _stub_job_pipeline(monkeypatch)
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)

    user = await _authed_user(db_client, db_session, rate_limit_exempt=True, clover_balance=100)

    resp = await db_client.post("/images/generate", json=_generate_payload())

    assert resp.status_code == 202
    await db_session.refresh(user)
    assert user.clover_balance == 100
