"""`api.core.redis_lock` — 여러 워커가 함께 지키는 Redis 락.

워커 둘은 Redis 입장에서 "연결 둘"이다. 그래서 클라이언트를 둘 만들어(각자 자기 연결 풀) 같은 키를
다투게 하면, 한 프로세스 안에서도 두 프로세스가 다투는 상황과 Redis 가 보는 상태가 같다.
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest_asyncio
from redis.asyncio import Redis

from api.core.config import settings
from api.core.redis import redis_client
from api.core.redis_lock import release_lock, try_acquire_lock, wait_for_lock

_KEY = "test_redis_lock:key"


@pytest_asyncio.fixture
async def two_connections() -> AsyncGenerator[tuple[Redis, Redis], None]:
    await redis_client.delete(_KEY)
    first = Redis.from_url(settings.redis_url, decode_responses=True)
    second = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield first, second
    finally:
        await first.aclose()
        await second.aclose()
        await redis_client.delete(_KEY)


async def test_two_connections_never_hold_the_lock_at_the_same_time(
    two_connections: tuple[Redis, Redis],
) -> None:
    """락이 상호배제를 못 하면 두 워커가 집 PC 를 동시에 부르고, 집 PC 는 두 번째 요청을 즉시
    429 로 거절해 그 이미지가 실패한다. 보호 구간의 진입·이탈을 기록해 겹치지 않는지 본다."""
    events: list[str] = []

    async def hold(redis: Redis, name: str) -> None:
        token = await wait_for_lock(
            redis, _KEY, ttl_ms=5_000, max_wait_seconds=5, poll_interval_seconds=0.02
        )
        assert token is not None
        events.append(f"enter:{name}")
        await asyncio.sleep(0.1)
        events.append(f"exit:{name}")
        await release_lock(redis, _KEY, token)

    first, second = two_connections
    await asyncio.gather(hold(first, "a"), hold(second, "b"))

    assert len(events) == 4
    assert [event.split(":")[0] for event in events] == ["enter", "exit", "enter", "exit"]


async def test_a_holder_that_dies_without_releasing_frees_the_lock_after_the_ttl(
    two_connections: tuple[Redis, Redis],
) -> None:
    """보유 워커가 해제 없이 죽으면(배포 재생성·크래시) TTL 이 지나야 다음 워커가 잡는다. TTL 이
    없으면 그 뒤 이미지 생성이 영원히 막힌다."""
    first, second = two_connections

    assert await try_acquire_lock(first, _KEY, ttl_ms=300) is not None
    # 첫 보유자는 여기서 "죽는다" — 해제하지 않는다.
    assert await try_acquire_lock(second, _KEY, ttl_ms=300) is None

    await asyncio.sleep(0.4)

    assert await try_acquire_lock(second, _KEY, ttl_ms=300) is not None


async def test_a_stale_owner_cannot_release_the_next_owners_lock(
    two_connections: tuple[Redis, Redis],
) -> None:
    """TTL 이 지난 뒤 늦게 도착한 옛 보유자의 해제가 새 보유자의 락을 지우면, 세 번째 워커가 바로
    들어와 보유자가 둘이 된다. 해제는 자기 토큰일 때만 지워야 한다."""
    first, second = two_connections

    stale_token = await try_acquire_lock(first, _KEY, ttl_ms=100)
    assert stale_token is not None
    await asyncio.sleep(0.2)
    assert await try_acquire_lock(second, _KEY, ttl_ms=5_000) is not None

    assert await release_lock(first, _KEY, stale_token) is False
    assert await try_acquire_lock(first, _KEY, ttl_ms=5_000) is None


async def test_release_by_the_owner_frees_the_lock_at_once(two_connections: tuple[Redis, Redis]) -> None:
    """해제가 안 되면 매 보유가 TTL 만큼 이어져 이미지 한 장마다 2분씩 다음 장이 기다린다."""
    first, second = two_connections

    token = await try_acquire_lock(first, _KEY, ttl_ms=60_000)
    assert token is not None
    assert await release_lock(first, _KEY, token) is True

    assert await try_acquire_lock(second, _KEY, ttl_ms=60_000) is not None


async def test_wait_for_lock_gives_up_after_the_max_wait(two_connections: tuple[Redis, Redis]) -> None:
    """대기 상한이 없으면 다른 워커가 계속 이길 때 이 장이 끝없이 기다린다."""
    first, second = two_connections
    assert await try_acquire_lock(first, _KEY, ttl_ms=60_000) is not None

    loop = asyncio.get_running_loop()
    started = loop.time()
    token = await wait_for_lock(
        second, _KEY, ttl_ms=60_000, max_wait_seconds=0.2, poll_interval_seconds=0.02
    )

    assert token is None
    assert loop.time() - started < 1.0

