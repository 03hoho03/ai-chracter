"""LLM 호출 사용량을 Redis 일 단위 해시에 누적한다.

`gemini_usage`·`bedrock_usage` 로그 줄은 컨테이너가 배포마다 새로 떠서 사라진다. 그래서 같은 숫자를 배포를
넘겨 남기려고 둔다. 키는 `llm_usage:{KST 날짜}` 하나, 필드는 `{call_site}|{model}|{지표}` 이고
값은 HINCRBY 누적이다. 사용자·방 id 는 넣지 않는다 — 개인 단위 이용 기록이 되면 처리방침
항목·보존기간·탈퇴 파기와 엮인다.

지표:
- `calls` 응답을 받은 호출 수(실패·중단 스트림은 `_log_usage` 와 같이 세지 않는다)
- `prompt`·`cached`·`candidates`·`thoughts`·`total` SDK 가 보고한 토큰 합
- `cache_write` 캐시에 새로 쓴 입력 토큰 합(Bedrock 의 Claude 만 보고한다). Claude 는 입력 토큰을 캐시 읽기·쓰기를 뺀 값으로
  보고하지만 `llm/bedrock.py` 가 셋을 더해 `prompt` 에 넣으므로, 모든 모델에서 `prompt` 는 캐시를 포함한 입력 전체이고
  `cached`·`cache_write` 는 그 안의 몫이다
- `missing` 사용량 메타데이터가 없거나 `prompt_token_count` 가 None 인 호출 수. 이미지가 실린
  호출은 입력 토큰이 None 으로 오고 `total` 만 온다 — 입력 원가는 `total − candidates − thoughts`
  로 복원해 읽는다.

날짜는 KST 다(클로버 일일분·레이트리밋과 같은 하루). 기존 어드민 메시지 지표는 UTC 날짜라
나란히 놓으면 9시간 어긋난다.
"""

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from redis.asyncio import Redis

from api.core.rate_limit import KST
from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure

logger = logging.getLogger(__name__)

USAGE_KEY_PREFIX = "llm_usage:"
# 하루 해시 하나가 많아야 call_site 17 × 모델 1~3 × 지표 8 개의 정수라, 400일을 둬도 수 MB 에
# 못 미친다. 모델 전환 전후·월 대비 비교가 40일 같은 짧은 창을 넘기기 쉬워 길게 둔다.
USAGE_RETENTION_SECONDS = 400 * 24 * 60 * 60
# 생성 스트림은 이 기록이 끝나야 `done` 으로 넘어가므로, 이 값이 Redis 장애 때 턴 하나가 더
# 기다리는 상한이다. 앱과 Redis 는 같은 VM 의 도커 네트워크라 정상 왕복은 1ms 안팎이고 새
# 커넥션을 여는 경우도 수 ms 라서 100ms 면 여유가 크다. 공용 클라이언트에 소켓 timeout 이 없어
# 이 상한이 없으면 응답 없는 Redis 가 턴을 무한정 붙잡는다.
RECORD_TIMEOUT_SECONDS = 0.1

_METRICS = ("calls", "prompt", "cached", "cache_write", "candidates", "thoughts", "total", "missing")
_TOKEN_ATTRS = {
    "prompt": "prompt_token_count",
    "cached": "cached_content_token_count",
    "cache_write": "cache_write_token_count",
    "candidates": "candidates_token_count",
    "thoughts": "thoughts_token_count",
    "total": "total_token_count",
}


def usage_key(day: date) -> str:
    return f"{USAGE_KEY_PREFIX}{day.isoformat()}"


def _increments(usage_metadata: object | None) -> dict[str, int]:
    """0 인 지표는 빼고 돌려준다 — 없는 필드는 읽는 쪽이 0 으로 본다(쓰기 명령 수만 준다)."""
    counts = {"calls": 1}
    for metric, attr in _TOKEN_ATTRS.items():
        value = getattr(usage_metadata, attr, None)
        if value:
            counts[metric] = int(value)
    if usage_metadata is None or getattr(usage_metadata, "prompt_token_count", None) is None:
        counts["missing"] = 1
    return counts


async def _write(call_site: str, model: str, usage_metadata: object | None, now: datetime) -> None:
    key = usage_key(now.astimezone(KST).date())
    increments = _increments(usage_metadata)
    # MULTI/EXEC 한 번 왕복이다. 트랜잭션이라 timeout 으로 중간에 끊겨도 지표 일부만 반영된
    # 호출이 생기지 않는다(전부 반영되거나 하나도 안 되거나).
    async with redis_client.pipeline(transaction=True) as pipe:
        for metric, amount in increments.items():
            pipe.hincrby(key, f"{call_site}|{model}|{metric}", amount)
        # 하루 버킷이라 첫 기록 시점에 한 번만 TTL 을 건다. 매번 갱신해도 보존이 하루 늘 뿐이다.
        pipe.expire(key, USAGE_RETENTION_SECONDS, nx=True)
        await pipe.execute()


async def record_usage(
    call_site: str, model: str, usage_metadata: object | None, *, now: datetime | None = None
) -> None:
    """호출 한 건을 오늘(KST) 해시에 더한다. **절대 raise 하지 않는다** — 생성 스트림(SSE
    제너레이터 안)과 판정 `try` 안에서 await 되는데, 판정 쪽은 `LLMClientError` 만 흡수하므로
    여기서 새는 예외는 SSE 본문을 뚫는다. timeout·Redis 오류·메타데이터 이상을 통째로 흡수하고
    그 한 건만 버린다. 취소(`CancelledError`)는 `Exception` 이 아니라서 그대로 올라간다."""
    try:
        async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
            await _write(call_site, model, usage_metadata, now or datetime.now(UTC))
    except Exception as exc:
        logger.warning("llm_usage 기록 실패 — 이 호출 한 건은 집계에서 빠진다", exc_info=True)
        capture_dependency_failure(exc, dependency="redis")


@dataclass(frozen=True)
class UsageRow:
    """집계 한 줄. `day` 가 None 이면 여러 날을 합친 줄이다."""

    day: date | None
    call_site: str
    model: str
    calls: int = 0
    prompt: int = 0
    cached: int = 0
    cache_write: int = 0
    candidates: int = 0
    thoughts: int = 0
    total: int = 0
    missing: int = 0


def _rows_for_day(day: date, fields: dict[str, str]) -> list[UsageRow]:
    by_pair: dict[tuple[str, str], dict[str, int]] = {}
    for field, raw in fields.items():
        parts = field.split("|")
        if len(parts) != 3 or parts[2] not in _METRICS:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        call_site, model, metric = parts
        by_pair.setdefault((call_site, model), {})[metric] = value
    return [
        UsageRow(day=day, call_site=call_site, model=model, **metrics)
        for (call_site, model), metrics in sorted(by_pair.items())
    ]


async def read_usage(start: date, end: date, *, client: Redis | None = None) -> list[UsageRow]:
    """`start`~`end`(양끝 포함, KST 날짜)의 일자 × call_site × model 줄. 읽기 전용이고 날짜 수만큼의
    HGETALL 을 파이프라인 한 번에 보낸다. 형식이 다른 필드는 건너뛴다."""
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    if not days:
        return []
    async with (client or redis_client).pipeline(transaction=False) as pipe:
        for day in days:
            pipe.hgetall(usage_key(day))
        hashes: list[dict[str, str]] = await pipe.execute()
    return [row for day, fields in zip(days, hashes, strict=True) for row in _rows_for_day(day, fields)]


def sum_by_call_site_and_model(rows: Iterable[UsageRow]) -> list[UsageRow]:
    """여러 날의 줄을 (call_site, model) 로 합친다. 합친 줄의 `day` 는 None 이다."""
    totals: dict[tuple[str, str], UsageRow] = {}
    for row in rows:
        pair = (row.call_site, row.model)
        acc = totals.get(pair) or UsageRow(day=None, call_site=row.call_site, model=row.model)
        totals[pair] = replace(acc, **{m: getattr(acc, m) + getattr(row, m) for m in _METRICS})
    return [totals[pair] for pair in sorted(totals)]
