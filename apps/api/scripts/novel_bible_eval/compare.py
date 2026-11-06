"""보고서 묶음 명령 — DB·모델을 부르지 않고 실행 폴더의 파일만 읽는다. `apps/api` 에서
`PYTHONPATH=scripts uv run --env-file .env python -m novel_bible_eval.compare <명령>`.

- `adapters`: 어댑터별 `synthetic` 보고서(`report.json`)를 합쳐 어댑터마다 관측치와 합격선 대조를 한 표로 쓴다.
- `removal`: 열거형 사전 항목을 뺀 전·후의 차단 지표를 두 열로 쓴다. 빼기 전은 그 실행의 결과(`outcomes.json`), 뺀 뒤는 다른
  길로 얻은 결과 묶음이다 — 추출을 다시 부른 실행이든 기록한 출력을 재생한 것이든, 이 명령은 그 결과 파일만 받는다. 세트는 뺀
  항목 목록과 함께 읽는다 — 앱 사전에서 그 줄을 지운 코드로 돌려도 같은 세트(같은 탐침)를 읽는다.

두 명령 모두 오라클 실행(가짜 해석기가 명세 정답을 그대로 낸 실행)의 결과를 거절한다 — 오라클 값은 추출 정확도가 아니라 세트·규칙
정합이라 실측과 한 표에 두면 실측처럼 읽힌다. 보고서는 `oracle` 칸으로, 결과 묶음은 호출 기록의 모델 칸(`oracle`)으로 알아본다."""

import argparse
import json
from pathlib import Path

from novel_bible_eval.fake_llm import ORACLE_MODEL
from novel_bible_eval.report import compare_markdown, removal_markdown, removal_report
from novel_bible_eval.run import ChapterOutcome
from novel_bible_eval.spec import load_set


def _outcomes(path: Path) -> list[ChapterOutcome]:
    outcomes = [ChapterOutcome.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))]
    if any(call.get("model") == ORACLE_MODEL for o in outcomes for job in o.jobs for call in job.calls):
        raise SystemExit(f"{path} 는 오라클 실행의 결과다 — 실측 비교에 넣지 않는다")
    return outcomes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novel_bible_eval.compare")
    commands = parser.add_subparsers(dest="command", required=True)
    adapters = commands.add_parser("adapters")
    adapters.add_argument("--report", nargs="+", required=True, metavar="어댑터=report.json")
    adapters.add_argument("--out", type=Path, required=True)
    removal = commands.add_parser("removal")
    removal.add_argument("--set", type=Path, required=True)
    removal.add_argument("--before", type=Path, required=True, help="빼기 전 실행의 outcomes.json")
    removal.add_argument("--after", type=Path, required=True, help="뺀 뒤 값을 낸 결과 묶음(outcomes.json 꼴)")
    removal.add_argument("--removed", nargs="+", required=True, metavar="enum:범주/정규 값")
    removal.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "adapters":
        reports = {
            name: json.loads(Path(path).read_text(encoding="utf-8"))
            for name, path in (item.split("=", 1) for item in args.report)
        }
        if oracle := [name for name, report in reports.items() if report.get("oracle")]:
            raise SystemExit(f"오라클 실행의 보고서는 어댑터 비교에 넣지 않는다: {', '.join(oracle)}")
        (args.out / "compare.md").write_text(compare_markdown(reports), encoding="utf-8")  # cite-ok: 하네스 출력 파일 이름
        return 0
    before, after = _outcomes(args.before), _outcomes(args.after)
    eval_set = load_set(args.set, removed=args.removed)
    table = removal_report(eval_set, before, after, removed=args.removed)
    (args.out / "removal.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "removal.md").write_text(removal_markdown(table), encoding="utf-8")  # cite-ok: 하네스 출력 파일 이름
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
