import json
import logging
from datetime import datetime
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, get_args

import httpx
import pytest
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from api.core.config import Settings, settings
from api.llm.client import (
    LLMCallContext,
    LLMCallSite,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
)
from api.llm.gemini import GeminiLLMClient


class _JudgmentResult(BaseModel):
    triggered: bool
    ending_id: str | None


_USAGE = LLMCallContext(call_site="chat_generate", user_id=None, room_id=None)


def _make_client(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> GeminiLLMClient:
    client = GeminiLLMClient(api_key="test-key")
    fake_client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(**overrides)))
    monkeypatch.setattr(client, "_client", fake_client)
    return client


async def _chunks(*texts: str) -> AsyncIterator[SimpleNamespace]:
    for text in texts:
        yield SimpleNamespace(text=text)


def _api_error(code: int = 503) -> genai_errors.APIError:
    return genai_errors.APIError(code=code, response_json={"error": {"message": "unavailable"}})


async def test_generate_relays_stream_chunks_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        return _chunks("Hello", ", ", "world")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    tokens = [token async for token in client.generate("hi", usage=_USAGE)]

    assert tokens == ["Hello", ", ", "world"]


async def test_generate_skips_empty_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        return _chunks("a", "", "b")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    tokens = [token async for token in client.generate("hi", usage=_USAGE)]

    assert tokens == ["a", "b"]


async def test_generate_wraps_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        raise _api_error()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMClientError) as exc_info:
        async for _ in client.generate("hi", usage=_USAGE):
            pass
    # 429가 아닌 APIError(여기선 503)는 쿼터 소진과 섞이면 안 된다.
    assert not isinstance(exc_info.value, LLMRateLimitError)


async def test_generate_wraps_429_api_error_as_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """429(쿼터 소진)는 다른 APIError와 구분되는 타입으로 올라가야
    승격된 이벤트가 행동 가능하다 — 사용자에게 보이는 동작(LLMClientError로 흡수)은 그대로다."""

    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        raise _api_error(code=429)

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMRateLimitError):
        async for _ in client.generate("hi", usage=_USAGE):
            pass


async def test_generate_wraps_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        raise httpx.ConnectTimeout("timed out")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMClientError) as exc_info:
        async for _ in client.generate("hi", usage=_USAGE):
            pass
    # 함정: httpx.HTTPError에는 `.code`가 없다 — isinstance 가드
    # 없이 접근하면 AttributeError가 원래 예외를 가린다. 이 pytest.raises(LLMClientError)가
    # 이미 그 함정을 잡는다(AttributeError면 여기서 안 잡혀 테스트가 실패한다).
    assert not isinstance(exc_info.value, LLMRateLimitError)


async def test_generate_raises_policy_violation_on_blocked_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        async def _iter() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                text=None,
                prompt_feedback=genai_types.GenerateContentResponsePromptFeedback(
                    block_reason=genai_types.BlockedReason.SAFETY
                ),
                candidates=None,
            )

        return _iter()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMPolicyViolationError):
        async for _ in client.generate("hi", usage=_USAGE):
            pass


async def test_generate_raises_policy_violation_on_blocked_output(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        async def _iter() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(text="some ", prompt_feedback=None, candidates=None)
            yield SimpleNamespace(
                text=None,
                prompt_feedback=None,
                candidates=[genai_types.Candidate(finish_reason=genai_types.FinishReason.SAFETY)],
            )

        return _iter()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    tokens: list[str] = []
    with pytest.raises(LLMPolicyViolationError):
        async for token in client.generate("hi", usage=_USAGE):
            tokens.append(token)

    assert tokens == ["some "]


async def test_generate_structured_returns_deserialized_model(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _JudgmentResult(triggered=True, ending_id="ending-1")

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=expected)

    client = _make_client(monkeypatch, generate_content=generate_content)

    result = await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE)

    assert result == expected


async def test_generate_structured_raises_when_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=None)

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMClientError) as exc_info:
        await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE)

    # 차단 표시가 없는 파싱 실패는 평범한 실패다 — 하위 타입(정책 차단)으로 올라가면 발행이 그것을 안전 기준
    # 거부로 안내해 버린다.
    assert type(exc_info.value) is LLMClientError


@pytest.mark.parametrize(
    ("prompt_feedback", "candidates"),
    [
        pytest.param(
            genai_types.GenerateContentResponsePromptFeedback(block_reason=genai_types.BlockedReason.IMAGE_SAFETY),
            None,
            id="blocked-prompt",
        ),
        pytest.param(
            None,
            [genai_types.Candidate(finish_reason=genai_types.FinishReason.PROHIBITED_CONTENT)],
            id="blocked-output",
        ),
    ],
)
async def test_generate_structured_raises_policy_violation_when_gemini_blocks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    prompt_feedback: object,
    candidates: object,
) -> None:
    """안전 차단은 응답에 본문이 없어 파싱 실패로 보인다. 차단 표시가 있으면 정책 위반으로 갈라 올려야 발행이
    작가에게 이의제기할 수 있는 거부로 돌려줄 수 있다. 토큰은 이미 과금됐으므로 사용량은 그대로 한 줄 찍는다."""
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            parsed=None, prompt_feedback=prompt_feedback, candidates=candidates, usage_metadata=_usage(9, 0, None, 9)
        )

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMPolicyViolationError):
        await client.generate_structured("judge this", _JudgmentResult, usage=_CTX)

    assert len(_usage_records(caplog)) == 1


async def test_generate_structured_returns_parsed_result_even_with_block_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """차단 표시는 파싱에 실패했을 때만 본다 — 판정·심사가 파싱해 낸 결과는 지금처럼 그대로 돌려준다."""
    expected = _JudgmentResult(triggered=False, ending_id=None)

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            parsed=expected,
            prompt_feedback=genai_types.GenerateContentResponsePromptFeedback(
                block_reason=genai_types.BlockedReason.SAFETY
            ),
            candidates=[genai_types.Candidate(finish_reason=genai_types.FinishReason.SAFETY)],
        )

    client = _make_client(monkeypatch, generate_content=generate_content)

    assert await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE) == expected


async def test_generate_structured_wraps_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        raise _api_error()

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMClientError) as exc_info:
        await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE)
    assert not isinstance(exc_info.value, LLMRateLimitError)


async def test_generate_structured_wraps_429_api_error_as_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`generate()`와 대칭을 유지해야 하는 판단 호출 쪽(스탯/엔딩
    판정 등)도 429를 구분해야 한다."""

    async def generate_content(**_: Any) -> SimpleNamespace:
        raise _api_error(code=429)

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMRateLimitError):
        await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE)


async def test_generate_structured_wraps_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """함정: `generate_structured()`의 except 절도 `generate()`와
    같은 `(APIError, httpx.HTTPError)` 튜플을 쓴다 — httpx 쪽은 `.code`가 없어 가드 없이
    접근하면 AttributeError가 원래 예외를 가린다."""

    async def generate_content(**_: Any) -> SimpleNamespace:
        raise httpx.ConnectTimeout("timed out")

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMClientError) as exc_info:
        await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE)
    assert not isinstance(exc_info.value, LLMRateLimitError)


async def test_generate_structured_without_images_sends_plain_string_contents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _JudgmentResult(triggered=True, ending_id=None)
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return SimpleNamespace(parsed=expected)

    client = _make_client(monkeypatch, generate_content=generate_content)

    await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE)

    assert received["contents"] == "judge this"


async def test_generate_structured_with_images_sends_multimodal_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _JudgmentResult(triggered=True, ending_id=None)
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return SimpleNamespace(parsed=expected)

    client = _make_client(monkeypatch, generate_content=generate_content)

    await client.generate_structured(
        "judge this",
        _JudgmentResult,
        images=[(b"fake-png-bytes", "image/png"), (b"fake-jpeg-bytes", "image/jpeg")],
        usage=_USAGE,
    )

    contents = received["contents"]
    assert contents[0] == "judge this"
    assert len(contents) == 3
    assert contents[1].inline_data.data == b"fake-png-bytes"
    assert contents[1].inline_data.mime_type == "image/png"
    assert contents[2].inline_data.data == b"fake-jpeg-bytes"
    assert contents[2].inline_data.mime_type == "image/jpeg"


async def test_generate_sends_a_runaway_backstop_and_forwards_the_stop_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """대화 생성에는 오랫동안 `GenerateContentConfig` 가 전혀 붙지 않아 출력 상한이 없었다 —
    폭주 응답에 천장이 없는 구조였다. `stop_sequences`는 이제 호출부가 화자 라벨에서
    파생시켜 넘긴다 — 이 계층은 그 값을 그대로
    `GenerateContentConfig`에 전달하는지만 본다(넘기지 않으면 `None`)."""
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    assert [token async for token in client.generate("hi", stop_sequences=["\n사용자:"], usage=_USAGE)] == ["네"]

    config = captured["config"]
    assert config.max_output_tokens == settings.gemini_max_output_tokens
    assert config.stop_sequences == ["\n사용자:"]
    # 상한이 설정에서 온다는 것까지 봐야 한다 — 리터럴을 그대로 두면 값을 올린 커밋이
    # 테스트만 깨고 배선이 끊긴 것은 못 잡는다(사고형 모델에서는 이 값이 절단을 가른다).
    monkeypatch.setattr(settings, "gemini_max_output_tokens", 4242)
    assert [token async for token in client.generate("hi", stop_sequences=["\n사용자:"], usage=_USAGE)] == ["네"]

    assert [token async for token in client.generate("hi", usage=_USAGE)] == ["네"]
    assert captured["config"].stop_sequences is None
    assert captured["config"].max_output_tokens == 4242


async def test_generate_forwards_the_system_instruction_to_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """바닥 지시문은 프롬프트 본문이 아니라 `system_instruction` 으로 가야 한다 — 본문에 이어
    붙이면 작품 설정과 같은 층에 놓여 우선순위(수위 항목이 작품 설정을 이긴다)가 사라진다.
    넘기지 않으면 None 이 그대로 실려 예전 호출 페이로드와 같아야 한다."""
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    assert [token async for token in client.generate("hi", "너는 화자다", usage=_USAGE)] == ["네"]
    assert captured["config"].system_instruction == "너는 화자다"
    assert captured["contents"] == "hi", "지시문이 프롬프트 본문에 섞이면 안 된다"

    assert [token async for token in client.generate("hi", usage=_USAGE)] == ["네"]
    assert captured["config"].system_instruction is None


async def test_generate_omits_seed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gemini_seed` 기본값 None 이면 config.seed 가 아예 안 실려야 한다(호출 페이로드가
    지금과 동일해야 하는 것이 이 필드의 성공 기준)."""
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)
    monkeypatch.setattr(settings, "gemini_seed", None)

    assert [token async for token in client.generate("hi", usage=_USAGE)] == ["네"]
    assert captured["config"].seed is None


async def test_generate_sets_seed_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)
    monkeypatch.setattr(settings, "gemini_seed", 42)

    assert [token async for token in client.generate("hi", usage=_USAGE)] == ["네"]
    assert captured["config"].seed == 42


async def test_generate_logs_when_the_response_is_cut_off_at_the_token_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """상한에 걸리면 문장 중간에서 잘린 응답이 그대로 사용자에게 간다 — 화면상으로는 그냥
    "말을 하다 말았다"로만 보이므로, 상한이 너무 낮은지 판단할 근거를 로그에 남겨야 한다."""

    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        async def stream() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                text="말을 하다",
                candidates=[SimpleNamespace(finish_reason=genai_types.FinishReason.MAX_TOKENS)],
            )

        return stream()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)
    warnings: list[str] = []
    monkeypatch.setattr(
        "api.llm.gemini.logger",
        SimpleNamespace(warning=lambda message, *args: warnings.append(message % args)),
    )

    tokens = [token async for token in client.generate("hi", usage=_USAGE)]

    assert tokens == ["말을 하다"]
    # 같은 logger로 `gemini_usage` 줄도 1줄 들어온다 — 그 줄을 따로 세고, 잘림 경고가
    # 정확히 한 번이라는 원래 단언은 그대로 유지한다.
    usage_lines = [w for w in warnings if w.startswith("gemini_usage ")]
    assert len(usage_lines) == 1
    assert [w for w in warnings if not w.startswith("gemini_usage ")] == [
        f"Gemini 응답이 max_output_tokens({settings.gemini_max_output_tokens})에서 잘렸다"
    ]


# --- `gemini_usage` 토큰 사용량 로그 -------------------------------------------------------------

_PROMPT_SENTINEL = "PROMPT-SENTINEL-7f3a"
_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_ROOM_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_CTX = LLMCallContext(call_site="chat_stat_judgment", user_id=_USER_ID, room_id=_ROOM_ID)


def _usage(
    prompt: int, candidates: int, thoughts: int | None, total: int, *, cached: int | None = None
) -> SimpleNamespace:
    # 암시 캐시가 적중하지 않으면 SDK는 cached_content_token_count 를 None 으로 준다(기본값).
    return SimpleNamespace(
        prompt_token_count=prompt,
        cached_content_token_count=cached,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        total_token_count=total,
    )


def _usage_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith("gemini_usage ")]


def _fields(record: logging.LogRecord) -> dict[str, str]:
    return dict(part.split("=", 1) for part in record.getMessage().split()[1:])


def _stream_of(*chunks: SimpleNamespace) -> Any:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        async def _iter() -> AsyncIterator[SimpleNamespace]:
            for chunk in chunks:
                yield chunk

        return _iter()

    return generate_content_stream


async def test_generate_logs_gemini_usage_once_from_last_chunk_metadata(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")
    client = _make_client(
        monkeypatch,
        generate_content_stream=_stream_of(
            SimpleNamespace(text="RESPONSE-SENTINEL-a"),
            SimpleNamespace(text="b", usage_metadata=None),
            SimpleNamespace(text="c", usage_metadata=_usage(11, 22, 3, 36, cached=8)),
        ),
    )

    tokens = [t async for t in client.generate(f"hi {_PROMPT_SENTINEL}", usage=_CTX)]

    assert tokens == ["RESPONSE-SENTINEL-a", "b", "c"]
    records = _usage_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert _fields(records[0]) == {
        "call_site": "chat_stat_judgment",
        "model": client._model_name,
        "prompt_tokens": "11",
        "cached_content_tokens": "8",
        "candidates_tokens": "22",
        "thoughts_tokens": "3",
        "total_tokens": "36",
        "user_id": str(_USER_ID),
        "room_id": str(_ROOM_ID),
    }
    assert all(_PROMPT_SENTINEL not in r.getMessage() for r in caplog.records)
    assert all("RESPONSE-SENTINEL" not in r.getMessage() for r in caplog.records)


async def test_generate_logs_the_last_non_none_usage_metadata(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """메타데이터가 마지막 청크에만 온다고 가정하지 않는다 — 마지막으로 본 비-None 값을 쓴다."""
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")
    client = _make_client(
        monkeypatch,
        generate_content_stream=_stream_of(
            SimpleNamespace(text="a", usage_metadata=_usage(1, 1, None, 2)),
            SimpleNamespace(text="b", usage_metadata=_usage(5, 7, None, 12)),
            SimpleNamespace(text="c", usage_metadata=None),
        ),
    )

    assert [t async for t in client.generate("hi", usage=_CTX)] == ["a", "b", "c"]

    records = _usage_records(caplog)
    assert len(records) == 1
    fields = _fields(records[0])
    assert (fields["prompt_tokens"], fields["candidates_tokens"], fields["total_tokens"]) == ("5", "7", "12")
    assert fields["thoughts_tokens"] == "None"
    # 캐시 미적중(None)도 필드는 찍힌다 — 없는 필드와 미적중을 로그에서 구분할 수 있어야 한다.
    assert fields["cached_content_tokens"] == "None"
    assert "usage=missing" not in records[0].getMessage()


async def test_generate_logs_usage_missing_when_no_chunk_has_metadata(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")
    client = _make_client(monkeypatch, generate_content_stream=_stream_of(SimpleNamespace(text="a")))
    preview = LLMCallContext(call_site="preview_generate", user_id=_USER_ID, room_id=None)

    assert [t async for t in client.generate("hi", usage=preview)] == ["a"]

    records = _usage_records(caplog)
    assert len(records) == 1
    fields = _fields(records[0])
    assert fields["usage"] == "missing"
    assert fields["call_site"] == "preview_generate"
    assert fields["room_id"] == "None"
    assert [
        fields[k]
        for k in ("prompt_tokens", "cached_content_tokens", "candidates_tokens", "thoughts_tokens", "total_tokens")
    ] == ["None"] * 5


async def test_generate_does_not_log_usage_when_the_stream_ends_in_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """정책 차단·SDK 예외로 끝난 스트림은 찍지 않는다(과소 집계)."""
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")
    blocked = _make_client(
        monkeypatch,
        generate_content_stream=_stream_of(
            SimpleNamespace(text="x", usage_metadata=_usage(1, 1, None, 2)),
            SimpleNamespace(
                text=None,
                prompt_feedback=None,
                candidates=[genai_types.Candidate(finish_reason=genai_types.FinishReason.SAFETY)],
            ),
        ),
    )
    with pytest.raises(LLMPolicyViolationError):
        async for _ in blocked.generate("hi", usage=_CTX):
            pass

    async def failing(**_: Any) -> AsyncIterator[SimpleNamespace]:
        raise _api_error()

    errored = _make_client(monkeypatch, generate_content_stream=failing)
    with pytest.raises(LLMClientError):
        async for _ in errored.generate("hi", usage=_CTX):
            pass

    assert _usage_records(caplog) == []


class _ExplodingUsage:
    @property
    def prompt_token_count(self) -> int:
        raise RuntimeError("boom")


async def test_generate_usage_logging_failure_does_not_break_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSE 제너레이터 본문을 뚫는 예외는 풀을 오염시킨다(apps/api/CLAUDE.md §SSE) — 로깅은
    어떤 이유로 실패해도 스트림을 깨면 안 된다. (a) 메타데이터 필드 접근 실패 (b) logger 자체 실패."""
    client = _make_client(
        monkeypatch,
        generate_content_stream=_stream_of(
            SimpleNamespace(text="a"), SimpleNamespace(text="b", usage_metadata=_ExplodingUsage())
        ),
    )
    assert [t async for t in client.generate("hi", usage=_CTX)] == ["a", "b"]

    calls: list[str] = []

    def raising_warning(message: str, *_: Any, **__: Any) -> None:
        calls.append(message)
        raise RuntimeError("logger down")

    monkeypatch.setattr("api.llm.gemini.logger", SimpleNamespace(warning=raising_warning))
    client = _make_client(
        monkeypatch,
        generate_content_stream=_stream_of(SimpleNamespace(text="c", usage_metadata=_usage(1, 1, None, 2))),
    )
    assert [t async for t in client.generate("hi", usage=_CTX)] == ["c"]
    # 로깅 경로를 실제로 탔는지(안 탔으면 이 테스트는 아무것도 증명하지 않는다).
    assert [m for m in calls if m.startswith("gemini_usage ")] != []


async def test_generate_structured_logs_gemini_usage(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")
    expected = _JudgmentResult(triggered=False, ending_id=None)

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=expected, usage_metadata=_usage(40, 5, 17, 62, cached=32))

    client = _make_client(monkeypatch, generate_content=generate_content)
    publish = LLMCallContext(call_site="publish_filter_story", user_id=_USER_ID, room_id=None)

    result = await client.generate_structured(f"judge {_PROMPT_SENTINEL}", _JudgmentResult, usage=publish)

    assert result == expected
    records = _usage_records(caplog)
    assert len(records) == 1
    assert _fields(records[0]) == {
        "call_site": "publish_filter_story",
        "model": client._model_name,
        "prompt_tokens": "40",
        "cached_content_tokens": "32",
        "candidates_tokens": "5",
        "thoughts_tokens": "17",
        "total_tokens": "62",
        "user_id": str(_USER_ID),
        "room_id": "None",
    }
    assert all(_PROMPT_SENTINEL not in r.getMessage() for r in caplog.records)


async def test_generate_structured_logs_usage_even_when_the_response_is_unparseable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """파싱 실패여도 토큰은 이미 과금됐다 — 사용량은 찍고 나서 실패를 올린다."""
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=None, usage_metadata=_usage(9, 0, None, 9))

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMClientError):
        await client.generate_structured("judge", _JudgmentResult, usage=_CTX)

    records = _usage_records(caplog)
    assert len(records) == 1
    assert _fields(records[0])["total_tokens"] == "9"


async def test_generate_structured_usage_missing_and_logging_failure_do_not_raise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")
    expected = _JudgmentResult(triggered=True, ending_id=None)

    async def no_metadata(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=expected)

    client = _make_client(monkeypatch, generate_content=no_metadata)
    assert await client.generate_structured("judge", _JudgmentResult, usage=_CTX) == expected
    records = _usage_records(caplog)
    assert len(records) == 1
    assert _fields(records[0])["usage"] == "missing"

    async def exploding(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=expected, usage_metadata=_ExplodingUsage())

    client = _make_client(monkeypatch, generate_content=exploding)
    assert await client.generate_structured("judge", _JudgmentResult, usage=_CTX) == expected


# ── call_site 로 고르는 구조화 호출 모델, 사용량 집계 ─────────────────────────────────

_STAT_SITES = ("chat_stat_judgment", "preview_stat_judgment")
_ENDING_SITES = ("chat_ending_judgment", "preview_ending_judgment", "replay_ending_judgment")
_IMAGE_SITES = (
    "chat_situational_image",
    "chat_media_book_image",
    "preview_media_book_image",
    "replay_media_book_image",
)
_JUDGMENT_SITES = _STAT_SITES + _ENDING_SITES + _IMAGE_SITES
_PUBLISH_FILTER_SITES = ("publish_filter_character", "publish_filter_story")
# 판정·심사가 아닌 구조화 호출 — 어느 스위치에도 끌려가면 안 된다.
_OTHER_STRUCTURED_SITES = ("chat_memory_summary", "seed_story_generate", "seed_similarity_review")
_ALL_STRUCTURED_SITES = _JUDGMENT_SITES + _PUBLISH_FILTER_SITES + _OTHER_STRUCTURED_SITES
# 설정 이름 → 그 설정을 따라가야 하는 call_site.
_MODEL_SWITCHES = {
    "gemini_stat_judgment_model_name": _STAT_SITES,
    "gemini_ending_judgment_model_name": _ENDING_SITES,
    "gemini_image_judgment_model_name": _IMAGE_SITES,
    "gemini_publish_filter_model_name": _PUBLISH_FILTER_SITES,
}


def _clear_model_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _MODEL_SWITCHES:
        monkeypatch.setattr(settings, name, None)


def _capture_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[GeminiLLMClient, list[dict[str, Any]], list[tuple[str, str]]]:
    """`generate_content` 에 넘어간 인자와 사용량 기록(call_site, model)을 함께 모은다."""
    sent: list[dict[str, Any]] = []
    recorded: list[tuple[str, str]] = []

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        sent.append(kwargs)
        return SimpleNamespace(parsed=_JudgmentResult(triggered=False, ending_id=None))

    async def fake_record(call_site: str, model: str, _usage_metadata: object | None) -> None:
        recorded.append((call_site, model))

    monkeypatch.setattr("api.llm.gemini.record_usage", fake_record)
    client = GeminiLLMClient(api_key="test-key", model_name="base-model")
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))),
    )
    return client, sent, recorded


async def _call_each(client: GeminiLLMClient, sites: tuple[str, ...]) -> None:
    for site in sites:
        ctx = LLMCallContext(call_site=site, user_id=None, room_id=None)  # type: ignore[arg-type]
        await client.generate_structured("judge", _JudgmentResult, usage=ctx)


async def test_structured_calls_use_the_base_model_when_no_override_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_model_switches(monkeypatch)
    client, sent, recorded = _capture_structured(monkeypatch)

    await _call_each(client, _ALL_STRUCTURED_SITES)

    assert [k["model"] for k in sent] == ["base-model"] * len(_ALL_STRUCTURED_SITES)
    assert recorded == [(site, "base-model") for site in _ALL_STRUCTURED_SITES]


@pytest.mark.parametrize("switch", list(_MODEL_SWITCHES))
async def test_each_model_switch_routes_only_its_own_call_sites(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, switch: str
) -> None:
    """판정 종류마다 모델을 따로 옮길 수 있어야 한다 — 스탯·엔딩만 옮기고 그림 매칭은 기본 모델에 두는 식이다."""
    caplog.set_level(logging.WARNING, logger="api.llm.gemini")
    _clear_model_switches(monkeypatch)
    monkeypatch.setattr(settings, switch, "switched-model")
    client, sent, recorded = _capture_structured(monkeypatch)

    await _call_each(client, _ALL_STRUCTURED_SITES)

    expected = ["switched-model" if site in _MODEL_SWITCHES[switch] else "base-model" for site in _ALL_STRUCTURED_SITES]
    assert [k["model"] for k in sent] == expected
    # 로그·집계의 model 은 실제로 호출한 모델이어야 전환 전후를 갈라 볼 수 있다.
    assert [m for _, m in recorded] == expected
    assert [_fields(r)["model"] for r in _usage_records(caplog)] == expected


async def test_model_switches_combine_without_crossing(monkeypatch: pytest.MonkeyPatch) -> None:
    """여럿을 함께 정해도 각 call_site 는 제 종류의 설정만 따른다. 빈 문자열은 정하지 않은 것과 같다."""
    monkeypatch.setattr(settings, "gemini_stat_judgment_model_name", "stat-model")
    monkeypatch.setattr(settings, "gemini_ending_judgment_model_name", "ending-model")
    monkeypatch.setattr(settings, "gemini_image_judgment_model_name", "")
    monkeypatch.setattr(settings, "gemini_publish_filter_model_name", "filter-model")
    client, sent, _ = _capture_structured(monkeypatch)

    await _call_each(client, _ALL_STRUCTURED_SITES)

    expected = (
        ["stat-model"] * len(_STAT_SITES)
        + ["ending-model"] * len(_ENDING_SITES)
        + ["base-model"] * len(_IMAGE_SITES)
        + ["filter-model"] * len(_PUBLISH_FILTER_SITES)
        + ["base-model"] * len(_OTHER_STRUCTURED_SITES)
    )
    assert [k["model"] for k in sent] == expected


def test_judgment_call_sites_are_exactly_the_three_kinds() -> None:
    """어드민 판정 비율은 판정 집합 전체를 본다 — 종류별 집합의 합이 그 집합이고 서로 겹치지 않아야 한다."""
    from api.llm.client import (
        ENDING_JUDGMENT_CALL_SITES,
        IMAGE_JUDGMENT_CALL_SITES,
        JUDGMENT_CALL_SITES,
        STAT_JUDGMENT_CALL_SITES,
    )

    kinds = (STAT_JUDGMENT_CALL_SITES, ENDING_JUDGMENT_CALL_SITES, IMAGE_JUDGMENT_CALL_SITES)
    assert JUDGMENT_CALL_SITES == frozenset(_JUDGMENT_SITES)
    assert sum(len(k) for k in kinds) == len(JUDGMENT_CALL_SITES)
    assert frozenset().union(*kinds) == JUDGMENT_CALL_SITES


async def test_model_overrides_do_not_touch_streaming_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _MODEL_SWITCHES:
        monkeypatch.setattr(settings, name, "switched-model")
    sent: list[dict[str, Any]] = []

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        sent.append(kwargs)
        return _chunks("a")

    client = GeminiLLMClient(api_key="test-key", model_name="base-model")
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))),
    )
    monkeypatch.setattr(settings, "gemini_thinking_budget", None)

    assert [t async for t in client.generate("hi", usage=_CTX)] == ["a"]
    assert sent[0]["model"] == "base-model"
    assert sent[0]["config"].thinking_config is None


def test_structured_calls_have_no_thinking_settings() -> None:
    """판정·심사 전용 사고 예산 설정은 없다 — 판정 호출은 기본 설정에서도 사고 토큰이 0 이었고, 현행 운영 모델은
    사고 끔(0)을 400 으로 거부해 그 설정은 판정을 조용히 멈추게 할 뿐이었다."""
    assert "gemini_judgment_thinking_budget" not in Settings.model_fields
    assert "gemini_publish_filter_thinking_budget" not in Settings.model_fields
    assert "gemini_judgment_model_name" not in Settings.model_fields


async def test_structured_calls_never_send_thinking_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # generate() 용 전역 예산은 구조화 호출에 새지 않는다 — 어느 call_site 든, 모델 스위치를 켜도.
    monkeypatch.setattr(settings, "gemini_thinking_budget", 0)
    for name in _MODEL_SWITCHES:
        monkeypatch.setattr(settings, name, "switched-model")
    client, sent, _ = _capture_structured(monkeypatch)

    await _call_each(client, _ALL_STRUCTURED_SITES)

    assert all(k["config"].thinking_config is None for k in sent)


async def test_generate_and_generate_structured_persist_usage_to_the_daily_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실제 Redis(테스트 DB)까지 — 스트리밍 생성과 구조화 호출 둘 다 오늘(KST) 해시에 쌓인다."""
    from api.core.rate_limit import KST
    from api.llm.usage_store import read_usage

    monkeypatch.setattr(settings, "gemini_stat_judgment_model_name", "judge-model")
    client = _make_client(
        monkeypatch,
        generate_content_stream=_stream_of(SimpleNamespace(text="a", usage_metadata=_usage(10, 3, 2, 15))),
    )
    gen_ctx = LLMCallContext(call_site="chat_generate", user_id=_USER_ID, room_id=_ROOM_ID)
    assert [t async for t in client.generate("hi", usage=gen_ctx)] == ["a"]

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            parsed=_JudgmentResult(triggered=False, ending_id=None), usage_metadata=_usage(40, 5, 0, 45)
        )

    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))),
    )
    await client.generate_structured("judge", _JudgmentResult, usage=_CTX)

    today = datetime.now(KST).date()
    rows = {(r.call_site, r.model): r for r in await read_usage(today, today)}
    assert rows[("chat_generate", client._model_name)].calls == 1
    assert rows[("chat_generate", client._model_name)].total == 15
    assert rows[("chat_stat_judgment", "judge-model")].prompt == 40


async def test_usage_persistence_failure_does_not_break_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """집계 저장이 죽어도(여기선 Redis 클라이언트 자체가 터짐) 스트림과 판정 결과는 그대로다."""

    def exploding_pipeline(**_: Any) -> Any:
        raise RuntimeError("redis client broken")

    monkeypatch.setattr("api.llm.usage_store.redis_client", SimpleNamespace(pipeline=exploding_pipeline))
    expected = _JudgmentResult(triggered=True, ending_id=None)

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=expected, usage_metadata=_usage(1, 1, None, 2))

    client = _make_client(
        monkeypatch,
        generate_content_stream=_stream_of(SimpleNamespace(text="a", usage_metadata=_usage(1, 1, None, 2))),
        generate_content=generate_content,
    )

    assert [t async for t in client.generate("hi", usage=_USAGE)] == ["a"]
    assert await client.generate_structured("judge", _JudgmentResult, usage=_CTX) == expected


# ---- 호출 타임아웃 ---------------------------------------------------------------------------------

# 호출 종류마다 기대하는 요청 단위 타임아웃(ms). 구현의 매핑 함수를 불러 기대값을 만들면 양쪽이 같은 값을 내
# 아무것도 증명하지 못하므로 숫자를 그대로 적는다. 판정은 출력이 수십 토큰이라 생성보다 훨씬 짧게 끊는다.
_EXPECTED_TIMEOUT_MS: dict[str, int] = {
    "chat_generate": 45_000,
    "preview_generate": 45_000,
    "chat_stat_judgment": 20_000,
    "chat_ending_judgment": 20_000,
    "chat_situational_image": 20_000,
    "chat_media_book_image": 20_000,
    "preview_stat_judgment": 20_000,
    "preview_ending_judgment": 20_000,
    "preview_media_book_image": 20_000,
    "chat_memory_summary": 60_000,
    "publish_filter_character": 60_000,
    "publish_filter_story": 60_000,
    "seed_story_generate": 300_000,
    "seed_similarity_review": 300_000,
}


def test_every_call_site_has_an_expected_timeout() -> None:
    """새 call_site 가 생기면 이 표에 값을 정해 넣어야 한다 — 빠뜨린 호출이 요청 단위 값 없이 나가면 SDK 가
    클라이언트 헤더에 전역값을 써 넣어 뒤따르는 호출의 서버 기한 헤더까지 바꾼다."""
    assert set(_EXPECTED_TIMEOUT_MS) == set(get_args(LLMCallSite))


@pytest.mark.parametrize("call_site", sorted(_EXPECTED_TIMEOUT_MS))
async def test_generate_structured_sends_the_per_call_site_timeout(
    monkeypatch: pytest.MonkeyPatch, call_site: LLMCallSite
) -> None:
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return SimpleNamespace(parsed=_JudgmentResult(triggered=False, ending_id=None))

    client = _make_client(monkeypatch, generate_content=generate_content)

    await client.generate_structured(
        "judge", _JudgmentResult, usage=LLMCallContext(call_site=call_site, user_id=None, room_id=None)
    )

    assert received["config"].http_options.timeout == _EXPECTED_TIMEOUT_MS[call_site]


@pytest.mark.parametrize("call_site", ["chat_generate", "preview_generate"])
async def test_generate_sends_the_generation_timeout(monkeypatch: pytest.MonkeyPatch, call_site: LLMCallSite) -> None:
    received: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        received.update(kwargs)
        return _chunks("a")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    [_ async for _ in client.generate("hi", usage=LLMCallContext(call_site=call_site, user_id=None, room_id=None))]

    assert received["config"].http_options.timeout == 45_000


async def test_request_timeouts_follow_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영에서 값이 맞지 않으면 배포 없이 `.env` 로 늘릴 수 있어야 한다 — 숫자가 코드에 박혀 있으면 안 된다."""
    monkeypatch.setattr(settings, "gemini_generate_timeout_ms", 1_001)
    monkeypatch.setattr(settings, "gemini_judgment_timeout_ms", 1_002)
    monkeypatch.setattr(settings, "gemini_memory_summary_timeout_ms", 1_003)
    monkeypatch.setattr(settings, "gemini_publish_filter_timeout_ms", 1_004)
    sent: list[int] = []

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        sent.append(kwargs["config"].http_options.timeout)
        return SimpleNamespace(parsed=_JudgmentResult(triggered=False, ending_id=None))

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        sent.append(kwargs["config"].http_options.timeout)
        return _chunks("a")

    client = _make_client(
        monkeypatch, generate_content=generate_content, generate_content_stream=generate_content_stream
    )

    [_ async for _ in client.generate("hi", usage=_USAGE)]
    for call_site in ("chat_ending_judgment", "chat_memory_summary", "publish_filter_story"):
        await client.generate_structured(
            "judge", _JudgmentResult, usage=LLMCallContext(call_site=call_site, user_id=None, room_id=None)
        )

    assert sent == [1_001, 1_002, 1_003, 1_004]


def test_client_carries_a_global_timeout_backstop(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청 단위 값이 빠진 호출이 생겨도 무제한으로 기다리지 않게 클라이언트 자체에 기본 상한을 건다."""
    created: dict[str, Any] = {}

    def fake_client(**kwargs: Any) -> SimpleNamespace:
        created.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("api.llm.gemini.genai.Client", fake_client)

    GeminiLLMClient(api_key="test-key")

    assert created["http_options"].timeout == 60_000


_SDK_DELAY_SECONDS = 1.0


def _timeout_enforcing_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    """httpx.MockTransport 는 타임아웃을 집행하지 않는다 — 지연만 주면 그만큼 기다렸다가 정상 응답한다. 그래서 SDK 가
    요청에 실어 보낸 읽기 상한을 읽어, 그 상한이 가짜 서버의 응답 지연보다 짧으면 실제 네트워크 백엔드처럼
    `httpx.ReadTimeout` 을 던진다. 상한이 없거나 넉넉하면 정상 응답을 돌려준다."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        read_timeout = request.extensions.get("timeout", {}).get("read")
        if read_timeout is not None and read_timeout < _SDK_DELAY_SECONDS:
            raise httpx.ReadTimeout("read timed out", request=request)
        body = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": '{"triggered": false, "ending_id": null}'}]},
                    "finishReason": "STOP",
                }
            ]
        }
        if "streamGenerateContent" in request.url.path:
            return httpx.Response(
                200, text=f"data: {json.dumps(body)}\n\n", headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def _sdk_backed_client(seen: list[httpx.Request]) -> GeminiLLMClient:
    """진짜 `genai.Client` 를 쓰되 네트워크만 가짜로 바꾼다 — 가짜 클라이언트 테스트는 "인자를 넘겼다"만 보여 주고,
    그 값이 SDK 안에서 실제로 httpx 요청까지 가는지는 이 경로로만 확인된다."""
    client = GeminiLLMClient(api_key="test-key", model_name="gemini-test")
    client._client = genai.Client(
        api_key="test-key",
        http_options=genai_types.HttpOptions(
            httpx_async_client=httpx.AsyncClient(transport=_timeout_enforcing_transport(seen))
        ),
    )
    return client


async def test_structured_call_times_out_through_the_real_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_judgment_timeout_ms", 50)
    seen: list[httpx.Request] = []
    client = _sdk_backed_client(seen)

    with pytest.raises(LLMClientError) as exc_info:
        await client.generate_structured(
            "judge",
            _JudgmentResult,
            usage=LLMCallContext(call_site="chat_stat_judgment", user_id=None, room_id=None),
        )

    assert not isinstance(exc_info.value, LLMRateLimitError)
    (request,) = seen
    assert request.extensions["timeout"]["read"] == pytest.approx(0.05)
    # 같은 값이 서버 기한 헤더로도 나간다(초 단위 올림).
    assert request.headers["X-Server-Timeout"] == "1"


async def test_streaming_generation_times_out_through_the_real_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_generate_timeout_ms", 50)
    seen: list[httpx.Request] = []
    client = _sdk_backed_client(seen)

    with pytest.raises(LLMClientError):
        [_ async for _ in client.generate("hi", usage=_USAGE)]

    (request,) = seen
    assert request.extensions["timeout"]["read"] == pytest.approx(0.05)
    assert request.headers["X-Server-Timeout"] == "1"


async def test_generate_wraps_a_bare_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """aiohttp 경로의 SDK 는 타임아웃을 `asyncio.TimeoutError`(= `TimeoutError`)로 올린다. 이것이 감싸지지 않으면
    SSE 제너레이터를 뚫고 나가 요청 스코프 DB 세션을 강제 종료시킨다."""

    async def failing_stream() -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(text="a")
        raise TimeoutError

    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        return failing_stream()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMClientError):
        [_ async for _ in client.generate("hi", usage=_USAGE)]


async def test_generate_structured_wraps_a_bare_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        raise TimeoutError

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMClientError):
        await client.generate_structured("judge", _JudgmentResult, usage=_USAGE)
