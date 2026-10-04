"""여러 프로세스(uvicorn 워커)가 함께 지키는 Redis 상호배제 락.

프로세스 안의 `asyncio.Lock`·`Semaphore` 는 워커를 둘 이상 띄우면 워커마다 따로 생겨 아무것도
막지 못한다. 그래서 잠금 상태를 모든 워커가 보는 Redis 키 하나에 둔다.

- 획득은 `SET key token NX PX ttl` 한 명령이다 — 키가 없을 때만 써지므로 검사와 기록 사이에 다른
  워커가 끼어들 틈이 없다.
- 키에는 획득자만 아는 무작위 토큰을 싣고, 해제는 "값이 내 토큰일 때만 지운다"를 Lua 로 서버에서
  한 번에 한다. 그냥 `DEL` 하면 TTL 이 지나 이미 다른 워커가 새로 잡은 락을 남이 지워 버린다.
  GET 과 DEL 을 따로 보내도 그 사이에 같은 일이 생긴다. 이 저장소의 다른 read-modify-write 는
  WATCH/MULTI 재시도를 쓰지만, 비교 삭제는 재시도가 소진됐을 때 "지웠다고 볼지"를 또 정해야 해서
  재시도 분기가 없는 Lua 로 둔다.
- 획득자가 해제하지 못하고 죽으면(프로세스 종료·배포 재생성) 키는 TTL 이 지나 저절로 사라진다.
  그래서 TTL 은 보호 구간이 끝날 수 있는 가장 긴 시간보다 길어야 한다 — 짧으면 살아 있는 보유자의
  락이 풀려 두 번째 보유자가 들어온다.

Redis 클라이언트를 인자로 받는다 — 테스트가 클라이언트(= 연결) 둘을 만들어 두 프로세스가 같은
락을 다투는 상황을 한 프로세스 안에서 재현할 수 있게 하려는 것이다(`core/rate_limit.py` 의
`take_tokens` 와 같은 이유).
"""

import asyncio
import random
import secrets
import time

from redis.asyncio import Redis

_RELEASE_IF_OWNER_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


async def try_acquire_lock(redis: Redis, key: str, *, ttl_ms: int) -> str | None:
    """락을 한 번 시도한다. 잡으면 해제에 쓸 토큰을, 이미 누가 쥐고 있으면 None 을 돌려준다."""
    token = secrets.token_hex(16)
    acquired = await redis.set(key, token, nx=True, px=ttl_ms)
    return token if acquired else None


async def wait_for_lock(
    redis: Redis,
    key: str,
    *,
    ttl_ms: int,
    max_wait_seconds: float,
    poll_interval_seconds: float = 0.5,
) -> str | None:
    """락이 풀릴 때까지 주기적으로 다시 시도한다. `max_wait_seconds` 안에 못 잡으면 None.

    Redis 에는 대기열이 없으니 기다리는 쪽이 폴링한다. 대기 순서는 보장되지 않는다(먼저 기다린
    워커가 먼저 잡는다는 보장이 없다). 간격에 작은 무작위 값을 더해 여러 워커가 같은 순간에 몰려
    재시도하지 않게 한다."""
    deadline = time.monotonic() + max_wait_seconds
    while True:
        token = await try_acquire_lock(redis, key, ttl_ms=ttl_ms)
        if token is not None:
            return token
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(poll_interval_seconds + random.uniform(0, poll_interval_seconds * 0.4))


async def release_lock(redis: Redis, key: str, token: str) -> bool:
    """토큰이 지금 키의 값과 같을 때만 지운다. 지웠으면 True.

    False 는 TTL 이 이미 지나 락을 잃었다는 뜻이다(그 사이 다른 보유자가 들어왔을 수 있다)."""
    deleted = await redis.eval(_RELEASE_IF_OWNER_SCRIPT, 1, key, token)
    return bool(deleted)
