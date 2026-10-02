"""`scripts/judgment_replay/runner.py` — 호출 상한이 동시 실행에서도 지켜지는지, 실패한 호출이 기록되고 실행이 이어지는지."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from api.chat.prompt_builder import EndingJudgmentResult
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from judgment_replay import scenes
from judgment_replay.runner import CONFIGS, CallBudget, run_replay


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

    result = await run_replay(
        client,
        _ending_inputs(10),
        configs,
        reps={"ending": 2},
        budget=CallBudget(limit),
        concurrency=3,
        sink=records.append,
        apply_config=lambda config: applied.append(config.name),
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
    await run_replay(
        _Flaky(),
        _ending_inputs(3),
        [CONFIGS["3.5-default"]],
        reps={"ending": 1},
        budget=CallBudget(10),
        concurrency=1,
        sink=records.append,
        apply_config=lambda config: None,
    )
    assert [r["ok"] for r in records] == [True, False, True]
    assert records[1]["error_type"] == "parse"
    assert records[0]["derived"] == {"triggered": False}
