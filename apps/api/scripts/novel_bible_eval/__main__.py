"""측정 하네스 진입점 — `apps/api` 에서 `PYTHONPATH=scripts uv run --env-file .env python -m novel_bible_eval <명령>`.

- `synthetic`: 합성 세트를 심고 확정·처리해 실행 폴더에 보고서(JSON·마크다운)와 결과(`outcomes.json`)를 쓴다.
- `extract`: 사람 라벨용 소설 사본의 앞 화들을 확정해 그 어댑터의 결과를 쓴다. 결과 파일의 `halted` 칸에 멈춤·끊김 까닭을 적는다
  (끝까지 돌았으면 null) — 나중에 결과 파일만 보는 사람도 앞 화 일부만 담긴 결과인지 안다.
- `sheet`: 어댑터들의 `extract` 결과를 합쳐 라벨 시트와 열쇠를 쓴다. 결과 파일의 `halted` 는 열쇠로 옮긴다.
- `score`: 사람이 내려받은 시트 결과를 읽어 어댑터별 라벨 지표를 쓴다. 열쇠에 멈춤·끊김 까닭이 있는 어댑터의 판정은 판정
  불가다.

무엇이든 하기 전에 DB 가 로컬인지 본다 — 운영·공유 DB 에 측정 소설을 심거나 사용자 원고를 모델에 보내지 않게. 모델을 부르는
명령(`synthetic`·`extract`)은 원장을 요구한다: 호출마다 견적으로 자리를 잡고 실제 호출 기록으로 원가를 적으며, 묶음 누적이
멈춤 선에 닿을 호출은 부르기 전에 멈추고 그때까지의 결과를 쓴 뒤 종료 코드 20 으로 끝난다. 다른 이유로 끊겨도(Ctrl-C·DB 오류)
끝난 부분까지 쓰고 예외를 다시 올린다 — 낸 돈은 원장에 남으므로 결과를 버리면 다시 돌려야 한다. 상한·멈춤 선·견적은 승인
값이라 기본값 없이 인자로 받는다. 어댑터 배정은 이 프로세스의 env(`NOVEL_BIBLE_ADAPTERS`)가 정한다 — `--adapter` 는 보고서에
적는 이름이다. 판정 모델 호출(정본 기억의 충돌 판정)은 아직 없다. 검사 단계에 판정이 들어오면 그 호출이 이 해석기를 지나게 해야
원장에 든다(지금 검사 단계는 해석기를 받지 않는다)."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import select

from api.core.config import settings
from api.db.models import NovelChapterRevision
from api.db.session import async_session_factory
from api.novel_bible.adapters.resolver import build_resolver
from api.novel_bible.core.contracts import AdapterResolver
from api.novel_bible.core.jobs import SessionFactory
from api.novel_bible.core.views import manuscript_of
from api.novel_bible.ids import SlotId
from memory_eval.ledger import EXIT_BUDGET, Ledger
from replay.local_db import ensure_local_database

from novel_bible_eval import labels
from novel_bible_eval.report import label_report, synthetic_report, write_report
from novel_bible_eval.run import BudgetHalt, ChapterOutcome, Meter, extract_chapters, run_set
from novel_bible_eval.spec import EvalSet, load_set


async def synthetic(
    factory: SessionFactory, resolver: AdapterResolver, eval_set: EvalSet, run_dir: Path, *, adapter: str,
    meter: Meter, repeats: int = 1, slots: frozenset[SlotId] | None = None,
) -> int:
    outcomes: list[ChapterOutcome] = []
    halted: str | None = None
    try:
        await run_set(factory, resolver, eval_set, repeats=repeats, slots=slots, outcomes=outcomes)
    except BudgetHalt as halt:
        halted = str(halt)
    except BaseException as error:
        halted = f"끊김 — {type(error).__name__}: {error}"
        raise
    finally:
        report = synthetic_report(eval_set, outcomes, meter.attempts, adapter=adapter, halted=halted)
        write_report(report, outcomes, run_dir)
    return EXIT_BUDGET if halted else 0


async def extract(
    factory: SessionFactory, resolver: AdapterResolver, novel_id: uuid.UUID, run_dir: Path, *, adapter: str,
    count: int, slots: frozenset[SlotId] | None = None,
) -> int:
    outcomes: list[ChapterOutcome] = []
    halted: str | None = None
    try:
        await extract_chapters(factory, resolver, novel_id, count=count, slots=slots, outcomes=outcomes)
    except BudgetHalt as halt:
        halted = str(halt)
        print(f"원장 멈춤: {halt} — 끝난 {len(outcomes)}화까지 썼다")
        return EXIT_BUDGET
    except BaseException as error:
        halted = f"끊김 — {type(error).__name__}: {error}"
        print(f"끊김: {type(error).__name__} — 끝난 {len(outcomes)}화까지 썼다")
        raise
    finally:
        _write_extract(outcomes, run_dir, adapter, halted)
    return 0


def _write_extract(outcomes: list[ChapterOutcome], run_dir: Path, adapter: str, halted: str | None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    written = {"halted": halted, "outcomes": [outcome.model_dump(mode="json") for outcome in outcomes]}
    (run_dir / f"extract-{adapter}.json").write_text(json.dumps(written, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")


def _outcomes(path: Path) -> list[ChapterOutcome]:
    rows = json.loads(path.read_text(encoding="utf-8"))["outcomes"]
    return [ChapterOutcome.model_validate(row) for row in rows]


def _halted(path: Path) -> str | None:
    reason: str | None = json.loads(path.read_text(encoding="utf-8"))["halted"]
    return reason


async def _block_texts(factory: SessionFactory, runs: dict[str, list[ChapterOutcome]]) -> dict[str, str]:
    texts: dict[str, str] = {}
    revisions = {uuid.UUID(o.revision) for outcomes in runs.values() for o in outcomes if o.revision is not None}
    async with factory() as session:
        for revision in await session.scalars(
            select(NovelChapterRevision).where(NovelChapterRevision.id.in_(revisions))
        ):
            texts |= {str(block.block_id): block.text for block in manuscript_of(revision).blocks}
    return texts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novel_bible_eval")
    commands = parser.add_subparsers(dest="command", required=True)
    paid = argparse.ArgumentParser(add_help=False)
    paid.add_argument("--run-dir", type=Path, required=True)
    paid.add_argument("--adapter", required=True, help="보고서에 적는 어댑터 이름(배정은 env 가 정한다)")
    paid.add_argument("--ledger", type=Path, required=True, help="측정 전체가 함께 쓰는 원장 jsonl")
    paid.add_argument("--bundle", required=True, help="승인 묶음 — 멈춤 판정은 이 묶음의 누적만 본다")
    paid.add_argument("--cap-usd", type=float, required=True)
    paid.add_argument("--halt-usd", type=float, required=True)
    paid.add_argument("--estimate-usd", type=float, required=True, help="호출 하나의 견적")
    paid.add_argument("--slots", help="쉼표로 가른 슬롯 id(없으면 등록부 전부)")
    run = commands.add_parser("synthetic", parents=[paid])
    run.add_argument("--set", type=Path, required=True)
    run.add_argument("--repeats", type=int, default=1)
    extract = commands.add_parser("extract", parents=[paid])
    extract.add_argument("--novel-id", type=uuid.UUID, required=True)
    extract.add_argument("--chapters", type=int, default=4)
    sheet = commands.add_parser("sheet")
    sheet.add_argument("--extract", nargs="+", required=True, metavar="어댑터=결과.json")
    sheet.add_argument("--out", type=Path, required=True)
    sheet.add_argument("--seed", type=int, default=0)
    score = commands.add_parser("score")
    score.add_argument("--key", type=Path, required=True)
    score.add_argument("--labels", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    return parser


async def _run(args: argparse.Namespace) -> int:
    factory: SessionFactory = async_session_factory
    if args.command in ("synthetic", "extract"):
        ledger = Ledger(args.ledger, cap_usd=args.cap_usd, halt_usd=args.halt_usd, bundle=args.bundle)
        meter = Meter(ledger=ledger, estimate_usd=args.estimate_usd)
        resolver = meter.wrap(build_resolver())
        # 등록부에 없는 이름은 확정 입구가 작업을 만들지 않고 지나간다.
        slots: frozenset[SlotId] | None = frozenset(args.slots.split(",")) if args.slots else None
        if args.command == "synthetic":
            return await synthetic(
                factory, resolver, load_set(args.set), args.run_dir, adapter=args.adapter, meter=meter,
                repeats=args.repeats, slots=slots,
            )
        return await extract(
            factory, resolver, args.novel_id, args.run_dir, adapter=args.adapter, count=args.chapters, slots=slots
        )
    if args.command == "sheet":
        files = {name: Path(path) for name, path in (item.split("=", 1) for item in args.extract)}
        runs = {name: _outcomes(path) for name, path in files.items()}
        sheet, key = labels.write_sheet(
            labels.merge_claims(runs, await _block_texts(factory, runs)), args.out,
            halted={name: _halted(path) for name, path in files.items()}, seed=args.seed,
        )
        print(f"시트 {sheet} · 열쇠 {key}")
        return 0
    report = label_report(labels.read_labels(args.labels, args.key), labels.read_halted(args.key))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "label-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ensure_local_database(settings.database_url, tool="novel_bible_eval")
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
