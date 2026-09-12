import json
import math
import secrets
from datetime import datetime
from typing import TypedDict

from api.core.config import settings
from api.core.redis import redis_client


class VerificationCode(TypedDict):
    code: str
    sent_at: str


# email-goal-prompt.md E-7: 인증 코드 1건의 수명 동안 허용하는 오답 횟수.
VERIFICATION_ATTEMPTS_LIMIT = 5


def _key(email: str) -> str:
    return f"email_verification:{email}"


def _attempts_key(email: str) -> str:
    return f"email_verification_attempts:{email}"


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def increment_verification_attempts(email: str) -> int:
    """오답마다 호출한다. `EXPIRE ... NX`는 코드와 같은 길이(`email_verification_code_ttl_seconds`)의
    TTL을 걸지만, 기산 시점은 코드 발급이 아니라 **이 카운터 키가 처음 생기는 시점(=최초 오답)**이다.
    최초 오답이 코드 발급보다 늦으면 카운터가 코드보다 그만큼 늦게 만료돼, "코드는 만료됐는데
    카운터만 살아있는" 상태가 가능하다. 동작에는 영향 없다 — 코드가 없으면 `get_verification_code`가
    None을 반환해 오답과 같은 분기를 타고, 새 코드가 발급되면 `store_verification_code`가 카운터를
    지운다(E-7a). `rate_limit.check_rate_limit`과 같은 이유로 INCR과 EXPIRE NX를 한 파이프라인
    (MULTI/EXEC)에 묶는다(email-goal-prompt.md E-7)."""
    key = _attempts_key(email)
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, settings.email_verification_code_ttl_seconds, nx=True)
        count, _ = await pipe.execute()
    return int(count)


async def clear_verification_attempts(email: str) -> None:
    await redis_client.delete(_attempts_key(email))


async def store_verification_code(email: str, code: str, sent_at: datetime) -> None:
    payload: VerificationCode = {"code": code, "sent_at": sent_at.isoformat()}
    await redis_client.set(
        _key(email), json.dumps(payload), ex=settings.email_verification_code_ttl_seconds
    )
    # email-goal-prompt.md E-7: 새 코드가 저장되면 이전 코드의 오답 횟수는 의미가 없다 —
    # 재전송이 "복구"가 되려면 시도 횟수도 함께 초기화돼야 한다.
    await clear_verification_attempts(email)


async def get_verification_code(email: str) -> VerificationCode | None:
    raw = await redis_client.get(_key(email))
    if raw is None:
        return None
    data: VerificationCode = json.loads(raw)
    return data


async def delete_verification_code(email: str) -> None:
    await redis_client.delete(_key(email))


def seconds_until_resend_allowed(sent_at: datetime, now: datetime, cooldown_seconds: int) -> int:
    """Pure function so the cooldown rule is unit-testable without Redis.

    Returns 0 once a resend is allowed, otherwise the whole seconds remaining
    (rounded up so callers never tell a client to retry a fraction early).
    """
    remaining = cooldown_seconds - (now - sent_at).total_seconds()
    return max(0, math.ceil(remaining))
