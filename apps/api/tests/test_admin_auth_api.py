import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code
from api.core.config import settings
from api.core.security import hash_password
from api.db.models.auth import AdminUser


def _admin_payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password": "adminpassword123",
    }
    defaults.update(overrides)
    return defaults


async def _create_admin(db_session: AsyncSession, **overrides: object) -> dict[str, object]:
    payload = _admin_payload(**overrides)
    admin = AdminUser(
        email=str(payload["email"]), password_hash=hash_password(str(payload["password"]))
    )
    db_session.add(admin)
    await db_session.flush()
    return payload


async def _signup_and_login_user(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "테스터",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
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
