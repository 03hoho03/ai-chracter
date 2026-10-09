"""LLM 호출 위치(`LLMCallSite`)마다 실제로 실리는 호출 정책을 한 표로 고정한다 — 어느 Gemini 모델로 가는지, 요청
타임아웃, 출력 상한, 사고 설정, seed, 소설화의 잘림·빈 본문 구분, Bedrock 의 타임아웃·출력 상한·캐시 블록, 상위 모델을
골랐을 때 어느 공급자로 가는지, 사용량 로그 줄과 지표 키.

값은 상수를 옮겨 적지 않고 진짜 클라이언트를 SDK 경계만 가짜로 두고 불러서 얻는다. 설정은 두 번 채운다.

- 표지 채우기: 모델 이름·타임아웃·상한·사고·seed 설정을 전부 서로 다른 표지 값으로 채운다. 실린 값을 설정 이름으로
  되읽으므로 "어느 설정이 이 호출을 정하는가"가 남는다(호출 위치를 다른 무리로 옮기면 바뀐다). 설정이 아닌 고정값은
  `literal:<값>` 으로 남는다.
- 선언 기본값 채우기: 같은 설정을 `Settings` 의 선언 기본값으로 채운다. 실린 숫자가 남으므로 기본값을 바꾸면 바뀐다.
  `.env` 와 무관하게 같은 값이 나오게 하려는 것이다.

표는 지금 동작을 기록한 것이다(`fixtures/llm_call_policy.json`). 다시 뜨는 법은 `factories._assert_characterization`.
"""

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pytest
from google.genai import types as genai_types
from pydantic import BaseModel

from api.core.config import Settings, settings
from api.core.redis import redis_client
from api.llm.bedrock import BedrockLLMClient
from api.llm.chat_models import actual_model_id
from api.llm.client import (
    JUDGMENT_CALL_SITES,
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    SegmentedPrompt,
)
from api.llm.gemini import GeminiLLMClient
from api.llm.routing import RoutingLLMClient
from api.llm.usage_store import USAGE_KEY_PREFIX
from factories import _assert_characterization, _assert_recorded_cases
from replay.calls import capture_usage

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "llm_call_policy.json"

_CALL_SITES: tuple[LLMCallSite, ...] = get_args(LLMCallSite)

# 표지로 채우는 설정. 문자열 설정은 값이 곧 `<설정 이름>` 이고, 정수 설정은 서로 겹치지 않는 수다.
_TEXT_SETTINGS = (
    "gemini_model_name",
    "gemini_stat_judgment_model_name",
    "gemini_ending_judgment_model_name",
    "gemini_image_judgment_model_name",
    "gemini_publish_filter_model_name",
    "gemini_novelize_model_name",
    "bedrock_sonnet_model_id",
    "bedrock_opus_model_id",
)
_INT_SETTINGS = (
    "gemini_generate_timeout_ms",
    "gemini_judgment_timeout_ms",
    "gemini_memory_summary_timeout_ms",
    "gemini_publish_filter_timeout_ms",
    "gemini_client_timeout_ms",
    "gemini_novelize_chapter_timeout_ms",
    "gemini_novelize_revise_timeout_ms",
    "gemini_novelize_boundary_timeout_ms",
    "gemini_max_output_tokens",
    "gemini_novelize_max_output_tokens",
    "gemini_thinking_budget",
    "gemini_novelize_thinking_budget",
    "gemini_seed",
    "bedrock_chat_timeout_ms",
    "bedrock_chapter_timeout_ms",
    "bedrock_chat_max_tokens",
    "bedrock_chapter_max_tokens",
)
# 사고 수준은 고를 수 있는 값이 넷뿐이라 표지로 그중 하나를 쓴다. 같은 값을 코드에 박아도 표지 채우기에서는 설정 이름으로
# 되읽히므로, 둘을 가르는 것은 선언 기본값 채우기다 — 선언 기본값이 None 이라 설정을 읽는 코드는 수준을 싣지 않고, 박힌
# 값은 거기서도 실린다.
_LEVEL_SETTING = "gemini_novelize_thinking_level"
_LEVEL_MARKER = "LOW"
_INT_MARKERS = {name: 70_001 + index for index, name in enumerate(_INT_SETTINGS)}
_MARKER_NAMES: dict[object, str] = {
    **{f"<{name}>": name for name in _TEXT_SETTINGS},
    **{value: name for name, value in _INT_MARKERS.items()},
    _LEVEL_MARKER: _LEVEL_SETTING,
}


def _fill_with_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _TEXT_SETTINGS:
        monkeypatch.setattr(settings, name, f"<{name}>")
    for name, value in _INT_MARKERS.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, _LEVEL_SETTING, _LEVEL_MARKER)


def _fill_with_declared_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_TEXT_SETTINGS, *_INT_SETTINGS, _LEVEL_SETTING):
        monkeypatch.setattr(settings, name, Settings.model_fields[name].default)


def _source(value: object) -> str | None:
    """표지 값을 설정 이름으로 되읽는다. 표지가 아닌 값은 코드에 박힌 고정값이다."""
    if value is None:
        return None
    return _MARKER_NAMES.get(value, f"literal:{value}")


class _Parsed(BaseModel):
    ok: bool


def _gemini_usage() -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=11,
        cached_content_token_count=0,
        candidates_token_count=5,
        thoughts_token_count=0,
        total_token_count=16,
    )


class _GeminiSdk:
    """`aio.models` 자리의 가짜. `mode` 가 정상(ok)·출력 상한에서 잘림(truncated)·빈 본문(empty)을 고른다."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.sent: list[dict[str, Any]] = []

    def _finish(self) -> Any:
        return genai_types.FinishReason.MAX_TOKENS if self.mode == "truncated" else genai_types.FinishReason.STOP

    async def generate_content_stream(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        self.sent.append(kwargs)
        text = "" if self.mode == "empty" else "본문"
        finish = self._finish()

        async def chunks() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                text=text,
                candidates=[SimpleNamespace(finish_reason=finish)],
                usage_metadata=_gemini_usage(),
                prompt_feedback=None,
            )

        return chunks()

    async def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.sent.append(kwargs)
        if self.mode == "ok":
            parsed: _Parsed | None = _Parsed(ok=True)
            text = '{"ok": true}'
        else:
            parsed = None
            text = "" if self.mode == "empty" else '{"ok": '
        return SimpleNamespace(
            parsed=parsed,
            text=text,
            candidates=[SimpleNamespace(finish_reason=self._finish())],
            usage_metadata=_gemini_usage(),
            prompt_feedback=None,
        )


def _gemini_client(monkeypatch: pytest.MonkeyPatch, sdk: _GeminiSdk) -> GeminiLLMClient:
    client = GeminiLLMClient(api_key="test-key")
    monkeypatch.setattr(client, "_client", SimpleNamespace(aio=SimpleNamespace(models=sdk)))
    return client


class _BedrockSdk:
    """`messages.create` 자리의 가짜. 모드는 `_GeminiSdk` 와 같다."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.sent: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        self.sent.append(kwargs)
        mode = self.mode

        async def stream() -> AsyncIterator[SimpleNamespace]:
            usage = SimpleNamespace(
                input_tokens=7, cache_read_input_tokens=0, cache_creation_input_tokens=0, output_tokens=0
            )
            yield SimpleNamespace(type="message_start", message=SimpleNamespace(usage=usage))
            if mode != "empty":
                yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="본문"))
            yield SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="max_tokens" if mode == "truncated" else "end_turn"),
                usage=SimpleNamespace(
                    output_tokens=3, input_tokens=None, cache_read_input_tokens=None, cache_creation_input_tokens=None
                ),
            )

        return stream()


def _bedrock_client(monkeypatch: pytest.MonkeyPatch, sdk: _BedrockSdk) -> BedrockLLMClient:
    client = BedrockLLMClient()
    monkeypatch.setattr(client, "_client", SimpleNamespace(messages=sdk))
    return client


def _usage(call_site: LLMCallSite) -> LLMCallContext:
    return LLMCallContext(call_site=call_site, user_id=None, room_id=None, model="sonnet")


# 채팅 턴처럼 경계가 있는 프롬프트 — Bedrock 이 캐시 블록으로 나누는지가 이것으로 드러난다.
_PROMPT = SegmentedPrompt(("앞부분 ", "직전 교환 ", "이번 입력"))


async def _run_generate(client: LLMClient, call_site: LLMCallSite) -> str | None:
    """생성 한 번을 끝까지 돌리고, 올라온 예외의 이름(없으면 None)을 돌려준다."""
    try:
        async for _ in client.generate(_PROMPT, "지시문", ["\n사용자:"], usage=_usage(call_site)):
            pass
    except Exception as exc:
        return type(exc).__name__
    return None


async def _run_structured(client: LLMClient, call_site: LLMCallSite) -> str | None:
    try:
        await client.generate_structured("판정 프롬프트", _Parsed, usage=_usage(call_site))
    except Exception as exc:
        return type(exc).__name__
    return None


def _thinking(config: genai_types.GenerateContentConfig) -> dict[str, str | None] | None:
    thinking = config.thinking_config
    if thinking is None:
        return None
    level = thinking.thinking_level
    return {
        "budget": _source(thinking.thinking_budget),
        "level": _source(level.value) if level is not None else None,
    }


def _declared_thinking(config: genai_types.GenerateContentConfig) -> dict[str, object] | None:
    thinking = config.thinking_config
    if thinking is None:
        return None
    level = thinking.thinking_level
    return {"budget": thinking.thinking_budget, "level": level.value if level is not None else None}


def _gemini_request(sent: dict[str, Any]) -> dict[str, Any]:
    config: genai_types.GenerateContentConfig = sent["config"]
    assert config.http_options is not None
    return {
        "model": _source(sent["model"]),
        "timeout": _source(config.http_options.timeout),
        "maxOutputTokens": _source(config.max_output_tokens),
        "thinking": _thinking(config),
        "seed": config.seed is not None,
    }


def _bedrock_request(sent: dict[str, Any]) -> dict[str, Any]:
    content = sent["messages"][0]["content"]
    return {
        "model": _source(sent["model"]),
        "timeout": _source(round(sent["timeout"] * 1000)),
        "maxTokens": _source(sent["max_tokens"]),
        "cacheBlocks": [bool(block.get("cache_control")) for block in content] if isinstance(content, list) else None,
    }


async def _routed_provider(call_site: LLMCallSite, method: str) -> str:
    """상위 모델(sonnet)을 실은 호출이 어느 구현으로 가는가."""
    reached: list[str] = []

    class _Named(LLMClient):
        def __init__(self, name: str) -> None:
            self.name = name

        async def generate(
            self,
            prompt: str,
            system_instruction: str | None = None,
            stop_sequences: list[str] | None = None,
            *,
            usage: LLMCallContext,
        ) -> AsyncIterator[str]:
            reached.append(self.name)
            yield ""

        async def generate_structured(
            self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
        ) -> Any:
            reached.append(self.name)
            return _Parsed(ok=True)

    router = RoutingLLMClient(_Named("gemini"), bedrock_factory=lambda: _Named("bedrock"))
    if method == "generate":
        await _run_generate(router, call_site)
    else:
        await _run_structured(router, call_site)
    (provider,) = reached
    return provider


_USAGE_LINE = re.compile(r"^(gemini_usage|bedrock_usage) call_site=(\S+) model=(\S+)")


def _usage_lines(records: list[logging.LogRecord]) -> list[str]:
    lines = []
    for record in records:
        match = _USAGE_LINE.match(record.getMessage())
        if match is not None:
            name, call_site, model = match.groups()
            lines.append(f"{name} call_site={call_site} model={_source(model)}")
    # 정상·잘림·빈 본문 세 번 모두 같은 줄을 남긴다 — 겹친 줄은 하나로 둔다.
    return list(dict.fromkeys(lines))


async def _metric_keys() -> list[str]:
    fields: set[str] = set()
    for key in await redis_client.keys(f"{USAGE_KEY_PREFIX}*"):
        fields.update(str(field) for field in await redis_client.hkeys(key))
    keys = []
    for field in sorted(fields):
        call_site, model, metric = field.split("|")
        keys.append(f"{call_site}|{_source(model)}|{metric}")
    return keys


async def _clear_usage() -> None:
    keys = await redis_client.keys(f"{USAGE_KEY_PREFIX}*")
    if keys:
        await redis_client.delete(*keys)


async def _marker_row(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, call_site: LLMCallSite
) -> dict[str, Any]:
    await _clear_usage()
    caplog.clear()
    failures: dict[str, dict[str, str | None]] = {"generate": {}, "structured": {}, "bedrock": {}}
    requests: dict[str, dict[str, Any]] = {}
    with caplog.at_level(logging.WARNING):
        for mode in ("ok", "truncated", "empty"):
            gemini_sdk = _GeminiSdk(mode)
            gemini = _gemini_client(monkeypatch, gemini_sdk)
            failures["generate"][mode] = await _run_generate(gemini, call_site)
            failures["structured"][mode] = await _run_structured(gemini, call_site)
            bedrock_sdk = _BedrockSdk(mode)
            failures["bedrock"][mode] = await _run_generate(_bedrock_client(monkeypatch, bedrock_sdk), call_site)
            if mode == "ok":
                generate_sent, structured_sent = gemini_sdk.sent
                requests["generate"] = _gemini_request(generate_sent)
                requests["structured"] = _gemini_request(structured_sent)
                (bedrock_sent,) = bedrock_sdk.sent
                requests["bedrock"] = _bedrock_request(bedrock_sent)
        routing_warned_before = len(caplog.records)
        routing = {
            "generate": await _routed_provider(call_site, "generate"),
            "structured": await _routed_provider(call_site, "structured"),
        }
        routing_warnings = [
            record.getMessage() for record in caplog.records[routing_warned_before:] if record.name == "api.llm.routing"
        ]
    return {
        "gemini": {
            "generate": {**requests["generate"], "failures": failures["generate"]},
            "structured": {**requests["structured"], "failures": failures["structured"]},
        },
        "bedrock": {**requests["bedrock"], "failures": failures["bedrock"]},
        "routingWhenSonnet": {**routing, "warned": len(routing_warnings) > 0},
        "usageLogLines": _usage_lines(caplog.records),
        "metricKeys": await _metric_keys(),
        "inJudgmentRatio": call_site in JUDGMENT_CALL_SITES,
    }


async def _declared_default_row(monkeypatch: pytest.MonkeyPatch, call_site: LLMCallSite) -> dict[str, Any]:
    gemini_sdk = _GeminiSdk("ok")
    gemini = _gemini_client(monkeypatch, gemini_sdk)
    await _run_generate(gemini, call_site)
    await _run_structured(gemini, call_site)
    bedrock_sdk = _BedrockSdk("ok")
    await _run_generate(_bedrock_client(monkeypatch, bedrock_sdk), call_site)
    row: dict[str, Any] = {}
    for method, sent in zip(("generate", "structured"), gemini_sdk.sent, strict=True):
        config: genai_types.GenerateContentConfig = sent["config"]
        assert config.http_options is not None
        row[method] = {
            "timeoutMs": config.http_options.timeout,
            "maxOutputTokens": config.max_output_tokens,
            "thinking": _declared_thinking(config),
        }
    (bedrock_sent,) = bedrock_sdk.sent
    row["bedrock"] = {"timeoutMs": round(bedrock_sent["timeout"] * 1000), "maxTokens": bedrock_sent["max_tokens"]}
    return row


def test_recorded_call_sites_are_exactly_the_parametrized_call_sites() -> None:
    _assert_recorded_cases(FIXTURE_PATH, _CALL_SITES)


@pytest.mark.parametrize("call_site", _CALL_SITES)
async def test_call_policy_per_call_site_matches_the_recorded_table(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, call_site: LLMCallSite
) -> None:
    with monkeypatch.context() as patch:
        _fill_with_declared_defaults(patch)
        declared = await _declared_default_row(patch, call_site)
    _fill_with_markers(monkeypatch)
    marked = await _marker_row(monkeypatch, caplog, call_site)

    _assert_characterization(FIXTURE_PATH, call_site, {**marked, "declaredDefaults": declared})


# ── 리플레이의 사용량 잡기 ──────────────────────────────────────────────────────────────────
#
# 리플레이(`scripts/replay/calls.py` 의 `capture_usage`)는 두 공급자 모듈의 `record_usage` 이름을 바꿔 끼워 실제로 보낸 모델과
# 토큰을 잡는다. 공급자가 그 이름이 아닌 다른 경로(예: 사용량 저장 모듈의 속성)로 기록하게 바뀌면 그 공급자의 줄만 비게 된다.


@pytest.mark.parametrize("provider", ["gemini", "bedrock"])
async def test_replay_usage_capture_sees_a_call_from_each_provider(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    _fill_with_markers(monkeypatch)
    client: LLMClient = (
        _gemini_client(monkeypatch, _GeminiSdk("ok"))
        if provider == "gemini"
        else _bedrock_client(monkeypatch, _BedrockSdk("ok"))
    )
    expected_model = settings.gemini_model_name if provider == "gemini" else actual_model_id("sonnet")

    with capture_usage() as sent:
        assert await _run_generate(client, "replay_generate") is None

    assert [(call.call_site, call.model) for call in sent] == [("replay_generate", expected_model)]
