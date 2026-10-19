"""측정 하네스 CLI 진입점 — 묶음 등록·데이터 폴더·상태 파일·원장 요약."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from memory_eval_cli import build_parser, main

API_DIR = Path(__file__).resolve().parents[1]


def test_infra_commands_load_without_any_judgment_module() -> None:
    # 판정 묶음이 없는 PR 에서도 진입점이 돌아야 한다 — 한 묶음이 다른 묶음 모듈을 import 하면 여기서 드러난다.
    code = (
        "import sys, memory_eval_cli; "
        "bad = sorted(m for m in sys.modules if m.split('.')[-1].startswith(('judge', 'verdict', 'wording', 'objective')));"
        "print(bad)"
    )
    env = {**os.environ, "PYTHONPATH": str(API_DIR / "scripts")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=API_DIR, check=True)
    assert out.stdout.strip() == "[]"


def test_global_arguments_go_before_the_subcommand(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--run", str(tmp_path), "--data-dir", str(tmp_path), "ledger"])
    assert args.command == "ledger" and args.data_dir == tmp_path
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--run", str(tmp_path), "ledger", "--data-dir", str(tmp_path)])


def test_reading_measurement_data_without_data_dir_stops_with_a_clear_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--run", str(tmp_path), "media-book"]) == 2
    assert "--data-dir" in capsys.readouterr().err


def test_data_dir_without_the_file_names_the_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--run", str(tmp_path), "--data-dir", str(tmp_path), "media-book"]) == 2
    assert "media_book_filmclub.json" in capsys.readouterr().err


def test_status_dir_gets_a_status_file_and_a_done_marker_with_the_exit_code(tmp_path: Path) -> None:
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    (status_dir / "done.2").write_text("앞 실행의 표지\n", encoding="utf-8")
    assert main(["--run", str(tmp_path), "--status-dir", str(status_dir), "ledger"]) == 0
    status = json.loads((status_dir / "status.json").read_text(encoding="utf-8"))
    assert status["command"] == "ledger" and status["state"] == "done" and status["exitCode"] == 0
    assert sorted(p.name for p in status_dir.glob("done.*")) == ["done.0"]


def test_status_dir_marks_a_refused_command_with_its_exit_code(tmp_path: Path) -> None:
    status_dir = tmp_path / "status"
    assert main(["--run", str(tmp_path), "--status-dir", str(status_dir), "media-book"]) == 2
    assert (status_dir / "done.2").exists()
    assert json.loads((status_dir / "status.json").read_text(encoding="utf-8"))["exitCode"] == 2


def test_ledger_summary_counts_hand_written_rows_without_a_stage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [{"cost_usd": 1.5, "note": "하네스 전 손으로 남긴 줄"}, {"stage": "probe", "costUsd": 0.25, "bundle": "b"}]
    (tmp_path / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert main(["--run", str(tmp_path), "ledger"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["byStage"] == {"(단계 없음)": 1.5, "probe": 0.25}
    assert out["totalUsd"] == pytest.approx(1.75)
