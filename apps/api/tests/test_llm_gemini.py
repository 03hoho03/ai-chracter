import logging
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from api.core.config import settings
from api.llm.client import LLMCallContext, LLMClientError, LLMPolicyViolationError, LLMRateLimitError
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

    with pytest.raises(LLMClientError):
        await client.generate_structured("judge this", _JudgmentResult, usage=_USAGE)


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


def _usage(prompt: int, candidates: int, thoughts: int | None, total: int) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=prompt,
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
            SimpleNamespace(text="c", usage_metadata=_usage(11, 22, 3, 36)),
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
    assert [fields[k] for k in ("prompt_tokens", "candidates_tokens", "thoughts_tokens", "total_tokens")] == [
        "None"
    ] * 4


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
        return SimpleNamespace(parsed=expected, usage_metadata=_usage(40, 5, 17, 62))

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
