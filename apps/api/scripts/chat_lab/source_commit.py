"""측정 서버 checkout 의 커밋 — 올리기 머리의 만든 커밋(`sourceCommit`).

띄울 때 한 번 읽는다 — 까닭과 더러움의 뜻은 `apps/chat-lab/README.md` 「묶음 계약 판과 출처 칸」 절.

git 을 부르는 자리는 `run_git` 하나다(테스트가 바꿔 넣는 자리)."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from chat_lab.schemas import SourceCommit

# git 을 돌릴 폴더 — 이 파일이 있는 checkout 안이면 어디든 같은 저장소다.
CHECKOUT = Path(__file__).resolve().parent


def run_git(args: Sequence[str]) -> str:
    """checkout 에서 git 을 돌려 표준 출력. git 이 없으면 `OSError`, 0 이 아닌 종료면 `subprocess.CalledProcessError`."""
    return subprocess.run(["git", "-C", str(CHECKOUT), *args], check=True, capture_output=True, text=True).stdout


def read_source_commit() -> SourceCommit | None:
    """지금 checkout 의 커밋 id 와 더러움. git 으로 읽지 못하면(git 이 없거나 checkout 이 아니다) None."""
    try:
        commit = run_git(["rev-parse", "HEAD"]).strip()
        changed = run_git(["status", "--porcelain", "--untracked-files=no"])
    except (OSError, subprocess.CalledProcessError):
        return None
    return SourceCommit(commit=commit, dirty=bool(changed.strip()))
