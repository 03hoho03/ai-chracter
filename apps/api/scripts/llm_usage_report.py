"""LLM 호출 사용량 집계(Redis `llm_usage:{KST 날짜}` 해시)를 표로 찍는다. 읽기 전용이다.

    # 운영 VM — 돌고 있는 api 컨테이너 안에서(REDIS_URL 이 이미 들어 있다)
    cd /opt/ddona/app && sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \\
        exec -T api python scripts/llm_usage_report.py --from 2026-10-01 --to 2026-10-07

    # 로컬
    cd apps/api && uv run --env-file .env python scripts/llm_usage_report.py --days 7

옵션:
- `--from`/`--to` KST 날짜(양끝 포함). 생략하면 `--days`(기본 1 = 오늘)만큼 거슬러 오늘까지.
- `--call-site`/`--model` 그 값과 같은 줄만.
- `--by-day` 날짜별 줄로 찍는다. 없으면 기간을 call_site × model 로 합친다.

열 `prompt` 는 SDK 가 입력 토큰을 보고한 호출만의 합이다. 이미지가 실린 호출은 입력 토큰이
비어 `missing` 으로 세지고 `total` 에만 들어간다 — 그 몫의 입력은 `total − candidates − thoughts`
로 읽는다. `cached` 는 SDK 가 보고한 암시 캐시 적중이지 청구 할인이 확인된 값이 아니다.
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta

from api.core.rate_limit import KST
from api.llm.usage_store import UsageRow, read_usage, sum_by_call_site_and_model

_COLUMNS = ("calls", "prompt", "cached", "candidates", "thoughts", "total", "missing")


def _date_range(args: argparse.Namespace) -> tuple[date, date]:
    today = datetime.now(KST).date()
    end = args.to or today
    start = args.from_ or end - timedelta(days=args.days - 1)
    if end < start:
        raise SystemExit(f"--to({end})가 --from({start})보다 앞이다")
    return start, end


def _format(rows: list[UsageRow], *, by_day: bool) -> str:
    head = (["day"] if by_day else []) + ["call_site", "model", *_COLUMNS]
    body = [
        ([str(r.day)] if by_day else []) + [r.call_site, r.model, *(str(getattr(r, c)) for c in _COLUMNS)] for r in rows
    ]
    widths = [max(len(line[i]) for line in [head, *body]) for i in range(len(head))]
    # 문자열 열은 왼쪽, 숫자 열은 오른쪽 정렬.
    text_cols = len(head) - len(_COLUMNS)
    return "\n".join(
        "  ".join(
            cell.ljust(w) if i < text_cols else cell.rjust(w)
            for i, (cell, w) in enumerate(zip(line, widths, strict=True))
        )
        for line in [head, *body]
    )


async def _main(args: argparse.Namespace) -> None:
    start, end = _date_range(args)
    rows = await read_usage(start, end)
    rows = [
        r
        for r in rows
        if (args.call_site is None or r.call_site == args.call_site) and (args.model is None or r.model == args.model)
    ]
    if not args.by_day:
        rows = sum_by_call_site_and_model(rows)
    print(f"llm_usage {start} ~ {end} (KST)")
    print(_format(rows, by_day=args.by_day) if rows else "(기록 없음)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_", type=date.fromisoformat)
    parser.add_argument("--to", type=date.fromisoformat)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--call-site")
    parser.add_argument("--model")
    parser.add_argument("--by-day", action="store_true")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
