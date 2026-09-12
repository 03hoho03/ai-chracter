import uuid
from datetime import UTC, datetime, timedelta

from api.auth.verification import (
    VERIFICATION_ATTEMPTS_LIMIT,
    clear_verification_attempts,
    generate_code,
    increment_verification_attempts,
    seconds_until_resend_allowed,
    store_verification_code,
)
from api.core.config import settings
from api.core.redis import redis_client


def test_generate_code_is_six_digits() -> None:
    code = generate_code()
    assert len(code) == 6
    assert code.isdigit()


def test_seconds_until_resend_allowed_within_cooldown() -> None:
    now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    sent_at = now - timedelta(seconds=10)
    assert seconds_until_resend_allowed(sent_at, now, cooldown_seconds=60) == 50


def test_seconds_until_resend_allowed_after_cooldown() -> None:
    now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    sent_at = now - timedelta(seconds=60)
    assert seconds_until_resend_allowed(sent_at, now, cooldown_seconds=60) == 0


def test_seconds_until_resend_allowed_well_after_cooldown() -> None:
    now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    sent_at = now - timedelta(seconds=120)
    assert seconds_until_resend_allowed(sent_at, now, cooldown_seconds=60) == 0


async def test_increment_verification_attempts_counts_up() -> None:
    email = f"attempts-{uuid.uuid4()}@example.com"
    assert await increment_verification_attempts(email) == 1
    assert await increment_verification_attempts(email) == 2


async def test_increment_verification_attempts_sets_ttl_matching_code_ttl() -> None:
    """email-goal-prompt.md E-7: TTL은 코드 TTL과 동일해야 한다."""
    email = f"attempts-ttl-{uuid.uuid4()}@example.com"
    await increment_verification_attempts(email)
    ttl = await redis_client.ttl(f"email_verification_attempts:{email}")
    assert 0 < ttl <= settings.email_verification_code_ttl_seconds


async def test_clear_verification_attempts_removes_counter() -> None:
    email = f"attempts-clear-{uuid.uuid4()}@example.com"
    await increment_verification_attempts(email)
    await clear_verification_attempts(email)
    assert await redis_client.get(f"email_verification_attempts:{email}") is None


async def test_store_verification_code_resets_attempts_counter() -> None:
    """email-goal-prompt.md E-7: 재전송(=새 코드 저장)은 이전 코드의 오답 횟수를 초기화한다
    — 안 그러면 재전송으로 "복구"돼야 할 사용자가 새 코드에서 곧바로 재잠긴다."""
    email = f"attempts-reset-{uuid.uuid4()}@example.com"
    for _ in range(VERIFICATION_ATTEMPTS_LIMIT - 1):
        await increment_verification_attempts(email)

    await store_verification_code(email, "123456", datetime.now(UTC))

    assert await redis_client.get(f"email_verification_attempts:{email}") is None
