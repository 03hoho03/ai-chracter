"""집 PC 자가 호스팅 이미지 생성 서버 클라이언트 + capabilities 프로브/캐시.

capabilities 조회를 한 함수로 합친 이유는 콜드 캐시에서도 `generate_images`의 사전 차단이
동작해야 해서다 — `/images/models`와 `generate_images` 두 호출부가 이 함수 하나를 공유한다.

Pillow는 import하지 않는다 — 서버가 픽셀을 열어 볼 일이 없기 때문이다. 콘텐츠 가드는 집
PC가 생성 전(프롬프트)·생성 후(이미지) 2단계로 돌리고(DEPLOY.md "이미지 생성" 절), 서버는 그 결과인
`422`를 받아 `LocalImageBlockedError`로 정규화하기만 한다 — 판정을
서버에서 다시 하지 않으니 이미지 바이트를 디코드할 이유가 없다. Pillow는 import에만 3.7MB를
읽고 이 모듈은 모든 기동 경로(`llm/dependencies.py`)에 걸려 있으므로 그 비용을 되살리지
않는다.
"""

import time
import uuid
from asyncio import Lock, Semaphore
from dataclasses import dataclass

import httpx

from api.core.config import settings
from api.images.models import ImageBlockedReason, ImageInputError, ImageStylePreset
from api.llm.client import LLMClientError
from api.llm.image import ImageClient


class LocalImageBlockedError(LLMClientError):
    """집 PC의 콘텐츠 정책 가드(프롬프트 사전 차단 · 이미지 사후 검증)가 422로 차단한
    경우에만 올린다. `LLMClientError`를 상속하는 이유는
    기존 `except LLMClientError` 경로가 이 예외를 놓쳐도 일반 실패로 안전하게 떨어지게
    하기 위해서다(fail-safe)."""

    def __init__(self, *, reason: ImageBlockedReason) -> None:
        self.reason = reason
        super().__init__(f"Local image generation blocked by content policy guard: reason={reason}")


class LocalImageInputError(LLMClientError):
    """사용자가 프롬프트를 고치면 통과할 수 있는
    입력 오류(길이 초과 400 두 종류 → `too_long`, 문법 오류 422 → `syntax`)에만 올린다.
    `LocalImageBlockedError`와 같은 이유로 `LLMClientError`를 상속한다(fail-safe)."""

    def __init__(self, *, input_error: ImageInputError) -> None:
        self.input_error = input_error
        super().__init__(f"Local image generation rejected the input: input_error={input_error}")


@dataclass(frozen=True)
class ModelCapability:
    model_id: str
    styles: tuple[str, ...]
    aspect_ratios: tuple[str, ...]


@dataclass(frozen=True)
class LocalCapabilities:
    ready: bool
    models: tuple[ModelCapability, ...]

    def capability_for(self, model_id: str) -> ModelCapability | None:
        for model in self.models:
            if model.model_id == model_id:
                return model
        return None


UNAVAILABLE = LocalCapabilities(ready=False, models=())

# `build_image_client`(`llm/dependencies.py`)는
# `@lru_cache`가 없어 요청마다 새 `LocalImageClient` 인스턴스가 생긴다 — 세마포어를
# 인스턴스 필드에 두면 아무것도 직렬화하지 않는다. 모듈 최상단이어야 프로세스 전역이다.
# Python 3.11에서는 `asyncio.Semaphore()`의 loop 인자가 제거돼 최상단 생성이 안전하다
# (최초 사용 시점에 실행 중인 루프에 붙는다).
_generation_semaphore = Semaphore(1)

# `asyncio.Semaphore`는 대기자 수를 공개하지 않는다
# (`_waiters`는 private) — 대기열 상한(`generate_images`의 사전 차단)을 판정하려면 별도
# 카운터가 필요하다.
#
# 이전에는 검사(라우터)와 증가(`generate_image` 진입 시점)가 서로 다른
# 시점에 있었고, 그 사이에 `await create_job(...)`이라는 진짜 yield 지점이 있어 동시
# 도착 요청이 전부 증가 이전 값을 읽고 전부 통과했다(실제 재현: admitted=10 rejected=0
# limit=4). 원인은 "`+=1`이 원자적이지 않아서"가 아니다 — 단일 이벤트 루프에서 `+=`/`-=`
# 자체는 항상 원자적이다. 진짜 원인은 검사와 증가가 서로 다른 await 경계에 걸쳐 있어서
# 그 사이에 다른 태스크가 끼어들 수 있었다는 것이다. 그래서 카운터의 의미를
# "generate_image 호출 중"에서 "admit된 잡 수"로 옮기고, `try_admit()`이 검사+증가를
# **하나의 동기 함수**(내부에 await가 전혀 없다) 안에 묶는다 — 동기 코드는 실행 도중
# 이벤트 루프에 제어를 넘기지 않으므로 두 호출이 겹칠 수 없다. `generate_image`는 더
# 이상 이 카운터를 건드리지 않는다(세마포어만으로 GPU 보호는 그대로 유지된다).
_queue_depth = 0

# 유저별 큐는 1칸이다 — 전역 상한(`local_image_queue_limit`)만
# 있으면 한 사용자가 그 칸을 전부 차지해 나머지 전원이 429를 받는다. 정책 상수를 여기 두는
# 이유는 정책 상수를 게이트·큐 모듈에 두기 때문이다(전역 큐 상한 바로 옆 = 같은 기구의
# 정책값이 한자리에 모인다). 전역 상한은 GPU 직렬 처리량 보호라 그대로 남고, 이 상한은
# 그 자원의 **분배**를 맡는다.
USER_QUEUE_LIMIT = 1

# 유저별 깊이. `_queue_depth`를 이 dict로 **대체하지 않는다** — 대체하면 유저마다 1칸씩
# 무제한으로 열려 전역 상한이 사라진다. 두 카운터는 서로 다른 것을 지킨다.
_user_queue_depth: dict[uuid.UUID, int] = {}


def try_admit(user_id: uuid.UUID) -> bool:
    """상한 검사와 증가를 한 동기 블록에서 한다 — 그 사이에 await가 없어야 TOCTOU가
    없다. 라우터가 `create_job` 이전에 호출하고, False면 잡을 만들지 않고 429.

    검사가 둘(전역·유저별)이지만 dict 조회·증가는 전부 동기라 이 블록의 불변식
    (내부에 `await`가 0개)은 그대로다 — 하나라도 await가 끼면 동시 도착한 같은 유저의 두
    요청이 둘 다 증가 이전 값을 읽고 통과한다(`_queue_depth` 주석의, 실제로 재현된 그 결함)."""
    global _queue_depth
    if _queue_depth >= settings.local_image_queue_limit:
        return False
    if _user_queue_depth.get(user_id, 0) >= USER_QUEUE_LIMIT:
        return False
    _queue_depth += 1
    _user_queue_depth[user_id] = _user_queue_depth.get(user_id, 0) + 1
    return True


def release_admission(user_id: uuid.UUID) -> None:
    """감소. 0 아래로 내려가지 않게 한다 — 안 그러면 상한이 사실상 무제한이 된다.

    유저별 깊이는 0이 되면 **키 자체를 지운다**. 안 지우면 dict가 서비스 수명 동안 접속한
    유저 수만큼 자라고(프로세스 전역이라 비워 주는 것도 없다), 판정은 그대로라 증상이
    메모리 증가로만 나타난다."""
    global _queue_depth
    if _queue_depth > 0:
        _queue_depth -= 1
    depth = _user_queue_depth.get(user_id, 0)
    if depth > 1:
        _user_queue_depth[user_id] = depth - 1
    elif depth == 1:
        del _user_queue_depth[user_id]


_capabilities_cache: LocalCapabilities | None = None
_capabilities_cached_at: float = 0.0

# 콜드/만료 시점에 동시에 들어온 호출이 조회를 하나만 내게
# 하는 single-flight 락. 두 호출부(`/images/models`·`generate_images` 사전 차단)는 인증
# 의존성 SELECT로 요청 세션이 DB 커넥션을 쥔 채 이 함수를 기다리므로, 조회가 N개 나가면
# 커넥션 N개가 조회 시간만큼 묶인다. 모듈 최상단 생성이 안전한 이유는 `_generation_semaphore`와
# 같다(Python 3.11, 최초 사용 시점의 루프에 붙는다).
_capabilities_lock = Lock()

# 조회 전용 타임아웃. 생성용 `local_image_timeout_seconds`(90초)와
# 분리한 이유는 이 대기 동안 요청 세션이 DB 커넥션을 쥐고 있어서다 — 점유를 이 값 수준으로
# 묶는다(httpx 타임아웃은 연결·쓰기·읽기·풀 단계별이라 엄밀한 총 상한은 아니다).
# 집 PC의 `/capabilities`는 추론을 스레드로 위탁해 생성 중에도 즉시 답한다 — 집 PC와의 계약이
# 요구하는 것이고, 집 PC 쪽 준수 확인에서 0.018초로 실측됐다. 5초는
# Cloudflare Tunnel 왕복 여유를 넉넉히 둔 값이다.
_CAPABILITIES_TIMEOUT_SECONDS = 5


def reset_capabilities_cache() -> None:
    """테스트 헬퍼 — 모듈 수준 캐시를 콜드 상태로 되돌리고 single-flight 락도 새로 만든다."""
    global _capabilities_cache, _capabilities_cached_at, _capabilities_lock
    _capabilities_cache = None
    _capabilities_cached_at = 0.0
    _capabilities_lock = Lock()


def _fresh_cached_capabilities() -> LocalCapabilities | None:
    if (
        _capabilities_cache is not None
        and time.monotonic() - _capabilities_cached_at < settings.local_image_capabilities_ttl_seconds
    ):
        return _capabilities_cache
    return None


def _access_headers(access_client_id: str, access_client_secret: str) -> dict[str, str]:
    # 인증은 Cloudflare Access가 앞단에서 처리하고,
    # 앱은 이 두 헤더를 그대로 전달만 한다.
    return {
        "CF-Access-Client-Id": access_client_id,
        "CF-Access-Client-Secret": access_client_secret,
    }


async def get_capabilities() -> LocalCapabilities:
    """`GET {base}/capabilities`를 TTL 캐시로 감싼다. 콜드거나 만료됐을 때만 프로브한다 —
    `/images/models`와 `generate_images` 사전 차단 두 호출부가 이 함수 하나를 공유한다.
    연결 실패·타임아웃·비200·파싱 실패 등 어떤
    프로브 실패도 종류를 구분하지 않고 전부 UNAVAILABLE로 접는다.

    프로브는 `_CAPABILITIES_TIMEOUT_SECONDS`(5초, httpx 단계별 타임아웃)로 끊고, 동시
    호출은 락으로 하나만 나가게 한다. 기록 시각은 프로브가 **끝난 뒤**에 잡는다 — 시작
    시각을 기록하면 TTL보다 오래 걸린 느린 실패가 기록 즉시 만료돼 다음 요청이 또
    기다린다. 캐시 적중 경로는 락을 잡지 않는다."""
    global _capabilities_cache, _capabilities_cached_at

    cached = _fresh_cached_capabilities()
    if cached is not None:
        return cached

    async with _capabilities_lock:
        # 락을 기다리는 동안 앞선 호출이 캐시를 채웠을 수 있다.
        cached = _fresh_cached_capabilities()
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=_CAPABILITIES_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{settings.local_image_base_url}/capabilities",
                    headers=_access_headers(
                        settings.local_image_access_client_id, settings.local_image_access_client_secret
                    ),
                )
                response.raise_for_status()
                body = response.json()
            capabilities = LocalCapabilities(
                ready=bool(body["ready"]),
                models=tuple(
                    ModelCapability(
                        model_id=str(model["id"]),
                        styles=tuple(str(style) for style in model["styles"]),
                        aspect_ratios=tuple(model["aspect_ratios"]),
                    )
                    for model in body.get("models", [])
                ),
            )
        except Exception:
            capabilities = UNAVAILABLE

        _capabilities_cache = capabilities
        _capabilities_cached_at = time.monotonic()
        return capabilities


class LocalImageClient(ImageClient):
    def __init__(
        self,
        model_id: str,
        *,
        base_url: str | None = None,
        access_client_id: str | None = None,
        access_client_secret: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._base_url = base_url if base_url is not None else settings.local_image_base_url
        self._access_client_id = (
            access_client_id if access_client_id is not None else settings.local_image_access_client_id
        )
        self._access_client_secret = (
            access_client_secret
            if access_client_secret is not None
            else settings.local_image_access_client_secret
        )

    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        # 세마포어를 획득한 뒤에 httpx 요청을
        # 시작한다 — 순서가 뒤집히면 대기 시간이 요청 타임아웃 타이머에 실려
        # Cloudflare edge 한도 여유를 먹는다.
        async with _generation_semaphore:
            return await self._call_generate(prompt, style, aspect_ratio)

    async def _call_generate(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        # 서버는 프롬프트를 가공하지 않는다 — 프리셋
        # 태그·네거티브 프롬프트·샘플러 등은 전부 로컬 소유다.
        #
        # `model`은 공개 id(`self._model_id`)가
        # 아니라 **와이어 id**(설정)를 보낸다 — 공개 id는 FE/서버 계약용 불투명 라벨일
        # 뿐, 홈PC는 자신의 실제 체크포인트 id만 이해한다.
        #
        # `style`은 공개 id와 와이어 id가 같아
        # `style.value`를 그대로 싣는다 — 별도 와이어 설정이 없다.
        body = {
            "prompt": prompt,
            "model": settings.local_image_model_wire_id,
            "style": style.value,
            "aspect_ratio": aspect_ratio,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.local_image_timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/generate",
                    headers=_access_headers(self._access_client_id, self._access_client_secret),
                    json=body,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                error_body = exc.response.json()
            except ValueError:
                error_body = None
            detail = error_body.get("detail") if isinstance(error_body, dict) else None
            if exc.response.status_code == 422:
                # 본문은 `{"detail": "...", "reason": "prompt"|"image"|"syntax"}`
                # 평평한 구조다. `detail`은 해석하지 않는다 — 분기는 오직 `reason`이다.
                # 본문이 JSON이 아니거나 `reason`이 계약 밖 값이면 일반 실패로 접는다 —
                # 프록시가 끼어든 422를 정책 차단으로
                # 오독하면 안 된다.
                reason = error_body.get("reason") if isinstance(error_body, dict) else None
                if reason == "prompt" or reason == "image":
                    raise LocalImageBlockedError(reason=reason) from exc
                if reason == "syntax":
                    raise LocalImageInputError(input_error="syntax") from exc
            elif exc.response.status_code == 400:
                # 계약이 400에는 `reason` 키를
                # 안 줘서 여기만 `detail` 문자열로 분기한다 — 위 422의 "detail은
                # 해석하지 않는다" 규율과 다르다는 것을 명시해 둔다.
                # `unsupported style`은 우리 쪽 계약 위반(버그)이지 사용자가 고칠 입력이
                # 아니므로 화이트리스트에 넣지 않는다 — 밖은 전부 일반 실패로 떨어진다.
                if detail in ("invalid request", "prompt too long"):
                    raise LocalImageInputError(input_error="too_long") from exc
            # 로그가 이 메시지를 그대로 남긴다(`router.py`).
            # 상태 코드 + `detail`만 싣는다 — 계약이 본문 형태를 보장하지 않아 원문을
            # 그대로 실으면 프롬프트 에코 가능성을 배제할 수 없다.
            # `detail`이 리스트(FastAPI 기본
            # 검증 핸들러 모양)면 pydantic v2가 `include_input=True`가 기본값이라 각
            # 항목의 `input` 키에 검증 실패한 제출값 원문(예: 프롬프트)이 통째로 들어갈
            # 수 있다 — `repr(detail)`을 캡 없이 로그에 남기면 위에서 막으려던 "본문
            # 전체 노출"이 재발한다. 이전에 있던 `exc.response.text[:300]` 캡을 그대로
            # 되살린다.
            raise LLMClientError(
                f"Local image generation failed: {exc.response.status_code} detail={repr(detail)[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Local image generation call failed: {exc}") from exc

        data = response.content
        if not data:
            raise LLMClientError("Local image response was empty")
        mime = response.headers.get("content-type") or "application/octet-stream"
        return data, mime
