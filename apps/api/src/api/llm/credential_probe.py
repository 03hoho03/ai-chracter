"""Claude 자격 목록에 넣을 키를 Anthropic API 로 확인하는 두 호출 — 저장 때 조직 조회(토큰 세기)와 모델 축 확인 호출.

- 조직 조회는 판정 모델 id 로 토큰 세기(무료)를 불러 응답 헤더 `anthropic-organization-id` 를 읽는다. 운영의 모든 판정·요약이
  그 id 로 가므로 그 id 로 토큰 세기조차 안 되는 키는 목록에서 쓸 수 없다. 헤더가 없으면 조직 미확인(None)이다.
- 확인 호출은 실제 id 하나에 한 번, 운영 요청과 같은 꼴에 출력 상한만 작게 보낸다(`CheckGroup` 의 꼴). 비스트림이다 — 확인할
  성질(이 키·이 조직이 이 id 를 받는가)은 첫 바이트 전에 정해지고, 헤더와 사용량이 응답 하나에 온다. 성공 기준은 HTTP 200
  이다(본문은 보지 않는다).
- 키와 호스트를 명시로 넘기고 재시도하지 않는다 — 직결 구현(`llm/anthropic_api.py`)과 같은 이유로, SDK 는 명시 인자가 없으면
  env 의 `ANTHROPIC_API_KEY`·`ANTHROPIC_BASE_URL` 을 읽는다. 저장마다 만들고 버리는 클라이언트라 `async with` 로 닫는다.
- 호출 위치를 만들지 않는다 — 사용량 기록·어드민 사용량 화면에 나타나지 않고, 실제 호출마다 고정 토큰 줄
  `anthropic_credential_check_usage` 하나만 남긴다(직결의 `anthropic_usage` grep·분포에 섞이지 않게 이름을 나눴다).
- 실패는 종류 문자열만 실은 `CredentialProbeError` 로 원인 사슬을 끊어 올린다 — SDK 전송 오류의 원인에는 하위 계층 문장이
  붙고, 그 계층(h11)은 헤더 값을 문장에 그대로 싣는다.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from api.core.config import settings
from api.llm.anthropic_api import _BASE_URL, _structured_reasoning
from api.llm.claude_messages import COMMON_TRANSPORT_ERRORS
from api.llm.credential_accounts import normalize_account
from api.llm.credentials import CheckGroup, ProbeFailureKind, probe_failure_kind

logger = logging.getLogger(__name__)

ORGANIZATION_HEADER = "anthropic-organization-id"
# 확인 호출의 출력 상한과 메시지. 사용자 대화는 싣지 않는다.
CHECK_MAX_TOKENS = 16
CHECK_PROMPT = "확인"
# 조직 조회(토큰 세기)의 상한. 확인 호출은 운영 채팅 생성과 같은 상한을 쓴다.
_PROBE_TIMEOUT_SECONDS = 10.0


class CredentialProbeError(Exception):
    """조직 조회가 실패했다. 문장은 실패 종류뿐이다."""

    def __init__(self, kind: ProbeFailureKind) -> None:
        super().__init__(kind)
        self.kind: ProbeFailureKind = kind


@dataclass(frozen=True)
class CheckCallResult:
    """확인 호출 한 번의 결과. `error_kind` 가 None 이면 받아들여졌다(200). `organization` 은 그 응답의 조직 헤더(정규화)다."""

    error_kind: ProbeFailureKind | None
    organization: str | None


class CredentialProbe(Protocol):
    async def organization_of(self, api_key: str) -> str | None: ...

    async def check(self, api_key: str, group: CheckGroup, *, credential_id: uuid.UUID) -> CheckCallResult: ...


def _sdk(api_key: str, timeout: float) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=api_key, base_url=_BASE_URL, max_retries=0, timeout=timeout)


def _messages() -> list[MessageParam]:
    return [{"role": "user", "content": CHECK_PROMPT}]


def _log_usage(credential_id: uuid.UUID, model: str, outcome: anthropic.types.Message | ProbeFailureKind) -> None:
    """실제 호출 한 건의 고정 토큰 줄 — 받아들여졌으면 토큰 수, 실패면 그 종류만. 절대 raise 하지 않는다."""
    try:
        if isinstance(outcome, str):
            logger.warning(
                "anthropic_credential_check_usage credential_id=%s model=%s outcome=%s", credential_id, model, outcome
            )
            return
        usage = outcome.usage
        logger.warning(
            "anthropic_credential_check_usage credential_id=%s model=%s input_tokens=%s output_tokens=%s "
            "cache_read_tokens=%s cache_write_tokens=%s",
            credential_id,
            model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_input_tokens,
            usage.cache_creation_input_tokens,
        )
    except Exception:
        pass


class AnthropicCredentialProbe:
    async def organization_of(self, api_key: str) -> str | None:
        """그 키의 조직 id(정규화). 헤더가 없거나 비면 None. 실패하면 `CredentialProbeError`."""
        async with _sdk(api_key, _PROBE_TIMEOUT_SECONDS) as client:
            try:
                raw = await client.messages.with_raw_response.count_tokens(
                    model=settings.anthropic_haiku_model_id, messages=_messages()
                )
                header = raw.headers.get(ORGANIZATION_HEADER)
                await raw.parse()
            except COMMON_TRANSPORT_ERRORS as exc:
                raise CredentialProbeError(probe_failure_kind(exc)) from None
        return normalize_account(header)

    async def check(self, api_key: str, group: CheckGroup, *, credential_id: uuid.UUID) -> CheckCallResult:
        """그 id 로 확인 호출 한 번. 실패도 예외가 아니라 결과로 돌려준다(그 축의 기록이 된다)."""
        thinking: anthropic.types.ThinkingConfigParam | None = None
        effort = settings.anthropic_chat_effort if group.shape == "generation" else None
        if group.shape == "judgment":
            thinking, effort = _structured_reasoning(group.model_id)
        async with _sdk(api_key, settings.anthropic_chat_timeout_ms / 1000) as client:
            try:
                raw = await client.messages.with_raw_response.create(
                    model=group.model_id,
                    max_tokens=CHECK_MAX_TOKENS,
                    messages=_messages(),
                    output_config={"effort": effort} if effort is not None else anthropic.omit,
                    thinking=thinking if thinking is not None else anthropic.omit,
                    timeout=settings.anthropic_chat_timeout_ms / 1000,
                )
                header = raw.headers.get(ORGANIZATION_HEADER)
                message = await raw.parse()
            except COMMON_TRANSPORT_ERRORS as exc:
                kind = probe_failure_kind(exc)
                _log_usage(credential_id, group.model_id, kind)
                return CheckCallResult(error_kind=kind, organization=None)
        _log_usage(credential_id, group.model_id, message)
        return CheckCallResult(error_kind=None, organization=normalize_account(header))


def get_anthropic_credential_probe() -> CredentialProbe:
    """저장·확인 라우트가 받는 조사. 테스트는 이 의존성을 갈아 끼운다."""
    return AnthropicCredentialProbe()
