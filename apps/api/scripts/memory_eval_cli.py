"""장기 기억 측정 하네스 CLI.

    cd apps/api
    uv run --env-file .env python scripts/memory_eval_cli.py --run <원자료 폴더> [--data-dir <측정 데이터 폴더>] <명령> ...

전역 인자(`--run`·`--data-dir`·`--status-dir`·`--cap-usd`·`--halt-usd`·`--bundle`·`--expect-head`)는 하위 명령 **앞에** 준다. 대본·심기 표·
명세 같은 측정 데이터는 공개 저장소에 두지 않으므로 기본 경로가 없고, 데이터를 읽는 명령은 `--data-dir` 를 요구한다.

DB 를 쓰는 명령은 실행 명령의 `DATABASE_URL` 로 작업 DB(이름 `lm_eval_` 로 시작)를 준다 — `.env` 의 값보다 명령의 값이 이긴다.
유료 호출이 날 수 있는 명령(insert·probe·prototype-facts·embed-run, 판정 묶음의 judge·prototype-extract·judge-agreement 등)은 `--dry-run` 이 기본 동작이고, 실제 호출은 `--allow-paid`
를 명시해야 한다(원장 상한을 본 뒤). 가짜 LLM(`--fake-llm`)은 절차 확인용이다.

하위 명령은 묶음 모듈마다 등록한다(`COMMAND_GROUPS`). 묶음은 공용 모듈(`memory_eval.cli_common`)만 함께 쓰고 서로 import 하지
않는다 — 인프라 묶음은 판정 모듈 없이 돈다.

오래 도는 명령은 `--status-dir` 를 주면 시작할 때 `status.json`(명령·pid·시작 시각·상태)을 쓰고, 끝나면 상태를 고친 뒤 완료
표지 `done.<종료 코드>` 를 만든다. 밖에서는 표지 파일이 생겼는지로 끝을 안다(출력 마지막 줄을 견주지 않는다).

종료 코드: 0 정상 · 1 검사 위반(check-script) · 2 인자·환경 거부 · 20 원장 상한 · 130 Ctrl-C 중단(`--status-dir` 를 주면
상태 `interrupted` 와 표지 `done.130`)."""

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_eval import cli_impression, cli_infra, cli_judge, cli_observe, head_check
from memory_eval.cli_common import add_global_args, read_status, update_status, write_status
from memory_eval.ledger import EXIT_BUDGET, BudgetExceededError

# Ctrl-C 로 멈춘 실행의 종료 코드 — 셸이 SIGINT 로 끝난 프로세스에 주는 값(128 + 2)과 같다.
EXIT_INTERRUPTED = 130

Register = Callable[["argparse._SubParsersAction[argparse.ArgumentParser]"], None]
# 하위 명령 묶음의 등록 함수. 판정·집계 묶음은 인프라 묶음의 두 명령에 인자를 덧붙이므로 인프라 뒤에 둔다.
COMMAND_GROUPS: tuple[Register, ...] = (
    cli_infra.register,
    cli_judge.register,
    cli_impression.register,
    cli_observe.register,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="memory_eval_cli")
    add_global_args(ap)
    sub = ap.add_subparsers(dest="command", required=True)
    for register in COMMAND_GROUPS:
        register(sub)
    return ap


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run(args: argparse.Namespace) -> int:
    try:
        code: int = args.fn(args)
    except BudgetExceededError as stop:
        print(stop)
        return EXIT_BUDGET
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(stop.code, file=sys.stderr)
            return 2
        if isinstance(stop.code, int):
            return stop.code
        return 0 if stop.code is None else 1
    return code


def _checked_run(args: argparse.Namespace, status_dir: Path | None) -> int:
    """측정 커밋을 받았으면(인자 또는 env) 명령 전에 HEAD·작업 트리를 단언하고 그 결과를 상태 파일에 남긴 뒤 명령을 돌린다.
    단언이 실패하면 명령을 돌리지 않고 종료 코드 2."""
    expected = args.expect_head or os.environ.get(head_check.EXPECT_HEAD_ENV)
    if expected:
        try:
            record = head_check.measured_head(head_check.REPO, expected)
        except SystemExit as stop:
            if status_dir is not None:
                update_status(status_dir, {"headCheck": {"ok": False, "expected": expected, "reason": str(stop.code)}})
            print(stop.code, file=sys.stderr)
            return 2
        if status_dir is not None:
            update_status(status_dir, {"headCheck": record})
    return _run(args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    check_args = getattr(args, "check_args", None)
    if check_args is not None:
        # 인자 사이의 모순은 인자 오류(종료 코드 2, 사용법 출력)로 멈춘다 — 명령 본문의 문자열 종료와 달리 부른 쪽에 예외로 닿는다.
        check_args(parser, args)
    status_dir: Path | None = args.status_dir
    if status_dir is None:
        return _checked_run(args, None)
    status: dict[str, Any] = {
        "command": args.command,
        "argv": list(sys.argv[1:] if argv is None else argv),
        "pid": os.getpid(),
        "startedAt": _now(),
        "state": "running",
    }
    for stale in status_dir.glob("done.*"):
        stale.unlink()
    write_status(status_dir, status)
    code = 1
    state = "done"
    try:
        code = _checked_run(args, status_dir)
    except KeyboardInterrupt:
        # 명령이 정리(돌던 작업이 끝나기를 기다림)를 마친 뒤에야 여기 온다 — 상태는 그 뒤에 쓴다.
        code, state = EXIT_INTERRUPTED, "interrupted"
    finally:
        # 예외로 끝나도(코드 1) 표지를 남긴다 — 표지가 없으면 지켜보는 쪽이 끝을 모르고 기다린다.
        # 명령이 진행 중에 더한 칸(작업자별 진행 등)은 남긴다.
        write_status(
            status_dir, {**read_status(status_dir), **status, "state": state, "exitCode": code, "endedAt": _now()}
        )
        (status_dir / f"done.{code}").write_text(_now() + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
