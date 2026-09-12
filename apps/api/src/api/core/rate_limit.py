"""email-goal-prompt.md E-6: 발송 엔드포인트(signup/resend/password-reset)의 시간당 rate limit.

고정 창(fixed window) 카운터. INCR로 창 안 호출 수를 세고, 첫 호출에서만 EXPIRE로 창의 끝을
못박는다. 상한은 여기 모듈 상수로 둔다(E-6 — env로 빼지 않는다. 조정이 필요하면 재배포 한 줄).

⚠️ INCR과 EXPIRE 사이의 경합: 두 명령을 따로 보내면 INCR만 반영되고 EXPIRE 전에 프로세스가
죽었을 때 TTL 없는 키가 영구히 남을 수 있다. 이 저장소의 redis-py 8.0.1 + redis:8-alpine은
Redis 7.0+의 `EXPIRE ... NX`(키에 TTL이 아직 없을 때만 설정)를 지원하고(실측 확인),
INCR·EXPIRE NX·TTL 세 명령을 **하나의 MULTI/EXEC 트랜잭션**(pipeline)으로 묶어 보내
서버가 통째로 원자적으로 실행하게 한다 — "INCR만 반영되고 EXPIRE는 안 걸린" 중간 상태 자체가
서버에 생기지 않는다(셋 다 실행되거나 아무것도 안 되거나). NX가 필요한 이유는 별개다: 창이 끝나기
전 재요청마다 EXPIRE를 무조건 걸면 TTL이 매번 늘어나 고정 창이 아니라 sliding window가 된다 —
NX로 "TTL이 아직 없을 때만"으로 제한해 창의 첫 호출에서만 만료 시각을 못박는다.
"""

from api.core.redis import redis_client

_WINDOW_SECONDS = 3600

SIGNUP_IP_LIMIT = 10
SIGNUP_EMAIL_LIMIT = 5
RESEND_VERIFICATION_EMAIL_LIMIT = 5
PASSWORD_RESET_EMAIL_LIMIT = 5
PASSWORD_RESET_IP_LIMIT = 10


def _key(scope: str, key: str) -> str:
    return f"rate_limit:{scope}:{key}"


def retry_after_seconds(count: int, limit: int, ttl: int) -> int:
    """Pure 함수라 Redis 없이 단위 테스트 가능하다(`verification.py`의
    `seconds_until_resend_allowed` 선례). 상한을 안 넘었으면 0, 넘었으면 창의 남은 초."""
    if count <= limit:
        return 0
    return max(ttl, 0)


async def check_rate_limit(scope: str, key: str, limit: int) -> int:
    """`scope`(엔드포인트+키 종류) 안에서 `key`(이메일/IP)의 호출 수를 올리고, 상한을 넘었으면
    남은 초(`retryAfterSeconds`)를, 안 넘었으면 0을 반환한다.

    ⚠️ 호출자는 이 함수를 DB 조회보다 먼저 불러야 한다(email-goal-prompt.md E-6) — 계정 존재
    여부와 무관하게 카운터가 항상 올라가야 429 자체가 존재 여부를 누설하지 않는다.
    """
    redis_key = _key(scope, key)
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.incr(redis_key)
        pipe.expire(redis_key, _WINDOW_SECONDS, nx=True)
        pipe.ttl(redis_key)
        count, _, ttl = await pipe.execute()
    return retry_after_seconds(count, limit, ttl)
