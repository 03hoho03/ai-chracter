"""턴 기록(`chat_turns.llm_calls`)으로 호출 위치별·턴별 원가 분포를 찍는다. 읽기 전용 트랜잭션에서 SELECT 만 한다.

    # 운영 VM — 돌고 있는 api 컨테이너 안에서(DATABASE_URL 이 이미 들어 있다)
    cd /opt/ddona/app && sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \\
        exec -T api_$(sudo bash ops/active-color.sh) python scripts/turn_cost_report.py --from 2026-10-16 --to 2026-10-22

    # 로컬
    cd apps/api && uv run --env-file .env python scripts/turn_cost_report.py --days 7

옵션:
- `--from`/`--to` KST 날짜(양끝 포함, 턴 기록의 `created_at` 기준). 생략하면 `--days`(기본 1 = 오늘)만큼 거슬러 오늘까지.
- `--chat-model` 그 턴의 글쓰기 모델(`chat_turns.chat_model` — `gemini`·`opus` 등)과 같은 행만.

읽는 법:
- 턴 기록에는 그 응답의 생성·판정 호출과, 임베딩 회상을 켠 턴의 맨 앞 질의 임베딩 한 칸만 있다. 턴 뒤 백그라운드 — 요약 접기,
  장면·사실 추출, 임베딩 채우기 — 는 없다. 그 원가는 `llm_usage_report.py`(일 단위 사용량 집계)로 본다. 🔴 두 표를 더하지
  않는다 — 일 단위 집계는 턴 기록에 남는 호출도 같은 자리에서 함께 세므로(`llm/client.py` 의 `collect_usage`) 더하면 그 몫이
  두 번 들어간다.
- 행 하나가 응답 하나다. 재생성·수정 행은 각자 실제로 부른 호출이라 원가는 행마다 더해도 이중 계산이 아니다(행마다 같은
  턴의 효과를 다시 적는 스탯 변화와 다르다). 방 삭제·초기화로 지운 행과 미리보기 턴은 없어, 합계는 실제보다 낮게 나온다.
- 질의 임베딩 칸은 `{callSite, model, dims, promptTokens, latencyMs, outcome}` 모양이라 캐시·출력 칸이 없다 — 입력만 친다.
- `first token ms` 두 줄은 생성 칸의 첫 글자 지연 분포다. `(turn start)` 는 턴 시작(생성 프롬프트 조립 직전)부터 잰
  `firstTokenMs` 라 기억 기능의 조립·질의 임베딩 지연까지 품고, `(stream start)` 는 생성 스트림을 연 때부터 잰
  `streamFirstTokenMs` 라 생성 호출(공급자 왕복) 쪽 지연이다 — 공급자까지의 네트워크 왕복과 백엔드 클라이언트 첫 생성이
  여기 든다. 글 없이 끝난 생성과 이 키를 쓰기 전의 행은 키가 없어 빠진다. 모델마다 지연이 크게 달라 섞으면 읽기
  어려우므로 `--chat-model` 로 나눠 본다.
- 단가는 `llm/pricing.py` 의 단가표다. 표에 없는 모델의 호출은 `unpriced` 로 세고 합계에서 빼며, 그런 호출이 하나라도 있는
  턴은 턴별 분포에서 빼고 따로 센다(낮게 보이는 합계가 분포에 섞이지 않게).
- 입력 토큰을 보고하지 않은 호출(이미지가 실린 판정, 시간 초과로 끊은 질의 임베딩)은 `missing` 으로 세고 보고된 칸만 친다 —
  그 몫은 낮게 보인다. 끊은 질의 임베딩도 공급자 쪽에서는 과금됐을 수 있다.
"""

import argparse
import asyncio
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.rate_limit import KST
from api.db.models.chat import ChatTurn
from api.db.session import async_session_factory
from api.llm.pricing import estimate_cost_usd


@dataclass(frozen=True)
class CallCost:
    call_site: str
    model: str
    # 단가표에 없는 모델이면 None.
    usd: float | None
    missing_tokens: bool


@dataclass(frozen=True)
class SiteSummary:
    call_site: str
    model: str
    calls: int
    missing_tokens: int
    unpriced: int
    total_usd: float
    p50_usd: float | None
    p90_usd: float | None
    max_usd: float | None


@dataclass
class Summary:
    sites: list[SiteSummary]
    turns: int
    unpriced_turns: int
    turn_usd: list[float]
    query_outcomes: dict[str, int] = field(default_factory=dict)
    query_latency_ms: list[int] = field(default_factory=list)
    first_token_ms: list[int] = field(default_factory=list)
    stream_first_token_ms: list[int] = field(default_factory=list)


def _tokens(call: dict[str, Any], key: str) -> int:
    value = call.get(key)
    return value if isinstance(value, int) else 0


def call_cost(call: dict[str, Any]) -> CallCost:
    """호출 칸 하나의 원가. 질의 임베딩 칸처럼 없는 칸은 0 으로 친다."""
    model = str(call.get("model"))
    usd = estimate_cost_usd(
        model,
        input_tokens=_tokens(call, "promptTokens"),
        cached_tokens=_tokens(call, "cachedTokens"),
        cache_write_tokens=_tokens(call, "cacheWriteTokens"),
        output_tokens=_tokens(call, "outputTokens"),
        thoughts_tokens=_tokens(call, "thoughtsTokens"),
    )
    return CallCost(str(call.get("callSite")), model, usd, missing_tokens=not isinstance(call.get("promptTokens"), int))


def percentile(values: list[float], fraction: float) -> float | None:
    """가장 가까운 순위 백분위수(보간 없음). 빈 목록이면 None."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(fraction * len(ordered)), 1) - 1]


def summarize(turns: list[list[dict[str, Any]]]) -> Summary:
    by_site: dict[tuple[str, str], list[CallCost]] = {}
    turn_usd: list[float] = []
    unpriced_turns = 0
    outcomes: Counter[str] = Counter()
    latencies: list[int] = []
    first_tokens: list[int] = []
    stream_first_tokens: list[int] = []
    for calls in turns:
        costs = [call_cost(call) for call in calls]
        for call, cost in zip(calls, costs, strict=True):
            by_site.setdefault((cost.call_site, cost.model), []).append(cost)
            # 질의 임베딩 칸만 결과·지연 칸을 가진다.
            if "outcome" in call:
                outcomes[str(call["outcome"])] += 1
                if isinstance(call.get("latencyMs"), int):
                    latencies.append(call["latencyMs"])
            # 생성 칸만 첫 글자 지연을 가진다 — 질의 임베딩의 결과 칸 조건과 섞지 않는다(생성 칸에는 `outcome` 이 없다).
            if isinstance(call.get("firstTokenMs"), int):
                first_tokens.append(call["firstTokenMs"])
            if isinstance(call.get("streamFirstTokenMs"), int):
                stream_first_tokens.append(call["streamFirstTokenMs"])
        if any(cost.usd is None for cost in costs):
            unpriced_turns += 1
        else:
            turn_usd.append(sum(cost.usd for cost in costs if cost.usd is not None))
    sites = []
    for (call_site, model), costs in sorted(by_site.items()):
        priced = [cost.usd for cost in costs if cost.usd is not None]
        sites.append(
            SiteSummary(
                call_site=call_site,
                model=model,
                calls=len(costs),
                missing_tokens=sum(cost.missing_tokens for cost in costs),
                unpriced=len(costs) - len(priced),
                total_usd=sum(priced),
                p50_usd=percentile(priced, 0.5),
                p90_usd=percentile(priced, 0.9),
                max_usd=max(priced, default=None),
            )
        )
    return Summary(
        sites, len(turns), unpriced_turns, turn_usd, dict(outcomes), latencies, first_tokens, stream_first_tokens
    )


def _usd(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def format_report(summary: Summary) -> str:
    head = ["call_site", "model", "calls", "missing", "unpriced", "total_usd", "p50_usd", "p90_usd", "max_usd"]
    body = [
        [
            s.call_site,
            s.model,
            str(s.calls),
            str(s.missing_tokens),
            str(s.unpriced),
            _usd(s.total_usd),
            _usd(s.p50_usd),
            _usd(s.p90_usd),
            _usd(s.max_usd),
        ]
        for s in summary.sites
    ]
    widths = [max(len(line[i]) for line in [head, *body]) for i in range(len(head))]
    lines = [
        "  ".join(
            cell.ljust(w) if i < 2 else cell.rjust(w) for i, (cell, w) in enumerate(zip(line, widths, strict=True))
        )
        for line in [head, *body]
    ]
    priced = summary.turn_usd
    mean = sum(priced) / len(priced) if priced else None
    lines.append("")
    lines.append(
        f"turns {summary.turns} (unpriced {summary.unpriced_turns}) · per-turn usd mean {_usd(mean)}"
        f" p50 {_usd(percentile(priced, 0.5))} p90 {_usd(percentile(priced, 0.9))} max {_usd(max(priced, default=None))}"
    )
    if summary.query_outcomes:
        outcomes = " ".join(f"{name}={count}" for name, count in sorted(summary.query_outcomes.items()))
        latency = summary.query_latency_ms
        lines.append(
            f"query embedding {outcomes} · latency ms p50 {percentile([float(v) for v in latency], 0.5)}"
            f" p90 {percentile([float(v) for v in latency], 0.9)} max {max(latency, default=None)}"
        )
    for label, values in (("turn start", summary.first_token_ms), ("stream start", summary.stream_first_token_ms)):
        if values:
            floats = [float(v) for v in values]
            lines.append(
                f"first token ms ({label}) n {len(values)} p50 {percentile(floats, 0.5)}"
                f" p90 {percentile(floats, 0.9)} max {max(values)}"
            )
    return "\n".join(lines)


async def read_llm_calls(
    session: AsyncSession, start: date, end: date, *, chat_model: str | None
) -> list[list[dict[str, Any]]]:
    """KST `start` 0시부터 `end` 다음 날 0시 전까지 만든 턴 기록의 호출 목록."""
    query = select(ChatTurn.llm_calls).where(
        ChatTurn.created_at >= datetime.combine(start, time.min, tzinfo=KST),
        ChatTurn.created_at < datetime.combine(end + timedelta(days=1), time.min, tzinfo=KST),
    )
    if chat_model is not None:
        query = query.where(ChatTurn.chat_model == chat_model)
    return list((await session.execute(query)).scalars())


async def load_turns(start: date, end: date, *, chat_model: str | None) -> list[list[dict[str, Any]]]:
    async with async_session_factory() as session, session.begin():
        # 첫 문장이어야 이 트랜잭션에 걸린다 — 운영 DB 에서 도는 스크립트라 실수로라도 쓰지 못하게.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return await read_llm_calls(session, start, end, chat_model=chat_model)


def _date_range(args: argparse.Namespace) -> tuple[date, date]:
    today = datetime.now(KST).date()
    end = args.to or today
    start = args.from_ or end - timedelta(days=args.days - 1)
    if end < start:
        raise SystemExit(f"--to({end})가 --from({start})보다 앞이다")
    return start, end


async def _main(args: argparse.Namespace) -> None:
    start, end = _date_range(args)
    turns = await load_turns(start, end, chat_model=args.chat_model)
    print(f"chat_turns {start} ~ {end} (KST)" + (f" chat_model={args.chat_model}" if args.chat_model else ""))
    print(format_report(summarize(turns)) if turns else "(기록 없음)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_", type=date.fromisoformat)
    parser.add_argument("--to", type=date.fromisoformat)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--chat-model")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
