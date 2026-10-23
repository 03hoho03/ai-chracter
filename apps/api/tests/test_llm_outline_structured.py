"""구성 흐름의 구성안 두 호출(`novelize_outline`·`novelize_episode_outline`)은 사용자가 고른 모델로 가는 지시문 구조화 호출이다.

다른 구조화 호출(판정·요약·심사·문단 수정·경계 제안)은 호출에 실린 모델을 보지 않고 그 호출의 모델로 간다 — 이 둘만 실린 모델을
따른다. 그래서 라우터가 실린 모델로 구현을 고르고, Claude 두 구현이 그 모델의 id 로 지시문(`system`)과 함께 보낸다. Bedrock 은
사고를 끌 수 있는 모델에서만 끈다. 배정은 장 생성 호출 위치의 것을 물려받는다.

Claude 구현은 실제 SDK 를 쓰고 전송 계층만 바꿔 끼운다 — 요청 본문이 실제로 어떻게 실리는지 본다."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, get_args

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ValidationError

from api.core.config import Settings, settings
from api.llm import anthropic_api as anthropic_module
from api.llm import backends
from api.llm import bedrock as bedrock_module
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.backends import BACKENDS, BackendCapabilities, assignment_errors, pick_backend
from api.llm.bedrock import BedrockLLMClient
from api.llm.call_policy import CALL_POLICIES
from api.llm.chat_models import ChatModelId
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient
from api.llm.routing import RoutingLLMClient

Handler = Callable[[httpx2.Request], httpx2.Response]

_OUTLINE_CALL_SITES: tuple[LLMCallSite, ...] = ("novelize_outline", "novelize_episode_outline")


class _Outline(BaseModel):
    episodes: list[str]


def _reply() -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": [{"type": "text", "text": '{"episodes": ["1화"]}'}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 9},
    }


def _capture(seen: list[httpx2.Request]) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_reply())

    return handler


@pytest.fixture(autouse=True)
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def record_usage(call_site: str, model: str, usage_metadata: object | None) -> None:
        calls.append((call_site, model))

    monkeypatch.setattr(bedrock_module, "record_usage", record_usage)
    monkeypatch.setattr(anthropic_module, "record_usage", record_usage)
    return calls


def _bedrock(monkeypatch: pytest.MonkeyPatch, seen: list[httpx2.Request]) -> LLMClient:
    monkeypatch.setattr(settings, "bedrock_access_key_id", "AKIATEST")
    monkeypatch.setattr(settings, "bedrock_secret_access_key", "secret-test")
    monkeypatch.setattr(settings, "bedrock_region", "ap-northeast-2")
    real = anthropic.AsyncAnthropicBedrock

    def build(**kwargs: Any) -> anthropic.AsyncAnthropicBedrock:
        return real(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_capture(seen))))

    monkeypatch.setattr(bedrock_module, "AsyncAnthropicBedrock", build)
    return BedrockLLMClient()


def _anthropic(monkeypatch: pytest.MonkeyPatch, seen: list[httpx2.Request]) -> LLMClient:
    monkeypatch.setattr(settings, "anthropic_direct_api_key", "sk-ant-test")
    real = anthropic.AsyncAnthropic

    def build(**kwargs: Any) -> anthropic.AsyncAnthropic:
        return real(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_capture(seen))))

    monkeypatch.setattr(anthropic_module, "AsyncAnthropic", build)
    return AnthropicLLMClient()


async def _outline(client: LLMClient, call_site: LLMCallSite, model: ChatModelId) -> _Outline:
    return await client.generate_structured_with_instruction(
        "구성안 본문", _Outline, system_instruction="구성안 지시문", usage=LLMCallContext(call_site, None, None, model=model)
    )


# ── Claude 두 구현 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("call_site", _OUTLINE_CALL_SITES)
@pytest.mark.parametrize("model", ["sonnet", "opus"])
async def test_bedrock_sends_the_chosen_models_id_with_the_instruction_as_system(
    monkeypatch: pytest.MonkeyPatch, recorded: list[tuple[str, str]], call_site: LLMCallSite, model: ChatModelId
) -> None:
    """구성안은 고른 모델의 id 로, 지시문은 `system` 으로, 본문은 user 메시지 하나로 간다. 출력 상한은 장 생성 몫이다(목록
    출력이 길다). 사용량은 실제로 보낸 id 로 남는다. 깨지는 시나리오: Opus 값을 내고 판정 모델(기본 Gemini)의 id 로 가거나,
    지시문이 본문에 섞여 원문 속 문장이 지시처럼 읽힌다."""
    seen: list[httpx2.Request] = []
    client = _bedrock(monkeypatch, seen)

    assert await _outline(client, call_site, model) == _Outline(episodes=["1화"])

    (request,) = seen
    sent = getattr(settings, f"bedrock_{model}_model_id")
    assert request.url.path == f"/model/{sent}/invoke"
    body = json.loads(request.content)
    assert body["system"] == "구성안 지시문"
    assert body["messages"] == [{"role": "user", "content": "구성안 본문"}]
    assert body["max_tokens"] == settings.bedrock_chapter_max_tokens
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": anthropic.transform_schema(_Outline)}
    assert recorded == [(call_site, sent)]


@pytest.mark.parametrize(
    ("model_id", "thinking"),
    [
        pytest.param("global.anthropic.claude-opus-4-6-v1", {"type": "disabled"}, id="can-turn-off"),
        pytest.param("global.anthropic.claude-opus-5-5-v1", None, id="always-thinks"),
        pytest.param("global.anthropic.claude-sonnet-5-5-v1", None, id="sonnet-always-thinks"),
    ],
)
async def test_bedrock_turns_thinking_off_only_where_the_model_takes_it(
    monkeypatch: pytest.MonkeyPatch, model_id: str, thinking: dict[str, str] | None
) -> None:
    """사고를 끌 수 있는 모델(4.x)에서는 끄고, 끌 수 없는 모델(5.x)에서는 싣지 않는다. 깨지는 시나리오: Opus 5.5 id 로 바꾼
    뒤 구성안 요청이 매번 거부되어 값을 낸 사용자가 늘 환불만 받는다."""
    monkeypatch.setattr(settings, "bedrock_opus_model_id", model_id)
    seen: list[httpx2.Request] = []

    await _outline(_bedrock(monkeypatch, seen), "novelize_outline", "opus")

    body = json.loads(seen[0].content)
    assert body.get("thinking") == thinking


@pytest.mark.parametrize("model", ["sonnet", "opus"])
async def test_anthropic_sends_the_chosen_models_id_with_the_instruction_as_system(
    monkeypatch: pytest.MonkeyPatch, recorded: list[tuple[str, str]], model: ChatModelId
) -> None:
    """직결 구현도 고른 모델의 id 와 `system` 을 싣는다. 사고는 싣지 않고, 깊이는 판정 몫이 아니라 장 생성 몫의 설정이다. 깨지는
    시나리오: 판정 원가를 줄이려 판정 깊이를 낮추면 값을 낸 Opus 구성안이 함께 낮은 깊이로 돈다."""
    monkeypatch.setattr(settings, "anthropic_structured_effort", "low")
    monkeypatch.setattr(settings, "anthropic_chapter_effort", "high")
    seen: list[httpx2.Request] = []

    await _outline(_anthropic(monkeypatch, seen), "novelize_episode_outline", model)

    (request,) = seen
    body = json.loads(request.content)
    sent = getattr(settings, f"anthropic_{model}_model_id")
    assert (body["model"], body["system"]) == (sent, "구성안 지시문")
    assert body["max_tokens"] == settings.anthropic_chapter_max_tokens
    assert "thinking" not in body
    assert body["output_config"]["effort"] == "high"
    assert recorded == [("novelize_episode_outline", sent)]


async def test_a_judgment_still_goes_with_its_own_model_not_the_one_carried(
    monkeypatch: pytest.MonkeyPatch, recorded: list[tuple[str, str]]
) -> None:
    """실린 모델을 따르는 것은 구성안 두 호출뿐이다 — 판정은 방의 모델이 실려 와도 판정 모델 설정의 id 로 간다. 깨지는 시나리오:
    방에서 Opus 를 고른 사용자의 매 턴 판정이 Opus 원가로 나간다."""
    monkeypatch.setattr(settings, "stat_judgment_model", "haiku")
    seen: list[httpx2.Request] = []
    client = _bedrock(monkeypatch, seen)

    await client.generate_structured(
        "판정", _Outline, usage=LLMCallContext("chat_stat_judgment", None, None, model="opus")
    )

    assert recorded == [("chat_stat_judgment", settings.bedrock_haiku_model_id)]


# ── 라우터 ─────────────────────────────────────────────────────────────────
class _Recorder(LLMClient):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append("generate")
        yield self.name

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[Any],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> Any:
        self.calls.append("generate_structured")
        return _Outline(episodes=[self.name])

    async def generate_structured_with_instruction(
        self,
        prompt: str,
        response_schema: type[Any],
        *,
        system_instruction: str,
        usage: LLMCallContext,
    ) -> Any:
        self.calls.append("generate_structured_with_instruction")
        return _Outline(episodes=[self.name])


@pytest.mark.parametrize("call_site", _OUTLINE_CALL_SITES)
@pytest.mark.parametrize(("model", "reached"), [("gemini", "gemini"), ("sonnet", "bedrock"), ("opus", "bedrock")])
async def test_the_router_sends_an_outline_to_the_backend_of_the_model_carried(
    call_site: LLMCallSite, model: ChatModelId, reached: str
) -> None:
    """구성안 구조화 호출은 실린 모델의 구현으로 간다(배정이 없으면 Claude 는 Bedrock). 깨지는 시나리오: Opus 값을 내고 Gemini
    구성안을 받는다 — 경고도 없이."""
    gemini = _Recorder("gemini")
    bedrock = _Recorder("bedrock")
    router = RoutingLLMClient(gemini, factories={"bedrock": lambda: bedrock})

    result = await _outline(router, call_site, model)

    assert result.episodes == [reached]


async def test_the_router_keeps_other_structured_calls_on_their_own_model() -> None:
    """문단 수정·경계 제안처럼 모델을 고르지 않는 구조화 호출은 상위 모델이 실려 와도 그 호출의 모델로 간다(지금 동작)."""
    gemini = _Recorder("gemini")
    bedrock = _Recorder("bedrock")
    router = RoutingLLMClient(gemini, factories={"bedrock": lambda: bedrock})

    for call_site in ("novelize_revise", "novelize_boundary"):
        await _outline(router, call_site, "opus")

    assert (len(gemini.calls), bedrock.calls) == (2, [])


# ── 배정과 기동 검증 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("call_site", _OUTLINE_CALL_SITES)
def test_an_outline_call_follows_the_chapter_calls_assignment(call_site: LLMCallSite) -> None:
    """구성안 호출은 장 생성 호출 위치의 배정을 물려받는다 — 운영 env 가 장 생성만 Anthropic 직결로 배정해도 구성안이 같은
    구현으로 간다. 자기 배정이 있으면 그것이 앞선다. 깨지는 시나리오: 운영 env 에 새 호출 위치를 적지 않으면 Opus 구성안이
    Bedrock(사고를 끌 수 없는 모델이면 매번 거부)으로 간다."""
    assert CALL_POLICIES[call_site].backend_from == "novelize_chapter"
    assert pick_backend(call_site, "opus", {"novelize_chapter": "anthropic"}) == ("opus", "anthropic")
    assert pick_backend(call_site, "opus", {"novelize_chapter": "anthropic", call_site: "bedrock"}) == (
        "opus",
        "bedrock",
    )
    assert pick_backend(call_site, "gemini", {"novelize_chapter": "anthropic"}) == ("gemini", "gemini")


def test_boot_refuses_when_the_backend_an_unassigned_outline_call_reaches_cannot_take_an_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """배정이 없어도 구성안 호출이 상위 모델로 실제로 갈 구현이 지시문 구조화를 받지 못하면 기동하지 않는다. 깨지는 시나리오:
    뜰 때는 조용하다가 첫 Opus 구성안에서야 실패한다."""
    spec = BACKENDS["bedrock"]
    monkeypatch.setitem(
        backends.BACKENDS,
        "bedrock",
        type(spec)(
            capabilities=BackendCapabilities(
                structured="json_schema", structured_images=False, structured_with_instruction=False
            ),
            model_id_settings=spec.model_id_settings,
            credential_env=spec.credential_env,
        ),
    )

    errors = assignment_errors({}, lambda name: str(getattr(settings, name)))

    assert all(any(call_site in line for line in errors) for call_site in _OUTLINE_CALL_SITES)
    assert not any("novelize_chapter " in line for line in errors)


def test_the_novel_premium_switch_needs_the_credentials_of_the_backend_an_outline_call_reaches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """소설 상위 모델 스위치는 장 생성과 함께 구성안 두 호출이 갈 구현의 자격도 본다. 장 생성을 Anthropic 직결로 옮기고(키 있음)
    구성안 하나만 Bedrock 에 남긴 채 Bedrock 자격이 비면 기동하지 않는다 — 기본 구현을 그대로 적은 배정이라 배정 검증은 자격을
    묻지 않으므로 이 스위치 검증만 잡는다. 깨지는 시나리오: 켜진 채 뜬 뒤 Opus 구성안이 매번 자격 오류로 실패·환불된다."""
    for key in ("BEDROCK_ACCESS_KEY_ID", "BEDROCK_SECRET_ACCESS_KEY", "BEDROCK_REGION", "LLM_CALL_SITE_BACKENDS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NOVELIZE_PREMIUM_MODELS_ENABLED", "true")
    monkeypatch.setenv("LLM_CALL_SITE_BACKENDS", "novelize_chapter:anthropic,novelize_episode_outline:anthropic")
    Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("LLM_CALL_SITE_BACKENDS", "novelize_chapter:anthropic,novelize_outline:bedrock")
    with pytest.raises(ValidationError, match="BEDROCK_ACCESS_KEY_ID"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_only_the_outline_calls_are_model_selectable_structured_calls() -> None:
    """실린 모델을 따르는 구조화 호출은 구성안 둘뿐이다 — 다른 호출이 이 무리에 들면 사용자가 고른 적 없는 비싼 모델 원가가
    붙는다."""
    selectable_structured = {
        call_site
        for call_site, policy in CALL_POLICIES.items()
        if policy.model_selectable and policy.call_kind != "stream"
    }

    assert selectable_structured == set(_OUTLINE_CALL_SITES)
    assert set(_OUTLINE_CALL_SITES) <= set(get_args(LLMCallSite))
