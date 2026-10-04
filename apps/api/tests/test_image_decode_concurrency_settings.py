"""이미지 디코드 동시 상한을 env 로 정한다 — 워커 수를 늘리면 상한이 워커 수만큼 곱해지므로, 워커 × 상한 × 건당
메모리가 VM 메모리를 넘지 않게 줄일 수 있어야 한다. 기본값은 env 를 넣기 전과 같은 상한이어야 병합만으로 동작이
바뀌지 않는다."""

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from api.core.config import Settings


def test_decode_concurrency_default_is_the_limit_the_app_ran_with(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 를 안 넣은 배포에서 상한이 바뀌면 업로드·블러가 한꺼번에 더 많이 디코드돼 메모리가 튀거나(올릴 때),
    더 오래 줄을 선다(내릴 때). 지금까지 앱은 프로세스당 3건으로 돌았다."""
    monkeypatch.delenv("IMAGE_DECODE_CONCURRENCY", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.image_decode_concurrency == 3


def test_decode_concurrency_zero_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 이면 세마포어가 아무도 들여보내지 않아 업로드 완료·발행 블러가 오류 없이 영원히 기다린다 — 기동에서 막는다."""
    monkeypatch.setenv("IMAGE_DECODE_CONCURRENCY", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_image_work_semaphore_uses_the_env() -> None:
    """설정 필드만 있고 세마포어에 안 넘기면 운영 `.env` 에 값을 넣어도 상한은 그대로다. 기본값과 다른 값을 넣고
    실제로 동시에 도는 작업 수를 센다(기본값으로 보면 안 넘겨도 같은 값이라 아무것도 확인하지 못한다). 세마포어는
    import 시점에 만들어지므로 새 프로세스에서 본다."""
    script = (
        "import asyncio, threading, time\n"
        "from api.assets.image_processing import run_image_work\n"
        "lock = threading.Lock()\n"
        "counts = {'running': 0, 'peak': 0}\n"
        "def job():\n"
        "    with lock:\n"
        "        counts['running'] += 1\n"
        "        counts['peak'] = max(counts['peak'], counts['running'])\n"
        "    time.sleep(0.05)\n"
        "    with lock:\n"
        "        counts['running'] -= 1\n"
        "async def main():\n"
        "    await asyncio.gather(*(run_image_work(job) for _ in range(12)))\n"
        "asyncio.run(main())\n"
        "print(counts['peak'])\n"
    )
    env = {**os.environ, "IMAGE_DECODE_CONCURRENCY": "5"}

    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["5"]
