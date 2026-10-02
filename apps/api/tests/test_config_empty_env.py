import pytest

from api.core.config import Settings

_MODEL_SWITCH_FIELDS = (
    "gemini_stat_judgment_model_name",
    "gemini_ending_judgment_model_name",
    "gemini_image_judgment_model_name",
    "gemini_publish_filter_model_name",
)


def test_empty_thinking_budget_env_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 에 `KEY=` 처럼 값만 비운 줄이 남아 있어도 기동한다 — 사고 예산을 넘기지 않는 기본 상태로 읽는다.
    빈 모델명이 기본 모델로 도는 것과 같은 성질이다."""
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "")

    assert Settings().gemini_thinking_budget is None


@pytest.mark.parametrize(("raw", "expected"), [("0", 0), ("512", 512)])
def test_thinking_budget_env_values_still_parse(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
    """0(사고 끔)은 빈 값과 다른 상태다 — 빈 값만 None 이 되고 숫자는 그대로 읽힌다."""
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", raw)

    assert Settings().gemini_thinking_budget == expected


@pytest.mark.parametrize("field", _MODEL_SWITCH_FIELDS)
def test_model_switches_default_to_unset_and_read_env(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    """정하지 않으면 None(기본 모델로 돈다), env 에 넣으면 그 모델명이다."""
    monkeypatch.delenv(field.upper(), raising=False)
    assert getattr(Settings(_env_file=None), field) is None  # type: ignore[call-arg]

    monkeypatch.setenv(field.upper(), "gemini-x")
    assert getattr(Settings(), field) == "gemini-x"
