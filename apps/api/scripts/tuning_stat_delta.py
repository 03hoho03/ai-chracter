"""턴당 스탯 변화폭(|Δ|)을 방 하나의 턴 로그와 trace 에서 센다(chat-tuning-goal-prompt.md TU-22, §7-1).

    uv run python scripts/tuning_stat_delta.py <room.jsonl> <trace.jsonl> <roomId> [--reach 이름=값 ...]

- 단위는 stat-turn = (턴, 판정 스탯). 카운터 스탯(시드 `statDefs[].perTurnDelta` 가 있는 스탯)은 LLM 판정 대상이
  아니라 뺀다. 시드는 턴 로그 meta 의 slug·setupIndex 로 `seed_content/data/stories/<slug>.json` 에서 읽는다.
- Δ = `stat_outcome.after − before`(클램프 후). 요청 Δ = `changes[].newValue − before`(클램프 전, LLM 이 낸 값).
  `changes` 에 없는 스탯은 둘 다 0 으로 넣고 누락으로 따로 센다.
- `judgment_failed.stage == "stat"` 인 턴은 뺀다(스탯 적용이 없다).
- 창은 W10(턴 1~10, 주 비교창)·턴 11 이후·방 전체 셋을 낸다. `--reach 몸 손상=90` 은 그 스탯의 `after` 가 값 이상이 된
  첫 턴을 낸다(방 전체 기준).
- 판정 문장은 만들지 않는다 — 기준은 사전 등록본 §7-1 이 정본이다.
"""

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from longrun_metrics import _lines, _stat_names

_SEED_STORIES = Path(__file__).parent / "seed_content" / "data" / "stories"


def _counter_names(meta: dict[str, Any]) -> set[str]:
    story = json.loads((_SEED_STORIES / f"{meta['slug']}.json").read_text(encoding="utf-8"))
    stat_defs = story["startingSetups"][meta["setupIndex"]]["statDefs"]
    return {d["name"] for d in stat_defs if d.get("perTurnDelta") is not None}


def _summary(rows: list[dict[str, Any]], names: list[str]) -> dict[str, Any]:
    deltas = [abs(r["delta"]) for r in rows]
    requested = [abs(r["requestedDelta"]) for r in rows]
    nonzero = [d for d in deltas if d != 0]
    n = len(rows)
    return {
        "n": n,
        "turns": sorted({r["turn"] for r in rows}),
        "absGe15": sum(1 for d in deltas if d >= 15),
        "absGt15": sum(1 for d in deltas if d > 15),
        "absGe10": sum(1 for d in deltas if d >= 10),
        "nonzero": len(nonzero),
        "absMedian": statistics.median(deltas) if deltas else None,
        "absMax": max(deltas, default=None),
        "nonzeroAbsMedian": statistics.median(nonzero) if nonzero else None,
        "requestedAbsGe15": sum(1 for d in requested if d >= 15),
        "requestedAbsGt15": sum(1 for d in requested if d > 15),
        # D2: 클램프 후 Δ 와 요청 Δ 중 하나라도 > 15 면 위반.
        "eitherAbsGt15": sum(1 for r in rows if abs(r["delta"]) > 15 or abs(r["requestedDelta"]) > 15),
        "missing": {name: sum(1 for r in rows if r["stat"] == name and r["missing"]) for name in names},
        "decreases": {name: sum(1 for r in rows if r["stat"] == name and r["delta"] < 0) for name in names},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("room_log", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("room_id")
    parser.add_argument("--reach", action="append", default=[], metavar="이름=값")
    args = parser.parse_args()

    rows_log = _lines(args.room_log)
    meta = next(row for row in rows_log if row["kind"] == "meta")
    if meta["roomId"] != args.room_id:
        raise SystemExit(f"턴 로그 meta roomId {meta['roomId']} 가 인자 {args.room_id} 와 다르다")
    room = [rec for rec in _lines(args.trace) if rec.get("roomId") == args.room_id]

    failed_turns = sorted({rec["turn"] for rec in room if rec["kind"] == "judgment_failed" and rec["stage"] == "stat"})
    outcomes = {rec["turn"]: rec for rec in room if rec["kind"] == "stat_outcome" and rec["turn"] not in failed_turns}
    if not outcomes:
        raise SystemExit("이 방의 stat_outcome 이 없다")
    turns = [
        row for row in rows_log
        if row["kind"] == "turn" and row["http"] == 200 and int(row["roomAfter"]["turnCount"]) in outcomes
    ]
    id_to_name = _stat_names(turns, outcomes)
    counters = _counter_names(meta)
    judged = sorted(name for name in id_to_name.values() if name not in counters)

    rows: list[dict[str, Any]] = []
    for turn in sorted(outcomes):
        rec = outcomes[turn]
        requested = {c["statId"]: float(c["newValue"]) for c in rec["changes"]}
        for stat_id, name in id_to_name.items():
            if name in counters:
                continue
            before = float(rec["before"][stat_id])
            after = float(rec["after"][stat_id])
            missing = stat_id not in requested
            rows.append({
                "turn": turn, "stat": name, "before": before, "after": after,
                "delta": after - before,
                "requested": None if missing else requested[stat_id],
                "requestedDelta": 0.0 if missing else requested[stat_id] - before,
                "missing": missing,
            })

    reach: dict[str, int | None] = {}
    for spec in args.reach:
        name, value = spec.split("=", 1)
        if name not in judged:
            raise SystemExit(f"--reach 스탯 {name} 이 판정 스탯 {judged} 에 없다")
        hits = [r["turn"] for r in rows if r["stat"] == name and r["after"] >= float(value)]
        reach[spec] = min(hits, default=None)

    print(json.dumps({
        "roomId": args.room_id, "slug": meta["slug"], "setupIndex": meta["setupIndex"],
        "judgedStats": judged, "excludedCounterStats": sorted(counters),
        "excludedStatJudgmentFailedTurns": failed_turns,
        "windows": {
            "W10": _summary([r for r in rows if 1 <= r["turn"] <= 10], judged),
            "after10": _summary([r for r in rows if r["turn"] >= 11], judged),
            "all": _summary(rows, judged),
        },
        "firstReachTurn": reach,
        "rows": rows,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
