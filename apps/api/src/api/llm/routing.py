"""호출마다 공급자 구현을 골라 보내는 클라이언트. `get_llm_client` 가 이것을 돌려준다.

호출부는 지금처럼 `LLMCallContext` 만 넘긴다. 구현은 `llm/backends.py` 의 `pick_backend` 가 호출 위치·모델·배정(env
`LLM_CALL_SITE_BACKENDS`, 정책 표의 `backend`)으로 정한다. 배정이 없으면 생성 호출은 `model` 이 상위 모델이고 호출이 모델을
고를 수 있는 종류(채팅 턴 생성·소설 장 생성·지난 턴 다시 생성)일 때만 Bedrock 으로 가고, 나머지는 Gemini 다. 구조화
호출은 방의 모델을 보지 않는다 — 판정·요약은 그 호출의 판정·요약 모델 설정(기본 Gemini)으로, 심사·문단 수정 같은 나머지는
기본 모델로 구현을 고른다. 레지스트리 밖 id 나 허용되지 않은 모델은 여기 닿기 전에 API 가 거부한다.
"""

import logging
from collections.abc import AsyncIterator, Callable, Mapping
from typing import TypeVar

from pydantic import BaseModel

from api.core.config import settings
from api.llm.backends import pick_backend
from api.llm.call_policy import BackendId
from api.llm.chat_models import PromptSetModelId, backend_model_id, configured_call_site_model
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


def resolve_backend(call_site: LLMCallSite, model: PromptSetModelId) -> tuple[BackendId, str]:
    """그 호출이 가는 구현과 그 구현이 보내는 실제 모델 id. 배정은 호출마다 설정에서 읽는다(호출 정책 표의 설정 값과 같은
    규칙 — import 때 붙잡으면 테스트가 바꾼 배정이 실리지 않는다). 프롬프트 덤프·리플레이의 비교·원가가 이것을 부른다 —
    라우터와 같은 규칙이라야 덤프에 적힌 id 가 실제로 보낸 id 다. Gemini 의 판정·심사·소설화 호출은 클라이언트가 모델을
    따로 고르므로, 그 호출들의 실제 id 는 이 값과 다를 수 있다."""
    resolved_model, backend = pick_backend(
        call_site, model, settings.llm_call_site_backends, call_model=configured_call_site_model(call_site)
    )
    return backend, backend_model_id(backend, resolved_model)


def _build_bedrock_client() -> LLMClient:
    # 지연 import 로 아끼는 것은 거의 없다 — `anthropic` 은 Sentry 통합(`core/sentry.py` 의 최상단 import, DSN 이 있으면
    # `sentry_sdk.init()` 의 auto-enabling 목록)이 기동 때 이미 끌어오고(개발 맥 실측 약 0.5초, 차가운 캐시 1.0초),
    # `botocore` 는 S3 클라이언트(`core/s3.py`)가 끌어온다. 그 뒤 `api.llm.bedrock` 자체의 import 는 1ms 안팎이다. 이
    # 비용을 기동에서 빼려면 Sentry 를 `auto_enabling_integrations=False` 와 명시 통합 목록으로 초기화해야 한다.
    from api.llm.bedrock import BedrockLLMClient

    return BedrockLLMClient()


def _build_anthropic_client() -> LLMClient:
    # Bedrock 과 같은 이유로 지연 import 로 아끼는 것은 거의 없다 — 배정이 없으면 불리지 않는다는 것만 드러낸다.
    from api.llm.anthropic_api import AnthropicLLMClient

    return AnthropicLLMClient()


# Gemini 를 뺀 구현의 팩토리. Gemini 는 `get_llm_client` 가 바로 만들어 넘긴다 — 키가 없을 때의 `ValueError` 가 의존성
# 해석 시점에 나야 한다. 나머지는 처음 필요할 때 한 번 만든다.
_FACTORIES: Mapping[BackendId, Callable[[], LLMClient]] = {
    "bedrock": _build_bedrock_client,
    "anthropic": _build_anthropic_client,
}


class RoutingLLMClient(LLMClient):
    def __init__(
        self, gemini: LLMClient, *, factories: Mapping[BackendId, Callable[[], LLMClient]] | None = None
    ) -> None:
        self._factories = _FACTORIES if factories is None else factories
        self._clients: dict[BackendId, LLMClient] = {"gemini": gemini}

    def _client_for(self, call_site: LLMCallSite, model: PromptSetModelId) -> LLMClient:
        resolved_model, backend = pick_backend(
            call_site, model, settings.llm_call_site_backends, call_model=configured_call_site_model(call_site)
        )
        if resolved_model != model:
            # 호출부가 방의 모델을 판정 같은 호출에까지 실어 보낸 실수다. 사용자가 고른 적 없는 호출에 비싼 모델 원가가
            # 붙지 않게 그 호출의 모델(판정·요약은 그 설정의 모델, 나머지는 기본 모델)로 돌리고, 실수가 드러나게 남긴다.
            logger.warning(
                "모델을 고를 수 없는 호출에 다른 모델이 실려 와 그 호출의 모델로 보낸다 call_site=%s model=%s sent=%s",
                call_site,
                model,
                resolved_model,
            )
        client = self._clients.get(backend)
        if client is None:
            client = self._factories[backend]()
            self._clients[backend] = client
        return client

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        # 제너레이터로 감싸지 않고 고른 구현의 스트림을 그대로 돌려준다 — 소비자가 중간에 끊을 때(aclose) 그 신호가 구현의
        # 스트림에 바로 닿아야 사용량을 기록하지 않는 규칙과 HTTP 스트림 정리가 지금과 같게 돈다.
        client = self._client_for(usage.call_site, usage.model)
        return client.generate(prompt, system_instruction, stop_sequences, usage=usage)

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        client = self._client_for(usage.call_site, configured_call_site_model(usage.call_site))
        return await client.generate_structured(prompt, response_schema, images, usage=usage)

    async def generate_structured_with_instruction(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str,
        usage: LLMCallContext,
    ) -> T:
        client = self._client_for(usage.call_site, configured_call_site_model(usage.call_site))
        return await client.generate_structured_with_instruction(
            prompt, response_schema, system_instruction=system_instruction, usage=usage
        )
