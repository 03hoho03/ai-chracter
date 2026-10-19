"""측정 커밋 고정 — 실행 틀은 시작할 때 HEAD 가 측정 커밋과 같고 추적 파일에 변경이 없는지 단언하고 그 결과를 상태 파일에 남긴다.
다른 커밋에서 돌거나 고친 코드로 돈 측정은 봉인한 하네스로 잰 것이 아니다. gitignore 된 산출 폴더와 추적하지 않는 파일은 보지
않는다."""

import json
import subprocess
from pathlib import Path

import pytest

from memory_eval import head_check


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text("probe-runs/\n", encoding="utf-8")
    (root / "code.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "one")
    return root


def test_same_head_and_clean_tree_returns_the_record(repo: Path) -> None:
    sha = _git(repo, "rev-parse", "HEAD")
    (repo / "probe-runs").mkdir()
    (repo / "probe-runs" / "out.json").write_text("{}", encoding="utf-8")
    (repo / "untracked.txt").write_text("u", encoding="utf-8")
    record = head_check.measured_head(repo, sha[:10])
    assert record == {"ok": True, "expected": sha[:10], "head": sha}


def test_a_different_head_is_refused(repo: Path) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "two")
    with pytest.raises(SystemExit) as stop:
        head_check.measured_head(repo, first)
    assert first[:12] in str(stop.value.code)


def test_a_modified_tracked_file_is_refused(repo: Path) -> None:
    sha = _git(repo, "rev-parse", "HEAD")
    (repo / "code.py").write_text("x = 3\n", encoding="utf-8")
    with pytest.raises(SystemExit) as stop:
        head_check.measured_head(repo, sha)
    assert "code.py" in str(stop.value.code)


def test_an_unknown_commit_is_refused(repo: Path) -> None:
    with pytest.raises(SystemExit):
        head_check.measured_head(repo, "deadbeef" * 5)


def test_the_entry_point_records_the_check_in_the_status_file(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(head_check, "REPO", repo)
    sha = _git(repo, "rev-parse", "HEAD")
    status_dir = tmp_path / "status"
    assert main(["--run", str(tmp_path), "--status-dir", str(status_dir), "--expect-head", sha, "ledger"]) == 0
    status = json.loads((status_dir / "status.json").read_text(encoding="utf-8"))
    assert status["headCheck"] == {"ok": True, "expected": sha, "head": sha}

    (repo / "code.py").write_text("x = 4\n", encoding="utf-8")
    assert main(["--run", str(tmp_path), "--status-dir", str(status_dir), "--expect-head", sha, "ledger"]) == 2
    status = json.loads((status_dir / "status.json").read_text(encoding="utf-8"))
    assert status["headCheck"]["ok"] is False and status["exitCode"] == 2
    assert (status_dir / "done.2").exists()


def test_the_expected_commit_can_come_from_the_environment(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(head_check, "REPO", repo)
    monkeypatch.setenv(head_check.EXPECT_HEAD_ENV, "deadbeef" * 5)
    assert main(["--run", str(tmp_path), "ledger"]) == 2


def test_the_run_template_pins_the_measured_commit() -> None:
    template = (Path(head_check.__file__).parent / "run_template.sh").read_text(encoding="utf-8")
    assert '--expect-head "$MEASURE_COMMIT"' in template
    assert "MEASURE_COMMIT:?" in template
