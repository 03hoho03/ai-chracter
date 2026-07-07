import uuid
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code, store_verification_code
from api.core.config import settings
from api.db.models.auth import GuardianConsent, User


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


async def test_signup_creates_unverified_user_and_sends_code(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = _signup_payload()

    resp = await db_client.post("/auth/signup", json=payload)
    assert resp.status_code == 201
    assert resp.json() == {"email": payload["email"]}

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.email_verified_at is None
    assert user.password_hash is not None
    assert user.password_hash != payload["password"]

    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None
    assert len(stored["code"]) == 6


async def test_signup_rejects_short_password(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/signup", json=_signup_payload(password="short"))
    assert resp.status_code == 422


async def test_signup_rejects_invalid_email(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/signup", json=_signup_payload(email="not-an-email"))
    assert resp.status_code == 422


async def test_signup_rejects_missing_terms_agreement(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/signup", json=_signup_payload(termsAgreed=False))
    assert resp.status_code == 422


async def test_signup_rejects_missing_privacy_agreement(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/signup", json=_signup_payload(privacyAgreed=False))
    assert resp.status_code == 422


async def test_signup_rejects_duplicate_email(db_client: httpx.AsyncClient) -> None:
    payload = _signup_payload()
    first = await db_client.post("/auth/signup", json=payload)
    assert first.status_code == 201

    second = await db_client.post("/auth/signup", json=_signup_payload(email=payload["email"]))
    assert second.status_code == 409


async def test_verify_email_adult_does_not_require_guardian_consent(
    db_client: httpx.AsyncClient,
) -> None:
    payload = _signup_payload(birthDate="2000-01-01")
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"isMinorGuardianRequired": False}


async def test_verify_email_minor_requires_guardian_consent(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = _signup_payload(birthDate=minor_birth_date.isoformat())
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"isMinorGuardianRequired": True}


async def test_verify_email_rejects_wrong_code(db_client: httpx.AsyncClient) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
    )
    assert resp.status_code == 400


async def test_verify_email_unknown_user_returns_404(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/verify-email", json={"email": "nobody@example.com", "code": "123456"}
    )
    assert resp.status_code == 404


async def test_resend_within_cooldown_returns_429_with_retry_after(
    db_client: httpx.AsyncClient,
) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post("/auth/resend-verification-code", json={"email": payload["email"]})
    assert resp.status_code == 429
    assert resp.json()["detail"]["retryAfterSeconds"] > 0


async def test_resend_after_cooldown_issues_new_code(db_client: httpx.AsyncClient) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)
    original = await get_verification_code(str(payload["email"]))
    assert original is not None

    # Simulate the cooldown having already elapsed.
    await store_verification_code(
        str(payload["email"]), original["code"], datetime.now().astimezone() - timedelta(seconds=61)
    )

    resp = await db_client.post("/auth/resend-verification-code", json={"email": payload["email"]})
    assert resp.status_code == 204

    refreshed = await get_verification_code(str(payload["email"]))
    assert refreshed is not None


async def test_resend_unknown_user_returns_404(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/resend-verification-code", json={"email": "nobody@example.com"}
    )
    assert resp.status_code == 404


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


def _guardian_consent_payload(email: str, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": email,
        "guardianName": "홍길동",
        "guardianContact": "010-1234-5678",
        "consentAgreed": True,
    }
    defaults.update(overrides)
    return defaults


async def test_guardian_consent_activates_minor_account_and_issues_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())

    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert resp.status_code == 204
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    consent = await db_session.scalar(select(GuardianConsent).where(GuardianConsent.user_id == user.id))
    assert consent is not None
    assert consent.guardian_name == "홍길동"

    echo = await db_client.get("/dev/session-echo")
    assert echo.status_code == 200
    assert echo.json() == {"user_id": str(user.id)}


async def test_guardian_consent_rejects_before_email_verified(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = _signup_payload(birthDate=minor_birth_date.isoformat())
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert resp.status_code == 400


async def test_guardian_consent_rejects_adult_account(db_client: httpx.AsyncClient) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")

    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert resp.status_code == 400


async def test_guardian_consent_rejects_consent_not_agreed(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())

    resp = await db_client.post(
        "/auth/guardian-consent",
        json=_guardian_consent_payload(str(payload["email"]), consentAgreed=False),
    )
    assert resp.status_code == 422


async def test_guardian_consent_unknown_user_returns_404(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload("nobody@example.com")
    )
    assert resp.status_code == 404


async def test_login_adult_issues_session_and_me_returns_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json() == {
        "id": str(user.id),
        "email": user.email,
        "nickname": user.nickname,
        "bio": None,
        "profileImageAssetId": None,
    }


async def test_login_rejects_wrong_password(db_client: httpx.AsyncClient) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_login_rejects_unknown_email(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "password123"}
    )
    assert resp.status_code == 401


async def test_login_rejects_unverified_email(db_client: httpx.AsyncClient) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 403


async def test_login_rejects_minor_without_guardian_consent(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 403


async def test_login_succeeds_for_minor_with_guardian_consent(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())
    consent_resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert consent_resp.status_code == 204

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


async def test_me_without_session_returns_401(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/me")
    assert resp.status_code == 401


async def test_logout_invalidates_session(db_client: httpx.AsyncClient) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")
    login_resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204

    me_before = await db_client.get("/me")
    assert me_before.status_code == 200

    logout_resp = await db_client.post("/auth/logout")
    assert logout_resp.status_code == 204

    me_after = await db_client.get("/me")
    assert me_after.status_code == 401


async def test_logout_without_session_is_idempotent(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/logout")
    assert resp.status_code == 204
