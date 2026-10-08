import pytest

from api.core import clover
from api.core.config import settings
from api.llm.chat_models import (
    CHAT_MODELS,
    actual_model_id,
    chat_turn_cost,
    novel_episode_unit_price,
    parse_chat_model_id,
)


def test_ids_outside_the_registry_are_not_models() -> None:
    """DB 의 모델 칸에는 값 제약이 없어 레지스트리에서 내린 모델의 옛 값이 남을 수 있다 — 그 값이 모델로 읽히면 안 된다."""
    assert parse_chat_model_id("sonnet") == "sonnet"
    assert parse_chat_model_id("claude-sonnet-4-6") is None
    assert parse_chat_model_id("") is None


def test_the_registry_lists_gemini_first_then_the_premium_models() -> None:
    assert [(m.id, m.provider) for m in CHAT_MODELS] == [
        ("gemini", "gemini"),
        ("sonnet", "bedrock"),
        ("opus", "bedrock"),
    ]


def test_actual_model_ids_follow_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """모델 버전을 바꿔도 와이어 id 와 DB 값은 그대로이고 실제 id 만 설정으로 바뀐다."""
    monkeypatch.setattr(settings, "gemini_model_name", "gemini-x")
    monkeypatch.setattr(settings, "bedrock_sonnet_model_id", "global.anthropic.sonnet-next")
    monkeypatch.setattr(settings, "bedrock_opus_model_id", "global.anthropic.opus-next")

    assert actual_model_id("gemini") == "gemini-x"
    assert actual_model_id("sonnet") == "global.anthropic.sonnet-next"
    assert actual_model_id("opus") == "global.anthropic.opus-next"


def test_default_actual_model_ids_are_the_seoul_global_profiles() -> None:
    assert actual_model_id("sonnet") == "global.anthropic.claude-sonnet-4-6"
    assert actual_model_id("opus") == "global.anthropic.claude-opus-4-6-v1"


def test_turn_costs_are_read_from_the_clover_constants_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """가격의 소스는 `core/clover.py` 하나다 — 레지스트리가 값을 복사해 두면 한쪽만 고쳐진다."""
    monkeypatch.setattr(clover, "CHAT_TURN_COST", 11)
    monkeypatch.setattr(clover, "CHAT_TURN_COST_SONNET", 41)
    monkeypatch.setattr(clover, "CHAT_TURN_COST_OPUS", 66)

    assert [chat_turn_cost(m.id) for m in CHAT_MODELS] == [11, 41, 66]


def test_episode_unit_prices_are_read_from_the_clover_constants_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST", 41)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST_SONNET", 106)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST_OPUS", 171)

    assert [novel_episode_unit_price(m.id) for m in CHAT_MODELS] == [41, 106, 171]


def test_default_episode_unit_prices_are_the_provisional_ones() -> None:
    """Gemini 40·Sonnet 105·Opus 170 — 화 하나의 값이다(생성 한 번은 이 값 × 화 수)."""
    assert [novel_episode_unit_price(m.id) for m in CHAT_MODELS] == [40, 105, 170]
