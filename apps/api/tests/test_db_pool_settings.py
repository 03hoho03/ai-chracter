"""DB 커넥션 풀 크기를 env 로 정한다 — 워커 수를 늘릴 때 워커 × (기본 + 초과) 가 Postgres 연결 상한을
넘지 않게 줄이려고. 기본값은 env 를 넣기 전과 같은 풀이어야 병합만으로 동작이 바뀌지 않는다."""

import os
import subprocess
import sys

import pytest

from api.core.config import Settings

_POOL_ENV = ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT")


def test_pool_defaults_are_the_sqlalchemy_defaults_the_app_ran_with(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 를 안 넣은 배포에서 풀이 바뀌면(예: 기본값을 줄이면) 동시 요청이 풀 대기로 밀려 30초 뒤 500 이
    난다. 지금까지 앱은 풀 인자 없이 SQLAlchemy 기본값(5 + 초과 10, 대기 30초)으로 돌았다."""
    for name in _POOL_ENV:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert (settings.db_pool_size, settings.db_max_overflow, settings.db_pool_timeout) == (5, 10, 30)


def test_the_app_engine_uses_the_pool_env() -> None:
    """설정 필드만 있고 엔진에 안 넘기면 운영 `.env` 에 값을 넣어도 풀은 그대로라 워커를 늘렸을 때 연결
    상한을 넘는다. 기본값과 다른 값을 넣어 엔진까지 닿는지 본다(기본값으로 보면 안 넘겨도 같은 값이라
    아무것도 확인하지 못한다). 엔진은 import 시점에 만들어지므로 새 프로세스에서 본다."""
    script = (
        "from api.db.session import engine\n"
        "pool = engine.pool\n"
        "print(pool.size(), pool._max_overflow, pool.timeout())\n"
    )
    env = {**os.environ, "DB_POOL_SIZE": "7", "DB_MAX_OVERFLOW": "3", "DB_POOL_TIMEOUT": "12"}

    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["7", "3", "12.0"]
