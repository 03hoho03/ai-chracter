import logging
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from api.core.config import settings
from api.core.longrun_trace import trace_enabled, write_usage
from api.llm.client import LLMClient, LLMClientError, LLMPolicyViolationError, LLMRateLimitError

T = TypeVar("T", bound=BaseModel)

# finish_reason values that mean Gemini's safetySettings blocked the output
# (as opposed to a normal STOP/MAX_TOKENS/OTHER end of generation).
_POLICY_FINISH_REASONS = frozenset(
    {genai_types.FinishReason.SAFETY, genai_types.FinishReason.PROHIBITED_CONTENT}
)

logger = logging.getLogger(__name__)


class GeminiLLMClient(LLMClient):
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key if api_key is not None else settings.gemini_api_key)
        self._model_name = model_name if model_name is not None else settings.gemini_model_name

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
    ) -> AsyncIterator[str]:
        # 출력 상한이 사고 토큰과 응답이 나눠 쓰는 예산이라는 점과 기본값의 근거는
        # core/config.py 의 gemini_max_output_tokens 주석 참고. stop_sequences 는 호출부가
        # 화자 라벨(prompt_set.user_label)에서 파생시켜 넘긴다(prompt-db-goal-prompt.md §4-5) —
        # 프롬프트가 `{user_label}: {입력}\n{assistant_label}:` 라는 대본 프레임으로 끝나서
        # 모델이 이어서 사용자의 다음 턴까지 지어낼 수 있는 구조이기 때문이다.
        config = genai_types.GenerateContentConfig(
            max_output_tokens=settings.gemini_max_output_tokens,
            stop_sequences=stop_sequences,
            system_instruction=system_instruction,
        )
        if settings.gemini_thinking_budget is not None:
            # None 이면 thinking_config 를 아예 넘기지 않아야 한다(모델 기본 사고 동작) —
            # 빈 ThinkingConfig 를 넘기는 것이 "안 넘김"과 같다는 보장이 없다.
            config.thinking_config = genai_types.ThinkingConfig(
                thinking_budget=settings.gemini_thinking_budget
            )
        if settings.gemini_seed is not None:
            # None 이면 seed 를 아예 넘기지 않아 지금과 같은 매 회차 난수 동작을 유지한다
            # (chat-techspec.md §3-1). generate_structured()에는 붙이지 않는다.
            config.seed = settings.gemini_seed
        # chat-longrun-goal-prompt.md LB-27: 토큰은 인터페이스가 돌려주지 않아 여기서만 잡힌다.
        # 스트림의 어느 청크에 usage 가 실리는지 모르므로 마지막 non-null 값을 쓴다.
        tracing = trace_enabled()
        started = time.monotonic()
        last_usage: Any = None
        model_version: str | None = None
        finish_reason: Any = None
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model_name,
                contents=prompt,
                config=config,
            )
            async for chunk in stream:
                if tracing:
                    last_usage = getattr(chunk, "usage_metadata", None) or last_usage
                    model_version = getattr(chunk, "model_version", None) or model_version
                    for traced in getattr(chunk, "candidates", None) or []:
                        finish_reason = getattr(traced, "finish_reason", None) or finish_reason
                prompt_feedback = getattr(chunk, "prompt_feedback", None)
                if prompt_feedback is not None and prompt_feedback.block_reason is not None:
                    raise LLMPolicyViolationError("Gemini blocked the prompt via safetySettings")
                for candidate in getattr(chunk, "candidates", None) or []:
                    if candidate.finish_reason in _POLICY_FINISH_REASONS:
                        raise LLMPolicyViolationError("Gemini blocked the output via safetySettings")
                    if candidate.finish_reason == genai_types.FinishReason.MAX_TOKENS:
                        # 상한에 걸리면 문장 중간에서 잘린 응답이 그대로 사용자에게 간다 —
                        # 조용히 넘기면 "AI가 말을 하다 말았다"로만 보이므로 로그에 남긴다.
                        # 이게 자주 찍히면 상한이 너무 낮은 것이다.
                        logger.warning(
                            "Gemini 응답이 max_output_tokens(%d)에서 잘렸다",
                            settings.gemini_max_output_tokens,
                        )
                if chunk.text:
                    yield chunk.text
            write_usage(
                call="generation",
                usage_metadata=last_usage,
                model_version=model_version,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                finish_reason=finish_reason,
            )
        except (genai_errors.APIError, httpx.HTTPError) as exc:
            # monitoring-techspec.md MT-6: 쿼터 소진(429)과 네트워크 타임아웃을 구분한다 —
            # `httpx.HTTPError`에는 `.code`가 없으므로 `isinstance` 가드가 먼저다(순서를
            # 바꾸면 네트워크 쪽에서 AttributeError가 원래 예외를 가린다).
            if isinstance(exc, genai_errors.APIError) and exc.code == 429:
                raise LLMRateLimitError(f"Gemini generate() call failed: {exc}") from exc
            raise LLMClientError(f"Gemini generate() call failed: {exc}") from exc

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
    ) -> T:
        contents: str | list[Any] = prompt
        if images:
            contents = [
                prompt,
                *(genai_types.Part.from_bytes(data=data, mime_type=mime_type) for data, mime_type in images),
            ]

        started = time.monotonic()
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )
        except (genai_errors.APIError, httpx.HTTPError) as exc:
            # `generate()`와 동일하게 두 계열을 함께 잡는다 — SDK의 네트워크/타임아웃 실패는
            # APIError가 아니라 내부적으로 쓰는 httpx 예외로 올라온다. 429 구분도 `generate()`와
            # 대칭을 유지한다(monitoring-techspec.md MT-6).
            if isinstance(exc, genai_errors.APIError) and exc.code == 429:
                raise LLMRateLimitError(f"Gemini generate_structured() call failed: {exc}") from exc
            raise LLMClientError(f"Gemini generate_structured() call failed: {exc}") from exc

        # chat-longrun-goal-prompt.md LB-27: call 은 스키마 이름(StatJudgmentResult 등). 파싱 실패로
        # 아래에서 raise 해도 토큰은 이미 썼으므로 그 전에 남긴다.
        write_usage(
            call=response_schema.__name__,
            usage_metadata=getattr(response, "usage_metadata", None),
            model_version=getattr(response, "model_version", None),
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        if not isinstance(response.parsed, response_schema):
            raise LLMClientError(
                f"Gemini structured response could not be parsed into {response_schema.__name__}"
            )
        return response.parsed
