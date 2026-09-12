import logging

import pytest

from api.auth.emails import send_password_reset_email, send_verification_code_email
from api.core.email import EmailSendError


async def test_send_verification_code_email_calls_sender_with_code() -> None:
    captured: dict[str, str] = {}

    async def _sender(to: str, subject: str, body: str) -> None:
        captured["to"] = to
        captured["subject"] = subject
        captured["body"] = body

    await send_verification_code_email(_sender, "user@example.com", "123456")

    assert captured["to"] == "user@example.com"
    assert "123456" in captured["body"]


async def test_send_password_reset_email_calls_sender_with_link() -> None:
    captured: dict[str, str] = {}

    async def _sender(to: str, subject: str, body: str) -> None:
        captured["to"] = to
        captured["body"] = body

    await send_password_reset_email(_sender, "user@example.com", "https://ddona.site/reset?token=abc")

    assert captured["to"] == "user@example.com"
    assert "https://ddona.site/reset?token=abc" in captured["body"]


async def test_send_failure_is_logged_as_warning_and_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _failing_sender(to: str, subject: str, body: str) -> None:
        raise EmailSendError("boom")

    with caplog.at_level(logging.WARNING):
        await send_verification_code_email(_failing_sender, "user@example.com", "123456")

    assert any(record.levelno == logging.WARNING for record in caplog.records)
