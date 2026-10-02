"""판정 리플레이 JSONL 을 판정 × 설정 표로 집계한다(호출 없음).

    cd apps/api && uv run python scripts/analyze_judgment_replay.py probe-runs/judgment-replay.jsonl

여러 파일을 주면 합쳐서 본다(같은 설정을 나눠 돌린 경우). 계산 정의와 통과 기준은 `judgment_replay/analysis.py`.
"""

import argparse
from pathlib import Path

from judgment_replay.analysis import analyze, format_report, load_records
from judgment_replay.runner import BASELINE_CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--baseline", default=BASELINE_CONFIG)
    parser.add_argument("--margin-pp", type=float, default=5.0, help="현행 자기 일치율보다 낮아도 되는 폭(%%p)")
    args = parser.parse_args()
    records = [record for path in args.paths for record in load_records(path)]
    print(format_report(analyze(records, baseline=args.baseline, margin_pp=args.margin_pp)))


if __name__ == "__main__":
    main()
