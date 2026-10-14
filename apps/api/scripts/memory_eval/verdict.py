"""최종 짝 비교(회상 꺼짐 A vs 켜짐 B) 병합 판단 집계 — 사전 등록한 ①~⑤.

① 짝 비교: 시험 절반의 짝 대상 항목(`metrics.MA1_pair`)마다 그 항목을 물은 마지막 체크포인트의 1문항. 두 갈래 중 하나라도
   프로브 불능이면 그 항목을 뺀다. 회상 코드 오류로 끝난 B 응답(`count_wrong`)은 B 오답이다. 정확 McNemar 단측 p < 0.05 그리고
   (B − A)/n ≥ 0.20.
② 300턴 정답 포함(`metrics.MA1_300`, 시험 절반): B 윌슨 하한 ≥ A 점추정.
③ 오프라인 직접 형식 합격선: `recall_offline.direct_passline`(분모 하한·대상 표시 포함). 회상 질문 recall@3 은 서버와 같은 주입 상한(회상 단서 3·그 밖 1)을 적용한 주입 집합으로 센다.
④ 기권: 기권 항목 전체에서 판정자가 "지어냄"으로 본 수가 B 에서 A 보다 2건 이상 많지 않다.
⑤ 되감기 누출: 되감기 항목 전체에서 B 누출(결정론 적중 AND 판정자 단정)이 0. A 의 결정론 적중도 함께 낸다.
④·⑤ 의 불능: 어느 갈래든 프로브 불능이거나 판정 불능(판정 줄의 값이 None)인 항목은 두 갈래 모두에서 빼고 계속한다. 예외로
   되감기 B 가 결정론으로 적중했는데 판정이 불능이면 누출로 센다(누출을 놓치는 쪽보다 과대 집계가 안전하다). 빼고 난 분모가
   0 이면 `halt`. 불능 기록 자체가 없는 입력 누락(채점 줄·판정 줄이 아예 없음)은 불능이 아니라 집계 입력의 결함이라 `halt`.
⑥ 프롬프트 길이: 턴 101~300 의 갈래별 최소제곱 기울기 차 |b_B − b_A| < 2자/턴 그리고 같은 턴의 B − A 최대 ≤ 회상 섹션 최대값.
⑦ 캐시 블록: 같은 턴마다 앞 두 블록 해시가 B 와 A 에서 같다. ⑥·⑦ 은 `trajectory` 두 갈래 점에서 계산하고, 점이 없으면 `halt`.
합격(`allPass`)은 ①~⑦ 전부. 보조로 A 갈래의 맥락 턴 적중 비율을 낸다.
④·⑤ 가 전체 기준이므로 채점 입력에 개발·시험 두 절반이 모두 있어야 한다. 시험 절반 계산이므로 부르는 쪽이 봉인 확인을 먼저
거친다."""

from collections.abc import Sequence
from typing import Any

from memory_eval.judge import leak
from memory_eval.metrics import mcnemar_exact_one_sided, ols_slope, wilson_interval
from memory_eval.plants import PlantSet
from memory_eval.recall_offline import direct_passline

PAIR_P_MAX = 0.05
PAIR_MIN_GAIN = 0.20
ABSTAIN_MAX_EXTRA = 2
SLOPE_DIFF_MAX = 2.0
TRAJECTORY_TURNS = (101, 300)


def _hit(row: dict[str, Any] | None) -> bool | None:
    """채점 줄의 정답 포함. 불능(채점 안 됨)은 None, 회상 오류(`count_wrong`)는 오답."""
    if row is None or row.get("status") == "unprobeable" or not row.get("scored", True):
        return None
    if row.get("status") == "count_wrong":
        return False
    return bool(row.get("hit"))


def _by_key(rows: Sequence[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    return {(str(r["arm"]), str(r["item"]), int(r["checkpoint"])): r for r in rows}


def _unprobeable(row: dict[str, Any] | None) -> bool:
    return row is not None and (row.get("status") == "unprobeable" or not row.get("scored", True))


# 갈래 쌍(기준, 비교). 1차 런은 A·B, 2차 런은 A2·B2.
ARM_PAIRS = (("A", "B"), ("A2", "B2"))


def trajectory_checks(
    points: Sequence[dict[str, Any]], *, recall_section_max: int, arms: tuple[str, str] | None = None
) -> dict[str, Any]:
    """⑥ 길이(턴 101~300 기울기 차·같은 턴 B − A 최대)와 ⑦ 캐시 블록(같은 턴 앞 두 블록 해시 동일). 갈래 쌍을 주지 않으면 점에
    나온 갈래로 고른다(2차 런 갈래가 있으면 A2·B2, 아니면 A·B). 아래 A·B 는 그 쌍의 기준·비교 갈래다."""
    present = {str(p.get("arm")) for p in points}
    base, other = arms or next((pair for pair in reversed(ARM_PAIRS) if set(pair) & present), ARM_PAIRS[0])
    low, high = TRAJECTORY_TURNS
    by_arm: dict[str, dict[int, dict[str, Any]]] = {"A": {}, "B": {}}
    for point in points:
        name = {base: "A", other: "B"}.get(str(point.get("arm")))
        if name is not None:
            by_arm[name][int(point["turn"])] = point
    turns = sorted(set(by_arm["A"]) & set(by_arm["B"]))
    window = [t for t in turns if low <= t <= high]
    if len(window) < 2:
        halt = {"status": "halt", "pass": False, "turns": len(window)}
        return {"6": dict(halt), "7": dict(halt)}
    slope = {arm: ols_slope([(t, by_arm[arm][t]["chars"]) for t in window]) for arm in ("A", "B")}
    diff = abs(slope["B"] - slope["A"])
    max_diff = max(by_arm["B"][t]["chars"] - by_arm["A"][t]["chars"] for t in turns)
    ok6 = diff < SLOPE_DIFF_MAX and max_diff <= recall_section_max
    mismatched = [t for t in turns if by_arm["A"][t]["segmentSha"][:2] != by_arm["B"][t]["segmentSha"][:2]]
    return {
        "6": {"slopeA": slope["A"], "slopeB": slope["B"], "slopeDiff": diff, "maxDiff": max_diff,
              "recallSectionMax": recall_section_max, "turns": len(window), "status": "pass" if ok6 else "fail", "pass": ok6},
        "7": {"turns": len(turns), "mismatchedTurns": mismatched, "status": "fail" if mismatched else "pass",
              "pass": not mismatched},
    }  # fmt: skip


def _last_checkpoint(rows: Sequence[dict[str, Any]], item: str) -> int | None:
    cps = [int(r["checkpoint"]) for r in rows if r["item"] == item]
    return max(cps) if cps else None


def s8_verdict(
    plant_set: PlantSet,
    score_rows: Sequence[dict[str, Any]],
    *,
    judge_rows: Sequence[dict[str, Any]],
    offline_rows: Sequence[dict[str, Any]],
    trajectory_points: Sequence[dict[str, Any]] | None = None,
    recall_section_max: int | None = None,
) -> dict[str, Any]:
    halves = {str(r.get("split")) for r in score_rows}
    if not {"dev", "test"} <= halves:
        raise SystemExit(
            f"④·⑤ 는 전체(개발 + 시험) 기준인데 채점 입력에 {sorted(halves)} 절반만 있다 — score 를 --splits dev,test 로 다시 돌린다"
        )
    rows = _by_key(score_rows)
    out: dict[str, Any] = {}

    # ①
    pair_items = sorted(
        str(p["id"]) for p in plant_set.plants if p.get("split") == "test" and (p.get("metrics") or {}).get("MA1_pair")
    )
    b_only = a_only = both = neither = 0
    excluded: list[str] = []
    pairs = []
    for item in pair_items:
        cp = _last_checkpoint(score_rows, item)
        if cp is None:
            excluded.append(item)
            continue
        a, b = _hit(rows.get(("A", item, cp))), _hit(rows.get(("B", item, cp)))
        if a is None or b is None:
            excluded.append(item)
            continue
        pairs.append({"item": item, "checkpoint": cp, "A": a, "B": b})
        b_only += b and not a
        a_only += a and not b
        both += a and b
        neither += not a and not b
    n = len(pairs)
    p = mcnemar_exact_one_sided(b_only, a_only)
    gain = (b_only - a_only) / n if n else 0.0
    out["1"] = {
        "n": n, "bOnly": b_only, "aOnly": a_only, "both": both, "neither": neither, "p": p, "gain": gain,
        "excludedUnprobeable": excluded, "pairs": pairs, "pass": n > 0 and p < PAIR_P_MAX and gain >= PAIR_MIN_GAIN,
    }  # fmt: skip

    # ②
    items_300 = [
        str(p["id"]) for p in plant_set.plants if p.get("split") == "test" and (p.get("metrics") or {}).get("MA1_300")
    ]
    hits: dict[str, list[bool]] = {"A": [], "B": []}
    for item in items_300:
        a, b = _hit(rows.get(("A", item, 300))), _hit(rows.get(("B", item, 300)))
        if a is None or b is None:
            continue
        hits["A"].append(a)
        hits["B"].append(b)
    n2 = len(hits["A"])
    a_rate = sum(hits["A"]) / n2 if n2 else 0.0
    b_low, b_high = wilson_interval(sum(hits["B"]), n2)
    out["2"] = {
        "n": n2,
        "A": a_rate,
        "B": sum(hits["B"]) / n2 if n2 else 0.0,
        "BWilson": [b_low, b_high],
        "pass": n2 > 0 and b_low >= a_rate,
    }

    # ③
    out["3"] = direct_passline([r for r in offline_rows if r.get("split") == "test"], plant_set, threshold=0.7)
    out["3"]["pass"] = out["3"]["status"] == "pass"

    judged = {(str(r["arm"]), str(r["item"])): r.get("judged") for r in judge_rows}

    def score_at(arm: str, item: str) -> dict[str, Any] | None:
        cp = _last_checkpoint(score_rows, item)
        return rows.get((arm, item, cp)) if cp is not None else None

    # ④ 기권 전체 — 불능 항목은 두 갈래 모두 빼고, 판정 줄 자체가 없으면 입력 누락으로 멈춘다.
    abstains = [str(a["id"]) for a in plant_set.abstains]
    usable: list[str] = []
    excluded4: list[str] = []
    missing_abstain: list[str] = []
    for item in abstains:
        if _unprobeable(score_at("A", item)) or _unprobeable(score_at("B", item)):
            excluded4.append(item)
        elif ("A", item) not in judged or ("B", item) not in judged:
            missing_abstain.append(item)
        elif judged[("A", item)] is None or judged[("B", item)] is None:
            excluded4.append(item)
        else:
            usable.append(item)
    fab_a = sum(1 for i in usable if judged[("A", i)] == "fabricated")
    fab_b = sum(1 for i in usable if judged[("B", i)] == "fabricated")
    status4 = "halt" if missing_abstain or not usable else ("pass" if fab_b - fab_a < ABSTAIN_MAX_EXTRA else "fail")
    out["4"] = {
        "n": len(usable), "fabricatedA": fab_a, "fabricatedB": fab_b, "excluded": excluded4, "missing": missing_abstain,
        "status": status4, "pass": status4 == "pass",
    }  # fmt: skip

    # ⑤ 되감기 전체 — 불능 항목은 빼되, B 가 적중했는데 판정 불능이면 누출로 센다.
    rewinds = [str(p["id"]) for p in plant_set.plants if p.get("category") == "되감기"]
    leaks_b = 0
    hits_a = 0
    counted: list[str] = []
    excluded5: list[str] = []
    missing_b: list[str] = []
    missing_judge: list[str] = []
    by_unjudgeable: list[str] = []
    for item in rewinds:
        a_row, b_row = score_at("A", item), score_at("B", item)
        if b_row is None:
            missing_b.append(item)
            continue
        if _unprobeable(a_row) or _unprobeable(b_row):
            excluded5.append(item)
            continue
        hits_a += bool(_hit(a_row))
        b_hit = bool(_hit(b_row))
        if b_hit and ("B", item) not in judged:
            missing_judge.append(item)
            continue
        counted.append(item)
        verdict = leak(hit=b_hit, judged=judged.get(("B", item)))
        if verdict is None:
            by_unjudgeable.append(item)
            verdict = True
        leaks_b += verdict
    status5 = "halt" if missing_b or missing_judge or not counted else ("pass" if leaks_b == 0 else "fail")
    out["5"] = {
        "n": len(counted), "leaksB": leaks_b, "leakByUnjudgeable": by_unjudgeable, "excluded": excluded5,
        "missingB": missing_b, "missingJudge": missing_judge, "hitsA": hits_a, "status": status5, "pass": status5 == "pass",
    }  # fmt: skip

    # ⑥·⑦
    if trajectory_points is None or recall_section_max is None:
        missing_input = {"status": "halt", "pass": False, "missingInput": True}
        out["6"], out["7"] = dict(missing_input), dict(missing_input)
    else:
        out.update(trajectory_checks(trajectory_points, recall_section_max=recall_section_max))

    # 보조: A 갈래 맥락 턴 적중 비율(회상 없이 맥락 문장만으로 정답이 나오는 정도 — 높으면 대명사 문항의 가정이 무너진다).
    context = [r for r in score_rows if r.get("arm") == "A" and "contextHit" in r and r.get("scored", True)]
    k = sum(1 for r in context if r["contextHit"])
    out["contextHitA"] = {"n": len(context), "k": k, "wilson": wilson_interval(k, len(context))}
    out["allPass"] = all(out[k]["pass"] for k in ("1", "2", "3", "4", "5", "6", "7"))
    out["status"] = (
        "halt"
        if any(out[k].get("status") == "halt" for k in ("3", "4", "5", "6", "7"))
        else ("pass" if out["allPass"] else "fail")
    )
    return out
