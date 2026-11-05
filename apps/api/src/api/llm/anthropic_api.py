"""Anthropic API 로 Claude 에 바로 보내는 LLMClient. 배정(`LLM_CALL_SITE_BACKENDS`)이 호출을 이 구현으로 옮길 때만 닿는다 —
배정이 없으면 Claude 모델은 Bedrock 으로 간다(`llm/backends.py` 의 기본 순서). 받는 호출과 실패 규칙은 Bedrock 구현과 같다:
채팅 턴 생성(지난 턴 다시 생성 포함)과 소설 장 생성(`generate`), 판정·요약 모델이 Claude 일 때의 판정·요약
(`generate_structured`), 사용자가 Claude 를 고른 소설 구성안(`generate_structured_with_instruction`)을 받고, 그림을 싣는
구조화는 등록부가 받지 못하는 구현으로 적어 기동 검증이 그런 배정을 거부한다. 예외에는 `provider = "anthropic"` 을 적는다.

글쓰기 모델(Opus 5.5 등)은 사고를 끌 수 없다 — `thinking` 을 끄거나 예산으로 보내면 요청이 거부되고, 생략하면 모델이
알아서 사고한다. 그래서 생성 요청에는 `thinking` 을 싣지 않고 깊이만 `output_config.effort` 로 고른다. 판정 전용 Haiku 는
버전마다 규칙이 달라 판정·요약 요청에서만 실제 모델 id 로 가른다(`_structured_reasoning`). 사고 토큰은 출력 상한 안에 들고
출력 단가로 과금된다. 강제 도구 선택과 assistant 미리 채우기도 이 모델들이 거부하는데, 대본이 user 메시지 하나라 둘 다
쓰지 않는다.

요청에 계정을 가리키는 값(`metadata.user_id` 등)을 싣지 않는다. 다른 모델로 조용히 넘기는 서버 쪽 대체 경로도 쓰지 않는다
(실패하면 오류와 환불이다 — 사용자가 고른 것과 다른 경로가 돌지 않게).

**어느 계정으로 보내나.** env 스위치(`LLM_CREDENTIAL_POOL_ENABLED`)가 꺼져 있거나, 켜졌어도 어드민의 "목록 사용"이 꺼져 있거나
Claude 자격 목록에 항목이 하나도 없으면 지금처럼 env 키(`ANTHROPIC_DIRECT_API_KEY`) 하나로 보낸다 — 스위치가 꺼졌으면 목록의
Redis·DB 를 보지도 않는다. 그 밖이면 목록에서 그 모델 축으로 보낼 수 있는 항목(`llm/credential_pool.py`)을 위치 순으로
내려간다. 모델 id·요청 인자는 어느 항목이든 같고 계정만 다르다. 응답 본문을 받기 전의 거절(HTTP 상태) 가운데 소진으로 볼
것(`llm/credentials.py` 의 `classify_anthropic_rejection`)만 그 항목을 소진으로 표시하고 다음 항목으로 같은 요청을 다시
보낸다 — 아직 사용자에게 글이 나가지 않았다. 스트림이 열린 뒤의 오류는 다시 보내지 않고(결제 오류 종류면 표시만), 소진이 아닌
거절·시간 초과·연결 오류는 env 키 경로와 같은 예외로 올린다. 보낼 항목이 남지 않으면 `LLMCredentialPoolEmptyError`(환불
경로)이고 env 키로 떨어지지 않는다. 목록으로 보낸 호출은 사용량 기록·로그 줄에 처리한 항목 id 를 싣고 그 항목의 추정 사용액에
원가를 쌓는다(`llm/credential_usage.py`).
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

import anthropic
from anthropic import AsyncAnthropic, AsyncStream
from anthropic.types import Message, RawMessageStreamEvent, ThinkingConfigParam
from pydantic import BaseModel

from api.core.config import ClaudeEffort, settings
from api.db.models.llm_credential import ClaudeModelAxis
from api.llm.backends import PromptSetModelId, follows_carried_model, turns_off_structured_thinking
from api.llm.call_policy import CALL_POLICIES
from api.llm.chat_models import backend_model_id, structured_call_model
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
    LLMCredentialPoolEmptyError,
    LLMEmptyResponseError,
    LLMRateLimitError,
    collect_usage,
    request_timeout_ms,
)
from api.llm.credential_pool import CredentialPool, PoolCredential
from api.llm.credential_usage import record_credential_spend
from api.llm.credentials import classify_anthropic_rejection
from api.llm.usage_store import record_usage

T = TypeVar("T", bound=BaseModel)
E = TypeVar("E", bound=LLMClientError)
R = TypeVar("R")

logger = logging.getLogger(__name__)

# SDK 는 호스트를 인자로 받지 않으면 env `ANTHROPIC_BASE_URL` 을 읽는다. 키를 명시로 넘기는 것과 같은 이유로 호스트도
# 명시한다 — 프로세스 env 의 값이 이 구현의 요청을 다른 곳으로 보내지 않게.
_BASE_URL = "https://api.anthropic.com"

# 사고 깊이(`output_config.effort`)를 받지 않는 모델의 id 접두 — 보내면 요청이 400 으로 거부된다(Claude Haiku 4.5).
_STRUCTURED_NO_EFFORT_PREFIXES = ("claude-haiku-4-5",)


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


def _structured_reasoning(model_id: str) -> tuple[ThinkingConfigParam | None, ClaudeEffort | None]:
    """판정·요약 요청의 (사고 설정, 깊이). None 이면 싣지 않는다. 판정 전용 id `haiku` 가 구현에 따라 Haiku 4.5 와 5.5 를
    함께 가리켜, 문안 모델 id 가 아니라 실제로 보내는 모델 id 로 가른다.

    - Haiku 4.5: 둘 다 싣지 않는다 — 깊이를 받으면 400 이고, 사고는 요청할 때만 한다.
    - Haiku 5.x: 사고를 끄고 깊이를 보낸다 — 사고가 기본으로 켜져 있고 깊이 기본값이 medium 이라, 둘 다 생략하면 판정이
      사고하며 돈다. 끄는 것은 Haiku 4.5 판정의 조건(사고 없음)을 잇고 사고 토큰(출력 단가)을 없앤다. 사고를 끈 요청은
      깊이를 high 까지만 받는다 — 기동 검증이 그 위를 거부한다(`llm/backends.py`).
    - 그 밖(Opus·Sonnet 5.5): 사고를 싣지 않고 깊이만 — 생성 경로와 같다.

    깊이는 판정·요약 몫의 설정(`anthropic_structured_effort`)이다. 채팅 생성 깊이를 따르면 그 값을 xhigh 로 올리는 순간
    Haiku 5.x 판정이 전부 거부된다."""
    effort = settings.anthropic_structured_effort
    if model_id.startswith(_STRUCTURED_NO_EFFORT_PREFIXES):
        return None, None
    if turns_off_structured_thinking(model_id):
        return {"type": "disabled"}, effort
    return None, effort


def _is_throttling(exc: BaseException) -> bool:
    """쿼터 소진인가. 요청 단계에서는 HTTP 429(`RateLimitError`)로 오지만, 스트림 도중에는 응답 상태가 이미 200 이라 SDK 가
    SSE `error` 이벤트를 상태 코드 갈래가 아닌 일반 `APIStatusError` 로 올린다 — 그때는 오류 본문의 종류로만 드러난다.
    과부하(529·`overloaded_error`)는 우리 쿼터가 아니라 공급자 쪽 혼잡이라 여기 넣지 않는다."""
    if isinstance(exc, anthropic.RateLimitError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.type == "rate_limit_error"


def _log_usage(
    usage: LLMCallContext, model: str, usage_metadata: ClaudeUsage | None, credential: PoolCredential | None
) -> None:
    """호출 한 건의 토큰 사용량을 고정 토큰 `anthropic_usage` 로 한 줄 남긴다. 형식과 규칙은 `bedrock_usage` 와 같고(텍스트는
    받지도 않는다, 메타데이터가 없으면 `usage=missing`, 절대 raise 하지 않는다), 이 경로는 사고하므로 사고 토큰 칸을 더한다.
    이름을 따로 두는 이유는 기존 `gemini_usage`·`bedrock_usage` grep·분포를 끊지 않으려는 것이다. Claude 자격 목록으로 보낸
    호출만 끝에 처리한 항목 id 를 붙인다 — 목록을 쓰지 않는 줄은 바이트까지 지금 그대로다."""
    try:
        logger.warning(
            "anthropic_usage call_site=%s model=%s prompt_tokens=%s cached_content_tokens=%s cache_write_tokens=%s "
            "candidates_tokens=%s thoughts_tokens=%s total_tokens=%s user_id=%s room_id=%s%s%s",
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
            f" credential_id={credential.id}" if credential is not None else "",
        )
    except Exception:
        pass


def _new_sdk(api_key: str) -> AsyncAnthropic:
    # 재시도는 하지 않는다(SDK 기본은 2회) — 재시도는 실패한 턴의 지연과 원가를 곱으로 늘린다. env 키와 목록 항목이 같은
    # 인자로 만든다 — 계정만 다르고 요청은 같아야 한다.
    return AsyncAnthropic(
        api_key=api_key,
        base_url=_BASE_URL,
        max_retries=0,
        timeout=settings.anthropic_chat_timeout_ms / 1000,
    )


def _axis(model: PromptSetModelId) -> ClaudeModelAxis:
    """Claude 자격 목록의 확인 축. 이 구현이 받는 모델은 늘 축이다 — 그 밖의 모델은 모델 id 표(`backend_model_id`)에서 이미
    `KeyError` 로 멈췄다."""
    if model == "gemini":
        raise KeyError(model)
    return model


class AnthropicLLMClient(LLMClient):
    def __init__(self, *, pool: CredentialPool | None = None) -> None:
        # SDK 클라이언트는 첫 호출 때 만든다 — 키가 비었을 때의 실패가 생성자(의존성 해석)가 아니라 그 호출의
        # `LLMClientError` 로 나야 채팅이 환불 경로를 탄다.
        self._client: AsyncAnthropic | None = None
        # Claude 자격 목록 읽기. 주지 않으면 스위치가 켜진 첫 호출에서 api 와 같은 세션 팩토리·Redis 로 만든다.
        self._pool = pool
        # 목록 항목마다의 SDK 클라이언트. (항목 id, 키 지문)으로 묶어 키를 바꾸면 새로 만들고, 호출마다 스냅숏의 켜진 항목으로
        # 걸러 끄기·소진·삭제·키 교체가 다음 호출에서 옛 클라이언트를 버린다. 버린 클라이언트는 닫지 않는다 — 진행 중인 스트림이
        # 쥐고 있을 수 있고, 가비지 수거 때 SDK 가 연결을 닫는다.
        self._pool_clients: dict[tuple[uuid.UUID, str], AsyncAnthropic] = {}

    def _sdk(self) -> AsyncAnthropic:
        if self._client is not None:
            return self._client
        key = settings.anthropic_direct_api_key.strip()
        if not key:
            # 🔴 키를 넘기지 않으면 SDK 가 env `ANTHROPIC_API_KEY`·`ANTHROPIC_AUTH_TOKEN`·로그인 프로필에서 다른 자격을 찾고,
            # 빈 문자열을 넘기면 그것도 명시 자격으로 쳐 env 를 보지 않은 채 인증 실패를 받는다. 만들기 전에 막는다.
            raise _anthropic_error(LLMClientError, "Anthropic API 키가 비어 있어 호출하지 않는다")
        self._client = _new_sdk(key)
        return self._client

    def _credential_pool(self) -> CredentialPool:
        if self._pool is None:
            self._pool = CredentialPool()
        return self._pool

    def _pool_sdk(self, pool: CredentialPool, credential: PoolCredential) -> AsyncAnthropic | None:
        """그 항목의 SDK 클라이언트. 키를 읽을 수 없으면 None(그 항목을 건너뛴다 — 알림은 풀이 한 번)."""
        sdk = self._pool_clients.get(credential.client_key)
        if sdk is None:
            secret = pool.secret_of(credential)
            if secret is None:
                return None
            sdk = self._pool_clients[credential.client_key] = _new_sdk(secret)
        return sdk

    async def _send(
        self, axis: ClaudeModelAxis, request: Callable[[AsyncAnthropic], Awaitable[R]]
    ) -> tuple[R, PoolCredential | None]:
        """요청을 보낸다. 목록을 쓰지 않으면 env 키로 한 번(지금 그대로). 쓰면 후보를 위치 순으로 내려가며, 소진으로 볼 거절이면
        그 항목을 소진으로 표시하고 다음 후보로 **같은 요청**을 보낸다. 여기서 잡는 거절은 응답 본문을 받기 전(HTTP 상태)이라
        사용자에게 글이 나가지 않았다 — 스트림 도중의 오류는 부르는 쪽의 읽기 루프에서 나므로 이 함수에 닿지 않는다. 소진이 아닌
        오류는 그대로 올려 부르는 쪽이 지금과 같은 예외로 바꾼다. 스위치는 호출마다 읽는다."""
        if not settings.llm_credential_pool_enabled:
            return await request(self._sdk()), None
        pool = self._credential_pool()
        plan = await pool.plan(axis)
        if plan is None:
            return await request(self._sdk()), None
        self._pool_clients = {key: sdk for key, sdk in self._pool_clients.items() if key in plan.live_keys}
        rejected: anthropic.APIStatusError | None = None
        marks: list[asyncio.Task[None]] = []
        for credential in plan.candidates:
            sdk = self._pool_sdk(pool, credential)
            if sdk is None:
                continue
            try:
                return await request(sdk), credential
            except anthropic.APIStatusError as exc:
                kind = classify_anthropic_rejection(exc)
                if kind is None:
                    raise
                marks.append(await pool.mark_exhausted(credential, kind))
                rejected = exc
        pool.alert_no_candidate(axis, after=marks)
        raise _anthropic_error(
            LLMCredentialPoolEmptyError, f"Claude 자격 목록에 {axis} 를 보낼 항목이 없다"
        ) from rejected

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
        # 한 번만 만든다 — 목록의 다음 항목으로 다시 보낼 때도 같은 요청이다.
        content = user_content(prompt, usage.call_site, logger)

        async def open_stream(sdk: AsyncAnthropic) -> AsyncStream[RawMessageStreamEvent]:
            return await sdk.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": content}],
                system=system_instruction if system_instruction is not None else anthropic.omit,
                stop_sequences=stop_sequences if stop_sequences else anthropic.omit,
                output_config={"effort": _effort(usage.call_site)},
                stream=True,
                timeout=_timeout_seconds(usage.call_site),
            )

        credential: PoolCredential | None = None
        try:
            # 여기까지가 첫 이벤트 전이다 — 목록의 다음 항목으로 다시 보내는 것은 이 안에서만 일어난다.
            stream, credential = await self._send(_axis(usage.model), open_stream)
            async for event in stream:
                was_truncated = tally.truncated
                text = tally.feed(event)
                if text:
                    yield text
                if tally.truncated and not was_truncated:
                    # 사고 토큰도 이 상한 안에 든다. 자주 찍히면 상한이 낮거나 effort 가 높은 것이다.
                    logger.warning("Anthropic 응답이 max_tokens(%d)에서 잘렸다", max_tokens)
        except COMMON_TRANSPORT_ERRORS as exc:
            if credential is not None:
                # 스트림이 열린 뒤의 오류 — 다시 보내지 않고, 결제 오류 종류면 그 항목을 표시만 한다.
                await self._credential_pool().mark_if_rejected_mid_stream(credential, exc)
            if _is_throttling(exc):
                raise _anthropic_error(LLMRateLimitError, f"Anthropic generate() call failed: {exc}") from exc
            raise _anthropic_error(LLMClientError, f"Anthropic generate() call failed: {exc}") from exc
        # 정상 종료한 스트림만 여기 닿는다 — 소비자가 중간에 끊으면(aclose) `yield` 자리에서 빠지고 기록하지 않는다. 스트림 도중
        # 실패한 호출도 위에서 올라가 기록하지 않는다. 구조화 호출이 시간 초과나 연결 끊김(부르는 쪽 취소)으로 응답 전에 끝난 것도
        # 같다. 이 셋은 과금될 수 있는데 목록 항목의 추정 사용액에도 쌓이지 않아, 그만큼 추정 잔액이 실제보다 많게 보일 수 있다
        # (사용량 기록과 같은 규칙).
        usage_metadata = tally.usage()
        _log_usage(usage, model, usage_metadata, credential)
        await record_usage(usage.call_site, model, usage_metadata)
        collect_usage(usage, model, usage_metadata, credential_id=credential.id if credential is not None else None)
        if credential is not None:
            await record_credential_spend(credential.spend_target, model, usage_metadata)
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
        """판정·요약 하나. 모델·타임아웃·출력 상한은 Bedrock 구현과 같은 규칙이다(그 호출의 판정·요약 모델, 그 호출 위치의
        Gemini 타임아웃, 채팅 상한). 사고와 깊이는 보내는 모델 id 로 정한다(`_structured_reasoning`). 사고하는 모델은 사고
        블록이 앞에 오고 그 토큰도 출력 상한 안에 든다."""
        if images:
            # 그림을 싣는 호출(발행 심사)은 기동 검증이 이 구현에 배정하지 못하게 막는다.
            raise _anthropic_error(LLMClientError, "Anthropic client does not take images in a structured call")
        return await self._structured(prompt, response_schema, None, usage, "generate_structured")

    async def generate_structured_with_instruction(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str,
        usage: LLMCallContext,
    ) -> T:
        """지시문을 `system` 으로 따로 싣는 구조화(소설 구성안). 모델은 사용자가 고른 모델이다(`structured_call_model`).
        나머지는 `generate_structured` 와 같다."""
        return await self._structured(
            prompt, response_schema, system_instruction, usage, "generate_structured_with_instruction"
        )

    async def _structured(
        self, prompt: str, response_schema: type[T], system: str | None, usage: LLMCallContext, method: str
    ) -> T:
        # 판정·요약은 방의 모델이 아니라 그 호출의 모델로 나가므로 목록의 후보도 그 축으로 고른다.
        axis = _axis(structured_call_model(usage.call_site, usage.model, usage.call_model))
        model = backend_model_id("anthropic", axis)
        thinking: ThinkingConfigParam | None
        effort: ClaudeEffort | None
        if follows_carried_model(usage.call_site):
            # 사용자가 고른 글쓰기 모델로 내는 유료 구조화(소설 구성안)는 판정 몫의 깊이가 아니라 그 호출 위치의 깊이(장 생성과
            # 같은 프로필)로 간다 — 판정 원가를 줄이려 판정 깊이를 낮추면 값을 낸 구성안의 품질까지 함께 내려가지 않게. 사고는
            # 생성과 같이 싣지 않는다(글쓰기 모델은 끌 수 없다).
            thinking, effort = None, _effort(usage.call_site)
        else:
            thinking, effort = _structured_reasoning(model)
        output_config = structured_output_config(response_schema)
        if effort is not None:
            output_config["effort"] = effort

        async def send(sdk: AsyncAnthropic) -> Message:
            return await sdk.messages.create(
                model=model,
                max_tokens=_max_tokens(usage.call_site),
                messages=[{"role": "user", "content": str(prompt)}],
                system=system if system is not None else anthropic.omit,
                output_config=output_config,
                thinking=thinking if thinking is not None else anthropic.omit,
                timeout=request_timeout_ms(usage.call_site) / 1000,
            )

        try:
            message, credential = await self._send(axis, send)
        except COMMON_TRANSPORT_ERRORS as exc:
            if _is_throttling(exc):
                raise _anthropic_error(LLMRateLimitError, f"Anthropic {method}() call failed: {exc}") from exc
            raise _anthropic_error(LLMClientError, f"Anthropic {method}() call failed: {exc}") from exc
        usage_metadata = message_usage(message)
        _log_usage(usage, model, usage_metadata, credential)
        await record_usage(usage.call_site, model, usage_metadata)
        collect_usage(usage, model, usage_metadata, credential_id=credential.id if credential is not None else None)
        if credential is not None:
            await record_credential_spend(credential.spend_target, model, usage_metadata)
        return parse_structured(message, response_schema, "anthropic", "Anthropic")
