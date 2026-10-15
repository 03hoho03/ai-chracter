"""판정·요약 모델 설정과 그 기동 검증.

판정 종류(스탯·엔딩·그림)와 기억 요약마다 문안 모델 id 하나를 고른다. 기본은 `gemini` 라 env 가 없으면 지금 동작 그대로다.
그 모델을 어느 구현이 서비스할지는 호출 위치 배정(`LLM_CALL_SITE_BACKENDS`)이 정하고, 배정이 없으면 모델의 기본 구현
(`haiku`·`sonnet`·`opus` → Bedrock)이다. 기동 검증은 판정 모델과 배정이 어긋나 배정이 조용히 무시되는 경우, 그리고 판정이
실제로 갈 구현의 자격이 빈 경우를 거부한다 — 배정이 없어 기본 구현으로 가는 경우도 본다."""

import dataclasses
from typing import get_args

import pytest
from pydantic import ValidationError

from api.core.config import Settings
from api.llm import backends
from api.llm.backends import PromptSetModelId
from api.llm.call_policy import CALL_POLICIES
from factories import PRODUCTION_ENV_NAMES, PRODUCTION_ENV_TYPED_VALUES, load_production_env

_MODEL_KEYS = (
    "STAT_JUDGMENT_MODEL",
    "ENDING_JUDGMENT_MODEL",
    "IMAGE_JUDGMENT_MODEL",
    "MEMORY_SUMMARY_MODEL",
    "MEMORY_EPISODE_MODEL",
    "MEMORY_FACT_MODEL",
)
_BEDROCK_KEYS = ("BEDROCK_ACCESS_KEY_ID", "BEDROCK_SECRET_ACCESS_KEY", "BEDROCK_REGION")
_ANTHROPIC_KEY = "ANTHROPIC_DIRECT_API_KEY"
_ASSIGN = "LLM_CALL_SITE_BACKENDS"
_HAIKU_ID_KEYS = ("BEDROCK_HAIKU_MODEL_ID", "ANTHROPIC_HAIKU_MODEL_ID")
_EFFORT_KEYS = ("ANTHROPIC_CHAT_EFFORT", "ANTHROPIC_STRUCTURED_EFFORT")
_BEDROCK_CREDENTIALS = {
    "BEDROCK_ACCESS_KEY_ID": "AKIATEST",
    "BEDROCK_SECRET_ACCESS_KEY": "secret",
    "BEDROCK_REGION": "ap-northeast-2",
}


def _load(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in (*_MODEL_KEYS, *_BEDROCK_KEYS, _ANTHROPIC_KEY, _ASSIGN, *_HAIKU_ID_KEYS, *_EFFORT_KEYS):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_every_judgment_and_summary_model_defaults_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load(monkeypatch)

    assert (
        loaded.stat_judgment_model,
        loaded.ending_judgment_model,
        loaded.image_judgment_model,
        loaded.memory_summary_model,
        loaded.memory_episode_model,
        loaded.memory_fact_model,
    ) == ("gemini", "gemini", "gemini", "gemini", "gemini", "gemini")
    assert loaded.bedrock_haiku_model_id == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    # 직결은 Haiku 5.5, Bedrock 은 Haiku 4.5 다 — 이 저장소의 판정 평가는 직결로만 하고 Bedrock 의 Haiku 5.5 구조화 출력은
    # 확인하지 않아 그쪽 id 는 옮기지 않았다.
    assert loaded.anthropic_haiku_model_id == "claude-haiku-5-5"


@pytest.mark.parametrize("key", [*_MODEL_KEYS, *_HAIKU_ID_KEYS])
@pytest.mark.parametrize("blank", ["", "  "])
def test_an_empty_env_line_reads_as_the_default(monkeypatch: pytest.MonkeyPatch, key: str, blank: str) -> None:
    loaded = _load(monkeypatch, **{key: blank})

    field = key.lower()
    assert getattr(loaded, field) == Settings.model_fields[field].default


@pytest.mark.parametrize("value", ["claude-haiku-4-5", "Haiku", "gpt"])
def test_a_model_outside_the_prompt_chains_refuses_to_start(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """판정 모델 값은 문안 체인의 모델 id 다(공급사 모델명이 아니다) — 모르는 값이면 판정이 첫 턴에서야 실패한다."""
    with pytest.raises(ValidationError):
        _load(monkeypatch, STAT_JUDGMENT_MODEL=value)


@pytest.mark.parametrize("key", _MODEL_KEYS)
@pytest.mark.parametrize("model", ["haiku", "sonnet", "opus"])
def test_a_claude_judgment_model_without_an_assignment_needs_bedrock_credentials(
    monkeypatch: pytest.MonkeyPatch, key: str, model: str
) -> None:
    """배정이 없으면 판정은 모델의 기본 구현(Bedrock)으로 간다 — 배정이 경로를 옮기지 않아도 자격이 빈 채로는 뜨지 않는다.
    빈 자격으로 SDK 를 만들면 R2 자격으로 서명되므로 구현이 호출 앞에서 막지만, 그때는 매 판정이 실패한다."""
    with pytest.raises(ValidationError, match="BEDROCK_ACCESS_KEY_ID"):
        _load(monkeypatch, **{key: model})

    assert getattr(_load(monkeypatch, **{key: model}, **_BEDROCK_CREDENTIALS), key.lower()) == model


@pytest.mark.parametrize(
    ("env", "call_site"),
    [
        # 판정 모델을 Gemini 가 서비스하지 않는다 — 해석이 조용히 Bedrock 으로 돌려 배정이 무시된다.
        pytest.param({"STAT_JUDGMENT_MODEL": "haiku", _ASSIGN: "chat_stat_judgment:gemini"}, "chat_stat_judgment", id="haiku-on-gemini"),
        # Bedrock 은 Gemini 판정 모델을 서비스하지 않는다.
        pytest.param({_ASSIGN: "chat_ending_judgment:bedrock"}, "chat_ending_judgment", id="gemini-on-bedrock"),
        pytest.param({_ASSIGN: "chat_memory_summary:anthropic", _ANTHROPIC_KEY: "k"}, "chat_memory_summary", id="gemini-on-anthropic"),
    ],
)
def test_an_assignment_whose_backend_does_not_serve_the_judgment_model_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], call_site: str
) -> None:
    with pytest.raises(ValidationError, match=call_site):
        _load(monkeypatch, **env, **_BEDROCK_CREDENTIALS)


def test_a_judgment_moved_to_anthropic_needs_its_key_and_not_bedrocks(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"STAT_JUDGMENT_MODEL": "haiku", _ASSIGN: "chat_stat_judgment:anthropic,preview_stat_judgment:anthropic"}

    with pytest.raises(ValidationError, match=_ANTHROPIC_KEY):
        _load(monkeypatch, **env)

    loaded = _load(monkeypatch, **env, **{_ANTHROPIC_KEY: "sk-ant-test"})
    assert loaded.llm_call_site_backends == {
        "chat_stat_judgment": "anthropic",
        "preview_stat_judgment": "anthropic",
    }
    assert loaded.bedrock_access_key_id == ""


def test_a_judgment_left_on_bedrock_while_its_preview_moves_to_anthropic_still_needs_bedrock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """채팅 판정과 미리보기 판정은 모델 설정을 함께 쓰지만 배정은 호출 위치마다다 — 한쪽만 옮기면 남은 쪽은 Bedrock 이다."""
    with pytest.raises(ValidationError, match="BEDROCK_ACCESS_KEY_ID"):
        _load(
            monkeypatch,
            STAT_JUDGMENT_MODEL="haiku",
            **{_ASSIGN: "chat_stat_judgment:anthropic", _ANTHROPIC_KEY: "sk-ant-test"},
        )


_HAIKU_ON_ANTHROPIC = {
    "STAT_JUDGMENT_MODEL": "haiku",
    _ASSIGN: "chat_stat_judgment:anthropic,preview_stat_judgment:anthropic",
    _ANTHROPIC_KEY: "sk-ant-test",
}


@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_startup_rejects_extreme_effort_when_a_structured_call_goes_to_haiku_5(
    monkeypatch: pytest.MonkeyPatch, effort: str
) -> None:
    """Haiku 5.x 직결 판정은 사고를 끄는데, 사고를 끈 요청은 깊이 high 까지만 받는다 — 그 위면 매 판정이 400 이다. 첫
    판정에서야 터지는 것보다 기동이 멈추는 편이 싸다."""
    with pytest.raises(ValidationError, match="ANTHROPIC_STRUCTURED_EFFORT"):
        _load(
            monkeypatch,
            **_HAIKU_ON_ANTHROPIC,
            ANTHROPIC_HAIKU_MODEL_ID="claude-haiku-5-5",
            ANTHROPIC_STRUCTURED_EFFORT=effort,
        )


@pytest.mark.parametrize(
    "env",
    [
        pytest.param(
            {**_HAIKU_ON_ANTHROPIC, "ANTHROPIC_HAIKU_MODEL_ID": "claude-haiku-5-5", "ANTHROPIC_STRUCTURED_EFFORT": "high"},
            id="high-is-the-ceiling-of-disabled-thinking",
        ),
        pytest.param(
            {**_HAIKU_ON_ANTHROPIC, "ANTHROPIC_HAIKU_MODEL_ID": "claude-haiku-4-5", "ANTHROPIC_STRUCTURED_EFFORT": "xhigh"},
            id="haiku-4-5-gets-no-effort-at-all",
        ),
        pytest.param(
            {**_HAIKU_ON_ANTHROPIC, "ANTHROPIC_HAIKU_MODEL_ID": "claude-haiku-5-5", "ANTHROPIC_CHAT_EFFORT": "xhigh"},
            id="chat-effort-is-not-the-judgments",
        ),
        pytest.param(
            {"STAT_JUDGMENT_MODEL": "haiku", "ANTHROPIC_STRUCTURED_EFFORT": "xhigh", **_BEDROCK_CREDENTIALS},
            id="haiku-on-bedrock",
        ),
    ],
)
def test_startup_accepts_extreme_effort_where_no_structured_call_turns_thinking_off(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    """사고를 끄는 구조화 호출(Haiku 5.x 로 가는 직결 판정·요약)이 없으면 깊이 상한도 없다. Bedrock 구현은 깊이를 보내지
    않고, Haiku 4.5 직결은 깊이를 싣지 않으며, 채팅 생성 깊이는 판정과 따로다."""
    _load(monkeypatch, **env)


def test_the_judgment_only_model_is_not_a_premium_writing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """상위 모델 스위치는 채팅·소설 글쓰기 모델의 경로만 본다. 판정 전용 `haiku` 가 그 검사에 섞이면, haiku 를 서비스하는
    구현이 글쓰기 모델과 다를 때 쓰지도 않는 경로의 자격을 요구한다 — 그 상황을 등록부에서 만들어 본다."""
    anthropic = backends.BACKENDS["anthropic"]
    monkeypatch.setitem(backends.MODEL_BACKENDS, "haiku", ("bedrock",))
    monkeypatch.setitem(
        backends.BACKENDS,
        "anthropic",
        dataclasses.replace(
            anthropic, model_id_settings={m: s for m, s in anthropic.model_id_settings.items() if m != "haiku"}
        ),
    )

    loaded = _load(
        monkeypatch,
        CHAT_PREMIUM_MODELS_ENABLED="true",
        NOVELIZE_PREMIUM_MODELS_ENABLED="true",
        **{
            _ASSIGN: "chat_generate:anthropic,replay_generate:anthropic,novelize_chapter:anthropic",
            _ANTHROPIC_KEY: "sk-ant-test",
        },
    )

    assert loaded.chat_premium_models_enabled


# ── 운영 env ────────────────────────────────────────────────────────────────────────────────


def test_the_production_env_judges_and_summarizes_with_haiku_through_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영은 판정·요약·기억 추출 모델 여섯을 모두 `haiku` 로 두고 그 호출 위치 전부를 Anthropic 직결로 배정해 돈다. Haiku 의
    실제 id·깊이 키는 운영에 없어 코드 기본값(직결 Haiku 5.5, 사고를 끈 요청이 받는 깊이)으로 뜨고, Bedrock 자격 없이 기동한다."""
    assert set(_MODEL_KEYS) <= set(PRODUCTION_ENV_NAMES)
    assert not {*_HAIKU_ID_KEYS, *_EFFORT_KEYS, *_BEDROCK_KEYS} & set(PRODUCTION_ENV_NAMES)

    loaded = load_production_env(monkeypatch)

    models: list[PromptSetModelId] = [
        loaded.stat_judgment_model,
        loaded.ending_judgment_model,
        loaded.image_judgment_model,
        loaded.memory_summary_model,
        loaded.memory_episode_model,
        loaded.memory_fact_model,
    ]
    assert models == ["haiku"] * 6
    assert loaded.anthropic_haiku_model_id.startswith("claude-haiku-5")
    judged = [cs for cs, policy in CALL_POLICIES.items() if policy.model_setting is not None]
    assert judged
    for call_site in judged:
        model = backends.call_site_model(call_site, lambda name: str(getattr(loaded, name)))
        assert backends.pick_backend(call_site, model, loaded.llm_call_site_backends, call_model=model) == (
            "haiku",
            "anthropic",
        ), call_site


_JUDGED_CALL_SITES = [cs for cs, policy in CALL_POLICIES.items() if policy.model_setting is not None]


def _production_assignment_without(call_site: str) -> str:
    return ",".join(pair for pair in PRODUCTION_ENV_TYPED_VALUES[_ASSIGN].split(",") if pair.split(":")[0] != call_site)


@pytest.mark.parametrize("call_site", _JUDGED_CALL_SITES)
def test_production_env_missing_one_judgment_assignment_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, call_site: str
) -> None:
    """운영 배정에서 판정·요약 호출 하나만 빠지면 그 호출은 `haiku` 의 기본 구현인 Bedrock 으로 가는데 운영엔 Bedrock 자격이
    없다 — 그 줄 하나 잃은 env 로는 새 이미지가 뜨지 않아야 한다(매 판정이 조용히 실패하는 대신)."""
    with pytest.raises(ValidationError, match="BEDROCK_ACCESS_KEY_ID"):
        load_production_env(monkeypatch, **{_ASSIGN: _production_assignment_without(call_site)})


@pytest.mark.parametrize("model_key", _MODEL_KEYS)
def test_production_env_missing_one_judgment_model_line_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, model_key: str
) -> None:
    """운영 env 에서 판정·요약 모델 줄 하나만 빠지면 그 모델은 `gemini` 로 돌아가는데 배정은 그 호출을 Anthropic 으로
    옮긴다 — Anthropic 은 Gemini 를 서비스하지 않아 배정이 조용히 무시되므로 기동을 거부해야 한다."""
    with pytest.raises(ValidationError, match="서비스하지 않는다"):
        load_production_env(monkeypatch, without=(model_key,))


def test_turning_on_a_claude_judgment_model_in_production_without_bedrock_credentials_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영에는 Bedrock 자격이 없다 — 판정 모델만 바꾸고 배정을 함께 옮기지 않으면 새 이미지가 뜨지 않는다(조용히 매 판정이
    실패하는 대신)."""
    with pytest.raises(ValidationError, match="BEDROCK_ACCESS_KEY_ID"):
        load_production_env(monkeypatch, STAT_JUDGMENT_MODEL="haiku")


def test_judgment_model_values_are_the_prompt_chain_ids() -> None:
    assert set(get_args(PromptSetModelId)) == {"gemini", "sonnet", "opus", "haiku"}
