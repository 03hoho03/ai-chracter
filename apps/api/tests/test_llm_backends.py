"""공급자 구현 등록부와 해석 규칙.

호출 하나가 어느 구현으로 가는지는 세 단계로 정한다. 모델을 고를 수 없는 호출에 실려 온 상위 모델은 기본 모델로 읽고,
배정(env 가 정책 표의 행보다 앞선다)이 있으면 그 구현이 그 모델을 서비스할 때만 따르고, 아니면 모델의 기본 구현이다.
지금 등록된 구현으로는 기동 검증의 능력 규칙이 걸리는 배정을 만들 수 없어(구조화를 받지 못하는 구현은 구조화 호출의
모델도 서비스하지 않는다), 그 규칙과 구조화 호출이 배정을 타는 경로는 테스트에서만 등록하는 가짜 구현 행으로 본다.
"""

import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal, cast, get_args

import pytest
from pydantic import BaseModel

from api.chat import turn_engine
from api.core.config import Settings, settings
from api.llm import routing
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.backends import (
    BACKENDS,
    DEFAULT_CHAT_MODEL,
    MODEL_BACKENDS,
    BackendCapabilities,
    BackendSpec,
    ChatModelId,
    PromptSetModelId,
    assignment_errors,
    call_site_model,
    pick_backend,
)
from api.llm.call_policy import CALL_POLICIES, BackendId, LLMCallSite
from api.llm.chat_models import backend_model_id
from api.llm.client import LLMCallContext, LLMClient
from api.llm.pricing import MODEL_PRICES, estimate_cost_usd
from api.llm.routing import RoutingLLMClient, resolve_backend
from replay.assemble import GenerationInput, sent_model_id

_FAKE = cast(BackendId, "fake")
_FAKE_SENT_ID = "fake-backend-model-id"
_MODELS: tuple[ChatModelId, ...] = get_args(ChatModelId)


def _default_setting(name: str) -> str:
    """기동 검증이 읽는 설정을 코드 기본값으로 읽는다 — env 없이 뜬 서버와 같다."""
    return str(Settings.model_fields[name].default)


def _models_of(call_site: LLMCallSite) -> tuple[ChatModelId, ...]:
    return _MODELS if CALL_POLICIES[call_site].model_selectable else (DEFAULT_CHAT_MODEL,)


def _register_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    structured: Literal["native_schema", "none"] = "native_schema",
    structured_images: bool = True,
    structured_with_instruction: bool = True,
    credential_env: tuple[tuple[str, str], ...] = (),
) -> None:
    """기본 모델을 두 번째 구현으로 서비스하는 가짜 행. 보내는 id 는 소설화 모델 설정에서 읽는다(아무 문자열 설정이면
    되고, 기본 구현의 id 와 다른 값이어야 해석 결과가 드러난다)."""
    spec = BackendSpec(
        capabilities=BackendCapabilities(
            structured=structured,
            structured_images=structured_images,
            structured_with_instruction=structured_with_instruction,
        ),
        model_id_settings={"gemini": "gemini_novelize_model_name"},
        credential_env=credential_env,
    )
    monkeypatch.setitem(BACKENDS, _FAKE, spec)
    monkeypatch.setitem(MODEL_BACKENDS, "gemini", ("gemini", _FAKE))
    monkeypatch.setattr(settings, "gemini_novelize_model_name", _FAKE_SENT_ID)


def _assign(monkeypatch: pytest.MonkeyPatch, assignments: dict[LLMCallSite, BackendId]) -> None:
    monkeypatch.setattr(settings, "llm_call_site_backends", assignments)


# ── 등록부 일관성 ──────────────────────────────────────────────────────────────────────────


def test_every_backend_id_has_exactly_one_registry_row() -> None:
    assert set(BACKENDS) == set(get_args(BackendId))


def test_the_default_order_table_and_the_served_models_agree() -> None:
    """모델 → 구현 표(기본 순서)와 구현마다 서비스하는 모델은 같은 사실의 두 방향이다. 어긋나면 기본 구현이 그 모델의
    id 를 모르거나, 서비스하는 구현이 해석에서 빠진다."""
    assert set(MODEL_BACKENDS) == set(get_args(PromptSetModelId))
    for model, ordered in MODEL_BACKENDS.items():
        assert ordered, model
        for backend in ordered:
            assert model in BACKENDS[backend].model_id_settings, (model, backend)
    for backend, spec in BACKENDS.items():
        for model in spec.model_id_settings:
            assert backend in MODEL_BACKENDS[model], (model, backend)


def test_registry_rows_name_string_settings() -> None:
    """등록부는 설정 이름만 담는다 — 오타가 난 이름은 첫 호출이나 기동에서야 터지므로 여기서 잡는다."""
    for spec in BACKENDS.values():
        names = [*spec.model_id_settings.values(), *(attr for _, attr in spec.credential_env)]
        for name in names:
            assert Settings.model_fields[name].annotation is str, name


def test_the_declared_default_id_of_every_served_model_has_a_price() -> None:
    """단가표에 없는 id 면 어드민 원가가 "단가 없음" 이 된다 — 구현 행을 더하며 단가 줄을 빠뜨리지 않게."""
    for spec in BACKENDS.values():
        for setting_name in spec.model_id_settings.values():
            assert Settings.model_fields[setting_name].default in MODEL_PRICES, setting_name


@pytest.mark.parametrize("call_site", get_args(LLMCallSite))
def test_writing_down_the_default_backend_of_a_call_is_accepted_at_boot(call_site: LLMCallSite) -> None:
    """지금 기본으로 가는 구현을 그대로 배정하면 아무것도 바뀌지 않으므로 기동 검증이 받아야 한다 — 받지 않으면 능력 표나
    호출 방식 표가 지금 라우팅과 어긋난 것이다."""
    for model in _models_of(call_site):
        assert assignment_errors({call_site: MODEL_BACKENDS[model][0]}, _default_setting) == []


# ── 해석 규칙 ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("call_site", "model", "assigned", "expected"),
    [
        # Gemini 는 상위 모델을 서비스하지 않는다 — 배정을 두고도 모델의 기본 구현으로 간다.
        ("chat_generate", "sonnet", "gemini", ("sonnet", "bedrock")),
        ("chat_generate", "opus", "gemini", ("opus", "bedrock")),
        # Bedrock 은 기본 모델을 서비스하지 않는다.
        ("chat_generate", "gemini", "bedrock", ("gemini", "gemini")),
        ("novelize_chapter", "sonnet", "bedrock", ("sonnet", "bedrock")),
        # 모델을 고를 수 없는 호출에 실려 온 상위 모델은 배정과 무관하게 기본 모델로 읽힌다.
        ("chat_stat_judgment", "sonnet", "gemini", ("gemini", "gemini")),
    ],
)
def test_an_assignment_is_followed_only_where_the_backend_serves_the_model(
    call_site: LLMCallSite, model: ChatModelId, assigned: BackendId, expected: tuple[ChatModelId, BackendId]
) -> None:
    assert pick_backend(call_site, model, {call_site: assigned}) == expected


def test_a_backend_on_the_policy_row_is_followed_and_the_env_assignment_wins_over_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_fake(monkeypatch)
    monkeypatch.setitem(
        CALL_POLICIES, "chat_stat_judgment", dataclasses.replace(CALL_POLICIES["chat_stat_judgment"], backend=_FAKE)
    )

    assert pick_backend("chat_stat_judgment", "gemini", {}) == ("gemini", _FAKE)
    assert pick_backend("chat_stat_judgment", "gemini", {"chat_stat_judgment": "gemini"}) == ("gemini", "gemini")


# ── 기동 검증의 능력·자격 규칙(가짜 구현 행) ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("call_site", "capabilities", "rejected"),
    [
        ("chat_stat_judgment", {"structured": "none"}, True),
        ("publish_filter_story", {"structured_images": False}, True),
        ("publish_filter_story", {"structured_with_instruction": False}, False),
        ("novelize_revise", {"structured_with_instruction": False}, True),
        ("novelize_revise", {"structured_images": False}, False),
        # 스트리밍은 모든 구현이 받는다.
        ("preview_generate", {"structured": "none", "structured_images": False}, False),
    ],
)
def test_an_assignment_whose_backend_cannot_take_the_call_kind_is_rejected(
    monkeypatch: pytest.MonkeyPatch, call_site: LLMCallSite, capabilities: dict[str, Any], rejected: bool
) -> None:
    """구조화 출력을 받지 못하는 구현에 판정을 배정하면 첫 판정에서야 실패한다 — 기동에서 막는다."""
    _register_fake(monkeypatch, **capabilities)

    errors = assignment_errors({call_site: _FAKE}, _default_setting)

    assert bool(errors) is rejected
    if rejected:
        assert call_site in errors[0]


@pytest.mark.parametrize(("value", "rejected"), [("", True), ("  ", True), ("key", False)])
def test_an_assignment_that_moves_a_call_needs_the_backend_credentials(
    monkeypatch: pytest.MonkeyPatch, value: str, rejected: bool
) -> None:
    """자격 없이 뜨면 배정된 호출이 런타임에 실패한다. 기본 구현을 그대로 적은 배정은 경로를 바꾸지 않으므로 자격을 묻지
    않는다(Bedrock 에 상위 모델을 배정한 경우가 그렇다 — 설정 테스트가 키 없이 기동하는 것을 본다)."""
    _register_fake(monkeypatch, credential_env=(("FAKE_API_KEY", "fake_api_key"),))
    read = {"fake_api_key": value}

    errors = assignment_errors({"chat_stat_judgment": _FAKE}, lambda name: read[name] if name in read else _default_setting(name))

    assert bool(errors) is rejected
    if rejected:
        assert "FAKE_API_KEY" in errors[0]


# ── 라우터와 해석 결과를 쓰는 곳 ─────────────────────────────────────────────────────────────


class _Parsed(BaseModel):
    ok: bool


class _Named(LLMClient):
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


async def test_structured_calls_resolve_with_the_default_model_and_follow_an_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """구조화 호출은 방의 모델이 아니라 기본 모델로 해석한다 — 그래도 배정은 탄다. 방이 상위 모델이어도 판정이 그 모델로
    가지 않고, 판정을 다른 구현으로 옮기는 배정은 먹어야 한다."""
    _register_fake(monkeypatch)
    _assign(monkeypatch, {"chat_stat_judgment": _FAKE, "novelize_revise": _FAKE, "preview_generate": _FAKE})
    reached: list[str] = []
    router = RoutingLLMClient(
        _Named("gemini", reached),
        factories={"bedrock": lambda: _Named("bedrock", reached), _FAKE: lambda: _Named("fake", reached)},
    )

    await router.generate_structured(
        "p", _Parsed, usage=LLMCallContext("chat_stat_judgment", None, None, model="sonnet")
    )
    await router.generate_structured_with_instruction(
        "p", _Parsed, system_instruction="s", usage=LLMCallContext("novelize_revise", None, None)
    )
    [_ async for _ in router.generate("p", usage=LLMCallContext("preview_generate", None, None))]
    await router.generate_structured("p", _Parsed, usage=LLMCallContext("chat_ending_judgment", None, None))

    assert reached == ["fake", "fake", "fake", "gemini"]


def test_the_resolved_id_is_the_id_the_resolved_backend_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    _assign(monkeypatch, {"chat_generate": _FAKE})

    assert resolve_backend("chat_generate", "gemini") == (_FAKE, _FAKE_SENT_ID)
    assert resolve_backend("chat_generate", "sonnet") == ("bedrock", backend_model_id("bedrock", "sonnet"))
    assert resolve_backend("chat_stat_judgment", "gemini") == ("gemini", settings.gemini_model_name)


def test_the_prompt_dump_names_the_id_of_the_resolved_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """덤프의 `model` 은 그 턴이 실제로 보낸 id 여야 재현할 수 있다 — 배정으로 구현이 바뀌면 그 구현의 id 다."""
    dump_path = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump_path))
    _register_fake(monkeypatch)
    _assign(monkeypatch, {"chat_generate": _FAKE})

    turn_engine._dump_prompt(
        room_id=None, call_site="chat_generate", model="gemini", turn=1, prompt="p", system_instruction="s"
    )
    turn_engine._dump_prompt(
        room_id=None, call_site="preview_generate", model="gemini", turn=1, prompt="p", system_instruction="s"
    )

    records = [json.loads(line) for line in dump_path.read_text(encoding="utf-8").splitlines()]
    assert [r["model"] for r in records] == [_FAKE_SENT_ID, settings.gemini_model_name]


def test_the_replay_compares_against_the_id_its_own_call_site_resolves_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """리플레이는 다시 생성하는 호출 위치로 보낸다 — 덤프와 비교할 "지금 보낼 id" 도 그 호출 위치의 해석이어야 한다."""
    _register_fake(monkeypatch)

    _assign(monkeypatch, {"chat_generate": _FAKE})
    assert sent_model_id("gemini") == settings.gemini_model_name

    _assign(monkeypatch, {"replay_generate": _FAKE})
    assert sent_model_id("gemini") == _FAKE_SENT_ID
    assert sent_model_id("opus") == backend_model_id("bedrock", "opus")


# ── Anthropic API 직접 구현 ─────────────────────────────────────────────────────────────────


def test_premium_models_resolve_to_bedrock_unless_assigned_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic 구현은 상위 모델의 두 번째 구현이다 — 배정이 없으면 지금처럼 Bedrock 으로 간다."""
    _assign(monkeypatch, {})
    assert resolve_backend("chat_generate", "opus") == ("bedrock", settings.bedrock_opus_model_id)

    _assign(monkeypatch, {"chat_generate": "anthropic", "novelize_chapter": "anthropic"})
    assert resolve_backend("chat_generate", "opus") == ("anthropic", settings.anthropic_opus_model_id)
    assert resolve_backend("chat_generate", "sonnet") == ("anthropic", settings.anthropic_sonnet_model_id)
    assert resolve_backend("novelize_chapter", "opus") == ("anthropic", settings.anthropic_opus_model_id)
    # 기본 모델은 Anthropic 이 서비스하지 않아 배정을 두고도 Gemini 다.
    assert resolve_backend("chat_generate", "gemini") == ("gemini", settings.gemini_model_name)
    # 배정하지 않은 호출은 그대로다.
    assert resolve_backend("replay_generate", "opus") == ("bedrock", settings.bedrock_opus_model_id)


async def test_the_router_builds_the_anthropic_client_only_when_a_call_is_assigned_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """키가 없을 때의 실패가 의존성 해석이 아니라 그 호출의 `LLMClientError` 로 나야 채팅이 환불 경로를 탄다 — 구현을
    만드는 것만으로는 SDK 를 만들지 않는다."""
    monkeypatch.setattr(settings, "anthropic_direct_api_key", "")
    built = routing._FACTORIES["anthropic"]()
    assert isinstance(built, AnthropicLLMClient)

    reached: list[str] = []
    router = RoutingLLMClient(
        _Named("gemini", reached),
        factories={"bedrock": lambda: _Named("bedrock", reached), "anthropic": lambda: _Named("anthropic", reached)},
    )
    _assign(monkeypatch, {"chat_generate": "anthropic"})

    [_ async for _ in router.generate("p", usage=LLMCallContext("chat_generate", None, None, model="opus"))]
    [_ async for _ in router.generate("p", usage=LLMCallContext("novelize_chapter", None, None, model="opus"))]

    assert reached == ["anthropic", "bedrock"]


def _replayed(chat_model: ChatModelId) -> GenerationInput:
    return GenerationInput(
        turn=1,
        variant="model",
        arm="a",
        swap_label=None,
        prompt="가" * 1600,
        system_instruction="",
        user_label="나",
        chat_model=chat_model,
        history_messages=0,
        content_version_id=uuid.uuid4(),
        chosen_set={},
    )


@pytest.mark.parametrize(
    ("assignments", "model_setting", "cap_setting"),
    [
        pytest.param({}, "bedrock_opus_model_id", "bedrock_chat_max_tokens", id="bedrock"),
        pytest.param(
            {"replay_generate": "anthropic"}, "anthropic_opus_model_id", "anthropic_chat_max_tokens", id="anthropic"
        ),
    ],
)
def test_the_replay_cost_ceiling_uses_the_output_cap_of_the_backend_the_call_resolves_to(
    monkeypatch: pytest.MonkeyPatch, assignments: dict[LLMCallSite, BackendId], model_setting: str, cap_setting: str
) -> None:
    """원가를 모르고 끝난 호출은 출력 상한을 다 쓴 것으로 센다 — 상한은 그 호출이 실제로 간 구현의 것이어야 한다."""
    _assign(monkeypatch, assignments)
    replayed = _replayed("opus")

    expected = estimate_cost_usd(
        getattr(settings, model_setting),
        input_tokens=replayed.estimated_input_tokens(),
        cached_tokens=0,
        output_tokens=getattr(settings, cap_setting),
        thoughts_tokens=0,
    )
    assert expected is not None
    assert replayed.cost_ceiling_usd() == pytest.approx(expected)


# ── 판정·요약 모델 ──────────────────────────────────────────────────────────────────────────

_JUDGMENT_SETTINGS = ("stat_judgment_model", "ending_judgment_model", "image_judgment_model", "memory_summary_model")


def test_the_judgment_only_model_is_served_by_both_claude_backends_with_bedrock_first() -> None:
    """판정 전용 `haiku` 는 글쓰기 모델이 아니라서 채팅 선택에는 없지만, 등록부에는 행이 있어야 판정 모델로 고를 수 있다."""
    assert MODEL_BACKENDS["haiku"] == ("bedrock", "anthropic")
    assert BACKENDS["bedrock"].model_id_settings["haiku"] == "bedrock_haiku_model_id"
    assert BACKENDS["anthropic"].model_id_settings["haiku"] == "anthropic_haiku_model_id"
    assert "haiku" not in get_args(ChatModelId)


@pytest.mark.parametrize("backend", ["bedrock", "anthropic"])
def test_both_claude_backends_take_plain_structured_calls_but_not_images_or_a_separate_instruction(
    backend: BackendId,
) -> None:
    """구조화 출력은 Claude 공용 조각 하나로 두 구현이 함께 받는다 — 한쪽만 올리면 다른 쪽 배정이 기동에서 거부된다."""
    assert BACKENDS[backend].capabilities == BackendCapabilities(
        structured="json_schema", structured_images=False, structured_with_instruction=False
    )


def test_each_judgment_and_summary_call_reads_the_model_setting_of_its_kind() -> None:
    expected_by_kind = {"stat": "stat_judgment_model", "ending": "ending_judgment_model", "image": "image_judgment_model"}
    for call_site, policy in CALL_POLICIES.items():
        if policy.judgment_kind is not None:
            assert policy.model_setting == expected_by_kind[policy.judgment_kind], call_site
        elif call_site == "chat_memory_summary":
            assert policy.model_setting == "memory_summary_model"
        else:
            assert policy.model_setting is None, call_site


def test_a_call_reads_its_model_from_its_setting_and_the_rest_use_the_default_model() -> None:
    read = {"stat_judgment_model": "haiku", "memory_summary_model": "opus"}

    def setting(name: str) -> str:
        return read.get(name, "gemini")

    assert call_site_model("chat_stat_judgment", setting) == "haiku"
    assert call_site_model("preview_stat_judgment", setting) == "haiku"
    assert call_site_model("chat_memory_summary", setting) == "opus"
    assert call_site_model("chat_ending_judgment", setting) == "gemini"
    # 설정 칸이 없는 구조화 호출(심사·소설화)과 생성 호출은 기본 모델이다.
    assert call_site_model("novelize_revise", setting) == DEFAULT_CHAT_MODEL
    assert call_site_model("chat_generate", setting) == DEFAULT_CHAT_MODEL


@pytest.mark.parametrize(
    ("call_site", "model", "call_model", "assignments", "expected"),
    [
        # 판정 호출은 판정 모델로 간다. 배정이 없으면 그 모델의 기본 구현이다.
        ("chat_stat_judgment", "haiku", "haiku", {}, ("haiku", "bedrock")),
        ("chat_memory_summary", "opus", "opus", {}, ("opus", "bedrock")),
        ("preview_ending_judgment", "sonnet", "sonnet", {"preview_ending_judgment": "anthropic"}, ("sonnet", "anthropic")),
        # 방의 모델이 실려 와도 판정 모델로 읽힌다.
        ("chat_stat_judgment", "opus", "haiku", {}, ("haiku", "bedrock")),
        ("chat_stat_judgment", "opus", "gemini", {}, ("gemini", "gemini")),
        # 설정 칸이 없는 비선택 호출은 기본 모델이다.
        ("novelize_revise", "haiku", "gemini", {}, ("gemini", "gemini")),
    ],
)
def test_a_call_that_cannot_pick_a_model_goes_with_its_own_model(
    call_site: LLMCallSite,
    model: PromptSetModelId,
    call_model: PromptSetModelId,
    assignments: dict[LLMCallSite, BackendId],
    expected: tuple[PromptSetModelId, BackendId],
) -> None:
    assert pick_backend(call_site, model, assignments, call_model=call_model) == expected


async def test_structured_calls_go_where_the_judgment_model_of_their_kind_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """판정 모델을 바꾸면 그 종류의 판정(채팅·미리보기)만 옮겨 간다. 방의 모델(여기서는 Opus)은 판정 경로에 아무 영향이
    없다 — 판정은 방의 모델이 아니라 판정 모델 설정으로 해석한다."""
    for name in _JUDGMENT_SETTINGS:
        monkeypatch.setattr(settings, name, "gemini")
    monkeypatch.setattr(settings, "stat_judgment_model", "haiku")
    monkeypatch.setattr(settings, "memory_summary_model", "sonnet")
    _assign(monkeypatch, {"chat_memory_summary": "anthropic"})
    reached: list[str] = []
    router = RoutingLLMClient(
        _Named("gemini", reached),
        factories={"bedrock": lambda: _Named("bedrock", reached), "anthropic": lambda: _Named("anthropic", reached)},
    )

    for call_site in (
        "chat_stat_judgment",
        "preview_stat_judgment",
        "chat_ending_judgment",
        "chat_situational_image",
        "chat_media_book_image",
        "chat_memory_summary",
    ):
        await router.generate_structured(
            "p", _Parsed, usage=LLMCallContext(call_site, None, None, model="opus")
        )

    assert reached == ["bedrock", "bedrock", "gemini", "gemini", "gemini", "anthropic"]


def test_the_judgment_dump_names_the_id_the_judgment_model_sends(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """판정 덤프의 `model` 도 실제로 보낸 id 다 — 판정 모델을 바꾸면 그 모델의 id, Gemini 면 판정 종류의 Gemini 모델이다."""
    dump_path = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump_path))
    monkeypatch.setattr(settings, "stat_judgment_model", "haiku")
    monkeypatch.setattr(settings, "ending_judgment_model", "gemini")
    monkeypatch.setattr(settings, "gemini_ending_judgment_model_name", "ending-judge-x")

    for call_site in ("chat_stat_judgment", "chat_ending_judgment"):
        turn_engine._dump_judgment_prompt(
            room_id=None, call_site=call_site, turn=1, schema="S", prompt="p"
        )

    records = [json.loads(line) for line in dump_path.read_text(encoding="utf-8").splitlines()]
    assert [r["model"] for r in records] == [settings.bedrock_haiku_model_id, "ending-judge-x"]
