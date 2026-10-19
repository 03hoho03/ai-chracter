"""프로브용 격리 API 서버를 띄우고 내린다.

서버는 `uv run --env-file .env uvicorn api.main:app` 이고, 실행 명령의 환경변수가 `.env` 를 덮는다: 작업 DB(`DATABASE_URL`),
프로브마다 따로인 프롬프트 덤프 파일(`PROMPT_DUMP_PATH`), 갈래 설정, 판정·요약 모델 배정. 🔴 유료 호출 승인 인자가 없으면
`ANTHROPIC_DIRECT_API_KEY` 를 빈 값으로 덮어 띄운다 — `.env` 에 실제 키가 있어도 서버가 Anthropic 을 부를 수 없다."""

import os
import re
import signal
import subprocess
import time
from collections.abc import Collection, Mapping
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


def conflicting_servers(
    procs: list[tuple[int, str, int | None]],
    trees: list[str],
    *,
    own_pids: set[int],
    own_ports: Collection[int] = (),
    own_tree: str | None = None,
) -> list[tuple[int, str, int | None]]:
    """같은 격리 Redis·DB 를 쓰는 트리(`trees`)에서 도는 다른 서버(pid, 작업 디렉터리, `--port`). 프로브는 방 키·활성 세트 캐시를
    지우고 DB 를 템플릿으로 갈아 끼우므로, 그동안 다른 측정 서버가 같은 자원을 쓰면 서로의 상태를 깬다.

    이 실행의 프로브 작업자 서버는 통과시킨다 — 이 트리(`own_tree`) 안에서 작업자 포트(`own_ports`)로 뜬 서버. 작업자마다 작업
    DB·Redis 번호가 따로라 서로의 자원을 쓰지 않는다. 같은 포트라도 다른 트리의 서버, 이 트리라도 작업자 포트가 아닌 서버는
    거부한다."""
    conflicts: list[tuple[int, str, int | None]] = []
    for pid, cwd, port in procs:
        if pid in own_pids:
            continue
        if not cwd:
            # 작업 디렉터리를 읽지 못한 서버는 어느 트리인지 모른다 — 통과시키지 않는다.
            print(f"경고: API 서버 pid {pid} 의 작업 디렉터리를 읽지 못했다 — 같은 자원을 쓴다고 보고 거부한다")
            conflicts.append((pid, cwd, port))
        elif own_tree is not None and port in own_ports and _under(cwd, own_tree):
            continue
        elif any(_under(cwd, tree) for tree in trees):
            conflicts.append((pid, cwd, port))
    return conflicts


def leftover_worker_servers(
    procs: list[tuple[int, str, int | None]], *, own_tree: str, ports: Collection[int]
) -> list[tuple[int, int]]:
    """중단된 프로브 실행이 남긴 작업자 서버(pid, 포트): 이 트리(`own_tree`) 안에서 이 실행의 작업자 포트(`ports`)로 뜬 서버만.
    다른 트리의 측정 서버, 이 트리라도 작업자 포트가 아닌 서버(개발 서버 등), 작업 디렉터리를 읽지 못한 서버는 고르지 않는다 —
    내리는 일은 되돌릴 수 없어, 거부할 때(`conflicting_servers`)와 달리 모르는 쪽을 건드리지 않는 편으로 고른다."""
    return [
        (pid, port) for pid, cwd, port in procs if cwd and port is not None and port in ports and _under(cwd, own_tree)
    ]


def stop_pids(pids: Collection[int], *, timeout: float = 30.0) -> list[int]:
    """프로세스마다 SIGTERM 을 보내고 `timeout` 초까지 기다린 뒤 남은 것에 SIGKILL 을 보낸다. SIGKILL 까지 간 pid 를 돌려준다."""

    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(alive(pid) for pid in pids):
        time.sleep(0.5)
    killed = [pid for pid in pids if alive(pid)]
    for pid in killed:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return killed


def _under(path: str, tree: str) -> bool:
    return path == tree.rstrip("/") or path.startswith(tree.rstrip("/") + "/")


_PORT_ARG = re.compile(r"--port[ =](\d+)")


def running_api_servers() -> list[tuple[int, str, int | None]]:
    """이 기계에서 도는 `uvicorn api.main:app` 프로세스와 그 작업 디렉터리, 명령줄의 `--port`(없으면 None)."""
    found = subprocess.run(["pgrep", "-f", "[u]vicorn api.main:app"], capture_output=True, text=True, check=False)
    procs = []
    for raw in found.stdout.split():
        pid = int(raw)
        cwd = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, check=False
        )
        path = next((line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")), "")
        args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, check=False)
        port = _PORT_ARG.search(args.stdout)
        procs.append((pid, path, int(port.group(1)) if port else None))
    return procs


# 측정 하네스가 도는 워크트리 이름의 머리. 이 이름의 워크트리들이 같은 격리 Redis·DB 를 쓴다.
HARNESS_TREE_GLOB = "long-memory*"


def harness_trees(api_dir: Path) -> list[str]:
    """같은 격리 자원을 쓰는 트리: 이 실행의 트리와, 저장소 루트(주 체크아웃) 아래 `.claude/worktrees/` 의 측정 워크트리들.

    루트는 git 의 공용 디렉터리(`--git-common-dir`)로 찾는다 — 실행 위치에서 상대 경로로 짐작하면 루트 체크아웃에서 돌 때
    워크트리 목록이 비어 검사가 조용히 꺼진다. 루트 체크아웃 자체는 거기서 돌 때만 든다(워크트리에서 돌 때 루트의 개발 서버는
    측정 워크트리와 다른 자원을 쓸 수 있어 전처럼 보지 않는다). git 저장소 밖이면 거부한다."""
    found = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir", "--show-toplevel"],
        cwd=api_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = found.stdout.split()
    if found.returncode != 0 or len(lines) != 2:
        raise SystemExit(f"{api_dir} 의 git 저장소 루트를 찾지 못했다 — 같은 자원을 쓰는 서버 검사를 켤 수 없다")
    common, here = (Path(line).resolve() for line in lines)
    root = common.parent
    trees = {str(here), *(str(p.resolve()) for p in (root / ".claude" / "worktrees").glob(HARNESS_TREE_GLOB))}
    return sorted(trees)
