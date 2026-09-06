"""3단계 §2 — 유저 정지 차단 메커니즘 (TS-2~TS-5).

유저 제재 API(`POST /admin/users/{id}/suspend` 등)는 아직 없으므로, `suspended_at`과
Redis 마커를 테스트에서 직접 세팅해 차단 메커니즘만 검증한다.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.verification import get_verification_code
from api.core.redis import redis_client
from api.core.security import hash_password
from api.db.models.auth import AdminUser, User
from api.session.suspension import (
    SUSPENDED_USER_KEY_PREFIX,
    is_user_suspended,
    mark_user_suspended,
    rebuild_suspended_user_markers,
    unmark_user_suspended,
)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_suspension_markers() -> AsyncGenerator[None, None]:
    """정지 마커는 TTL이 없고 Redis DB 1은 테스트 세션 전체가 공유한다 — 어서션 실패로
    각 테스트의 try/finally 정리가 스킵돼도 다음 테스트에 새지 않도록 방어한다."""
    yield
    async for key in redis_client.scan_iter(match=f"{SUSPENDED_USER_KEY_PREFIX}*"):
        await redis_client.delete(key)


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
    verify_resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert verify_resp.status_code == 200
    return payload


async def _signup_and_login(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    payload = await _signup_and_verify(db_client, **overrides)
    login_resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204
    return payload


# ---------------------------------------------------------------------------
# 마커 CRUD (TS-3) — Redis만, HTTP 없음
# ---------------------------------------------------------------------------


async def test_mark_unmark_is_suspended_round_trip() -> None:
    user_id = uuid.uuid4()
    assert not await is_user_suspended(user_id)

    await mark_user_suspended(user_id)
    assert await is_user_suspended(user_id)

    await unmark_user_suspended(user_id)
    assert not await is_user_suspended(user_id)


# ---------------------------------------------------------------------------
# 차단 지점 (§2-1) — get_current_user_id / get_current_user_id_optional
# ---------------------------------------------------------------------------


async def test_suspended_marker_blocks_existing_session_with_403(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """회귀: 정지는 재로그인 없이 기존 세션에 즉시 발효돼야 한다(D-6) — 401(미인증)이
    아니라 403(인증은 됐지만 권한이 막힘)이어야 한다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    before = await db_client.get("/me")
    assert before.status_code == 200

    await mark_user_suspended(user.id)
    after = await db_client.get("/me")
    assert after.status_code == 403


async def test_unmark_restores_access_with_same_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    await mark_user_suspended(user.id)
    blocked = await db_client.get("/me")
    assert blocked.status_code == 403

    await unmark_user_suspended(user.id)
    restored = await db_client.get("/me")
    assert restored.status_code == 200


async def test_optional_dependency_treats_suspended_user_as_logged_out(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`GET /users/{id}/contents`는 로그인 시 추가 정보를 주는 공개 조회다 — 정지된
    조회자는 403이 아니라 비로그인과 같이 200을 받아야 한다(공개 조회 자체는 깨지면
    안 된다)."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    await mark_user_suspended(user.id)
    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "character"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 로그인 경로 가드 — 정지된 계정은 새 세션을 못 받는다
# ---------------------------------------------------------------------------


async def test_login_rejects_suspended_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_verify(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user.suspended_at = datetime.now(UTC)
    await db_session.flush()

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Account suspended"


# ---------------------------------------------------------------------------
# 어드민 인증은 완전히 별개 스택 — 정지 마커의 영향을 받지 않는다
# ---------------------------------------------------------------------------


async def test_admin_endpoints_ignore_suspended_user_marker(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`admin_users`는 `users`와 별개 테이블·별개 인증 스택이다(techspec §2-1) —
    어드민 본인의 id로 정지 마커가 세팅돼 있어도(우연한 UUID 충돌을 흉내) 어드민
    세션은 영향을 받지 않아야 한다."""
    email = f"admin-{uuid.uuid4()}@example.com"
    password = "adminpassword123"
    admin = AdminUser(email=email, password_hash=hash_password(password))
    db_session.add(admin)
    await db_session.flush()

    login_resp = await db_client.post(
        "/admin/auth/login", json={"email": email, "password": password}
    )
    assert login_resp.status_code == 204

    await mark_user_suspended(admin.id)
    me = await db_client.get("/admin/me")
    assert me.status_code == 200


# ---------------------------------------------------------------------------
# lifespan 마커 재구축 (TS-4) — 훅 자체가 아니라 분리된 함수를 직접 호출해 검증한다
# (테스트 클라이언트가 httpx.ASGITransport라 lifespan 프로토콜 자체가 오지 않는다)
# ---------------------------------------------------------------------------


async def test_rebuild_suspended_user_markers_restores_marker_from_db(
    db_session: AsyncSession,
) -> None:
    user = User(
        email=f"suspended-{uuid.uuid4()}@example.com",
        nickname="정지유저",
        birth_date=datetime.now(UTC).date(),
        terms_agreed_at=datetime.now(UTC),
        privacy_agreed_at=datetime.now(UTC),
        suspended_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()

    # Redis 볼륨 유실을 흉내: DB엔 suspended_at이 있지만 마커는 없는 상태에서 시작.
    assert not await is_user_suspended(user.id)

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await rebuild_suspended_user_markers(session_factory)

    assert await is_user_suspended(user.id)


async def test_rebuild_suspended_user_markers_skips_deleted_users(
    db_session: AsyncSession,
) -> None:
    user = User(
        email=f"deleted-{uuid.uuid4()}@example.com",
        nickname="탈퇴유저",
        birth_date=datetime.now(UTC).date(),
        terms_agreed_at=datetime.now(UTC),
        privacy_agreed_at=datetime.now(UTC),
        suspended_at=datetime.now(UTC),
        deleted_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await rebuild_suspended_user_markers(session_factory)

    assert not await is_user_suspended(user.id)
