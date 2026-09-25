import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest

from api.core import rate_limit
from api.core.rate_limit import (
    check_rate_limit,
    refund_tokens,
    retry_after_seconds,
    seconds_until_kst_midnight,
    take_tokens,
)
from api.core.redis import redis_client


def test_retry_after_seconds_allows_up_to_limit() -> None:
    assert retry_after_seconds(count=1, limit=5, ttl=3600) == 0
    assert retry_after_seconds(count=5, limit=5, ttl=3600) == 0


def test_retry_after_seconds_blocks_over_limit_and_returns_ttl() -> None:
    assert retry_after_seconds(count=6, limit=5, ttl=1800) == 1800


def test_retry_after_seconds_never_returns_negative() -> None:
    # TTL이 이미 키가 없거나(-2) 만료 없이 걸려 있는(-1) 상태로 관측되는 방어적 경우도
    # 음수를 사용자에게 돌려주지 않는다.
    assert retry_after_seconds(count=6, limit=5, ttl=-1) == 0


async def test_check_rate_limit_allows_up_to_limit_then_blocks() -> None:
    scope, key = "test_scope", "user@example.com"
    await redis_client.delete(f"rate_limit:{scope}:{key}")

    for _ in range(3):
        assert await check_rate_limit(scope, key, limit=3) == 0

    retry_after = await check_rate_limit(scope, key, limit=3)
    assert retry_after > 0


async def test_check_rate_limit_isolates_by_key() -> None:
    scope = "test_scope_isolation"
    await redis_client.delete(f"rate_limit:{scope}:a@example.com")
    await redis_client.delete(f"rate_limit:{scope}:b@example.com")

    for _ in range(2):
        assert await check_rate_limit(scope, "a@example.com", limit=2) == 0

    # 다른 키는 아직 한 번도 안 썼으니 여전히 통과한다.
    assert await check_rate_limit(scope, "b@example.com", limit=2) == 0


async def test_check_rate_limit_recovers_after_window_expires() -> None:
    scope, key = "test_scope_expiry", "user@example.com"
    redis_key = f"rate_limit:{scope}:{key}"
    await redis_client.delete(redis_key)

    for _ in range(2):
        assert await check_rate_limit(scope, key, limit=2) == 0
    assert await check_rate_limit(scope, key, limit=2) > 0

    # 1시간을 기다릴 수 없으니 창이 끝난 상태를 키 삭제로 직접 만든다.
    await redis_client.delete(redis_key)

    assert await check_rate_limit(scope, key, limit=2) == 0


def test_seconds_until_kst_midnight_shrinks_toward_midnight() -> None:
    # 구현의 KST 상수를 빌려 쓰지 않는다 — 여기서 오프셋을 직접 만들어야 오프셋이 틀렸을 때 깨진다.
    kst = timezone(timedelta(hours=9))

    assert seconds_until_kst_midnight(datetime(2026, 9, 17, 0, 0, tzinfo=kst)) == 86400
    assert seconds_until_kst_midnight(datetime(2026, 9, 17, 12, 0, tzinfo=kst)) == 43200
    assert seconds_until_kst_midnight(datetime(2026, 9, 17, 23, 59, tzinfo=kst)) == 60
    # 같은 순간을 UTC로 넘겨도 같은 값이다(KST 12:00 == UTC 03:00).
    assert seconds_until_kst_midnight(datetime(2026, 9, 17, 3, 0, tzinfo=UTC)) == 43200


def test_seconds_until_kst_midnight_rejects_naive_datetime() -> None:
    # naive를 받아주면 `astimezone`이 프로세스 로컬 시간으로 재해석한다 — 같은
    # `datetime(2026, 9, 17, 12, 0)`이 이 머신(KST)에선 43200, `TZ=UTC` 컨테이너에선 10800이
    # 나온다(실측). `datetime.utcnow()`처럼 naive를 넘기면 일일 창이 KST 자정이 아니라 UTC
    # 자정(=KST 09:00)에서 끊기는데 예외도 로그도 없어 조용히 깨진다.
    with pytest.raises(ValueError, match="tz-aware"):
        seconds_until_kst_midnight(datetime(2026, 9, 17, 12, 0))


async def test_check_rate_limit_window_seconds_defaults_to_3600_for_existing_callers() -> None:
    # `auth/router.py`의 5개 호출부는 창 길이를 넘기지 않는다 — 기본값이 바뀌면 그 5곳의
    # 시간당 상한이 조용히 다른 창으로 바뀐다.
    scope, key = "test_scope_default_window", "user@example.com"

    assert await check_rate_limit(scope, key, limit=5) == 0

    assert await redis_client.ttl(f"rate_limit:{scope}:{key}") == 3600


async def test_check_rate_limit_honours_custom_window_seconds() -> None:
    scope, key = "test_scope_custom_window", "user@example.com"

    assert await check_rate_limit(scope, key, limit=5, window_seconds=60) == 0

    ttl = await redis_client.ttl(f"rate_limit:{scope}:{key}")
    assert 0 < ttl <= 60


async def test_token_bucket_refills_one_per_hour_and_caps_at_capacity() -> None:
    scope, key = "test_bucket_refill", "user-1"
    start = 1_000_000.0

    async def take(count: int, now: float) -> int:
        return await take_tokens(
            redis_client, scope, key, count, capacity=10, refill_seconds=3600, now=now
        )

    # 키가 없으면 만땅(용량 10)에서 시작한다.
    assert await take(10, now=start) == 0
    assert await take(1, now=start) > 0

    # 1시간 뒤 정확히 1개가 찬다 — 2장은 아직 안 되고 1장은 된다.
    assert await take(2, now=start + 3600) > 0
    assert await take(1, now=start + 3600) == 0
    assert await take(1, now=start + 3600) > 0

    # 20시간을 놀려도 천장은 용량 10이다(20개가 쌓이지 않는다).
    assert await take(10, now=start + 20 * 3600) == 0
    assert await take(1, now=start + 20 * 3600) > 0


async def test_token_bucket_rejects_without_partial_charge_and_returns_wait_seconds() -> None:
    scope, key = "test_bucket_partial", "user-1"
    start = 1_000_000.0

    async def take(count: int, now: float) -> int:
        return await take_tokens(
            redis_client, scope, key, count, capacity=10, refill_seconds=3600, now=now
        )

    assert await take(9, now=start) == 0

    # 1개 남았는데 2개를 요청하면 부족분 1개가 찰 때까지의 초를 돌려준다.
    assert await take(2, now=start) == 3600

    # 그리고 남은 1개는 깎이지 않았다(부분 차감 금지).
    assert await take(1, now=start) == 0


async def test_token_bucket_does_not_lose_tokens_when_clock_goes_backwards() -> None:
    # 이 테스트는 "빨강 먼저"가 불가능한 회귀 가드다 — `_refilled_tokens`의
    # `max(now - updated_at, 0.0)` 클램프가 이미 있어 처음부터 초록이다. 신호는 클램프를 지우는
    # 변이로 확인했다(지우면 elapsed가 음수가 되어 충전이 아니라 차감이 되고, 마지막 단언이
    # 깨진다). NTP 되감기나 인스턴스 간 시계 차이로 `updated_at`이 `now`보다 미래일 수 있다.
    scope, key = "test_bucket_clock_skew", "user-1"
    start = 1_000_000.0

    async def take(count: int, now: float) -> int:
        return await take_tokens(
            redis_client, scope, key, count, capacity=10, refill_seconds=3600, now=now
        )

    # 미래 시각으로 먼저 차감해 `updated_at`을 `now`보다 앞에 둔다(= 시계가 역행한 상태).
    assert await take(5, now=start + 3600) == 0

    # 역행한 시계로 읽어도 남은 5장이 그대로다 — 6장은 안 되고 5장은 된다.
    assert await take(6, now=start) > 0
    assert await take(5, now=start) == 0


async def test_token_bucket_refund_restores_tokens_up_to_capacity() -> None:
    scope, key = "test_bucket_refund", "user-1"
    start = 1_000_000.0

    async def take(count: int, now: float) -> int:
        return await take_tokens(
            redis_client, scope, key, count, capacity=10, refill_seconds=3600, now=now
        )

    async def refund(count: int, now: float) -> None:
        await refund_tokens(
            redis_client, scope, key, count, capacity=10, refill_seconds=3600, now=now
        )

    assert await take(10, now=start) == 0
    assert await take(1, now=start) > 0

    await refund(2, now=start)

    assert await take(2, now=start) == 0
    assert await take(1, now=start) > 0

    # 용량을 넘겨 환불해도 천장은 10이다.
    await refund(100, now=start)
    assert await take(10, now=start) == 0
    assert await take(1, now=start) > 0


async def test_token_bucket_charges_exactly_under_concurrent_gather() -> None:
    # WATCH 없이 GET-then-SET으로 짜면 갱신 유실로 10개보다 많이 통과한다.
    scope, key = "test_bucket_concurrent", "user-1"
    now = 2_000_000.0

    results = await asyncio.gather(
        *(
            take_tokens(redis_client, scope, key, 1, capacity=10, refill_seconds=3600, now=now)
            for _ in range(20)
        )
    )

    assert results.count(0) == 10
    # 버킷은 정확히 비어 있다.
    assert (
        await take_tokens(redis_client, scope, key, 1, capacity=10, refill_seconds=3600, now=now) > 0
    )


async def test_token_bucket_denies_when_watch_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 경합이 안 풀린 채 재시도를 다 써도 fail-open이면 안 된다 — 0을 돌려주면 차감이 저장되지
    # 않은 채로 통과라 상한이 그대로 뚫린다. 재시도 0회로 소진 상태를 직접 만든다.
    monkeypatch.setattr(rate_limit, "_WATCH_MAX_ATTEMPTS", 0)

    retry_after = await take_tokens(
        redis_client, "test_bucket_exhausted", "user-1", 1, capacity=10, refill_seconds=3600, now=0.0
    )

    assert retry_after > 0


async def test_token_bucket_refund_gives_up_quietly_when_watch_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `take_tokens`의 fail-closed(위 테스트)와 반대 결정이다 — 환불 실패는 사용자 요청을 막지
    # 않으므로 raise하지 않고 버린다. 반대 결정이라 양쪽을 각각 고정한다.
    scope, key = "test_bucket_refund_exhausted", "user-1"
    redis_key = f"rate_limit:{scope}:{key}"
    now = 1_000_000.0

    assert (
        await take_tokens(redis_client, scope, key, 3, capacity=10, refill_seconds=3600, now=now)
        == 0
    )
    raw_before = await redis_client.get(redis_key)

    # 재시도 0회로 소진 상태를 직접 만든다.
    monkeypatch.setattr(rate_limit, "_WATCH_MAX_ATTEMPTS", 0)

    # raise하지 않고 반환한다(여기서 예외가 새면 이 호출이 그대로 터진다).
    await refund_tokens(redis_client, scope, key, 3, capacity=10, refill_seconds=3600, now=now)

    # 그리고 버킷은 손대지 않는다.
    assert await redis_client.get(redis_key) == raw_before
