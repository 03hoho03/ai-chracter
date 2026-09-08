import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone, UTC

import httpx
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.redis import redis_client
from api.db.models import (
    AdminActionLog,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    Notification,
    Report,
    ReportReasonCategory,
    ReportStatus,
)
from api.session.suspension import SUSPENDED_USER_KEY_PREFIX, is_user_suspended
from factories import _count_queries, _create_admin, _login_as_admin, _make_user


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_suspension_markers() -> AsyncGenerator[None, None]:
    """`tests/test_suspension.py`와 같은 이유 — 정지 마커는 TTL이 없고 Redis DB 1을 테스트
    세션 전체가 공유하므로, 어서션 실패로 각 테스트의 정리가 스킵돼도 다음 테스트로
    새지 않도록 방어한다."""
    yield
    async for key in redis_client.scan_iter(match=f"{SUSPENDED_USER_KEY_PREFIX}*"):
        await redis_client.delete(key)


async def _make_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    name: str = "",
) -> Content:
    """상세/목록 테스트에 필요한 최소 콘텐츠. `name`을 주면 발행 버전까지 채워
    `content_name` 필드 검증에 쓴다 — 안 주면 `current_published_version_id`가 null로
    남아 `_content_names_by_id`가 빈 문자열을 채운다(`admin/contents.py`와 동일 규칙)."""
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=visibility,
        moderation_status=moderation_status,
    )
    db_session.add(content)
    await db_session.flush()

    if name:
        version = ContentVersion(
            content_id=content.id,
            version_number=1,
            published_at=datetime.now(UTC),
            detail_description="",
        )
        db_session.add(version)
        await db_session.flush()
        db_session.add(
            CharacterVersionDetail(
                content_version_id=version.id,
                name=name,
                one_liner="",
                thumbnail_asset_id=None,
                intro="",
                example_dialogues=[],
                character_prompt="",
            )
        )
        await db_session.flush()
        content.current_published_version_id = version.id
        await db_session.flush()

    return content


async def _make_chat_room(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: Content,
    name: str | None = None,
    turn_count: int = 0,
    created_at: datetime | None = None,
) -> ChatRoom:
    """`chat_rooms.content_version_id`는 NOT NULL이라, 발행 버전이 없는(`_make_content`
    기본값) 콘텐츠라면 채팅방용 최소 버전 행을 하나 만든다."""
    version_id = content.current_published_version_id
    if version_id is None:
        version = ContentVersion(
            content_id=content.id, version_number=None, published_at=None, detail_description=""
        )
        db_session.add(version)
        await db_session.flush()
        version_id = version.id

    room = ChatRoom(
        user_id=user_id, content_id=content.id, content_version_id=version_id, name=name,
        turn_count=turn_count,
    )
    if created_at is not None:
        room.created_at = created_at
    db_session.add(room)
    await db_session.flush()
    return room


async def _add_chat_message(
    db_session: AsyncSession,
    *,
    chat_room_id: uuid.UUID,
    role: ChatMessageRole,
    created_at: datetime | None = None,
) -> ChatMessage:
    message = ChatMessage(chat_room_id=chat_room_id, role=role, content="메시지")
    if created_at is not None:
        message.created_at = created_at
    db_session.add(message)
    await db_session.flush()
    return message


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


# ---- 인증 -------------------------------------------------------------------


async def _assert_requires_admin_session(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    json: dict[str, object] | None = None,
) -> None:
    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    session_resp = await db_client.post(
        "/dev/session-echo", json={"data": {"user_id": str(user.id)}}
    )
    assert session_resp.status_code == 201

    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401


async def test_list_users_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(db_client, db_session, "get", "/admin/users?page=1")


async def test_user_detail_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(db_client, db_session, "get", f"/admin/users/{uuid.uuid4()}")


async def test_warn_user_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(
        db_client, db_session, "post", f"/admin/users/{uuid.uuid4()}/warn", json={"reasonCategory": "spam"}
    )


async def test_suspend_user_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(
        db_client,
        db_session,
        "post",
        f"/admin/users/{uuid.uuid4()}/suspend",
        json={"reasonCategory": "spam"},
    )


async def test_unsuspend_user_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(
        db_client,
        db_session,
        "post",
        f"/admin/users/{uuid.uuid4()}/unsuspend",
        json={"adminComment": "해제합니다"},
    )


# ---- 목록 --------------------------------------------------------------------


async def test_list_users_search_by_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    target = _make_user(email="findme@example.com")
    other = _make_user(email="other@example.com")
    db_session.add_all([target, other])
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/users?page=1&q=findme")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(target.id) in ids
    assert str(other.id) not in ids


async def test_list_users_search_by_nickname_case_insensitive(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    target = _make_user(nickname="Sparkle")
    other = _make_user(nickname="상관없음")
    db_session.add_all([target, other])
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/users?page=1&q=SPARKLE")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(target.id) in ids
    assert str(other.id) not in ids


async def test_list_users_filters_by_suspended(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    suspended_user = _make_user(suspended_at=datetime.now(UTC))
    active_user = _make_user()
    db_session.add_all([suspended_user, active_user])
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/users?page=1&suspended=true")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(suspended_user.id) in ids
    assert str(active_user.id) not in ids

    resp = await db_client.get("/admin/users?page=1&suspended=false")
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(active_user.id) in ids
    assert str(suspended_user.id) not in ids


async def test_list_users_excludes_deleted_users(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    deleted_user = _make_user(deleted_at=datetime.now(UTC))
    active_user = _make_user()
    db_session.add_all([deleted_user, active_user])
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/users?page=1")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(active_user.id) in ids
    assert str(deleted_user.id) not in ids


async def test_list_users_content_and_chat_room_counts_are_accurate(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content_a = await _make_content(db_session, creator_user_id=user.id)
    await _make_content(db_session, creator_user_id=user.id)
    await _make_chat_room(db_session, user_id=user.id, content=content_a)
    await _make_chat_room(db_session, user_id=user.id, content=content_a)
    await _make_chat_room(db_session, user_id=user.id, content=content_a)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/users?page=1&q=" + user.email.split("@")[0])
    assert resp.status_code == 200
    item = next(item for item in resp.json()["items"] if item["id"] == str(user.id))
    assert item["contentCount"] == 2
    assert item["chatRoomCount"] == 3


async def test_list_users_pagination_second_page_has_no_duplicate_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    for i in range(25):
        db_session.add(
            _make_user(created_at=datetime.now(UTC) - timedelta(minutes=i))
        )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp1 = await db_client.get("/admin/users?page=1")
    resp2 = await db_client.get("/admin/users?page=2")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = resp1.json()
    body2 = resp2.json()
    assert body1["totalCount"] == 25
    assert body1["totalPages"] == 2
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert len(ids1) == 20
    assert len(ids2) == 5
    assert ids1.isdisjoint(ids2)


async def test_list_users_query_count_stays_bounded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """goal-prompt.md 3단계 검증 기준: 20행 조회에 쿼리 1~3개(T-8, N+1 금지) — 코드
    읽기가 아니라 SQLAlchemy `before_cursor_execute` 이벤트로 실측한다."""
    for i in range(20):
        user = _make_user(created_at=datetime.now(UTC) - timedelta(minutes=i))
        db_session.add(user)
        await db_session.flush()
        content = await _make_content(db_session, creator_user_id=user.id)
        await _make_chat_room(db_session, user_id=user.id, content=content)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    with _count_queries() as get_count:
        resp = await db_client.get("/admin/users?page=1")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 20
    assert get_count() <= 3, f"expected <=3 queries, got {get_count()}"


# ---- 상세 --------------------------------------------------------------------


async def test_user_detail_unknown_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_user_detail_deleted_user_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(deleted_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 404


async def test_user_detail_stats_match_actual_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(nickname="통계유저")
    db_session.add(user)
    await db_session.flush()

    content_a = await _make_content(db_session, creator_user_id=user.id, name="작품A")
    await _make_content(db_session, creator_user_id=user.id, name="작품B")

    room = await _make_chat_room(db_session, user_id=user.id, content=content_a)
    await _add_chat_message(
        db_session,
        chat_room_id=room.id,
        role=ChatMessageRole.USER,
        created_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    last_user_message = await _add_chat_message(
        db_session,
        chat_room_id=room.id,
        role=ChatMessageRole.USER,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    # 마지막 메시지가 ASSISTANT여도 last_active_at은 USER 메시지 기준이어야 한다.
    await _add_chat_message(db_session, chat_room_id=room.id, role=ChatMessageRole.ASSISTANT)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contentCount"] == 2
    assert body["chatRoomCount"] == 1
    assert body["messageCount"] == 2
    assert body["lastActiveAt"] is not None
    parsed_last_active = datetime.fromisoformat(body["lastActiveAt"].replace("Z", "+00:00"))
    assert abs((parsed_last_active - last_user_message.created_at).total_seconds()) < 1
    assert body["signupMethod"] == "email"


async def test_user_detail_restrictable_content_count_excludes_already_restricted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`restrictableContentCount`는 `contentCount`(전체)와 달리 지금 정지하면 새로
    RESTRICTED로 내려갈 작품(NORMAL)만 센다 — 이미 restricted/deleted인 작품은 제외."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_content(db_session, creator_user_id=user.id, moderation_status=ModerationStatus.NORMAL)
    await _make_content(db_session, creator_user_id=user.id, moderation_status=ModerationStatus.RESTRICTED)
    await _make_content(db_session, creator_user_id=user.id, moderation_status=ModerationStatus.DELETED)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contentCount"] == 3
    assert body["restrictableContentCount"] == 1


async def test_user_detail_restrictable_content_count_excludes_private_visibility(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """D-6: 정지 대상은 공개 작품(PUBLIC/LINK)뿐이라, `visibility=PRIVATE`인 NORMAL
    작품은 정지해도 내려가지 않는다 — `restrictableContentCount`도 그 작품을 빼고 세야
    한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_content(
        db_session,
        creator_user_id=user.id,
        moderation_status=ModerationStatus.NORMAL,
        visibility=ContentVisibility.PRIVATE,
    )
    await _make_content(
        db_session,
        creator_user_id=user.id,
        moderation_status=ModerationStatus.NORMAL,
        visibility=ContentVisibility.PUBLIC,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contentCount"] == 2
    assert body["restrictableContentCount"] == 1


async def test_user_detail_google_signup_method(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(google_sub="google-sub-123", password_hash=None)
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    assert resp.json()["signupMethod"] == "google"


async def test_user_detail_includes_reports_received_on_own_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    reporter = _make_user()
    db_session.add_all([creator, reporter])
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=creator.id, name="신고받은작품")
    report = await _make_report(
        db_session,
        reporter_user_id=reporter.id,
        content_id=content.id,
        reason_category=ReportReasonCategory.HATE,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{creator.id}")
    assert resp.status_code == 200
    reports = resp.json()["reports"]
    assert len(reports) == 1
    assert reports[0]["id"] == str(report.id)
    assert reports[0]["contentId"] == str(content.id)
    assert reports[0]["contentName"] == "신고받은작품"
    assert reports[0]["reasonCategory"] == "hate"


async def test_user_detail_includes_action_logs_targeting_user_or_their_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, name="조치대상작품")
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    # 유저 대상 조치(warn)
    warn_resp = await db_client.post(
        f"/admin/users/{user.id}/warn", json={"reasonCategory": "spam", "adminComment": "경고"}
    )
    assert warn_resp.status_code == 204

    # 그 유저의 작품 대상 조치(콘텐츠 직접 restrict) — content.py의 액션 라우터 재사용
    content_action_resp = await db_client.post(
        f"/admin/contents/{content.id}/action",
        json={"action": "restrict", "reasonCategory": "hate", "adminComment": "콘텐츠 조치"},
    )
    assert content_action_resp.status_code == 200

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    action_logs = resp.json()["actionLogs"]
    action_types = {log["actionType"] for log in action_logs}
    assert "user-warn" in action_types
    assert "content-restrict" in action_types
    content_log = next(log for log in action_logs if log["actionType"] == "content-restrict")
    assert content_log["targetContentId"] == str(content.id)
    assert content_log["contentName"] == "조치대상작품"


async def test_user_detail_includes_chat_view_action_log(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`POST /admin/chat-rooms/{id}/view`(chat_view.py)가 남기는 열람 로그가 실제로
    유저 상세의 `actionLogs`에 걸리는지 증명한다 — target_user_id를 채우지 않으면
    이 경로가 조용히 실패한다(로그는 DB에 남지만 화면엔 안 보임)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, name="채팅열람대상작품")
    room = await _make_chat_room(db_session, user_id=user.id, content=content)
    await _add_chat_message(db_session, chat_room_id=room.id, role=ChatMessageRole.USER)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    view_resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "report-investigation", "reasonText": "신고 확인차 열람"},
    )
    assert view_resp.status_code == 200

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    action_logs = resp.json()["actionLogs"]
    chat_view_log = next(log for log in action_logs if log["actionType"] == "chat-view")
    assert chat_view_log["reasonCategory"] == "report-investigation"


async def test_user_detail_includes_chat_rooms_with_message_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, name="채팅작품")
    room = await _make_chat_room(db_session, user_id=user.id, content=content, name="대화 1", turn_count=3)
    await _add_chat_message(db_session, chat_room_id=room.id, role=ChatMessageRole.USER)
    last_message = await _add_chat_message(db_session, chat_room_id=room.id, role=ChatMessageRole.ASSISTANT)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    rooms = resp.json()["chatRooms"]
    assert len(rooms) == 1
    assert rooms[0]["id"] == str(room.id)
    assert rooms[0]["contentId"] == str(content.id)
    assert rooms[0]["contentName"] == "채팅작품"
    assert rooms[0]["name"] == "대화 1"
    assert rooms[0]["turnCount"] == 3
    assert rooms[0]["messageCount"] == 2
    parsed_last_message_at = datetime.fromisoformat(rooms[0]["lastMessageAt"].replace("Z", "+00:00"))
    assert abs((parsed_last_message_at - last_message.created_at).total_seconds()) < 1


# ---- 경고 --------------------------------------------------------------------


async def test_warn_creates_notification_and_log(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/warn",
        json={"reasonCategory": "spam", "adminComment": "경고합니다"},
    )
    assert resp.status_code == 204

    notifications = (
        await db_session.scalars(sa.select(Notification).where(Notification.user_id == user.id))
    ).all()
    assert len(notifications) == 1
    assert notifications[0].type == "user-warned"
    assert notifications[0].content_id is None
    assert notifications[0].action_id is None
    assert notifications[0].reason_category == "spam"
    assert notifications[0].admin_comment == "경고합니다"

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "user-warn"
    assert logs[0].reason_category == "spam"

    await db_session.refresh(user)
    assert user.suspended_at is None


async def test_warn_missing_reason_category_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/warn", json={})
    assert resp.status_code == 422


async def test_warn_allowed_on_already_suspended_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """경고(알림)와 정지(접근 차단)는 서로 다른 축이라 정지 중에도 경고를 보낼 수
    있어야 한다 — `api/admin/users.py`의 `warn_user` docstring 참고."""
    user = _make_user(suspended_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/warn", json={"reasonCategory": "spam"}
    )
    assert resp.status_code == 204


# ---- 정지 --------------------------------------------------------------------


async def test_suspend_sets_suspended_at_restricts_content_notifies_logs_and_marks_redis(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    normal_content = await _make_content(
        db_session, creator_user_id=user.id, visibility=ContentVisibility.LINK
    )
    deleted_content = await _make_content(
        db_session, creator_user_id=user.id, moderation_status=ModerationStatus.DELETED
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/suspend",
        json={"reasonCategory": "hate", "adminComment": "정지합니다"},
    )
    assert resp.status_code == 200
    assert resp.json()["restrictedContentCount"] == 1

    await db_session.refresh(user)
    assert user.suspended_at is not None

    await db_session.refresh(normal_content)
    assert normal_content.moderation_status == ModerationStatus.RESTRICTED
    assert normal_content.visibility == ContentVisibility.LINK  # T-1: visibility 불변

    await db_session.refresh(deleted_content)
    assert deleted_content.moderation_status == ModerationStatus.DELETED  # 되살아나지 않음

    notifications = (
        await db_session.scalars(sa.select(Notification).where(Notification.user_id == user.id))
    ).all()
    assert len(notifications) == 1
    assert notifications[0].type == "user-suspended"
    assert notifications[0].content_id is None

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "user-suspend"

    assert await is_user_suspended(user.id) is True


async def test_suspend_excludes_private_content_from_restriction(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """D-6: 정지는 그 유저의 공개 작품(PUBLIC/LINK) 전부를 비공개 처리하되, 한 번도
    공개한 적 없는 PRIVATE 초안은 건드리지 않는다 — `content/router.py`의
    `create_content_draft`가 새 초안을 PRIVATE+NORMAL로 만들기 때문에, 이 조건이
    없으면 미공개 초안까지 restricted가 된다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    private_content = await _make_content(
        db_session, creator_user_id=user.id, visibility=ContentVisibility.PRIVATE
    )
    public_content = await _make_content(
        db_session, creator_user_id=user.id, visibility=ContentVisibility.PUBLIC
    )
    link_content = await _make_content(
        db_session, creator_user_id=user.id, visibility=ContentVisibility.LINK
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/suspend", json={"reasonCategory": "spam"})
    assert resp.status_code == 200
    assert resp.json()["restrictedContentCount"] == 2

    await db_session.refresh(private_content)
    assert private_content.moderation_status == ModerationStatus.NORMAL

    await db_session.refresh(public_content)
    assert public_content.moderation_status == ModerationStatus.RESTRICTED

    await db_session.refresh(link_content)
    assert link_content.moderation_status == ModerationStatus.RESTRICTED


async def test_suspend_missing_reason_category_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/suspend", json={})
    assert resp.status_code == 422


async def test_suspend_unknown_user_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{uuid.uuid4()}/suspend", json={"reasonCategory": "spam"}
    )
    assert resp.status_code == 404


async def test_suspend_is_idempotent_on_repeat_call(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재시도 시나리오(techspec §2-2 6단계 — Redis 실패 후 재호출) 대비: 두 번째
    suspend 호출은 400이 아니라 그대로 통과하고, 이미 내려간 작품은 다시 세지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_content(db_session, creator_user_id=user.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    first_resp = await db_client.post(
        f"/admin/users/{user.id}/suspend", json={"reasonCategory": "spam"}
    )
    assert first_resp.status_code == 200
    assert first_resp.json()["restrictedContentCount"] == 1

    second_resp = await db_client.post(
        f"/admin/users/{user.id}/suspend", json={"reasonCategory": "spam"}
    )
    assert second_resp.status_code == 200
    assert second_resp.json()["restrictedContentCount"] == 0

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert len(logs) == 2


async def test_suspend_restricted_content_count_matches_detail_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지 확인 다이얼로그가 상세 응답의 `restrictableContentCount`로 예고한 개수는
    실제 suspend 응답의 `restrictedContentCount`와 정확히 일치해야 한다 — 이미
    restricted인 작품과 PRIVATE(한 번도 공개한 적 없는 초안)인 작품이 섞여 있어도
    (`contentCount`와는 값이 갈리는 상황) 어긋나면 안 된다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_content(db_session, creator_user_id=user.id, moderation_status=ModerationStatus.NORMAL)
    await _make_content(db_session, creator_user_id=user.id, moderation_status=ModerationStatus.RESTRICTED)
    await _make_content(
        db_session,
        creator_user_id=user.id,
        moderation_status=ModerationStatus.NORMAL,
        visibility=ContentVisibility.PRIVATE,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    detail_resp = await db_client.get(f"/admin/users/{user.id}")
    assert detail_resp.status_code == 200
    previewed_count = detail_resp.json()["restrictableContentCount"]

    suspend_resp = await db_client.post(
        f"/admin/users/{user.id}/suspend", json={"reasonCategory": "spam"}
    )
    assert suspend_resp.status_code == 200
    assert suspend_resp.json()["restrictedContentCount"] == previewed_count


async def test_suspend_blocks_existing_session_immediately(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """techspec §9 회귀 2번: 실제 suspend 엔드포인트를 태워 기존 세션이 즉시(재로그인
    없이) 차단되는지 확인한다 — `tests/test_suspension.py`는 마커를 직접 세팅해서
    검증했지만, 여기서는 API 경로 전체가 맞물리는지를 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    session_resp = await db_client.post(
        "/dev/session-echo", json={"data": {"user_id": str(user.id)}}
    )
    assert session_resp.status_code == 201

    me_resp = await db_client.get("/me")
    assert me_resp.status_code == 200

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    suspend_resp = await db_client.post(
        f"/admin/users/{user.id}/suspend", json={"reasonCategory": "spam"}
    )
    assert suspend_resp.status_code == 200

    blocked_resp = await db_client.get("/me")
    assert blocked_resp.status_code == 403


# ---- 해제 --------------------------------------------------------------------


async def test_unsuspend_clears_suspended_at_removes_marker_and_keeps_content_restricted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    suspend_resp = await db_client.post(
        f"/admin/users/{user.id}/suspend", json={"reasonCategory": "spam"}
    )
    assert suspend_resp.status_code == 200
    assert await is_user_suspended(user.id) is True

    unsuspend_resp = await db_client.post(
        f"/admin/users/{user.id}/unsuspend", json={"adminComment": "해제합니다"}
    )
    assert unsuspend_resp.status_code == 204

    await db_session.refresh(user)
    assert user.suspended_at is None
    assert await is_user_suspended(user.id) is False

    await db_session.refresh(content)
    assert content.moderation_status == ModerationStatus.RESTRICTED  # D-7: 작품은 안 돌아온다

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(
                AdminActionLog.target_user_id == user.id,
                AdminActionLog.action_type == "user-unsuspend",
            )
        )
    ).all()
    assert len(logs) == 1

    notifications = (
        await db_session.scalars(sa.select(Notification).where(Notification.user_id == user.id))
    ).all()
    assert all(n.type != "user-unsuspended" for n in notifications)


async def test_unsuspend_missing_admin_comment_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(suspended_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/unsuspend", json={})
    assert resp.status_code == 422


async def test_unsuspend_blank_admin_comment_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(suspended_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/unsuspend", json={"adminComment": "   "}
    )
    assert resp.status_code == 422
