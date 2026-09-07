import uuid
from datetime import date, datetime, timedelta, timezone, UTC

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    AdminUser,
    Content,
    ContentTarget,
    ContentType,
    ContentVisibility,
    Genre,
    ModerationAction,
    ModerationActionType,
    ModerationStatus,
    Notice,
    Notification,
    User,
)
from test_admin_users_api import _count_queries


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(UTC),
        "privacy_agreed_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_admin(**overrides: object) -> AdminUser:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password_hash": "hashed",
    }
    defaults.update(overrides)
    return AdminUser(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    """Logs in via the existing dev session-echo endpoint (no real /auth/login yet)."""
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _make_content(db_session: AsyncSession, creator_user_id: uuid.UUID) -> Content:
    genre = (await db_session.execute(sa.select(Genre).limit(1))).scalars().one()
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def _make_action(db_session: AsyncSession, content: Content) -> ModerationAction:
    admin = _make_admin()
    db_session.add(admin)
    await db_session.flush()
    action = ModerationAction(
        content_id=content.id, admin_id=admin.id, action=ModerationActionType.RESTRICT
    )
    db_session.add(action)
    await db_session.flush()
    return action


async def _make_notification(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: Content,
    action: ModerationAction,
    created_at: datetime | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        content_id=content.id,
        action_id=action.id,
        reason_category="adult",
        admin_comment="부적절한 콘텐츠로 판단되어 이용제한 처리되었습니다.",
    )
    db_session.add(notification)
    await db_session.flush()
    if created_at is not None:
        await db_session.execute(
            sa.update(Notification).where(Notification.id == notification.id).values(created_at=created_at)
        )
        await db_session.refresh(notification)
    return notification


async def _make_account_notification(
    db_session: AsyncSession, *, user_id: uuid.UUID, notification_type: str = "user-warned"
) -> Notification:
    """techspec.md §1-2 완화 회귀 — 콘텐츠와 무관한 계정 단위 알림(경고/정지)은
    content_id/action_id가 둘 다 null이다."""
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        content_id=None,
        action_id=None,
        reason_category="other",
        admin_comment="이용 규칙 위반으로 경고 처리되었습니다.",
    )
    db_session.add(notification)
    await db_session.flush()
    return notification


async def _make_notice_notification(db_session: AsyncSession, *, user_id: uuid.UUID, title: str) -> Notification:
    """공지 알림(T-11b) — 공지 하나당 알림 하나다. `ux_notifications_notice_user` 부분
    유니크 인덱스가 (notice_id, user_id) 조합을 유일하게 강제하므로, 알림을 여러 건
    만들려면 공지 자체를 여러 개 만들어야 한다(같은 공지에 두 번 못 받는다)."""
    notice = Notice(title=title, body_markdown="본문", published=True, published_at=datetime.now(UTC))
    db_session.add(notice)
    await db_session.flush()
    notification = Notification(user_id=user_id, type="notice", notice_id=notice.id)
    db_session.add(notification)
    await db_session.flush()
    return notification


async def test_list_notifications_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/notifications")
    assert resp.status_code == 401


async def test_list_notifications_returns_empty_list_when_none_exist(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_notifications_returns_own_notifications_newest_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, user.id)
    action = await _make_action(db_session, content)

    now = datetime.now(UTC)
    older = await _make_notification(
        db_session, user_id=user.id, content=content, action=action, created_at=now - timedelta(hours=1)
    )
    newer = await _make_notification(
        db_session, user_id=user.id, content=content, action=action, created_at=now
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200

    body = resp.json()
    assert [item["id"] for item in body] == [str(newer.id), str(older.id)]
    first = body[0]
    assert first["type"] == "moderation-action"
    assert first["contentId"] == str(content.id)
    assert first["actionId"] == str(action.id)
    assert first["reasonCategory"] == "adult"
    assert first["adminComment"]
    assert first["read"] is False


async def test_list_notifications_excludes_other_users_notifications(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_content(db_session, other.id)
    action = await _make_action(db_session, content)
    await _make_notification(db_session, user_id=other.id, content=content, action=action)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_mark_notification_read_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(f"/notifications/{uuid.uuid4()}/read")
    assert resp.status_code == 401


async def test_mark_notification_read_marks_own_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, user.id)
    action = await _make_action(db_session, content)
    notification = await _make_notification(db_session, user_id=user.id, content=content, action=action)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(f"/notifications/{notification.id}/read")
    assert resp.status_code == 200
    assert resp.json()["read"] is True

    await db_session.refresh(notification)
    assert notification.read is True


async def test_mark_notification_read_rejects_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_content(db_session, owner.id)
    action = await _make_action(db_session, content)
    notification = await _make_notification(db_session, user_id=owner.id, content=content, action=action)
    await db_session.commit()

    await _login_as(db_client, other.id)
    resp = await db_client.patch(f"/notifications/{notification.id}/read")
    assert resp.status_code == 403

    await db_session.refresh(notification)
    assert notification.read is False


async def test_mark_notification_read_unknown_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(f"/notifications/{uuid.uuid4()}/read")
    assert resp.status_code == 404


async def test_list_notifications_includes_null_content_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """회귀(techspec.md §1-2/§9): content_id/action_id가 null인 알림도 `GET /notifications`가
    500 대신 200으로 내려줘야 한다 — 계정 단위 조치(경고/정지)는 콘텐츠와 무관하다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    notification = await _make_account_notification(db_session, user_id=user.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200

    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(notification.id)
    assert body[0]["type"] == "user-warned"
    assert body[0]["contentId"] is None
    assert body[0]["actionId"] is None


async def test_mark_notification_read_works_for_null_content_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """회귀(techspec.md §1-2/§9): `PATCH /notifications/{id}/read`도 content_id/action_id가
    null인 행에서 깨지지 않아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    notification = await _make_account_notification(db_session, user_id=user.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.patch(f"/notifications/{notification.id}/read")
    assert resp.status_code == 200
    body = resp.json()
    assert body["read"] is True
    assert body["contentId"] is None
    assert body["actionId"] is None


async def test_list_notifications_fills_title_for_notice_type(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """techspec.md §4-5 — notice 알림은 `noticeId`가 가리키는 `Notice.title`을 응답의
    `title`에 채우고, 조치 통지 3종처럼 `reasonCategory`/`adminComment`를 요구하지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    notification = await _make_notice_notification(db_session, user_id=user.id, title="점검 안내")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/notifications")
    assert resp.status_code == 200

    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(notification.id)
    assert body[0]["type"] == "notice"
    assert body[0]["noticeId"] == str(notification.notice_id)
    assert body[0]["title"] == "점검 안내"
    assert body[0]["reasonCategory"] is None
    assert body[0]["adminComment"] is None


async def test_list_notifications_query_count_independent_of_notice_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """techspec.md §4-5 — notice_id가 있는 알림의 제목을 IN 조회 한 번으로 가져오므로, 공지
    알림이 여러 건이어도 쿼리 수가 늘지 않아야 한다(N+1 없음). `test_admin_users_api.py`의
    `_count_queries`(`before_cursor_execute` 카운터)를 재사용한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_notice_notification(db_session, user_id=user.id, title="공지 1")
    await db_session.commit()

    await _login_as(db_client, user.id)

    with _count_queries() as get_count:
        resp = await db_client.get("/notifications")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    query_count_with_one_notice = get_count()

    for i in range(2, 7):
        await _make_notice_notification(db_session, user_id=user.id, title=f"공지 {i}")
    await db_session.commit()

    with _count_queries() as get_count:
        resp = await db_client.get("/notifications")
    assert resp.status_code == 200
    assert len(resp.json()) == 6
    assert get_count() == query_count_with_one_notice
