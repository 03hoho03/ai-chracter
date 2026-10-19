"""측정 커밋 고정 — 하네스가 측정 커밋에서, 추적 파일을 고치지 않은 채 도는지.

측정은 정해 둔 하네스 커밋으로 잰다. 다른 커밋에서 돌거나 추적 파일을 고친 채 돌면 그 결과는 그 커밋으로 잰 것이 아니다. 실행
틀(`run_template.sh`)은 측정 커밋을 env 로 받아 전역 인자 `--expect-head` 로 넘기고, 진입점은 명령을 돌리기 전에 이 단언을 하고
결과를 상태 파일에 남긴다.

추적 파일만 본다 — 산출 폴더(`probe-runs/`)는 gitignore 되어 있고, 추적하지 않는 파일은 하네스 코드가 아니다."""

import subprocess
from pathlib import Path
from typing import Any

# 기대 커밋을 인자 대신 줄 때의 env 이름.
EXPECT_HEAD_ENV = "MEMORY_EVAL_EXPECT_HEAD"
# 볼 저장소 — 이 하네스 파일이 든 작업 트리.
REPO = Path(__file__).resolve().parent


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def measured_head(repo: Path, expected: str) -> dict[str, Any]:
    """HEAD 가 `expected`(전체 또는 앞부분 sha)와 같은 커밋이고 추적 파일 변경이 없으면 기록 칸을 돌려준다. 아니면 `SystemExit`."""
    want = _git(repo, "rev-parse", "--verify", "--quiet", f"{expected}^{{commit}}")
    if want.returncode != 0:
        raise SystemExit(f"측정 커밋을 이 저장소에서 찾지 못했다: {expected}")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    target = want.stdout.strip()
    if head != target:
        raise SystemExit(f"HEAD {head[:12]} 가 측정 커밋 {target[:12]} 와 다르다 — 측정 커밋으로 옮긴 뒤 다시 돌린다")
    status = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        raise SystemExit(f"작업 트리 상태를 읽지 못했다: {status.stderr.strip()}")
    changed = [line[3:] for line in status.stdout.splitlines() if line.strip()]
    if changed:
        raise SystemExit(f"추적 파일에 커밋하지 않은 변경이 {len(changed)}개 있다: {changed[:10]}")
    return {"ok": True, "expected": expected, "head": head}
