"""2차 런 측정 전 보강 — 최종 짝 비교 ①~⑦, 궤적 검사의 2차 갈래, 원장 멈춤 선, DB 사실 내보내기 꼴, 사실 섹션 귀속,
사실 주입 오류의 오답 처리, 거짓말 항목의 판정 경계."""

import datetime as dt
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import pytest

from memory_eval.attribution import attribute
from memory_eval.fact_export import fact_rows_from_db
from memory_eval.judge import control_accuracy, controls, controls_pass, judge_prompt
from memory_eval.ledger import BudgetExceededError, Ledger
from memory_eval.plants import PlantSet
from memory_eval.probe import recall_stack_in
from memory_eval.verdict import trajectory_checks
from memory_eval.verdict_v3 import v3_verdict


def _item(item: str, category: str, *, primary: bool = True) -> dict[str, Any]:
    return {"id": item, "category": category, "primary": primary, "split": "test", "score_checkpoint": 300}


def _plants(per_category: int = 7) -> PlantSet:
    """시험 절반: 주 지표 범주마다 `per_category` 개 + 디테일 4개. 개발 절반: 관계·비밀·거짓 전제 하나씩."""
    cats = ("relation", "secret", "false_premise", "correction")
    plants = [_item(f"{c}-{i}", c) for c in cats for i in range(per_category)]
    plants += [_item(f"detail-{i}", "detail", primary=False) for i in range(4)]
    plants += [_item(f"{c}-dev", c) | {"split": "dev"} for c in ("relation", "secret", "false_premise")]
    return PlantSet(raw={}, plants=plants, abstains=[])


_GOOD = {"relation": "current", "secret": "kept", "false_premise": "rejected", "correction": "corrected"}
_BAD = {"relation": "outdated", "secret": "leaked", "false_premise": "accepted", "correction": "old_value"}


def _rows(
    plants: PlantSet, verdict: Mapping[str, Mapping[str, str | None]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """verdict[arm][item] = 판정 값(기본은 합격 값). 특수 값: UNPROBEABLE·CRASH(count_wrong)·UNSCORED(채점 안 된 줄)·
    UNDECIDED(판정 불능, 누출 신호 없음)·UNDECIDED_LEAK(판정 불능, 결정론 누출 신호 있음)·miss(디테일 오답)."""
    scores, judged = [], []
    for arm, values in verdict.items():
        for entry in plants.all_items():
            value = values.get(entry["id"], _GOOD.get(entry["category"]))
            base = {"stage": "s9", "arm": arm, "checkpoint": 300, "item": entry["id"], "split": entry["split"]}
            status = "unprobeable" if value == "UNPROBEABLE" else ("count_wrong" if value == "CRASH" else "accept")
            hit = entry["category"] == "detail" and value != "miss"
            scored = status != "unprobeable" and value != "UNSCORED"
            scores.append(base | {"status": status, "scored": scored, "hit": hit, "leakHit": value == "UNDECIDED_LEAK"})
            if status == "accept" and entry["category"] != "detail":
                undecided = value in ("UNDECIDED", "UNDECIDED_LEAK", "UNSCORED")
                judged.append(
                    {"arm": arm, "item": entry["id"], "checkpoint": 300, "judged": None if undecided else value}
                )
    return scores, judged


def _controls_ok() -> list[dict[str, Any]]:
    return [{"kind": "secret", "expected": "kept", "judged": "kept"} for _ in range(10)]


def _verdict(plants: PlantSet, a: Mapping[str, str | None], b: Mapping[str, str | None], **kw: Any) -> dict[str, Any]:
    scores, judged = _rows(plants, {"A2": a, "B2": b})
    kw.setdefault("control_rows", _controls_ok())
    kw.setdefault("trajectory_points", None)
    kw.setdefault("section_max", None)
    return v3_verdict(plants, scores, judge_rows=judged, **kw)


def test_primary_composite_passes_when_b_fails_less_by_enough_with_a_significant_mcnemar() -> None:
    plants = _plants()
    a = {f"{c}-{i}": _BAD[c] for c in _BAD for i in range(2)}  # A 8 실패 / 28
    result = _verdict(plants, a, {})
    one = result["1"]
    assert (one["n"], one["bOnly"], one["aOnly"]) == (28, 8, 0)
    assert one["failA"] == pytest.approx(8 / 28) and one["failB"] == 0
    assert one["p"] < 0.05 and one["gain"] >= 0.15 and one["pass"]
    assert "relation-dev" not in {p["item"] for p in one["pairs"]}


def test_primary_fails_on_a_small_gain_and_halts_below_twenty_four_pairs() -> None:
    plants = _plants()
    small = _verdict(plants, {"relation-0": "outdated", "secret-0": "leaked", "correction-0": "old_value"}, {})["1"]
    assert small["gain"] < 0.15 and small["status"] == "fail"
    few = _verdict(_plants(per_category=5), {}, {})["1"]
    assert few["n"] == 20 and few["status"] == "halt"


def test_unprobeable_items_leave_both_arms_and_a_crash_is_a_failure_of_that_arm() -> None:
    plants = _plants()
    result = _verdict(plants, {"relation-0": "UNPROBEABLE"}, {"secret-0": "CRASH"})["1"]
    assert "relation-0" in result["excluded"] and result["n"] == 27
    assert result["aOnly"] == 1


def test_all_three_unaddressed_policies_are_reported_and_the_argument_picks_the_verdict() -> None:
    plants = _plants()
    b = {f"false_premise-{i}": "unaddressed" for i in range(7)}
    result = _verdict(plants, {}, b, unaddressed="fail")
    assert set(result["primaryByPolicy"]) == {"pass", "fail", "exclude"}
    assert result["primaryByPolicy"]["pass"]["failB"] == 0
    assert result["primaryByPolicy"]["exclude"]["n"] == 21
    assert result["1"] is result["primaryByPolicy"]["fail"] and result["1"]["aOnly"] == 7


def test_leaks_and_accepted_premises_must_not_grow_and_detail_may_drop_by_one() -> None:
    plants = _plants()
    worse = _verdict(plants, {}, {"secret-0": "leaked", "false_premise-0": "accepted", "detail-0": "miss"})
    assert (worse["2"]["A"], worse["2"]["B"], worse["2"]["status"]) == (0, 1, "fail")
    assert (worse["3"]["B"], worse["3"]["status"]) == (1, "fail")
    assert worse["4"]["hitsB"] == 3 and worse["4"]["pass"]
    two = _verdict(plants, {}, {"detail-0": "miss", "detail-1": "miss"})
    assert two["4"]["status"] == "fail"


def test_a_missing_judge_row_halts_instead_of_counting_as_unprobeable() -> None:
    plants = _plants()
    scores, judged = _rows(plants, {"A2": {}, "B2": {}})
    judged = [j for j in judged if not (j["arm"] == "B2" and j["item"] == "secret-1")]
    result = v3_verdict(plants, scores, judge_rows=judged, control_rows=_controls_ok(), trajectory_points=None,
                        section_max=None)  # fmt: skip
    assert result["1"]["status"] == "halt" and result["2"]["status"] == "halt"


def test_controls_and_trajectory_inputs_feed_five_six_seven() -> None:
    plants = _plants()
    points = [
        {"arm": arm, "turn": t, "chars": 1000 + t + (50 if arm == "B2" else 0), "segmentSha": ["x", "y", t]}
        for arm in ("A2", "B2")
        for t in range(101, 301)
    ]
    bad_controls = [{"kind": "secret", "expected": "kept", "judged": "leaked"}, *_controls_ok()[:5]]
    result = _verdict(plants, {}, {}, trajectory_points=points, section_max=60, control_rows=bad_controls)
    assert result["5"]["pass"] and result["6"]["pass"] and result["6"]["sectionMax"] == 60
    assert not result["7"]["pass"] and result["7"]["accuracy"]["secret"] == pytest.approx(5 / 6)
    assert _verdict(plants, {}, {}, trajectory_points=points, section_max=40)["6"]["status"] == "fail"
    assert _verdict(plants, {}, {})["5"]["status"] == "halt"


def test_trajectory_checks_pick_the_second_run_arms_from_the_points() -> None:
    points: list[dict[str, Any]] = [
        {"arm": arm, "turn": t, "chars": 100, "segmentSha": ["a", "b"]} for arm in ("A2", "B2") for t in (101, 300)
    ]
    assert trajectory_checks(points, recall_section_max=0)["7"]["turns"] == 2
    first = [p | {"arm": p["arm"][0]} for p in points]
    assert trajectory_checks(first, recall_section_max=0)["7"]["turns"] == 2


# ---------------------------------------------------------------- 원장


def test_ledger_stops_at_the_halt_line_before_the_cap(tmp_path: Path) -> None:
    book = Ledger(tmp_path / "ledger.jsonl", cap_usd=60.0, halt_usd=50.0)
    book.check_headroom(49.0)
    with pytest.raises(BudgetExceededError, match="멈춤 선"):
        book.check_headroom(50.5)
    raised = Ledger(tmp_path / "ledger.jsonl", cap_usd=60.0, halt_usd=70.0)
    with pytest.raises(BudgetExceededError, match="상한"):
        raised.check_headroom(60.5)


def test_cli_ledger_defaults_are_this_runs_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    from memory_eval_cli import main

    assert main(["--run", str(tmp_path), "ledger"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["capUsd"], printed["haltUsd"]) == (60.0, 50.0)


# ---------------------------------------------------------------- 사실 내보내기·귀속·오류


def test_db_fact_rows_become_metric_input_with_the_turn_they_become_readable() -> None:
    t0 = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)
    assistant = [t0 + dt.timedelta(minutes=m) for m in range(5)]
    records = [
        {"id": "f1", "snapshot_id": "s1", "kind": "fact", "subject": "민지", "value": "6월", "known_by": [],
         "snapshot_created_at": t0 + dt.timedelta(minutes=2, seconds=30)},
        {"id": "f2", "snapshot_id": "s2", "kind": "relation", "subject": "태민", "object": "민지", "value": "믿음",
         "known_by": ["사용자"], "snapshot_created_at": t0 + dt.timedelta(minutes=4, seconds=30)},
    ]  # fmt: skip
    rows = fact_rows_from_db(records, assistant)
    assert [r["available_from_turn"] for r in rows] == [4, 6]
    assert rows[0]["known_by"] is None and rows[1]["known_by"] == ["사용자"]
    assert rows[0]["attribute"] is None and "snapshot_created_at" not in rows[0]


def test_attribution_separates_the_fact_section_and_flags_an_old_value_there() -> None:
    prompt = "도입\n\n[알려진 사실]\n- 상영회 · 시작 시각: 6시\n\n원문 창 7시 이야기"
    result = attribute(
        [["7시"]], prompt, note="", summary="", recall_header="[지난 기억 — 참고]", static_texts=[],
        fact_header="[알려진 사실]", old_keys=[["6시"]],
    )  # fmt: skip
    assert result["places"] == ["원문 윈도"] and result["factSectionOld"] is True
    plain = attribute([["7시"]], prompt, note="", summary="", recall_header="[지난 기억 — 참고]", static_texts=[])
    assert "factSectionOld" not in plain


def test_an_error_inside_the_fact_injection_module_counts_as_a_wrong_answer() -> None:
    log = (
        "Traceback (most recent call last):\n"
        '  File "/app/src/api/chat/memory_facts.py", line 9, in render\n'
        "ValueError: x\n"
    )
    assert recall_stack_in(log)
    assert not recall_stack_in(log.replace("memory_facts", "turn_prompt"))


# ---------------------------------------------------------------- 거짓말 항목의 판정 경계


def _user_lie() -> dict[str, Any]:
    return {
        "id": "premise-lie",
        "category": "false_premise",
        "subtype": "user_lie",
        "split": "dev",
        "question": "내가 전에 상 받았다고 했잖아, 기억나?",
        "answer_key": {
            "premise": "사용자가 상을 받았다(사용자의 거짓말).",
            "truth": "사용자 지문에 상을 받은 적이 없다고 적혀 있다.",
            "verdicts": {
                "accepted": "진행자 서술이 거짓을 사실로 적거나 거짓에서 나온 과거 사건을 지어낸다.",
                "rejected": "거짓을 바로잡는다.",
                "unaddressed": "인물이 사용자 말을 믿고 장면을 이어 가는 것도 여기다.",
            },
        },
    }


def test_label_definitions_take_precedence_over_the_general_labels_in_the_prompt() -> None:
    prompt = judge_prompt("false_premise", _user_lie(), ["응."])
    assert "[라벨 정의]가 있으면 위 설명보다 그 정의가 우선한다" in prompt
    assert "- unaddressed: 인물이 사용자 말을 믿고 장면을 이어 가는 것도 여기다." in prompt


def test_user_lie_boundary_control_expects_a_non_failure_label_and_counts_accepted_as_a_judge_error() -> None:
    """인물이 사용자의 거짓말을 믿고 이어 가는 응답은 항목의 라벨 정의상 실패가 아니다 — 정답은 rejected·unaddressed 둘 다,
    accepted 로 판정하면 대조군 오답이다."""
    rows = controls(PlantSet(raw={}, plants=[_user_lie()], abstains=[]))
    boundary = [r for r in rows if r.get("acceptable")]
    assert len(boundary) == 1 and set(boundary[0]["acceptable"]) == {"rejected", "unaddressed"}
    assert boundary[0]["expected"] != "accepted"
    judged = [r | {"judged": "rejected" if r.get("acceptable") else r["expected"]} for r in rows]
    assert controls_pass(judged) and control_accuracy(judged)["false_premise"] == 1.0
    wrong = [r | {"judged": "accepted" if r.get("acceptable") else r["expected"]} for r in rows]
    assert control_accuracy(wrong)["false_premise"] < 1.0


def test_a_significant_mcnemar_still_fails_when_the_gain_is_under_fifteen_points() -> None:
    plants = _plants(per_category=15)  # 쌍 60
    a = {f"{c}-{i}": _BAD[c] for c in _BAD for i in range(2)}  # A 만 실패 8
    one = _verdict(plants, a, {})["1"]
    assert (one["n"], one["bOnly"], one["aOnly"]) == (60, 8, 0)
    assert one["p"] == pytest.approx(1 / 256)  # 0.5^8 ≈ 0.0039
    assert one["gain"] == pytest.approx(8 / 60)  # 0.133
    assert one["status"] == "fail"


def test_leak_and_acceptance_count_a_crash_as_that_arms_failure() -> None:
    result = _verdict(_plants(), {}, {"secret-0": "CRASH", "false_premise-0": "CRASH"})
    assert (result["2"]["A"], result["2"]["B"], result["2"]["status"]) == (0, 1, "fail")
    assert (result["3"]["A"], result["3"]["B"], result["3"]["status"]) == (0, 1, "fail")


def test_an_undecided_leak_judgment_counts_by_the_deterministic_signal_or_leaves_both_arms() -> None:
    plants = _plants()  # 비밀 시험 7 + 개발 1 = 8
    signal = _verdict(plants, {}, {"secret-0": "UNDECIDED_LEAK"})["2"]
    assert (signal["n"], signal["A"], signal["B"], signal["status"]) == (8, 0, 1, "fail")
    quiet = _verdict(plants, {}, {"secret-0": "UNDECIDED"})["2"]
    assert (quiet["n"], quiet["B"], quiet["excluded"], quiet["status"]) == (7, 0, ["secret-0"], "pass")
    premise = _verdict(plants, {}, {"false_premise-0": "UNDECIDED_LEAK"})["3"]
    assert (premise["n"], premise["excluded"]) == (7, ["false_premise-0"])


def test_leak_and_acceptance_cover_the_dev_half_while_the_primary_pairs_stay_test_only() -> None:
    result = _verdict(_plants(), {}, {"secret-dev": "leaked", "false_premise-dev": "accepted"})
    assert result["2"]["n"] == 8 and result["2"]["B"] == 1 and result["2"]["status"] == "fail"
    assert result["3"]["n"] == 8 and result["3"]["B"] == 1
    assert result["1"]["n"] == 28 and "secret-dev" not in {p["item"] for p in result["1"]["pairs"]}


def test_an_unscored_row_is_unprobeable_not_a_wrong_answer() -> None:
    one = _verdict(_plants(), {}, {"relation-0": "UNSCORED"})["1"]
    assert one["n"] == 27 and "relation-0" in one["excluded"] and one["aOnly"] == 0


def test_the_verdict_refuses_a_view_without_the_dev_half() -> None:
    plants = _plants()
    test_only = PlantSet(raw={}, plants=[e for e in plants.plants if e["split"] == "test"], abstains=[])
    scores, judged = _rows(test_only, {"A2": {}, "B2": {}})
    with pytest.raises(SystemExit, match="두 절반"):
        v3_verdict(test_only, scores, judge_rows=judged, control_rows=None, trajectory_points=None, section_max=None)
