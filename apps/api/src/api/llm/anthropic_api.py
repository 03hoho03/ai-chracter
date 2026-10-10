"""Anthropic API 로 Claude 에 바로 보내는 LLMClient. 배정(`LLM_CALL_SITE_BACKENDS`)이 상위 모델의 호출을 이 구현으로 옮길
때만 닿는다 — 배정이 없으면 상위 모델은 Bedrock 으로 간다(`llm/backends.py` 의 기본 순서). 받는 호출과 실패 규칙은 Bedrock
구현과 같다: 채팅 턴 생성(지난 턴 다시 생성 포함)과 소설 장 생성(`generate`)만 받고, 구조화 호출은 등록부가 받지 못하는
구현으로 적어 기동 검증이 그런 배정을 거부한다. 예외에는 `provider = "anthropic"` 을 적는다.

이 경로의 모델(Opus 5.5 등)은 사고를 끌 수 없다 — `thinking` 을 끄거나 예산으로 보내면 요청이 거부되고, 생략하면 모델이
알아서 사고한다. 그래서 요청에 `thinking` 을 싣지 않고 깊이만 `output_config.effort` 로 고른다. 사고 토큰은 출력 상한
안에 들고 출력 단가로 과금된다. 강제 도구 선택과 assistant 미리 채우기도 이 모델들이 거부하는데, 대본이 user 메시지
하나라 둘 다 쓰지 않는다.

요청에 계정을 가리키는 값(`metadata.user_id` 등)을 싣지 않는다. 다른 모델로 조용히 넘기는 서버 쪽 대체 경로도 쓰지 않는다
(실패하면 오류와 환불이다 — 사용자가 고른 것과 다른 경로가 돌지 않게).
"""

import logging
from collections.abc import AsyncIterator
from typing import TypeVar

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from api.core.config import ClaudeEffort, settings
from api.llm.call_policy import CALL_POLICIES
from api.llm.chat_models import backend_model_id
from api.llm.claude_messages import (
    COMMON_TRANSPORT_ERRORS,
    ClaudeStreamTally,
    ClaudeUsage,
    claude_error,
    raise_if_unusable,
    user_content,
)
from api.llm.client import (
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    LLMClientError,
    LLMEmptyResponseError,
    LLMRateLimitError,
    collect_usage,
)
from api.llm.usage_store import record_usage

T = TypeVar("T", bound=BaseModel)
E = TypeVar("E", bound=LLMClientError)

logger = logging.getLogger(__name__)

# SDK 는 호스트를 인자로 받지 않으면 env `ANTHROPIC_BASE_URL` 을 읽는다. 키를 명시로 넘기는 것과 같은 이유로 호스트도
# 명시한다 — 프로세스 env 의 값이 이 구현의 요청을 다른 곳으로 보내지 않게.
_BASE_URL = "https://api.anthropic.com"


def _anthropic_error(cls: type[E], message: str) -> E:
    return claude_error(cls, message, "anthropic")


def _timeout_seconds(call_site: LLMCallSite) -> float:
    """요청 하나의 타임아웃(초). Bedrock 구현과 같이 스트리밍에서는 "다음 청크까지"의 상한이고, 장 상한과 채팅 상한 중
    무엇을 쓸지는 호출 정책 표의 `claude_limits` 가 정한다."""
    if CALL_POLICIES[call_site].claude_limits == "chapter":
        return settings.anthropic_chapter_timeout_ms / 1000
    return settings.anthropic_chat_timeout_ms / 1000


def _max_tokens(call_site: LLMCallSite) -> int:
    if CALL_POLICIES[call_site].claude_limits == "chapter":
        return settings.anthropic_chapter_max_tokens
    return settings.anthropic_chat_max_tokens


def _effort(call_site: LLMCallSite) -> ClaudeEffort:
    """사고 깊이. 모델의 기본값에 맡기지 않고 늘 보낸다 — 기본값이 모델마다 달라 모델 id 만 바꿔도 길이·원가가 움직인다."""
    if CALL_POLICIES[call_site].claude_limits == "chapter":
        return settings.anthropic_chapter_effort
    return settings.anthropic_chat_effort


def _is_throttling(exc: BaseException) -> bool:
    """쿼터 소진인가. 요청 단계에서는 HTTP 429(`RateLimitError`)로 오지만, 스트림 도중에는 응답 상태가 이미 200 이라 SDK 가
    SSE `error` 이벤트를 상태 코드 갈래가 아닌 일반 `APIStatusError` 로 올린다 — 그때는 오류 본문의 종류로만 드러난다.
    과부하(529·`overloaded_error`)는 우리 쿼터가 아니라 공급자 쪽 혼잡이라 여기 넣지 않는다."""
    if isinstance(exc, anthropic.RateLimitError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.type == "rate_limit_error"


def _log_usage(usage: LLMCallContext, model: str, usage_metadata: ClaudeUsage | None) -> None:
    """호출 한 건의 토큰 사용량을 고정 토큰 `anthropic_usage` 로 한 줄 남긴다. 형식과 규칙은 `bedrock_usage` 와 같고(텍스트는
    받지도 않는다, 메타데이터가 없으면 `usage=missing`, 절대 raise 하지 않는다), 이 경로는 사고하므로 사고 토큰 칸을 더한다.
    이름을 따로 두는 이유는 기존 `gemini_usage`·`bedrock_usage` grep·분포를 끊지 않으려는 것이다."""
    try:
        logger.warning(
            "anthropic_usage call_site=%s model=%s prompt_tokens=%s cached_content_tokens=%s cache_write_tokens=%s "
            "candidates_tokens=%s thoughts_tokens=%s total_tokens=%s user_id=%s room_id=%s%s",
            usage.call_site,
            model,
            getattr(usage_metadata, "prompt_token_count", None),
            getattr(usage_metadata, "cached_content_token_count", None),
            getattr(usage_metadata, "cache_write_token_count", None),
            getattr(usage_metadata, "candidates_token_count", None),
            getattr(usage_metadata, "thoughts_token_count", None),
            getattr(usage_metadata, "total_token_count", None),
            usage.user_id,
            usage.room_id,
            " usage=missing" if usage_metadata is None else "",
        )
    except Exception:
        pass


class AnthropicLLMClient(LLMClient):
    def __init__(self) -> None:
        # SDK 클라이언트는 첫 호출 때 만든다 — 키가 비었을 때의 실패가 생성자(의존성 해석)가 아니라 그 호출의
        # `LLMClientError` 로 나야 채팅이 환불 경로를 탄다.
        self._client: AsyncAnthropic | None = None

    def _sdk(self) -> AsyncAnthropic:
        if self._client is not None:
            return self._client
        key = settings.anthropic_direct_api_key.strip()
        if not key:
            # 🔴 키를 넘기지 않으면 SDK 가 env `ANTHROPIC_API_KEY`·`ANTHROPIC_AUTH_TOKEN`·로그인 프로필에서 다른 자격을 찾고,
            # 빈 문자열을 넘기면 그것도 명시 자격으로 쳐 env 를 보지 않은 채 인증 실패를 받는다. 만들기 전에 막는다.
            raise _anthropic_error(LLMClientError, "Anthropic API 키가 비어 있어 호출하지 않는다")
        # 재시도는 하지 않는다(SDK 기본은 2회) — 재시도는 실패한 턴의 지연과 원가를 곱으로 늘린다.
        self._client = AsyncAnthropic(
            api_key=key,
            base_url=_BASE_URL,
            max_retries=0,
            timeout=settings.anthropic_chat_timeout_ms / 1000,
        )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        # 모델 id 는 이 구현의 표에서 바로 읽는다(Bedrock 구현과 같은 이유 — 라우터가 이미 구현을 정했다).
        model = backend_model_id("anthropic", usage.model)
        max_tokens = _max_tokens(usage.call_site)
        tally = ClaudeStreamTally("anthropic", "Anthropic")
        try:
            stream = await self._sdk().messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": user_content(prompt, usage.call_site, logger)}],
                system=system_instruction if system_instruction is not None else anthropic.omit,
                stop_sequences=stop_sequences if stop_sequences else anthropic.omit,
                output_config={"effort": _effort(usage.call_site)},
                stream=True,
                timeout=_timeout_seconds(usage.call_site),
            )
            async for event in stream:
                was_truncated = tally.truncated
                text = tally.feed(event)
                if text:
                    yield text
                if tally.truncated and not was_truncated:
                    # 사고 토큰도 이 상한 안에 든다. 자주 찍히면 상한이 낮거나 effort 가 높은 것이다.
                    logger.warning("Anthropic 응답이 max_tokens(%d)에서 잘렸다", max_tokens)
        except COMMON_TRANSPORT_ERRORS as exc:
            if _is_throttling(exc):
                raise _anthropic_error(LLMRateLimitError, f"Anthropic generate() call failed: {exc}") from exc
            raise _anthropic_error(LLMClientError, f"Anthropic generate() call failed: {exc}") from exc
        # 정상 종료한 스트림만 여기 닿는다 — 소비자가 중간에 끊으면(aclose) `yield` 자리에서 빠지고 기록하지 않는다.
        usage_metadata = tally.usage()
        _log_usage(usage, model, usage_metadata)
        await record_usage(usage.call_site, model, usage_metadata)
        collect_usage(usage, model, usage_metadata)
        if tally.truncated and not tally.has_text:
            # 사고가 먼저 나오므로 사고 도중 상한에 닿으면 본문이 하나도 없다. 채팅이라도 빈 턴을 저장·과금하지 않고 실패로
            # 올려 환불 경로를 태운다(원가는 이미 나가 위에서 기록했다). 본문이 조금이라도 있으면 아래 규칙대로다.
            raise _anthropic_error(
                LLMEmptyResponseError, f"Anthropic output hit max_tokens({max_tokens}) before any text"
            )
        raise_if_unusable(tally, usage.call_site, max_tokens)

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        raise _anthropic_error(LLMClientError, "Anthropic client does not serve structured calls — they go to Gemini")
