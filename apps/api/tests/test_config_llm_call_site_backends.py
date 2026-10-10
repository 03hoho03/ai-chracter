"""`LLM_CALL_SITE_BACKENDS`(호출 위치마다 공급자 구현을 배정하는 env)를 읽는 규칙과 기동 검증.

값은 `call_site:backend` 를 쉼표로 이은 목록이다. 비어 있으면 배정 없음(지금 라우팅 그대로)이고, 읽을 수 없는 값이나 그
호출에서 아무 모델도 서비스하지 못하는 배정은 기동에서 거부한다 — 배정이 틀린 채 뜨면 그 호출이 런타임에 실패하거나 조용히
배정이 무시된다.
"""

import pytest
from pydantic import ValidationError

from api.core.config import Settings

_ENV = "LLM_CALL_SITE_BACKENDS"
_BEDROCK_CREDENTIALS = ("BEDROCK_ACCESS_KEY_ID", "BEDROCK_SECRET_ACCESS_KEY")


def _load(monkeypatch: pytest.MonkeyPatch, value: str | None = None) -> Settings:
    monkeypatch.delenv(_ENV, raising=False)
    # 배정이 자격을 요구하지 않는다는 것을 보이려고 Bedrock 키는 늘 비운다.
    for key in _BEDROCK_CREDENTIALS:
        monkeypatch.delenv(key, raising=False)
    if value is not None:
        monkeypatch.setenv(_ENV, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("value", [None, "", "   ", " , ,"])
def test_a_missing_or_blank_value_means_no_assignment(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    """빈 값은 허용 명단처럼 "기본 그대로" 다 — 키가 없을 때와 같아야 운영 env 에 빈 줄이 남아도 라우팅이 바뀌지 않는다."""
    assert _load(monkeypatch, value).llm_call_site_backends == {}


def test_entries_are_split_on_commas_and_colons_with_surrounding_spaces_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _load(monkeypatch, " chat_generate : gemini , ,chat_stat_judgment:gemini,")

    assert loaded.llm_call_site_backends == {"chat_generate": "gemini", "chat_stat_judgment": "gemini"}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("chat_generate", id="no-colon"),
        pytest.param("chat_generate:", id="empty-backend"),
        pytest.param(":gemini", id="empty-call-site"),
        pytest.param("chat_generate:gemini:bedrock", id="two-colons"),
    ],
)
def test_an_entry_that_is_not_one_call_site_and_one_backend_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    with pytest.raises(ValidationError, match=_ENV):
        _load(monkeypatch, value)


def test_the_same_call_site_twice_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """사전으로 바로 만들면 뒤의 값이 조용히 이긴다 — 어느 쪽이 의도였는지 모르므로 기동하지 않는다."""
    with pytest.raises(ValidationError, match="chat_generate"):
        _load(monkeypatch, "chat_generate:gemini,chat_generate:bedrock")


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("chat_genrate:gemini", id="unknown-call-site"),
        pytest.param("Chat_generate:gemini", id="call-site-case"),
        pytest.param("chat_generate:Gemini", id="backend-case"),
        pytest.param("chat_generate:openai", id="unknown-backend"),
    ],
)
def test_an_unknown_call_site_or_backend_refuses_to_start(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    with pytest.raises(ValidationError):
        _load(monkeypatch, value)


@pytest.mark.parametrize(
    "value",
    [
        # 판정·요약·심사·미리보기는 모델을 고를 수 없어 기본 모델만 받는데, Bedrock 은 그 모델을 서비스하지 않는다.
        "chat_stat_judgment:bedrock",
        "novelize_revise:bedrock",
        "publish_filter_story:bedrock",
        "preview_generate:bedrock",
    ],
)
def test_assigning_a_backend_that_serves_no_model_of_that_call_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    call_site = value.split(":")[0]
    with pytest.raises(ValidationError, match=call_site):
        _load(monkeypatch, value)


@pytest.mark.parametrize(
    "value",
    [
        # 모델을 고르는 호출에서 Bedrock 은 상위 모델을 서비스한다 — 지금 기본과 같은 배정이라 자격 없이도 뜬다.
        "chat_generate:bedrock",
        # 기본 모델은 Gemini 로, 상위 모델은 Gemini 가 서비스하지 않아 기본(Bedrock)으로 간다.
        "chat_generate:gemini",
        "chat_stat_judgment:gemini",
        "chat_generate:gemini,novelize_chapter:bedrock,publish_filter_character:gemini",
    ],
)
def test_assignments_that_some_model_of_the_call_can_use_start(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    assert _load(monkeypatch, value).llm_call_site_backends != {}


# ── Anthropic API 직접 구현으로 옮기는 배정 ─────────────────────────────────────────────────

_ANTHROPIC_KEY = "ANTHROPIC_DIRECT_API_KEY"
_SWITCHES = ("CHAT_PREMIUM_MODELS_ENABLED", "NOVELIZE_PREMIUM_MODELS_ENABLED")
# 상위 모델을 Anthropic 으로 운영에서 켤 때의 배정. 상위 모델 스위치가 쓰는 호출 위치 셋을 모두 옮긴다.
_ALL_PREMIUM_CALLS_TO_ANTHROPIC = "chat_generate:anthropic,replay_generate:anthropic,novelize_chapter:anthropic"


def _load_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Bedrock 자격 셋(리전 포함)·Anthropic 키·스위치·배정을 모두 지운 뒤 `env` 만 심는다."""
    for key in (_ENV, *_BEDROCK_CREDENTIALS, "BEDROCK_REGION", _ANTHROPIC_KEY, *_SWITCHES):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("key", [None, "", "  "])
def test_moving_a_call_to_anthropic_without_its_key_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    env = {_ENV: "chat_generate:anthropic"} if key is None else {_ENV: "chat_generate:anthropic", _ANTHROPIC_KEY: key}

    with pytest.raises(ValidationError, match=_ANTHROPIC_KEY):
        _load_env(monkeypatch, **env)


def test_moving_a_call_to_anthropic_with_its_key_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load_env(monkeypatch, **{_ENV: "chat_generate:anthropic", _ANTHROPIC_KEY: "sk-ant-test"})

    assert loaded.llm_call_site_backends == {"chat_generate": "anthropic"}


@pytest.mark.parametrize("call_site", ["chat_stat_judgment", "chat_memory_summary", "preview_generate"])
def test_assigning_anthropic_to_a_call_that_cannot_pick_a_premium_model_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, call_site: str
) -> None:
    """이 호출들은 기본 모델만 받는데 Anthropic 구현은 그 모델을 서비스하지 않는다 — 키가 있어도 배정이 아무 일도 하지 않는다."""
    with pytest.raises(ValidationError, match=call_site):
        _load_env(monkeypatch, **{_ENV: f"{call_site}:anthropic", _ANTHROPIC_KEY: "sk-ant-test"})


def test_premium_switches_with_every_premium_call_on_anthropic_start_without_bedrock_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """상위 모델 스위치의 기동 검증은 스위치가 쓰는 호출이 실제로 갈 구현의 자격을 본다 — 모두 Anthropic 으로 옮겼으면
    Bedrock 키가 없어도 뜬다."""
    loaded = _load_env(
        monkeypatch,
        **{_ENV: _ALL_PREMIUM_CALLS_TO_ANTHROPIC, _ANTHROPIC_KEY: "sk-ant-test"},
        **dict.fromkeys(_SWITCHES, "true"),
    )

    assert loaded.chat_premium_models_enabled and loaded.novelize_premium_models_enabled
    assert set(loaded.llm_call_site_backends.values()) == {"anthropic"}
    assert loaded.bedrock_access_key_id == ""


@pytest.mark.parametrize(
    ("assignment", "switch"),
    [
        # 측정용 다시 생성도 채팅 스위치가 여는 호출이다 — 남겨 두면 그 호출은 Bedrock 으로 간다.
        pytest.param("chat_generate:anthropic,novelize_chapter:anthropic", "CHAT_PREMIUM_MODELS_ENABLED", id="replay"),
        pytest.param("replay_generate:anthropic,novelize_chapter:anthropic", "CHAT_PREMIUM_MODELS_ENABLED", id="chat"),
        pytest.param(
            "chat_generate:anthropic,replay_generate:anthropic", "NOVELIZE_PREMIUM_MODELS_ENABLED", id="chapter"
        ),
    ],
)
def test_a_premium_call_left_on_bedrock_still_needs_bedrock_credentials(
    monkeypatch: pytest.MonkeyPatch, assignment: str, switch: str
) -> None:
    with pytest.raises(ValidationError, match="BEDROCK_ACCESS_KEY_ID"):
        _load_env(monkeypatch, **{_ENV: assignment, _ANTHROPIC_KEY: "sk-ant-test", switch: "true"})


def test_the_chat_switch_alone_needs_only_the_chat_calls_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load_env(
        monkeypatch,
        **{
            _ENV: "chat_generate:anthropic,replay_generate:anthropic",
            _ANTHROPIC_KEY: "sk-ant-test",
            "CHAT_PREMIUM_MODELS_ENABLED": "true",
        },
    )

    assert loaded.chat_premium_models_enabled


@pytest.mark.parametrize("switch", _SWITCHES)
def test_premium_switches_without_an_assignment_still_need_bedrock_credentials_even_with_an_anthropic_key(
    monkeypatch: pytest.MonkeyPatch, switch: str
) -> None:
    """배정이 없으면 상위 모델은 지금처럼 Bedrock 으로 간다 — Anthropic 키는 그 자격을 대신하지 못한다."""
    with pytest.raises(ValidationError, match="BEDROCK_ACCESS_KEY_ID"):
        _load_env(monkeypatch, **{_ANTHROPIC_KEY: "sk-ant-test", switch: "true"})


# 운영 API 컨테이너가 받는 env 키 이름(값 없이). 컨테이너는 `.env` 를 통째로 받으므로 compose·다른 서비스 키도 섞여 있다.
# 운영은 상위 모델 호출 셋을 모두 Anthropic 으로 배정하고, Bedrock 자격(`BEDROCK_*`)은 운영에 없다. 채팅·소설 상위 모델
# 스위치는 켠 상태가 기동 검증이 더 엄격한 경우라 켠 상태로 본다.
_PRODUCTION_ENV_NAMES = (
    "ANTHROPIC_DIRECT_API_KEY",
    "API_BASE_URL",
    "API_IMAGE_BLUE",
    "API_IMAGE_GREEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_REGION",
    "AWS_SECRET_ACCESS_KEY",
    "BUGSINK_BASE_URL",
    "BUGSINK_CREATE_SUPERUSER",
    "BUGSINK_SECRET_KEY",
    "CHAT_PREMIUM_MODEL_ALLOWLIST",
    "CHAT_PREMIUM_MODELS_ENABLED",
    "CORS_ALLOW_ORIGINS",
    "DATABASE_URL",
    "DB_MAX_OVERFLOW",
    "DB_POOL_SIZE",
    "DB_POOL_TIMEOUT",
    "DDONA_ENV_FILE",
    "DISCORD_WEBHOOK_URL",
    "EMAIL_FROM",
    "EMAIL_PROVIDER",
    "FORWARDED_ALLOW_IPS",
    "FRONTEND_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_ENDING_JUDGMENT_MODEL_NAME",
    "GEMINI_MODEL_NAME",
    "GEMINI_STAT_JUDGMENT_MODEL_NAME",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "HEALTHCHECKS_BACKUP_PING_URL",
    "HEALTHCHECKS_RESOURCE_PING_URL",
    "IDENTITY_CI_HMAC_KEY",
    "IMAGE_DECODE_CONCURRENCY",
    "INGEST_SHARED_SECRET",
    "KAKAO_ADMIN_KEY",
    "KAKAO_CLIENT_SECRET",
    "KAKAO_REST_API_KEY",
    "LLM_CALL_SITE_BACKENDS",
    "LOCAL_IMAGE_ACCESS_CLIENT_ID",
    "LOCAL_IMAGE_ACCESS_CLIENT_SECRET",
    "LOCAL_IMAGE_BASE_URL",
    "LOCAL_IMAGE_MODEL_WIRE_ID",
    "LOCAL_IMAGE_REFERENCE_ENABLED",
    "NOVELIZE_ENABLED",
    "NOVELIZE_GRANT_ALLOWLIST",
    "NOVELIZE_PREMIUM_MODEL_ALLOWLIST",
    "NOVELIZE_PREMIUM_MODELS_ENABLED",
    "NOVEL_PUBLIC_ENABLED",
    "PAYMENTS_ENABLED",
    "PORTONE_API_SECRET",
    "PORTONE_IDENTITY_CHANNEL_KEY",
    "PORTONE_PAYMENT_CHANNEL_KEY",
    "PORTONE_STORE_ID",
    "PORTONE_WEBHOOK_SECRET",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "REDIS_URL",
    "RESEND_API_KEY",
    "S3_BUCKET_NAME",
    "S3_ENDPOINT_URL",
    "SENTRY_DSN",
    "SENTRY_ENVIRONMENT",
    "SESSION_COOKIE_SAMESITE",
    "SESSION_COOKIE_SECURE",
    "SITE_ADDRESS",
    "WEB_CONCURRENCY",
    "WITHDRAWN_EMAIL_HMAC_KEY",
)

# 문자열이 아닌 설정만 형식에 맞는 가짜 값을 둔다. 나머지(문자열 설정과 `Settings` 가 모르는 키)는 아무 글자다. 배정은
# 운영 값 그대로다 — 형식만 맞는 다른 배정이면 Bedrock 으로 남는 호출이 생겨 이 집합으로는 기동하지 못한다.
_TYPED_FAKE_VALUES = {
    "CHAT_PREMIUM_MODELS_ENABLED": "true",
    "CORS_ALLOW_ORIGINS": "https://a.example,https://b.example",
    "DB_MAX_OVERFLOW": "10",
    "DB_POOL_SIZE": "5",
    "DB_POOL_TIMEOUT": "30",
    "EMAIL_PROVIDER": "resend",
    "IMAGE_DECODE_CONCURRENCY": "3",
    "LLM_CALL_SITE_BACKENDS": _ALL_PREMIUM_CALLS_TO_ANTHROPIC,
    "LOCAL_IMAGE_REFERENCE_ENABLED": "true",
    "NOVELIZE_ENABLED": "true",
    "NOVELIZE_GRANT_ALLOWLIST": "11111111-1111-4111-8111-111111111111",
    "NOVELIZE_PREMIUM_MODEL_ALLOWLIST": "22222222-2222-4222-8222-222222222222",
    "NOVELIZE_PREMIUM_MODELS_ENABLED": "true",
    "NOVEL_PUBLIC_ENABLED": "true",
    "PAYMENTS_ENABLED": "true",
    "S3_ENDPOINT_URL": "https://r2.example",
    "SENTRY_ENVIRONMENT": "production",
    "SESSION_COOKIE_SAMESITE": "none",
    "SESSION_COOKIE_SECURE": "true",
}


def test_the_production_env_key_set_starts_with_every_premium_call_on_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 env 그대로 새 이미지가 떠야 한다 — 상위 모델 호출이 모두 Anthropic 으로 가므로 Bedrock 자격 없이도 기동 검증을
    통과해야 한다. 두 스위치는 켠 상태가 기동 검증이 더 엄격한 경우라 그 상태로 본다. 컨테이너가 받는 `.env` 에는 `Settings` 가 모르는 compose·다른 서비스 키도 있어,
    모르는 키를 무시하는 설정이 이 기동의 전제다."""
    assert Settings.model_config.get("extra") == "ignore"
    # 테스트 프로세스가 물려받은 설정 env 를 지워, 운영에 있는 키만 남긴다.
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    unknown = [name for name in _PRODUCTION_ENV_NAMES if name.lower() not in Settings.model_fields]
    assert unknown, "운영 env 에 Settings 가 모르는 키가 있다는 전제가 깨졌다"
    for name in _PRODUCTION_ENV_NAMES:
        monkeypatch.setenv(name, _TYPED_FAKE_VALUES.get(name, "x"))

    loaded = Settings(_env_file=None)  # type: ignore[call-arg]

    assert loaded.chat_premium_models_enabled and loaded.novelize_premium_models_enabled
    assert loaded.llm_call_site_backends == {
        "chat_generate": "anthropic",
        "replay_generate": "anthropic",
        "novelize_chapter": "anthropic",
    }
    assert loaded.bedrock_access_key_id == ""
