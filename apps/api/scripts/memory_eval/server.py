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


def conflicting_servers(procs: list[tuple[int, str]], trees: list[str], *, own_pids: set[int]) -> list[tuple[int, str]]:
    """같은 격리 Redis·DB 를 쓰는 워크트리(`trees`)에서 도는 다른 서버. 프로브는 방 키·활성 세트 캐시를 지우고 DB 를 템플릿으로
    갈아 끼우므로, 그동안 다른 측정 서버가 같은 자원을 쓰면 서로의 상태를 깬다."""
    conflicts: list[tuple[int, str]] = []
    for pid, cwd in procs:
        if pid in own_pids:
            continue
        if not cwd:
            # 작업 디렉터리를 읽지 못한 서버는 어느 트리인지 모른다 — 통과시키지 않는다.
            print(f"경고: API 서버 pid {pid} 의 작업 디렉터리를 읽지 못했다 — 같은 자원을 쓴다고 보고 거부한다")
            conflicts.append((pid, cwd))
        elif any(cwd == tree or cwd.startswith(tree.rstrip("/") + "/") for tree in trees):
            conflicts.append((pid, cwd))
    return conflicts


def running_api_servers() -> list[tuple[int, str]]:
    """이 기계에서 도는 `uvicorn api.main:app` 프로세스와 그 작업 디렉터리."""
    found = subprocess.run(["pgrep", "-f", "[u]vicorn api.main:app"], capture_output=True, text=True, check=False)
    procs = []
    for raw in found.stdout.split():
        pid = int(raw)
        cwd = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, check=False
        )
        path = next((line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")), "")
        procs.append((pid, path))
    return procs
