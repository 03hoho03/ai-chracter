"""소설 작업 행의 호출 기록(`novel_jobs.llm_calls`)으로 작업 종류 × 모델별 원가 분포를 찍는다. 읽기 전용 트랜잭션에서 SELECT 만 한다.

    # 운영 VM — 돌고 있는 api 컨테이너 안에서(DATABASE_URL 이 이미 들어 있다)
    cd /opt/ddona/app && sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \\
        exec -T api_$(sudo bash ops/active-color.sh) python scripts/novel_job_cost_report.py --from 2026-10-20 --to 2026-10-26

    # 로컬
    cd apps/api && uv run --env-file .env python scripts/novel_job_cost_report.py --days 7

옵션:
- `--from`/`--to` KST 날짜(양끝 포함, 작업 행의 `created_at` 기준). 생략하면 `--days`(기본 1 = 오늘)만큼 거슬러 오늘까지.
- `--kind` 작업 종류(`novel_jobs.kind` — `chapter_generate`·`ai_edit` 등), `--model` 작업에 적힌 글쓰기 모델(`novel_jobs.model`)과 같은
  행만.

읽는 법:
- 행 하나가 작업 하나이고, 작업 원가는 그 행의 호출 원소 합이다. 연쇄 생성은 부모 행(경계 제안)과 자식 행(화 생성)이 각자 제 호출만
  가지므로 더해도 이중 계산이 아니다. 모델 칸이 생기기 전 작업은 모델이 `-` 다. 묶음 재검사는 이미 끝난 여러 문단 수정 작업 행에
  덧붙으므로 그 작업의 원가에 들어간다.
- 🔴 `llm_usage_report.py`(일 단위 사용량 집계)와 더하지 않는다 — 일 단위 집계는 이 기록에 남는 호출도 같은 자리에서 함께
  세므로(`llm/client.py` 의 `collect_usage`) 더하면 그 몫이 두 번 들어간다. `turn_cost_report.py`(채팅 턴 기록)와는 겹치지 않는다.
- 합계는 실제보다 낮게 나온다: 소설 삭제·탈퇴로 지운 작업 행은 기록째 없고, 이 칸이 생기기 전 작업과 기록하지 못한 호출(프로세스
  사망 만료, 연쇄 부모의 시간 상한에 취소된 자식, 재검사의 503·409 갈래 — `novelize/call_records.py` 머리 주석)은 `[]` 이다.
- 단가는 `llm/pricing.py` 의 단가표다(그 모듈의 `call_cost` — 턴 보고와 같은 함수). 표에 없는 모델의 원소는 `unpriced` 로 세고 합계에서 빼며, 그런
  원소가 하나라도 있는 작업은 작업별 분포에서 빼고 따로 센다(`unpriced_jobs`). 사용량 없이 끝난 원소(안전 차단·전송 오류·쿼터
  소진·시간 상한 취소 — 공급자 쪽에서는 과금됐을 수 있다)는 `missing` 으로 세고 0 으로 친다.
- `call failures` 줄은 원소의 호출 단위 실패 사유 분포다. 호출 뒤 소설 쪽 판정 실패(거절·형식·낡음)는 원소가 아니라 작업 행의 실패
  사유라 여기 없고, `failed` 열에 든다.
- `charged`·`refunded` 는 작업 행의 차감액·환불액 합(클로버)이다. 금액을 다시 계산하지 않는다.
"""

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.rate_limit import KST
from api.db.models.novel import NovelJob
from api.db.session import async_session_factory
from api.llm.pricing import call_cost

# 기간 해석·백분위수는 턴 보고와 같은 규칙이라 그 함수를 그대로 쓴다.
from turn_cost_report import _date_range, percentile


@dataclass(frozen=True)
class JobRow:
    kind: str
    model: str | None
    status: str
    failure_code: str | None
    charged_amount: int
    refunded_amount: int | None
    llm_calls: list[dict[str, Any]]


@dataclass(frozen=True)
class GroupSummary:
    kind: str
    model: str
    jobs: int
    succeeded: int
    failed: int
    calls: int
    missing: int
    unpriced: int
    unpriced_jobs: int
    total_usd: float
    p50_usd: float | None
    p90_usd: float | None
    max_usd: float | None
    charged: int
    refunded: int


@dataclass
class Summary:
    groups: list[GroupSummary]
    failures: dict[str, int] = field(default_factory=dict)


def summarize(rows: list[JobRow]) -> Summary:
    by_group: dict[tuple[str, str], list[JobRow]] = {}
    failures: Counter[str] = Counter()
    for row in rows:
        by_group.setdefault((row.kind, row.model or "-"), []).append(row)
        failures.update(str(call["failure"]) for call in row.llm_calls if call.get("failure") is not None)
    groups = []
    for (kind, model), members in sorted(by_group.items()):
        job_usd: list[float] = []
        calls = missing = unpriced = unpriced_jobs = 0
        total = 0.0
        for row in members:
            costs = [call_cost(call) for call in row.llm_calls]
            calls += len(costs)
            missing += sum(cost.missing_tokens for cost in costs)
            priced = [cost.usd for cost in costs if cost.usd is not None]
            unpriced += len(costs) - len(priced)
            total += sum(priced)
            if len(priced) < len(costs):
                unpriced_jobs += 1
            else:
                job_usd.append(sum(priced))
        groups.append(
            GroupSummary(
                kind=kind,
                model=model,
                jobs=len(members),
                succeeded=sum(row.status == "succeeded" for row in members),
                failed=sum(row.status == "failed" for row in members),
                calls=calls,
                missing=missing,
                unpriced=unpriced,
                unpriced_jobs=unpriced_jobs,
                total_usd=total,
                p50_usd=percentile(job_usd, 0.5),
                p90_usd=percentile(job_usd, 0.9),
                max_usd=max(job_usd, default=None),
                charged=sum(row.charged_amount for row in members),
                refunded=sum(row.refunded_amount or 0 for row in members),
            )
        )
    return Summary(groups, dict(failures))


def _usd(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def format_report(summary: Summary) -> str:
    head = [
        "kind",
        "model",
        "jobs",
        "ok",
        "failed",
        "calls",
        "missing",
        "unpriced",
        "total_usd",
        "p50_usd",
        "p90_usd",
        "max_usd",
        "charged",
        "refunded",
    ]
    body = [
        [
            g.kind,
            g.model,
            str(g.jobs),
            str(g.succeeded),
            str(g.failed),
            str(g.calls),
            str(g.missing),
            f"{g.unpriced} ({g.unpriced_jobs} jobs)" if g.unpriced else "0",
            _usd(g.total_usd),
            _usd(g.p50_usd),
            _usd(g.p90_usd),
            _usd(g.max_usd),
            str(g.charged),
            str(g.refunded),
        ]
        for g in summary.groups
    ]
    widths = [max(len(line[i]) for line in [head, *body]) for i in range(len(head))]
    lines = [
        "  ".join(
            cell.ljust(w) if i < 2 else cell.rjust(w) for i, (cell, w) in enumerate(zip(line, widths, strict=True))
        )
        for line in [head, *body]
    ]
    if summary.failures:
        lines.append("")
        lines.append("call failures " + " ".join(f"{name}={count}" for name, count in sorted(summary.failures.items())))
    return "\n".join(lines)


async def read_jobs(
    session: AsyncSession, start: date, end: date, *, kind: str | None, model: str | None
) -> list[JobRow]:
    """KST `start` 0시부터 `end` 다음 날 0시 전까지 만든 작업 행. 호출 기록 칸은 지연 로드 칸이라 칸을 골라 읽는다."""
    query = select(
        NovelJob.kind,
        NovelJob.model,
        NovelJob.status,
        NovelJob.failure_code,
        NovelJob.charged_amount,
        NovelJob.refunded_amount,
        NovelJob.llm_calls,
    ).where(
        NovelJob.created_at >= datetime.combine(start, time.min, tzinfo=KST),
        NovelJob.created_at < datetime.combine(end + timedelta(days=1), time.min, tzinfo=KST),
    )
    if kind is not None:
        query = query.where(NovelJob.kind == kind)
    if model is not None:
        query = query.where(NovelJob.model == model)
    rows = await session.execute(query.order_by(NovelJob.created_at, NovelJob.id))
    return [JobRow(*row) for row in rows.tuples()]


async def load_jobs(start: date, end: date, *, kind: str | None, model: str | None) -> list[JobRow]:
    async with async_session_factory() as session, session.begin():
        # 첫 문장이어야 이 트랜잭션에 걸린다 — 운영 DB 에서 도는 스크립트라 실수로라도 쓰지 못하게.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return await read_jobs(session, start, end, kind=kind, model=model)


async def _main(args: argparse.Namespace) -> None:
    start, end = _date_range(args)
    rows = await load_jobs(start, end, kind=args.kind, model=args.model)
    filters = "".join(f" {name}={value}" for name, value in (("kind", args.kind), ("model", args.model)) if value)
    print(f"novel_jobs {start} ~ {end} (KST){filters}")
    print(format_report(summarize(rows)) if rows else "(기록 없음)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_", type=date.fromisoformat)
    parser.add_argument("--to", type=date.fromisoformat)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--kind")
    parser.add_argument("--model")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
