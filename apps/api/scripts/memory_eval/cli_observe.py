"""측정 하네스 CLI 의 관측 묶음 — 요약 `[관계]` 칸 비율과 판정 이벤트 로그 분포. 둘 다 DB 를 읽기 전용으로만 연다.

접속은 실행 명령의 `DATABASE_URL`(로컬 호스트만) 서버이고, DB 이름은 인자로 고른다 — 측정 DB 가 여러 개라서다. 설정 모듈을
읽지 않으므로 `.env` 없이 돈다. 표준출력과 결과 파일에는 개수·비율만 있고 id·글은 없다."""

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from memory_eval.cli_common import _print, _write


def _base_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL(접속할 로컬 서버)을 실행 명령에 줘야 한다")
    return url


def _source(raw: str) -> tuple[str, list[str]]:
    label, sep, names = raw.partition("=")
    databases = [name for name in names.split(",") if name]
    if not sep or not label or not databases or label == "*":
        raise argparse.ArgumentTypeError(f"출처는 이름=DB[,DB...] 꼴이다(이름 '*' 는 합계 자리라 못 쓴다): {raw!r}")
    return label, databases


def _when(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise argparse.ArgumentTypeError(f"시각에 시간대를 붙인다(예: 2026-10-24T08:45:25+00:00): {raw!r}")
    return value


def cmd_relation_share(args: argparse.Namespace) -> int:
    """출처마다 DB 들의 요약 스냅샷을 읽어 `[관계]` 칸 비율을 레인·모델별로 집계한다."""
    from memory_eval.relation_share import load_snapshots, relation_share
    from memory_eval.stat_event_dist import read_only_connection

    url = _base_url()

    async def run() -> list[tuple[str, list[dict[str, Any]]]]:
        sources: list[tuple[str, list[dict[str, Any]]]] = []
        for label, databases in args.source:
            snapshots: list[dict[str, Any]] = []
            for database in databases:
                async with read_only_connection(url, database) as connection:
                    snapshots += await load_snapshots(connection)
            sources.append((label, snapshots))
        return sources

    report = relation_share(asyncio.run(run()))
    report["databases"] = {label: databases for label, databases in args.source}
    _write(args.out, report)
    _print(
        {
            "duplicatesSkipped": report["duplicatesSkipped"],
            "groups": {
                name: {
                    "snapshots": g["snapshots"],
                    "rooms": g["rooms"],
                    "presentRate": g["presentRate"],
                    "nonEmptyRate": g["nonEmptyRate"],
                    "shareMean": g["share"]["mean"],
                    "sharePooled": g["share"]["pooled"],
                    "lastShareMean": g["last"]["share"]["mean"],
                }
                for name, g in report["groups"].items()
            },
        }
    )
    return 0


def cmd_stat_event_dist(args: argparse.Namespace) -> int:
    """턴 기록의 판정 이벤트 로그 분포. `--print-sql` 은 DB 에 붙지 않고 같은 SQL 만 낸다(운영 psql 블록용)."""
    from memory_eval.stat_event_dist import read_only_connection, stat_event_distribution, stat_events_sql

    if args.print_sql:
        print(stat_events_sql(args.since, args.until))
        return 0
    if args.out is None:
        raise SystemExit("--out 을 줘야 한다(--print-sql 이 아니면)")
    url = _base_url()

    async def run() -> dict[str, Any]:
        async with read_only_connection(url, args.database) as connection:
            return await stat_event_distribution(connection, since=args.since, until=args.until)

    report = asyncio.run(run())
    _write(args.out, report)
    _print(report)
    return 0


def register(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    p = sub.add_parser("relation-share", help="요약 [관계] 칸 비율 — 레인·모델별(DB 읽기 전용)")
    p.add_argument(
        "--source",
        type=_source,
        action="append",
        required=True,
        help="이름=DB[,DB...] (여러 번). 준 순서로 읽고, 앞 출처에 이미 있는 스냅샷은 뒤 출처에서 세지 않는다",
    )
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_relation_share)

    p = sub.add_parser("stat-event-dist", help="판정 이벤트 로그(chat_turns.stat_events) 분포(DB 읽기 전용)")
    p.add_argument("--database", help="같은 서버의 DB 이름(없으면 DATABASE_URL 의 DB)")
    p.add_argument("--since", type=_when, required=True, help="기준 시각(포함, 시간대 필수)")
    p.add_argument("--until", type=_when, help="끝 시각(제외, 시간대 필수)")
    p.add_argument("--print-sql", action="store_true", help="집계 SQL 만 낸다(DB 에 붙지 않는다)")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_stat_event_dist)
