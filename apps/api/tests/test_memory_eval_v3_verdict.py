"""2차 런 측정 전 보강 — 최종 짝 비교 결과 칸 1~7, 궤적 검사의 2차 갈래, 원장 멈춤 선, DB 사실 내보내기 꼴, 사실 섹션 귀속,
사실 주입 오류의 오답 처리, 거짓말 항목의 판정 경계."""

import datetime as dt
import json
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
from memory_eval_fakes import fake_wording


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
    assert result["7"]["binaryAccuracy"] == {"secret": pytest.approx(5 / 6)}
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


def test_ledger_rows_carry_their_bundle_and_the_halt_counts_only_that_bundle(tmp_path: Path) -> None:
    """승인은 묶음마다 받는다 — 앞 묶음의 지출이 이번 묶음의 멈춤 선을 먼저 채우면 안 된다(손으로 남긴 옛 줄도 같다)."""
    path = tmp_path / "ledger.jsonl"
    earlier = {"stage": "old", "callSite": "x", "costUsd": 40.0, "bundle": "earlier"}
    path.write_text(
        json.dumps(earlier) + "\n" + json.dumps({"stage": "hand", "cost_usd": 5.0}) + "\n", encoding="utf-8"
    )
    book = Ledger(path, cap_usd=10.0, halt_usd=8.0, bundle="next")
    assert book.total_usd() == pytest.approx(45.0)
    assert book.bundle_usd() == 0.0
    book.check_headroom(7.9)
    row = book.append(
        stage="s", call_site="x", model="claude-haiku-5-5", input_tokens=1_000_000, cached_tokens=0,
        cache_write_tokens=0, output_tokens=0, thoughts_tokens=0,
    )  # fmt: skip
    assert row["bundle"] == "next"
    assert row["bundleCumulativeUsd"] == pytest.approx(0.10)
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["bundle"] == "next"
    with pytest.raises(BudgetExceededError, match="멈춤 선"):
        book.check_headroom(7.95)


def test_paid_runs_refuse_to_start_unless_cap_halt_and_bundle_are_all_given(tmp_path: Path) -> None:
    """기본값이 있으면 상한을 올려 주고 멈춤 선을 잊은 실행이 옛 멈춤 선에서 조용히 먼저 멈춘다 — 셋 다 명시해야 돈다."""
    from memory_eval.cli_common import _ledger
    from memory_eval_cli import build_parser

    run = ["--run", str(tmp_path)]
    paid = ["judge", "--plants", str(tmp_path / "plants.json"), "--allow-paid"]
    given = {"--cap-usd": "60", "--halt-usd": "50", "--bundle": "next"}
    for left_out in given:
        flags = [x for k, v in given.items() if k != left_out for x in (k, v)]
        with pytest.raises(SystemExit, match="명시"):
            _ledger(build_parser().parse_args([*run, *flags, *paid]))
    book = _ledger(build_parser().parse_args([*run, *[x for kv in given.items() for x in kv], *paid]))
    assert (book.cap_usd, book.halt_usd, book.bundle) == (60.0, 50.0, "next")
    # 돈을 쓰지 않는 실행(드라이런)은 원장을 읽기만 하므로 셋 없이도 된다.
    dry = _ledger(build_parser().parse_args([*run, "judge", "--plants", str(tmp_path / "plants.json"), "--dry-run"]))
    assert dry.total_usd() == 0.0


def test_cli_ledger_has_no_default_cap_or_halt_and_reports_what_was_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    assert main(["--run", str(tmp_path), "ledger"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["capUsd"], printed["haltUsd"], printed["bundle"]) == (None, None, None)
    assert main(["--run", str(tmp_path), "--cap-usd", "80", "--halt-usd", "70", "--bundle", "next", "ledger"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["capUsd"], printed["haltUsd"], printed["bundle"]) == (80.0, 70.0, "next")


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
        '  File "/app/src/api/chat/memory_fact_section.py", line 9, in render\n'
        "ValueError: x\n"
    )
    assert recall_stack_in(log)
    assert not recall_stack_in(log.replace("memory_fact_section", "turn_prompt"))


def _frame_log(path: str, function: str) -> str:
    return f'Traceback (most recent call last):\n  File "{path}", line 9, in {function}\nValueError: x\n'


def test_injection_frames_are_the_five_production_places_by_exact_module_and_function() -> None:
    """프롬프트에 기억을 싣는 운영 자리 다섯 — 장면 회상·사실 섹션·지식 범위 필터·임베딩 회상 모듈 안 어디든, 그리고 생성 프롬프트
    조립 함수. 이름이 바뀌면 판정이 조용히 0 이 되므로 실제 모듈·함수가 있는지도 본다."""
    import importlib

    from memory_eval.probe import INJECTION_MODULES

    assert INJECTION_MODULES == {
        "api.chat.memory_recall": None,
        "api.chat.memory_fact_section": None,
        "api.chat.memory_knowledge": None,
        "api.chat.memory_vector": None,
        "api.chat.turn_prompt": "build_room_prompt",
    }
    for module, function in INJECTION_MODULES.items():
        loaded = importlib.import_module(module)
        assert function is None or callable(getattr(loaded, function)), module
    for name in ("memory_recall", "memory_fact_section", "memory_knowledge", "memory_vector"):
        assert recall_stack_in(_frame_log(f"/app/src/api/chat/{name}.py", "anything")), name
    assert recall_stack_in(_frame_log("/app/src/api/chat/turn_prompt.py", "build_room_prompt"))


def test_frames_that_only_look_like_injection_modules_do_not_count() -> None:
    for path, function in (
        ("/app/src/api/chat/turn_prompt.py", "system_instruction_for"),  # 조립 모듈의 다른 함수
        ("/app/src/api/chat/memory_facts.py", "extract_pending_facts"),  # 백그라운드 사실 추출
        ("/app/src/api/chat/memory_embeddings.py", "fill_embeddings"),  # 백그라운드 임베딩 채우기
        ("/app/src/api/chat/memory_recall_old.py", "score"),
        ("/app/tests/test_chat_memory_recall.py", "test_score"),
        ("/app/scripts/memory_eval/memory_vector.py", "nearest"),
    ):
        assert not recall_stack_in(_frame_log(path, function)), path


# ---------------------------------------------------------------- 거짓말 항목의 판정 경계


def _user_lie() -> dict[str, Any]:
    return {
        "id": "premise-lie",
        "category": "false_premise",
        "subtype": "user_lie",
        "split": "dev",
        "question": "지어낸 질문: 내가 전에 등대를 칠했다고 했지?",
        "answer_key": {
            "premise": "지어낸 전제: 사용자가 등대를 칠했다.",
            "truth": "지어낸 진실: 사용자 지문에는 등대 근처에도 안 갔다고 적혔다.",
            "verdicts": {
                "accepted": "지어낸 받아들임 정의.",
                "rejected": "지어낸 부정 정의.",
                "unaddressed": "지어낸 미결 정의.",
            },
        },
    }


def test_label_definitions_follow_the_general_instruction_in_the_prompt(tmp_path: Path) -> None:
    wording = fake_wording(tmp_path)
    prompt = judge_prompt("false_premise", _user_lie(), ["응."], wording)
    assert prompt.index(wording.instructions["false_premise"]) < prompt.index("[라벨 정의]")
    assert "- unaddressed: 지어낸 미결 정의." in prompt


def test_user_lie_boundary_control_expects_only_unaddressed_when_the_character_just_believes_the_lie(
    tmp_path: Path,
) -> None:
    """인물이 사용자의 거짓말을 믿고 이어 가기만 하면 전제를 굳힌 것도 부정한 것도 아니다 — 정답은 unaddressed 하나이고,
    accepted 로도 rejected 로도 판정하면 대조군 오답이다."""
    wording = fake_wording(tmp_path)
    rows = controls(PlantSet(raw={}, plants=[_user_lie()], abstains=[]), wording)
    boundary = [r for r in rows if r["reply"] == wording.false_premise_replies["userLieUnaddressed"]]
    assert len(boundary) == 1 and boundary[0]["expected"] == "unaddressed" and not boundary[0].get("acceptable")
    judged = [r | {"judged": r["expected"]} for r in rows]
    assert controls_pass(judged) and control_accuracy(judged)["false_premise"] == 1.0
    for wrong_label in ("accepted", "rejected"):
        wrong = [r | {"judged": wrong_label if r is boundary[0] else r["expected"]} for r in rows]
        assert control_accuracy(wrong)["false_premise"] < 1.0, wrong_label


def test_user_lie_accepted_control_is_narration_fixing_the_lie_not_a_character_echoing_it(tmp_path: Path) -> None:
    """사용자 거짓말 항목에서 인물이 맞장구만 치는 사본은 인물이 속는 연기와 가를 수 없다 — accepted 사본은 진행자 서술이
    거짓을 사실로 적는 고정 응답이어야 한다. 인물이 지어낸 말 항목은 맞장구 사본을 그대로 쓴다."""
    wording = fake_wording(tmp_path)
    narration = wording.false_premise_replies["userLieAccepted"]
    lie = [r for r in controls(PlantSet(raw={}, plants=[_user_lie()], abstains=[]), wording) if r["expected"] == "accepted"]
    assert len(lie) == 1 and lie[0]["reply"] == narration
    claim_entry = _user_lie() | {"id": "premise-claim", "subtype": "character_claim"}
    claim = [r for r in controls(PlantSet(raw={}, plants=[claim_entry], abstains=[]), wording) if r["expected"] == "accepted"]
    assert len(claim) == 1 and claim[0]["reply"] != narration


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
