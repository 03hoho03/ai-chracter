"""질문 꼴별 응답 회피 집계 — 거짓 전제 판정 줄을 심기 표의 질문 꼴 칸으로 묶어 꼴마다 표본 수·판정 불능·회피(unaddressed)
수와 비율을 낸다. 꼴 칸이 없는 항목은 기본 꼴로 센다. 판정 줄의 문항이 어느 심기 표에도 없으면 엉뚱한 표를 준 것이라
거부한다. 값은 모두 지어낸 것이다."""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_eval import judge as judge_mod
from memory_eval.b1 import plants_tool


def _row(item: str, judged: str | None, kind: str = "false_premise") -> dict[str, Any]:
    return {"item": item, "kind": kind, "judged": judged, "arm": "A0", "checkpoint": 300}


FORMS = {"f1": "premise_followup", "f2": "premise_followup", "c1": "closed_confirm", "p1": "plain", "s1": "plain"}


def test_unaddressed_is_counted_per_ask_form_over_decided_rows() -> None:
    rows = [_row("f1", "unaddressed"), _row("f2", "rejected"), _row("f1", None)]
    rows += [_row("c1", "accepted"), _row("c1", "unaddressed"), _row("p1", "unaddressed")]
    rows += [_row("s1", "leaked", kind="secret")]
    out = judge_mod.unaddressed_by_ask_form(rows, FORMS)
    assert out == {
        "closed_confirm": {"n": 2, "undecided": 0, "unaddressed": 1, "rate": 0.5},
        "plain": {"n": 1, "undecided": 0, "unaddressed": 1, "rate": 1.0},
        "premise_followup": {"n": 3, "undecided": 1, "unaddressed": 1, "rate": 0.5},
    }


def test_a_judged_item_missing_from_every_plants_table_is_refused() -> None:
    with pytest.raises(SystemExit, match="심기 표"):
        judge_mod.unaddressed_by_ask_form([_row("zz", "rejected")], FORMS)


def test_the_form_summary_command_reads_the_forms_from_the_plants_tables_and_prints_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    plants = {
        "plants": [
            {"id": "f1", "category": "false_premise", "askForm": "premise_followup", "question": "지어낸 질문 하나"},
            {"id": "c1", "category": "false_premise", "askForm": "closed_confirm", "question": "지어낸 질문 둘"},
            {"id": "p1", "category": "false_premise", "question": "지어낸 질문 셋"},
        ],
        "abstains": [],
    }
    plants_path = tmp_path / "plants.json"
    plants_path.write_text(json.dumps(plants, ensure_ascii=False), encoding="utf-8")
    judged = tmp_path / "judged.json"
    judged.write_text(
        json.dumps([_row("f1", "unaddressed"), _row("c1", "rejected"), _row("p1", "unaddressed")]), encoding="utf-8"
    )
    argv = ["--run", str(tmp_path), "judge-form-summary", "--judged", str(judged), "--plants", str(plants_path)]
    assert main(argv) == 0
    out = capsys.readouterr().out
    printed = json.loads(out)
    assert printed["falsePremiseByAskForm"]["premise_followup"]["rate"] == 1.0
    assert printed["falsePremiseByAskForm"]["closed_confirm"]["rate"] == 0.0
    assert printed["falsePremiseByAskForm"][plants_tool.DEFAULT_ASK_FORM]["unaddressed"] == 1
    assert "지어낸 질문" not in out
