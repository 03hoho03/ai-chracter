import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import (
    AdminUser,
    Asset,
    AssetKind,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
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


async def test_dashboard_endpoints_require_admin_session(db_client: httpx.AsyncClient) -> None:
    for path in (
        "/admin/dashboard/counts",
        "/admin/dashboard/trend",
        "/admin/dashboard/popular",
        "/admin/dashboard/activity",
    ):
        resp = await db_client.get(path)
        assert resp.status_code == 401, path


async def test_regular_user_session_cannot_access_dashboard(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    resp = await db_client.post("/dev/session-echo", json={"data": {"user_id": str(user.id)}})
    assert resp.status_code == 201

    for path in (
        "/admin/dashboard/counts",
        "/admin/dashboard/trend",
        "/admin/dashboard/popular",
        "/admin/dashboard/activity",
    ):
        resp = await db_client.get(path)
        assert resp.status_code == 401, path


async def test_dashboard_counts_returns_accurate_numbers(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    active_user = _make_user()
    deleted_user = _make_user(deleted_at=datetime.now(timezone.utc))
    creator = _make_user()
    db_session.add_all([active_user, deleted_user, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)

    room = ChatRoom(
        user_id=active_user.id,
        content_id=character.id,
        content_version_id=character.current_published_version_id,
    )
    db_session.add(room)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            ChatMessage(
                chat_room_id=room.id, role=ChatMessageRole.USER, content="오늘 유저 메시지", created_at=now
            ),
            ChatMessage(
                chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content="오늘 AI 응답", created_at=now
            ),
            ChatMessage(
                chat_room_id=room.id,
                role=ChatMessageRole.USER,
                content="어제 유저 메시지",
                created_at=now - timedelta(days=1),
            ),
        ]
    )
    await _make_report(
        db_session, reporter_user_id=active_user.id, content_id=character.id, status=ReportStatus.PENDING
    )
    await _make_report(
        db_session, reporter_user_id=active_user.id, content_id=character.id, status=ReportStatus.RESOLVED
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/counts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalUsers"] == 2
    assert body["totalContents"] == 1
    assert body["todayMessages"] == 1
    assert body["pendingReports"] == 1


async def test_dashboard_counts_empty_db_returns_zero(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/counts")
    assert resp.status_code == 200
    assert resp.json() == {
        "totalUsers": 0,
        "totalContents": 0,
        "todayMessages": 0,
        "pendingReports": 0,
    }


async def test_dashboard_trend_fills_empty_days_with_zero(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/trend?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 30
    assert all(point["signups"] == 0 and point["contents"] == 0 and point["messages"] == 0 for point in body)


async def test_dashboard_trend_counts_seeded_data_on_correct_day(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    target_day = datetime.now(timezone.utc) - timedelta(days=5)
    user = _make_user(created_at=target_day)
    creator = _make_user(created_at=datetime.now(timezone.utc) - timedelta(days=60))
    db_session.add_all([user, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)

    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    character.created_at = target_day
    await db_session.flush()

    room = ChatRoom(
        user_id=user.id, content_id=character.id, content_version_id=character.current_published_version_id
    )
    db_session.add(room)
    await db_session.flush()
    db_session.add(
        ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="메시지", created_at=target_day)
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/trend?days=30")
    assert resp.status_code == 200
    body = resp.json()

    target_date_str = target_day.date().isoformat()
    target_point = next(p for p in body if p["date"] == target_date_str)
    assert target_point["signups"] == 1
    assert target_point["contents"] == 1
    assert target_point["messages"] == 1

    other_points = [p for p in body if p["date"] != target_date_str]
    assert all(
        p["signups"] == 0 and p["contents"] == 0 and p["messages"] == 0 for p in other_points
    )


async def test_dashboard_popular_sorted_by_chat_count_desc_with_names(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)

    character = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="인기캐릭터"
    )
    character.chat_count = 100
    story = await _make_published_story(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="인기스토리"
    )
    story.chat_count = 50
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/popular?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body[:2]] == [str(character.id), str(story.id)]

    by_id = {item["id"]: item for item in body}
    assert by_id[str(character.id)]["name"] == "인기캐릭터"
    assert by_id[str(character.id)]["chatCount"] == 100
    assert by_id[str(story.id)]["name"] == "인기스토리"
    assert by_id[str(story.id)]["chatCount"] == 50


async def test_dashboard_popular_empty_db_returns_empty_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/popular?limit=10")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_dashboard_popular_tie_breaker_is_deterministic(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`chat_count`가 전부 같으면 2차 키(`created_at DESC`), 그마저 같으면 3차 키(`id`)로
    완전히 결정적인 순서가 나와야 한다 — 안 그러면 새로고침마다 Top 10 순서가 바뀐다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)

    now = datetime.now(timezone.utc)
    older = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="오래된작품"
    )
    older.chat_count = 5
    older.created_at = now - timedelta(days=2)
    newer = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="최신작품"
    )
    newer.chat_count = 5
    newer.created_at = now - timedelta(days=1)
    # 같은 chat_count에 같은 created_at까지 겹치는 두 작품 — id가 최종 결정권을 가져야 한다.
    tie_a = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="동시생성A"
    )
    tie_a.chat_count = 5
    tie_a.created_at = now
    tie_b = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="동시생성B"
    )
    tie_b.chat_count = 5
    tie_b.created_at = now
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    tie_first, tie_second = sorted([tie_a, tie_b], key=lambda c: c.id)
    expected_ids = [str(tie_first.id), str(tie_second.id), str(newer.id), str(older.id)]

    resp1 = await db_client.get("/admin/dashboard/popular?limit=10")
    resp2 = await db_client.get("/admin/dashboard/popular?limit=10")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = resp1.json()
    body2 = resp2.json()

    assert [item["id"] for item in body1] == expected_ids
    assert [item["id"] for item in body2] == expected_ids


async def test_dashboard_activity_returns_latest_five_each(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(timezone.utc)

    users = [_make_user(nickname=f"유저{i}", created_at=now - timedelta(minutes=i)) for i in range(6)]
    db_session.add_all(users)
    await db_session.flush()
    genre = await _get_genre(db_session)
    creator = users[0]

    contents = [
        await _make_published_character(
            db_session, creator_user_id=creator.id, genre_id=genre.id, name=f"작품{i}"
        )
        for i in range(6)
    ]
    for i, content in enumerate(contents):
        content.created_at = now - timedelta(minutes=i)
    await db_session.flush()

    reports = [
        await _make_report(db_session, reporter_user_id=creator.id, content_id=contents[i].id)
        for i in range(6)
    ]
    for i, report in enumerate(reports):
        report.created_at = now - timedelta(minutes=i)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/activity")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["recentUsers"]) == 5
    assert len(body["recentContents"]) == 5
    assert len(body["recentReports"]) == 5

    assert [u["id"] for u in body["recentUsers"]] == [str(users[i].id) for i in range(5)]
    assert [c["id"] for c in body["recentContents"]] == [str(contents[i].id) for i in range(5)]
    assert [r["id"] for r in body["recentReports"]] == [str(reports[i].id) for i in range(5)]

    assert body["recentContents"][0]["name"] == "작품0"
    assert body["recentReports"][0]["contentName"] == "작품0"


async def test_dashboard_activity_empty_db_returns_empty_lists(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/activity")
    assert resp.status_code == 200
    assert resp.json() == {"recentUsers": [], "recentContents": [], "recentReports": []}
