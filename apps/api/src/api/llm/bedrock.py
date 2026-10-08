"""AWS Bedrock 의 Claude 로 글을 쓰는 LLMClient. 채팅 턴 생성(지난 턴 다시 생성 포함)과 소설 장 생성(`generate`)만
받는다 — 구조화 호출은 라우팅 클라이언트(`llm/routing.py`)가 언제나 Gemini 로 보내므로 여기서는 구현하지 않는다.

실패 규칙은 `llm/gemini.py` 와 같다. SDK·네트워크 예외는 전부 `LLMClientError` 계열로 바꾼다(그대로 새면 SSE 제너레이터를
뚫어 요청 스코프 DB 세션이 강제 종료된다). 사용량은 정상 종료한 스트림만 기록하고, 소설 장의 잘림·빈 본문은 기록한 **뒤**
구분된 실패로 올린다. 여기서 올리는 예외에는 `provider = "bedrock"` 을 적어 Bugsink 태그가 Gemini 와 갈리게 한다.

요청에 계정을 가리키는 값(`metadata.user_id` 등)을 싣지 않는다 — 개인정보 처리방침의 국외 이전 항목이 이 전제로 쓰인다.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TypeVar

import anthropic
import botocore.eventstream
import botocore.exceptions
import httpx
import httpx2
from anthropic import AsyncAnthropicBedrock
from anthropic.types import TextBlockParam
from pydantic import BaseModel

from api.core.config import settings
from api.llm.chat_models import actual_model_id
from api.llm.client import (
    NOVELIZE_CALL_SITES,
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    LLMTruncatedError,
    SegmentedPrompt,
)
from api.llm.usage_store import record_usage

T = TypeVar("T", bound=BaseModel)
E = TypeVar("E", bound=LLMClientError)

logger = logging.getLogger(__name__)


def _bedrock_error(cls: type[E], message: str) -> E:
    exc = cls(message)
    exc.provider = "bedrock"
    return exc


def _timeout_seconds(call_site: LLMCallSite) -> float:
    """요청 하나의 타임아웃(초). SDK 의 httpx 경로에서 이 값은 연결·읽기 단계마다의 상한이라, 스트리밍에서는 호출 전체가
    아니라 "다음 청크까지"의 상한이다(Gemini 생성과 같은 성질). 꾸준히 흘러나오는 긴 장의 전체 시간은 소설화 작업 상한이
    끊는다."""
    if call_site == "novelize_chapter":
        return settings.bedrock_chapter_timeout_ms / 1000
    return settings.bedrock_chat_timeout_ms / 1000


def _max_tokens(call_site: LLMCallSite) -> int:
    if call_site == "novelize_chapter":
        return settings.bedrock_chapter_max_tokens
    return settings.bedrock_chat_max_tokens


def _is_throttling(exc: BaseException) -> bool:
    """쿼터 소진(스로틀)인가. 요청 단계의 스로틀은 HTTP 429 로 오지만, 스트림 도중의 스로틀은 응답 상태가 이미 200 이라
    상태 코드가 아니라 오류 본문의 종류(`throttlingException`)로만 드러난다."""
    if isinstance(exc, anthropic.RateLimitError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and "throttl" in str(exc.body).lower()


def _user_content(prompt: str, call_site: LLMCallSite) -> str | list[TextBlockParam]:
    """대본을 user 메시지 내용으로 만든다. 채팅 턴은 빌더가 나눈 블록 셋으로 보내고 둘째 블록(대화 기록 끝)에만 캐시
    체크포인트를 단다 — 다음 턴은 이 턴의 첫째·둘째 블록을 이은 것을 첫째 블록으로 보내므로, 자기 첫째 블록 경계에서 이
    체크포인트가 쓴 캐시를 찾는다. 셋째 블록(키워드북·현재 상황·이번 입력)은 턴마다 바뀌어 표시하지 않는다. system 은
    메시지보다 앞이라 체크포인트까지의 앞부분에 저절로 들어간다. 체크포인트까지가 모델별 최소 캐시 길이보다 짧으면 Bedrock 은
    오류 없이 캐시만 하지 않으므로 길이를 따로 재지 않는다.

    소설 장은 장마다 내용이 거의 다 바뀌어 캐시 쓰기 할증만 내므로 걸지 않는다. 경계가 없는 채팅 턴(보통 문자열)은 하나로
    보낸다 — 빌더는 대화 기록이 빈 턴에 일부러 보통 문자열을 내고, 기록이 있는데 나누지 못한 턴은 이유를 아는 빌더가 경고로
    남긴다. 여기서는 경계가 있는데 셋이 아닌 경우(빌더와 이 구현이 어긋난 것)만 경고로 남긴다.

    지난 턴을 다시 생성하는 측정 호출(`replay_generate`)도 같은 블록·체크포인트로 보낸다 — 실제 생성과 같은 요청 모양이라야
    원가·지연 측정이 맞고, 같은 턴을 여러 번 돌릴 때 앞부분을 캐시로 싸게 읽는다."""
    if call_site in ("chat_generate", "replay_generate") and isinstance(prompt, SegmentedPrompt):
        if len(prompt.segments) == 3:
            first, history_end, rest = prompt.segments
            return [
                {"type": "text", "text": first},
                {"type": "text", "text": history_end, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": rest},
            ]
        try:
            # 로그 실패가 턴을 막지 않게 한다(`_log_usage` 와 같은 규칙).
            logger.warning("채팅 턴 프롬프트의 캐시 경계가 셋이 아니라 블록 하나로 보낸다(조각 %d개)", len(prompt.segments))
        except Exception:
            pass
    return str(prompt)


@dataclass(frozen=True)
class _BedrockUsage:
    """Claude 의 사용량을 Gemini 사용량 메타데이터의 속성 이름으로 옮긴 것 — 사용량 기록(`record_usage`)과 어드민 원가가
    공급자를 가리지 않고 같은 열을 읽게 한다. Claude 의 입력 토큰은 캐시 읽기·쓰기를 뺀 값이라, Gemini 처럼 캐시를 포함한
    입력 전체가 되게 셋을 더한다. 사고는 끄므로 사고 토큰은 0 이다."""

    prompt_token_count: int
    cached_content_token_count: int
    cache_write_token_count: int
    candidates_token_count: int
    thoughts_token_count: int
    total_token_count: int


def _to_usage(input_tokens: int, cache_read: int, cache_write: int, output_tokens: int) -> _BedrockUsage:
    prompt = input_tokens + cache_read + cache_write
    return _BedrockUsage(
        prompt_token_count=prompt,
        cached_content_token_count=cache_read,
        cache_write_token_count=cache_write,
        candidates_token_count=output_tokens,
        thoughts_token_count=0,
        total_token_count=prompt + output_tokens,
    )


def _log_usage(usage: LLMCallContext, model: str, usage_metadata: _BedrockUsage | None) -> None:
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
        # (채팅 턴은 그 안을 캐시 블록으로 나눈다, `_user_content`).
        # 사고는 끈다 — 채팅은 첫 글자 지연이 체감이고, 두 모델 모두 끌 수 있다.
        model = actual_model_id(usage.model)
        max_tokens = _max_tokens(usage.call_site)
        input_tokens: int | None = None
        cache_read = 0
        cache_write = 0
        output_tokens = 0
        truncated = False
        has_text = False
        try:
            stream = await self._sdk().messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": _user_content(prompt, usage.call_site)}],
                system=system_instruction if system_instruction is not None else anthropic.omit,
                stop_sequences=stop_sequences if stop_sequences else anthropic.omit,
                thinking={"type": "disabled"},
                stream=True,
                timeout=_timeout_seconds(usage.call_site),
            )
            async for event in stream:
                if event.type == "message_start":
                    start_usage = event.message.usage
                    input_tokens = start_usage.input_tokens
                    cache_read = start_usage.cache_read_input_tokens or 0
                    cache_write = start_usage.cache_creation_input_tokens or 0
                    output_tokens = start_usage.output_tokens
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta" and event.delta.text:
                        has_text = has_text or bool(event.delta.text.strip())
                        yield event.delta.text
                elif event.type == "message_delta":
                    # 사용량은 누적값으로 온다. 입력·캐시 값이 실려 오면 시작 때의 값보다 이것이 최종이다.
                    delta_usage = event.usage
                    output_tokens = delta_usage.output_tokens
                    if delta_usage.input_tokens is not None:
                        input_tokens = delta_usage.input_tokens
                    if delta_usage.cache_read_input_tokens is not None:
                        cache_read = delta_usage.cache_read_input_tokens
                    if delta_usage.cache_creation_input_tokens is not None:
                        cache_write = delta_usage.cache_creation_input_tokens
                    if event.delta.stop_reason == "refusal":
                        raise _bedrock_error(LLMPolicyViolationError, "Bedrock Claude refused to continue")
                    if event.delta.stop_reason == "max_tokens":
                        # 조용히 넘기면 "AI가 말을 하다 말았다"로만 보인다. 자주 찍히면 상한이 낮은 것이다.
                        truncated = True
                        logger.warning("Bedrock 응답이 max_tokens(%d)에서 잘렸다", max_tokens)
        except (
            anthropic.AnthropicError,
            botocore.exceptions.BotoCoreError,
            botocore.eventstream.ParserError,
            httpx2.HTTPError,
            httpx.HTTPError,
            TimeoutError,
        ) as exc:
            # SDK 는 요청 단계의 실패를 자기 예외(`AnthropicError` 계열)로 바꾸지만, 스트림을 읽는 도중의 네트워크 실패는
            # 자기가 쓰는 `httpx2` 예외 그대로 올린다. `httpx`(이 저장소의 다른 SDK 가 쓰는 쪽)와 `TimeoutError` 는 전송 계층이
            # 바뀌어도 SSE 본문을 뚫지 않게 함께 잡는다. botocore 예외도 SDK 가 감싸지 않고 그대로 올린다 — 요청 서명
            # 단계(`BotoCoreError` 계열, 프로세스 env 의 `AWS_PROFILE` 이 없는 프로필을 가리키면 `ProfileNotFound`)와 응답
            # event-stream 디코딩 단계(`ParserError` 계열, 체크섬·길이가 깨진 프레임)다.
            if _is_throttling(exc):
                raise _bedrock_error(LLMRateLimitError, f"Bedrock generate() call failed: {exc}") from exc
            raise _bedrock_error(LLMClientError, f"Bedrock generate() call failed: {exc}") from exc
        # 정상 종료한 스트림만 여기 닿는다 — 정책 거절·SDK 예외는 위에서 올라가고, 소비자가 중간에 끊으면(aclose) `yield`
        # 자리에서 GeneratorExit 으로 빠진다. 그 경우는 기록하지 않는다(Gemini 와 같은 규칙).
        usage_metadata = (
            None if input_tokens is None else _to_usage(input_tokens, cache_read, cache_write, output_tokens)
        )
        _log_usage(usage, model, usage_metadata)
        await record_usage(usage.call_site, model, usage_metadata)
        if usage.call_site in NOVELIZE_CALL_SITES:
            if truncated:
                raise _bedrock_error(LLMTruncatedError, f"Bedrock output hit max_tokens({max_tokens})")
            if not has_text:
                raise _bedrock_error(LLMEmptyResponseError, "Bedrock returned an empty body")

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        raise _bedrock_error(LLMClientError, "Bedrock client does not serve structured calls — they go to Gemini")
