from typing import get_args

import pytest

from api.core import clover
from api.core.config import Settings, settings
from api.llm.chat_models import (
    CHAT_MODELS,
    CHAT_MODELS_BY_ID,
    ChatModelId,
    ChatRoomModelId,
    PromptSetModelId,
    backend_model_id,
    chat_turn_cost,
    novel_episode_outline_unit_price,
    novel_episode_unit_price,
    novel_outline_unit_price,
    parse_chat_model_id,
    parse_prompt_set_model_id,
)
from factories import _set_model_price


def test_ids_outside_the_registry_are_not_models() -> None:
    """DB 의 모델 칸에는 값 제약이 없어 레지스트리에서 내린 모델의 옛 값이 남을 수 있다 — 그 값이 모델로 읽히면 안 된다."""
    assert parse_chat_model_id("sonnet") == "sonnet"
    assert parse_chat_model_id("claude-sonnet-4-6") is None
    assert parse_chat_model_id("") is None


def test_the_judgment_only_id_is_a_prompt_set_model_but_never_a_chat_model() -> None:
    """판정 전용 id 는 판정·요약 문안 체인에만 있다 — 채팅 생성 모델 선택(레지스트리·파서)에 나오면 그 id 로 생성하려 들거나
    값을 매길 수 없는 모델이 방·소설 요청에 들어온다."""
    assert get_args(ChatModelId) == ("gemini", "haiku_writer", "sonnet", "opus")
    assert "haiku" not in CHAT_MODELS_BY_ID
    assert parse_chat_model_id("haiku") is None
    assert set(get_args(PromptSetModelId)) == set(get_args(ChatModelId)) | {"haiku"}
    assert [parse_prompt_set_model_id(m) for m in ("gemini", "haiku_writer", "sonnet", "opus", "haiku")] == [
        "gemini",
        "haiku_writer",
        "sonnet",
        "opus",
        "haiku",
    ]
    assert parse_prompt_set_model_id("claude-haiku-4-5") is None


def test_the_registry_lists_gemini_first_then_the_premium_models_from_the_cheapest_chat_turn() -> None:
    """레지스트리 순서가 곧 화면 순서다 — 기본 모델 뒤로 채팅 턴 가격이 낮은 것부터. Haiku 글쓰기는 직결이 기본 구현이다."""
    assert [(m.id, m.provider) for m in CHAT_MODELS] == [
        ("gemini", "gemini"),
        ("haiku_writer", "anthropic"),
        ("sonnet", "bedrock"),
        ("opus", "bedrock"),
    ]
    premium_costs = [chat_turn_cost(m.id) for m in CHAT_MODELS[1:]]
    assert premium_costs == sorted(premium_costs)


def test_the_haiku_writer_is_a_beta_chat_model_named_after_the_model_it_calls() -> None:
    spec = CHAT_MODELS_BY_ID["haiku_writer"]

    assert (spec.name, spec.chat_selectable, spec.beta) == ("Claude Haiku 5.5", True, True)


def test_only_the_haiku_writer_is_kept_out_of_novels() -> None:
    """소설 모델 목록·소설 요청 게이트·기동 검증이 이 표시 하나를 읽는다 — 채팅 전용 모델은 소설 상한·단가가 없다."""
    assert {m.id: m.novel_selectable for m in CHAT_MODELS} == {
        "gemini": True,
        "haiku_writer": False,
        "sonnet": True,
        "opus": True,
    }


@pytest.mark.parametrize(
    "price", [novel_episode_unit_price, novel_outline_unit_price, novel_episode_outline_unit_price]
)
def test_a_novel_price_of_a_chat_only_model_stops_instead_of_charging_a_made_up_value(price: object) -> None:
    """소설 요청 게이트 뒤라 닿지 않는 경로다 — 닿으면 버그이므로 0 이나 다른 모델 값으로 깎지 않고 멈춘다."""
    assert callable(price)
    with pytest.raises(RuntimeError, match="haiku_writer"):
        price("haiku_writer")


def test_the_chat_room_model_type_matches_the_chat_selectable_models() -> None:
    """방 모델 지정 요청은 이 타입으로 받고 방 해석·목록은 레지스트리 표시를 읽는다 — 둘이 갈리면 목록에 없는 모델을
    지정할 수 있거나, 목록의 모델을 지정하면 422 가 된다."""
    assert set(get_args(ChatRoomModelId)) == {m.id for m in CHAT_MODELS if m.chat_selectable}


def test_actual_model_ids_follow_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """모델 버전을 바꿔도 와이어 id 와 DB 값은 그대로이고 실제 id 만 설정으로 바뀐다."""
    monkeypatch.setattr(settings, "gemini_model_name", "gemini-x")
    monkeypatch.setattr(settings, "bedrock_sonnet_model_id", "global.anthropic.sonnet-next")
    monkeypatch.setattr(settings, "bedrock_opus_model_id", "global.anthropic.opus-next")

    assert backend_model_id("gemini", "gemini") == "gemini-x"
    assert backend_model_id("bedrock", "sonnet") == "global.anthropic.sonnet-next"
    assert backend_model_id("bedrock", "opus") == "global.anthropic.opus-next"


def test_the_haiku_writer_id_is_its_own_setting_apart_from_the_judgment_only_haiku(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """판정 모델 버전을 바꾸는 설정이 사용자가 고른 글쓰기 모델을 바꾸지 않는다. 글쓰기 쪽 기본값은 Haiku 5.5 다."""
    assert Settings.model_fields["anthropic_haiku_writer_model_id"].default == "claude-haiku-5-5"
    monkeypatch.setattr(settings, "anthropic_haiku_model_id", "claude-haiku-next")
    monkeypatch.setattr(settings, "anthropic_haiku_writer_model_id", "claude-haiku-5-5")

    assert backend_model_id("anthropic", "haiku_writer") == "claude-haiku-5-5"
    assert backend_model_id("anthropic", "haiku") == "claude-haiku-next"


def test_default_actual_model_ids_are_the_seoul_global_profiles() -> None:
    assert backend_model_id("bedrock", "sonnet") == "global.anthropic.claude-sonnet-4-6"
    assert backend_model_id("bedrock", "opus") == "global.anthropic.claude-opus-4-6-v1"


def test_turn_costs_are_read_from_the_price_registry_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """가격의 소스는 `core/clover.py` 하나다 — 레지스트리가 값을 복사해 두면 한쪽만 고쳐진다."""
    _set_model_price(monkeypatch, "gemini", chat_turn=11)
    _set_model_price(monkeypatch, "haiku_writer", chat_turn=23)
    _set_model_price(monkeypatch, "sonnet", chat_turn=41)
    _set_model_price(monkeypatch, "opus", chat_turn=66)

    assert [chat_turn_cost(m.id) for m in CHAT_MODELS] == [11, 23, 41, 66]


def test_episode_unit_prices_are_read_from_the_price_registry_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_model_price(monkeypatch, "gemini", novel_episode=41)
    _set_model_price(monkeypatch, "sonnet", novel_episode=106)
    _set_model_price(monkeypatch, "opus", novel_episode=171)

    assert [novel_episode_unit_price(m.id) for m in CHAT_MODELS if m.novel_selectable] == [41, 106, 171]


def test_default_episode_unit_prices_are_the_registry_values() -> None:
    """모델마다 화 하나의 값이다(생성 한 번은 이 값 × 화 수). 값 자체는 정책 상수 테스트가 고정한다."""
    assert [novel_episode_unit_price(m.id) for m in CHAT_MODELS if m.novel_selectable] == [
        clover.CLOVER_MODEL_PRICES["gemini"].novel_episode,
        clover.CLOVER_MODEL_PRICES["sonnet"].novel_episode,
        clover.CLOVER_MODEL_PRICES["opus"].novel_episode,
    ]
