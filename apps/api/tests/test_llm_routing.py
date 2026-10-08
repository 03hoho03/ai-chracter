import logging
from collections.abc import AsyncIterator
from typing import Any, get_args

import pytest
from pydantic import BaseModel

from api.llm.chat_models import ChatModelId
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient
from api.llm.routing import RoutingLLMClient


class _Result(BaseModel):
    ok: bool


class _Recorder(LLMClient):
    """어느 내부 클라이언트로 갔는지와 받은 인자를 남기는 가짜."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append(("generate", (prompt, system_instruction, stop_sequences, usage)))
        yield self.name

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[Any],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> Any:
        self.calls.append(("generate_structured", usage))
        return _Result(ok=True)

    async def generate_structured_with_instruction(
        self,
        prompt: str,
        response_schema: type[Any],
        *,
        system_instruction: str,
        usage: LLMCallContext,
    ) -> Any:
        self.calls.append(("generate_structured_with_instruction", usage))
        return _Result(ok=True)


def _router() -> tuple[RoutingLLMClient, _Recorder, list[_Recorder]]:
    gemini = _Recorder("gemini")
    built: list[_Recorder] = []

    def factory() -> LLMClient:
        bedrock = _Recorder("bedrock")
        built.append(bedrock)
        return bedrock

    return RoutingLLMClient(gemini, bedrock_factory=factory), gemini, built


_MODEL_SELECTABLE: frozenset[LLMCallSite] = frozenset({"chat_generate", "novelize_chapter", "replay_generate"})


@pytest.mark.parametrize("model", get_args(ChatModelId))
@pytest.mark.parametrize("call_site", get_args(LLMCallSite))
async def test_generate_goes_to_bedrock_only_for_a_premium_model_at_a_model_selectable_call_site(
    call_site: LLMCallSite, model: ChatModelId
) -> None:
    """판정·요약·미리보기·심사는 모델이 잘못 실려 와도 Gemini 로 간다 — 비싼 모델 원가가 사용자가 고른 적 없는 호출에
    붙지 않게."""
    router, gemini, _ = _router()

    tokens = [t async for t in router.generate("p", usage=LLMCallContext(call_site, None, None, model=model))]

    expected = "bedrock" if model != "gemini" and call_site in _MODEL_SELECTABLE else "gemini"
    assert tokens == [expected]
    assert len(gemini.calls) == (1 if expected == "gemini" else 0)


@pytest.mark.parametrize("model", ["sonnet", "opus"])
async def test_a_replayed_turn_with_a_premium_model_goes_to_bedrock(model: ChatModelId) -> None:
    """Claude 로 쓴 턴도 다시 생성해 비교할 수 있어야 한다 — 다시 생성하는 호출이 Gemini 로 새면 다른 모델의 글을 비교한다."""
    router, gemini, built = _router()

    tokens = [t async for t in router.generate("p", usage=LLMCallContext("replay_generate", None, None, model=model))]

    assert tokens == ["bedrock"]
    assert gemini.calls == []
    assert len(built) == 1


async def test_generate_forwards_every_argument_unchanged() -> None:
    router, gemini, built = _router()
    usage = LLMCallContext("chat_generate", None, None, model="opus")

    [_ async for _ in router.generate("p", "sys", ["\nU:"], usage=usage)]
    [_ async for _ in router.generate("q", "sys2", None, usage=LLMCallContext("chat_generate", None, None))]

    assert built[0].calls == [("generate", ("p", "sys", ["\nU:"], usage))]
    assert gemini.calls[0][1][:3] == ("q", "sys2", None)


async def test_the_bedrock_client_is_built_once_and_only_when_first_needed() -> None:
    """Bedrock SDK 는 import 비용이 있고 운영은 상위 모델이 꺼져 있다 — Gemini 만 쓰는 프로세스는 만들지 않는다."""
    router, _, built = _router()

    [_ async for _ in router.generate("p", usage=LLMCallContext("chat_generate", None, None))]
    assert built == []

    for model in ("sonnet", "opus"):
        [_ async for _ in router.generate("p", usage=LLMCallContext("chat_generate", None, None, model=model))]
    assert len(built) == 1
    assert len(built[0].calls) == 2


async def test_a_premium_model_at_another_call_site_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    router, _, _ = _router()

    with caplog.at_level(logging.WARNING, logger="api.llm.routing"):
        [_ async for _ in router.generate("p", usage=LLMCallContext("chat_stat_judgment", None, None, model="sonnet"))]

    assert "chat_stat_judgment" in caplog.text and "sonnet" in caplog.text


@pytest.mark.parametrize("model", get_args(ChatModelId))
async def test_structured_calls_always_go_to_gemini(model: ChatModelId) -> None:
    """Bedrock 의 Claude 는 네이티브 구조화 출력이 없어 판정 계열은 언제나 Gemini 다."""
    router, gemini, built = _router()
    usage = LLMCallContext("chat_generate", None, None, model=model)

    await router.generate_structured("p", _Result, usage=usage)
    await router.generate_structured_with_instruction("p", _Result, system_instruction="s", usage=usage)

    assert [name for name, _ in gemini.calls] == ["generate_structured", "generate_structured_with_instruction"]
    assert built == []
