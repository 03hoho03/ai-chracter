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


def _key(email: str) -> str:
    return f"email_verification:{email}"


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def store_verification_code(email: str, code: str, sent_at: datetime) -> None:
    payload: VerificationCode = {"code": code, "sent_at": sent_at.isoformat()}
    await redis_client.set(
        _key(email), json.dumps(payload), ex=settings.email_verification_code_ttl_seconds
    )


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
