import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code
from api.core.security import verify_password
from api.db.models.auth import User


def _signup_payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "테스터",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
    }
    defaults.update(overrides)
    return defaults


async def _signup_and_verify(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    payload = _signup_payload(**overrides)
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert resp.status_code == 200
    return payload


def _extract_token(reset_link: str) -> str:
    query = parse_qs(urlparse(reset_link).query)
    return query["token"][0]


async def _request_reset_and_capture_token(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, email: str
) -> str:
    captured: dict[str, str] = {}

    def _capture(to: str, reset_link: str) -> None:
        captured["to"] = to
        captured["reset_link"] = reset_link

    monkeypatch.setattr("api.auth.router.send_password_reset_email", _capture)

    resp = await db_client.post("/auth/password-reset/request", json={"email": email})
    assert resp.status_code == 204
    assert captured["to"] == email
    return _extract_token(captured["reset_link"])


async def test_request_password_reset_for_registered_user_sends_email(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")

    token = await _request_reset_and_capture_token(db_client, monkeypatch, str(payload["email"]))
    assert token


async def test_request_password_reset_for_unknown_email_returns_same_response(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def _capture(to: str, reset_link: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("api.auth.router.send_password_reset_email", _capture)

    resp = await db_client.post(
        "/auth/password-reset/request", json={"email": "nobody@example.com"}
    )
    assert resp.status_code == 204
    assert called is False


async def test_validate_valid_token_returns_200(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")
    token = await _request_reset_and_capture_token(db_client, monkeypatch, str(payload["email"]))

    resp = await db_client.get("/auth/password-reset/validate", params={"token": token})
    assert resp.status_code == 200


async def test_validate_unknown_token_returns_400(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/auth/password-reset/validate", params={"token": "does-not-exist"})
    assert resp.status_code == 400


async def test_confirm_updates_password_and_login_works(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")
    token = await _request_reset_and_capture_token(db_client, monkeypatch, str(payload["email"]))

    resp = await db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "new-password123"}
    )
    assert resp.status_code == 204

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.password_hash is not None
    assert verify_password("new-password123", user.password_hash)

    old_login = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert old_login.status_code == 401

    new_login = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": "new-password123"}
    )
    assert new_login.status_code == 204


async def test_confirm_rejects_unknown_token(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/password-reset/confirm", json={"token": "does-not-exist", "newPassword": "new-password123"}
    )
    assert resp.status_code == 400


async def test_confirm_rejects_short_new_password(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")
    token = await _request_reset_and_capture_token(db_client, monkeypatch, str(payload["email"]))

    resp = await db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "short"}
    )
    assert resp.status_code == 422


async def test_confirm_token_cannot_be_reused(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")
    token = await _request_reset_and_capture_token(db_client, monkeypatch, str(payload["email"]))

    first = await db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "new-password123"}
    )
    assert first.status_code == 204

    second = await db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "another-password123"}
    )
    assert second.status_code == 400

    validate_after_use = await db_client.get("/auth/password-reset/validate", params={"token": token})
    assert validate_after_use.status_code == 400
