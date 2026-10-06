"""스탯 판정 형식 갈래 분석기가 사전에 정한 기준대로 분류·판정하는지 DB 없이 본다 — 옛 형식 비교 80호출에서 알려진 오독
수(현행 15/20·A 0/20·L 1/20·B 0/20)를 다시 내는지, 오독·규칙 위반·형식 이상의 경계, 합성 출력에서의 갈래 판정.

    uv run --env-file .env pytest scripts/experiments/filmclub_longturn/test_analyze_stat_misread.py
"""

import json
from pathlib import Path
from typing import Any

import pytest

from experiments.filmclub_longturn import analyze_stat_misread as an

API = Path(__file__).resolve().parents[3]
RUN = API / "probe-runs" / "stat-misread-2026-10-06"
# 형식 비교 80호출 원자료는 메인 체크아웃(워크트리 네 단계 위)의 probe-runs 에 있다.
OLD = API.parents[4] / "apps" / "api" / "probe-runs" / "filmclub-longturn-2026-10-05" / "replay"


def test_old_format_comparison_calls_reproduce_the_known_misread_counts() -> None:
    old = OLD
    if not (old / "stat-format-t013.jsonl").exists() or not (RUN / "inputs").exists():
        pytest.skip("옛 형식 비교 원자료나 닻 입력이 없다")
    specs = {}
    calls = []
    for turn in (13, 25):
        spec = an.input_from_json(
            json.loads((RUN / "inputs" / f"anchor-filmclub-6787bb78-t{turn:03d}.json").read_text(encoding="utf-8"))
        )
        specs[spec.input_id] = spec
        calls += an.load_calls(old / f"stat-format-t{turn:03d}.jsonl", spec)
    data = an.Data(specs=specs, calls=calls)
    an.check_counts(data, 10)
    got = {arm: an.g1(data, arm)["x"] for arm in an.TREATMENTS}
    assert an.g1(data, "L")["current"] == 15
    assert got == {"L": 1, "A": 0, "B": 0}


def _stat(
    sid: str,
    *,
    lo: float = 0,
    hi: float = 100,
    counter: bool = False,
    direction: str = "both",
    step: float | None = None,
) -> dict[str, Any]:
    return {
        "entity_id": sid,
        "name": sid,
        "min_value": lo,
        "max_value": hi,
        "per_turn_delta": -1 if counter else None,
        "change_direction": direction,
        "max_change_per_turn": step,
    }


def _spec(group: str, stats: list[dict[str, Any]], start: dict[str, float], input_id: str = "x") -> an.InputSpec:
    return an.input_from_json({"inputId": input_id, "group": group, "statDefs": stats, "statStart": start})


E_STATS = [_stat("d"), _stat("y"), _stat("s"), _stat("days", hi=42, direction="decrease", step=7)]
E_START = {"d": 24.5, "y": 24.5, "s": 52.5, "days": 40.0}


def _call(
    changes: list[tuple[str, float]],
    *,
    arm: str = "current",
    rep: int = 0,
    error: str | None = None,
    input_id: str = "x",
) -> an.Call:
    output = None if error else {"stat_changes": [{"stat_id": k, "new_value": v} for k, v in changes]}
    return an.Call(input_id=input_id, arm=arm, rep=rep, output=output, error=error)


def test_misread_needs_distance_eight_and_a_closer_same_kind_peer() -> None:
    spec = _spec("E1", E_STATS, E_START)
    assert an.misread_stats(_call([("s", 26.5)]), spec) == {"s"}  # 다른 호감 24.5 근처
    assert an.misread_stats(_call([("s", 55.5)]), spec) == set()  # 자기 +3
    # 자기에서 7 떨어진 45.5 는 다른 호감(24.5)보다 자기에 가깝다 — 거리 조건 전에 이미 아니다.
    assert an.misread_stats(_call([("s", 45.5)]), spec) == set()
    near = _spec("E1", E_STATS, {"d": 30.0, "y": 24.5, "s": 37.0, "days": 40.0})
    # 자기 37 에서 7 떨어진 30 은 도희 30 과 같지만 8 미만이라 오독이 아니고, 8 떨어진 29 는 오독이다.
    assert an.misread_stats(_call([("s", 30.0)]), near) == set()
    assert an.misread_stats(_call([("s", 29.0)]), near) == {"s"}
    # 범위가 다른 「days」는 호감의 비교 대상이 아니다 — 40 근처로 내도 오독이 아니라 폭 위반으로 잡힌다.
    assert an.misread_stats(_call([("s", 41.0)]), spec) == set()
    assert an.misread_stats(_call([("s", 26.5)]), _spec("N1", E_STATS, E_START)) == set()  # N 군엔 정의가 없다
    assert an.misread_stats(_call([("s", 52.5)]), spec) == set()  # 시작값과 같으면 요청이 아니다
    assert an.misread_stats(_call([("s", 38.5)]), spec) == set()  # 둘에서 똑같이 14 — 더 가깝지 않으면 오독이 아니다


def test_e_input_without_three_same_kind_stats_is_refused() -> None:
    with pytest.raises(ValueError, match="셋 이상"):
        _spec("E1", [_stat("d"), _stat("s"), _stat("c", counter=True)], {"d": 1, "s": 2, "c": 3})


def test_rule_violations_and_the_small_range_exemption() -> None:
    spec = _spec(
        "N1",
        [*E_STATS, _stat("tiny", hi=5), _stat("up", direction="increase"), _stat("st", step=3)],
        {**E_START, "tiny": 1.0, "up": 50.0, "st": 50.0},
    )
    stat = {s.stat_id: s for s in spec.stats}
    assert an.rule_violations(_call([("days", 41.0)]), spec, stat["days"]) == ["direction"]
    assert an.rule_violations(_call([("st", 54.0)]), spec, stat["st"]) == ["maxChange"]
    assert an.rule_violations(_call([("st", 53.0)]), spec, stat["st"]) == []
    # 범위 42 의 「days」에서 8 감소는 최대 폭 7 과 범위 15%(6.3)를 함께 넘는다 — 한 (호출, 스탯)으로 한 번 센다.
    assert an.rule_violations(_call([("days", 32.0)]), spec, stat["days"]) == ["maxChange", "over15"]
    assert an.rule_violations(_call([("s", 67.5)]), spec, stat["s"]) == []  # 정확히 15(범위의 15%)는 넘지 않는다
    assert an.rule_violations(_call([("s", 67.6)]), spec, stat["s"]) == ["over15"]
    assert an.rule_violations(_call([("tiny", 3.0)]), spec, stat["tiny"]) == []  # 범위 5: 1 이 이미 20% → 면제
    assert an.rule_violations(_call([("up", 49.0)]), spec, stat["up"]) == ["direction"]


def test_format_anomalies_cover_errors_parse_failures_unknown_ids_and_counters() -> None:
    spec = _spec(
        "E2", [_stat("c", lo=0, hi=20, counter=True), *E_STATS[:3]], {"d": 24.5, "y": 24.5, "s": 52.5, "c": 4.0}
    )
    parse = "LLMClientError: Gemini structured response could not be parsed into StatJudgmentResult"
    assert an.format_anomalies(_call([], error=parse), spec) == ["parseFailure"]
    assert an.format_anomalies(_call([], error="LLMClientError: timeout"), spec) == ["error"]
    assert an.format_anomalies(_call([("nope", 1.0)]), spec) == ["unknownStatId"]
    assert an.format_anomalies(_call([("c", 4.0)]), spec) == ["counterRequested"]  # 값이 같아도 넣은 것 자체
    assert an.format_anomalies(_call([("s", 55.5)]), spec) == []


def test_fisher_one_sided_matches_the_power_facts_written_before_the_run() -> None:
    assert an.fisher_one_sided_less(0, 60, 6, 60) == pytest.approx(0.0137, abs=1e-4)
    assert an.fisher_one_sided_less(1, 60, 6, 60) == pytest.approx(0.0570, abs=1e-4)
    assert an.fisher_one_sided_less(0, 20, 15, 20) == pytest.approx(3.85e-7, rel=1e-2)


def test_g2a_counts_a_cell_as_changed_only_when_the_modal_sign_sets_are_disjoint() -> None:
    assert an.modal_set(["+", "+", "0", "0", "-"]) == frozenset({"+", "0"})
    assert an.modal_set(["0", "0", "0", "+", "+"]) == frozenset({"0"})


# ── 합성 출력 전체 판정 ─────────────────────────────────────────────────────────


def synthetic_rows(inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """실제 입력 위의 합성 호출 줄. 현행 = E 의 s* 를 5회 중 2회 다른 호감 근처로(오독), 나머지 +3. N 은 양방향 판정
    스탯마다 3회 +2 · 2회 출력 없음. L = 오독 없음·N 은 현행과 같음(통과). A = 오독 없음·N 을 전부 −2(방향·요청률 변화 →
    실패). B = L 과 같되 형식 이상 3호출(파싱 실패·모르는 id·카운터) + E 의 오독 아닌 스탯 방향 위반 1건(G2e 로 실패)."""
    rows: list[dict[str, Any]] = []
    for data in inputs:
        defs = data["statDefs"]
        start = data["statStart"]
        both = [d for d in defs if d["per_turn_delta"] is None and d["change_direction"] == "both"]
        lead = next(d for d in defs if d["name"] == data["sStar"][0]["name"]) if data.get("sStar") else None
        counter = next((d for d in defs if d["per_turn_delta"] is not None), None)
        for arm in an.ARMS:
            for rep in range(5):
                changes: list[dict[str, Any]] = []
                error = None
                if lead is not None:
                    sid = lead["entity_id"]
                    peer = next(d for d in both if d is not lead and d["max_value"] == lead["max_value"])
                    misread = arm == "current" and rep < 2
                    value = start[peer["entity_id"]] + 2 if misread else start[sid] + 3
                    changes.append({"stat_id": sid, "new_value": value})
                    if arm == "B" and rep == 0 and data["inputId"].endswith("6787bb78-t046"):
                        # 감소만 가능한 「상영회까지」를 1 올림 — 같은 종류 짝이 없어 오독이 아니라 방향 위반이다.
                        days = next(d for d in defs if d["change_direction"] == "decrease")
                        changes.append({"stat_id": days["entity_id"], "new_value": start[days["entity_id"]] + 1})
                else:
                    for d in both:
                        if arm == "A":
                            changes.append({"stat_id": d["entity_id"], "new_value": start[d["entity_id"]] - 2})
                        elif rep < 3:
                            changes.append({"stat_id": d["entity_id"], "new_value": start[d["entity_id"]] + 2})
                if arm == "B" and data["inputId"].startswith("E2") and rep == 4:
                    if data["inputId"].endswith("040b4dda-t017"):
                        error = "LLMClientError: Gemini structured response could not be parsed into StatJudgmentResult"
                    elif data["inputId"].endswith("064bba4f-t013"):
                        changes.append({"stat_id": "00000000-0000-0000-0000-000000000000", "new_value": 1})
                    elif data["inputId"].endswith("18a927fe-t017") and counter is not None:
                        changes.append({"stat_id": counter["entity_id"], "new_value": start[counter["entity_id"]]})
                rows.append(
                    {
                        "kind": "call",
                        "inputId": data["inputId"],
                        "group": data["group"],
                        "judgment": "stat",
                        "statFormat": arm,
                        "rep": rep,
                        "sentModel": "gemini-3.1-flash-lite",
                        "tokens": {"prompt": 1800, "cached": None, "candidates": 80, "thoughts": None, "total": 1880},
                        "latencyMs": 1000.0,
                        "output": None if error else {"stat_changes": changes},
                        "error": error,
                    }
                )
    return rows


def _run_inputs() -> list[Path]:
    return sorted(p for p in (RUN / "inputs").glob("*.json") if p.name[:2] in ("E1", "E2", "N1", "N2"))


def test_synthetic_outputs_on_the_run_inputs_give_the_expected_verdicts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _run_inputs()
    if len(paths) != 20:
        pytest.skip("런 입력 20개가 없다")
    inputs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    replay = tmp_path / "synthetic.jsonl"
    replay.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in synthetic_rows(inputs)), encoding="utf-8"
    )
    out_json = tmp_path / "result.json"
    an.main(
        [
            "--inputs-dir",
            str(RUN / "inputs"),
            "--replay",
            str(replay),
            "--reps",
            "5",
            "--out",
            str(tmp_path / "result.out"),
            "--json",
            str(out_json),
        ]
    )
    results = json.loads(out_json.read_text(encoding="utf-8"))["results"]
    assert {arm: r["final"] for arm, r in results.items()} == {"L": "통과", "A": "실패", "B": "실패"}
    assert results["L"]["g1"]["current"] == 24 and results["L"]["g1"]["x"] == 0
    assert results["L"]["g2abc"]["cells"] == 24
    # 양방향 판정 스탯 칸만 바뀌었다(N1 「상영회까지」 2칸 제외).
    assert len(results["A"]["g2abc"]["g2a"]["changed"]) == 22
    assert results["B"]["g2e"] == {
        "x": 3,
        "current": 0,
        "kinds": {"parseFailure": 1, "unknownStatId": 1, "counterRequested": 1},
        "ok": False,
    }
    assert results["B"]["g2d"]["x"] == 1 and results["B"]["g2d"]["ok"]
    assert "L: 통과" in capsys.readouterr().out


def _g1_data(current_misreads: int) -> an.Data:
    spec = _spec("E1", E_STATS, E_START)
    n_spec = _spec("N2", [_stat("a"), _stat("b")], {"a": 10.0, "b": 20.0}, input_id="n")
    calls = []
    for arm in an.ARMS:
        for rep in range(10):
            mis = arm == "current" and rep < current_misreads
            calls.append(_call([("s", 26.5 if mis else 55.5)], arm=arm, rep=rep))
            calls.append(_call([("a", 12.0)], arm=arm, rep=rep, input_id="n"))
    data = an.Data(specs={"x": spec, "n": n_spec}, calls=calls)
    an.check_counts(data, 10)
    return data


def test_g1_is_non_informative_below_six_current_misreads_and_needs_user_judgment() -> None:
    result = an.verdict(_g1_data(5), "L")
    assert not result["g1"]["informative"] and result["g1"]["ok"]
    assert result["final"] == "비정보적 — 사용자 판단"
    # 현행 6건이면 검정이 정보를 준다 — 0 대 6/10 은 단측 p≈0.005 로 통과.
    result = an.verdict(_g1_data(6), "L")
    assert result["g1"]["informative"] and result["final"] == "통과"


def test_g1_fails_when_the_arm_has_more_than_one_extra_e_error_even_if_g2e_passes() -> None:
    # 현행이 카운터를 3번 넣으면 G2e 허용이 4 로 커진다. 그 틈에 X 의 E 군 오류 4호출은 G2e 를 통과하면서 G1 에서
    # 오독이 될 수 없는 호출로 세인다 — G1 이 E 군 오류를 따로 묶지 않으면 그만큼 감소가 공짜로 생긴다.
    spec = _spec(
        "E2", [_stat("c", lo=0, hi=20, counter=True), *E_STATS[:3]], {"d": 24.5, "y": 24.5, "s": 52.5, "c": 4.0}
    )
    n_spec = _spec("N2", [_stat("a"), _stat("b")], {"a": 10.0, "b": 20.0}, input_id="n")
    calls = []
    for arm in an.ARMS:
        for rep in range(10):
            if arm == "current":
                changes = [("s", 26.5 if rep < 8 else 55.5)] + ([("c", 4.0)] if rep < 3 else [])
                calls.append(_call(changes, arm=arm, rep=rep))
            elif rep < 4:
                calls.append(_call([], arm=arm, rep=rep, error="LLMClientError: timeout"))
            else:
                calls.append(_call([("s", 55.5)], arm=arm, rep=rep))
            calls.append(_call([("a", 12.0)], arm=arm, rep=rep, input_id="n"))
    data = an.Data(specs={"x": spec, "n": n_spec}, calls=calls)
    an.check_counts(data, 10)
    result = an.verdict(data, "L")
    assert result["g2e"]["ok"]  # 4 ≤ 3 + 1
    assert not result["g1"]["ok"] and result["final"] == "실패"
    assert result["g1"]["errorsX"] == 4 and result["g1"]["errorsCurrent"] == 0
