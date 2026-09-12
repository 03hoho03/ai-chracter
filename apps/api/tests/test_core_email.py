import json
from collections.abc import Callable

import httpx
import pytest

from api.core.config import settings
from api.core.email import EmailSendError, get_email_sender, send_email_console, send_email_resend


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """core.email이 만드는 httpx.AsyncClient에 MockTransport를 주입한다
    (test_llm_cloudflare_image.py의 `_patch_httpx`와 동일 패턴)."""
    real_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("api.core.email.httpx.AsyncClient", factory)


async def test_send_email_console_prints_message(capsys: pytest.CaptureFixture[str]) -> None:
    await send_email_console("user@example.com", "제목", "본문")
    captured = capsys.readouterr()
    assert "user@example.com" in captured.out
    assert "제목" in captured.out
    assert "본문" in captured.out


def test_get_email_sender_defaults_to_console() -> None:
    assert settings.email_provider == "console"
    assert get_email_sender() is send_email_console


def test_get_email_sender_returns_resend_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "resend")
    assert get_email_sender() is send_email_resend


async def test_send_email_resend_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "email_from", "noreply@ddona.site")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "email_123"})

    _patch_httpx(monkeypatch, handler)
    await send_email_resend("user@example.com", "제목", "본문")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["authorization"] == "Bearer re_test_key"
    assert captured["body"] == {
        "from": "noreply@ddona.site",
        "to": ["user@example.com"],
        "subject": "제목",
        "text": "본문",
    }


async def test_send_email_resend_http_status_error_raises_email_send_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "invalid from address"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(EmailSendError):
        await send_email_resend("user@example.com", "제목", "본문")


async def test_send_email_resend_network_error_raises_email_send_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(EmailSendError):
        await send_email_resend("user@example.com", "제목", "본문")
