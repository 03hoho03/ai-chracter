from pathlib import Path

import pytest
from pydantic import ValidationError

from api.core.config import Settings

_PROD_ORIGINS = ["https://ddona.site", "https://admin.ddona.site"]


def _origins_from_env(monkeypatch: pytest.MonkeyPatch, raw: str) -> list[str]:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", raw)
    return Settings(_env_file=None).cors_allow_origins  # type: ignore[call-arg]


def test_comma_separated_env_is_split(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 파일은 따옴표 없는 값만 쓰므로 쉼표 구분이 기본 표기다."""
    assert _origins_from_env(monkeypatch, "https://ddona.site,https://admin.ddona.site") == _PROD_ORIGINS


def test_json_array_env_still_reads_the_same_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """예전 운영 값(JSON 배열)이 바뀌기 전까지 같은 리스트로 읽혀야 배포가 CORS 를 깨지 않는다."""
    assert _origins_from_env(monkeypatch, '["https://ddona.site","https://admin.ddona.site"]') == _PROD_ORIGINS


def test_items_are_trimmed_and_empty_items_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _origins_from_env(monkeypatch, " https://a , ,https://b ,") == ["https://a", "https://b"]


@pytest.mark.parametrize("raw", ["", " ", ",", " , "])
def test_no_origin_left_fails_startup(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """빈 값으로 뜨면 운영 FE 요청이 전부 막히므로 기동에서 멈춘다(바꾸기 전에도 빈 값은 기동 실패였다)."""
    with pytest.raises(ValidationError):
        _origins_from_env(monkeypatch, raw)


def test_default_is_local_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_allow_origins == [  # type: ignore[call-arg]
        "http://localhost:5173",
        "http://localhost:5174",
    ]


def test_dotenv_file_uses_same_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """로컬은 pydantic 이 `.env` 파일을 직접 읽기도 한다 — 프로세스 env 와 같은 결과여야 한다."""
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("CORS_ALLOW_ORIGINS=https://ddona.site,https://admin.ddona.site\n", encoding="utf-8")
    assert Settings(_env_file=env_file).cors_allow_origins == _PROD_ORIGINS  # type: ignore[call-arg]
