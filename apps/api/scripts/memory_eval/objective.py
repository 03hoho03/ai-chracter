"""목적함수 파일(`objective.json`) — 격자에서 하나를 고르는 순서는 결과보다 먼저 커밋돼 있어야 한다.

격자 결과를 본 뒤 고르는 순서를 고치면 선택이 결과에 맞춰진다. 그래서 고르는 명령은 목적함수 파일이 git 에 커밋돼 있고 작업
트리·스테이지에 커밋 뒤 변경이 없을 때만 그 파일을 읽고, 결과에 그 커밋과 sha256 을 적는다. 커밋만으로는 결과를 본 뒤
목적함수를 고쳐 다시 커밋하고 같은 결과 파일에 다시 고르는 것을 못 막으므로, 결과 파일이 이미 있으면 그 안의 목적함수
sha256 이 지금 파일과 같을 때만 덮어쓴다. 파일 꼴:

    {"sectionGrid": ["primaryHits", "secretHits", "-abstainMisinjected", "constant_ratio", "tau"]}

목록 순서대로 견주며, 이름 앞에 `-` 가 있으면 값이 작을수록, 없으면 클수록 낫다. 사실 섹션 격자는 다섯 기준을 하나도 빼지 않는다."""

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

OBJECTIVE_FILE = "objective.json"  # cite-ok: 하네스가 여는 목적함수 파일의 실제 이름이다
# 사실 섹션 격자 결과에서 견줄 수 있는 기준 — 앞 셋은 결과 칸, 뒤 둘은 설정 칸이다.
SECTION_GRID_KEYS = frozenset({"primaryHits", "secretHits", "abstainMisinjected", "constant_ratio", "tau"})


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def load_committed_objective(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"목적함수 파일이 없다: {path}")
    repo, name = path.resolve().parent, path.resolve().name
    commit = _git(repo, "log", "-1", "--format=%H", "--", name).stdout.strip()
    if _git(repo, "ls-files", "--error-unmatch", "--", name).returncode != 0 or not commit:
        raise SystemExit(f"목적함수 파일이 git 에 커밋돼 있지 않다 — 결과보다 먼저 커밋한다: {path}")
    if _git(repo, "diff", "--quiet", "HEAD", "--", name).returncode != 0:
        raise SystemExit(
            f"목적함수 파일이 커밋된 내용과 다르다(작업 트리·스테이지 변경) — 커밋한 그대로만 읽는다: {path}"
        )
    return {
        "path": str(path),
        "commit": commit,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "objective": json.loads(path.read_text(encoding="utf-8")),
    }


def refuse_result_from_other_objective(out: Path, objective: Mapping[str, Any]) -> None:
    """결과 파일이 이미 있고 그 안의 목적함수 sha256 이 지금 목적함수와 다르면(기록이 없어도) 덮어쓰지 않고 거부한다."""
    if not out.exists():
        return
    try:
        earlier = json.loads(out.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        earlier = None
    recorded = (earlier.get("objective") or {}).get("sha256") if isinstance(earlier, dict) else None
    if recorded != objective["sha256"]:
        raise SystemExit(
            f"결과 파일이 다른 목적함수(sha256 {recorded})로 이미 골라져 있다 — 지금 목적함수({objective['sha256']})로 "
            f"덮어쓰지 않는다. 새 결과 파일에 쓴다: {out}"
        )


def section_grid_order(objective: Mapping[str, Any]) -> list[tuple[str, int]]:
    """사실 섹션 격자의 고르는 순서 — (기준, 큰 쪽이 나으면 1 · 작은 쪽이면 -1)."""
    raw: Sequence[str] = objective.get("sectionGrid") or []
    order = [(k[1:], -1) if k.startswith("-") else (k, 1) for k in raw]
    keys = [k for k, _ in order]
    if sorted(keys) != sorted(SECTION_GRID_KEYS):
        raise SystemExit(f"목적함수의 사실 섹션 격자 기준은 {sorted(SECTION_GRID_KEYS)} 를 한 번씩 적는다: {list(raw)}")
    return order
