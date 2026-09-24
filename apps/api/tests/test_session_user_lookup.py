"""backlog-sweep-goal-prompt.md BS-3 — 세션 의존성이 `users` 행을 직접 확인한다.

세션만 믿던 시절에는 탈퇴한 계정의 다른 기기 세션이 `users`를 안 보는 라우트를 그대로
통과했고, 존재하지 않는 user_id(dev 재시딩)는 쓰기 라우트에서 FK 위반이 됐다. 탈퇴는
`withdraw` 엔드포인트가 아니라 `deleted_at`을 직접 세운다 — 엔드포인트는 현재 세션을
지우므로(이후 단계에서는 다른 세션까지) 의존성 자체의 판정이 가려진다.
"""

import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import ContentVisibility, Like, User
from api.llm.local_image import LocalCapabilities
from api.main import app
from api.session.suspension import mark_user_suspended, unmark_user_suspended
from factories import _get_genre, _login_as, _make_published_character, _make_user


async def _logged_in_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/notifications", id="db-session-route"),
        # DB 세션을 따로 받지 않는 유일한 인증 라우트 — 의존성이 스스로 세션을 연다.
        pytest.param("/images/models", id="no-db-session-route"),
    ],
)
async def test_deleted_user_session_is_rejected_on_route_without_user_lookup(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    async def fake_get_capabilities() -> LocalCapabilities:
        return LocalCapabilities(ready=True, models=())

    monkeypatch.setattr("api.images.router.get_capabilities", fake_get_capabilities)
    user = await _logged_in_user(db_client, db_session)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    resp = await db_client.get(path)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


async def test_withdraw_then_other_device_session_gets_401(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_user(db_client, db_session)
    async with AsyncExitStack() as stack:
        # 같은 유저의 두 번째 기기. `app.dependency_overrides`가 전역이라 같은 DB 세션을 쓴다.
        other_device = await stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        )
        await _login_as(other_device, user.id)

        assert (await db_client.delete("/me")).status_code == 204
        resp = await other_device.get("/notifications")

    assert resp.status_code == 401


async def test_deleted_and_suspended_user_gets_401_not_403(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """조회(401)가 정지 마커(403)보다 먼저다 — 탈퇴 계정에 정지 안내를 띄우지 않는다."""
    user = await _logged_in_user(db_client, db_session)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()
    await mark_user_suspended(user.id)
    try:
        resp = await db_client.get("/notifications")
    finally:
        await unmark_user_suspended(user.id)

    assert resp.status_code == 401


async def test_deleted_owner_session_sees_only_public_contents(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_user(db_client, db_session)
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    content.visibility = ContentVisibility.PRIVATE
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "character"})

    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_session_for_nonexistent_user_is_a_guest_on_content_detail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """optional 쪽은 401이 아니라 비로그인으로 흡수한다 — 게스트 뷰어 쿠키가 구워지는 것이
    `user:` 뷰어 키가 아니라 게스트로 처리됐다는 관측 가능한 흔적이다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, uuid.uuid4())

    resp = await db_client.get(f"/contents/{content.id}")

    assert resp.status_code == 200
    assert settings.guest_viewer_cookie_name in resp.cookies


async def test_session_for_nonexistent_user_gets_401_not_integrity_error(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, uuid.uuid4())

    resp = await db_client.post(f"/contents/{content.id}/like")

    assert resp.status_code == 401
    like_count = await db_session.scalar(select(func.count()).select_from(Like).where(Like.content_id == content.id))
    assert like_count == 0
