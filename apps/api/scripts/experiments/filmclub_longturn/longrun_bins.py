"""긴 턴 드라이버 로그를 구간별 `analyze_chat_probe.py` 입력 JSON 으로 바꾼다.

    uv run python scripts/experiments/filmclub_longturn/longrun_bins.py --log <run>/<방>.jsonl \\
        --out <run>/analysis/bins [--bin-size 50] [--phases <run>/analysis/phases.json] [--label filmclub]

긴 턴 런용 옛 판(구간을 1-10…31-40 으로 박아 두어 41턴부터 예외로 멈췄다)을 구간 인자로 바꾼 것이다.
구간은 **방의 `turnCount` 기준** `bin-size` 턴씩(1-50, 51-100, …)이고, 마지막 턴까지 빈틈없이 덮는다.
`--phases` 를 주면(턴 → 국면 이름, `longturn_metrics.py turns` 가 내는 `phases.json`) 국면별 파일도 낸다.
출력은 분석기가 읽는 `{model, results[{label, transcript[{role, text}]}]}` 꼴이다 — 분석기는 고치지 않는다.

- 채점에 넣는 턴은 시뮬레이터 턴뿐이다. 사람 턴(`source: human`)과 회상 프로브 턴(`tag: 프로브`)은 기계 지표
  분모에서 빼야 하므로 transcript 에 넣지 않고 `humanTurns`·`probeTurns` 로만 표시한다. 대신 그 응답은 다음 턴의
  "직전 응답"이 되므로, 빠진 턴에서 transcript 를 끊고 다음 턴부터 새 항목(`results` 의 다음 원소)으로 이어 간다 —
  분석기의 자기복제 판정이 `transcript[0]` 을 직전 응답으로 읽기 때문이다.
- 생성 유실 턴(`failure` 가 있거나 응답이 빈 200 줄)은 `turnCount` 가 늘지 않으므로 시도한 번호(직전 + 1)의
  구간에 빈 응답으로 넣는다. 분석기는 빈 응답을 유실로 세고 채점에서 뺀다.
- http≠200 줄(앱 429·409 등)은 같은 발화의 재시도라 턴이 아니다 — `rejectedLines` 로만 센다.
- 턴이 하나도 없는 구간은 `observed=false` 로 적는다. 0 이 아니라 "관측 없음"이다.
"""

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

BIN_SIZE = 50


def bin_of(turn: int, size: int) -> tuple[int, int]:
    if turn < 1 or size < 1:
        raise ValueError(f"턴 {turn}·구간 크기 {size} 는 1 이상이어야 한다")
    start = (turn - 1) // size * size + 1
    return start, start + size - 1


def bin_name(bounds: tuple[int, int]) -> str:
    return f"{bounds[0]}-{bounds[1]}"


def classify(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, str]:
    """턴 줄을 (턴 번호, 종류, 응답) 으로 정리한다. 종류: scored / lost / human / probe."""
    opening = next(row for row in rows if row["kind"] == "opening")
    turn_count = int(opening["roomAfter"]["turnCount"])
    out: list[dict[str, Any]] = []
    rejected = 0
    for row in rows:
        if row["kind"] != "turn":
            continue
        if row.get("http", 200) != 200:
            rejected += 1
            continue
        lost = bool(row.get("failure")) or not row.get("reply")
        turn = turn_count + 1 if lost else int(row["roomAfter"]["turnCount"])
        if row.get("source") == "human":
            kind = "human"
        elif row.get("tag") == "프로브":
            kind = "probe"
        else:
            kind = "lost" if lost else "scored"
        out.append(
            {
                "turn": turn,
                "kind": kind,
                "lost": lost,
                "user": str(row.get("userText") or ""),
                "reply": "" if lost else str(row["reply"]),
            }
        )
        if not lost:
            turn_count = turn
    return out, rejected, "\n\n".join(opening["messages"])


def group(turns: list[dict[str, Any]], opening: str, key: Callable[[int], str | None]) -> dict[str, dict[str, Any]]:
    """`key(턴)` 이 같은 턴끼리 묶는다. 빠지는 턴(사람·프로브)이나 다른 묶음의 턴을 만나면 transcript 를 끊는다."""
    groups: dict[str, dict[str, Any]] = {}
    previous_reply = opening
    open_segment: tuple[str, list[dict[str, str]]] | None = None
    for item in turns:
        name = key(item["turn"])
        if name is None:
            continue
        entry = groups.setdefault(name, {"segments": [], "turns": [], "lost": [], "humanTurns": [], "probeTurns": []})
        if item["kind"] in ("human", "probe"):
            entry["humanTurns" if item["kind"] == "human" else "probeTurns"].append(item["turn"])
            open_segment = None
        else:
            if open_segment is None or open_segment[0] != name:
                transcript: list[dict[str, str]] = [{"role": "진행자", "text": previous_reply}]
                entry["segments"].append({"transcript": transcript, "turns": []})
                open_segment = (name, transcript)
            open_segment[1].append({"role": "사용자", "text": item["user"]})
            open_segment[1].append({"role": "진행자", "text": item["reply"]})
            entry["segments"][-1]["turns"].append(item["turn"])
            entry["turns"].append(item["turn"])
            if item["lost"]:
                entry["lost"].append(item["turn"])
        if not item["lost"]:
            previous_reply = item["reply"]
    return groups


def payload(label: str, name: str, found: dict[str, Any] | None) -> dict[str, Any]:
    data: dict[str, Any] = {"model": f"{label} {name}", "bin": name, "observed": bool(found and found["turns"])}
    if not data["observed"]:
        data["results"] = []
        data["note"] = "관측 없음 — 이 묶음에 채점 턴이 없다. 0 이 아니다"
    else:
        assert found is not None
        data["results"] = [
            {"label": f"{label}#{name}#{i + 1}", "transcript": seg["transcript"], "turns": seg["turns"]}
            for i, seg in enumerate(found["segments"])
        ]
    if found:
        for field in ("turns", "lost", "humanTurns", "probeTurns"):
            data[field] = found[field]
    return data


def convert(
    rows: list[dict[str, Any]],
    out_dir: Path,
    *,
    label: str,
    bin_size: int = BIN_SIZE,
    phases: dict[int, str] | None = None,
) -> dict[str, Any]:
    turns, rejected, opening = classify(rows)
    last = max((t["turn"] for t in turns), default=0)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "label": label,
        "binSize": bin_size,
        "rejectedLines": rejected,
        "lastTurn": last,
        "bins": [],
        "phases": [],
    }

    by_bin = group(turns, opening, lambda t: bin_name(bin_of(t, bin_size)))
    for start in range(1, last + 1, bin_size):
        name = bin_name((start, start + bin_size - 1))
        data = payload(label, name, by_bin.get(name))
        path = out_dir / f"{label}__{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["bins"].append(
            {
                "path": str(path),
                "bin": name,
                "observed": data["observed"],
                "turns": data.get("turns", []),
                "lost": data.get("lost", []),
                "humanTurns": data.get("humanTurns", []),
                "probeTurns": data.get("probeTurns", []),
            }
        )

    if phases:
        by_phase = group(turns, opening, lambda t: phases.get(t))
        for name, found in by_phase.items():
            data = payload(label, name, found)
            path = out_dir / f"{label}__phase-{name.replace('/', '+').replace(' ', '_')}.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            summary["phases"].append({"path": str(path), "phase": name, "turns": found["turns"]})
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="room")
    ap.add_argument("--bin-size", type=int, default=BIN_SIZE)
    ap.add_argument("--phases")
    args = ap.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.log).read_text(encoding="utf-8").splitlines() if line.strip()]
    phases = None
    if args.phases:
        phases = {int(k): v for k, v in json.loads(Path(args.phases).read_text(encoding="utf-8")).items()}
    summary = convert(rows, Path(args.out), label=args.label, bin_size=args.bin_size, phases=phases)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
