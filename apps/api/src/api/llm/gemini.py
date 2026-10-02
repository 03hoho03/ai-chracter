import logging
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from api.core.config import settings
from api.llm.client import (
    JUDGMENT_CALL_SITES,
    PUBLISH_FILTER_CALL_SITES,
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
)
from api.llm.usage_store import record_usage

T = TypeVar("T", bound=BaseModel)

# finish_reason values that mean Gemini's safetySettings blocked the output
# (as opposed to a normal STOP/MAX_TOKENS/OTHER end of generation).
_POLICY_FINISH_REASONS = frozenset(
    {genai_types.FinishReason.SAFETY, genai_types.FinishReason.PROHIBITED_CONTENT}
)

logger = logging.getLogger(__name__)


def _log_usage(usage: LLMCallContext, model: str, usage_metadata: object | None) -> None:
    """호출 한 건의 토큰 사용량을 고정 토큰 `gemini_usage`로
    한 줄 남긴다(`info`는 프로덕션에서 사라지므로 `warning`). 🔴 프롬프트·응답 텍스트는 인자로
    받지도 않는다 — 개수와 id만 찍는다. 메타데이터가 없으면 토큰을 None으로 두고 `usage=missing`을
    붙인다(없다는 사실이 로그에 보여야 한다). `cached_content_tokens`는 `prompt_tokens` 중 암시
    캐시가 적중한 몫이다 — 턴 원가를 입력 토큰만으로 추정하면 캐시 할인이 빠지므로 함께 찍는다.
    적중이 없으면 SDK가 None을 준다.

    **절대 raise하지 않는다** — `generate()`는 SSE 제너레이터 안에서 소비되고, 본문을 뚫는 예외는
    요청 스코프 DB 세션을 강제 종료시켜 풀을 오염시킨다(apps/api/CLAUDE.md §SSE). 필드 추출과
    logger 호출을 통째로 감싸 실패하면 그 한 줄만 버린다."""
    try:
        logger.warning(
            "gemini_usage call_site=%s model=%s prompt_tokens=%s cached_content_tokens=%s candidates_tokens=%s "
            "thoughts_tokens=%s total_tokens=%s user_id=%s room_id=%s%s",
            usage.call_site,
            model,
            getattr(usage_metadata, "prompt_token_count", None),
            getattr(usage_metadata, "cached_content_token_count", None),
            getattr(usage_metadata, "candidates_token_count", None),
            getattr(usage_metadata, "thoughts_token_count", None),
            getattr(usage_metadata, "total_token_count", None),
            usage.user_id,
            usage.room_id,
            " usage=missing" if usage_metadata is None else "",
        )
    except Exception:
        pass


class GeminiLLMClient(LLMClient):
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key if api_key is not None else settings.gemini_api_key)
        self._model_name = model_name if model_name is not None else settings.gemini_model_name

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        # 출력 상한이 사고 토큰과 응답이 나눠 쓰는 예산이라는 점과 기본값의 근거는
        # core/config.py 의 gemini_max_output_tokens 주석 참고. stop_sequences 는 호출부가
        # 화자 라벨(prompt_set.user_label)에서 파생시켜 넘긴다 —
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
            # generate_structured()에는 붙이지 않는다.
            config.seed = settings.gemini_seed
        # 메타데이터가 마지막 청크에만 온다고 가정하지 않는다 — 마지막으로 본 비-None 값을
        # 쓴다. `getattr` 기본값은 이 속성이 없는 테스트용 청크(SimpleNamespace)를 위한 것이다.
        usage_metadata: object | None = None
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model_name,
                contents=prompt,
                config=config,
            )
            async for chunk in stream:
                chunk_usage = getattr(chunk, "usage_metadata", None)
                if chunk_usage is not None:
                    usage_metadata = chunk_usage
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
        except (genai_errors.APIError, httpx.HTTPError) as exc:
            # 쿼터 소진(429)과 네트워크 타임아웃을 구분한다 —
            # `httpx.HTTPError`에는 `.code`가 없으므로 `isinstance` 가드가 먼저다(순서를
            # 바꾸면 네트워크 쪽에서 AttributeError가 원래 예외를 가린다).
            if isinstance(exc, genai_errors.APIError) and exc.code == 429:
                raise LLMRateLimitError(f"Gemini generate() call failed: {exc}") from exc
            raise LLMClientError(f"Gemini generate() call failed: {exc}") from exc
        # 정상 종료한 스트림만 여기 닿는다 — 정책 차단·SDK 예외는 위에서 올라가고, 소비자가 중간에
        # 끊으면(aclose) `yield` 자리에서 GeneratorExit으로 빠진다. 그 경우는 기록하지 않는다.
        _log_usage(usage, self._model_name, usage_metadata)
        await record_usage(usage.call_site, self._model_name, usage_metadata)

    def _structured_model_and_thinking(self, call_site: LLMCallSite) -> tuple[str, int | None]:
        """판정·발행 심사 call_site 집합(`llm/client.py`)이면 그 스위치의 모델·사고 예산을, 아니면
        기본 모델에 사고 설정 없음을 돌려준다. 설정은 호출마다 읽는다 — 클라이언트가 프로세스당
        하나이고 설정은 실행 중에 바뀌지 않아 운영에서는 기동 때 읽는 것과 같다. 모델명을 `or` 로
        고르는 건 env 에 키만 남아 빈 문자열이 들어와도 기본 모델로 돌게 하려는 것이다(빈 모델명은
        어떤 모델도 가리키지 않는다)."""
        if call_site in JUDGMENT_CALL_SITES:
            return (
                settings.gemini_judgment_model_name or self._model_name,
                settings.gemini_judgment_thinking_budget,
            )
        if call_site in PUBLISH_FILTER_CALL_SITES:
            return (
                settings.gemini_publish_filter_model_name or self._model_name,
                settings.gemini_publish_filter_thinking_budget,
            )
        return self._model_name, None

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        contents: str | list[Any] = prompt
        if images:
            contents = [
                prompt,
                *(genai_types.Part.from_bytes(data=data, mime_type=mime_type) for data, mime_type in images),
            ]

        model, thinking_budget = self._structured_model_and_thinking(usage.call_site)
        config = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        if thinking_budget is not None:
            # `generate()` 와 같은 이유로 None 이면 thinking_config 를 아예 넘기지 않는다.
            config.thinking_config = genai_types.ThinkingConfig(thinking_budget=thinking_budget)
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except (genai_errors.APIError, httpx.HTTPError) as exc:
            # `generate()`와 동일하게 두 계열을 함께 잡는다 — SDK의 네트워크/타임아웃 실패는
            # APIError가 아니라 내부적으로 쓰는 httpx 예외로 올라온다. 429 구분도 `generate()`와
            # 대칭을 유지한다.
            if isinstance(exc, genai_errors.APIError) and exc.code == 429:
                raise LLMRateLimitError(f"Gemini generate_structured() call failed: {exc}") from exc
            raise LLMClientError(f"Gemini generate_structured() call failed: {exc}") from exc

        # 파싱 검사 **앞**이다 — 응답을 받은 시점에 토큰은 이미 과금됐다.
        usage_metadata = getattr(response, "usage_metadata", None)
        _log_usage(usage, model, usage_metadata)
        await record_usage(usage.call_site, model, usage_metadata)
        if not isinstance(response.parsed, response_schema):
            raise LLMClientError(
                f"Gemini structured response could not be parsed into {response_schema.__name__}"
            )
        return response.parsed
