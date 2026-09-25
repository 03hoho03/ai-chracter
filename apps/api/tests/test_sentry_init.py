"""`api.main._init_sentry()`가 `settings.sentry_dsn` 유무로
`sentry_sdk.init()` 호출을 게이트하는지, 호출될 때 옵션이 `build_sentry_options()`의
결과를 그대로 포함하는지 검증한다.

전역 `sentry_sdk.init()`을 실제로 부르면 테스트 프로세스의 SDK 상태가 오염된다
(`_processed_integrations`/`_installed_integrations`가 프로세스 전역 캐시라는 것이 바로
`build_sentry_options()`를 거치지 않은 초기화 경로를 만들면 안 되는 이유다) — 그래서
`sentry_sdk.init` 자체를 스텁으로 갈아끼우고 호출 여부·인자만 관찰한다.
"""

import os
import subprocess
import sys
from typing import Any

import pytest
import sentry_sdk

from api import main
from api.core.config import settings
from api.core.sentry import build_sentry_options


def test_init_sentry_noop_when_dsn_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    # `main.py`의 모듈 전역 `settings`는 `api.core.config.settings`와 같은 싱글턴 객체다
    # (mypy strict의 `--no-implicit-reexport`가 `main.settings` attribute 접근을 막으므로
    # 여기서 직접 그 원본을 patch한다).
    monkeypatch.setattr(settings, "sentry_dsn", "")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    main._init_sentry()

    assert calls == []


def test_init_sentry_calls_init_with_scrubbing_options_when_dsn_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "sentry_dsn", "https://key@example.com/1")
    monkeypatch.setattr(settings, "sentry_environment", "production")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    main._init_sentry()

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["dsn"] == "https://key@example.com/1"
    assert kwargs["environment"] == "production"
    for key, value in build_sentry_options().items():
        assert kwargs[key] == value


def test_init_sentry_is_actually_called_when_api_main_is_imported() -> None:
    """위 두 테스트는 `main._init_sentry()`를 직접 호출할 뿐이라, `main.py` 모듈 최상단의
    `_init_sentry()` 호출 줄이 지워져도(리팩터·머지 충돌 등) 계속 통과한다 — 그 줄이 프로덕션
    Sentry를 영구 비활성으로 만드는 유일한 스위치인데도 이 사각을 아무도 못 잡는다.

    `import api.main`이 이미 이 프로세스에서 끝나 있어(다른 테스트 파일이 이미 로드) 여기서
    다시 import해도 재실행되지 않고, `importlib.reload(main)`은 모듈 top-level을 통째로
    재실행해 `app = FastAPI(...)`를 새로 만들고 모든 라우터를 재등록한다 — `conftest.py`의
    `from api.main import app`이 붙잡고 있는 객체와 갈라져 이후 테스트가 어떤 `app`을 오버라이드
    하는지 꼬인다. 그래서 별도 서브프로세스에서 처음부터 `import api.main`을 시켜 관찰한다 —
    이 프로세스의 sentry_sdk/전역 상태는 전혀 건드리지 않는다.
    """
    script = (
        "import sentry_sdk\n"
        "calls = []\n"
        "sentry_sdk.init = lambda **kwargs: calls.append(kwargs)\n"
        "import api.main\n"
        "print(len(calls))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "SENTRY_DSN": "https://key@example.com/1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1", result.stderr
