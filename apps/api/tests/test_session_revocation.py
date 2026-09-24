"""backlog-sweep-goal-prompt.md BS-6 — 어느 경로가 그 유저의 세션을 폐기하는가.

| 경로 | 폐기 범위 |
|---|---|
| 탈퇴 | 전부 |
| 비밀번호 변경 | 현재 세션만 남긴다 |
| 비밀번호 재설정 | 전부 |
| 관리자 정지 | 폐기하지 않는다(마커가 403으로 막는다 — Q-2) |
"""

import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.password_reset import store_reset_token
from api.core.config import settings
from api.core.redis import redis_client
from api.core.security import hash_password
from api.db.models import User
from factories import _create_admin, _login_as, _login_as_admin, _make_user

_PASSWORD = "oldpassword123"


async def _session_alive(session_id: str) -> bool:
    return bool(await redis_client.exists(f"session:{session_id}"))


async def _other_device_session(user_id: uuid.UUID) -> str:
    """같은 유저의 두 번째 기기 세션 id. 쿠키 jar로만 쓰는 클라이언트라 요청은 보내지 않는다."""
    async with httpx.AsyncClient() as other_device:
        await _login_as(other_device, user_id)
        session_id = other_device.cookies[settings.session_cookie_name]
    return session_id


async def _user_with_two_sessions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[User, str, str]:
    user = _make_user(password_hash=hash_password(_PASSWORD))
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    current = db_client.cookies[settings.session_cookie_name]
    other = await _other_device_session(user.id)
    return user, current, other


async def test_withdraw_revokes_every_session_of_the_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, current, other = await _user_with_two_sessions(db_client, db_session)

    assert (await db_client.delete("/me")).status_code == 204

    assert not await _session_alive(current)
    assert not await _session_alive(other)


async def test_change_password_revokes_other_sessions_but_keeps_current(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, current, other = await _user_with_two_sessions(db_client, db_session)

    resp = await db_client.patch(
        "/me/password", json={"currentPassword": _PASSWORD, "newPassword": "newpassword456"}
    )

    assert resp.status_code == 204
    assert not await _session_alive(other)
    assert await _session_alive(current)
    assert (await db_client.get("/me")).status_code == 200


async def test_password_reset_revokes_every_session_of_the_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, current, other = await _user_with_two_sessions(db_client, db_session)
    token = await store_reset_token(user.id)

    resp = await db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "new-password123"}
    )

    assert resp.status_code == 204
    assert not await _session_alive(current)
    assert not await _session_alive(other)


async def test_password_reset_rejects_token_of_withdrawn_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """backlog-sweep-goal-prompt.md M-5 — 탈퇴 전에 발급된 토큰이 탈퇴 때 파기한 `password_hash`를
    되살리지 못한다(없는 유저와 같은 400)."""
    user = _make_user(deleted_at=datetime.now(UTC), password_hash=None)
    db_session.add(user)
    await db_session.commit()
    token = await store_reset_token(user.id)

    resp = await db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "new-password123"}
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired token"
    await db_session.refresh(user)
    assert user.password_hash is None


async def test_suspend_keeps_existing_sessions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지는 세션을 지우지 않는다 — 지우면 다음 요청이 403이 아니라 401이 되어 FE가 정지 안내를
    못 띄운다. 차단은 `test_admin_users_api.py::test_suspend_blocks_existing_session_immediately`가 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    session_id = db_client.cookies[settings.session_cookie_name]
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/suspend", json={"reasonCategory": "spam"})

    assert resp.status_code == 200
    assert await _session_alive(session_id)
