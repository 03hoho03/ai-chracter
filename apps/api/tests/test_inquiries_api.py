import uuid

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Inquiry, InquiryCategory, InquiryStatus
from factories import _login_as, _make_asset, _make_user


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


async def test_create_inquiry_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/inquiries", json={"category": "account", "title": "제목", "body": "본문"})
    assert resp.status_code == 401


async def test_create_inquiry_without_attachment_succeeds(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post("/inquiries", json={"category": "account", "title": "제목", "body": "본문"})
    assert resp.status_code == 201
    inquiry_id = resp.json()["id"]

    detail_resp = await db_client.get(f"/me/inquiries/{inquiry_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["status"] == "pending"
    assert body["attachmentUrl"] is None


async def test_create_inquiry_with_own_attachment_succeeds(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_asset(db_session, owner_user_id=user.id, storage_key_prefix="assets/inquiry-attachment/")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/inquiries",
        json={"category": "bug", "title": "제목", "body": "본문", "attachmentAssetId": str(asset.id)},
    )
    assert resp.status_code == 201

    detail_resp = await db_client.get(f"/me/inquiries/{resp.json()['id']}")
    assert detail_resp.json()["attachmentUrl"] is not None


async def test_create_inquiry_with_other_users_attachment_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소유권 검증 — 존재하지 않는 asset_id가 아니라, 다른 유저가 실제로 소유한
    asset으로 검증해야 이 단언이 항진명제가 아니다."""
    user = _make_user()
    other = _make_user()
    db_session.add_all([user, other])
    await db_session.flush()
    other_asset = await _make_asset(
        db_session, owner_user_id=other.id, storage_key_prefix="assets/inquiry-attachment/"
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/inquiries",
        json={
            "category": "bug",
            "title": "제목",
            "body": "본문",
            "attachmentAssetId": str(other_asset.id),
        },
    )
    assert resp.status_code == 403

    inquiries = (await db_session.execute(sa.select(Inquiry).where(Inquiry.user_id == user.id))).scalars().all()
    assert inquiries == []


async def test_get_my_inquiry_detail_rejects_other_users_inquiry_with_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    inquiry = await _make_inquiry(db_session, user_id=owner.id)
    await db_session.commit()

    await _login_as(db_client, other.id)
    resp = await db_client.get(f"/me/inquiries/{inquiry.id}")
    assert resp.status_code == 404


async def test_list_my_inquiries_returns_only_own(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    await _make_inquiry(db_session, user_id=other.id, title="남의 문의")
    mine = await _make_inquiry(db_session, user_id=owner.id, title="내 문의")
    await db_session.commit()

    await _login_as(db_client, owner.id)
    resp = await db_client.get("/me/inquiries")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["id"] for item in items] == [str(mine.id)]
