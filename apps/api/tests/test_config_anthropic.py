"""Anthropic API 직접 구현의 설정. 배정이 없으면 이 설정은 아무 호출에도 쓰이지 않는다."""

import pytest
from pydantic import ValidationError

from api.core.config import Settings

_KEYS = (
    "ANTHROPIC_DIRECT_API_KEY",
    "ANTHROPIC_SONNET_MODEL_ID",
    "ANTHROPIC_OPUS_MODEL_ID",
    "ANTHROPIC_CHAT_TIMEOUT_MS",
    "ANTHROPIC_CHAPTER_TIMEOUT_MS",
    "ANTHROPIC_CHAT_MAX_TOKENS",
    "ANTHROPIC_CHAPTER_MAX_TOKENS",
    "ANTHROPIC_CHAT_EFFORT",
    "ANTHROPIC_CHAPTER_EFFORT",
    "LLM_CALL_SITE_BACKENDS",
)


def _load(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


_DEFAULTS = [
    ("ANTHROPIC_SONNET_MODEL_ID", "anthropic_sonnet_model_id", "claude-sonnet-5-5"),
    ("ANTHROPIC_OPUS_MODEL_ID", "anthropic_opus_model_id", "claude-opus-5-5"),
    ("ANTHROPIC_CHAT_TIMEOUT_MS", "anthropic_chat_timeout_ms", 45_000),
    ("ANTHROPIC_CHAPTER_TIMEOUT_MS", "anthropic_chapter_timeout_ms", 300_000),
    # 사고 토큰도 이 상한 안에 든다 — 상한이지 과금량이 아니다.
    ("ANTHROPIC_CHAT_MAX_TOKENS", "anthropic_chat_max_tokens", 16_000),
    ("ANTHROPIC_CHAPTER_MAX_TOKENS", "anthropic_chapter_max_tokens", 64_000),
    ("ANTHROPIC_CHAT_EFFORT", "anthropic_chat_effort", "low"),
    ("ANTHROPIC_CHAPTER_EFFORT", "anthropic_chapter_effort", "medium"),
]


def test_the_direct_api_is_off_without_any_env(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load(monkeypatch)

    assert loaded.anthropic_direct_api_key == ""
    assert loaded.llm_call_site_backends == {}
    for _, field, default in _DEFAULTS:
        assert getattr(loaded, field) == default, field


@pytest.mark.parametrize(("key", "field", "default"), _DEFAULTS)
@pytest.mark.parametrize("blank", ["", "  "])
def test_an_empty_env_line_reads_as_the_default(
    monkeypatch: pytest.MonkeyPatch, key: str, field: str, default: object, blank: str
) -> None:
    """값만 비운 줄(`KEY=`)이 남아도 기동한다. 빈 모델 id 는 어떤 모델도 가리키지 않으므로 비어 있는 채로 두지 않고
    기본 id 로 읽는다."""
    assert getattr(_load(monkeypatch, **{key: blank}), field) == default


@pytest.mark.parametrize("key", ["ANTHROPIC_CHAT_EFFORT", "ANTHROPIC_CHAPTER_EFFORT"])
@pytest.mark.parametrize("value", ["lowest", "LOW", "none"])
def test_an_effort_outside_the_api_levels_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    """API 가 받지 않는 깊이면 첫 호출이 거부된다 — 기동에서 막는다."""
    with pytest.raises(ValidationError):
        _load(monkeypatch, **{key: value})


def test_the_key_stays_out_of_the_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load(monkeypatch, ANTHROPIC_DIRECT_API_KEY="sk-ant-secret")

    assert loaded.anthropic_direct_api_key == "sk-ant-secret"
    assert "sk-ant-secret" not in repr(loaded)
