import pytest

from api.core.config import Settings

_BUDGET_FIELDS = (
    "gemini_thinking_budget",
    "gemini_judgment_thinking_budget",
    "gemini_publish_filter_thinking_budget",
)


@pytest.mark.parametrize("field", _BUDGET_FIELDS)
def test_empty_thinking_budget_env_means_unset(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    """env 에 `KEY=` 처럼 값만 비운 줄이 남아 있어도 기동한다 — 사고 예산을 넘기지 않는 기본 상태로 읽는다.
    빈 모델명이 기본 모델로 도는 것과 같은 성질이다."""
    monkeypatch.setenv(field.upper(), "")

    assert getattr(Settings(), field) is None


@pytest.mark.parametrize("field", _BUDGET_FIELDS)
@pytest.mark.parametrize(("raw", "expected"), [("0", 0), ("512", 512)])
def test_thinking_budget_env_values_still_parse(
    monkeypatch: pytest.MonkeyPatch, field: str, raw: str, expected: int
) -> None:
    """0(사고 끔)은 빈 값과 다른 상태다 — 빈 값만 None 이 되고 숫자는 그대로 읽힌다."""
    monkeypatch.setenv(field.upper(), raw)

    assert getattr(Settings(), field) == expected
