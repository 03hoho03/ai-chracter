"""AWS Bedrock 의 Claude 를 부르는 LLMClient. 채팅 턴 생성(지난 턴 다시 생성 포함)과 소설 장 생성(`generate`), 그리고
판정·요약 모델이 Claude 일 때의 판정·요약(`generate_structured`)을 받는다. 그림을 싣는 구조화(발행 심사)와 지시문을 따로
싣는 구조화(소설화)는 받지 않는다 — 등록부(`llm/backends.py`)가 그렇게 적어 기동 검증이 그런 배정을 거부한다.

실패 규칙은 `llm/gemini.py` 와 같다. SDK·네트워크 예외는 전부 `LLMClientError` 계열로 바꾼다(그대로 새면 SSE 제너레이터를
뚫어 요청 스코프 DB 세션이 강제 종료된다). 사용량은 정상 종료한 스트림만 기록하고, 소설 장의 잘림·빈 본문은 기록한 **뒤**
구분된 실패로 올린다. 구조화 호출은 응답을 받으면 기록하고 그 뒤에 읽는다(거절·잘림·파싱 실패도 과금된 응답이다). 여기서 올리는 예외에는 `provider = "bedrock"` 을 적어 Bugsink 태그가 Gemini 와 갈리게 한다.

요청에 계정을 가리키는 값(`metadata.user_id` 등)을 싣지 않는다 — 개인정보 처리방침의 국외 이전 항목이 이 전제로 쓰인다.

Anthropic API 직접 구현과 같은 Messages API 조각(캐시 블록·스트림 집계·사용량 모양)은 `llm/claude_messages.py` 에 있다.
"""

import logging
from collections.abc import AsyncIterator
from typing import TypeVar

import anthropic
import botocore.eventstream
import botocore.exceptions
from anthropic import AsyncAnthropicBedrock
from pydantic import BaseModel

from api.core.config import settings
from api.llm.call_policy import CALL_POLICIES
from api.llm.chat_models import backend_model_id, configured_call_site_model
from api.llm.claude_messages import (
    COMMON_TRANSPORT_ERRORS,
    ClaudeStreamTally,
    ClaudeUsage,
    claude_error,
    message_usage,
    parse_structured,
    raise_if_unusable,
    structured_output_config,
    user_content,
)
from api.llm.client import (
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    LLMClientError,
    LLMRateLimitError,
    collect_usage,
    request_timeout_ms,
)
from api.llm.usage_store import record_usage

T = TypeVar("T", bound=BaseModel)
E = TypeVar("E", bound=LLMClientError)

logger = logging.getLogger(__name__)


# botocore 예외는 SDK 가 감싸지 않고 그대로 올린다 — 요청 서명 단계(`BotoCoreError` 계열, 프로세스 env 의 `AWS_PROFILE` 이
# 없는 프로필을 가리키면 `ProfileNotFound`)와 응답 event-stream 디코딩 단계(`ParserError` 계열, 체크섬·길이가 깨진 프레임)다.
# 나머지 전송 예외는 공용 목록의 설명을 본다.
_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    *COMMON_TRANSPORT_ERRORS,
    botocore.exceptions.BotoCoreError,
    botocore.eventstream.ParserError,
)


def _bedrock_error(cls: type[E], message: str) -> E:
    return claude_error(cls, message, "bedrock")


def _timeout_seconds(call_site: LLMCallSite) -> float:
    """요청 하나의 타임아웃(초). SDK 의 httpx 경로에서 이 값은 연결·읽기 단계마다의 상한이라, 스트리밍에서는 호출 전체가
    아니라 "다음 청크까지"의 상한이다(Gemini 생성과 같은 성질). 꾸준히 흘러나오는 긴 장의 전체 시간은 소설화 작업 상한이
    끊는다. 장 상한과 채팅 상한 중 무엇을 쓸지는 호출 정책 표의 `claude_limits` 가 정한다."""
    if CALL_POLICIES[call_site].claude_limits == "chapter":
        return settings.bedrock_chapter_timeout_ms / 1000
    return settings.bedrock_chat_timeout_ms / 1000


def _max_tokens(call_site: LLMCallSite) -> int:
    if CALL_POLICIES[call_site].claude_limits == "chapter":
        return settings.bedrock_chapter_max_tokens
    return settings.bedrock_chat_max_tokens


def _is_throttling(exc: BaseException) -> bool:
    """쿼터 소진(스로틀)인가. 요청 단계의 스로틀은 HTTP 429 로 오지만, 스트림 도중의 스로틀은 응답 상태가 이미 200 이라
    상태 코드가 아니라 오류 본문의 종류(`throttlingException`)로만 드러난다."""
    if isinstance(exc, anthropic.RateLimitError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and "throttl" in str(exc.body).lower()


def _log_usage(usage: LLMCallContext, model: str, usage_metadata: ClaudeUsage | None) -> None:
    """호출 한 건의 토큰 사용량을 고정 토큰 `bedrock_usage` 로 한 줄 남긴다. 형식과 규칙은 Gemini 의 `gemini_usage` 와 같다
    (텍스트는 받지도 않는다, 메타데이터가 없으면 `usage=missing`, 절대 raise 하지 않는다). 이름을 따로 두는 이유는 기존
    `gemini_usage` grep·분포를 끊지 않으려는 것이다."""
    try:
        logger.warning(
            "bedrock_usage call_site=%s model=%s prompt_tokens=%s cached_content_tokens=%s cache_write_tokens=%s "
            "candidates_tokens=%s total_tokens=%s user_id=%s room_id=%s%s",
            usage.call_site,
            model,
            getattr(usage_metadata, "prompt_token_count", None),
            getattr(usage_metadata, "cached_content_token_count", None),
            getattr(usage_metadata, "cache_write_token_count", None),
            getattr(usage_metadata, "candidates_token_count", None),
            getattr(usage_metadata, "total_token_count", None),
            usage.user_id,
            usage.room_id,
            " usage=missing" if usage_metadata is None else "",
        )
    except Exception:
        pass


class BedrockLLMClient(LLMClient):
    def __init__(self) -> None:
        # SDK 클라이언트는 첫 호출 때 만든다 — 자격이 비었을 때의 실패가 생성자(의존성 해석)가 아니라 그 호출의
        # `LLMClientError` 로 나야 채팅이 환불 경로를 탄다.
        self._client: AsyncAnthropicBedrock | None = None

    def _sdk(self) -> AsyncAnthropicBedrock:
        if self._client is not None:
            return self._client
        key = settings.bedrock_access_key_id.strip()
        secret = settings.bedrock_secret_access_key.strip()
        region = settings.bedrock_region.strip()
        if not (key and secret and region):
            # 🔴 빈 값으로 SDK 를 만들면 boto3 기본 자격 체인이 프로세스 env 의 R2 키(`AWS_ACCESS_KEY_ID`)로 서명하고, 리전이
            # 없으면 R2 리전(`AWS_REGION=auto`)으로 엔드포인트를 만든다. 만들기 전에 막는다.
            raise _bedrock_error(LLMClientError, "Bedrock 자격(키·비밀 키·리전)이 비어 있어 호출하지 않는다")
        try:
            # 재시도는 하지 않는다(SDK 기본은 2회) — Gemini 와 같은 규칙이고, 재시도는 실패한 턴의 지연과 원가를 곱으로 늘린다.
            self._client = AsyncAnthropicBedrock(
                aws_access_key=key,
                aws_secret_key=secret,
                aws_region=region,
                max_retries=0,
                timeout=settings.bedrock_chat_timeout_ms / 1000,
            )
        except ValueError as exc:
            # 프로세스 env 에 `AWS_BEARER_TOKEN_BEDROCK` 가 있으면 SDK 가 명시 키와 함께 받기를 거부한다.
            raise _bedrock_error(LLMClientError, f"Bedrock client could not be built: {exc}") from exc
        return self._client

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        # 정지 시퀀스는 Gemini 와 같이 호출부가 대본의 화자 라벨에서 만들어 넘긴다. 대본은 user 메시지 하나로 싣는다
        # (채팅 턴은 그 안을 캐시 블록으로 나눈다, `user_content`).
        # 사고는 끈다 — 채팅은 첫 글자 지연이 체감이고, 두 모델 모두 끌 수 있다. 🔴 사고를 끌 수 없는 모델(Opus 5.5 등)의 id 로
        # 바꾸면 이 값 때문에 매 호출이 거부된다 — 그런 모델은 Anthropic API 직접 구현(`llm/anthropic_api.py`)으로 보낸다.
        # 모델 id 는 이 구현의 표에서 바로 읽는다. 어느 구현으로 갈지는 라우터가 이미 정했고, 여기서 다시 해석하면 모델을
        # 고를 수 없는 호출 위치에서 모델이 기본 모델로 바뀌어 이 구현이 모르는 id 를 찾는다.
        model = backend_model_id("bedrock", usage.model)
        max_tokens = _max_tokens(usage.call_site)
        tally = ClaudeStreamTally("bedrock", "Bedrock")
        try:
            stream = await self._sdk().messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": user_content(prompt, usage.call_site, logger)}],
                system=system_instruction if system_instruction is not None else anthropic.omit,
                stop_sequences=stop_sequences if stop_sequences else anthropic.omit,
                thinking={"type": "disabled"},
                stream=True,
                timeout=_timeout_seconds(usage.call_site),
            )
            async for event in stream:
                was_truncated = tally.truncated
                text = tally.feed(event)
                if text:
                    yield text
                if tally.truncated and not was_truncated:
                    # 조용히 넘기면 "AI가 말을 하다 말았다"로만 보인다. 자주 찍히면 상한이 낮은 것이다.
                    logger.warning("Bedrock 응답이 max_tokens(%d)에서 잘렸다", max_tokens)
        except _TRANSPORT_ERRORS as exc:
            if _is_throttling(exc):
                raise _bedrock_error(LLMRateLimitError, f"Bedrock generate() call failed: {exc}") from exc
            raise _bedrock_error(LLMClientError, f"Bedrock generate() call failed: {exc}") from exc
        # 정상 종료한 스트림만 여기 닿는다 — 정책 거절·SDK 예외는 위에서 올라가고, 소비자가 중간에 끊으면(aclose) `yield`
        # 자리에서 GeneratorExit 으로 빠진다. 그 경우는 기록하지 않는다(Gemini 와 같은 규칙).
        usage_metadata = tally.usage()
        _log_usage(usage, model, usage_metadata)
        await record_usage(usage.call_site, model, usage_metadata)
        collect_usage(usage, model, usage_metadata)
        raise_if_unusable(tally, usage.call_site, max_tokens)

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        """판정·요약 하나. 모델은 방의 모델이 아니라 그 호출의 판정·요약 모델 설정이다(라우터가 이 구현을 고른 것도 그
        모델로다). 타임아웃은 그 호출 위치의 Gemini 값과 같고(판정 하나가 턴을 붙잡는 시간이 공급자에 따라 늘지 않게), 출력
        상한은 채팅 상한이다. 사고는 생성과 같이 끈다. 응답 해석과 실패 정규화는 공용 조각(`parse_structured`)이다."""
        if images:
            # 그림을 싣는 호출(발행 심사)은 기동 검증이 이 구현에 배정하지 못하게 막는다.
            raise _bedrock_error(LLMClientError, "Bedrock client does not take images in a structured call")
        model = backend_model_id("bedrock", configured_call_site_model(usage.call_site))
        try:
            message = await self._sdk().messages.create(
                model=model,
                max_tokens=_max_tokens(usage.call_site),
                messages=[{"role": "user", "content": str(prompt)}],
                output_config=structured_output_config(response_schema),
                thinking={"type": "disabled"},
                timeout=request_timeout_ms(usage.call_site) / 1000,
            )
        except _TRANSPORT_ERRORS as exc:
            if _is_throttling(exc):
                raise _bedrock_error(LLMRateLimitError, f"Bedrock generate_structured() call failed: {exc}") from exc
            raise _bedrock_error(LLMClientError, f"Bedrock generate_structured() call failed: {exc}") from exc
        usage_metadata = message_usage(message)
        _log_usage(usage, model, usage_metadata)
        await record_usage(usage.call_site, model, usage_metadata)
        collect_usage(usage, model, usage_metadata)
        return parse_structured(message, response_schema, "bedrock", "Bedrock")
