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
    LocalImageBlockedError,
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
    data, mime = await _client().generate_image("a cat wizard", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert data == b"webp-bytes"
    assert mime == "image/webp"


async def test_non_200_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """LC-4: 500은 생성 실패다 — 안 감싸면 잡 러너(`images/router.py:68`)가 못 잡아 잡이
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
    """guard-techspec.md GT-1 / guard-contract-md LC-4a: 두 가드 사유를 구분 못 하면
    GT-3/GT-5가 사유별로 분기·집계·로깅할 수 없어 사용자가 어떤 가드에 걸렸는지
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
    사용자에게 "표현을 바꾸라"는 틀린 안내가 나간다(guard-goal-prompt.md G-4)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "content blocked", "reason": "image"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LocalImageBlockedError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert exc_info.value.reason == "image"


async def test_422_missing_reason_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LC-4a가 정의하지 않은 모양이다 — 이걸 차단으로 해석하면 계약 밖 422를 정책
    차단으로 오독해 근거 없이 "정책 위반"이라고 사용자에게 말하게 된다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "content blocked"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_unknown_reason_value_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """계약 밖 reason(신규 가드 종류 등)이 오면 서버가 모르는 카테고리를 차단으로
    단정하지 않는다 — LC-4a "서버가 모르는 값이 오면 일반 실패로 접는다"."""

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
    안 된다 — GT-1이 명시적으로 요구하는 안전장치다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, content=b"<html>not json</html>")

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_detail_string_is_never_interpreted_only_reason_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LC-4a: 분기는 오직 `reason`이다. `detail` 문구를 매칭에 쓰면 로컬이 문구를
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
    """image-style-7-goal-prompt.md IS-9: 화이트리스트 밖 422는 전부 일반 실패다. 빈
    본문(`.json()`이 `JSONDecodeError`)도 예외가 아니다 — 프록시가 만든 빈 422를 콘텐츠
    차단으로 오독하면 안 된다. I-2 조사에서 "커버 0건"으로 확인된 경로다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422)

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


async def test_422_list_detail_collapses_to_plain_llm_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """image-style-7-goal-prompt.md IS-9: FastAPI 기본 검증 핸들러가 내는
    `{"detail": [{"loc": ..., "msg": ...}]}` 모양(`detail`이 리스트)도 `reason` 키가
    없으므로 화이트리스트 밖이다 — I-2가 "커버 0건, 주요 오분류 후보"로 지목한 경로."""

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
    """image-style-7-goal-prompt.md IS-11 §3-12: pydantic v2는 `include_input=True`가
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
    """image-style-7-goal-prompt.md IS-9: 집 PC에 `reason: "syntax"` 추가를 요구했으나
    (§4-1) **아직 회신 전이다.** 회신 전까지 keyless `{"detail": "invalid prompt syntax"}`는
    여전히 일반 실패로 남는다 — `test_422_missing_reason_collapses_to_plain_llm_client_error`가
    이미 그 경로(reason 키 없음 → 일반 실패)를 고정하므로 여기서 다시 쓰지 않는다.

    이 테스트는 회신 후 화이트리스트가 3값(`prompt`/`image`/`syntax`)으로 확장됐을 때의
    계약을 **미리** 고정한다 — 구현이 그 전제로 짜이기 때문이다.

    구현자 요구사항: `api.llm.local_image.LocalImageInputError`를 `LocalImageBlockedError`와
    같은 모양으로 신설한다 — `__init__(self, *, input_error: str) -> None`,
    속성 `.input_error`(IS-8 `input_error` 축, 값 `too_long`/`syntax`)."""
    from api.llm.local_image import LocalImageInputError  # 미구현 심볼 — 로컬 import

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
    """GT-1이 422 처리를 추가한다고 다른 비200까지 차단으로 넓히면, 진짜 장애(500)·
    계약 위반(400)·과부하(429)가 정책 차단으로 오인되어 잘못된 안내가 나간다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=b'{"detail":"irrelevant"}')

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageBlockedError)


# ---- 400 (IS-8: input_error 축, too_long) ------------------------------------


async def test_400_invalid_request_raises_input_error_too_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """image-style-7-goal-prompt.md IS-8: 1000자 초과 400(`{"detail":"invalid request"}`)과
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
    """image-style-7-goal-prompt.md IS-8: 위 테스트와 같은 축 — 320토큰 초과 400도
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
    """image-style-7-goal-prompt.md IS-8: `{"detail":"unsupported style"}`은 계약 위반
    (우리 쪽 버그)이지 사용자가 고칠 수 있는 입력이 아니다 — `too_long`으로 뭉개면 안
    된다. 세 400 모양을 같은 버킷으로 접으면 이 구분이 사라지는 것이 이 테스트가 잡으려는
    신호다(IS-8: "unsupported style은 too_long이 아니다")."""
    from api.llm.local_image import LocalImageInputError  # 미구현 심볼 — 로컬 import

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "unsupported style"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError) as exc_info:
        await _client().generate_image("a cat", ImageStylePreset.SOFT_PORTRAIT, "1:1")
    assert not isinstance(exc_info.value, LocalImageInputError)


@pytest.mark.parametrize("style", [ImageStylePreset.SOFT_PORTRAIT, ImageStylePreset.PIXEL_ART])
async def test_request_body_carries_prompt_unmodified_and_access_headers(
    monkeypatch: pytest.MonkeyPatch, style: ImageStylePreset
) -> None:
    """LG-3/LC-2: 서버는 프롬프트를 가공하지 않고 model/style/aspect_ratio 불투명 id만
    싣는다. 여기서 suffix를 붙이거나 필드를 더 보내면 집 PC(별도 저장소)의 계약을 어긴다.

    image-style-7-goal-prompt.md IS-2/2차 인터뷰 결정 4: 두 스타일로 파라미터화해
    "인자를 바꾸면 바디도 바뀐다"를 실제로 증명한다 — style.value를 그대로 싣는 IS-2
    변경 전에는 이 파일 어떤 테스트도 이걸 증명하지 못했다(전부 BASE 하나만 썼다)."""
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
    """local-image-gen-goal-prompt.md LG-19: 공개 model id(`v1`)를 그대로 보내면 홈PC의
    실제 체크포인트 id(`sdxl-anime-v1`)와 맞지 않아 계약(LC-4) 위반으로 모든 요청이
    400이 된다 — 설정에 둔 와이어 id가 실제 요청 바디에 실리는지 고정한다.

    image-style-7-goal-prompt.md IS-2: style은 더 이상 별도 와이어 설정이 없다 —
    `style.value`가 그대로 실리는지는 위
    `test_request_body_carries_prompt_unmodified_and_access_headers`가 담당한다."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/webp"})

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(settings, "local_image_model_wire_id", "sdxl-anime-v1")

    await _client().generate_image("a cat wizard", ImageStylePreset.SOFT_PORTRAIT, "1:1")

    assert captured["body"] == {
        "prompt": "a cat wizard",
        "model": "sdxl-anime-v1",
        "style": "soft_portrait",
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
        client_a.generate_image("prompt-1", ImageStylePreset.SOFT_PORTRAIT, "1:1"),
        client_b.generate_image("prompt-2", ImageStylePreset.SOFT_PORTRAIT, "1:1"),
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
