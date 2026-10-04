"""`api.llm.local_image` — `LocalImageClient`(집 PC 호출), 생성 직렬화, capabilities TTL 캐시.

전송 페이크는 `factories._patch_httpx`가 `api.llm.local_image.httpx.AsyncClient`에
`MockTransport`를 주입하는 monkeypatch 방식이다.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from redis.exceptions import RedisError

from api.core.config import settings
from api.core.redis import redis_client
from api.images.models import ImageStylePreset
from api.llm import local_image
from api.llm.client import LLMClientError
from api.llm.local_image import (
    UNAVAILABLE,
    LocalCapabilities,
    LocalImageBlockedError,
    LocalImageClient,
    ModelCapability,
    get_capabilities,
    keep_admission_alive,
    release_admission,
    reset_capabilities_cache,
    try_admit,
)
from factories import _patch_httpx


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
    data, mime = await _client().generate_image("a cat wizard", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert data == b"webp-bytes"
    assert mime == "image/webp"


async def test_non_200_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """500은 생성 실패다 — 안 감싸면 잡 러너(`images/router.py:68`)가 못 잡아 잡이
    running에 영원히 멈춘다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"internal error")

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")


async def test_empty_body_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")


async def test_connection_failure_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """집 PC가 꺼져 있거나 터널이 끊기면 연결 자체가 실패한다 — `httpx.HTTPError` 전체를
    잡지 않으면(비200만 잡으면) 이 경로가 그대로 새어나가 잡 러너의 `except LLMClientError`를
    비켜간다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")


async def test_422_with_prompt_reason_raises_block_error_with_reason_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 가드 사유를 구분 못 하면
    `_run_generation`과 라우터 로깅이 사유별로 분기·집계·로깅할 수 없어 사용자가 어떤 가드에 걸렸는지
    영원히 알 수 없다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "content blocked", "reason": "prompt"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageBlockedError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.reason == "prompt"


async def test_422_with_image_reason_raises_block_error_with_reason_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이미지 가드 사유가 프롬프트 가드로 잘못 표시되면, 재시도해도 소용없는데
    사용자에게 "표현을 바꾸라"는 틀린 안내가 나간다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "content blocked", "reason": "image"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageBlockedError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.reason == "image"


async def test_422_with_reference_reason_raises_block_error_with_reason_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """참조 이미지 사전 검사가 막은 요청이 일반 실패로 떨어지면, 사용자는 "다른 이미지를
    고르라"는 안내 대신 "모두 실패"를 보고 같은 참조로 다시 시도하며, 정책 차단마다 장애
    이벤트가 쌓인다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "reference image blocked", "reason": "reference"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageBlockedError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.reason == "reference"


async def test_422_missing_reason_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """422 본문 계약이 정의하지 않은 모양이다 — 이걸 차단으로 해석하면 계약 밖 422를 정책
    차단으로 오독해 근거 없이 "정책 위반"이라고 사용자에게 말하게 된다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "content blocked"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_syntax_detail_without_reason_is_not_an_input_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """집 PC 계약은 문법 오류 422 에 `reason: "syntax"` 를 싣는다 — `reason` 없는 422 는 계약상
    집 PC 가 보낸 것이 아니다. `detail` 문구가 문법 오류처럼 읽혀도 입력 오류로 올리면, 프록시가
    만든 422 를 "프롬프트 문법을 확인하라"는 안내로 사용자 탓으로 돌리게 된다."""
    from api.llm.local_image import LocalImageInputError

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "invalid prompt syntax"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, (LocalImageInputError, LocalImageBlockedError))


async def test_422_unknown_reason_value_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """계약 밖 reason(신규 가드 종류 등)이 오면 서버가 모르는 카테고리를 차단으로
    단정하지 않는다 — 계약이 "서버가 모르는 값이 오면 일반 실패로 접는다"고 정했다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "content blocked", "reason": "nsfw"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_non_json_body_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """프록시가 끼어들어 만든 422(HTML 오류 페이지 등)를 정책 차단으로 오독하면
    안 된다 — 422를 전용 예외로 올릴 때 명시적으로 요구한 안전장치다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, content=b"<html>not json</html>")

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_detail_string_is_never_interpreted_only_reason_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """분기는 오직 `reason`이다. `detail` 문구를 매칭에 쓰면 로컬이 문구를
    다듬을 때마다(오타 수정 등) 이 클라이언트가 깨진다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "완전히 다른 문구", "reason": "prompt"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageBlockedError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.reason == "prompt"


async def test_422_empty_body_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """화이트리스트 밖 422는 전부 일반 실패다. 빈
    본문(`.json()`이 `JSONDecodeError`)도 예외가 아니다 — 프록시가 만든 빈 422를 콘텐츠
    차단으로 오독하면 안 된다. 에러 경로 조사에서 "커버 0건"으로 확인된 경로다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422)

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_list_detail_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FastAPI 기본 검증 핸들러가 내는
    `{"detail": [{"loc": ..., "msg": ...}]}` 모양(`detail`이 리스트)도 `reason` 키가
    없으므로 화이트리스트 밖이다 — 에러 경로 조사가 "커버 0건, 주요 오분류 후보"로 지목한 경로."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "prompt"], "msg": "field required", "type": "missing"}]},
        )

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_list_detail_with_long_input_field_is_capped_in_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pydantic v2는 `include_input=True`가
    기본값이라, FastAPI 기본 검증 핸들러의 `detail` 리스트 각 항목에 검증 실패한
    제출값 원문(`input` 키)이 그대로 담길 수 있다 — 집 PC가 언젠가 `prompt`에 제약을
    걸면 그 원문이 캡 없이 로그로 샌다. 이전에는 `exc.response.text[:300]` 캡이 있었는데
    `{status} detail={detail!r}`로 바뀌며 한동안 사라졌다 — `repr(detail)`에 캡을
    되살렸는지 이 테스트가 고정한다."""
    long_prompt = "매우 긴 프롬프트 원문 " * 50  # 300자 캡을 확실히 넘긴다

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "detail": [
                    {"loc": ["body", "prompt"], "msg": "field required", "type": "missing", "input": long_prompt}
                ]
            },
        )

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image(long_prompt, ImageStylePreset.SOFT_PORTRAIT, "1:1")
    message = str(exc_info.value)
    assert long_prompt not in message
    assert len(message) < 400  # 캡이 살아 있으면 여유 있게 통과, 없으면 원문 그대로라 500자를 넘는다


async def test_422_with_syntax_reason_raises_input_error_syntax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """집 PC가 `reason: "syntax"`를 추가했다. 이 테스트는 화이트리스트 4값(`prompt`/`image`/`reference`/`syntax`)
    중 입력 오류로 가는 `syntax`를 고정한다."""
    from api.llm.local_image import LocalImageInputError

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "invalid prompt syntax", "reason": "syntax"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageInputError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.input_error == "syntax"


@pytest.mark.parametrize("status_code", [400, 429, 500])
async def test_non_422_status_codes_never_raise_block_error(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    """422 처리를 추가한다고 다른 비200까지 차단으로 넓히면, 진짜 장애(500)·
    계약 위반(400)·과부하(429)가 정책 차단으로 오인되어 잘못된 안내가 나간다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=b'{"detail":"irrelevant"}')

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


# ---- 400 (input_error 축, too_long) ------------------------------------------


async def test_400_invalid_request_raises_input_error_too_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1000자 초과 400(`{"detail":"invalid request"}`)과
    320토큰 초과 400(`{"detail":"prompt too long"}`)을 사용자에게는 `too_long` 하나로
    합친다 — 요구하는 행동이 같기 때문이다(1000자인지 320토큰인지는 서버 로그에서만 구분).

    구현자 요구사항: `LocalImageInputError(input_error="too_long")`
    (위 `test_422_with_syntax_reason_raises_input_error_syntax` 참고)."""
    from api.llm.local_image import LocalImageInputError  # 미구현 심볼 — 로컬 import

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "invalid request"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageInputError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.input_error == "too_long"


async def test_400_prompt_too_long_raises_input_error_too_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """위 테스트와 같은 축 — 320토큰 초과 400도
    `too_long`으로 합쳐진다."""
    from api.llm.local_image import LocalImageInputError  # 미구현 심볼 — 로컬 import

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "prompt too long"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageInputError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.input_error == "too_long"


async def test_400_unsupported_style_does_not_raise_input_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`{"detail":"unsupported style"}`은 계약 위반
    (우리 쪽 버그)이지 사용자가 고칠 수 있는 입력이 아니다 — `too_long`으로 뭉개면 안
    된다. 세 400 모양을 같은 버킷으로 접으면 이 구분이 사라지는 것이 이 테스트가 잡으려는
    신호다("unsupported style은 too_long이 아니다")."""
    from api.llm.local_image import LocalImageInputError  # 미구현 심볼 — 로컬 import

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "unsupported style"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageInputError)


async def test_400_invalid_reference_image_is_a_plain_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`{"detail":"invalid reference image"}` 은 참조 이미지의 형식·크기가 계약을 벗어났다는
    뜻이다. 사용자가 고를 수 있는 참조는 이 서비스가 만든 이미지뿐이라 이건 우리 쪽 버그다 —
    입력 오류로 올리면 "프롬프트가 너무 길어요" 라는 거짓 안내가 나가고 장애 신호도 사라진다."""
    from api.llm.local_image import LocalImageInputError

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "invalid reference image"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, (LocalImageInputError, LocalImageBlockedError))


@pytest.mark.parametrize("detail", ["invalid request", "invalid reference image"])
async def test_400_on_a_request_carrying_a_reference_image_is_a_plain_failure(
    monkeypatch: pytest.MonkeyPatch, detail: str
) -> None:
    """참조를 실은 요청에서 `invalid request` 는 프롬프트 길이보다 참조 인코딩 길이 초과일 수 있고,
    그 길이는 우리가 보내기 전에 검증한다 — 나오면 우리 쪽 버그다. `too_long` 으로 올리면 참조를
    붙인 사용자에게 "프롬프트가 너무 길어요" 라는 거짓 안내가 나간다."""
    from api.llm.local_image import LocalImageInputError

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": detail})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image(
            "a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1", reference_image=b"reference-bytes"
        )
    assert not isinstance(exc_info.value, (LocalImageInputError, LocalImageBlockedError))


async def test_reference_image_is_sent_as_single_line_standard_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    """집 PC 는 `reference_image` 를 표준 base64 한 줄(개행·`data:` 접두사 없음)로 받는다.
    76자마다 줄을 바꾸는 인코더로 바뀌면 서버가 400 으로 거절한다 — 참조 바이트를 76자가
    넘게 인코딩되는 길이로 둬야 그 차이가 드러난다."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    reference = bytes(range(200))
    await _client().generate_image(
        "a cat", ImageStylePreset.SOFT_PORTRAIT, "3:4", reference_image=reference
    )

    body = captured["body"]
    assert isinstance(body, dict)
    encoded = body.pop("reference_image")
    assert isinstance(encoded, str)
    assert "\n" not in encoded
    assert not encoded.startswith("data:")
    assert base64.b64decode(encoded, validate=True) == reference
    assert body == {"prompt": "a cat", "model": "v1", "style": "soft_portrait", "aspect_ratio": "3:4"}


@pytest.mark.parametrize("style", [ImageStylePreset.SOFT_PORTRAIT, ImageStylePreset.PIXEL_ART])
async def test_request_body_carries_prompt_unmodified_and_access_headers(
    monkeypatch: pytest.MonkeyPatch, style: ImageStylePreset
) -> None:
    """서버는 프롬프트를 가공하지 않고 model/style/aspect_ratio 불투명 id만
    싣는다. 여기서 suffix를 붙이거나 필드를 더 보내면 집 PC(별도 저장소)의 계약을 어긴다.

    두 스타일로 파라미터화해
    "인자를 바꾸면 바디도 바뀐다"를 실제로 증명한다 — style.value를 그대로 싣도록 바뀌기
    전에는 이 파일 어떤 테스트도 이걸 증명하지 못했다(전부 BASE 하나만 썼다)."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["headers"] = request.headers
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    prompt = "a cat wizard, extremely detailed, dramatic lighting"
    await _client().generate_image(prompt, style, "2:3")

    assert captured["body"] == {
        "prompt": prompt,
        "model": "v1",
        "style": style.value,
        "aspect_ratio": "2:3",
    }
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert headers["CF-Access-Client-Id"] == "cid"
    assert headers["CF-Access-Client-Secret"] == "csecret"


async def test_request_body_carries_wire_ids_not_public_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """공개 model id(`v1`)를 그대로 보내면 홈PC의
    실제 체크포인트 id(`opaque-wire-id`)와 맞지 않아 계약 위반으로 모든 요청이
    400이 된다 — 설정에 둔 와이어 id가 실제 요청 바디에 실리는지 고정한다.

    style은 더 이상 별도 와이어 설정이 없다 —
    `style.value`가 그대로 실리는지는 위
    `test_request_body_carries_prompt_unmodified_and_access_headers`가 담당한다."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "opaque-wire-id")

    await _client().generate_image("a cat wizard", ImageStylePreset.SOFT_PORTRAIT, "1:1")

    assert captured["body"] == {
        "prompt": "a cat wizard",
        "model": "opaque-wire-id",
        "style": "soft_portrait",
        "aspect_ratio": "1:1",
    }


# ---- 생성 직렬화 (모듈 수준 asyncio.Semaphore(1)) ------------------------------


async def test_concurrent_generate_calls_never_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """두 생성 호출이 겹치면 8GB VRAM에서 GPU OOM인데 증상이 조용하다. 핸들러
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
        client_a.generate_image("prompt-1", ImageStylePreset.SOFT_PORTRAIT, "1:1"),
        client_b.generate_image("prompt-2", ImageStylePreset.SOFT_PORTRAIT, "1:1"),
    )

    assert events == ["enter", "exit", "enter", "exit"]


# ---- admission (모든 워커가 함께 보는 Redis 정렬 집합 — 멤버 하나 = admit 된 잡 하나, 점수 = 만료
# 시각). 검사(전역 상한·유저별 1칸)와 추가가 Lua 한 번으로 서버에서 원자적으로 끝나야 동시 도착한
# 요청이 둘 다 추가 이전 값을 읽고 통과하는 일이 없다. 워커가 여럿이면 워커 둘 = Redis 연결
# 둘이므로, 아래 테스트는 클라이언트를 둘 만들어 같은 키를 다투게 한다. ---------------------------


@pytest_asyncio.fixture
async def second_connection() -> AsyncGenerator[Redis, None]:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def test_try_admit_admits_up_to_the_limit_then_rejects_and_release_restores_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전역 상한(2)만큼만 admit되고 그 다음은 거절돼야 한다 — 안 그러면 사용자들이 GPU 직렬
    처리량을 독점한다. `release_admission` 한 번으로 슬롯 하나가 돌아오는지까지 고정한다.

    유저별 큐가 1칸이라 **서로 다른 유저**로 채워야 전역 상한을
    본다. 같은 유저로 두 번 부르면 유저별 1칸에서 먼저 걸려 전역 상한을 아예 못 본다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 2)
    user_a, user_b, user_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    admission_a = await try_admit(redis_client, user_a)
    admission_b = await try_admit(redis_client, user_b)
    assert admission_a is not None
    assert admission_b is not None
    assert await try_admit(redis_client, user_c) is None

    await release_admission(redis_client, admission_a)
    assert await try_admit(redis_client, user_a) is not None


async def test_releasing_an_admission_that_is_not_held_does_not_open_a_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """대응하는 admit 없이 여분으로 해제돼도 자리가 늘면 안 된다 — 늘면 그 뒤 admit 두 번이
    상한(1)을 넘어 통과해 상한이 사실상 무제한이 된다.

    두 번째 admit은 **다른 유저**여야 한다 — 같은 유저면 유저별 1칸에서 거절돼
    전역 자리가 늘었든 아니든 같은 결과가 나와(항진명제) 아무것도 논증하지 못한다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 1)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()

    await release_admission(redis_client, f"{user_a}:never-admitted")

    assert await try_admit(redis_client, user_a) is not None
    assert await try_admit(redis_client, user_b) is None


async def test_release_admission_leaves_nothing_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    """반납이 멤버를 지우지 않으면 정렬 집합이 접속한 유저 수만큼 자라고, 만료 전까지 그 유저의
    칸도 차 있다. 판정만 보는 테스트로는 만료가 결국 회수해 버려 안 잡힐 수 있다 — 집합 자체를
    들여다본다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 4)
    user = uuid.uuid4()

    admission = await try_admit(redis_client, user)
    assert admission is not None
    assert await redis_client.zcard(local_image.ADMISSION_KEY) == 1

    await release_admission(redis_client, admission)

    assert await redis_client.zcard(local_image.ADMISSION_KEY) == 0


async def test_the_global_limit_holds_across_two_workers(
    monkeypatch: pytest.MonkeyPatch, second_connection: Redis
) -> None:
    """워커마다 따로 세면 워커 수만큼 상한이 곱해져 GPU 대기열이 상한의 몇 배로 쌓인다. 서로 다른
    유저 다섯이 두 워커에 나뉘어 **동시에** 들어와도 합쳐서 4건만 들어가야 한다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 4)
    users = [uuid.uuid4() for _ in range(5)]
    connections = [redis_client, second_connection]

    results = await asyncio.gather(*[try_admit(connections[index % 2], user) for index, user in enumerate(users)])

    assert sum(result is not None for result in results) == 4
    assert await redis_client.zcard(local_image.ADMISSION_KEY) == 4


async def test_one_user_gets_one_slot_across_two_workers(
    monkeypatch: pytest.MonkeyPatch, second_connection: Redis
) -> None:
    """같은 유저의 두 요청이 서로 다른 워커로 가면 워커마다 따로 센 유저 칸은 둘 다 비어 있어 둘 다
    들어간다. 전역 상한은 넉넉히 두고(4) 다른 유저는 같은 순간 통과하는 것까지 봐야 "전역 상한이
    1" 과 구분된다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 4)
    user, other_user = uuid.uuid4(), uuid.uuid4()

    first, second, other = await asyncio.gather(
        try_admit(redis_client, user),
        try_admit(second_connection, user),
        try_admit(second_connection, other_user),
    )

    assert sum(result is not None for result in (first, second)) == 1
    assert other is not None


async def test_an_admission_whose_worker_died_is_reclaimed_after_its_lease(
    monkeypatch: pytest.MonkeyPatch, second_connection: Redis
) -> None:
    """칸을 쥔 워커가 반납 없이 죽으면(배포 재생성·크래시) 그 칸은 만료 시각이 지나면 회수돼야 한다.
    회수가 없으면 그 유저는 영원히 `QUEUE_FULL` 을 받고, 전역 칸이 넷 다 그렇게 새면 아무도 못
    만든다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 4)
    monkeypatch.setattr(local_image, "ADMISSION_LEASE_MS", 300)
    user = uuid.uuid4()

    assert await try_admit(redis_client, user) is not None
    # 이 칸의 워커는 여기서 "죽는다" — 반납도 갱신도 하지 않는다.
    assert await try_admit(second_connection, user) is None

    await asyncio.sleep(0.4)

    assert await try_admit(second_connection, user) is not None


async def test_a_live_job_keeps_its_admission_past_the_lease(
    monkeypatch: pytest.MonkeyPatch, second_connection: Redis
) -> None:
    """잡은 대기를 포함해 몇 분씩 걸린다. 갱신이 만료 시각을 밀어 주지 않으면 살아 있는 잡의 칸이
    만료로 풀려, 같은 유저가 잡 둘을 세우고 전역 상한도 넘친다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 4)
    monkeypatch.setattr(local_image, "ADMISSION_LEASE_MS", 300)
    monkeypatch.setattr(local_image, "ADMISSION_HEARTBEAT_SECONDS", 0.05)
    user = uuid.uuid4()

    admission = await try_admit(redis_client, user)
    assert admission is not None
    heartbeat = asyncio.create_task(keep_admission_alive(redis_client, admission))
    try:
        await asyncio.sleep(0.6)
        assert await try_admit(second_connection, user) is None
    finally:
        heartbeat.cancel()
        await release_admission(redis_client, admission)


async def test_a_heartbeat_after_release_does_not_revive_the_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    """반납과 갱신은 서로 다른 태스크라 반납 직후 갱신이 한 번 더 도착할 수 있다. 갱신이 없는 칸을
    새로 만들면 반납한 칸이 만료까지 되살아나, 그 자리에 이미 다른 잡이 들어갔다면 상한을 하나 넘긴다."""
    monkeypatch.setattr(settings, "local_image_queue_limit", 4)
    monkeypatch.setattr(local_image, "ADMISSION_HEARTBEAT_SECONDS", 0.01)
    user = uuid.uuid4()

    admission = await try_admit(redis_client, user)
    assert admission is not None
    await release_admission(redis_client, admission)

    heartbeat = asyncio.create_task(keep_admission_alive(redis_client, admission))
    try:
        await asyncio.sleep(0.1)
    finally:
        heartbeat.cancel()

    assert await redis_client.zscore(local_image.ADMISSION_KEY, admission) is None


# ---- 워커 사이의 생성 직렬화 (Redis 락) ------------------------------------------

_HOME_PC_WORKER_SCRIPT = """
import asyncio, sys
from api.images.models import ImageStylePreset
from api.llm.local_image import LocalImageClient

async def main() -> None:
    client = LocalImageClient(
        "v1", base_url=sys.argv[1], access_client_id="cid", access_client_secret="csecret"
    )
    print("ready", flush=True)
    sys.stdin.readline()
    await client.generate_image("prompt", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    print("generated", flush=True)

asyncio.run(main())
"""


class _FakeHomePc:
    """집 PC 와 같은 계약으로 답한다 — 다른 생성이 진행 중이면 대기열 없이 즉시 429."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self.statuses: list[int] = []

    def handle(self) -> int:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            busy = self._in_flight > 1
        try:
            if not busy:
                time.sleep(0.5)
            status = 429 if busy else 200
        finally:
            with self._lock:
                self._in_flight -= 1
                self.statuses.append(status)
        return status


def _serve_fake_home_pc(home_pc: _FakeHomePc) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length", "0")))
            status = home_pc.handle()
            body = b"webp-bytes" if status == 200 else b'{"detail": "busy"}'
            self.send_response(status)
            self.send_header("content-type", "image/webp" if status == 200 else "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_two_worker_processes_never_call_the_home_pc_at_the_same_time() -> None:
    """워커가 둘이면 프로세스 안 세마포어는 워커마다 따로라 둘이 집 PC 를 동시에 부른다. 집 PC 는
    두 번째를 즉시 429 로 거절하므로 그 이미지는 실패한다(GPU 는 안 터지지만 사용자는 실패를 본다).
    실제 프로세스 둘이 같은 순간 생성을 시작해도 집 PC 가 본 동시 요청은 1이어야 한다."""
    home_pc = _FakeHomePc()
    server = _serve_fake_home_pc(home_pc)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    env = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _HOME_PC_WORKER_SCRIPT, base_url],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(2)
    ]
    try:
        for worker in workers:
            assert worker.stdout is not None
            assert worker.stdout.readline().strip() == "ready"
        # 둘 다 import 를 끝낸 뒤 같은 순간에 출발시킨다 — 기동 시간 차이로 겹치지 않고 지나가면
        # 락이 없어도 초록이 된다.
        for worker in workers:
            assert worker.stdin is not None
            worker.stdin.write("go\n")
            worker.stdin.flush()
        outputs = [worker.communicate(timeout=30) for worker in workers]
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
        server.shutdown()

    assert [worker.returncode for worker in workers] == [0, 0], [stderr for _, stderr in outputs]
    assert home_pc.max_in_flight == 1
    assert home_pc.statuses == [200, 200]


async def test_a_redis_failure_while_waiting_for_the_generation_lock_fails_only_that_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """락을 못 확인한 채 집 PC 를 부르면 다른 워커와 겹칠 수 있다 — 부르지 않고 그 장을 실패로
    접는다. `LLMClientError` 여야 잡의 장 단위 실패·환불 경로를 탄다(다른 예외면 로그 한 줄로만
    남고 Bugsink 에 안 간다)."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    async def failing_wait_for_lock(*args: object, **kwargs: object) -> str | None:
        raise RedisError("redis down")

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(local_image, "wait_for_lock", failing_wait_for_lock)

    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert calls == []


async def test_a_call_that_outlives_the_cap_fails_and_frees_the_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx 타임아웃은 단계별이라 호출 전체가 락 TTL 보다 길어질 수 있다. 그러면 락이 만료돼 다음
    워커가 들어와 집 PC 를 동시에 부른다. 호출 전체 상한에서 끊고, 끊긴 뒤 락이 바로 풀려 다음 장이
    TTL 만큼 기다리지 않아야 한다."""

    async def slow_handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, slow_handler)
    monkeypatch.setattr(settings, "local_image_timeout_seconds", 0.1)
    monkeypatch.setattr(local_image, "GENERATION_CALL_CAP_MARGIN_SECONDS", 0.1)

    started = time.monotonic()
    with pytest.raises(LLMClientError):
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")

    assert time.monotonic() - started < 1.5
    assert await redis_client.exists(local_image.GENERATION_LOCK_KEY) == 0


async def test_the_generation_lock_outlives_the_capped_call() -> None:
    """락 TTL 이 호출 전체 상한보다 짧으면 정상적으로 오래 걸린 호출 도중에 락이 풀려 다른 워커가
    집 PC 를 동시에 부른다. 두 값의 대소를 고정한다."""
    assert local_image.generation_lock_ttl_ms() > local_image.generation_call_cap_seconds() * 1000


# ---- capabilities TTL 캐시 ------------------------------------------------------


def _capabilities_body(
    *, ready: bool = True, models: list[dict[str, object]] | None = None
) -> dict[str, object]:
    if models is None:
        models = [{"id": "v1", "styles": ["base"], "aspect_ratios": ["1:1"]}]
    return {"ready": ready, "models": models}


async def test_cold_cache_probes_the_local_server(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    """배포 직후 콜드 캐시에서도 (`generate_images`뿐 아니라 `/images/models`도) 최초
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


async def test_slow_failure_is_cached_for_the_ttl(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    """조회가 TTL보다 오래 걸린 뒤 실패해도 그 결과는
    TTL 동안 캐시돼야 한다. 기록 시각을 조회 **전**에 잡으면 기록 즉시 만료돼, 집 PC가
    느리게 죽어 있는 동안 매 요청이 DB 커넥션을 쥔 채 조회를 다시 기다린다."""
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        await asyncio.sleep(0.1)
        return httpx.Response(503)

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 0.05)

    assert await get_capabilities() == UNAVAILABLE
    assert await get_capabilities() == UNAVAILABLE

    assert calls["n"] == 1


async def test_concurrent_cold_calls_share_one_probe(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    """콜드/만료 시점에 동시에 들어온 호출이 각자 조회하면
    조회 N개가 각자 요청 세션(DB 커넥션)을 쥔 채 기다린다 — 조회는 하나만 나가야 한다."""
    calls = {"n": 0}
    release = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        await release.wait()
        return httpx.Response(200, json=_capabilities_body())

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 30)

    async def release_after_yield() -> None:
        for _ in range(10):
            await asyncio.sleep(0)
        release.set()

    *results, _ = await asyncio.gather(*(get_capabilities() for _ in range(5)), release_after_yield())

    assert calls["n"] == 1
    assert results == [
        LocalCapabilities(
            ready=True, models=(ModelCapability(model_id="v1", styles=("base",), aspect_ratios=("1:1",)),)
        )
    ] * 5


async def test_probe_uses_its_own_short_timeout_not_the_generation_timeout(
    monkeypatch: pytest.MonkeyPatch, reset_capabilities: None
) -> None:
    """조회를 기다리는 동안 요청 세션이 DB 커넥션을 쥐므로
    조회 타임아웃은 생성용(`local_image_timeout_seconds`)과 분리된 5초여야 한다. 생성 경로는
    그대로 설정값을 쓴다."""
    real_client = httpx.AsyncClient
    timeouts: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json=_capabilities_body())
        return httpx.Response(200, content=b"webp-bytes", headers={"content-type": "image/webp"})

    def factory(**kwargs: object) -> httpx.AsyncClient:
        timeouts.append(kwargs.get("timeout"))
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("api.llm.local_image.httpx.AsyncClient", factory)
    monkeypatch.setattr(settings, "local_image_base_url", "https://local.example")
    monkeypatch.setattr(settings, "local_image_capabilities_ttl_seconds", 30)
    monkeypatch.setattr(settings, "local_image_timeout_seconds", 90)

    await get_capabilities()
    await _client().generate_image("a cat wizard", ImageStylePreset.SOFT_PORTRAIT, "1:1")

    assert timeouts == [5, 90]
