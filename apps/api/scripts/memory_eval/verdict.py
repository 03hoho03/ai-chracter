"""최종 짝 비교(회상 꺼짐 A vs 켜짐 B) 병합 판단 집계 — 사전 등록한 ①~⑤.

① 짝 비교: 시험 절반의 짝 대상 항목(`metrics.MA1_pair`)마다 그 항목을 물은 마지막 체크포인트의 1문항. 두 갈래 중 하나라도
   프로브 불능이면 그 항목을 뺀다. 회상 코드 오류로 끝난 B 응답(`count_wrong`)은 B 오답이다. 정확 McNemar 단측 p < 0.05 그리고
   (B − A)/n ≥ 0.20.
② 300턴 정답 포함(`metrics.MA1_300`, 시험 절반): B 윌슨 하한 ≥ A 점추정.
③ 오프라인 직접 형식 합격선: `recall_offline.direct_passline`(분모 하한·대상 표시 포함).
④ 기권: 기권 항목 전체에서 판정자가 "지어냄"으로 본 수가 B 에서 A 보다 2건 이상 많지 않다(판정 불능 항목은 두 갈래 모두 뺀다).
⑤ 되감기 누출: 되감기 항목 전체에서 B 누출(결정론 적중 AND 판정자 단정)이 0. A 의 결정론 적중도 함께 낸다.
보조로 A 갈래의 맥락 턴 적중 비율을 낸다.
시험 절반 계산이므로 부르는 쪽이 봉인 확인을 먼저 거친다."""

from collections.abc import Sequence
from typing import Any

from memory_eval.judge import leak
from memory_eval.metrics import mcnemar_exact_one_sided, wilson_interval
from memory_eval.plants import PlantSet
from memory_eval.recall_offline import direct_passline

PAIR_P_MAX = 0.05
PAIR_MIN_GAIN = 0.20
ABSTAIN_MAX_EXTRA = 2


def _hit(row: dict[str, Any] | None) -> bool | None:
    """채점 줄의 정답 포함. 불능(채점 안 됨)은 None, 회상 오류(`count_wrong`)는 오답."""
    if row is None or row.get("status") == "unprobeable" or not row.get("scored", True):
        return None
    if row.get("status") == "count_wrong":
        return False
    return bool(row.get("hit"))


def _by_key(rows: Sequence[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    return {(str(r["arm"]), str(r["item"]), int(r["checkpoint"])): r for r in rows}


def _last_checkpoint(rows: Sequence[dict[str, Any]], item: str) -> int | None:
    cps = [int(r["checkpoint"]) for r in rows if r["item"] == item]
    return max(cps) if cps else None


def s8_verdict(
    plant_set: PlantSet,
    score_rows: Sequence[dict[str, Any]],
    *,
    judge_rows: Sequence[dict[str, Any]],
    offline_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
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

    # ④ 기권 전체
    abstains = [str(a["id"]) for a in plant_set.abstains]
    usable = [i for i in abstains if judged.get(("A", i)) is not None and judged.get(("B", i)) is not None]
    fab_a = sum(1 for i in usable if judged[("A", i)] == "fabricated")
    fab_b = sum(1 for i in usable if judged[("B", i)] == "fabricated")
    out["4"] = {
        "n": len(usable), "fabricatedA": fab_a, "fabricatedB": fab_b,
        "judgeUnavailable": sorted(set(abstains) - set(usable)), "pass": fab_b - fab_a < ABSTAIN_MAX_EXTRA,
    }  # fmt: skip

    # ⑤ 되감기 전체
    rewinds = [str(p["id"]) for p in plant_set.plants if p.get("category") == "되감기"]
    leaks_b = 0
    undecided = []
    hits_a = 0
    for item in rewinds:
        cp = _last_checkpoint(score_rows, item) or 300
        b_hit = _hit(rows.get(("B", item, cp)))
        a_hit = _hit(rows.get(("A", item, cp)))
        hits_a += bool(a_hit)
        verdict = leak(hit=bool(b_hit), judged=judged.get(("B", item)))
        if verdict is None:
            undecided.append(item)
        leaks_b += bool(verdict)
    out["5"] = {
        "n": len(rewinds),
        "leaksB": leaks_b,
        "undecidedB": undecided,
        "hitsA": hits_a,
        "pass": leaks_b == 0 and not undecided,
    }
    # 보조: A 갈래 맥락 턴 적중 비율(회상 없이 맥락 문장만으로 정답이 나오는 정도 — 높으면 대명사 문항의 가정이 무너진다).
    context = [r for r in score_rows if r.get("arm") == "A" and "contextHit" in r and r.get("scored", True)]
    k = sum(1 for r in context if r["contextHit"])
    out["contextHitA"] = {"n": len(context), "k": k, "wilson": wilson_interval(k, len(context))}
    out["allPass"] = all(out[k]["pass"] for k in ("1", "2", "3", "4", "5"))
    return out
