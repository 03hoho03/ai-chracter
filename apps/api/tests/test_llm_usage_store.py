import asyncio
import time
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from api.core.redis import redis_client
from api.llm import usage_store
from api.llm.usage_store import (
    USAGE_RETENTION_SECONDS,
    UsageRow,
    read_usage,
    record_usage,
    sum_by_call_site_and_model,
    usage_key,
)

# 다른 테스트의 "오늘" 키와 겹치지 않게 먼 날짜를 쓴다(KST 기준 2030-03-10 정오).
_NOW = datetime(2030, 3, 10, 3, 0, tzinfo=UTC)
_DAY = date(2030, 3, 10)


def _meta(
    prompt: int | None, candidates: int | None, thoughts: int | None, total: int | None, cached: int | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=prompt,
        cached_content_token_count=cached,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        total_token_count=total,
    )


async def _hash(day: date) -> dict[str, str]:
    # 클라이언트가 decode_responses=True 라 실제로는 전부 str 이다(스텁은 bytes 도 허용한다).
    return {str(k): str(v) for k, v in (await redis_client.hgetall(usage_key(day))).items()}


async def test_record_usage_increments_metrics_per_call_site_and_model() -> None:
    await record_usage("chat_stat_judgment", "m-a", _meta(100, 20, 5, 125, cached=60), now=_NOW)
    await record_usage("chat_stat_judgment", "m-a", _meta(10, 2, None, 12), now=_NOW)
    await record_usage("chat_stat_judgment", "m-b", _meta(1, 1, 1, 3), now=_NOW)

    stored = await _hash(_DAY)

    assert {k: v for k, v in stored.items() if k.startswith("chat_stat_judgment|m-a|")} == {
        "chat_stat_judgment|m-a|calls": "2",
        "chat_stat_judgment|m-a|prompt": "110",
        "chat_stat_judgment|m-a|cached": "60",
        "chat_stat_judgment|m-a|candidates": "22",
        "chat_stat_judgment|m-a|thoughts": "5",
        "chat_stat_judgment|m-a|total": "137",
    }
    # 모델 축이 갈린다 — 판정 모델을 바꾼 뒤 두 모델의 호출이 한 줄로 합쳐지면 전환 감시가 안 된다.
    assert stored["chat_stat_judgment|m-b|calls"] == "1"
    # 사용자·방 id 는 키에도 필드에도 없다.
    assert all(k.count("|") == 2 for k in stored)


async def test_record_usage_counts_missing_when_prompt_tokens_or_metadata_absent() -> None:
    """이미지가 실린 호출은 prompt_tokens 가 None 이고 total 만 온다 — total 이 집계돼야
    발행 심사·그림 판정의 입력 원가가 0 으로 잡히지 않고, missing 이 그 호출 수를 드러낸다."""
    await record_usage("publish_filter_story", "m", _meta(None, 30, None, 900), now=_NOW)
    await record_usage("publish_filter_story", "m", None, now=_NOW)

    stored = await _hash(_DAY)

    assert stored["publish_filter_story|m|calls"] == "2"
    assert stored["publish_filter_story|m|missing"] == "2"
    assert stored["publish_filter_story|m|total"] == "900"
    assert stored["publish_filter_story|m|candidates"] == "30"
    assert "publish_filter_story|m|prompt" not in stored


async def test_record_usage_sets_retention_ttl_once() -> None:
    await record_usage("chat_generate", "m", _meta(1, 1, None, 2), now=_NOW)
    ttl = await redis_client.ttl(usage_key(_DAY))

    assert USAGE_RETENTION_SECONDS - 5 < ttl <= USAGE_RETENTION_SECONDS


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param(datetime(2030, 3, 9, 14, 59, 59, tzinfo=UTC), date(2030, 3, 9), id="kst-23:59:59"),
        pytest.param(datetime(2030, 3, 9, 15, 0, 0, tzinfo=UTC), date(2030, 3, 10), id="kst-midnight"),
    ],
)
async def test_record_usage_buckets_by_kst_date(now: datetime, expected: date) -> None:
    await record_usage("chat_generate", "m", _meta(1, 1, None, 2), now=now)

    assert (await _hash(expected)).get("chat_generate|m|calls") == "1"


class _FailingPipeline:
    def __init__(self, behaviour: str) -> None:
        self._behaviour = behaviour

    async def __aenter__(self) -> "_FailingPipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def __getattr__(self, _name: str) -> Any:
        return lambda *_a, **_k: None

    async def execute(self) -> list[int]:
        if self._behaviour == "hang":
            await asyncio.sleep(30)
        raise RedisConnectionError("redis down")


@pytest.mark.parametrize("behaviour", [pytest.param("raise", id="redis-error"), pytest.param("hang", id="hang")])
async def test_record_usage_never_raises_and_returns_quickly(monkeypatch: pytest.MonkeyPatch, behaviour: str) -> None:
    """생성 스트림 끝에서 await 된다 — Redis 가 죽거나 응답이 없어도 턴의 `done` 을 붙잡으면 안 된다."""
    monkeypatch.setattr(usage_store, "redis_client", SimpleNamespace(pipeline=lambda **_: _FailingPipeline(behaviour)))

    started = time.monotonic()
    await record_usage("chat_generate", "m", _meta(1, 1, None, 2), now=_NOW)

    assert time.monotonic() - started < 1.0


async def test_record_usage_swallows_broken_metadata() -> None:
    class _Exploding:
        @property
        def prompt_token_count(self) -> int:
            raise RuntimeError("boom")

    await record_usage("chat_generate", "m", _Exploding(), now=_NOW)

    assert await _hash(_DAY) == {}


async def test_read_usage_returns_rows_per_day_and_sums_by_call_site_and_model() -> None:
    day1, day2, day3 = date(2030, 3, 10), date(2030, 3, 11), date(2030, 3, 12)
    await record_usage(
        "chat_generate", "m", _meta(100, 10, 1, 111, cached=50), now=datetime(2030, 3, 10, 3, tzinfo=UTC)
    )
    await record_usage("chat_generate", "m", _meta(200, 20, 2, 222), now=datetime(2030, 3, 11, 3, tzinfo=UTC))
    await record_usage("publish_filter_story", "m", None, now=datetime(2030, 3, 11, 3, tzinfo=UTC))
    # 범위 밖 날짜는 읽히지 않는다.
    await record_usage("chat_generate", "m", _meta(9, 9, 9, 27), now=datetime(2030, 3, 12, 3, tzinfo=UTC))
    # 형식이 다른 필드(사람이 손으로 넣은 값 등)는 표를 깨지 않고 건너뛴다.
    await redis_client.hset(usage_key(day1), "garbage", "1")

    rows = await read_usage(day1, day2)

    assert rows == [
        UsageRow(
            day=day1,
            call_site="chat_generate",
            model="m",
            calls=1,
            prompt=100,
            cached=50,
            candidates=10,
            thoughts=1,
            total=111,
            missing=0,
        ),
        UsageRow(
            day=day2,
            call_site="chat_generate",
            model="m",
            calls=1,
            prompt=200,
            cached=0,
            candidates=20,
            thoughts=2,
            total=222,
            missing=0,
        ),
        UsageRow(
            day=day2,
            call_site="publish_filter_story",
            model="m",
            calls=1,
            prompt=0,
            cached=0,
            candidates=0,
            thoughts=0,
            total=0,
            missing=1,
        ),
    ]
    assert day3 not in {r.day for r in rows}

    summed = sum_by_call_site_and_model(rows)
    assert summed == [
        UsageRow(
            day=None,
            call_site="chat_generate",
            model="m",
            calls=2,
            prompt=300,
            cached=50,
            candidates=30,
            thoughts=3,
            total=333,
            missing=0,
        ),
        UsageRow(
            day=None,
            call_site="publish_filter_story",
            model="m",
            calls=1,
            prompt=0,
            cached=0,
            candidates=0,
            thoughts=0,
            total=0,
            missing=1,
        ),
    ]
