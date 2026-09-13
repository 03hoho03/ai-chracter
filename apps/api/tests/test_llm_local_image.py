"""`api.llm.local_image` — `LocalImageClient`(집 PC 호출), 생성 직렬화, capabilities TTL 캐시.

계약은 `local-image-gen-contract.md` LC-1/LC-2/LC-7, 설계는 `local-image-gen-techspec.md`
LT-1/LT-2/LT-3. 전송 페이크는 아래 `_patch_httpx`가 `api.llm.local_image.httpx.AsyncClient`에
`MockTransport`를 주입하는 monkeypatch 방식이다.
"""

import asyncio
import json
from collections.abc import Callable, Generator

import httpx
import pytest

from api.core.config import settings
from api.images.models import ImageStylePreset
from api.llm.client import LLMClientError
from api.llm.local_image import (
    UNAVAILABLE,
    LocalCapabilities,
    LocalImageClient,
    ModelCapability,
    get_capabilities,
    release_admission,
    reset_capabilities_cache,
    try_admit,
)


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], object]
) -> None:
    """local_image가 만드는 httpx.AsyncClient에 MockTransport를 주입한다."""
    real_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("api.llm.local_image.httpx.AsyncClient", factory)


def _client() -> LocalImageClient:
    return LocalImageClient(
        "v1", base_url="https://local.example", access_client_id="cid", access_client_secret="csecret"
    )


@pytest.fixture
def reset_capabilities() -> Generator[None, None, None]:
    reset_capabilities_cache()
    yield
    reset_capabilities_cache()


# ---- LocalImageClient.generate_image ---------------------------------------


async def test_generate_image_returns_bytes_and_content_type_as_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"webp-bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    data, mime = await _client().generate_image("a cat wizard", ImageStylePreset.BASE, "1:1")
    assert data == b"webp-bytes"
    assert mime == "image/webp"


async def test_non_200_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """LC-4: 500은 생성 실패다 — 안 감싸면 잡 러너(`images/router.py:68`)가 못 잡아 잡이
    running에 영원히 멈춘다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"internal error")

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.BASE, "1:1")


async def test_empty_body_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.BASE, "1:1")


async def test_connection_failure_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """집 PC가 꺼져 있거나 터널이 끊기면 연결 자체가 실패한다 — `httpx.HTTPError` 전체를
    잡지 않으면(비200만 잡으면) 이 경로가 그대로 새어나가 잡 러너의 `except LLMClientError`를
    비켜간다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.BASE, "1:1")


async def test_request_body_carries_prompt_unmodified_and_access_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LG-3/LC-2: 서버는 프롬프트를 가공하지 않고 model/style/aspect_ratio 불투명 id만
    싣는다. 여기서 suffix를 붙이거나 필드를 더 보내면 집 PC(별도 저장소)의 계약을 어긴다."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["headers"] = request.headers
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    prompt = "a cat wizard, extremely detailed, dramatic lighting"
    await _client().generate_image(prompt, ImageStylePreset.BASE, "2:3")

    assert captured["body"] == {
        "prompt": prompt,
        "model": "v1",
        "style": "base",
        "aspect_ratio": "2:3",
    }
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert headers["CF-Access-Client-Id"] == "cid"
    assert headers["CF-Access-Client-Secret"] == "csecret"


async def test_request_body_carries_wire_ids_not_public_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """local-image-gen-goal-prompt.md LG-19: 공개 id(`v1`/`base`)를 그대로 보내면 홈PC의
    실제 체크포인트/LoRA id(`sdxl-anime-v1`/`default`)와 맞지 않아 계약(LC-4) 위반으로
    모든 요청이 400이 된다 — 설정에 둔 와이어 id가 실제 요청 바디에 실리는지 고정한다."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "sdxl-anime-v1")
    monkeypatch.setattr(settings, "local_image_style_wire_id", "default")

    await _client().generate_image("a cat wizard", ImageStylePreset.BASE, "1:1")

    assert captured["body"] == {
        "prompt": "a cat wizard",
        "model": "sdxl-anime-v1",
        "style": "default",
        "aspect_ratio": "1:1",
    }


# ---- 생성 직렬화 (모듈 수준 asyncio.Semaphore(1), LG-6/LT-1) ------------------


async def test_concurrent_generate_calls_never_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """두 생성 호출이 겹치면 8GB VRAM에서 GPU OOM인데 증상이 조용하다(LG-6). 핸들러
    진입/이탈을 기록해 두 번째 호출이 첫 번째가 끝난 뒤에야 진입하는지 고정한다."""
    events: list[str] = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        events.append("enter")
        await asyncio.sleep(0.01)
        events.append("exit")
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    client_a = _client()
    client_b = _client()

    await asyncio.gather(
        client_a.generate_image("prompt-1", ImageStylePreset.BASE, "1:1"),
        client_b.generate_image("prompt-2", ImageStylePreset.BASE, "1:1"),
    )

    assert events == ["enter", "exit", "enter", "exit"]


# ---- admission (모듈 수준 정수, LT-3 — 의미가 "generate_image 호출 중"에서 "admit된
# 잡"으로 바뀌었다. P2-R: 상한 검사와 증가가 서로 다른 시점에 있으면(검사는 라우터에서,
# 증가는 이 카운터의 옛 위치인 `generate_image` 진입 시점에서) 그 사이의 진짜 await
# (`create_job`)가 동시 요청을 전부 증가 이전 값으로 통과시킨다 — 그래서 `try_admit`이
# 검사+증가를 하나의 동기 블록으로 묶는다. `generate_image`는 더 이상 이 카운터를
# 건드리지 않는다(세마포어 직렬화는 위 `test_concurrent_generate_calls_never_overlap`가
# 이미 고정한다). ----------------------------------------------------------------


async def test_try_admit_admits_up_to_the_limit_then_rejects_and_release_restores_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """상한(2)만큼만 admit되고 그 다음은 거절돼야 한다 — 안 그러면 한 사용자가 GPU 직렬
    처리량을 독점한다. `release_admission` 한 번으로 슬롯 하나가 돌아오는지까지 고정한다."""
    monkeypatch.setattr("api.llm.local_image._queue_depth", 0)
    monkeypatch.setattr(settings, "local_image_queue_limit", 2)

    assert try_admit() is True
    assert try_admit() is True
    assert try_admit() is False

    release_admission()
    assert try_admit() is True

    release_admission()
    release_admission()


async def test_release_admission_does_not_go_below_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """대응하는 admit 없이 여분으로 해제되면 카운터가 음수로 내려가, 그 뒤 admit 두 번이
    상한(1)을 넘어 통과해버린다 — 0 바닥을 고정하지 않으면 상한이 사실상 무제한이 된다."""
    monkeypatch.setattr("api.llm.local_image._queue_depth", 0)
    monkeypatch.setattr(settings, "local_image_queue_limit", 1)

    release_admission()

    assert try_admit() is True
    assert try_admit() is False

    release_admission()


# ---- capabilities TTL 캐시 (LT-2/LG-18) --------------------------------------


def _capabilities_body(
    *, ready: bool = True, models: list[dict[str, object]] | None = None
) -> dict[str, object]:
    if models is None:
        models = [{"id": "v1", "styles": ["base"], "aspect_ratios": ["1:1"]}]
    return {"ready": ready, "models": models}


async def test_cold_cache_probes_the_local_server(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    """LG-18: 배포 직후 콜드 캐시에서도 (`generate_images`뿐 아니라 `/images/models`도) 최초
    호출은 반드시 프로브해야 한다 — 안 그러면 첫 요청이 사전 차단을 아예 못 받는다."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_capabilities_body())

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 30)

    caps = await get_capabilities()

    assert calls["n"] == 1
    assert caps == LocalCapabilities(
        ready=True, models=(ModelCapability(model_id="v1", styles=("base",), aspect_ratios=("1:1",)),)
    )


async def test_within_ttl_does_not_reprobe(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_capabilities_body())

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 30)

    await get_capabilities()
    await get_capabilities()

    assert calls["n"] == 1


async def test_reprobes_after_ttl_expires(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    """TTL이 지났는데도 캐시를 계속 믿으면 집 PC가 복구된 뒤에도 계속 불가로 오판하거나
    (또는 그 반대로) 꺼진 뒤에도 계속 가용으로 오판한다."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_capabilities_body())

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 0.05)

    await get_capabilities()
    await asyncio.sleep(0.15)
    await get_capabilities()

    assert calls["n"] == 2


async def test_connection_failure_probe_collapses_to_unavailable(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 30)

    assert await get_capabilities() == UNAVAILABLE


async def test_non_200_probe_collapses_to_unavailable(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 30)

    assert await get_capabilities() == UNAVAILABLE


async def test_malformed_json_probe_collapses_to_unavailable(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    """`ready: false`가 아니라 응답 자체가 깨진 경우(빈 페이로드·JSON 아님)도 "불가"로
    접어야 한다 — 파싱 예외가 새어나가면 `/images/models`가 500이 된다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 30)

    assert await get_capabilities() == UNAVAILABLE
