"""승인된 보완판 문안 표(칸 전문, 안 W·안 N)를 생성 리플레이의 치환 표 두 개로 바꾼다.

    uv run python scripts/experiments/filmclub_longturn/build_swap_tables.py <supplement-swaps.json> <출력 폴더>

입력 칸마다 `v6fix_text`, `supplement_text_W`, 있으면 `supplement_text_N`(없으면 안 N 도 W 문안을 쓴다), 실림 조건
`loaded` 가 있다. 출력 `swap-W.json`·`swap-N.json` 의 칸은 `{key, v6fix, supplement, when, target}` — 문안은 작품 글
원문 그대로 두고(메모리 안 치환이 행의 원문을 바꾸므로), 프롬프트와 견주는 단언은 리플레이 도구가 그 턴의 이름으로 프롬프트
형태로 바꿔서 한다. 오프닝 칸은 작품 행이 아니라 대화 기록 첫 진행자 줄을 바꾸는 칸(`historyOpening`)이다 — 운영 새 방은
보완판 오프닝으로 시작하기 때문이다. 두 문안이 같은 칸은 바꿀 것이 없어 뺀다.
"""

import json
import sys
from pathlib import Path
from typing import Any

OPENING_KEY = "opening_message"


def build_tables(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = {}
    for label in ("W", "N"):
        slots = []
        for cell in source["slots"]:
            supplement = cell.get(f"supplement_text_{label}") or cell["supplement_text_W"]
            if supplement == cell["v6fix_text"]:
                continue
            slots.append(
                {
                    "key": cell["key"],
                    "v6fix": cell["v6fix_text"],
                    "supplement": supplement,
                    "when": cell["loaded"],
                    "target": "historyOpening" if cell["key"] == OPENING_KEY else "rows",
                }
            )
        tables[label] = {"label": label, "variantText": source["variants"][label], "slots": slots}
    if tables["W"]["slots"] == tables["N"]["slots"]:
        raise ValueError("안 W 와 안 N 의 표가 같다 — 두 안이 다른 칸이 없다")
    return tables


def main(argv: list[str]) -> int:
    source = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for label, table in build_tables(source).items():
        path = out / f"swap-{label}.json"
        path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{path}: 칸 {len(table['slots'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
