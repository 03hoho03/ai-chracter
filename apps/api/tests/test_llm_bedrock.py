import base64
import binascii
import json
import logging
import struct
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import anthropic
import botocore.eventstream
import botocore.exceptions
import httpx
import httpx2
import pytest
from pydantic import BaseModel

from api.chat.turn_judgments import _llm_dependency_tag
from api.core.config import settings
from api.llm import bedrock as bedrock_module
from api.llm.bedrock import BedrockLLMClient
from api.llm.client import (
    LLMCallContext,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    LLMTruncatedError,
    SegmentedPrompt,
)

_CHAT = LLMCallContext("chat_generate", None, None, model="sonnet")
_CHAPTER = LLMCallContext("novelize_chapter", None, None, model="opus")


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bedrock_access_key_id", "AKIATEST")
    monkeypatch.setattr(settings, "bedrock_secret_access_key", "secret-test")
    monkeypatch.setattr(settings, "bedrock_region", "ap-northeast-2")


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    calls: list[tuple[str, str, Any]] = []

    async def record_usage(call_site: str, model: str, usage_metadata: object | None) -> None:
        calls.append((call_site, model, usage_metadata))

    monkeypatch.setattr(bedrock_module, "record_usage", record_usage)
    return calls


def _usage(input_tokens: int = 0, read: int | None = None, write: int | None = None, output: int = 0) -> Any:
    return SimpleNamespace(
        input_tokens=input_tokens,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=write,
        output_tokens=output,
    )


def _start(**usage: Any) -> Any:
    return SimpleNamespace(type="message_start", message=SimpleNamespace(usage=_usage(**usage)))


def _text(text: str) -> Any:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _end(stop_reason: str = "end_turn", output: int = 5) -> Any:
    return SimpleNamespace(
        type="message_delta",
        delta=SimpleNamespace(stop_reason=stop_reason),
        usage=SimpleNamespace(
            output_tokens=output, input_tokens=None, cache_read_input_tokens=None, cache_creation_input_tokens=None
        ),
    )


def _client_streaming(
    monkeypatch: pytest.MonkeyPatch, *events: Any, raise_at: BaseException | None = None
) -> tuple[BedrockLLMClient, list[dict[str, Any]]]:
    """SDK 경계(`messages.create(stream=True)`)만 가짜로 둔다. `raise_at` 은 이벤트를 다 보낸 뒤 스트림 도중에 낸다."""
    seen: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> AsyncIterator[Any]:
        seen.append(kwargs)

        async def stream() -> AsyncIterator[Any]:
            for event in events:
                yield event
            if raise_at is not None:
                raise raise_at

        return stream()

    client = BedrockLLMClient()
    monkeypatch.setattr(client, "_client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client, seen


def _client_failing_on_create(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> BedrockLLMClient:
    async def create(**_: Any) -> Any:
        raise exc

    client = BedrockLLMClient()
    monkeypatch.setattr(client, "_client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client


async def _collect(client: BedrockLLMClient, usage: LLMCallContext = _CHAT, **kwargs: Any) -> list[str]:
    return [token async for token in client.generate("대본", usage=usage, **kwargs)]


_REQUEST = httpx2.Request("POST", "https://bedrock-runtime.ap-northeast-2.amazonaws.com/model/m/invoke")


def _status_error(cls: type[anthropic.APIStatusError], status: int, body: object) -> anthropic.APIStatusError:
    return cls(f"Error code: {status}", response=httpx2.Response(status, request=_REQUEST), body=body)


# ---- 스트림 ----------------------------------------------------------------------------------


async def test_generate_relays_only_text_deltas(monkeypatch: pytest.MonkeyPatch, recorded: list[Any]) -> None:
    other_delta = SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="signature_delta"))
    client, _ = _client_streaming(
        monkeypatch, _start(input_tokens=10), _text("안"), other_delta, _text(""), _text("녕"), _end()
    )

    assert await _collect(client) == ["안", "녕"]


@pytest.mark.parametrize(
    ("usage", "model_setting", "max_tokens", "timeout_seconds"),
    [
        pytest.param(_CHAT, "bedrock_sonnet_model_id", 4096, 45.0, id="chat-sonnet"),
        pytest.param(_CHAPTER, "bedrock_opus_model_id", 32_768, 300.0, id="chapter-opus"),
    ],
)
async def test_generate_maps_the_request(
    monkeypatch: pytest.MonkeyPatch,
    recorded: list[Any],
    usage: LLMCallContext,
    model_setting: str,
    max_tokens: int,
    timeout_seconds: float,
) -> None:
    """시스템 지시는 `system`, 대본은 user 메시지 하나, 정지 시퀀스 그대로, 사고는 끔. 계정을 가리키는 값은 싣지 않는다
    (처리방침 초안이 그 전제로 쓰였다)."""
    monkeypatch.setattr(settings, model_setting, "actual-model")
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    await _collect(client, usage, system_instruction="지시", stop_sequences=["\n나:"])

    (kwargs,) = seen
    assert kwargs["model"] == "actual-model"
    assert kwargs["system"] == "지시"
    assert kwargs["messages"] == [{"role": "user", "content": "대본"}]
    assert kwargs["stop_sequences"] == ["\n나:"]
    assert kwargs["max_tokens"] == max_tokens
    assert kwargs["thinking"] == {"type": "disabled"}
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == timeout_seconds
    assert "metadata" not in kwargs


async def test_generate_without_system_or_stop_sequences_sends_neither(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    await _collect(client)

    assert seen[0]["system"] is anthropic.omit
    assert seen[0]["stop_sequences"] is anthropic.omit


_SEGMENTED = SegmentedPrompt(("앞부분", "\n나: 직전\n너: 응답", "\n\n나: 지금\n너:"))


async def test_a_segmented_chat_prompt_goes_as_three_blocks_with_one_checkpoint_on_the_second(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """체크포인트는 대화 기록 끝(둘째 블록) 하나다 — 셋째 블록은 턴마다 바뀌어 캐시해도 다시 읽히지 않고, 첫째 블록 끝은
    다음 턴이 거슬러 보며 찾는 경계라 따로 표시하지 않아도 된다."""
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    [_ async for _ in client.generate(_SEGMENTED, usage=_CHAT)]

    assert seen[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "앞부분"},
                {"type": "text", "text": "\n나: 직전\n너: 응답", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "\n\n나: 지금\n너:"},
            ],
        }
    ]


_REPLAY = LLMCallContext("replay_generate", None, None, model="sonnet")


def _client_recording_each_request(monkeypatch: pytest.MonkeyPatch) -> tuple[BedrockLLMClient, list[dict[str, Any]]]:
    """요청마다 새 정상 스트림을 돌려주는 가짜 SDK — 한 클라이언트로 여러 번 불러 요청끼리 비교할 때 쓴다."""
    seen: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> AsyncIterator[Any]:
        seen.append(kwargs)

        async def stream() -> AsyncIterator[Any]:
            for event in (_start(input_tokens=1), _text("x"), _end()):
                yield event

        return stream()

    client = BedrockLLMClient()
    monkeypatch.setattr(client, "_client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client, seen


async def test_a_replayed_turn_is_sent_exactly_like_a_chat_turn_but_counted_under_its_own_label(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """지난 턴을 다시 생성해 비교하는 측정은 실제 대화와 같은 출력 상한·타임아웃·사고 설정으로 나가야 뜻이 있다. 사용량만
    따로 쌓여야 실제 대화 원가에 섞이지 않는다."""
    client, seen = _client_recording_each_request(monkeypatch)

    await _collect(client, _CHAT, system_instruction="지시", stop_sequences=["\n나:"])
    await _collect(client, _REPLAY, system_instruction="지시", stop_sequences=["\n나:"])

    chat, replayed = seen
    assert replayed == chat
    assert (replayed["max_tokens"], replayed["timeout"], replayed["thinking"]) == (4096, 45.0, {"type": "disabled"})
    assert [site for site, _, _ in recorded] == ["chat_generate", "replay_generate"]


async def test_a_replayed_segmented_turn_carries_the_same_cache_checkpoint_as_a_chat_turn(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """다시 생성하는 턴이 캐시 없이 나가면 원가·지연이 실제 대화와 달라 측정이 어긋나고, 같은 턴을 여러 번 돌릴 때 앞부분을
    매번 제값에 낸다 — 실제 턴과 같은 블록 셋·같은 체크포인트로 가야 한다."""
    client, seen = _client_recording_each_request(monkeypatch)

    [_ async for _ in client.generate(_SEGMENTED, usage=_CHAT)]
    [_ async for _ in client.generate(_SEGMENTED, usage=_REPLAY)]

    chat, replayed = (kwargs["messages"][0]["content"] for kwargs in seen)
    assert replayed == chat
    assert [block.get("cache_control") for block in replayed] == [None, {"type": "ephemeral"}, None]


@pytest.mark.parametrize(
    ("prompt", "usage", "warns"),
    [
        # 빌더는 기록이 빈 턴에 일부러 보통 문자열을 낸다. 나누지 못한 턴은 빌더가 이유와 함께 남기므로 여기서는 남기지 않는다.
        pytest.param("대본", _CHAT, False, id="chat-without-segments"),
        pytest.param(SegmentedPrompt(("앞", "뒤")), _CHAT, True, id="chat-with-two-segments"),
        pytest.param(_SEGMENTED, _CHAPTER, False, id="chapter-never-caches"),
    ],
)
async def test_other_prompts_go_as_one_plain_block_without_a_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    recorded: list[Any],
    caplog: pytest.LogCaptureFixture,
    prompt: str,
    usage: LLMCallContext,
    warns: bool,
) -> None:
    """채팅 턴이 경계 없이 오면 블록 하나로 보낸다(캐시만 못 맞는다). 경계가 있는데 모양이 셋이 아니면 로그로 드러낸다. 소설 장은 장마다 내용이 거의 다 바뀌어
    캐시 쓰기 할증만 내므로 경계가 있어도 걸지 않는다."""
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    with caplog.at_level(logging.WARNING, logger="api.llm.bedrock"):
        [_ async for _ in client.generate(prompt, usage=usage)]

    content = seen[0]["messages"][0]["content"]
    assert type(content) is str and content == prompt
    assert any("캐시 경계" in r.getMessage() for r in caplog.records) is warns


async def test_a_refusal_is_a_policy_violation_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end("refusal"))

    with pytest.raises(LLMPolicyViolationError) as exc_info:
        await _collect(client)
    assert exc_info.value.provider == "bedrock"
    assert recorded == []


async def test_a_chat_cut_off_at_the_cap_is_logged_and_returned(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("말을 하다"), _end("max_tokens"))

    with caplog.at_level(logging.WARNING, logger="api.llm.bedrock"):
        assert await _collect(client) == ["말을 하다"]

    # 로거 이름까지 본다 — 공용 모듈의 로거로 남기면 문구는 같아도 `api.llm.bedrock` 로 거르던 검색에서 빠진다.
    assert any(r.name == "api.llm.bedrock" and "max_tokens(4096)" in r.getMessage() for r in caplog.records)
    assert len(recorded) == 1


async def test_a_chapter_cut_off_at_the_cap_fails_after_recording_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("장"), _end("max_tokens"))

    with pytest.raises(LLMTruncatedError) as exc_info:
        await _collect(client, _CHAPTER)
    assert exc_info.value.provider == "bedrock"
    assert len(recorded) == 1


@pytest.mark.parametrize("texts", [pytest.param([], id="no-text"), pytest.param([" \n"], id="whitespace")])
async def test_an_empty_chapter_fails_after_recording_usage_but_an_empty_chat_ends_normally(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], texts: list[str]
) -> None:
    events = [_start(input_tokens=1), *(_text(t) for t in texts), _end()]

    chapter, _ = _client_streaming(monkeypatch, *events)
    with pytest.raises(LLMEmptyResponseError):
        await _collect(chapter, _CHAPTER)
    assert len(recorded) == 1

    chat, _ = _client_streaming(monkeypatch, *events)
    assert "".join(await _collect(chat)).strip() == ""
    assert len(recorded) == 2


# ---- 사용량 ----------------------------------------------------------------------------------


async def test_usage_maps_cache_reads_and_writes_onto_the_gemini_metrics(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Anthropic 의 `input_tokens` 는 캐시 읽기·쓰기를 뺀 값이고 Gemini 의 입력은 캐시를 포함한다 — 같은 열에서 원가를
    내려면 입력을 셋의 합으로 올린다. 출력은 마지막 `message_delta` 의 누적값이다."""
    monkeypatch.setattr(settings, "bedrock_sonnet_model_id", "sonnet-actual")
    client, _ = _client_streaming(
        monkeypatch, _start(input_tokens=100, read=1000, write=200, output=1), _text("x"), _end(output=50)
    )

    with caplog.at_level(logging.WARNING, logger="api.llm.bedrock"):
        await _collect(client)

    ((call_site, model, meta),) = recorded
    assert (call_site, model) == ("chat_generate", "sonnet-actual")
    assert (
        meta.prompt_token_count,
        meta.cached_content_token_count,
        meta.cache_write_token_count,
        meta.candidates_token_count,
        meta.thoughts_token_count,
        meta.total_token_count,
    ) == (1300, 1000, 200, 50, 0, 1350)
    assert "bedrock_usage call_site=chat_generate model=sonnet-actual prompt_tokens=1300" in caplog.text
    assert "gemini_usage" not in caplog.text


async def test_usage_without_cache_fields_counts_them_as_zero(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=7), _text("x"), _end(output=3))

    await _collect(client)

    meta = recorded[0][2]
    assert (meta.prompt_token_count, meta.cached_content_token_count, meta.cache_write_token_count) == (7, 0, 0)
    assert meta.total_token_count == 10


async def test_a_stream_without_message_start_records_missing_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = _client_streaming(monkeypatch, _text("x"), _end())

    with caplog.at_level(logging.WARNING, logger="api.llm.bedrock"):
        await _collect(client)

    assert recorded[0][2] is None
    assert "usage=missing" in caplog.text


async def test_usage_is_not_recorded_when_the_stream_fails_or_is_abandoned(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    failing, _ = _client_streaming(
        monkeypatch, _start(input_tokens=1), _text("x"), raise_at=httpx2.ReadTimeout("read timed out")
    )
    with pytest.raises(LLMClientError):
        await _collect(failing)

    abandoned, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("a"), _text("b"), _end())
    stream = abandoned.generate("대본", usage=_CHAT)
    assert await anext(stream) == "a"
    await stream.aclose()  # type: ignore[attr-defined]

    assert recorded == []


async def test_a_usage_logging_failure_does_not_break_the_stream(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    def explode(*_: Any, **__: Any) -> None:
        raise RuntimeError("logging broke")

    monkeypatch.setattr(bedrock_module.logger, "warning", explode)
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    assert await _collect(client) == ["x"]
    assert len(recorded) == 1


# ---- 실패 매핑 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_status_error(anthropic.RateLimitError, 429, None), id="http-429"),
        pytest.param(
            _status_error(
                anthropic.APIStatusError,
                200,
                {"type": "error", "error": {"type": "throttlingException", "message": "Too many requests"}},
            ),
            id="throttling-error-body",
        ),
    ],
)
async def test_throttling_is_a_rate_limit_error(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    client = _client_failing_on_create(monkeypatch, exc)

    with pytest.raises(LLMRateLimitError) as exc_info:
        await _collect(client)
    assert exc_info.value.provider == "bedrock"
    assert _llm_dependency_tag(exc_info.value) == "bedrock_rate_limit"


async def test_throttling_after_some_text_is_a_rate_limit_error_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    throttled = _status_error(
        anthropic.APIStatusError,
        200,
        {"type": "error", "error": {"type": "throttlingException", "message": "Too many tokens"}},
    )
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("말을"), raise_at=throttled)
    received: list[str] = []

    with pytest.raises(LLMRateLimitError) as exc_info:
        async for token in client.generate("대본", usage=_CHAT):
            received.append(token)

    assert received == ["말을"]
    assert exc_info.value.provider == "bedrock"
    assert recorded == []


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_status_error(anthropic.BadRequestError, 400, None), id="http-400"),
        pytest.param(_status_error(anthropic.PermissionDeniedError, 403, None), id="http-403"),
        pytest.param(_status_error(anthropic.InternalServerError, 500, None), id="http-500"),
        pytest.param(anthropic.APIConnectionError(request=_REQUEST), id="connection"),
        pytest.param(anthropic.APITimeoutError(request=_REQUEST), id="sdk-timeout"),
        pytest.param(httpx2.ReadTimeout("read timed out"), id="httpx2-read-timeout"),
        pytest.param(httpx.ReadTimeout("read timed out"), id="httpx-read-timeout"),
        pytest.param(TimeoutError(), id="bare-timeout"),
        # 요청 서명 단계 — SDK 가 감싸지 않는다. 프로세스 env 의 `AWS_PROFILE` 이 없는 프로필을 가리키면 이것이 난다.
        pytest.param(botocore.exceptions.ProfileNotFound(profile="missing"), id="botocore-signing"),
        # 응답 event-stream 디코딩 단계 — 깨진 프레임. 역시 SDK 가 감싸지 않는다.
        pytest.param(botocore.eventstream.ChecksumMismatch(1, 2), id="eventstream-decoding"),
    ],
)
@pytest.mark.parametrize("where", ["create", "mid-stream"])
async def test_other_failures_are_plain_client_errors(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], exc: BaseException, where: str
) -> None:
    """SDK·네트워크 예외가 그대로 새면 SSE 제너레이터를 뚫어 요청 스코프 DB 세션이 강제 종료된다 — 전부
    `LLMClientError` 로 바꾼다."""
    if where == "create":
        client = _client_failing_on_create(monkeypatch, exc)
    else:
        client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), raise_at=exc)

    with pytest.raises(LLMClientError) as exc_info:
        await _collect(client)

    assert not isinstance(exc_info.value, LLMRateLimitError)
    assert exc_info.value.provider == "bedrock"
    assert _llm_dependency_tag(exc_info.value) == "bedrock"
    assert recorded == []


@pytest.mark.parametrize(
    ("exc", "mapped"),
    [
        pytest.param(_status_error(anthropic.RateLimitError, 429, None), LLMRateLimitError, id="throttled"),
        pytest.param(botocore.exceptions.ProfileNotFound(profile="missing"), LLMClientError, id="botocore-signing"),
    ],
)
async def test_a_mapped_failure_keeps_the_original_exception_as_its_cause(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], exc: BaseException, mapped: type[LLMClientError]
) -> None:
    """바꾼 예외는 원래 SDK·botocore 예외를 직접 원인(`__cause__`)으로 쥔다(Anthropic 구현과 같은 규칙) — 추적이 "처리
    중에 또 다른 오류가 났다"가 아니라 "이 예외에서 바꿨다"로 읽힌다."""
    client = _client_failing_on_create(monkeypatch, exc)

    with pytest.raises(mapped) as exc_info:
        await _collect(client)

    assert exc_info.value.__cause__ is exc


# ---- SDK 클라이언트 생성 ---------------------------------------------------------------------


@pytest.mark.parametrize("field", ["bedrock_access_key_id", "bedrock_secret_access_key", "bedrock_region"])
async def test_an_empty_credential_fails_before_building_the_sdk_client(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """빈 키로 SDK 를 만들면 boto3 기본 체인이 R2 의 `AWS_*` 키로 서명한다 — 만들기 전에 막는다."""
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(bedrock_module, "AsyncAnthropicBedrock", lambda **kwargs: built.append(kwargs))
    monkeypatch.setattr(settings, field, " ")

    with pytest.raises(LLMClientError) as exc_info:
        await _collect(BedrockLLMClient())

    assert exc_info.value.provider == "bedrock"
    assert built == []


async def test_the_sdk_client_gets_explicit_credentials_and_no_retries(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    built: list[dict[str, Any]] = []

    async def create(**_: Any) -> AsyncIterator[Any]:
        async def stream() -> AsyncIterator[Any]:
            yield _end()

        return stream()

    def fake_sdk(**kwargs: Any) -> Any:
        built.append(kwargs)
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    monkeypatch.setattr(bedrock_module, "AsyncAnthropicBedrock", fake_sdk)
    client = BedrockLLMClient()

    await _collect(client)
    await _collect(client)

    assert built == [
        {
            "aws_access_key": "AKIATEST",
            "aws_secret_key": "secret-test",
            "aws_region": "ap-northeast-2",
            "max_retries": 0,
            "timeout": settings.bedrock_chat_timeout_ms / 1000,
        }
    ]


async def test_a_bearer_token_in_the_env_is_a_client_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """프로세스 env 에 `AWS_BEARER_TOKEN_BEDROCK` 가 있으면 SDK 가 명시 키와 함께 `ValueError` 를 낸다."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "token")

    with pytest.raises(LLMClientError):
        await _collect(BedrockLLMClient())


# ---- 실제 SDK 를 거친 요청 -------------------------------------------------------------------


def _sdk_backed(monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, Any]) -> tuple[BedrockLLMClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    sdk = anthropic.AsyncAnthropicBedrock(
        aws_access_key="AKIATEST",
        aws_secret_key="secret-test",
        aws_region="ap-northeast-2",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    client = BedrockLLMClient()
    monkeypatch.setattr(client, "_client", sdk)
    return client, seen


async def test_the_request_reaches_the_wire_in_bedrock_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """가짜 SDK 로는 SDK 가 인자를 실제로 어떻게 싣는지 모른다 — 엔드포인트·서명·본문을 실제 SDK 로 본다."""
    client, seen = _sdk_backed(monkeypatch, 400, {"message": "bad request"})

    with pytest.raises(LLMClientError):
        await _collect(client, system_instruction="지시", stop_sequences=["\n나:"])

    (request,) = seen
    assert request.url.host == "bedrock-runtime.ap-northeast-2.amazonaws.com"
    assert request.url.path == "/model/global.anthropic.claude-sonnet-4-6/invoke-with-response-stream"
    assert "Credential=AKIATEST/" in request.headers["authorization"]
    body = json.loads(request.content)
    assert body["system"] == "지시"
    assert body["messages"] == [{"role": "user", "content": "대본"}]
    assert body["stop_sequences"] == ["\n나:"]
    assert body["max_tokens"] == 4096
    assert body["thinking"] == {"type": "disabled"}
    assert "metadata" not in body


async def test_cache_blocks_reach_the_wire_through_the_real_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    client, seen = _sdk_backed(monkeypatch, 400, {"message": "bad request"})

    with pytest.raises(LLMClientError):
        [_ async for _ in client.generate(_SEGMENTED, usage=_CHAT)]

    blocks = json.loads(seen[0].content)["messages"][0]["content"]
    assert [b["text"] for b in blocks] == list(_SEGMENTED.segments)
    assert [b.get("cache_control") for b in blocks] == [None, {"type": "ephemeral"}, None]


async def test_a_429_through_the_real_sdk_is_a_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client, seen = _sdk_backed(monkeypatch, 429, {"message": "Too many requests"})

    with pytest.raises(LLMRateLimitError):
        await _collect(client)
    assert len(seen) == 1  # 재시도하지 않는다


def _event_stream_frame(headers: dict[str, str], payload: bytes) -> bytes:
    """AWS event-stream 프레임 하나. 전체 길이·헤더 길이·프렐류드 CRC, 문자열 헤더들(이름 길이 1바이트, 값 타입 7,
    값 길이 2바이트), 본문, 메시지 CRC 순서다."""
    encoded = b"".join(
        struct.pack(">B", len(name.encode()))
        + name.encode()
        + b"\x07"
        + struct.pack(">H", len(value.encode()))
        + value.encode()
        for name, value in headers.items()
    )
    prelude = struct.pack(">II", 12 + len(encoded) + len(payload) + 4, len(encoded))
    prelude += struct.pack(">I", binascii.crc32(prelude))
    message = prelude + encoded + payload
    return message + struct.pack(">I", binascii.crc32(message))


def _chunk_frame(event: dict[str, Any]) -> bytes:
    payload = {"bytes": base64.b64encode(json.dumps(event).encode()).decode()}
    return _event_stream_frame(
        {":event-type": "chunk", ":content-type": "application/json", ":message-type": "event"},
        json.dumps(payload).encode(),
    )


async def test_a_throttling_frame_mid_stream_through_the_real_sdk_is_a_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """스트림 도중의 스로틀은 HTTP 상태가 이미 200 이라 event-stream 의 예외 프레임으로만 온다. 진짜 SDK 의 디코더가
    그 프레임을 오류 본문으로 바꾼 것을 스로틀로 알아보는지 본다 — SDK 가 프레임을 옮기는 모양이 바뀌면 여기서 드러난다."""
    body = (
        _chunk_frame(
            {
                "type": "message_start",
                "message": {
                    "id": "msg",
                    "type": "message",
                    "role": "assistant",
                    "model": "m",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            }
        )
        + _chunk_frame({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        + _chunk_frame({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "말을"}})
        + _event_stream_frame(
            {
                ":exception-type": "throttlingException",
                ":content-type": "application/json",
                ":message-type": "exception",
            },
            json.dumps({"message": "Too many tokens, please wait"}).encode(),
        )
    )
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(200, headers={"content-type": "application/vnd.amazon.eventstream"}, content=body)
    )
    client = BedrockLLMClient()
    monkeypatch.setattr(
        client,
        "_client",
        anthropic.AsyncAnthropicBedrock(
            aws_access_key="AKIATEST",
            aws_secret_key="secret-test",
            aws_region="ap-northeast-2",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=transport),
        ),
    )
    received: list[str] = []

    with pytest.raises(LLMRateLimitError) as exc_info:
        async for token in client.generate("대본", usage=_CHAT):
            received.append(token)

    assert received == ["말을"]
    assert exc_info.value.provider == "bedrock"
    assert recorded == []
