import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code
from api.core import rate_limit
from api.core.config import settings
from api.db.models.auth import AdminUser
from factories import _create_admin


async def _signup_and_login_user(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "테스터",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
        "transferAgreed": True,
    }
    defaults.update(overrides)
    await db_client.post("/auth/signup", json=defaults)
    stored = await get_verification_code(str(defaults["email"]))
    assert stored is not None
    verify_resp = await db_client.post(
        "/auth/verify-email", json={"email": defaults["email"], "code": stored["code"]}
    )
    assert verify_resp.status_code == 200
    login_resp = await db_client.post(
        "/auth/login", json={"email": defaults["email"], "password": defaults["password"]}
    )
    assert login_resp.status_code == 204
    return defaults


async def test_admin_login_issues_admin_session_and_me_returns_admin(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _create_admin(db_session)

    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204
    assert settings.admin_session_cookie_name in resp.cookies
    assert settings.session_cookie_name not in resp.cookies

    me = await db_client.get("/admin/me")
    assert me.status_code == 200
    admin = await db_session.scalar(select(AdminUser).where(AdminUser.email == payload["email"]))
    assert admin is not None
    assert me.json() == {"id": str(admin.id), "email": admin.email}


async def test_admin_login_rejects_wrong_password(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _create_admin(db_session)

    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_admin_login_rejects_unknown_email(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/admin/auth/login", json={"email": "nobody@example.com", "password": "password123"}
    )
    assert resp.status_code == 401


def _assert_auth_limit(resp: httpx.Response, *, window_seconds: int) -> int:
    """어드민 로그인 429 는 사용자 auth 429 와 같은 모양이다."""
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail == {
        "code": "AUTH_LIMIT",
        "retryAfterSeconds": detail.get("retryAfterSeconds"),
        "window": "auth",
    }
    retry_after = detail["retryAfterSeconds"]
    assert isinstance(retry_after, int) and 0 < retry_after <= window_seconds
    return retry_after


async def test_admin_login_rate_limited_by_ip(db_client: httpx.AsyncClient) -> None:
    for _ in range(rate_limit.ADMIN_LOGIN_IP_LIMIT):
        resp = await db_client.post(
            "/admin/auth/login", json={"email": f"nobody-{uuid.uuid4()}@example.com", "password": "x"}
        )
        assert resp.status_code == 401

    resp = await db_client.post(
        "/admin/auth/login", json={"email": f"nobody-{uuid.uuid4()}@example.com", "password": "x"}
    )
    _assert_auth_limit(resp, window_seconds=rate_limit.ADMIN_LOGIN_IP_WINDOW_SECONDS)


async def test_admin_login_rate_limited_by_email_even_with_correct_password(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _create_admin(db_session)
    for _ in range(rate_limit.ADMIN_LOGIN_EMAIL_LIMIT):
        resp = await db_client.post(
            "/admin/auth/login", json={"email": payload["email"], "password": "wrong-password"}
        )
        assert resp.status_code == 401

    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    retry_after = _assert_auth_limit(resp, window_seconds=rate_limit.ADMIN_LOGIN_EMAIL_WINDOW_SECONDS)
    # IP 창(10분)보다 길다 — 이 429 가 이메일 카운터(15분 창)에서 왔다.
    assert retry_after > rate_limit.ADMIN_LOGIN_IP_WINDOW_SECONDS
    assert settings.admin_session_cookie_name not in resp.cookies


async def test_admin_login_rate_limit_hits_at_the_same_attempt_for_unknown_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 두 이메일로 상한+1 회씩 보내면 IP 상한(10)을 먼저 넘으므로 이 테스트에서만 IP 상한을 올린다.
    monkeypatch.setattr(rate_limit, "ADMIN_LOGIN_IP_LIMIT", 100)
    payload = await _create_admin(db_session)
    for email in (payload["email"], f"nobody-{uuid.uuid4()}@example.com"):
        statuses = [
            (
                await db_client.post(
                    "/admin/auth/login", json={"email": email, "password": "wrong-password"}
                )
            ).status_code
            for _ in range(rate_limit.ADMIN_LOGIN_EMAIL_LIMIT + 1)
        ]
        assert statuses == [401] * rate_limit.ADMIN_LOGIN_EMAIL_LIMIT + [429]


async def test_admin_me_without_session_returns_401(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/admin/me")
    assert resp.status_code == 401


async def test_admin_logout_invalidates_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _create_admin(db_session)
    login_resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204

    logout_resp = await db_client.post("/admin/auth/logout")
    assert logout_resp.status_code == 204

    me = await db_client.get("/admin/me")
    assert me.status_code == 401


async def test_regular_user_session_cannot_access_admin_endpoints(
    db_client: httpx.AsyncClient,
) -> None:
    await _signup_and_login_user(db_client)

    me = await db_client.get("/admin/me")
    assert me.status_code == 401


async def test_admin_session_cannot_access_user_endpoints(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _create_admin(db_session)
    login_resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204

    me = await db_client.get("/me")
    assert me.status_code == 401
