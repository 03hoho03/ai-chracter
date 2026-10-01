import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Inquiry, InquiryCategory, InquiryStatus
from factories import _login_as, _make_asset, _make_user, _set_signing_clock


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


async def test_my_inquiry_attachment_url_is_signed_afresh_on_every_request(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """첨부 주소는 같은 15분 구간 안에서도 요청마다 새로 서명된다 — 구간 서명으로 바뀌면 1초 간격의
    두 응답이 같은 URL 이 되어 이 테스트가 깨진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_asset(db_session, owner_user_id=user.id, storage_key_prefix="assets/inquiry-attachment/")
    inquiry = await _make_inquiry(db_session, user_id=user.id, attachment_asset_id=asset.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    at = datetime(2026, 10, 1, 10, 0, 1, tzinfo=UTC)
    _set_signing_clock(monkeypatch, at)
    first = (await db_client.get(f"/me/inquiries/{inquiry.id}")).json()["attachmentUrl"]
    _set_signing_clock(monkeypatch, at + timedelta(seconds=1))
    second = (await db_client.get(f"/me/inquiries/{inquiry.id}")).json()["attachmentUrl"]

    assert first is not None
    assert first != second


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
