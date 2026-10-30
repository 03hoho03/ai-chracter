"""채팅 모델 공개 목록(`CHAT_MODELS_VISIBLE`) — 상위 모델 스위치가 켜져 있을 때 채팅에서 고를 수 있게 보일 상위 모델.

값은 쉼표로 나눈 모델 id 목록이다. 기본은 Opus 하나라, 이 설정이 생기기 전 운영 env 그대로 배포하면 Opus 는 지금처럼 보이고
Sonnet 은 숨는다. 모르는 id 는 기동에서 거부한다 — 오타가 조용히 무시되면 켠 모델이 화면에 없는데 기동은 성공한다. 기본 모델(Gemini)은
늘 보이므로 목록에 쓸 수 없다. 빈 값은 상위 모델을 하나도 보이지 않는다는 뜻이다(코드 기본값으로 대체하지 않는다).
"""

import pytest
from pydantic import ValidationError

from api.core.config import Settings

_ENV = "CHAT_MODELS_VISIBLE"


def _load(monkeypatch: pytest.MonkeyPatch, value: str | None = None) -> Settings:
    monkeypatch.delenv(_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(_ENV, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_without_the_env_line_only_opus_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _load(monkeypatch).chat_models_visible == ["opus"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("opus", ["opus"], id="opus"),
        pytest.param("opus,sonnet", ["opus", "sonnet"], id="both"),
        pytest.param("opus,haiku_writer", ["opus", "haiku_writer"], id="haiku-writer"),
        pytest.param("sonnet", ["sonnet"], id="sonnet-only"),
        pytest.param(" opus , sonnet ,", ["opus", "sonnet"], id="spaces-and-empty-items"),
        pytest.param("", [], id="blank-hides-every-premium-model"),
        pytest.param(" , ", [], id="only-separators-hide-every-premium-model"),
    ],
)
def test_entries_are_split_on_commas(monkeypatch: pytest.MonkeyPatch, value: str, expected: list[str]) -> None:
    assert _load(monkeypatch, value).chat_models_visible == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("sonet", id="typo"),
        pytest.param("gpt", id="unknown-model"),
        pytest.param("haiku", id="judgment-only-model"),
        pytest.param("gemini", id="default-model-is-always-visible"),
        pytest.param("opus,gemini", id="default-model-among-others"),
        pytest.param("opus,opus", id="duplicate"),
        pytest.param("Opus", id="case-matters"),
    ],
)
def test_an_unknown_duplicate_or_default_entry_refuses_to_start(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    with pytest.raises(ValidationError, match="chat_models_visible"):
        _load(monkeypatch, value)
