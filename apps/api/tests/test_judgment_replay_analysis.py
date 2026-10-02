"""`scripts/judgment_replay/analysis.py` — 일치율·정확도·통과 기준 계산."""

from typing import Any

import pytest

from judgment_replay import analysis


def _rec(
    kind: str, input_id: str, config: str, rep: int, derived: Any, expected: Any, *, ok: bool = True
) -> dict[str, Any]:
    return {
        "kind": kind,
        "input_id": input_id,
        "config": config,
        "rep": rep,
        "ok": ok,
        "error_type": None if ok else "parse",
        "derived": derived if ok else None,
        "expected": expected,
        "model": "gemini-3.5-flash-lite" if config.startswith("3.5") else "gemini-3.1-flash-lite",
        "tokens": {"prompt": 100, "cached": 0, "candidates": 10, "thoughts": 0, "total": 110},
        "latency_ms": 100.0 * (rep + 1),
    }


def _ending_records() -> list[dict[str, Any]]:
    base = {"e1": [True, True, False], "e2": [False, False, False]}
    cand = {"e1": [True, True, True], "e2": [False, True, False]}
    expected = {"e1": True, "e2": False}
    records = []
    for config, table in (("3.5-default", base), ("3.1-off", cand)):
        for input_id, values in table.items():
            for rep, value in enumerate(values):
                records.append(_rec("ending", input_id, config, rep, {"triggered": value}, expected[input_id]))
    return records


def test_agreement_rates_are_pairwise_on_both_sides() -> None:
    report = analysis.analyze(_ending_records(), baseline="3.5-default", margin_pp=5.0)
    row = report.rows[("ending", "3.1-off")]
    # 현행끼리: e1 의 세 쌍 중 하나, e2 의 세 쌍 전부 → 4/6.
    assert report.self_agreement["ending"] == pytest.approx(4 / 6)
    # 후보 × 현행 모든 쌍: e1 6/9, e2 6/9.
    assert row.cross_agreement == pytest.approx(12 / 18)
    # 현행 다수결(e1=참, e2=거짓) 대비: e1 3/3, e2 2/3.
    assert row.majority_agreement == pytest.approx(5 / 6)
    assert report.rows[("ending", "3.5-default")].accuracy == pytest.approx(5 / 6)
    assert row.passes


def test_structured_failure_or_publish_label_mismatch_fails_the_gate() -> None:
    records = _ending_records()
    records.append(_rec("ending", "e3", "3.1-off", 0, None, True, ok=False))
    records += [
        _rec("publish", "p1", "3.5-default", 0, {"passed": False, "reason": "x"}, False),
        _rec("publish", "p1", "3.1-off", 0, {"passed": True, "reason": None}, False),
    ]
    report = analysis.analyze(records, baseline="3.5-default", margin_pp=5.0)
    assert report.rows[("ending", "3.1-off")].structural_failures == 1
    assert not report.rows[("ending", "3.1-off")].passes
    assert report.rows[("publish", "3.1-off")].label_mismatches == 1
    assert not report.rows[("publish", "3.1-off")].passes
    assert report.rows[("publish", "3.5-default")].label_mismatches == 0


def test_stat_units_are_per_stat_directions() -> None:
    records = [
        _rec("stat", "s1", "3.5-default", rep, {"directions": {"a": "+", "b": "0"}}, {"a": "+", "b": "0"})
        for rep in range(2)
    ] + [_rec("stat", "s1", "3.1-off", 0, {"directions": {"a": "+", "b": "-"}}, {"a": "+", "b": "0"})]
    report = analysis.analyze(records, baseline="3.5-default", margin_pp=5.0)
    assert report.self_agreement["stat"] == pytest.approx(1.0)
    assert report.rows[("stat", "3.1-off")].cross_agreement == pytest.approx(0.5)
    assert report.rows[("stat", "3.1-off")].accuracy == pytest.approx(0.5)
    assert not report.rows[("stat", "3.1-off")].passes


def test_units_without_a_strict_baseline_majority_are_left_out_of_the_majority_rate() -> None:
    """현행 세 회차가 셋 다 다른 그림을 고르면 다수결이 없다 — 그 단위를 아무 값으로나 채우면 참고 일치율이 흔들린다."""
    records = (
        [
            _rec("image", "i1", "3.5-default", rep, {"matched": value, "out_of_candidates": False}, "A")
            for rep, value in enumerate(["A", "B", None])
        ]
        + [
            _rec("image", "i2", "3.5-default", rep, {"matched": "A", "out_of_candidates": False}, "A")
            for rep in range(3)
        ]
        + [
            _rec("image", input_id, "3.1-off", 0, {"matched": value, "out_of_candidates": False}, "A")
            for input_id, value in (("i1", "A"), ("i2", "B"))
        ]
    )
    report = analysis.analyze(records, baseline="3.5-default", margin_pp=5.0)
    # i1 은 다수결이 없어 빠지고(첫 표 A 로 채우면 후보 A 와 맞아 50% 가 된다), i2 만 남는다(후보 B ≠ 다수결 A).
    assert report.rows[("image", "3.1-off")].majority_agreement == pytest.approx(0.0)


def test_stat_gate_also_holds_on_units_expected_to_change() -> None:
    """정답 0 단위가 대부분이면 전체 일치율은 거의 안 떨어진다 — 변화 기대 단위에서 반이 틀려도 전체는 3%p 만 낮다."""
    zeros = {f"z{i}": "0" for i in range(30)}
    expected = {**zeros, "a": "+", "b": "-"}
    records = [_rec("stat", "s1", "3.5-default", rep, {"directions": expected}, expected) for rep in range(2)]
    records.append(_rec("stat", "s1", "3.1-off", 0, {"directions": {**zeros, "a": "+", "b": "0"}}, expected))
    row = analysis.analyze(records, baseline="3.5-default", margin_pp=5.0).rows[("stat", "3.1-off")]
    assert row.cross_agreement == pytest.approx(31 / 32)
    assert row.nontrivial_cross_agreement == pytest.approx(0.5)
    assert row.passes is False


def test_publish_gate_fails_when_calls_failed_instead_of_judging() -> None:
    records = [
        _rec("publish", "p1", "3.5-default", 0, {"passed": True, "reason": None}, True),
        {**_rec("publish", "p1", "3.1-off", 0, None, True, ok=False), "error_type": "rate_limit"},
    ]
    row = analysis.analyze(records, baseline="3.5-default", margin_pp=5.0).rows[("publish", "3.1-off")]
    assert row.label_mismatches == 0
    assert row.passes is False


def test_runs_split_across_files_keep_their_reps_apart() -> None:
    """회차는 실행마다 0 부터라, 실행 id 로 묶지 않으면 나눠 돌린 두 실행의 회차 0 이 서로 덮어써 쌍이 사라진다."""
    records = [
        {**_rec("ending", "e1", "3.5-default", 0, {"triggered": value}, True), "run_id": run_id}
        for run_id, value in (("a", True), ("b", False))
    ]
    report = analysis.analyze(records, baseline="3.5-default", margin_pp=5.0)
    assert report.self_agreement["ending"] == pytest.approx(0.0)
