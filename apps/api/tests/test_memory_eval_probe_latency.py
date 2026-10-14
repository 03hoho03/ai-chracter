"""프로브 결과의 첫 글자 지연 — 드라이버 기록의 `ttftMs` 를 턴마다 싣고, 갈래별 p50·p95 를 받아들인 프로브의 잰 턴으로만 낸다."""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_eval.probe import percentile, probe_summary


def _row(arm: str, status: str, *ttft: int | None) -> dict[str, Any]:
    return {"arm": arm, "status": status, "turns": [{"reply": "r", "ttftMs": t} for t in ttft]}


def test_nearest_rank_percentile() -> None:
    values = [float(v) for v in range(1, 21)]
    assert percentile(values, 50) == 10.0
    assert percentile(values, 95) == 19.0
    assert percentile([5.0, 1.0, 3.0], 50) == 3.0
    assert percentile([], 50) is None


def test_summary_counts_statuses_per_arm_and_only_measured_turns_of_accepted_probes() -> None:
    rows = [
        _row("A2", "accept", 100, 300),
        _row("A2", "accept", None),
        _row("A2", "unprobeable", 9_000),
        _row("B2", "accept", 200),
        _row("B2", "count_wrong", 50),
    ]
    summary = probe_summary(rows)
    assert summary["A2"]["status"] == {"accept": 2, "unprobeable": 1}
    assert summary["A2"]["ttftTurns"] == 2
    assert (summary["A2"]["ttftP50Ms"], summary["A2"]["ttftP95Ms"]) == (100.0, 300.0)
    assert summary["B2"]["ttftTurns"] == 1 and summary["B2"]["ttftP95Ms"] == 200.0


def test_latency_command_reads_probe_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from memory_eval_cli import main

    path = tmp_path / "s8-A2.jsonl"
    path.write_text(json.dumps(_row("A2", "accept", 120, 80)) + "\n", encoding="utf-8")
    assert main(["--run", str(tmp_path), "latency", "--probes", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["A2"]["ttftP50Ms"] == 80.0
