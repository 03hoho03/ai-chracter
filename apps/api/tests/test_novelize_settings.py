import uuid

import pytest
from pydantic import ValidationError

from api.core.config import Settings

_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _allowlist_from_env(monkeypatch: pytest.MonkeyPatch, raw: str) -> list[uuid.UUID]:
    monkeypatch.setenv("NOVELIZE_GRANT_ALLOWLIST", raw)
    return Settings(_env_file=None).novelize_grant_allowlist  # type: ignore[call-arg]


def test_allowlist_comma_separated_env_is_split(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 파일은 따옴표 없는 값만 쓰므로 쉼표 구분이 유일한 표기다."""
    assert _allowlist_from_env(monkeypatch, f" {_A} , ,{_B},") == [_A, _B]


@pytest.mark.parametrize("raw", ["", " ", ","])
def test_allowlist_empty_value_is_an_empty_list(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """빈 명단은 아무에게도 허용할 수 없다는 뜻이라 정상 값이다 — 기동을 막지 않는다."""
    assert _allowlist_from_env(monkeypatch, raw) == []


def test_allowlist_rejects_a_non_uuid_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """오타 난 id 를 조용히 버리면 운영자가 허용했다고 믿는 계정이 막힌 채로 남는다 — 기동에서 멈춘다."""
    with pytest.raises(ValidationError):
        _allowlist_from_env(monkeypatch, f"{_A},not-a-uuid")


def test_novelize_defaults_are_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOVELIZE_ENABLED", raising=False)
    monkeypatch.delenv("NOVELIZE_GRANT_ALLOWLIST", raising=False)
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    assert defaults.novelize_enabled is False
    assert defaults.novelize_grant_allowlist == []
