"""고른 모델에 따라 생성 호출을 Gemini 와 Bedrock 구현으로 나눠 보내는 클라이언트. `get_llm_client` 가 이것을 돌려준다.

호출부는 지금처럼 `LLMCallContext` 만 넘긴다 — 그 안의 `model` 이 상위 모델이고 호출이 모델을 고를 수 있는 종류(채팅 턴 생성·
소설 장 생성·지난 턴 다시 생성)일 때만 Bedrock 으로 간다. 판정·요약·심사·문단 수정 같은 구조화 호출은 언제나 Gemini 다
(Bedrock 의 Claude 는 네이티브 구조화 출력을 받지 않는다). 레지스트리 밖 id 나 허용되지 않은 모델은 여기 닿기 전에 API 가
거부한다.
"""

import logging
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

from pydantic import BaseModel

from api.llm.call_policy import CALL_POLICIES
from api.llm.chat_models import CHAT_MODELS_BY_ID
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

# 사용자가 고른 모델을 따르는 호출(호출 정책 표의 `model_selectable`). 재생성·수정은 같은 call_site 로 온다. 지난 턴을
# 다시 생성하는 측정 호출도 그 턴의 모델(Claude 포함)로 다시 써야 비교가 맞아 함께 둔다.
MODEL_SELECTABLE_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    cs for cs, p in CALL_POLICIES.items() if p.model_selectable
)


def _build_bedrock_client() -> LLMClient:
    # 지연 import 로 아끼는 것은 거의 없다 — `anthropic` 은 Sentry 통합(`core/sentry.py` 의 최상단 import, DSN 이 있으면
    # `sentry_sdk.init()` 의 auto-enabling 목록)이 기동 때 이미 끌어오고(개발 맥 실측 약 0.5초, 차가운 캐시 1.0초),
    # `botocore` 는 S3 클라이언트(`core/s3.py`)가 끌어온다. 그 뒤 `api.llm.bedrock` 자체의 import 는 1ms 안팎이다. 이
    # 비용을 기동에서 빼려면 Sentry 를 `auto_enabling_integrations=False` 와 명시 통합 목록으로 초기화해야 한다.
    from api.llm.bedrock import BedrockLLMClient

    return BedrockLLMClient()


class RoutingLLMClient(LLMClient):
    def __init__(self, gemini: LLMClient, *, bedrock_factory: Callable[[], LLMClient] = _build_bedrock_client) -> None:
        self._gemini = gemini
        self._bedrock_factory = bedrock_factory
        self._bedrock: LLMClient | None = None

    def _for_generation(self, usage: LLMCallContext) -> LLMClient:
        if CHAT_MODELS_BY_ID[usage.model].provider == "gemini":
            return self._gemini
        if usage.call_site not in MODEL_SELECTABLE_CALL_SITES:
            # 호출부가 방의 모델을 판정 같은 호출에까지 실어 보낸 실수다. 사용자가 고른 적 없는 호출에 비싼 모델 원가가
            # 붙지 않게 Gemini 로 돌리고, 실수가 드러나게 남긴다.
            logger.warning(
                "모델을 고를 수 없는 호출에 상위 모델이 실려 와 Gemini 로 보낸다 call_site=%s model=%s",
                usage.call_site,
                usage.model,
            )
            return self._gemini
        if self._bedrock is None:
            self._bedrock = self._bedrock_factory()
        return self._bedrock

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
        return self._for_generation(usage).generate(prompt, system_instruction, stop_sequences, usage=usage)

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        return await self._gemini.generate_structured(prompt, response_schema, images, usage=usage)

    async def generate_structured_with_instruction(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str,
        usage: LLMCallContext,
    ) -> T:
        return await self._gemini.generate_structured_with_instruction(
            prompt, response_schema, system_instruction=system_instruction, usage=usage
        )
