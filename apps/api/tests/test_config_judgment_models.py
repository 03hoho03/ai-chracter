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
from api.llm.call_policy import CALL_POLICIES, LLMCallSite
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
# 운영 env 에 아직 모델 줄·배정이 없는 호출 위치. 인상 생성은 쓰기 스위치가 꺼져 있어 운영에서 부르지 않고, 그래서 모델은 코드
# 기본값(`gemini`)이다 — 스위치를 켤 때 모델 줄(`MEMORY_IMPRESSION_MODEL=haiku`)과 배정을 운영 env 에 넣고 여기서 뺀다.
_NOT_YET_IN_PRODUCTION = frozenset({"chat_memory_impression"})
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


def test_a_judgment_moved_to_anthropic_takes_its_preview_along_without_bedrock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """미리보기 판정은 자기 줄이 없으면 채팅 판정 짝의 배정을 물려받는다 — 채팅 판정 줄만 옮겨도 미리보기 판정(장면 헤더 포함)이
    함께 Anthropic 으로 가고, Bedrock 자격을 요구하지 않는다."""
    loaded = _load(
        monkeypatch,
        STAT_JUDGMENT_MODEL="haiku",
        **{_ASSIGN: "chat_stat_judgment:anthropic", _ANTHROPIC_KEY: "sk-ant-test"},
    )

    for call_site in ("preview_stat_judgment", "preview_scene_judgment"):
        assert _resolved(loaded, call_site) == ("haiku", "anthropic"), call_site


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
    judged = [
        cs
        for cs, policy in CALL_POLICIES.items()
        if policy.model_setting is not None and cs not in _NOT_YET_IN_PRODUCTION
    ]
    assert judged
    for call_site in judged:
        model = backends.call_site_model(call_site, lambda name: str(getattr(loaded, name)))
        assert backends.pick_backend(call_site, model, loaded.llm_call_site_backends, call_model=model) == (
            "haiku",
            "anthropic",
        ), call_site


# 운영 env 로 뜬 프로세스에서 호출 위치마다 (보낼 모델, 구현). 실린 모델이 기본(Gemini)인 호출 전부와, 사용자가 고른 상위 모델이
# 실리는 글쓰기 호출 셋. 값은 판정·요약 호출이 모델 배정 표의 부를 모델을 받기 전 코드에서 같은 계산으로 적었다 — 표가 비면 그
# 뒤에도 같아야 한다.
_PRODUCTION_ROUTES: dict[tuple[LLMCallSite, PromptSetModelId], tuple[PromptSetModelId, str]] = {
    ("chat_generate", "gemini"): ("gemini", "gemini"),
    ("chat_stat_judgment", "gemini"): ("haiku", "anthropic"),
    ("chat_ending_judgment", "gemini"): ("haiku", "anthropic"),
    ("chat_situational_image", "gemini"): ("haiku", "anthropic"),
    ("chat_media_book_image", "gemini"): ("haiku", "anthropic"),
    ("chat_memory_summary", "gemini"): ("haiku", "anthropic"),
    ("chat_memory_episode", "gemini"): ("haiku", "anthropic"),
    ("chat_memory_fact", "gemini"): ("haiku", "anthropic"),
    # 인상 생성은 운영 env 에 모델 줄도 배정 줄도 아직 없어 기본(Gemini)으로 간다.
    ("chat_memory_impression", "gemini"): ("gemini", "gemini"),
    ("chat_scene_judgment", "gemini"): ("haiku", "anthropic"),
    ("preview_generate", "gemini"): ("gemini", "gemini"),
    ("preview_stat_judgment", "gemini"): ("haiku", "anthropic"),
    ("preview_ending_judgment", "gemini"): ("haiku", "anthropic"),
    ("preview_media_book_image", "gemini"): ("haiku", "anthropic"),
    ("preview_scene_judgment", "gemini"): ("haiku", "anthropic"),
    ("publish_filter_character", "gemini"): ("gemini", "gemini"),
    ("publish_filter_story", "gemini"): ("gemini", "gemini"),
    ("seed_story_generate", "gemini"): ("gemini", "gemini"),
    ("seed_similarity_review", "gemini"): ("gemini", "gemini"),
    ("novelize_chapter", "gemini"): ("gemini", "gemini"),
    ("novelize_revise", "gemini"): ("gemini", "gemini"),
    ("novelize_boundary", "gemini"): ("gemini", "gemini"),
    ("novelize_revise_recheck", "gemini"): ("gemini", "gemini"),
    ("novelize_outline", "gemini"): ("gemini", "gemini"),
    ("novelize_episode_outline", "gemini"): ("gemini", "gemini"),
    ("novel_publish_screen", "gemini"): ("gemini", "gemini"),
    ("novel_illustration_screen", "gemini"): ("gemini", "gemini"),
    ("replay_generate", "gemini"): ("gemini", "gemini"),
    ("chat_generate", "opus"): ("opus", "anthropic"),
    ("replay_generate", "opus"): ("opus", "anthropic"),
    ("novelize_chapter", "opus"): ("opus", "anthropic"),
}


def test_the_production_env_starts_and_routes_every_call_site_as_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 키 조합(판정·요약·추출 모델 여섯 `haiku`, 상위 모델 스위치 켬, 판정·요약 호출 위치를 Anthropic 직결로 둔 배정, 자격은
    가짜 값, Bedrock 자격 없음)으로 설정이 뜨고, 그 프로세스의 호출 위치마다 경로가 적어 둔 값과 같다. 기동 검증 규칙을 더하거나
    바꿀 때 운영 env 그대로 새 이미지가 뜨는지를 여기서 먼저 본다."""
    loaded = load_production_env(monkeypatch)

    assert loaded.chat_premium_models_enabled
    assert not loaded.bedrock_access_key_id
    assert not loaded.bedrock_secret_access_key
    assert {cs for cs, _ in _PRODUCTION_ROUTES} == set(CALL_POLICIES)
    routes = {}
    for call_site, carried in _PRODUCTION_ROUTES:
        model = backends.call_site_model(call_site, lambda name: str(getattr(loaded, name)))
        routes[(call_site, carried)] = backends.pick_backend(
            call_site, carried, loaded.llm_call_site_backends, call_model=model
        )
    assert routes == _PRODUCTION_ROUTES


# 배정을 다른 호출 위치에서 물려받는 호출은 아래 "한 줄 빠짐" 경우가 거부가 아니다 — 장면 헤더 판정은 운영 배정에 자기 줄이 없어
# 원래 호출 위치의 줄이 빠지는 경우가 덮고, 미리보기 판정은 줄이 빠지면 채팅 짝을 물려받아 뜬다(이 파일 끝).
_JUDGED_CALL_SITES = [
    cs
    for cs, policy in CALL_POLICIES.items()
    if policy.model_setting is not None and policy.backend_from is None and cs not in _NOT_YET_IN_PRODUCTION
]


def test_every_judgment_call_site_has_a_missing_line_case() -> None:
    """운영 배정에서 줄 하나가 빠진 경우를 판정 호출 위치마다 한 규칙이 덮는다 — 자기 줄로 가는 호출은 기동 거부(아래), 미리보기
    판정은 채팅 짝 물려받기(이 파일 끝). 장면 헤더 둘은 운영에 자기 줄이 없어 물려받는 원래 호출 위치의 경우가 덮는다. 물려받는
    호출이 늘어 위 목록에서 조용히 빠지는 호출이 없게 한다. 운영 env 에 아직 줄이 없는 호출(위 `_NOT_YET_IN_PRODUCTION`)은 빠질
    줄이 없어 따로 센다."""
    judged = {call_site for call_site, policy in CALL_POLICIES.items() if policy.model_setting is not None}

    assert judged == {
        *_JUDGED_CALL_SITES,
        *_PRODUCTION_PREVIEW_LINES,
        *_NOT_YET_IN_PRODUCTION,
        "chat_scene_judgment",
        "preview_scene_judgment",
    }


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


def test_judgment_model_values_are_the_prompt_chain_ids() -> None:
    assert set(get_args(PromptSetModelId)) == {"gemini", "sonnet", "opus", "haiku"}


# ── 장면 헤더 판정의 배정 물려받기 ──────────────────────────────────────────────────────────────

_SCENE_SOURCES: dict[LLMCallSite, LLMCallSite] = {
    "chat_scene_judgment": "chat_stat_judgment",
    "preview_scene_judgment": "chat_scene_judgment",
}


def _resolved(loaded: Settings, call_site: LLMCallSite) -> tuple[str, str]:
    model = backends.call_site_model(call_site, lambda name: str(getattr(loaded, name)))
    return backends.pick_backend(call_site, model, loaded.llm_call_site_backends, call_model=model)


def test_scene_judgment_follows_each_stat_judgment_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    """장면 판정은 자기 배정 줄이 없어도 스탯 판정의 배정으로 간다 — 채팅 장면은 채팅 스탯 판정을, 미리보기 장면은 채팅 장면을
    거쳐 같은 배정을 물려받으므로 채팅 스탯 판정 줄 하나로 넷이 함께 움직인다."""
    loaded = _load(
        monkeypatch,
        STAT_JUDGMENT_MODEL="haiku",
        **{_ASSIGN: "chat_stat_judgment:anthropic", _ANTHROPIC_KEY: "sk-ant-test"},
        **_BEDROCK_CREDENTIALS,
    )

    assert _resolved(loaded, "chat_scene_judgment") == ("haiku", "anthropic")
    assert _resolved(loaded, "preview_scene_judgment") == ("haiku", "anthropic")
    for scene, source in _SCENE_SOURCES.items():
        assert _resolved(loaded, scene) == _resolved(loaded, source)


def test_scene_judgment_starts_on_a_bedrock_only_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """배정 없이 Bedrock 자격만 둔 구성에서도 뜨고, 장면 판정은 스탯 판정처럼 haiku 의 기본 구현(Bedrock)으로 간다 — 직결 키를
    따로 요구하지 않는다."""
    loaded = _load(monkeypatch, STAT_JUDGMENT_MODEL="haiku", **_BEDROCK_CREDENTIALS)

    for scene, source in _SCENE_SOURCES.items():
        assert _resolved(loaded, scene) == _resolved(loaded, source) == ("haiku", "bedrock")


def test_scene_judgment_needs_the_credentials_of_the_backend_it_inherits(monkeypatch: pytest.MonkeyPatch) -> None:
    """기동 검증은 장면 판정이 물려받아 실제로 갈 구현의 자격을 본다 — 스탯 판정을 직결로 옮기고 키를 비우면 장면 판정 줄도
    같은 이유로 걸린다."""
    with pytest.raises(ValidationError, match="chat_scene_judgment — 가는 구현 anthropic"):
        _load(
            monkeypatch,
            STAT_JUDGMENT_MODEL="haiku",
            **{_ASSIGN: "chat_stat_judgment:anthropic,preview_stat_judgment:anthropic"},
        )


# ── 미리보기 호출의 배정 물려받기 ────────────────────────────────────────────────────────────

# 미리보기 호출 → 배정을 물려받는 채팅 짝. 자기 env 줄이 없으면 짝의 배정으로 가고, 있으면 짝의 배정과 같아야 뜬다 — 기동한
# 프로세스에서 미리보기와 채팅이 같은 문안을 다른 경로로 부르는 일이 없다.
_PREVIEW_PAIRS: dict[LLMCallSite, LLMCallSite] = {
    "preview_generate": "chat_generate",
    "preview_stat_judgment": "chat_stat_judgment",
    "preview_ending_judgment": "chat_ending_judgment",
    "preview_media_book_image": "chat_media_book_image",
    "preview_scene_judgment": "chat_scene_judgment",
}


def _production_assignment_with(call_site: str, backend: str) -> str:
    return f"{_production_assignment_without(call_site)},{call_site}:{backend}"


@pytest.mark.parametrize("call_site", list(_PREVIEW_PAIRS))
def test_production_env_with_a_preview_line_unlike_its_chat_pair_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, call_site: LLMCallSite
) -> None:
    """운영 배정에 미리보기 줄을 채팅 짝과 다른 구현으로 적으면 뜨지 않는다. Bedrock 자격을 채워 다른 이유로는 거부되지 않게 한다."""
    with pytest.raises(ValidationError, match=f"{call_site}:bedrock — 물려받는 {_PREVIEW_PAIRS[call_site]}"):
        load_production_env(
            monkeypatch, **{_ASSIGN: _production_assignment_with(call_site, "bedrock")}, **_BEDROCK_CREDENTIALS
        )


@pytest.mark.parametrize("call_site", list(_PREVIEW_PAIRS))
def test_production_env_with_a_preview_line_like_its_chat_pair_starts(
    monkeypatch: pytest.MonkeyPatch, call_site: LLMCallSite
) -> None:
    loaded = load_production_env(monkeypatch, **{_ASSIGN: _production_assignment_with(call_site, "anthropic")})

    assert loaded.llm_call_site_backends[call_site] == "anthropic"


_PRODUCTION_PREVIEW_LINES: list[LLMCallSite] = [
    call_site
    for call_site in _PREVIEW_PAIRS
    if f"{call_site}:anthropic" in PRODUCTION_ENV_TYPED_VALUES[_ASSIGN].split(",")
]


@pytest.mark.parametrize("call_site", _PRODUCTION_PREVIEW_LINES)
def test_production_env_missing_a_preview_judgment_line_starts_on_its_chat_pair(
    monkeypatch: pytest.MonkeyPatch, call_site: LLMCallSite
) -> None:
    """운영 배정에서 미리보기 판정 줄 하나만 빠지면 그 판정은 채팅 짝의 배정(Anthropic 직결)을 물려받아 뜬다 — 자격이 없는
    Bedrock 으로 풀려 기동을 막던 경우가 아니다."""
    loaded = load_production_env(monkeypatch, **{_ASSIGN: _production_assignment_without(call_site)})

    assert call_site not in loaded.llm_call_site_backends
    assert _resolved(loaded, call_site) == _resolved(loaded, _PREVIEW_PAIRS[call_site]) == ("haiku", "anthropic")


def test_production_env_sends_a_premium_preview_where_it_sends_a_premium_chat_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 env 에는 미리보기 생성 줄이 없다 — Opus 미리보기는 채팅 생성의 배정을 물려받아 Anthropic 직결로 가고, 상위 모델 스위치의
    자격 검사도 그 경로를 본다. 기본(Gemini) 미리보기는 그대로 Gemini 다."""
    loaded = load_production_env(monkeypatch)

    assert "preview_generate" not in loaded.llm_call_site_backends
    for carried in ("gemini", "opus"):
        assert backends.pick_backend("preview_generate", carried, loaded.llm_call_site_backends) == (
            backends.pick_backend("chat_generate", carried, loaded.llm_call_site_backends)
        )
    assert backends.pick_backend("preview_generate", "opus", loaded.llm_call_site_backends) == ("opus", "anthropic")
