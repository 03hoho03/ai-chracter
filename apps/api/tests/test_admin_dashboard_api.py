import uuid
from datetime import datetime, timedelta, timezone, UTC

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
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
    ModerationStatus,
    Report,
    ReportReasonCategory,
    ReportStatus,
)
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail
from factories import _create_admin, _get_genre, _login_as, _login_as_admin, _make_user


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
        published_at=datetime.now(UTC),
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
        published_at=datetime.now(UTC),
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


async def test_dashboard_endpoints_require_admin_session(db_client: httpx.AsyncClient) -> None:
    for path in (
        "/admin/dashboard/counts",
        "/admin/dashboard/trend",
        "/admin/dashboard/popular",
        "/admin/dashboard/activity",
        "/admin/dashboard/growth",
    ):
        resp = await db_client.get(path)
        assert resp.status_code == 401, path


async def test_regular_user_session_cannot_access_dashboard(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    assert (await db_client.get("/me")).status_code == 200

    for path in (
        "/admin/dashboard/counts",
        "/admin/dashboard/trend",
        "/admin/dashboard/popular",
        "/admin/dashboard/activity",
        "/admin/dashboard/growth",
    ):
        resp = await db_client.get(path)
        assert resp.status_code == 401, path


async def test_dashboard_counts_returns_accurate_numbers(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    active_user = _make_user()
    deleted_user = _make_user(deleted_at=datetime.now(UTC))
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

    now = datetime.now(UTC)
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
    target_day = datetime.now(UTC) - timedelta(days=5)
    user = _make_user(created_at=target_day)
    creator = _make_user(created_at=datetime.now(UTC) - timedelta(days=60))
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

    now = datetime.now(UTC)
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
    now = datetime.now(UTC)

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


async def test_dashboard_growth_returns_accurate_numbers(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """가입자 성장 지표 5축(activation/publish/creator/withdrawn + 그 분모)을 한 시나리오에서
    검증한다. `user_room_only`는 방을 만들고 어시스턴트 메시지만 받았을 뿐 본인은 유저
    메시지를 한 번도 안 보낸 경우라 activated에서 빠져야 한다 — 도달 판정을 `ChatRoom`
    존재 여부로 되돌리면 이 테스트가 activatedUsers/activationRate에서 깨진다."""
    genre = await _get_genre(db_session)

    user_msg = _make_user()
    user_room_only = _make_user()
    user_no_room = _make_user()
    creator_published = _make_user()
    creator_draft_only = _make_user()
    deleted_user = _make_user(deleted_at=datetime.now(UTC))
    db_session.add_all(
        [user_msg, user_room_only, user_no_room, creator_published, creator_draft_only, deleted_user]
    )
    await db_session.flush()

    character = await _make_published_character(
        db_session, creator_user_id=creator_published.id, genre_id=genre.id
    )

    room_msg = ChatRoom(
        user_id=user_msg.id, content_id=character.id, content_version_id=character.current_published_version_id
    )
    room_only = ChatRoom(
        user_id=user_room_only.id,
        content_id=character.id,
        content_version_id=character.current_published_version_id,
    )
    db_session.add_all([room_msg, room_only])
    await db_session.flush()
    db_session.add_all(
        [
            ChatMessage(chat_room_id=room_msg.id, role=ChatMessageRole.USER, content="안녕"),
            ChatMessage(chat_room_id=room_only.id, role=ChatMessageRole.ASSISTANT, content="어서오세요"),
        ]
    )

    draft_content = Content(
        creator_user_id=creator_draft_only.id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(draft_content)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/growth")
    assert resp.status_code == 200
    body = resp.json()

    assert body["totalUsers"] == 5
    assert body["totalSignups"] == 6
    assert body["withdrawnUsers"] == 1
    assert body["withdrawnRate"] == pytest.approx(1 / 6)
    assert body["activatedUsers"] == 1
    assert body["activationRate"] == pytest.approx(1 / 5)
    assert body["creatorsWithPublishedContent"] == 1
    assert body["publishRate"] == pytest.approx(1 / 5)
    assert body["usersWithContent"] == 2
    assert body["creatorRate"] == pytest.approx(2 / 5)


async def test_dashboard_growth_room_without_user_message_is_not_activated(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방만 만들고 유저 메시지를 한 번도 안 보낸 경우가 도달로 안 세어지는지를
    최소 시나리오로 못박는다(위 happy path와 별개로, 이 정의의 핵심을 단독으로 검증)."""
    genre = await _get_genre(db_session)
    creator = _make_user()
    room_only_user = _make_user()
    db_session.add_all([creator, room_only_user])
    await db_session.flush()
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)

    room = ChatRoom(
        user_id=room_only_user.id,
        content_id=character.id,
        content_version_id=character.current_published_version_id,
    )
    db_session.add(room)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/growth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalUsers"] == 2
    assert body["activatedUsers"] == 0
    assert body["activationRate"] == 0.0


async def test_dashboard_growth_empty_db_returns_zero(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/growth")
    assert resp.status_code == 200
    assert resp.json() == {
        "totalUsers": 0,
        "activatedUsers": 0,
        "activationRate": 0.0,
        "creatorsWithPublishedContent": 0,
        "publishRate": 0.0,
        "totalSignups": 0,
        "withdrawnUsers": 0,
        "withdrawnRate": 0.0,
        "usersWithContent": 0,
        "creatorRate": 0.0,
        "cohortRetention": [],
    }


async def test_dashboard_growth_cohort_retention_buckets_by_signup_week(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """가입 후 1주차(W1)에 유저 메시지를 보낸 유저는 그 주차에서만 유지로 잡히고,
    한 번도 안 보낸 유저는 어떤 주차에서도 안 잡힌다. 3주 전에 가입한 코호트라 관측
    가능한 최대 주차는 W3까지고, 그 뒤(W4~)는 응답에 아예 없어야 한다 — 0으로 채우면
    '유지 안 함'과 '아직 그 주차에 도달 못함'이 구분되지 않는다."""
    genre = await _get_genre(db_session)
    now = datetime.now(UTC)
    this_week_monday = now.date() - timedelta(days=now.weekday())
    signup_week_start = this_week_monday - timedelta(weeks=3)
    signup_at = datetime(
        signup_week_start.year, signup_week_start.month, signup_week_start.day, 12, tzinfo=UTC
    )

    retained_user = _make_user(created_at=signup_at)
    churned_user = _make_user(created_at=signup_at)
    db_session.add_all([retained_user, churned_user])
    await db_session.flush()

    character = await _make_published_character(
        db_session, creator_user_id=retained_user.id, genre_id=genre.id
    )
    room = ChatRoom(
        user_id=retained_user.id,
        content_id=character.id,
        content_version_id=character.current_published_version_id,
    )
    db_session.add(room)
    await db_session.flush()
    w1_message_at = signup_at + timedelta(weeks=1, hours=1)
    db_session.add(
        ChatMessage(
            chat_room_id=room.id, role=ChatMessageRole.USER, content="1주차 메시지", created_at=w1_message_at
        )
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/growth")
    assert resp.status_code == 200
    body = resp.json()

    cohorts = [c for c in body["cohortRetention"] if c["cohortWeekStart"] == signup_week_start.isoformat()]
    assert len(cohorts) == 1
    cohort = cohorts[0]
    assert cohort["cohortSize"] == 2

    weeks_by_offset = {w["weekOffset"]: w for w in cohort["weeks"]}
    assert set(weeks_by_offset) == {0, 1, 2, 3}
    assert weeks_by_offset[0]["retainedUsers"] == 0
    assert weeks_by_offset[1]["retainedUsers"] == 1
    assert weeks_by_offset[1]["retentionRate"] == pytest.approx(0.5)
    assert weeks_by_offset[2]["retainedUsers"] == 0
    assert weeks_by_offset[3]["retainedUsers"] == 0


async def test_dashboard_growth_cohort_retention_excludes_deleted_users(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴한 유저는 탈퇴 전에 유저 메시지를 보냈어도 코호트 크기·유지 카운트 어느
    쪽에도 반영되면 안 된다 — `_cohort_retention`이 탈퇴 유저의 메시지를 걸러내는
    분기(코호트 시작일을 못 찾으면 skip)를 검증한다."""
    genre = await _get_genre(db_session)
    active_user = _make_user()
    deleted_user = _make_user(deleted_at=datetime.now(UTC))
    db_session.add_all([active_user, deleted_user])
    await db_session.flush()

    character = await _make_published_character(
        db_session, creator_user_id=active_user.id, genre_id=genre.id
    )
    deleted_room = ChatRoom(
        user_id=deleted_user.id,
        content_id=character.id,
        content_version_id=character.current_published_version_id,
    )
    db_session.add(deleted_room)
    await db_session.flush()
    db_session.add(ChatMessage(chat_room_id=deleted_room.id, role=ChatMessageRole.USER, content="탈퇴 유저 메시지"))
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/growth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalUsers"] == 1

    cohorts = body["cohortRetention"]
    assert len(cohorts) == 1
    assert cohorts[0]["cohortSize"] == 1

    week0 = next(w for w in cohorts[0]["weeks"] if w["weekOffset"] == 0)
    assert week0["retainedUsers"] == 0


async def test_dashboard_growth_excludes_deleted_creators_and_activated_users(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴한 유저가 발행 콘텐츠와 본인 유저 메시지를 둘 다 가진 시나리오. `activated_users`와
    `creators_with_published_content`가 `User.deleted_at` 필터를 잃으면(각각 `ChatRoom`/
    `Content`를 `User`와 조인만 하고 필터를 안 걸면) 탈퇴 유저 2명이 분자에 그대로 잡혀
    분모(`total_users`=1)를 넘는 2.0 비율이 나온다 — 정상 구현에서는 분자가 0이라
    비율도 0.0이어야 한다."""
    genre = await _get_genre(db_session)
    active_user = _make_user()
    deleted_creator_a = _make_user(deleted_at=datetime.now(UTC))
    deleted_creator_b = _make_user(deleted_at=datetime.now(UTC))
    db_session.add_all([active_user, deleted_creator_a, deleted_creator_b])
    await db_session.flush()

    character_a = await _make_published_character(
        db_session, creator_user_id=deleted_creator_a.id, genre_id=genre.id, name="탈퇴 캐릭터 A"
    )
    character_b = await _make_published_character(
        db_session, creator_user_id=deleted_creator_b.id, genre_id=genre.id, name="탈퇴 캐릭터 B"
    )

    room_a = ChatRoom(
        user_id=deleted_creator_a.id,
        content_id=character_a.id,
        content_version_id=character_a.current_published_version_id,
    )
    room_b = ChatRoom(
        user_id=deleted_creator_b.id,
        content_id=character_b.id,
        content_version_id=character_b.current_published_version_id,
    )
    db_session.add_all([room_a, room_b])
    await db_session.flush()
    db_session.add_all(
        [
            ChatMessage(chat_room_id=room_a.id, role=ChatMessageRole.USER, content="탈퇴 유저 A 메시지"),
            ChatMessage(chat_room_id=room_b.id, role=ChatMessageRole.USER, content="탈퇴 유저 B 메시지"),
        ]
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/dashboard/growth")
    assert resp.status_code == 200
    body = resp.json()

    assert body["totalUsers"] == 1
    assert body["activatedUsers"] == 0
    assert body["activationRate"] == 0.0
    assert body["creatorsWithPublishedContent"] == 0
    assert body["publishRate"] == 0.0
    assert body["usersWithContent"] == 0
    assert body["creatorRate"] == 0.0

    assert body["activationRate"] <= 1.0
    assert body["publishRate"] <= 1.0
    assert body["creatorRate"] <= 1.0
