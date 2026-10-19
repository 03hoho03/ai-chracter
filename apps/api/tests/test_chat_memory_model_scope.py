"""기억 사용 범위(`MEMORY_MODEL_SCOPE`) — 기억 스위치가 실제로 동작하는 방을 레인과 글쓰기 모델로 고른다.

값은 쉼표로 나눈 목록이고 원소는 `모델`(두 레인 모두) 또는 `레인:모델`이다. 기본은 Opus 방뿐이다. 모르는 레인·모델 이름은
기동에서 거부한다 — 오타가 "어떤 방도 범위에 없음"으로 조용히 읽히면 켠 스위치가 아무 데서도 동작하지 않는데 기동은 성공한다.
"""

import pytest
from pydantic import ValidationError

from api.chat.memory_window import memory_model_in_scope
from api.core.config import Settings

_ENV = "MEMORY_MODEL_SCOPE"


def _load(monkeypatch: pytest.MonkeyPatch, value: str | None = None) -> Settings:
    monkeypatch.delenv(_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(_ENV, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_default_scope_is_the_opus_rooms_of_both_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _load(monkeypatch).memory_model_scope == [("story", "opus"), ("character", "opus")]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("opus", [("story", "opus"), ("character", "opus")], id="model-covers-both-lanes"),
        pytest.param("story:opus", [("story", "opus")], id="lane-and-model"),
        pytest.param(
            " opus , character:gemini ,",
            [("story", "opus"), ("character", "opus"), ("character", "gemini")],
            id="spaces-and-empty-items",
        ),
        pytest.param("", [], id="blank-is-no-room"),
    ],
)
def test_entries_expand_to_lane_and_model_pairs(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: list[tuple[str, str]]
) -> None:
    assert _load(monkeypatch, value).memory_model_scope == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("gpt", id="unknown-model"),
        pytest.param("haiku", id="judgment-only-model"),
        pytest.param("story:haiku", id="judgment-only-model-with-lane"),
        pytest.param("novel:opus", id="unknown-lane"),
        pytest.param("story:", id="empty-model"),
        pytest.param(":opus", id="empty-lane"),
        pytest.param("story:opus:x", id="two-colons"),
        pytest.param("opus,Opus", id="case-matters"),
    ],
)
def test_an_unknown_or_malformed_entry_refuses_to_start(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    with pytest.raises(ValidationError, match="memory_model_scope"):
        _load(monkeypatch, value)


# 설정 값 → 범위 안인 (레인, 글쓰기 모델). 표에 없는 조합은 범위 밖이다.
_SCOPE_TABLE = {
    "opus": {("story", "opus"), ("character", "opus")},
    "story:opus": {("story", "opus")},
    "opus,sonnet": {("story", "opus"), ("character", "opus"), ("story", "sonnet"), ("character", "sonnet")},
    "character:gemini": {("character", "gemini")},
    "story:sonnet,character:opus": {("story", "sonnet"), ("character", "opus")},
    "": set(),
}


@pytest.mark.parametrize("value", list(_SCOPE_TABLE))
def test_in_scope_judgment_follows_the_configured_lane_and_model_pairs(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    scope = _load(monkeypatch, value).memory_model_scope

    judged = {
        (lane, model)
        for lane in ("story", "character")
        for model in ("gemini", "sonnet", "opus")
        if memory_model_in_scope(lane, model, scope)
    }

    assert judged == _SCOPE_TABLE[value]
