"""측정 하네스 진입점 — `apps/api` 에서 `PYTHONPATH=scripts uv run --env-file .env python -m novel_bible_eval <명령>`.

- `synthetic`: 합성 세트를 심고 확정·처리해 실행 폴더에 보고서(JSON·마크다운)와 결과(`outcomes.json`)를 쓴다.
- `copy-text`: 텍스트 파일 폴더(사람 라벨 원고)에서 어댑터마다 새 소설 사본을 만들고 어댑터 → 소설 id 를 `copies.json` 에 쓴다.
  그 파일이 이미 있으면 `--add` 없이는 거절한다(덮으면 다른 어댑터의 사본 id 가 사라진다). 문단이 하나뿐인 화는 경고한다.
- `extract`: 사람 라벨용 소설 사본의 앞 화들을 확정해 그 어댑터의 결과를 쓴다. 이미 정본 기억 확정이 있는 소설은 거절한다 —
  같은 소설로 두 번째 어댑터를 돌리면 확정 입구가 같은 개정을 그대로 돌려 첫 어댑터의 작업을 모으고, 오류 없이 틀린 결과가 된다.
  결과 파일의 `halted` 칸에 멈춤·끊김 까닭, 또는 검사까지 끝난 확정이 요청한 화 수보다 적다는 것을 적는다(끝까지 돌았으면
  null) — 나중에 결과 파일만 보는 사람도 앞 화 일부만 담긴 결과인지 안다. 시도 기록·원가·막힌 화도 함께 싣는다. 화가 모자라면
  표준 오류에 까닭을 쓰고 종료 코드 21 로 끝난다 — 라벨 전에 다시 추출할지 정하게.
- `sheet`: 어댑터들의 `extract` 결과를 합쳐 라벨 시트와 열쇠를 쓴다. 결과 파일의 `halted` 와 추출 요약은 열쇠로 옮기고, 멈췄거나
  모자란 추출이 있으면 시트 머리와 표준 오류에 알린다. 어댑터 사본들의 같은 화 본문이 다르면(다른 원고) 거절한다.
- `judge`: 열쇠의 주장을 판정 모델 하나(`gemini` 먼저, 그다음 `haiku`)로 사람 라벨과 같은 범주로 매겨 `judge-<모델>.json` 에
  쓴다(`judge.py`). 부를 모델 id 는 `--judge-model` 로 정하고, 판정 호출이 실제로 가는 구현에서 사고를 끈 조건이 되지 않는 id 나
  단가표에 없는 id 는 부르기 전에 거절한다. 멈춘 뒤 같은 실행 폴더로 다시 돌리면 판정이 없는 주장만 부른다 — 판정 파일의 모델
  id 나 열쇠가 다르면 거절한다.
- `score`: 사람이 내려받은 시트 결과를 읽어 어댑터별 라벨 지표를 쓰고, 판정 파일을 주면 판정 모델마다 κ 를 더한다. 열쇠에
  멈춤·끊김 까닭이 있는 어댑터의 판정은 판정 불가다. 판정 이름이 같은 판정 파일 둘은 거절한다 — κ 칸이 판정 이름마다 하나다.

무엇이든 하기 전에 DB 가 로컬인지 본다 — 운영·공유 DB 에 측정 소설을 심거나 사용자 원고를 모델에 보내지 않게. 모델을 부르는
명령(`synthetic`·`extract`·`judge`)은 원장을 요구한다: 호출마다 견적으로 자리를 잡고 실제 호출 기록으로 원가를 적으며, 묶음 누적이
멈춤 선에 닿을 호출은 부르기 전에 멈추고 그때까지의 결과를 쓴 뒤 종료 코드 20 으로 끝난다. 다른 이유로 끊겨도(Ctrl-C·DB 오류)
끝난 부분까지 쓰고 예외를 다시 올린다 — 낸 돈은 원장에 남으므로 결과를 버리면 다시 돌려야 한다. 상한·멈춤 선·견적은 승인
값이라 기본값 없이 인자로 받는다. 어댑터 배정은 이 프로세스의 env(`NOVEL_BIBLE_ADAPTERS`)가 정한다 — `--adapter` 는 보고서에
적는 이름이다. 판정 모델 호출(정본 기억의 충돌 판정)은 아직 없다. 검사 단계에 판정이 들어오면 그 호출이 이 해석기를 지나게 해야
원장에 든다(지금 검사 단계는 해석기를 받지 않는다)."""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select

from api.core.config import settings
from api.db.models import NovelChapterRevision
from api.db.models.novel_bible import NovelBibleCommit
from api.db.session import async_session_factory
from api.novel_bible.adapters.resolver import build_resolver
from api.novel_bible.core.contracts import AdapterResolver, BibleModelAdapter
from api.novel_bible.core.jobs import SessionFactory
from api.novel_bible.core.views import manuscript_of
from api.novel_bible.ids import SlotId
from memory_eval.ledger import EXIT_BUDGET, Ledger
from replay.local_db import ensure_local_database

from novel_bible_eval import judge as judging
from novel_bible_eval import labels, metrics, text_copy
from novel_bible_eval.report import label_report, synthetic_report, write_report
from novel_bible_eval.run import BudgetHalt, ChapterOutcome, Meter, extract_chapters, run_set
from novel_bible_eval.spec import EvalSet, load_set

# 화 부족으로 끝난 추출 — 원장 멈춤(`EXIT_BUDGET`)과 갈라 다음 단계(시트·라벨)로 넘어가기 전에 멈추게 한다.
EXIT_SHORT = 21


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


async def copy_text(
    factory: SessionFactory, folder: Path, adapters: list[str], run_dir: Path, *, add: bool = False
) -> int:
    """어댑터마다 사본 하나. 한 트랜잭션이라 폴더가 거절되거나 중간에 끊기면 사본이 하나도 남지 않는다. `add` 면 기존
    `copies.json` 에 더한다(같은 어댑터는 새 사본으로 바뀐다)."""
    path = run_dir / "copies.json"
    copies: dict[str, str] = {}
    if path.exists():
        if not add:
            raise SystemExit(f"{path} 가 이미 있다 — 덮으면 다른 어댑터의 사본 id 가 파일에서 사라진다. 사본을 더하려면 --add")
        copies = json.loads(path.read_text(encoding="utf-8"))
    text = text_copy.read_text_dir(folder)
    for number, paragraphs in enumerate(text.chapters, start=1):
        if len(paragraphs) == 1:
            print(f"경고: {number}화는 문단이 하나뿐이다 — 줄바꿈 하나로 문단을 가른 원고면 빈 줄로 다시 가른다", file=sys.stderr)
    async with factory() as session, session.begin():
        for adapter in adapters:
            novel_id, _ = await text_copy.copy_text_novel(session, text)
            copies[adapter] = str(novel_id)
    _write_json(path, copies)
    counts = " · ".join(f"{number}화 {len(paragraphs)}" for number, paragraphs in enumerate(text.chapters, start=1))
    print(f"{len(text.chapters)}화 사본 {len(adapters)}벌 — {path} (화별 문단 수: {counts})")
    return 0


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def extract(
    factory: SessionFactory, resolver: AdapterResolver, novel_id: uuid.UUID, run_dir: Path, *, adapter: str,
    count: int, meter: Meter, slots: frozenset[SlotId] | None = None,
) -> int:
    """`resolver` 는 `meter` 가 감싼 해석기다 — 그 시도 기록을 결과에 싣는다."""
    async with factory() as session:
        confirmed = await session.scalar(
            select(func.count()).select_from(NovelBibleCommit).where(NovelBibleCommit.novel_id == novel_id)
        )
    if confirmed:
        # 결과 파일을 쓰기 전에 거절한다 — 같은 어댑터 이름으로 다시 돌린 것이면 앞서 쓴 결과를 덮지 않는다.
        raise SystemExit(
            f"소설 {novel_id} 에 이미 정본 기억 확정이 {confirmed}건 있다 — 어댑터마다 copy-text 로 만든 새 사본을 쓴다"
        )
    outcomes: list[ChapterOutcome] = []
    halted: str | None = None
    try:
        await extract_chapters(factory, resolver, novel_id, count=count, slots=slots, outcomes=outcomes)
        judged = sum(outcome.status in ("committed", "blocked") for outcome in outcomes)
        if judged < count:
            halted = f"화 부족 — 요청 {count}화 중 검사까지 끝난 확정 {judged}화(확정한 화 {len(outcomes)})"
            print(f"{halted} — 이 추출로 라벨하면 그 어댑터 판정은 판정 불가다", file=sys.stderr)
    except BudgetHalt as halt:
        halted = str(halt)
        print(f"원장 멈춤: {halt} — 끝난 {len(outcomes)}화까지 썼다")
        return EXIT_BUDGET
    except BaseException as error:
        halted = f"끊김 — {type(error).__name__}: {error}"
        print(f"끊김: {type(error).__name__} — 끝난 {len(outcomes)}화까지 썼다")
        raise
    finally:
        _write_extract(outcomes, run_dir, adapter, halted, meter.attempts)
    return EXIT_SHORT if halted else 0


def _write_extract(
    outcomes: list[ChapterOutcome], run_dir: Path, adapter: str, halted: str | None,
    attempts: list[tuple[str, str | None]],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = labels.ExtractionSummary(
        attempts=attempts, quote=list(metrics.quote_rate(outcomes).clusters), cost=metrics.cost(outcomes),
        blocked={outcome.ordinal: outcome.block_rules for outcome in outcomes if outcome.status == "blocked"},
    )
    written = {
        "halted": halted, **summary.model_dump(mode="json"),
        "outcomes": [outcome.model_dump(mode="json") for outcome in outcomes],
    }
    (run_dir / f"extract-{adapter}.json").write_text(json.dumps(written, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")


async def judge(adapter: BibleModelAdapter, key: Path, run_dir: Path, *, model: str, model_id: str) -> int:
    """`adapter` 는 측정 원장을 지나는(`Meter` 가 감싼) 판정 어댑터이고 `model_id` 는 그 어댑터가 부르는 모델 id 다. 판정 파일이
    이미 있으면 그 판정을 이어받는다."""
    path = run_dir / f"judge-{model}.json"
    run, claims = _judge_inputs(path, key, model, model_id)
    try:
        await judging.judge_claims(adapter, claims, run)
    except BudgetHalt as halt:
        run.halted = str(halt)
        print(f"원장 멈춤: {halt} — 판정 {len(run.answers)}건까지 썼다")
        return EXIT_BUDGET
    except BaseException as error:
        run.halted = f"끊김 — {type(error).__name__}: {error}"
        raise
    finally:
        judging.write_run(run, path)
    return 0


def _judge_inputs(
    path: Path, key: Path, model: str, model_id: str
) -> tuple[judging.JudgeRun, list[labels.Claim]]:
    """이어받는 판정 파일이 다른 모델 id 의 것이거나 다른 열쇠로 판정한 것이면 거절한다 — 섞인 판정으로 κ 를 재지 않게."""
    claims = [labels.Claim.model_validate(row) for row in json.loads(key.read_text(encoding="utf-8"))["claims"]]
    digest = judging.key_digest(claims)
    if not path.exists():
        return judging.JudgeRun(model=model, model_id=model_id, key_digest=digest), claims
    run = judging.read_run(path)
    if run.model_id != model_id:
        raise SystemExit(f"{path} 는 {run.model_id} 의 판정이다 — {model_id} 로 이어 돌리지 않는다. 다른 실행 폴더를 쓴다")
    _check_key(run, digest, path)
    run.halted = None
    return run, claims


def _check_key(run: judging.JudgeRun, digest: str, path: Path) -> None:
    if run.key_digest != digest:
        raise SystemExit(f"{path} 는 지금 열쇠와 다른 주장·인용으로 판정했다 — 이 열쇠로 새 판정 파일을 만든다")


async def _check_same_manuscript(factory: SessionFactory, runs: dict[str, list[ChapterOutcome]]) -> None:
    """어댑터 사본들의 같은 화가 같은 본문(개정의 `content_hash`)인가. 사본 사이에 원고 폴더를 고쳤다면 다른 원고의 추출이 한
    시트에 섞여, 같은 화의 주장이 서로 다른 본문을 가리킨다."""
    revision_of = {
        (name, outcome.ordinal): uuid.UUID(outcome.revision)
        for name, outcomes in runs.items() for outcome in outcomes if outcome.revision is not None
    }
    async with factory() as session:
        rows = await session.execute(
            select(NovelChapterRevision.id, NovelChapterRevision.content_hash)
            .where(NovelChapterRevision.id.in_(set(revision_of.values())))
        )
        hashes = {revision: content_hash for revision, content_hash in rows.tuples()}
    bodies: dict[int, set[str]] = {}
    for (_, ordinal), revision in revision_of.items():
        bodies.setdefault(ordinal, set()).add(hashes[revision])
    differing = sorted(ordinal for ordinal, found in bodies.items() if len(found) > 1)
    if differing:
        chapters = ", ".join(f"{ordinal}화" for ordinal in differing)
        raise SystemExit(f"어댑터 사본들의 {chapters} 본문이 서로 다르다 — 같은 원고로 만든 사본의 추출만 한 시트에 합친다")


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
    budget = argparse.ArgumentParser(add_help=False)
    budget.add_argument("--run-dir", type=Path, required=True)
    budget.add_argument("--ledger", type=Path, required=True, help="측정 전체가 함께 쓰는 원장 jsonl")
    budget.add_argument("--bundle", required=True, help="승인 묶음 — 멈춤 판정은 이 묶음의 누적만 본다")
    budget.add_argument("--cap-usd", type=float, required=True)
    budget.add_argument("--halt-usd", type=float, required=True)
    budget.add_argument("--estimate-usd", type=float, required=True, help="호출 하나의 견적")
    paid = argparse.ArgumentParser(add_help=False, parents=[budget])
    paid.add_argument("--adapter", required=True, help="보고서에 적는 어댑터 이름(배정은 env 가 정한다)")
    paid.add_argument("--slots", help="쉼표로 가른 슬롯 id(없으면 등록부 전부)")
    run = commands.add_parser("synthetic", parents=[paid])
    run.add_argument("--set", type=Path, required=True)
    run.add_argument("--repeats", type=int, default=1)
    extract = commands.add_parser("extract", parents=[paid])
    extract.add_argument("--novel-id", type=uuid.UUID, required=True)
    extract.add_argument("--chapters", type=int, default=4)
    copy = commands.add_parser("copy-text")
    copy.add_argument("--text-dir", type=Path, required=True, help="01.txt…NN.txt 와 선택 meta.txt 가 든 원고 폴더")
    copy.add_argument("--adapters", nargs="+", required=True, help="사본을 하나씩 만들 어댑터 이름")
    copy.add_argument("--run-dir", type=Path, required=True)
    copy.add_argument("--add", action="store_true", help="기존 copies.json 에 사본을 더한다(같은 어댑터는 새 사본으로 바뀐다)")
    rate = commands.add_parser("judge", parents=[budget])
    rate.add_argument("--key", type=Path, required=True, help="sheet 가 쓴 열쇠(claims-key.json)")
    rate.add_argument("--model", choices=list(judging.JUDGE_MODELS), required=True, help="판정 모델 — 싼 gemini 먼저")
    rate.add_argument(
        "--judge-model", required=True, help="부를 모델 id(예 gemini-3.5-flash-lite·claude-haiku-5-5) — 판정 파일에 적는다"
    )
    sheet = commands.add_parser("sheet")
    sheet.add_argument("--extract", nargs="+", required=True, metavar="어댑터=결과.json")
    sheet.add_argument("--out", type=Path, required=True)
    sheet.add_argument("--seed", type=int, default=0)
    score = commands.add_parser("score")
    score.add_argument("--key", type=Path, required=True)
    score.add_argument("--labels", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    score.add_argument("--judged", type=Path, nargs="*", default=[], metavar="judge-모델.json")
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
            factory, resolver, args.novel_id, args.run_dir, adapter=args.adapter, count=args.chapters, meter=meter,
            slots=slots,
        )
    if args.command == "judge":
        judge_adapter = judging.judge_adapter(args.model, args.judge_model)
        ledger = Ledger(args.ledger, cap_usd=args.cap_usd, halt_usd=args.halt_usd, bundle=args.bundle)
        meter = Meter(ledger=ledger, estimate_usd=args.estimate_usd)
        adapter = meter.wrap(lambda _operation: judge_adapter)("conflicts.judge")
        return await judge(adapter, args.key, args.run_dir, model=args.model, model_id=args.judge_model)
    if args.command == "copy-text":
        return await copy_text(factory, args.text_dir, args.adapters, args.run_dir, add=args.add)
    if args.command == "sheet":
        files = {name: Path(path) for name, path in (item.split("=", 1) for item in args.extract)}
        runs = {name: _outcomes(path) for name, path in files.items()}
        await _check_same_manuscript(factory, runs)
        halted = {name: _halted(path) for name, path in files.items()}
        sheet, key = labels.write_sheet(
            labels.merge_claims(runs, await _block_texts(factory, runs)), args.out,
            halted=halted,
            extraction={
                name: labels.ExtractionSummary.model_validate_json(path.read_text(encoding="utf-8"))
                for name, path in files.items()
            },
            seed=args.seed,
        )
        for name, reason in halted.items():
            if reason:
                print(f"!!! {name} 추출이 멈췄거나 모자라다 — {reason}. 이대로 라벨하면 그 어댑터 판정은 판정 불가다", file=sys.stderr)
        print(f"시트 {sheet} · 열쇠 {key}")
        return 0
    labeled = labels.read_labels(args.labels, args.key)
    judged = {path: judging.read_run(path) for path in args.judged}
    digest = judging.key_digest([row.claim for row in labeled])
    for path, run in judged.items():
        _check_key(run, digest, path)
    names = [run.model for run in judged.values()]
    if doubled := sorted({name for name in names if names.count(name) > 1}):
        raise SystemExit(
            f"판정 이름이 같은 판정 파일이 둘 이상이다({', '.join(doubled)}) — 보고서의 κ 는 판정 이름마다 한 칸이라 한 파일만 "
            "남는다. 파일마다 따로 점수를 낸다"
        )
    report = label_report(
        labeled, labels.read_halted(args.key), labels.read_extraction(args.key),
        {run.model: run for run in judged.values()},
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "label-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ensure_local_database(settings.database_url, tool="novel_bible_eval")
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
