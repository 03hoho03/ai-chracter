from datetime import UTC, datetime, timedelta

from api.auth.verification import generate_code, seconds_until_resend_allowed


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
