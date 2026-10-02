"""`scripts/judgment_replay/runner.py` — 호출 상한이 동시 실행에서도 지켜지는지, 실패한 호출이 기록되고 실행이 이어지는지."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types as genai_types

from api.chat.prompt_builder import EndingJudgmentResult
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMRateLimitError
from api.llm.gemini import GeminiLLMClient
from judgment_replay import scenes
from judgment_replay.runner import CONFIGS, CallBudget, ReplayConfig, install_usage_capture, run_replay


class _CountingClient(LLMClient):
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("판정 리플레이는 생성 호출을 쓰지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: list[tuple[bytes, str]] | None = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls += 1
        return response_schema(triggered=True)


def _ending_inputs(count: int) -> list[scenes.ReplayInput]:
    return [
        scenes.ReplayInput(
            input_id=f"e{i}",
            kind="ending",
            call_site="chat_ending_judgment",
            prompt="p",
            schema=EndingJudgmentResult,
            image_paths=[],
            expected=True,
            context={},
        )
        for i in range(count)
    ]


@pytest.mark.parametrize(
    ("limit", "made", "stopped"),
    [pytest.param(7, 7, True, id="stops-at-limit"), pytest.param(40, 40, False, id="limit-equals-plan")],
)
async def test_limit_calls_is_a_hard_cap_even_with_concurrency(limit: int, made: int, stopped: bool) -> None:
    client = _CountingClient()
    records: list[dict[str, Any]] = []
    applied: list[str] = []
    configs = [CONFIGS["3.5-default"], CONFIGS["3.1-off"]]

    def make_client(config: ReplayConfig) -> LLMClient:
        applied.append(config.name)
        return client

    result = await run_replay(
        _ending_inputs(10),
        configs,
        reps={"ending": 2},
        budget=CallBudget(limit),
        concurrency=3,
        sink=records.append,
        make_client=make_client,
    )

    assert client.calls == made
    assert len(records) == made
    assert result.stopped_by_limit is stopped
    assert applied[0] == "3.5-default"


async def test_failed_call_is_recorded_and_the_run_continues() -> None:
    class _Flaky(_CountingClient):
        async def generate_structured(
            self,
            prompt: str,
            response_schema: Any,
            images: list[tuple[bytes, str]] | None = None,
            *,
            usage: LLMCallContext,
        ) -> Any:
            self.calls += 1
            if self.calls == 2:
                raise LLMClientError("Gemini structured response could not be parsed into EndingJudgmentResult")
            return response_schema(triggered=False)

    records: list[dict[str, Any]] = []
    flaky = _Flaky()
    await run_replay(
        _ending_inputs(3),
        [CONFIGS["3.5-default"]],
        reps={"ending": 1},
        budget=CallBudget(10),
        concurrency=1,
        sink=records.append,
        make_client=lambda config: flaky,
    )
    assert [r["ok"] for r in records] == [True, False, True]
    assert records[1]["error_type"] == "parse"
    assert records[0]["derived"] == {"triggered": False}


async def test_consecutive_transport_failures_stop_the_run() -> None:
    """쿼터가 막히면 남은 호출이 전부 같은 실패로 타 버린다 — 연달아 다섯 번이면 멈춘다."""

    class _Exhausted(_CountingClient):
        async def generate_structured(
            self,
            prompt: str,
            response_schema: Any,
            images: list[tuple[bytes, str]] | None = None,
            *,
            usage: LLMCallContext,
        ) -> Any:
            self.calls += 1
            raise LLMRateLimitError("Gemini generate_structured() call failed: 429")

    client = _Exhausted()
    records: list[dict[str, Any]] = []
    result = await run_replay(
        _ending_inputs(10),
        [CONFIGS["3.5-default"], CONFIGS["3.1-off"]],
        reps={"ending": 2},
        budget=CallBudget(40),
        concurrency=1,
        sink=records.append,
        make_client=lambda config: client,
    )
    assert client.calls == 5
    assert result.stopped_by_errors == "rate_limit"


def _fake_sdk(client: GeminiLLMClient) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def generate_content(**kwargs: Any) -> Any:
        sent.append(kwargs)
        return SimpleNamespace(
            parsed=EndingJudgmentResult(triggered=True), usage_metadata=None, text="{}", candidates=[]
        )

    setattr(client._client.aio.models, "generate_content", generate_content)  # noqa: B010
    return sent


async def test_measured_model_and_thinking_are_sent_as_configured_not_from_app_settings() -> None:
    """측정 설정의 모델·사고 끔은 앱 설정(판정 모델 스위치 등)을 거치지 않고 SDK 호출에 그대로 실린다 — 클라이언트
    기본 모델이 달라도 3.1-off 는 3.1 에 thinking_budget=0 으로 나간다."""
    client = GeminiLLMClient(api_key="test", model_name="gemini-3.5-flash-lite")
    sent = _fake_sdk(client)
    install_usage_capture(client, CONFIGS["3.1-off"])

    await client.generate_structured(
        "p", EndingJudgmentResult, usage=LLMCallContext(call_site="chat_ending_judgment", user_id=None, room_id=None)
    )

    assert sent[0]["model"] == "gemini-3.1-flash-lite"
    assert sent[0]["config"].thinking_config.thinking_budget == 0


async def test_default_thinking_config_sends_no_thinking_config_even_if_the_app_set_one() -> None:
    client = GeminiLLMClient(api_key="test", model_name="gemini-3.1-flash-lite")
    sent = _fake_sdk(client)
    install_usage_capture(client, CONFIGS["3.5-default"])

    await client._client.aio.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents="p",
        config=genai_types.GenerateContentConfig(thinking_config=genai_types.ThinkingConfig(thinking_budget=512)),
    )

    assert sent[0]["model"] == "gemini-3.5-flash-lite"
    assert sent[0]["config"].thinking_config is None
