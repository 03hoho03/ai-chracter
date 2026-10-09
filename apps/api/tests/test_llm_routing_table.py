"""라우팅 클라이언트가 호출 위치(`LLMCallSite`) × 고른 모델 × 메서드마다 어느 구현에 닿는지와, 그때 경고를 남기는지를
한 표로 고정한다. 공급자 갈래를 고르는 코드를 옮겨도 이 표가 그대로여야 한다.

호출 정책 표의 고정(`test_llm_call_policy_snapshot.py`)은 상위 모델 하나와 메서드 둘만 보므로, 여기서는 세 모델과 지시문
분리 구조화 메서드까지 전부 본다. 경고는 라우팅 모듈의 로거(`api.llm.routing`) 이름으로 남은 것만 센다 — 운영 로그 검색이
그 이름을 쓴다.

표는 지금 동작을 기록한 것이다(`fixtures/llm_routing_table.json`). 다시 뜨는 법은 `factories._assert_characterization`.
"""

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import BaseModel

from api.llm.chat_models import ChatModelId
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient
from api.llm.routing import RoutingLLMClient
from factories import _assert_characterization, _assert_recorded_cases

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "llm_routing_table.json"

_CALL_SITES: tuple[LLMCallSite, ...] = get_args(LLMCallSite)
_MODELS: tuple[ChatModelId, ...] = get_args(ChatModelId)
_METHODS = ("generate", "generate_structured", "generate_structured_with_instruction")


class _Parsed(BaseModel):
    ok: bool


class _Named(LLMClient):
    """닿으면 자기 이름을 남기는 가짜 구현."""

    def __init__(self, name: str, reached: list[str]) -> None:
        self.name = name
        self._reached = reached

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self._reached.append(self.name)
        yield ""

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[Any],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> Any:
        self._reached.append(self.name)
        return _Parsed(ok=True)

    async def generate_structured_with_instruction(
        self,
        prompt: str,
        response_schema: type[Any],
        *,
        system_instruction: str,
        usage: LLMCallContext,
    ) -> Any:
        self._reached.append(self.name)
        return _Parsed(ok=True)


def _router(reached: list[str]) -> RoutingLLMClient:
    return RoutingLLMClient(_Named("gemini", reached), bedrock_factory=lambda: _Named("bedrock", reached))


async def _call(router: RoutingLLMClient, method: str, usage: LLMCallContext) -> None:
    if method == "generate":
        [_ async for _ in router.generate("p", usage=usage)]
    elif method == "generate_structured":
        await router.generate_structured("p", _Parsed, usage=usage)
    else:
        await router.generate_structured_with_instruction("p", _Parsed, system_instruction="s", usage=usage)


async def _routing_row(caplog: pytest.LogCaptureFixture, call_site: LLMCallSite) -> dict[str, dict[str, Any]]:
    row: dict[str, dict[str, Any]] = {}
    for model in _MODELS:
        row[model] = {}
        for method in _METHODS:
            reached: list[str] = []
            caplog.clear()
            with caplog.at_level(logging.WARNING):
                await _call(_router(reached), method, LLMCallContext(call_site, None, None, model=model))
            (implementation,) = reached
            warned = any(r.name == "api.llm.routing" and r.levelno >= logging.WARNING for r in caplog.records)
            row[model][method] = {"reached": implementation, "warned": warned}
    return row


def test_recorded_call_sites_are_exactly_the_parametrized_call_sites() -> None:
    _assert_recorded_cases(FIXTURE_PATH, _CALL_SITES)


@pytest.mark.parametrize("call_site", _CALL_SITES)
async def test_routing_per_call_site_model_and_method_matches_the_recorded_table(
    caplog: pytest.LogCaptureFixture, call_site: LLMCallSite
) -> None:
    _assert_characterization(FIXTURE_PATH, call_site, await _routing_row(caplog, call_site))
