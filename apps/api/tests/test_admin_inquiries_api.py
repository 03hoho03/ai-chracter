import uuid
from datetime import UTC, datetime, timedelta

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import AdminUser, Inquiry, InquiryCategory, InquiryStatus, Notification
from factories import _login_as, _login_as_admin, _make_user


async def _make_inquiry(db_session: AsyncSession, *, user_id: uuid.UUID, **overrides: object) -> Inquiry:
    defaults: dict[str, object] = {
        "user_id": user_id,
        "category": InquiryCategory.ACCOUNT,
        "title": "문의 제목",
        "body": "문의 본문",
        "status": InquiryStatus.PENDING,
    }
    defaults.update(overrides)
    inquiry = Inquiry(**defaults)
    db_session.add(inquiry)
    await db_session.flush()
    return inquiry


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


async def test_admin_inquiries_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/admin/inquiries?page=1")
    assert resp.status_code == 401


async def test_admin_inquiries_rejects_non_admin_user_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/admin/inquiries?page=1")
    assert resp.status_code == 401


async def test_admin_inquiry_detail_includes_author_info(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(nickname="문의러", email="inquirer@example.com")
    db_session.add(user)
    await db_session.flush()
    inquiry = await _make_inquiry(db_session, user_id=user.id)
    admin_payload = await _create_admin(db_session)
    await db_session.commit()

    await _login_as_admin(db_client, admin_payload)
    resp = await db_client.get(f"/admin/inquiries/{inquiry.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authorNickname"] == "문의러"
    assert body["authorEmail"] == "inquirer@example.com"


async def test_reply_answers_inquiry_and_notifies_only_target_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    target = _make_user()
    other = _make_user()
    db_session.add_all([target, other])
    await db_session.flush()
    inquiry = await _make_inquiry(db_session, user_id=target.id)
    admin_payload = await _create_admin(db_session)
    await db_session.commit()

    await _login_as_admin(db_client, admin_payload)
    resp = await db_client.post(f"/admin/inquiries/{inquiry.id}/reply", json={"replyBody": "답변입니다"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "answered"
    assert body["replyBody"] == "답변입니다"

    target_notifications = (
        (await db_session.execute(sa.select(Notification).where(Notification.user_id == target.id)))
        .scalars()
        .all()
    )
    assert len(target_notifications) == 1
    assert target_notifications[0].type == "inquiry-reply"
    assert target_notifications[0].inquiry_id == inquiry.id

    other_notifications = (
        (await db_session.execute(sa.select(Notification).where(Notification.user_id == other.id)))
        .scalars()
        .all()
    )
    assert other_notifications == []


async def test_replying_again_updates_body_without_duplicate_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    target = _make_user()
    db_session.add(target)
    await db_session.flush()
    inquiry = await _make_inquiry(db_session, user_id=target.id)
    admin_payload = await _create_admin(db_session)
    await db_session.commit()

    await _login_as_admin(db_client, admin_payload)
    first_resp = await db_client.post(
        f"/admin/inquiries/{inquiry.id}/reply", json={"replyBody": "오타있는 답변"}
    )
    assert first_resp.status_code == 200

    second_resp = await db_client.post(f"/admin/inquiries/{inquiry.id}/reply", json={"replyBody": "고친 답변"})
    assert second_resp.status_code == 200
    assert second_resp.json()["replyBody"] == "고친 답변"

    notifications = (
        (await db_session.execute(sa.select(Notification).where(Notification.user_id == target.id)))
        .scalars()
        .all()
    )
    assert len(notifications) == 1


async def test_admin_inquiry_list_filter_persists_across_pages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """techspec.md §4-4 — status·category 필터가 offset 페이징 경계(20건)를 넘어도
    유지돼야 한다. 노이즈(다른 카테고리·다른 상태)를 섞어 필터가 실제로 걸러내는지도
    같이 확인한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    now = datetime.now(UTC)
    for i in range(21):
        await _make_inquiry(
            db_session,
            user_id=user.id,
            category=InquiryCategory.BUG,
            status=InquiryStatus.PENDING,
            title=f"버그 문의 {i}",
            created_at=now - timedelta(minutes=i),
        )
    await _make_inquiry(
        db_session,
        user_id=user.id,
        category=InquiryCategory.ACCOUNT,
        status=InquiryStatus.PENDING,
        title="계정 문의(노이즈)",
    )
    await _make_inquiry(
        db_session,
        user_id=user.id,
        category=InquiryCategory.BUG,
        status=InquiryStatus.ANSWERED,
        title="답변된 버그 문의(노이즈)",
        reply_body="답변",
        answered_at=now,
    )
    admin_payload = await _create_admin(db_session)
    await db_session.commit()

    await _login_as_admin(db_client, admin_payload)

    page1 = await db_client.get("/admin/inquiries?page=1&status=pending&category=bug")
    assert page1.status_code == 200
    page1_body = page1.json()
    assert page1_body["totalCount"] == 21
    assert page1_body["totalPages"] == 2
    assert len(page1_body["items"]) == 20

    page2 = await db_client.get("/admin/inquiries?page=2&status=pending&category=bug")
    assert page2.status_code == 200
    page2_body = page2.json()
    assert page2_body["totalCount"] == 21
    assert len(page2_body["items"]) == 1
