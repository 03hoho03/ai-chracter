"""리플레이 호출의 실제 원가 장부와 하드 상한.

원가는 견적이 아니라 각 호출 기록(jsonl 의 `kind: call`)에 남은 `costUsd` — 모델이 돌려준 토큰 수에 가격표를 곱한
값 — 의 합이다. 여러 묶음을 따로 돌려도 같은 장부(파일 묶음)를 가리키면 앞 묶음의 실제 원가가 이번 상한에 들어간다.
토큰 메타데이터 없이 끝난 호출(중단·오류·정책 거절)은 원가를 모르지만 청구됐을 수 있다. 그런 호출은 기록의
`costCeilingUsd` — 그 호출의 모델 단가로 센 입력 추정과 출력 상한의 값 — 로 센다. 한 값으로 세면 모델 사이 단가 차이만큼
샌다(Claude 상위 모델은 입력만으로도 Gemini 호출 한 번의 수십 배다). 그 칸이 없는 옛 기록만 `UNKNOWN_CALL_USD` 로 센다
(그 기록들은 Gemini 호출뿐이었다).

    # 장부 합계(파일별·전체)
    uv run python scripts/replay/budget.py '<run>/replay/**/*.jsonl'
"""

import glob
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNKNOWN_CALL_USD = 0.01


def call_charge(record: dict[str, Any]) -> float:
    """호출 기록 하나가 상한에 차지하는 금액 — 원가를 알면 그 값, 모르면 그 호출의 상한 추정, 그것도 없는 옛 기록이면
    `UNKNOWN_CALL_USD`."""
    for key in ("costUsd", "costCeilingUsd"):
        if record.get(key) is not None:
            return float(record[key])
    return UNKNOWN_CALL_USD


@dataclass
class LedgerTotal:
    calls: int = 0
    known_usd: float = 0.0
    unknown_calls: int = 0
    unknown_usd: float = 0.0
    per_file: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def charged_usd(self) -> float:
        return self.known_usd + self.unknown_usd


def ledger_paths(pattern: str) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(pattern, recursive=True) if p.endswith(".jsonl"))


def sum_ledger(paths: list[Path]) -> LedgerTotal:
    total = LedgerTotal()
    for path in paths:
        calls = known = unknown = 0.0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("kind") != "call":
                continue
            calls += 1
            if record.get("costUsd") is None:
                unknown += 1
                total.unknown_usd += call_charge(record)
            else:
                known += float(record["costUsd"])
        total.calls += int(calls)
        total.known_usd += known
        total.unknown_calls += int(unknown)
        total.per_file[str(path)] = {"calls": calls, "knownUsd": round(known, 6), "unknownCalls": unknown}
    return total


class CallBudget:
    """프로세스 전체의 실호출 상한 두 겹 — 호출 수(`limit`)와 실제 원가 누적(`usd_limit`, 장부의 앞 묶음 원가
    `spent_usd` 포함). `take` 는 다음 호출을 해도 되는지 보고, 원가는 호출이 끝난 뒤 `charge` 로 더한다 — 그래서 원가
    상한은 마지막 한 호출만큼 넘을 수 있다. `take` 와 그 앞의 검사 사이에 await 가 없어 동시 호출끼리도 호출 수 상한은
    넘지 않는다."""

    def __init__(self, limit: int, *, usd_limit: float | None = None, spent_usd: float = 0.0) -> None:
        self.limit = limit
        self.used = 0
        self.usd_limit = usd_limit
        self.spent_usd = spent_usd

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        if self.usd_limit is not None and self.spent_usd >= self.usd_limit:
            return False
        self.used += 1
        return True

    def charge(self, record: dict[str, Any]) -> None:
        self.spent_usd += call_charge(record)

    def exhausted(self) -> dict[str, Any]:
        return {
            "kind": "budgetExhausted",
            "limit": self.limit,
            "used": self.used,
            "usdLimit": self.usd_limit,
            "spentUsd": round(self.spent_usd, 6),
        }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("사용: budget.py '<glob>'")
        return 1
    total = sum_ledger(ledger_paths(args[0]))
    for path, row in total.per_file.items():
        print(json.dumps({"file": path, **row}, ensure_ascii=False))
    print(
        json.dumps(
            {
                "files": len(total.per_file),
                "calls": total.calls,
                "knownUsd": round(total.known_usd, 6),
                "unknownCalls": total.unknown_calls,
                "chargedUsd": round(total.charged_usd, 6),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
