"""긴 턴 런의 토큰·길이 곡선(T), 자극 기술(S), 엔딩 깔때기(E4·E5)를 턴 로그와 trace 에서 계산한다.

    uv run python scripts/longrun_metrics.py <runDir> <slug> [<slug> ...]

입력은 `<runDir>/<slug>-s0.jsonl`(드라이버 턴 로그)과 `<runDir>/trace.jsonl`(계측 두 층)이다.
지표 정의와 판정 기준은 사전 등록본(`<runDir>/preregistration.md` §7-1·§7-4·§7-5)이 정본이고,
이 스크립트는 그 정의를 그대로 계산만 한다 — 결론 문장은 만들지 않는다.

- T-P1: `generation.promptChars` ~ 턴 최소제곱. R² ≥ 0.95 면 기준 충족.
- T-P2: `stat_judgment.promptChars` 기울기 / T-P1 기울기 < 0.05 면 기준 충족.
- T-P3: `ending_judgment.promptChars` 를 엔딩 order 별로 판정 턴에 대해 적합한 기울기 / T-P1 기울기 가
  0.5~2 면 기준 충족. **판정 턴이 2개 미만이면 기울기가 정의되지 않아 계산 불가**다.
- T-D: `usage.prompt_token_count / promptChars` 기술, `cached_content_token_count > 0` 건수.
- `usage` 는 (roomId, turn, call, order) 로 호출부 레코드에 잇는다(chat-longrun-goal-prompt.md §4-2).
- 스모크 방 등 인자로 주지 않은 방의 trace 레코드는 쓰지 않는다(방은 턴 로그 meta 의 roomId 로 고른다).
"""

import json
import statistics
import sys
from pathlib import Path
from typing import Any

_USAGE_CALL = {
    "generation": "generation",
    "stat_judgment": "StatJudgmentResult",
    "ending_judgment": "EndingJudgmentResult",
}


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fit(points: list[tuple[float, float]]) -> dict[str, Any]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    if len(set(xs)) < 2:
        return {"n": len(points), "slope": None, "intercept": None, "r2": None,
                "note": "계산 불가 — 서로 다른 턴이 2개 미만이라 기울기가 정의되지 않는다"}
    slope, intercept = statistics.linear_regression(xs, ys)
    # 점이 2개면 직선이 항상 정확히 지나가 R² 는 1 이다(판정력 없음) — 값은 내되 n 과 함께 읽는다.
    r2 = statistics.correlation(xs, ys) ** 2 if len(set(ys)) > 1 else None
    return {"n": len(points), "slope": slope, "intercept": intercept, "r2": r2}


def _stat_names(turns: list[dict[str, Any]], outcomes: dict[int, dict[str, Any]]) -> dict[str, str]:
    """trace 의 statId 를 턴 로그의 스탯 이름에 잇는다 — 전 턴에서 값이 같은 짝이 하나뿐이어야 한다."""
    ids = list(next(iter(outcomes.values()))["after"])
    names = list(turns[0]["roomAfter"]["stats"])
    mapping: dict[str, str] = {}
    for stat_id in ids:
        matches = [
            name for name in names
            if all(float(t["roomAfter"]["stats"][name]) == float(outcomes[int(t["roomAfter"]["turnCount"])]["after"][stat_id])
                   for t in turns)
        ]
        if len(matches) != 1:
            raise SystemExit(f"statId {stat_id} 매핑이 유일하지 않다: {matches}")
        mapping[stat_id] = matches[0]
    return mapping


def room_metrics(run_dir: Path, slug: str, trace: list[dict[str, Any]]) -> dict[str, Any]:
    rows = _lines(run_dir / f"{slug}-s0.jsonl")
    meta = next(row for row in rows if row["kind"] == "meta")
    opening = next(row for row in rows if row["kind"] == "opening")
    turns = [row for row in rows if row["kind"] == "turn" and row["http"] == 200]
    room = [rec for rec in trace if rec.get("roomId") == meta["roomId"]]

    usage: dict[tuple[int, str, int | None], dict[str, Any]] = {}
    for rec in room:
        if rec["kind"] == "usage":
            usage[(rec["turn"], rec["call"], rec.get("order"))] = rec

    series: dict[str, list[dict[str, Any]]] = {kind: [] for kind in _USAGE_CALL}
    for rec in room:
        if rec["kind"] not in _USAGE_CALL:
            continue
        order = rec.get("order") if rec["kind"] == "ending_judgment" else None
        joined = usage.get((rec["turn"], _USAGE_CALL[rec["kind"]], order))
        point = {"turn": rec["turn"], "order": order, "promptChars": rec["promptChars"],
                 "systemChars": rec.get("systemChars"), "usageJoined": joined is not None}
        if joined is not None:
            for key in ("prompt_token_count", "candidates_token_count", "thoughts_token_count",
                        "cached_content_token_count", "total_token_count", "elapsedMs"):
                point[key] = joined.get(key)
            point["tokenPerChar"] = joined["prompt_token_count"] / rec["promptChars"]
        series[rec["kind"]].append(point)

    t_p1 = _fit([(p["turn"], p["promptChars"]) for p in series["generation"]])
    t_p2 = _fit([(p["turn"], p["promptChars"]) for p in series["stat_judgment"]])
    p1_slope = t_p1["slope"]
    t_p2["ratioToP1"] = (t_p2["slope"] / p1_slope) if (t_p2["slope"] is not None and p1_slope) else None
    t_p2["criterionMet"] = t_p2["ratioToP1"] < 0.05 if t_p2["ratioToP1"] is not None else None
    t_p1["criterionMet"] = t_p1["r2"] >= 0.95 if t_p1["r2"] is not None else None

    t_p3: dict[str, Any] = {}
    for order in sorted({p["order"] for p in series["ending_judgment"]}):
        fit = _fit([(p["turn"], p["promptChars"]) for p in series["ending_judgment"] if p["order"] == order])
        fit["turns"] = sorted(p["turn"] for p in series["ending_judgment"] if p["order"] == order)
        fit["ratioToP1"] = (fit["slope"] / p1_slope) if (fit["slope"] is not None and p1_slope) else None
        fit["criterionMet"] = (0.5 <= fit["ratioToP1"] <= 2) if fit["ratioToP1"] is not None else None
        t_p3[str(order)] = fit

    t_d: dict[str, Any] = {}
    for kind, points in series.items():
        ratios = [p["tokenPerChar"] for p in points if p["usageJoined"]]
        cached = [p for p in points if (p.get("cached_content_token_count") or 0) > 0]
        t_d[kind] = {
            "records": len(points),
            "joined": len(ratios),
            "tokenPerChar": {"min": min(ratios), "median": statistics.median(ratios), "max": max(ratios)}
            if ratios else None,
            "cachedPositive": len(cached),
            "cachedNull": sum(1 for p in points if p.get("cached_content_token_count") is None),
            "thoughtsNull": sum(1 for p in points if p.get("thoughts_token_count") is None),
        }

    cumulative = 0
    per_turn: list[dict[str, Any]] = []
    driver_seconds = {int(t["roomAfter"]["turnCount"]): t["seconds"] for t in turns}
    for turn in sorted(driver_seconds):
        total = sum(u.get("total_token_count") or 0 for (t, _, _), u in usage.items() if t == turn)
        cumulative += total
        per_turn.append({"turn": turn, "seconds": driver_seconds[turn], "totalTokens": total,
                         "cumulativeTotalTokens": cumulative})

    # S — 사용자 발화 자극 기술(§7-4).
    lengths = [len(t["userText"]) for t in turns]
    buckets = {"<=30": sum(1 for n in lengths if n <= 30),
               "31-80": sum(1 for n in lengths if 31 <= n <= 80),
               "81-150": sum(1 for n in lengths if 81 <= n <= 150),
               ">150": sum(1 for n in lengths if n > 150)}
    intents: dict[str, int] = {}
    for t in turns:
        intents[t["intent"]] = intents.get(t["intent"], 0) + 1
    first = turns[0]["userText"] if turns else ""
    chips = opening["suggestedReplies"]
    chip_exact = [i for i, chip in enumerate(chips) if chip == first]
    chip_unquoted = [i for i, chip in enumerate(chips) if chip.strip().strip('"“”') == first]

    # E4·E5 — 판정 깔때기와 카운터 식.
    outcomes = {rec["turn"]: rec for rec in room if rec["kind"] == "stat_outcome"}
    names = _stat_names(turns, outcomes)
    failures = [rec for rec in room if rec["kind"] == "judgment_failed"]
    funnel = [
        {"turn": rec["turn"], "order": rec["order"], "name": rec["name"], "gate": rec["gate"],
         "triggered": rec["triggered"], "rulesPass": rec["rulesPass"],
         "statsAtCheck": {names[k]: v for k, v in rec["statsAtCheck"].items()}}
        for rec in room if rec["kind"] == "ending_check"
    ]
    reached = [{"turn": rec["turn"], "order": rec["order"], "name": rec["name"]}
               for rec in room if rec["kind"] == "ending_reached"]
    trajectory = [
        {"turn": turn,
         "before": {names[k]: v for k, v in outcomes[turn]["before"].items()},
         "llmChanges": {names[c["statId"]]: c["newValue"] for c in outcomes[turn]["changes"]},
         "after": {names[k]: v for k, v in outcomes[turn]["after"].items()},
         "counterApplied": outcomes[turn]["counterApplied"]}
        for turn in sorted(outcomes)
    ]

    return {
        "slug": slug, "roomId": meta["roomId"], "turns": len(turns),
        "T": {"series": series, "T-P1": t_p1, "T-P2": t_p2, "T-P3": t_p3, "T-D": t_d, "perTurn": per_turn},
        "S": {"userLengths": lengths, "lengthMedian": statistics.median(lengths) if lengths else None,
              "lengthMin": min(lengths, default=None), "lengthMax": max(lengths, default=None),
              "buckets": buckets, "intents": intents, "firstTurnText": first, "chips": chips,
              "chipExactIndex": chip_exact, "chipUnquotedIndex": chip_unquoted},
        "E": {"judgmentFailed": failures, "funnel": funnel, "reached": reached,
              "endingLogged": [t["ending"] | {"turn": t["roomAfter"]["turnCount"]} for t in turns if t["ending"]],
              "trajectory": trajectory},
    }


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    run_dir = Path(sys.argv[1])
    trace = _lines(run_dir / "trace.jsonl")
    print(json.dumps([room_metrics(run_dir, slug, trace) for slug in sys.argv[2:]], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
