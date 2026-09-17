"""rate limit 기구 두 가지: 고정 창(fixed window) 카운터와 토큰 버킷.

정책값(분·일 상한, 버킷 용량)은 이 파일에 없다 — 호출자가 인자로 넘긴다
(limit-goal-prompt.md RL-14: 정책 상수는 게이트 모듈에 두고 여기는 기구만 제공한다).
예외는 먼저 있던 발송 엔드포인트(signup/resend/password-reset)의 시간당 상한이다
(email-goal-prompt.md E-6) — 상한은 여기 모듈 상수로 둔다(E-6 — env로 빼지 않는다.
조정이 필요하면 재배포 한 줄).

고정 창 카운터(`check_rate_limit`). INCR로 창 안 호출 수를 세고, 첫 호출에서만 EXPIRE로 창의
끝을 못박는다. 창 길이는 `window_seconds`(기본 1시간)로 받고, 일일 창이 필요한 호출자는
`seconds_until_kst_midnight()`를 넘기면서 키에 KST 날짜를 직접 섞어 조립한다
(limit-goal-prompt.md RL-4) — 기구는 창의 의미에 관여하지 않는다.

토큰 버킷(`take_tokens`/`refund_tokens`). 용량만큼 모아 두고 `refill_seconds`마다 1개씩
연속 충전한다(limit-goal-prompt.md RL-5). 요청 수만큼 한 번에 차감하고, 모자라면 부분 차감
없이 거절한다. read-modify-write라 `apps/api/CLAUDE.md` §백그라운드·Redis의 규칙대로
WATCH/MULTI/EXEC로 감싼다(`images/jobs.py`의 `update_job` 선례) — 없으면 갱신 유실로 상한이
그냥 뚫린다(실측: GET-then-SET으로 짜면 용량 10짜리 버킷에 동시 20건이 **전부** 통과했다).

키 프리픽스는 두 기구 모두 `rate_limit:`이다(limit-goal-prompt.md RL-6). 테스트
`conftest.py`의 autouse `_flush_rate_limit_keys`가 `rate_limit:*`를 지우므로, 같은 프리픽스를
쓰는 한 새 키도 테스트 격리에 자동으로 편입된다.

⚠️ INCR과 EXPIRE 사이의 경합: 두 명령을 따로 보내면 INCR만 반영되고 EXPIRE 전에 프로세스가
죽었을 때 TTL 없는 키가 영구히 남을 수 있다. 이 저장소의 redis-py 8.0.1 + redis:8-alpine은
Redis 7.0+의 `EXPIRE ... NX`(키에 TTL이 아직 없을 때만 설정)를 지원하고(실측 확인),
INCR·EXPIRE NX·TTL 세 명령을 **하나의 MULTI/EXEC 트랜잭션**(pipeline)으로 묶어 보내
서버가 통째로 원자적으로 실행하게 한다 — "INCR만 반영되고 EXPIRE는 안 걸린" 중간 상태 자체가
서버에 생기지 않는다(셋 다 실행되거나 아무것도 안 되거나). NX가 필요한 이유는 별개다: 창이 끝나기
전 재요청마다 EXPIRE를 무조건 걸면 TTL이 매번 늘어나 고정 창이 아니라 sliding window가 된다 —
NX로 "TTL이 아직 없을 때만"으로 제한해 창의 첫 호출에서만 만료 시각을 못박는다.
"""

import logging
import math
from datetime import datetime, time, timedelta, timezone

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import WatchError

from api.core.redis import redis_client

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 3600

# limit-goal-prompt.md RL-4: `ZoneInfo("Asia/Seoul")`이 아니라 고정 오프셋이다. KST는 DST가
# 없어 오프셋이 영구히 +9이고, 이렇게 두면 컨테이너에 tzdata가 있든 없든 같은 값이 나온다.
KST = timezone(timedelta(hours=9))

# WATCH 재시도는 횟수를 막는다. 경합이 풀리지 않는 상황(같은 키에 계속 쓰기가 몰림)에서
# `while True`면 요청 하나가 이벤트 루프를 붙든 채 영원히 돌 수 있기 때문이다. 한 라운드마다
# 최소 한 명은 성공하므로 동시 N건이면 최악이 N회 — 동시성 실측 테스트(20건)보다 넉넉히 둔다.
_WATCH_MAX_ATTEMPTS = 50

SIGNUP_IP_LIMIT = 10
SIGNUP_EMAIL_LIMIT = 5
RESEND_VERIFICATION_EMAIL_LIMIT = 5
PASSWORD_RESET_EMAIL_LIMIT = 5
PASSWORD_RESET_IP_LIMIT = 10


class _TokenBucket(BaseModel):
    """버킷 상태는 키 **하나**에 담는다 — WATCH가 원자성을 보장하는 단위가 키라서,
    토큰 수와 마지막 갱신 시각이 서로 다른 키에 있으면 둘이 어긋난 상태가 관측된다."""

    tokens: float
    updated_at: float


def _key(scope: str, key: str) -> str:
    return f"rate_limit:{scope}:{key}"


def seconds_until_kst_midnight(now: datetime) -> int:
    """tz-aware `now`(UTC든 KST든)에서 다음 KST 자정까지 남은 초(limit-goal-prompt.md RL-4).

    naive `now`는 거부한다 — `astimezone`이 naive를 **프로세스 로컬 시간**으로 재해석해서 같은
    입력이 컨테이너 TZ마다 다른 답을 낸다(실측: naive 12:00이 이 머신에선 43200, `TZ=UTC`에선
    10800). 흔한 습관인 `datetime.utcnow()`를 넘기면 일일 창이 KST 자정이 아니라 UTC 자정
    (=KST 09:00)에서 끊기는데 예외도 로그도 없어 RL-4가 조용히 깨진다.

    반환은 항상 ≥ 1이다 — `ceil`의 입력이 `(0, 86400]`이라 0은 도달 불가다(`kst_now ==
    next_midnight`이려면 오늘이 내일이어야 한다). 그런데도 `max(1, ...)`를 남기는 건 호출자가
    이 값을 TTL로 쓰기 때문이다: 0이 새면 `EXPIRE 0`이 키를 **지워**(실측 `ttl=-2`, 만료 없는
    키가 아니다) 그 창의 카운터가 매 호출 사라지고 상한이 통째로 무력화된다. 도달 불가인 채로
    불변식을 코드에 박아 둔다.
    """
    if now.tzinfo is None:
        raise ValueError("tz-aware `now`가 필요하다 — `datetime.now(UTC)`를 넘길 것")
    kst_now = now.astimezone(KST)
    next_midnight = datetime.combine(kst_now.date() + timedelta(days=1), time.min, tzinfo=KST)
    return max(1, math.ceil((next_midnight - kst_now).total_seconds()))


def retry_after_seconds(count: int, limit: int, ttl: int) -> int:
    """Pure 함수라 Redis 없이 단위 테스트 가능하다(`verification.py`의
    `seconds_until_resend_allowed` 선례). 상한을 안 넘었으면 0, 넘었으면 창의 남은 초."""
    if count <= limit:
        return 0
    return max(ttl, 0)


async def check_rate_limit(
    scope: str, key: str, limit: int, window_seconds: int = _WINDOW_SECONDS
) -> int:
    """`scope`(엔드포인트+키 종류) 안에서 `key`(이메일/IP)의 호출 수를 올리고, 상한을 넘었으면
    남은 초(`retryAfterSeconds`)를, 안 넘었으면 0을 반환한다.

    `window_seconds`의 기본값 1시간은 E-6 발송 엔드포인트 5개 호출부가 그대로 쓴다 — 바꾸면
    그 5곳의 창이 같이 바뀐다. 일일 창은 호출자가 `seconds_until_kst_midnight()`를 넘긴다.

    ⚠️ 호출자는 이 함수를 DB 조회보다 먼저 불러야 한다(email-goal-prompt.md E-6) — 계정 존재
    여부와 무관하게 카운터가 항상 올라가야 429 자체가 존재 여부를 누설하지 않는다.
    """
    redis_key = _key(scope, key)
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds, nx=True)
        pipe.ttl(redis_key)
        count, _, ttl = await pipe.execute()
    return retry_after_seconds(count, limit, ttl)


def _refilled_tokens(
    raw: str | bytes | None, *, capacity: int, refill_seconds: int, now: float
) -> float:
    """저장된 상태를 `now` 기준으로 충전한 토큰 수. 충전은 계단이 아니라 연속이다.

    키가 없으면(한 번도 안 썼거나 TTL로 사라졌으면) 만땅이다 — TTL이 `capacity *
    refill_seconds`라, 그 시간을 안 쓰고 버틴 버킷은 어차피 만땅까지 차 있다.
    """
    if raw is None:
        return float(capacity)
    bucket = _TokenBucket.model_validate_json(raw)
    elapsed = max(now - bucket.updated_at, 0.0)
    return min(float(capacity), bucket.tokens + elapsed / refill_seconds)


def _dump_bucket(tokens: float, now: float) -> str:
    return _TokenBucket(tokens=tokens, updated_at=now).model_dump_json()


async def take_tokens(
    redis: Redis,
    scope: str,
    key: str,
    count: int,
    *,
    capacity: int,
    refill_seconds: int,
    now: float,
) -> int:
    """토큰 `count`개를 차감하고 0을, 모자라면 **차감 없이** 부족분이 채워질 때까지의 초를
    반환한다(limit-goal-prompt.md RL-5 — 부분 차감은 없다).

    `now`는 주입받는다(단조 증가하는 epoch 초). 시간을 고정하는 라이브러리가 이 저장소에 없어
    충전 경계를 테스트하려면 호출자가 시계를 넘기는 수밖에 없다.
    """
    redis_key = _key(scope, key)
    async with redis.pipeline() as pipe:
        for _ in range(_WATCH_MAX_ATTEMPTS):
            try:
                await pipe.watch(redis_key)
                tokens = _refilled_tokens(
                    await pipe.get(redis_key),
                    capacity=capacity,
                    refill_seconds=refill_seconds,
                    now=now,
                )
                if tokens < count:
                    await pipe.unwatch()  # type: ignore[no-untyped-call]
                    return max(1, math.ceil((count - tokens) * refill_seconds))
                pipe.multi()  # type: ignore[no-untyped-call]
                pipe.set(redis_key, _dump_bucket(tokens - count, now), ex=capacity * refill_seconds)
                await pipe.execute()
                return 0
            except WatchError:
                continue
    # 재시도를 다 쓰면 fail-closed로 거절한다 — 여기서 0을 반환하면 저장에 실패한 채로 통과라
    # 상한이 조용히 뚫린다. 경합이 원인이라 곧 풀리므로 1초 뒤 재시도를 안내한다.
    logger.warning("rate_limit: token bucket WATCH contention unresolved (scope=%s)", scope)
    return 1


async def refund_tokens(
    redis: Redis,
    scope: str,
    key: str,
    count: int,
    *,
    capacity: int,
    refill_seconds: int,
    now: float,
) -> None:
    """차감했던 토큰 `count`개를 용량 천장까지 돌려놓는다(limit-goal-prompt.md RL-16 —
    `QUEUE_FULL`처럼 요청을 실제로 처리하지 못했을 때 호출한다)."""
    redis_key = _key(scope, key)
    async with redis.pipeline() as pipe:
        for _ in range(_WATCH_MAX_ATTEMPTS):
            try:
                await pipe.watch(redis_key)
                tokens = _refilled_tokens(
                    await pipe.get(redis_key),
                    capacity=capacity,
                    refill_seconds=refill_seconds,
                    now=now,
                )
                pipe.multi()  # type: ignore[no-untyped-call]
                pipe.set(
                    redis_key,
                    _dump_bucket(min(float(capacity), tokens + count), now),
                    ex=capacity * refill_seconds,
                )
                await pipe.execute()
                return
            except WatchError:
                continue
    # 환불 실패는 사용자 요청을 막지 않으므로 raise하지 않는다. 대신 조용히 사라지지 않게
    # 로그로 남긴다(`apps/api/CLAUDE.md` — uvicorn에선 warning 이상만 stderr로 나간다).
    logger.warning("rate_limit: token refund dropped, WATCH contention (scope=%s)", scope)
