import uuid

import pytest
from pydantic import ValidationError

from api.core.config import Settings

_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
_B = uuid.UUID("22222222-2222-4222-8222-222222222222")

_SWITCHES = ("CHAT_PREMIUM_MODELS_ENABLED", "NOVELIZE_PREMIUM_MODELS_ENABLED")
_CREDENTIALS = {
    "BEDROCK_ACCESS_KEY_ID": "AKIATEST",
    "BEDROCK_SECRET_ACCESS_KEY": "secret-test",
    "BEDROCK_REGION": "ap-northeast-2",
}


def _load(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in (*_SWITCHES, *_CREDENTIALS, "NOVELIZE_PREMIUM_MODEL_ALLOWLIST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_premium_models_are_closed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """코드 기본값이 닫힘이어야 env 없이 배포해도 상위 모델이 닫힌 채 뜬다. 꺼져 있으면 키가 없어도 기동한다."""
    loaded = _load(monkeypatch)

    assert loaded.chat_premium_models_enabled is False
    assert loaded.novelize_premium_models_enabled is False
    assert loaded.novelize_premium_model_allowlist == []
    assert loaded.bedrock_access_key_id == ""


@pytest.mark.parametrize("switch", _SWITCHES)
@pytest.mark.parametrize("missing", list(_CREDENTIALS))
def test_a_switch_on_with_an_empty_credential_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, switch: str, missing: str
) -> None:
    """키나 리전이 빈 채로 SDK 에 가면 프로세스 env 의 R2 키(`AWS_*`)로 서명하거나 R2 리전(`auto`)으로 엔드포인트를
    만든다 — 켜진 채로 뜨게 두지 않는다."""
    env = {**_CREDENTIALS, missing: " ", switch: "true"}

    with pytest.raises(ValidationError, match="BEDROCK_"):
        _load(monkeypatch, **env)


@pytest.mark.parametrize("switch", _SWITCHES)
def test_a_switch_on_with_all_credentials_starts(monkeypatch: pytest.MonkeyPatch, switch: str) -> None:
    loaded = _load(monkeypatch, **_CREDENTIALS, **{switch: "true"})

    assert loaded.bedrock_access_key_id == "AKIATEST"


@pytest.mark.parametrize("field", ["novelize_premium_model_allowlist"])
def test_allowlists_split_like_the_novelize_allowlist(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    assert getattr(_load(monkeypatch, **{field.upper(): f" {_A} , ,{_B},"}), field) == [_A, _B]
    assert getattr(_load(monkeypatch, **{field.upper(): ""}), field) == []
    with pytest.raises(ValidationError):
        _load(monkeypatch, **{field.upper(): "not-a-uuid"})


@pytest.mark.parametrize("value", [str(_A), "not-a-uuid"])
def test_a_leftover_chat_allowlist_line_is_ignored(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """채팅 상위 모델은 스위치 하나로 열려 명단 키가 없다. 운영 env 에 옛 명단 줄이 남아 있어도(값이 깨져 있어도) 기동하고,
    그 값이 어디에도 읽히지 않는다."""
    loaded = _load(monkeypatch, CHAT_PREMIUM_MODEL_ALLOWLIST=value)

    assert "chat_premium_model_allowlist" not in type(loaded).model_fields


@pytest.mark.parametrize(
    ("key", "field", "default"),
    [
        ("CHAT_PREMIUM_MODELS_ENABLED", "chat_premium_models_enabled", False),
        ("NOVELIZE_PREMIUM_MODELS_ENABLED", "novelize_premium_models_enabled", False),
        ("BEDROCK_SONNET_MODEL_ID", "bedrock_sonnet_model_id", "global.anthropic.claude-sonnet-4-6"),
        ("BEDROCK_OPUS_MODEL_ID", "bedrock_opus_model_id", "global.anthropic.claude-opus-4-6-v1"),
        ("BEDROCK_CHAT_TIMEOUT_MS", "bedrock_chat_timeout_ms", 45_000),
        ("BEDROCK_CHAPTER_TIMEOUT_MS", "bedrock_chapter_timeout_ms", 300_000),
        ("BEDROCK_CHAT_MAX_TOKENS", "bedrock_chat_max_tokens", 4096),
        ("BEDROCK_CHAPTER_MAX_TOKENS", "bedrock_chapter_max_tokens", 32_768),
    ],
)
def test_an_empty_env_line_reads_as_the_default(
    monkeypatch: pytest.MonkeyPatch, key: str, field: str, default: object
) -> None:
    """값만 비운 줄(`KEY=`)이 남아도 기동한다 — 정하지 않은 것으로 읽는다. 빈 모델 id 는 어떤 모델도 가리키지 않는다."""
    assert getattr(_load(monkeypatch, **{key: ""}), field) == default


def test_bedrock_credentials_stay_out_of_the_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load(monkeypatch, **_CREDENTIALS)

    assert "AKIATEST" not in repr(loaded)
    assert "secret-test" not in repr(loaded)
