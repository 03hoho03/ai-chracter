"""기동·마이그레이션이 실패할 때 출력에 비밀값이 새지 않는지.

운영과 같은 진입점을 하위 프로세스로 돌린다 — uvicorn 이 lifespan 실패 글(예외 전문)을 그대로 찍고, alembic 이 설정값 보간
오류에 값 전체를 싣는 경로까지 실제로 거치게 하려는 것이다. 하위 프로세스에는 PATH 와 이 테스트가 정한 값만 물려준다 —
개발자 셸의 다른 비밀이 섞이지 않게.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from harness import SV_ROOT
from keys import AUD, ISSUER

TIME_LIMIT_SECONDS = 30


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _marker() -> str:
    return f"Mk{secrets.token_hex(6)}"


def _password(marker: str) -> str:
    # URL 인코딩한 비밀번호는 `%` 를 담는다 — ConfigParser 보간이 그 글자에서 값 전체를 오류에 싣는다.
    return f"Pw%40{marker}%25z"


def _bad_database_url(marker: str) -> str:
    return f"postgresql+asyncpg://chat_lab:{_password(marker)}@127.0.0.1:{_closed_port()}/chat_lab"


def _service_env(web_dir: Path, **overrides: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "LAB_DATABASE_URL": "postgresql+asyncpg://chat_lab:unused@127.0.0.1:1/chat_lab",
        "LAB_ACCESS_ISSUER": ISSUER,
        "LAB_ACCESS_AUD": AUD,
        "LAB_READ_EMAILS": "reader@example.com",
        "LAB_UPLOAD_CLIENT_IDS": "uploader-client.access",
        "LAB_WEB_DIR": str(web_dir),
    }
    env.update(overrides)
    return env


def _run(command: list[str], env: dict[str, str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command, cwd=SV_ROOT, env=env, capture_output=True, timeout=TIME_LIMIT_SECONDS, check=False
        )
    except subprocess.TimeoutExpired as expired:
        partial = (expired.stdout or b"") + (expired.stderr or b"")
        pytest.fail(
            f"{TIME_LIMIT_SECONDS}초 안에 끝나지 않았다 — 실패해야 할 기동이 떠 있었다:\n"
            + partial.decode("utf-8", errors="replace")[-2000:]
        )
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    return completed.returncode, output


def _start_service(env: dict[str, str]) -> tuple[int, str]:
    return _run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "chat_lab_service.main:create_app_from_env",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(_closed_port()),
            "--no-access-log",
        ],
        env,
    )


# 서비스 코드에 닿기도 전에 끝난 실패(패키지·ini·마이그레이션 폴더가 없음)의 글. 이런 실패에서는 DB 주소를 읽지도 않았으므로
# 비밀 표지가 없다는 것이 아무것도 말하지 않는다.
UNREACHED = ("No module named", "No config file", "Path doesn't exist", "No 'script_location'")
# 닿지 않는 포트로 실제 접속을 시도했을 때 asyncpg 가 내는 예외의 이름·글 가운데 하나. 이 가운데 하나가 출력에 있어야
# 주소를 읽고 접속 단계까지 간 실패다(macOS 실측은 `ConnectionRefusedError: [Errno 61] Connect call failed (…)`).
CONNECT_ATTEMPTED = (
    "ConnectionRefusedError",
    "Connect call failed",
    "ConnectionError",
    "OSError",
    "CannotConnectNowError",
)


def _assert_hidden(code: int, output: str, *markers: str) -> None:
    assert code != 0, output[-2000:]
    for unreached in UNREACHED:
        assert unreached not in output, output[-2000:]
    for marker in markers:
        assert marker not in output, f"비밀 표지가 출력에 나왔다:\n{output[-2000:]}"


def _assert_connect_attempted(output: str) -> None:
    assert any(sign in output for sign in CONNECT_ATTEMPTED), (
        f"DB 접속을 시도한 흔적이 없다 — 주소를 읽기 전에 다른 이유로 실패했다:\n{output[-2000:]}"
    )


def test_bad_database_url_at_startup_hides_password(web_dir: Path) -> None:
    # DB 에 닿지 않아 기동 점검(마이그레이션 판 대조)이 실패하는 경로다.
    marker = _marker()
    code, output = _start_service(_service_env(web_dir, LAB_DATABASE_URL=_bad_database_url(marker)))
    _assert_hidden(code, output, marker)
    # 설정은 통과하고 lifespan 의 기동 점검이 DB 에 접속하려다 실패했다는 표지.
    assert "Application startup failed" in output, output[-2000:]
    _assert_connect_attempted(output)


@pytest.mark.parametrize("shape", ["no-scheme", "bad-port"])
def test_unparsable_database_url_hides_value(web_dir: Path, shape: str) -> None:
    marker = _marker()
    url = {
        "no-scheme": f"chat_lab:{_password(marker)}@127.0.0.1/chat_lab",
        "bad-port": f"postgresql+asyncpg://chat_lab:{_password(marker)}@127.0.0.1:port/chat_lab",
    }[shape]
    code, output = _start_service(_service_env(web_dir, LAB_DATABASE_URL=url))
    _assert_hidden(code, output, marker)
    # 무엇이 틀렸는지는 값 없이 설정 이름으로 알린다.
    assert "LAB_DATABASE_URL" in output, output[-2000:]


def test_migration_with_bad_url_hides_password() -> None:
    # 마이그레이션은 DB 주소 하나만 읽는다 — Access 설정 없이 돈다.
    marker = _marker()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "LAB_DATABASE_URL": _bad_database_url(marker),
    }
    code, output = _run([sys.executable, "-m", "alembic", "upgrade", "head"], env)
    _assert_hidden(code, output, marker)
    assert "interpolation" not in output.lower(), output[-2000:]
    _assert_connect_attempted(output)


def test_invalid_settings_error_hides_values(web_dir: Path) -> None:
    password_marker = _marker()
    issuer_marker = _marker()
    email_marker = _marker()
    env = _service_env(
        web_dir,
        LAB_DATABASE_URL=f"postgresql+asyncpg://chat_lab:{_password(password_marker)}@127.0.0.1:5432/chat_lab",
        LAB_ACCESS_ISSUER=f"http://{issuer_marker}.cloudflareaccess.com/",
        LAB_READ_EMAILS=f"{email_marker}@example.com",
        LAB_UPLOAD_CLIENT_IDS="",
    )
    code, output = _start_service(env)
    _assert_hidden(code, output, password_marker, issuer_marker, email_marker)
    # 설정 검증에서 실패했다는 표지(pydantic 의 "N validation error(s) for Settings") — 다른 이유로 일찍 끝난 실패가 아니다.
    assert "validation error" in output.lower(), output[-2000:]
    # 값은 숨기되 어느 설정이 틀렸는지는 이름으로 알린다.
    assert "access_issuer" in output.lower(), output[-2000:]
    assert "upload_client_ids" in output.lower(), output[-2000:]
