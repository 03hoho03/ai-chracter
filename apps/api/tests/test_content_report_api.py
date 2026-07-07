import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    CharacterVersionDetail,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    Report,
    ReportReasonCategory,
    ReportStatus,
    User,
)


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(timezone.utc),
        "privacy_agreed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_published_content(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(timezone.utc),
        detail_description="설명",
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = Asset(owner_user_id=creator_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL)
    db_session.add(thumbnail)
    await db_session.flush()

    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def test_report_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        f"/contents/{uuid.uuid4()}/report", json={"reasonCategory": "spam"}
    )
    assert resp.status_code == 401


async def test_report_unknown_content_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(
        f"/contents/{uuid.uuid4()}/report", json={"reasonCategory": "spam"}
    )
    assert resp.status_code == 404


async def test_report_invalid_reason_category_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(
        f"/contents/{content.id}/report", json={"reasonCategory": "not-a-real-reason"}
    )
    assert resp.status_code == 422


async def test_report_creates_pending_row_and_allows_repeat_reports(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    reporter = _make_user()
    creator = _make_user()
    db_session.add_all([reporter, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_content(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, reporter.id)

    resp = await db_client.post(
        f"/contents/{content.id}/report", json={"reasonCategory": "hate"}
    )
    assert resp.status_code == 204
    # A second report from the same user is a distinct row, not deduped (no idempotency AC).
    resp = await db_client.post(
        f"/contents/{content.id}/report", json={"reasonCategory": "adult"}
    )
    assert resp.status_code == 204

    reports = (
        await db_session.execute(
            sa.select(Report)
            .where(Report.content_id == content.id, Report.reporter_user_id == reporter.id)
            .order_by(Report.reason_category)
        )
    ).scalars().all()
    assert len(reports) == 2
    assert {r.reason_category for r in reports} == {ReportReasonCategory.HATE, ReportReasonCategory.ADULT}
    assert all(r.status == ReportStatus.PENDING for r in reports)
