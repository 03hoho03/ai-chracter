"""측정한 방의 지난 턴에서 응답 생성을 다시 부른다 — 같은 히스토리·같은 사용자 발화에서 현행(window)과 한 축만 바꾼
갈래가 낸 응답을 모아, 대화 품질 쌍 판정이 공정한 쌍을 짓게 한다.

    cd apps/api
    # 현행 갈래만 시험 실행(호출 0) — 되살린 조립이 덤프와 바이트까지 같은지 본다
    uv run --env-file .env python scripts/generation_replay.py --room <id> --turn 22 --turn 105 \\
        --dump <run>/prompt-dump.jsonl --log <run>/chat.jsonl --snapshot-log <run>/memory-snapshots.jsonl \\
        --limit-calls 0 --out <run>/replay/gen
    # 변형 갈래 하나(축은 하나만): 세트 · 모델 · 작품 버전 · 치환 표
    ... --set <세트 id>|draft [--model gemini|sonnet|opus] --arm <이름> ...
    ... --model sonnet --arm sonnet ...
    ... --version <content_version_id> --arm v7 ...
    ... --swap-table <표.json> --arm W ...
    # 현행 갈래의 세트를 시각 규칙 대신 지정(축이 아니다 — 변형 갈래와 함께 줄 수 있다)
    ... --window-set <세트 id> ...
    # 실제 호출(비용이 든다)
    ... --reps 2 --limit-calls 40 --limit-usd 5 --ledger '<run>/replay/**/*.jsonl' --execute
    # 같은 접두에 두 번째 변형 갈래부터는 현행을 다시 부르지 않는다(이미 부른 (턴, 반복, 갈래)가 있으면 거부한다)
    ... --model sonnet --arm sonnet --skip-window-calls --execute
    # 장부의 실제 원가 합계: uv run python scripts/replay/budget.py '<run>/replay/**/*.jsonl'

입력은 측정 드라이버(`scripts/chat_play.py`)의 두 로그와, 측정하는 동안 서버가 `PROMPT_DUMP_PATH` 로 남긴 프롬프트 덤프다.
덤프가 없는 턴은 리플레이하지 않는다. 턴 N 의 상태는 로그에서(스탯·기억 노트·요약 본문), 히스토리·발화·요약 커서·단축어는
`--env-file` 로 준 DB 에서 읽는다. 그 DB 가 로컬(localhost 류)이 아니면 무엇이든 읽기 전에 거부한다 — 실제 사용자 대화를
생성 모델에 다시 보내지 않기 위해서다. 스토리 방만 다룬다.

현행 갈래가 덤프와 프롬프트·지시문 둘 다 바이트까지 같아야 어느 갈래든 부른다. 모든 턴이 그 단언을 통과해야 호출을
시작한다. 현행 갈래의 세트는 그 턴 사용자 메시지보다 먼저 게시된 것 중 가장 최신이라, 측정 뒤 게시된 세트 때문에 덤프가
안 맞을 일은 없다. 다만 게시 시각이 턴보다 늦게 찍힌 세트(원본 게시 직후 복사한 마이그레이션 등)는 고르지 못해 그 턴이
거부되거나 덤프와 안 맞는다. 그때는 `--window-set <세트 id>` 로 현행 갈래의 세트를 지정한다 — 그 세트의 레인·모델이 그
턴의 생성 모델과 다르면 거부하고, plan 의 `setRule` 이 `window-set` 이 된다. `--set` 은 변형 갈래의 세트만 바꾼다.

출력: `<접두>.window.jsonl` 에 현행 갈래, `<접두>.<갈래 이름>.jsonl` 에 변형 갈래의 plan·call 기록을 붙여 쓴다(쌍 판정이
갈래별 파일을 읽는다). 이번에 부를 갈래 파일에 같은 (턴, 반복, 갈래) 호출이 이미 있으면 부르지 않고 종료 2 다. `--execute`
없으면 호출하지 않고, 호출 수는 `--limit-calls` 하드 상한을, 실제 원가 누적(`--ledger` 의 앞 묶음 포함, 원가를 모르는
호출은 그 모델의 상한 추정)은 `--limit-usd` 를 넘지 않는다(원가 상한은 마지막 한 호출만큼 넘을 수 있다).

종료 코드: 0 정상 · 1 입력 파일 없음 · 2 단언 실패·거부된 턴(방이 없는 것도 거부다)·이미 부른 호출(호출 0), 인자 오류
(`--room`·`--window-set` 이 UUID 가 아닌 것 포함)도 argparse 가 2 · 3 장부가 이미 원가 상한 이상.
"""

import argparse
import asyncio
import json
import re
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.core.config import settings
from api.llm.chat_models import ChatModelId
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from replay.assemble import ArmSpec, GenerationInput, TurnAssembly, assemble_turn, plan_record
from replay.budget import CallBudget, ledger_paths, sum_ledger
from replay.calls import capture_usage, run_calls
from replay.local_db import ensure_local_database
from replay.logs import ReplayRefusedError, load_driver_logs
from replay.swap import load_swap_table

_ARM_NAME = re.compile(r"[\w.-]+")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="측정한 방의 지난 턴을 같은 입력으로 다시 생성한다")
    ap.add_argument("--room", type=uuid.UUID, required=True)
    ap.add_argument("--turn", type=int, action="append", required=True, help="턴 번호(서버 턴 수 +1, 여럿 가능)")
    ap.add_argument("--dump", required=True, help="서버 프롬프트 덤프(PROMPT_DUMP_PATH)")
    ap.add_argument("--log", required=True, help="드라이버 --log")
    ap.add_argument("--snapshot-log", required=True, help="드라이버 --snapshot-log")
    ap.add_argument(
        "--window-set",
        type=uuid.UUID,
        help="현행 갈래의 세트 id — 시각 규칙(턴 이전 게시 최신) 대신 쓴다. 레인·모델이 그 턴과 같아야 한다",
    )
    ap.add_argument("--set", help="세트 축: 세트 id 또는 draft((레인, 모델)의 초안)")
    ap.add_argument("--model", choices=list(get_args(ChatModelId)), help="모델 축(그 모델의 지금 활성 세트)")
    ap.add_argument("--version", help="작품 버전 축: 같은 작품의 content_version_id")
    ap.add_argument("--swap-table", help="치환 표 축: 치환 표 JSON")
    ap.add_argument("--arm", help="변형 갈래 이름(축을 줄 때 필수) — 출력 파일 이름과 기록의 arm")
    ap.add_argument("--skip-window-calls", action="store_true", help="현행 갈래는 단언에만 쓰고 변형 갈래만 부른다")
    ap.add_argument("--prompt-out", help="만든 프롬프트를 이 접두 경로에 저장(<접두>.tNNN.<갈래>.txt)")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--limit-calls", type=int, required=True, help="이 실행의 실호출 하드 상한")
    ap.add_argument("--limit-usd", type=float, help="장부 포함 실제 원가 누적 상한(달러)")
    ap.add_argument("--ledger", help="앞 묶음 호출 기록 glob(재귀 **) — 실제 원가를 상한에 넣는다")
    ap.add_argument("--out", required=True, help="출력 접두 경로")
    ap.add_argument("--execute", action="store_true", help="LLM 을 실제로 부른다(비용이 든다)")
    return ap


def arm_from_args(ap: argparse.ArgumentParser, args: argparse.Namespace) -> ArmSpec | None:
    """축은 하나만 받는다 — 두 축을 함께 바꾸면 응답 차이가 어느 쪽 때문인지 가릴 수 없다. 예외는 세트와 모델이다: 초안은
    (레인, 모델)마다 있어 모델을 함께 줘야 고를 수 있다(세트가 이기고 갈래는 `set`)."""
    axes = [name for name in ("set", "model", "version", "swap_table") if getattr(args, name) is not None]
    if not axes:
        if args.arm is not None:
            ap.error("--arm 은 변형 축(--set·--model·--version·--swap-table)과 함께만 준다")
        if args.skip_window_calls:
            ap.error("--skip-window-calls 는 변형 축과 함께만 준다")
        return None
    if len(axes) > 1 and set(axes) != {"set", "model"}:
        ap.error(f"변형 축은 하나만 준다(--set 과 --model 은 함께 줄 수 있다): {axes}")
    if args.arm is None:
        ap.error("변형 축을 주면 --arm 으로 갈래 이름을 붙인다")
    if not _ARM_NAME.fullmatch(args.arm) or args.arm == "window":
        ap.error(f"갈래 이름은 글자·숫자·._- 로만, window 는 쓸 수 없다: {args.arm}")
    model: ChatModelId | None = args.model
    if args.set is not None:
        draft = args.set == "draft"
        try:
            set_id = None if draft else uuid.UUID(args.set)
        except ValueError:
            ap.error(f"--set 은 세트 id 또는 draft: {args.set}")
        return ArmSpec(variant="set", arm=args.arm, set_id=set_id, set_draft=draft, model=model)
    if model is not None:
        return ArmSpec(variant="model", arm=args.arm, model=model)
    if args.version is not None:
        try:
            version_id = uuid.UUID(args.version)
        except ValueError:
            ap.error(f"--version 은 content_version_id: {args.version}")
        return ArmSpec(variant="version", arm=args.arm, version_id=version_id)
    try:
        slots = load_swap_table(Path(args.swap_table))
    except (OSError, ValueError, KeyError) as exc:
        ap.error(f"치환 표를 읽지 못했다: {exc}")
    return ArmSpec(variant="swap", arm=args.arm, swap=tuple(slots))


def parse_args(argv: list[str] | None) -> tuple[argparse.Namespace, ArmSpec | None]:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.reps < 1:
        ap.error("--reps 는 1 이상")
    if args.limit_calls < 0:
        ap.error("--limit-calls 는 0 이상")
    if len(set(args.turn)) != len(args.turn):
        ap.error(f"같은 --turn 을 두 번 줬다: {args.turn}")
    return args, arm_from_args(ap, args)


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _taken_calls(files: dict[str, Path], turns: set[int], reps: int) -> list[tuple[int, int, str, str]]:
    """이번에 부를 갈래 파일에 이미 있는 (턴, 반복, 갈래 축, 갈래 이름) 호출. 쌍 판정은 (턴, 반복)으로 짝을 지으므로 같은
    칸에 둘이 있으면 어느 것과 짝지을지 정해지지 않는다."""
    taken: list[tuple[int, int, str, str]] = []
    for path in files.values():
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line) if line.strip() else {}
            if record.get("kind") == "call" and record.get("turn") in turns and record.get("rep", reps) < reps:
                taken.append((record["turn"], record["rep"], record["variant"], record["arm"]))
    return taken


async def run(
    args: argparse.Namespace,
    arm: ArmSpec | None,
    db: AsyncSession,
    *,
    client_factory: Callable[[], LLMClient] = get_llm_client,
) -> int:
    """CLI 본체. 세션은 부른 쪽이 연 것을 받고 그 세션에 commit·rollback 을 하지 않는다. LLM 클라이언트는 실제로 부를 때만
    만든다 — 시험 실행에서는 만들지도 않는다."""
    room_id: uuid.UUID = args.room
    for name in ("dump", "log", "snapshot_log"):
        if not Path(getattr(args, name)).is_file():  # noqa: ASYNC240 — 한 번 쓰는 CLI
            print(f"파일이 없다: --{name.replace('_', '-')} {getattr(args, name)}")
            return 1
    logs = load_driver_logs(Path(args.log), Path(args.snapshot_log), room_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    files = {"window": Path(f"{out}.window.jsonl")}
    if arm is not None:
        files[arm.arm] = Path(f"{out}.{arm.arm}.jsonl")

    calling = [name for name in files if not (args.skip_window_calls and name == "window")]
    taken = _taken_calls({name: files[name] for name in calling}, set(args.turn), args.reps)
    if taken:
        print(f"출력 파일에 같은 (턴, 반복, 갈래) 호출이 이미 있다 — 붙여 쓰면 한 칸에 응답이 둘이 된다: {taken[:5]}")
        return 2

    def sink(record: dict[str, Any]) -> None:
        # 상한 기록은 어느 갈래 파일에서 읽어도 멈춘 까닭이 보이게 모든 파일에 남긴다.
        targets = files.values() if record["kind"] != "call" else [files[record["arm"]]]
        for path in targets:
            _append(path, record)

    def called(assembly: TurnAssembly) -> list[GenerationInput]:
        return [i for i in assembly.inputs if not (args.skip_window_calls and i.variant == "window")]

    assemblies: list[TurnAssembly] = []
    failed: list[int] = []
    for turn in args.turn:
        try:
            assembly = await assemble_turn(
                db,
                room_id=room_id,
                turn=turn,
                logs=logs,
                dump=Path(args.dump),
                arm=arm,
                window_set_id=args.window_set,
            )
        except ReplayRefusedError as refused:
            sink(
                {"kind": "plan", "roomId": str(room_id), "turn": turn, "execute": args.execute, "refused": str(refused)}
            )
            print(json.dumps({"turn": turn, "refused": str(refused)}, ensure_ascii=False))
            failed.append(turn)
            continue
        plan = plan_record(assembly, execute=args.execute, reps=args.reps, called=called(assembly))
        sink(plan)
        print(json.dumps({"turn": turn, "passed": plan["passed"], "checks": plan["checks"]}, ensure_ascii=False))
        if args.prompt_out:
            for item in assembly.inputs:
                Path(f"{args.prompt_out}.t{turn:03d}.{item.arm}.txt").write_text(item.prompt, encoding="utf-8")  # noqa: ASYNC240 — 한 번 쓰는 CLI
        if not assembly.passed:
            failed.append(turn)
        assemblies.append(assembly)
    if failed:
        print(f"단언 실패·거부 턴 {failed} — 되살린 조립이나 변형 갈래를 믿을 수 없어 실행하지 않는다")
        return 2
    inputs = [item for assembly in assemblies for item in called(assembly)]
    spent = sum_ledger(ledger_paths(args.ledger)).charged_usd if args.ledger else 0.0
    planned = min(len(inputs) * args.reps, args.limit_calls)
    print(json.dumps({"turns": len(args.turn), "plannedCalls": planned, "ledgerChargedUsd": round(spent, 6)}))
    if not args.execute:
        print("시험 실행 — LLM 을 부르지 않았다(--execute 로 실행)")
        return 0
    if args.limit_usd is not None and spent >= args.limit_usd:
        print(f"장부 누적 ${spent:.4f} 가 이미 상한 ${args.limit_usd} 이상이다 — 부르지 않는다")
        return 3
    client = client_factory()
    budget = CallBudget(args.limit_calls, usd_limit=args.limit_usd, spent_usd=spent)
    with capture_usage() as sent:
        await run_calls(
            client,
            sent,
            inputs,
            reps=args.reps,
            budget=budget,
            user_id=assemblies[0].user_id,
            room_id=room_id,
            sink=sink,
        )
    print(json.dumps({"calls": budget.used, "cumulativeChargedUsd": round(budget.spent_usd, 6)}))
    return 0


async def _main(args: argparse.Namespace, arm: ArmSpec | None) -> int:
    # 전역 엔진은 쓰지 않는다 — 처음 쓴 이벤트 루프에 묶이는 풀이라, 실행마다 새 루프를 여는 도구는 연결을 남기지 않는
    # 엔진을 따로 연다. 이 세션은 읽기만 하고 끝에 되돌린다.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as db:
            try:
                return await run(args, arm, db)
            finally:
                await db.rollback()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    # 운영 DB 거부를 무엇보다 먼저 건다 — 인자 검사 전이라도 DB 가 로컬이 아니면 이 도구를 쓸 일이 없다.
    ensure_local_database(settings.database_url, tool="generation_replay.py")
    args, arm = parse_args(argv)
    return asyncio.run(_main(args, arm))


if __name__ == "__main__":
    sys.exit(main())
