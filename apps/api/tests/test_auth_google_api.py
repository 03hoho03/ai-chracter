import uuid
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.google_oauth import GoogleProfile, get_google_profile
from api.core.config import settings
from api.db.models.auth import GuardianConsent, User
from api.main import app


def _fake_profile(sub: str, email: str) -> GoogleProfile:
    return GoogleProfile(sub=sub, email=email)


def _override_google_profile(sub: str, email: str) -> None:
    app.dependency_overrides[get_google_profile] = lambda: _fake_profile(sub, email)


def _clear_google_profile_override() -> None:
    del app.dependency_overrides[get_google_profile]


async def test_google_login_redirects_to_google_auth_url(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/auth/google", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "redirect_uri=" in location
    assert "state=" in location


async def test_google_callback_rejects_unknown_state(db_client: httpx.AsyncClient) -> None:
    """소비된/위조된 state는 날것의 400이 아니라 로그인 화면으로 되돌린다 — 온보딩에서
    뒤로가기 후 계정 재선택처럼 정상 사용자도 도달하는 경로라, 브라우저에 JSON 본문이
    렌더링되는 막다른 페이지가 되면 안 된다."""
    _override_google_profile("google-sub-unknown-state", "unknown-state@example.com")
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": "not-a-real-state"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"
    finally:
        _clear_google_profile_override()


async def _start_google_login(db_client: httpx.AsyncClient, redirect: str = "/") -> str:
    start = await db_client.get("/auth/google", params={"redirect": redirect}, follow_redirects=False)
    location = start.headers["location"]
    state = httpx.URL(location).params["state"]
    return state


async def test_google_callback_new_user_redirects_to_onboarding_without_session(
    db_client: httpx.AsyncClient,
) -> None:
    state = await _start_google_login(db_client)
    _override_google_profile(f"google-sub-{uuid.uuid4()}", f"new-{uuid.uuid4()}@example.com")
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(f"{settings.frontend_base_url}/onboarding/google?token=")
        assert settings.session_cookie_name not in resp.cookies
    finally:
        _clear_google_profile_override()


async def _onboard_new_google_user(
    db_client: httpx.AsyncClient, birth_date: str, **overrides: object
) -> dict[str, object]:
    sub = f"google-sub-{uuid.uuid4()}"
    email = f"new-{uuid.uuid4()}@example.com"
    state = await _start_google_login(db_client)
    _override_google_profile(sub, email)
    try:
        callback = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()
    token = httpx.URL(callback.headers["location"]).params["token"]

    payload: dict[str, object] = {
        "token": token,
        "nickname": "구글유저",
        "birthDate": birth_date,
        "termsAgreed": True,
        "privacyAgreed": True,
    }
    payload.update(overrides)
    return {"payload": payload, "sub": sub, "email": email}


async def test_onboarding_google_adult_creates_user_and_issues_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")

    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 200
    assert resp.json() == {"isMinorGuardianRequired": False, "email": ctx["email"]}
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == ctx["email"]))
    assert user is not None
    assert user.google_sub == ctx["sub"]
    assert user.nickname == "구글유저"
    assert user.email_verified_at is not None

    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)


async def test_onboarding_google_minor_requires_guardian_consent_and_no_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10).isoformat()
    ctx = await _onboard_new_google_user(db_client, minor_birth_date)

    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 200
    assert resp.json() == {"isMinorGuardianRequired": True, "email": ctx["email"]}
    assert settings.session_cookie_name not in resp.cookies

    me = await db_client.get("/me")
    assert me.status_code == 401

    user = await db_session.scalar(select(User).where(User.email == ctx["email"]))
    assert user is not None

    consent_resp = await db_client.post(
        "/auth/guardian-consent",
        json={
            "email": ctx["email"],
            "guardianName": "홍길동",
            "guardianContact": "010-1234-5678",
            "consentAgreed": True,
        },
    )
    assert consent_resp.status_code == 204
    assert settings.session_cookie_name in consent_resp.cookies

    consent = await db_session.scalar(select(GuardianConsent).where(GuardianConsent.user_id == user.id))
    assert consent is not None


async def test_onboarding_google_rejects_missing_terms_agreement(db_client: httpx.AsyncClient) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01", termsAgreed=False)
    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 422


async def test_onboarding_google_rejects_invalid_token(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/onboarding/google",
        json={
            "token": "not-a-real-token",
            "nickname": "구글유저",
            "birthDate": "2000-01-01",
            "termsAgreed": True,
            "privacyAgreed": True,
        },
    )
    assert resp.status_code == 400


async def test_google_callback_existing_adult_user_issues_session_and_redirects(
    db_client: httpx.AsyncClient,
) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200
    db_client.cookies.clear()

    state = await _start_google_login(db_client, redirect="/mypage")
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/mypage"
    assert settings.session_cookie_name in resp.cookies


async def test_google_callback_links_existing_password_account_by_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    signup_payload = {
        "email": f"linked-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "패스워드유저",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
    }
    signup_resp = await db_client.post("/auth/signup", json=signup_payload)
    assert signup_resp.status_code == 201

    state = await _start_google_login(db_client)
    google_sub = f"google-sub-{uuid.uuid4()}"
    _override_google_profile(google_sub, str(signup_payload["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == signup_payload["email"]))
    assert user is not None
    assert user.google_sub == google_sub


async def test_google_callback_minor_without_consent_redirects_to_onboarding_again(
    db_client: httpx.AsyncClient,
) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10).isoformat()
    ctx = await _onboard_new_google_user(db_client, minor_birth_date)
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200
    assert settings.session_cookie_name not in onboard_resp.cookies

    state = await _start_google_login(db_client)
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"].startswith(f"{settings.frontend_base_url}/onboarding/google?token=")
    assert settings.session_cookie_name not in resp.cookies
