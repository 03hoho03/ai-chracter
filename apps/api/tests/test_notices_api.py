from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Notice


async def _make_notice(
    db_session: AsyncSession,
    *,
    title: str = "공지",
    body_markdown: str = "본문",
    published: bool = False,
    published_at: datetime | None = None,
) -> Notice:
    notice = Notice(
        title=title, body_markdown=body_markdown, published=published, published_at=published_at
    )
    db_session.add(notice)
    await db_session.flush()
    return notice


async def test_list_notices_works_without_auth_cookie(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/notices")
    assert resp.status_code == 200


async def test_get_notice_works_without_auth_cookie(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    notice = await _make_notice(db_session, published=True, published_at=datetime.now(UTC))
    await db_session.commit()

    resp = await db_client.get(f"/notices/{notice.id}")
    assert resp.status_code == 200


async def test_get_unpublished_notice_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    notice = await _make_notice(db_session, published=False)
    await db_session.commit()

    resp = await db_client.get(f"/notices/{notice.id}")
    assert resp.status_code == 404


async def test_list_excludes_unpublished_and_sorts_by_published_at_desc(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    older = await _make_notice(
        db_session, title="옛 공지", published=True, published_at=now - timedelta(days=1)
    )
    newer = await _make_notice(db_session, title="새 공지", published=True, published_at=now)
    await _make_notice(db_session, title="초안", published=False)
    await db_session.commit()

    resp = await db_client.get("/notices")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["id"] for item in items] == [str(newer.id), str(older.id)]


async def test_get_notice_returns_full_body(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    notice = await _make_notice(
        db_session, title="점검 안내", body_markdown="**점검**합니다", published=True, published_at=datetime.now(UTC)
    )
    await db_session.commit()

    resp = await db_client.get(f"/notices/{notice.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "점검 안내"
    assert body["bodyMarkdown"] == "**점검**합니다"
