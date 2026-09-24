"""긴 턴 드라이버 로그(`chat_play.py --log`)를 구간별 `chat_probe` 호환 JSON 으로 바꾼다.

    uv run python scripts/longrun_bins.py <runDir> <slug> [<slug> ...]

`<runDir>/<slug>-s0.jsonl` 을 읽어 `<runDir>/analysis/bins/<slug>__<구간>.json` 을 쓴다.
구간은 1-10 / 11-20 / 21-30 / 31-40 이고 **서버 `turnCount` 기준**이다
(chat-longrun-goal-prompt.md §7-2·§7-3). 출력은 `analyze_chat_probe.py` 가 읽는 신 포맷
`{model, results[{label, transcript[{role, text}]}]}` 이다 — 분석기는 고치지 않는다(LB-24).

- `transcript[0]` 은 **구간 직전 진행자 응답**이다(1구간은 오프닝). 분석기의 자기복제 판정이
  "직전 발화"를 `transcript[0]` 에서 읽기 때문이다(`analyze_chat_probe.py:summarize`).
- 생성 유실 턴(`failure` 가 있거나 `reply` 가 빈 200 줄)은 `turnCount` 가 늘지 않으므로
  **시도한 턴 번호(직전 `turnCount` + 1)의 구간**에 빈 진행자 응답으로 넣는다. 분석기는 빈 응답을
  `empty_replies` 로 세고 채점에서 뺀다.
- 앱 429 줄(`http != 200`)은 같은 발화의 재시도라 턴이 아니다 — 넣지 않고 `rateLimited` 로만 센다.
- 턴이 하나도 없는 구간도 파일을 만들되 `results` 를 비우고 `observed=false` 로 적는다.
  **0 이 아니라 "관측 없음"이다**(엔딩 뒤 턴은 없다, §7-0). 분석기에 넣지 않는다.
- 분석기 결함 줄의 `t<i>` 는 구간 안 순번이라, 서버 턴 번호를 `turns`(분석기가 무시하는 추가 키)에 남긴다.
"""

import json
import sys
from pathlib import Path
from typing import Any

BINS: tuple[tuple[int, int], ...] = ((1, 10), (11, 20), (21, 30), (31, 40))


def bin_name(bounds: tuple[int, int]) -> str:
    return f"{bounds[0]}-{bounds[1]}"


def _bin_of(turn: int) -> tuple[int, int]:
    for bounds in BINS:
        if bounds[0] <= turn <= bounds[1]:
            return bounds
    raise ValueError(f"turn {turn} 이 구간 밖이다(1~40)")


def convert(run_dir: Path, slug: str) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in (run_dir / f"{slug}-s0.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    opening = next(row for row in rows if row["kind"] == "opening")
    previous_reply = "\n\n".join(opening["messages"])
    turn_count = int(opening["roomAfter"]["turnCount"])

    per_bin: dict[tuple[int, int], dict[str, Any]] = {}
    rate_limited = 0
    for row in rows:
        if row["kind"] != "turn":
            continue
        if row["http"] != 200:
            rate_limited += 1
            continue
        lost = bool(row.get("failure")) or not row.get("reply")
        # 유실 턴은 turnCount 가 늘지 않는다 → 시도한 번호(직전 + 1)의 구간.
        turn = turn_count + 1 if lost else int(row["roomAfter"]["turnCount"])
        bounds = _bin_of(turn)
        entry = per_bin.setdefault(
            bounds,
            {"transcript": [{"role": "진행자", "text": previous_reply}], "turns": [], "lost": []},
        )
        reply = "" if lost else str(row["reply"])
        entry["transcript"].append({"role": "사용자", "text": row["userText"]})
        entry["transcript"].append({"role": "진행자", "text": reply})
        entry["turns"].append(turn)
        if lost:
            entry["lost"].append(turn)
        else:
            turn_count = turn
            previous_reply = reply

    out_dir = run_dir / "analysis" / "bins"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for bounds in BINS:
        found = per_bin.get(bounds)
        payload: dict[str, Any] = {
            "model": f"{slug} {bin_name(bounds)}",
            "slug": slug,
            "bin": bin_name(bounds),
            "observed": found is not None,
            "results": [],
        }
        if found is None:
            payload["note"] = "관측 없음 — 이 구간에 턴이 없다(엔딩 뒤 턴 없음). 0 이 아니다"
        else:
            payload["results"] = [
                {"label": f"{slug}#{bin_name(bounds)}", "transcript": found["transcript"],
                 "turns": found["turns"]}
            ]
        path = out_dir / f"{slug}__{bin_name(bounds)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary.append(
            {
                "path": str(path),
                "bin": bin_name(bounds),
                "observed": found is not None,
                "turns": found["turns"] if found else [],
                "lost": found["lost"] if found else [],
            }
        )
    summary.append({"slug": slug, "rateLimitedLines": rate_limited, "finalTurnCount": turn_count})
    return summary


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    run_dir = Path(sys.argv[1])
    report = {slug: convert(run_dir, slug) for slug in sys.argv[2:]}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
