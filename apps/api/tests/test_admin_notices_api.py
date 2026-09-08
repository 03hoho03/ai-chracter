import uuid
from datetime import UTC, datetime, timedelta

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import AdminUser, Notice, Notification
from factories import _login_as_admin, _make_user


async def _make_notice(
    db_session: AsyncSession,
    *,
    title: str = "공지",
    body_markdown: str = "본문",
    published: bool = False,
    published_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Notice:
    notice = Notice(
        title=title,
        body_markdown=body_markdown,
        published=published,
        published_at=published_at,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db_session.add(notice)
    await db_session.flush()
    return notice


async def _create_admin(db_session: AsyncSession, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password": "adminpassword123",
    }
    defaults.update(overrides)
    admin = AdminUser(
        email=str(defaults["email"]), password_hash=hash_password(str(defaults["password"]))
    )
    db_session.add(admin)
    await db_session.flush()
    return defaults


async def _notification_count(db_session: AsyncSession, notice_id: uuid.UUID) -> int:
    result = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(Notification)
        .where(Notification.notice_id == notice_id)
    )
    return result or 0


# ---- 인증 -------------------------------------------------------------------


async def test_list_admin_notices_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/admin/notices?page=1")
    assert resp.status_code == 401


async def test_regular_user_session_cannot_list_admin_notices(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    resp = await db_client.post("/dev/session-echo", json={"data": {"user_id": str(user.id)}})
    assert resp.status_code == 201

    resp = await db_client.get("/admin/notices?page=1")
    assert resp.status_code == 401


# ---- CRUD -------------------------------------------------------------------


async def test_create_notice_starts_unpublished(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        "/admin/notices", json={"title": "새 공지", "bodyMarkdown": "내용"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["published"] is False
    assert body["publishedAt"] is None


async def test_patch_updates_title_and_body(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    notice = await _make_notice(db_session, title="원제목", body_markdown="원본")
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.patch(f"/admin/notices/{notice.id}", json={"title": "새 제목"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "새 제목"
    assert body["bodyMarkdown"] == "원본"


async def test_admin_list_includes_unpublished(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _make_notice(db_session, title="미게시", published=False)
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/notices?page=1")
    assert resp.status_code == 200
    titles = [item["title"] for item in resp.json()["items"]]
    assert "미게시" in titles


async def test_admin_list_pagination_across_21_items(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # `created_at`을 명시적으로 벌려 둔다 — 한 테스트 트랜잭션 안에서는 `now()`가
    # 트랜잭션 시작 시각으로 고정돼(apps/api/CLAUDE.md §테스트 인프라) server_default로
    # 21개를 만들면 전부 같은 `created_at`이 되고, 그러면 `ORDER BY created_at DESC`
    # 페이지네이션에서 동률 행의 순서가 두 조회 사이에 안정된다는 보장이 없다.
    base = datetime.now(UTC)
    for i in range(21):
        await _make_notice(db_session, title=f"공지 {i}", created_at=base - timedelta(seconds=i))
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    first = await db_client.get("/admin/notices?page=1")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["totalCount"] == 21
    assert first_body["totalPages"] == 2
    assert len(first_body["items"]) == 20

    second = await db_client.get("/admin/notices?page=2")
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1

    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


# ---- 게시 fan-out -------------------------------------------------------------


async def test_publish_notifies_alive_users_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    alive_a = _make_user()
    alive_b = _make_user()
    deleted = _make_user(deleted_at=datetime.now(UTC))
    db_session.add_all([alive_a, alive_b, deleted])
    notice = await _make_notice(db_session)
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/notices/{notice.id}/publish")
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] is True
    assert body["publishedAt"] is not None

    count = await _notification_count(db_session, notice.id)
    assert count == 2

    notified_user_ids = (
        await db_session.scalars(
            sa.select(Notification.user_id).where(Notification.notice_id == notice.id)
        )
    ).all()
    assert set(notified_user_ids) == {alive_a.id, alive_b.id}


async def test_republish_after_unpublish_does_not_duplicate_notifications(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    notice = await _make_notice(db_session)
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    first_publish = await db_client.post(f"/admin/notices/{notice.id}/publish")
    assert first_publish.status_code == 200
    original_published_at = first_publish.json()["publishedAt"]

    unpublish_resp = await db_client.post(f"/admin/notices/{notice.id}/unpublish")
    assert unpublish_resp.status_code == 200
    assert unpublish_resp.json()["published"] is False

    second_publish = await db_client.post(f"/admin/notices/{notice.id}/publish")
    assert second_publish.status_code == 200
    assert second_publish.json()["published"] is True
    assert second_publish.json()["publishedAt"] == original_published_at

    count = await _notification_count(db_session, notice.id)
    assert count == 1
