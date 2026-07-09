import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import (
    AdminUser,
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
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail


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


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_published_character(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID, name: str = "캐릭터"
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
        detail_description="설명입니다",
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = Asset(
        owner_user_id=creator_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL
    )
    db_session.add(thumbnail)
    await db_session.flush()

    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="캐릭터 프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _make_published_story(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID, name: str = "스토리"
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
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
        detail_description="스토리 설명",
    )
    db_session.add(version)
    await db_session.flush()

    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner="한줄소개",
            thumbnail_asset_id=None,
            prompt_template=StoryPromptTemplate.CUSTOM,
            setting_text=None,
            development_example=None,
            custom_prompt="커스텀 프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _make_report(
    db_session: AsyncSession,
    *,
    reporter_user_id: uuid.UUID,
    content_id: uuid.UUID,
    reason_category: ReportReasonCategory = ReportReasonCategory.SPAM,
    status: ReportStatus = ReportStatus.PENDING,
) -> Report:
    report = Report(
        reporter_user_id=reporter_user_id,
        content_id=content_id,
        reason_category=reason_category,
        status=status,
    )
    db_session.add(report)
    await db_session.flush()
    return report


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


async def _login_as_admin(db_client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


async def test_list_reports_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/admin/reports?page=1")
    assert resp.status_code == 401


async def test_regular_user_session_cannot_list_reports(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    resp = await db_client.post("/dev/session-echo", json={"data": {"user_id": str(user.id)}})
    assert resp.status_code == 201

    resp = await db_client.get("/admin/reports?page=1")
    assert resp.status_code == 401


async def test_list_reports_returns_paginated_items_with_content_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    reporter = _make_user()
    creator = _make_user()
    db_session.add_all([reporter, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="캐릭터A"
    )
    story = await _make_published_story(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="스토리B"
    )
    report_a = await _make_report(
        db_session,
        reporter_user_id=reporter.id,
        content_id=character.id,
        reason_category=ReportReasonCategory.HATE,
    )
    report_b = await _make_report(
        db_session,
        reporter_user_id=reporter.id,
        content_id=story.id,
        reason_category=ReportReasonCategory.SPAM,
        status=ReportStatus.RESOLVED,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/reports?page=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["totalCount"] == 2
    assert body["totalPages"] == 1
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[str(report_a.id)]["contentName"] == "캐릭터A"
    assert by_id[str(report_a.id)]["contentType"] == "character"
    assert by_id[str(report_a.id)]["reasonCategory"] == "hate"
    assert by_id[str(report_a.id)]["status"] == "pending"
    assert by_id[str(report_b.id)]["contentName"] == "스토리B"
    assert by_id[str(report_b.id)]["contentType"] == "story"
    assert by_id[str(report_b.id)]["status"] == "resolved"


async def test_list_reports_filters_by_status(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    reporter = _make_user()
    creator = _make_user()
    db_session.add_all([reporter, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await _make_report(
        db_session, reporter_user_id=reporter.id, content_id=character.id, status=ReportStatus.PENDING
    )
    await _make_report(
        db_session, reporter_user_id=reporter.id, content_id=character.id, status=ReportStatus.REJECTED
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/reports?page=1&status=rejected")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalCount"] == 1
    assert all(item["status"] == "rejected" for item in body["items"])


async def test_report_detail_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/admin/reports/{uuid.uuid4()}")
    assert resp.status_code == 401


async def test_report_detail_unknown_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/reports/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_report_detail_returns_content_detail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    reporter = _make_user()
    creator = _make_user()
    db_session.add_all([reporter, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="캐릭터C"
    )
    report = await _make_report(
        db_session,
        reporter_user_id=reporter.id,
        content_id=character.id,
        reason_category=ReportReasonCategory.COPYRIGHT,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/reports/{report.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(report.id)
    assert body["reasonCategory"] == "copyright"
    assert body["reporterUserId"] == str(reporter.id)
    assert body["status"] == "pending"
    assert body["content"]["id"] == str(character.id)
    assert body["content"]["type"] == "character"
    assert body["content"]["name"] == "캐릭터C"
    assert body["content"]["detailDescription"] == "설명입니다"
    assert body["content"]["prompt"] == "캐릭터 프롬프트"
    assert body["content"]["thumbnailUrl"] is not None
    assert body["content"]["moderationStatus"] == "normal"


async def test_report_detail_for_story_uses_custom_prompt(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    reporter = _make_user()
    creator = _make_user()
    db_session.add_all([reporter, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="스토리D"
    )
    report = await _make_report(db_session, reporter_user_id=reporter.id, content_id=story.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/reports/{report.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"]["type"] == "story"
    assert body["content"]["name"] == "스토리D"
    assert body["content"]["prompt"] == "커스텀 프롬프트"
    assert body["content"]["thumbnailUrl"] is None
