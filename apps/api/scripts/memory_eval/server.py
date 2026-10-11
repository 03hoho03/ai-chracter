"""프로브용 격리 API 서버를 띄우고 내린다.

서버는 `uv run --env-file .env uvicorn api.main:app` 이고, 실행 명령의 환경변수가 `.env` 를 덮는다: 작업 DB(`DATABASE_URL`),
프로브마다 따로인 프롬프트 덤프 파일(`PROMPT_DUMP_PATH`), 갈래 설정, 판정·요약 모델 배정. 🔴 유료 호출 승인 인자가 없으면
`ANTHROPIC_DIRECT_API_KEY` 를 빈 값으로 덮어 띄운다 — `.env` 에 실제 키가 있어도 서버가 Anthropic 을 부를 수 없다."""

import os
import signal
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

API_DIR = Path(__file__).resolve().parents[2]


@dataclass
class ServerHandle:
    process: subprocess.Popen[bytes]
    base: str
    log: Path


def server_env(overrides: Mapping[str, str], *, allow_paid: bool) -> dict[str, str]:
    env = {**os.environ, **overrides}
    if not allow_paid:
        env["ANTHROPIC_DIRECT_API_KEY"] = ""
    return env


def start(
    overrides: Mapping[str, str], *, port: int, log: Path, allow_paid: bool, timeout: float = 90.0
) -> ServerHandle:
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab")
    process = subprocess.Popen(
        ["uv", "run", "--env-file", ".env", "uvicorn", "api.main:app", "--port", str(port)],
        cwd=API_DIR,
        env=server_env(overrides, allow_paid=allow_paid),
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"서버가 기동 중 종료됐다(코드 {process.returncode}) — {log} 확인")
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                return ServerHandle(process=process, base=base, log=log)
        except httpx.HTTPError:
            pass
        time.sleep(1)
    stop(ServerHandle(process=process, base=base, log=log))
    raise SystemExit(f"서버가 {timeout:.0f}초 안에 뜨지 않았다 — {log} 확인")


def stop(server: ServerHandle, *, timeout: float = 30.0) -> None:
    if server.process.poll() is not None:
        return
    os.killpg(server.process.pid, signal.SIGTERM)
    try:
        server.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(server.process.pid, signal.SIGKILL)
        server.process.wait()


def port_in_use(port: int) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
    except httpx.HTTPError:
        return False
    return True
