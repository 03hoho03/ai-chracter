from api.core.rate_limit import check_rate_limit, retry_after_seconds
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
