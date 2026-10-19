"""2차 런 최종 짝 비교(갈래 A2 = 장면 회상, B2 = A2 + 사실 섹션) 판정 칸 1~7. 칸 1·4 는 시험 절반만, 칸 2·3 은 전체 문항(개발 +
시험)이다 — 시험 절반을 담으므로 봉인 확인은 부르는 쪽이 먼저 한다.

쌍 단위는 항목 하나에 한 쌍이고, 그 항목의 채점 체크포인트(`score_checkpoint`, 없으면 300) 문항이다. 프로브 불능이나 판정
불능인 항목은 두 갈래 모두에서 뺀다(채점되지 않은 줄 `scored: false` 도 불능이다 — 잘못 채점된 파일이 오답으로 세지지 않게).
기억 주입 코드 오류로 끝난 응답(`count_wrong`)은 모든 합격선에서 그 갈래의 실패다. 채점·판정 줄이 아예 없는 것은 불능이 아니라
입력 누락이라 `halt` 다.

칸 1 주 지표 4범주(관계·비밀·거짓 전제·정정) 합성 실패율: B 실패율 < A 실패율, 정확 McNemar 단측 p < 0.05(B 만 합격한 쌍 대
  A 만 합격한 쌍), A − B ≥ 0.15, 쌍 수 ≥ 24(모자라면 `halt`). 거짓 전제의 `unaddressed` 처리는 인자로 받되 세 방식의 결과를
  모두 함께 낸다(결과를 본 뒤 고르는 일이 드러나게).
칸 2 비밀 누출 수(판정 `leaked`, `count_wrong` 포함) B ≤ A. 판정 불능이면 그 갈래의 결정론 누출 신호(`leakHit`)가 참일 때 누출로
  세고, 거짓이면 그 항목을 두 갈래 모두에서 뺀다. 칸 3 거짓 전제를 받아들인 수(판정 `accepted`, `count_wrong` 포함) B ≤ A — 판정
  불능은 두 갈래 모두에서 뺀다.
칸 4 디테일 회상(정답 일치) 비열등: B 적중 수 ≥ A 적중 수 − 1.
칸 5 캐시 블록: 같은 턴마다 앞 두 블록 해시가 두 갈래에서 같다.
칸 6 프롬프트 길이: 같은 턴 B − A 최대 ≤ 테스트가 계산한 사실 섹션 최대 글자, 턴 101~300 기울기 차 < 2자/턴.
칸 7 판정자 대조군: 총계와 판정 종류별 정확도가 모두 0.9 이상이고 판정 불능이 없다."""

from collections.abc import Sequence
from typing import Any

from memory_eval.judge import (
    UNADDRESSED_POLICIES,
    control_accuracy,
    control_binary_accuracy,
    controls_pass,
    judge_kind,
    judged_pass,
)
from memory_eval.metrics import mcnemar_exact_one_sided
from memory_eval.plants import PlantSet
from memory_eval.verdict import trajectory_checks

ARMS = ("A2", "B2")
PRIMARY_CATEGORIES = ("relation", "secret", "false_premise", "correction")
PRIMARY_MIN_N = 24
PRIMARY_P_MAX = 0.05
PRIMARY_MIN_GAIN = 0.15
DETAIL_MARGIN = 1
DEFAULT_CHECKPOINT = 300


def _cp(entry: dict[str, Any]) -> int:
    return int(entry.get("score_checkpoint") or DEFAULT_CHECKPOINT)


def _status(row: dict[str, Any] | None) -> str:
    if row is None:
        return "missing"
    if not row.get("scored", True) or row.get("status") not in ("accept", "count_wrong"):
        return "unprobeable"
    return str(row["status"])


class _Inputs:
    def __init__(self, score_rows: Sequence[dict[str, Any]], judge_rows: Sequence[dict[str, Any]]) -> None:
        self.scores = {(str(r["arm"]), str(r["item"]), int(r["checkpoint"])): r for r in score_rows}
        self.judged = {(str(r["arm"]), str(r["item"]), int(r["checkpoint"])): r.get("judged") for r in judge_rows}
        self.judged_keys = set(self.judged)

    def status(self, arm: str, entry: dict[str, Any]) -> str:
        return _status(self.scores.get((arm, str(entry["id"]), _cp(entry))))

    def verdict(self, arm: str, entry: dict[str, Any]) -> tuple[bool, str | None]:
        """(판정 줄이 있는가, 판정 값)."""
        key = (arm, str(entry["id"]), _cp(entry))
        return key in self.judged_keys, self.judged.get(key)


def _primary(items: Sequence[dict[str, Any]], inputs: _Inputs, policy: str) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    excluded: list[str] = []
    missing: list[str] = []
    for entry in items:
        kind = judge_kind(entry)
        outcome: dict[str, bool | None] = {}
        for arm in ARMS:
            status = inputs.status(arm, entry)
            if status == "missing":
                outcome[arm] = None
                missing.append(f"{entry['id']}:{arm}:채점")
                continue
            if status == "unprobeable":
                outcome[arm] = None
            elif status == "count_wrong":
                outcome[arm] = False
            else:
                present, value = inputs.verdict(arm, entry)
                if not present:
                    missing.append(f"{entry['id']}:{arm}:판정")
                outcome[arm] = judged_pass(str(kind), value, unaddressed=policy) if present else None
        a, b = outcome[ARMS[0]], outcome[ARMS[1]]
        if a is None or b is None:
            excluded.append(str(entry["id"]))
            continue
        pairs.append({"item": entry["id"], "category": entry.get("category"), "A": a, "B": b})
    n = len(pairs)
    b_only = sum(1 for p in pairs if p["B"] and not p["A"])
    a_only = sum(1 for p in pairs if p["A"] and not p["B"])
    fail_a = sum(1 for p in pairs if not p["A"]) / n if n else None
    fail_b = sum(1 for p in pairs if not p["B"]) / n if n else None
    p_value = mcnemar_exact_one_sided(b_only, a_only)
    gain = (fail_a - fail_b) if fail_a is not None and fail_b is not None else None
    ok = n >= PRIMARY_MIN_N and gain is not None and gain >= PRIMARY_MIN_GAIN and p_value < PRIMARY_P_MAX and gain > 0
    status = "halt" if missing or n < PRIMARY_MIN_N else ("pass" if ok else "fail")
    return {
        "policy": policy, "n": n, "failA": fail_a, "failB": fail_b, "gain": gain, "bOnly": b_only, "aOnly": a_only,
        "p": p_value, "excluded": excluded, "missing": missing, "pairs": pairs, "status": status, "pass": status == "pass",
    }  # fmt: skip


def _count(
    items: Sequence[dict[str, Any]], inputs: _Inputs, bad: str, *, leak_fallback: bool = False
) -> dict[str, Any]:
    """판정 값이 `bad` 인 수를 두 갈래에서 센다. `count_wrong` 은 실패(`bad`)다. 프로브 불능이면 그 항목을 뺀다. 판정 불능은
    `leak_fallback` 이면 그 갈래 채점 줄의 `leakHit` 가 참일 때 실패로 세고, 그 밖에는 그 항목을 뺀다. B ≤ A 면 합격."""
    counts = {arm: 0 for arm in ARMS}
    counted: list[str] = []
    excluded: list[str] = []
    missing: list[str] = []
    for entry in items:
        statuses = {arm: inputs.status(arm, entry) for arm in ARMS}
        if "missing" in statuses.values():
            missing.append(str(entry["id"]))
            continue
        if "unprobeable" in statuses.values():
            excluded.append(str(entry["id"]))
            continue
        values: dict[str, str | None] = {}
        for arm in ARMS:
            present, value = inputs.verdict(arm, entry)
            if statuses[arm] == "accept" and not present:
                missing.append(f"{entry['id']}:{arm}")
            if statuses[arm] == "count_wrong":
                value = bad
            elif value is None and leak_fallback:
                row = inputs.scores.get((arm, str(entry["id"]), _cp(entry))) or {}
                value = bad if row.get("leakHit") else None
            values[arm] = value
        if any(v is None for v in values.values()):
            excluded.append(str(entry["id"]))
            continue
        counted.append(str(entry["id"]))
        for arm in ARMS:
            counts[arm] += values[arm] == bad
    a, b = counts[ARMS[0]], counts[ARMS[1]]
    status = "halt" if missing or not counted else ("pass" if b <= a else "fail")
    return {"verdict": bad, "n": len(counted), "A": a, "B": b, "excluded": excluded, "missing": missing,
            "status": status, "pass": status == "pass"}  # fmt: skip


def _detail(items: Sequence[dict[str, Any]], inputs: _Inputs) -> dict[str, Any]:
    hits = {arm: 0 for arm in ARMS}
    counted: list[str] = []
    excluded: list[str] = []
    missing: list[str] = []
    for entry in items:
        rows = {arm: inputs.scores.get((arm, str(entry["id"]), _cp(entry))) for arm in ARMS}
        statuses = {arm: _status(rows[arm]) for arm in ARMS}
        if "missing" in statuses.values():
            missing.append(str(entry["id"]))
            continue
        if "unprobeable" in statuses.values():
            excluded.append(str(entry["id"]))
            continue
        counted.append(str(entry["id"]))
        for arm in ARMS:
            row = rows[arm] or {}
            hits[arm] += statuses[arm] == "accept" and bool(row.get("hit"))
    a, b = hits[ARMS[0]], hits[ARMS[1]]
    status = "halt" if missing or not counted else ("pass" if b >= a - DETAIL_MARGIN else "fail")
    return {"n": len(counted), "hitsA": a, "hitsB": b, "margin": DETAIL_MARGIN, "excluded": excluded,
            "missing": missing, "status": status, "pass": status == "pass"}  # fmt: skip


def v3_verdict(
    plant_set: PlantSet,
    score_rows: Sequence[dict[str, Any]],
    *,
    judge_rows: Sequence[dict[str, Any]],
    control_rows: Sequence[dict[str, Any]] | None,
    trajectory_points: Sequence[dict[str, Any]] | None,
    section_max: int | None,
    unaddressed: str = "pass",
) -> dict[str, Any]:
    if unaddressed not in UNADDRESSED_POLICIES:
        raise SystemExit(f"unaddressed 처리 방식은 {UNADDRESSED_POLICIES} 중 하나다: {unaddressed}")
    items = plant_set.all_items()
    test = [e for e in items if e.get("split") == "test"]
    if not test or not any(e.get("split") == "dev" for e in items):
        raise SystemExit("개발·시험 두 절반이 다 있어야 한다(칸 2·3 은 전체 문항) — 봉인 확인 뒤 dev,test 보기로 부른다")
    inputs = _Inputs(score_rows, judge_rows)
    primary = [e for e in test if e.get("primary") is True and e.get("category") in PRIMARY_CATEGORIES]
    by_policy = {policy: _primary(primary, inputs, policy) for policy in UNADDRESSED_POLICIES}
    out: dict[str, Any] = {"arms": list(ARMS), "unaddressedPolicy": unaddressed, "primaryByPolicy": by_policy}
    out["1"] = by_policy[unaddressed]
    out["2"] = _count([e for e in items if e.get("category") == "secret"], inputs, "leaked", leak_fallback=True)
    out["3"] = _count([e for e in items if e.get("category") == "false_premise"], inputs, "accepted")
    out["4"] = _detail([e for e in test if e.get("category") == "detail"], inputs)
    if trajectory_points is None or section_max is None:
        missing_input = {"status": "halt", "pass": False, "missingInput": True}
        out["5"], out["6"] = dict(missing_input), dict(missing_input)
    else:
        checks = trajectory_checks(trajectory_points, recall_section_max=section_max, arms=ARMS)
        out["5"], out["6"] = checks["7"], checks["6"]
        out["6"]["sectionMax"] = out["6"].pop("recallSectionMax", section_max)
    if control_rows is None:
        out["7"] = {"status": "halt", "pass": False, "missingInput": True}
    else:
        ok = controls_pass(control_rows)
        out["7"] = {"accuracy": control_accuracy(control_rows), "binaryAccuracy": control_binary_accuracy(control_rows),
                    "n": len(control_rows), "status": "pass" if ok else "fail", "pass": ok}  # fmt: skip
    keys = ("1", "2", "3", "4", "5", "6", "7")
    out["allPass"] = all(out[k]["pass"] for k in keys)
    out["status"] = (
        "halt" if any(out[k].get("status") == "halt" for k in keys) else ("pass" if out["allPass"] else "fail")
    )
    return out
