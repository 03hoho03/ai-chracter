"""Anthropic 직결 구현이 SDK 에 넘기는 요청 인자와 남기는 기록을 고정한다 — 생성(채팅 세 모델·리플레이·소설 장·본문 없이 끝난
응답·402 거절)과 구조화(판정·배정 행이 정한 판정 모델·소설 구성안·401 거절).

SDK 경계(`messages.create`)만 가짜로 두고 구현을 그대로 부른다. 경우마다 남기는 값은 다섯이다: 가짜 SDK 가 받은 인자 목록,
사용량 기록(`record_usage`)에 넘긴 값, 턴·소설 기록에 실리는 사용량(`as_record()`), 고정 토큰 사용량 로그 줄, 올라온 예외(클래스
이름·문장·원인 클래스 이름·공급자). 응답 본문은 보지 않는다 — 이 고정이 지키는 것은 "같은 요청이 나가고 같은 기록이 남는다"이다.

기존 장부 고정(`test_llm_request_ledger.py`)은 라우팅 클라이언트 안쪽을 가짜 구현으로 바꿔 이 구현의 SDK 인자를 보지 않는다.
요청 인자에 닿는 설정(모델 id·깊이·상한·시간 초과)은 로컬 env 파일과 무관하게 여기서 고정한다.

기대값은 지금 동작을 기록한 것이다(`fixtures/anthropic_request_characterization.json`). 다시 뜨는 법은
`factories._assert_characterization`(갱신 변수 `UPDATE_ANTHROPIC_REQUEST_CHARACTERIZATION`).
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types import Message
from pydantic import BaseModel

from api.core.config import settings
from api.llm import anthropic_api as anthropic_module
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.client import CallUsage, LLMCallContext, LLMClientError, SegmentedPrompt
from factories import _assert_characterization, _assert_recorded_cases

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "anthropic_request_characterization.json"
UPDATE_ENV = "UPDATE_ANTHROPIC_REQUEST_CHARACTERIZATION"

_ENV_KEY = "sk-ant-test-characterization-env-key-0000"
_SETTINGS: dict[str, object] = {
    "anthropic_direct_api_key": _ENV_KEY,
    "anthropic_opus_model_id": "claude-opus-5-5",
    "anthropic_sonnet_model_id": "claude-sonnet-5-5",
    "anthropic_haiku_writer_model_id": "claude-haiku-5-5",
    "anthropic_haiku_model_id": "claude-haiku-5-5",
    "anthropic_chat_timeout_ms": 45_000,
    "anthropic_chapter_timeout_ms": 300_000,
    "anthropic_chat_max_tokens": 16_000,
    "anthropic_chapter_max_tokens": 64_000,
    "anthropic_chat_effort": "low",
    "anthropic_chapter_effort": "medium",
    "anthropic_structured_effort": "low",
    "stat_judgment_model": "haiku",
    "gemini_judgment_timeout_ms": 20_000,
    "gemini_novelize_chapter_timeout_ms": 300_000,
}

_SYSTEM = "역할 지시문"
_STOP = ["나:"]
_SEGMENTED = SegmentedPrompt(("앞부분", "대화 기록 끝", "이번 입력"))
_CHAPTER_PROMPT = "장 원고 프롬프트"
_JUDGMENT_PROMPT = "판정 프롬프트"
_OUTLINE_INSTRUCTION = "구성안 지시문"
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class _Verdict(BaseModel):
    """응답 스키마. 다른 모듈의 스키마가 바뀌어도 이 고정이 흔들리지 않게 여기 둔다."""

    rule_ids: list[str]


# ── SDK 가짜가 돌려주는 것 ─────────────────────────────────────────────────────────────
def _start() -> Any:
    usage = SimpleNamespace(
        input_tokens=700, cache_read_input_tokens=200, cache_creation_input_tokens=100, output_tokens=1
    )
    return SimpleNamespace(type="message_start", message=SimpleNamespace(usage=usage))


def _thinking() -> list[Any]:
    return [
        SimpleNamespace(
            type="content_block_start", index=0, content_block=SimpleNamespace(type="thinking", thinking="")
        ),
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="thinking_delta", thinking="")),
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="signature_delta", signature="sig")),
        SimpleNamespace(type="content_block_stop", index=0),
    ]


def _text(text: str) -> Any:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _end(stop_reason: str) -> Any:
    usage = SimpleNamespace(
        output_tokens=70,
        input_tokens=None,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
        output_tokens_details=SimpleNamespace(thinking_tokens=20),
    )
    return SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason=stop_reason), usage=usage)


_REPLY = [_start(), *_thinking(), _text("안녕"), _text("하세요"), _end("end_turn")]
_THINKING_ONLY = [_start(), *_thinking(), _end("max_tokens")]


def _message() -> Message:
    return Message.model_validate(
        {
            "id": "msg_characterization",
            "type": "message",
            "role": "assistant",
            "model": "m",
            "content": [{"type": "text", "text": '{"rule_ids": ["r1"]}'}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 300,
                "cache_read_input_tokens": 40,
                "cache_creation_input_tokens": 0,
                "output_tokens": 9,
            },
        }
    )


def _rejection_402() -> anthropic.APIStatusError:
    body = {"type": "error", "error": {"type": "billing_error", "message": "Your credit balance is too low"}}
    return anthropic.APIStatusError("Error code: 402", response=httpx2.Response(402, request=_REQUEST), body=body)


def _rejection_401() -> anthropic.APIStatusError:
    body = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    return anthropic.AuthenticationError("Error code: 401", response=httpx2.Response(401, request=_REQUEST), body=body)


@dataclass(frozen=True)
class _Reply:
    """가짜 SDK 의 응답 하나 — 스트림 이벤트, 비스트림 메시지, 또는 create 에서 낼 예외."""

    events: list[Any] | None = None
    message: Message | None = None
    error: BaseException | None = None


class _FakeMessages:
    def __init__(self, reply: _Reply) -> None:
        self.reply = reply
        self.seen: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.seen.append(kwargs)
        if self.reply.error is not None:
            raise self.reply.error
        if self.reply.events is not None:
            events = self.reply.events

            async def stream() -> AsyncIterator[Any]:
                for event in events:
                    yield event

            return stream()
        return self.reply.message


# ── 경우 ─────────────────────────────────────────────────────────────────────────
Call = Callable[[AnthropicLLMClient, list[CallUsage]], Awaitable[object]]


def _generate(prompt: str, usage: LLMCallContext, *, system: str | None, stop: list[str] | None) -> Call:
    async def call(client: AnthropicLLMClient, sink: list[CallUsage]) -> object:
        context = LLMCallContext(usage.call_site, None, None, model=usage.model, usage_sink=sink)
        return "".join([token async for token in client.generate(prompt, system, stop, usage=context)])

    return call


def _structured(usage: LLMCallContext) -> Call:
    async def call(client: AnthropicLLMClient, sink: list[CallUsage]) -> object:
        context = LLMCallContext(
            usage.call_site, None, None, model=usage.model, call_model=usage.call_model, usage_sink=sink
        )
        return await client.generate_structured(_JUDGMENT_PROMPT, _Verdict, usage=context)

    return call


def _outline(usage: LLMCallContext) -> Call:
    async def call(client: AnthropicLLMClient, sink: list[CallUsage]) -> object:
        context = LLMCallContext(usage.call_site, None, None, model=usage.model, usage_sink=sink)
        return await client.generate_structured_with_instruction(
            _JUDGMENT_PROMPT, _Verdict, system_instruction=_OUTLINE_INSTRUCTION, usage=context
        )

    return call


_CASES: dict[str, tuple[Call, _Reply]] = {
    "generate-chat-opus": (
        _generate(_SEGMENTED, LLMCallContext("chat_generate", None, None, model="opus"), system=_SYSTEM, stop=_STOP),
        _Reply(events=_REPLY),
    ),
    "generate-chat-sonnet": (
        _generate(_SEGMENTED, LLMCallContext("chat_generate", None, None, model="sonnet"), system=_SYSTEM, stop=_STOP),
        _Reply(events=_REPLY),
    ),
    "generate-chat-haiku-writer": (
        _generate(
            _SEGMENTED, LLMCallContext("chat_generate", None, None, model="haiku_writer"), system=_SYSTEM, stop=_STOP
        ),
        _Reply(events=_REPLY),
    ),
    "generate-replay-sonnet": (
        _generate(
            _SEGMENTED, LLMCallContext("replay_generate", None, None, model="sonnet"), system=_SYSTEM, stop=_STOP
        ),
        _Reply(events=_REPLY),
    ),
    "generate-chapter-opus": (
        _generate(
            _CHAPTER_PROMPT, LLMCallContext("novelize_chapter", None, None, model="opus"), system=_SYSTEM, stop=None
        ),
        _Reply(events=_REPLY),
    ),
    "generate-empty-before-text": (
        _generate(_SEGMENTED, LLMCallContext("chat_generate", None, None, model="opus"), system=_SYSTEM, stop=_STOP),
        _Reply(events=_THINKING_ONLY),
    ),
    "generate-rejected-402": (
        _generate(_SEGMENTED, LLMCallContext("chat_generate", None, None, model="opus"), system=_SYSTEM, stop=_STOP),
        _Reply(error=_rejection_402()),
    ),
    "structured-stat-haiku": (
        _structured(LLMCallContext("chat_stat_judgment", None, None, model="opus")),
        _Reply(message=_message()),
    ),
    "structured-routed-sonnet": (
        _structured(LLMCallContext("chat_stat_judgment", None, None, model="opus", call_model="sonnet")),
        _Reply(message=_message()),
    ),
    "structured-outline-opus": (
        _outline(LLMCallContext("novelize_outline", None, None, model="opus")),
        _Reply(message=_message()),
    ),
    "structured-rejected-401": (
        _structured(LLMCallContext("chat_stat_judgment", None, None, model="opus")),
        _Reply(error=_rejection_401()),
    ),
}


# ── 기록 ─────────────────────────────────────────────────────────────────────────
def _plain(value: Any) -> Any:
    """요청 인자를 JSON 으로 남길 꼴로 — SDK 의 "보내지 않음" 표지는 문자열로 적는다."""
    if value is anthropic.omit:
        return "<omit>"
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


_USAGE_ATTRS = (
    "prompt_token_count",
    "cached_content_token_count",
    "cache_write_token_count",
    "candidates_token_count",
    "thoughts_token_count",
    "total_token_count",
)


@pytest.fixture(autouse=True)
def _pinned_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _SETTINGS.items():
        monkeypatch.setattr(settings, name, value)


async def _observe(
    case: str, client: AnthropicLLMClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> tuple[dict[str, object], _FakeMessages]:
    """그 경우를 한 번 부르고 남는 다섯 값을 모은다. 가짜 SDK 는 env 키 클라이언트 자리에 끼운다."""
    call, reply = _CASES[case]
    fake = _FakeMessages(reply)
    monkeypatch.setattr(client, "_client", SimpleNamespace(messages=fake))
    usage_calls: list[list[object]] = []

    async def record_usage(call_site: str, model: str, usage_metadata: object | None) -> None:
        usage_calls.append([call_site, model, {attr: getattr(usage_metadata, attr, None) for attr in _USAGE_ATTRS}])

    monkeypatch.setattr(anthropic_module, "record_usage", record_usage)
    sink: list[CallUsage] = []
    error: dict[str, object] | None = None
    with caplog.at_level(logging.WARNING, logger=anthropic_module.__name__):
        try:
            await call(client, sink)
        except LLMClientError as exc:
            cause = exc.__cause__
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "cause": None if cause is None else type(cause).__name__,
                "provider": exc.provider,
            }
    log = [
        record.getMessage()
        for record in caplog.records
        if record.name == anthropic_module.__name__ and record.getMessage().startswith("anthropic_usage")
    ]
    observed: dict[str, object] = {
        "requests": [_plain(kwargs) for kwargs in fake.seen],
        "recordUsage": usage_calls,
        "records": [usage.as_record() for usage in sink],
        "log": log,
        "error": error,
    }
    return observed, fake


@pytest.mark.parametrize("case", list(_CASES))
async def test_requests_usage_and_records_match_the_recorded_baseline(
    case: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    observed, _ = await _observe(case, AnthropicLLMClient(), monkeypatch, caplog)

    _assert_characterization(FIXTURE_PATH, case, observed, UPDATE_ENV)


def test_recorded_cases_match_the_parameters() -> None:
    _assert_recorded_cases(FIXTURE_PATH, _CASES, UPDATE_ENV)
