import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import date, datetime, timedelta, timezone, UTC

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.redis import redis_client
from api.db.models import (
    AdminActionLog,
    Appeal,
    AppealStatus,
    AppealTargetKind,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationAction,
    ModerationActionType,
    ModerationStatus,
    Notification,
    Report,
    ReportReasonCategory,
    ReportStatus,
)
from api.session.suspension import SUSPENDED_USER_KEY_PREFIX, is_user_suspended
from factories import _count_queries, _create_admin, _login_as, _login_as_admin, _make_user


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
    await _login_as(db_client, user.id)
    # 세션이 아예 안 서도 admin 401은 나오므로, 먼저 "이
    # 유저로는 실제로 인증된다"를 고정해야 위 무세션 401과 구분되는 명제가 남는다(공허한 통과 방지).
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401


_ADMIN_SESSION_GUARD_CASES = [
    pytest.param("get", "/admin/users?page=1", None, id="list"),
    pytest.param("get", f"/admin/users/{uuid.uuid4()}", None, id="detail"),
    pytest.param("post", f"/admin/users/{uuid.uuid4()}/warn", {"reasonCategory": "spam"}, id="warn"),
    pytest.param("post", f"/admin/users/{uuid.uuid4()}/suspend", {"reasonCategory": "spam"}, id="suspend"),
    pytest.param(
        "post", f"/admin/users/{uuid.uuid4()}/unsuspend", {"adminComment": "해제합니다"}, id="unsuspend"
    ),
    pytest.param(
        "post",
        f"/admin/users/{uuid.uuid4()}/rate-limit-exempt",
        {"exempt": True, "adminComment": "면제합니다"},
        id="rate-limit-exempt",
    ),
    pytest.param(
        "post",
        f"/admin/users/{uuid.uuid4()}/beta",
        {"beta": True, "adminComment": "베타 참가"},
        id="beta",
    ),
    pytest.param(
        "post",
        f"/admin/users/{uuid.uuid4()}/clover",
        {"amount": 100, "adminComment": "지급합니다", "idempotencyKey": "k"},
        id="clover",
    ),
    pytest.param("get", f"/admin/users/{uuid.uuid4()}/clover-ledger?page=1", None, id="clover-ledger"),
]


@pytest.mark.parametrize(("method", "path", "json"), _ADMIN_SESSION_GUARD_CASES)
async def test_requires_admin_session(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    json: dict[str, object] | None,
) -> None:
    await _assert_requires_admin_session(db_client, db_session, method, path, json=json)


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
    """20행 조회에 쿼리 1~3개(N+1 금지) — 코드
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
    """정지 대상은 공개 작품(PUBLIC/LINK)뿐이라, `visibility=PRIVATE`인 NORMAL
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


async def test_user_detail_kakao_signup_method(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(kakao_id="1234567890", password_hash=None)
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{user.id}")
    assert resp.status_code == 200
    assert resp.json()["signupMethod"] == "kakao"


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


async def test_user_detail_includes_action_log_from_report_action_on_their_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """신고 경로 조치 로그는 `target_user_id` 없이
    `target_content_id`만 채운다 — 그래도 작품 소유 조건으로 크리에이터 상세에 걸려야 한다."""
    creator = _make_user()
    reporter = _make_user()
    db_session.add_all([creator, reporter])
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=creator.id, name="신고조치작품")
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

    action_resp = await db_client.post(
        f"/admin/reports/{report.id}/action",
        json={"action": "restrict", "adminComment": "신고 처리"},
    )
    assert action_resp.status_code == 200

    resp = await db_client.get(f"/admin/users/{creator.id}")
    assert resp.status_code == 200
    action_logs = resp.json()["actionLogs"]
    assert len(action_logs) == 1
    assert action_logs[0]["actionType"] == "content-restrict"
    assert action_logs[0]["targetContentId"] == str(content.id)
    assert action_logs[0]["contentName"] == "신고조치작품"


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
    assert normal_content.visibility == ContentVisibility.LINK  # visibility 불변

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
    """정지는 그 유저의 공개 작품(PUBLIC/LINK) 전부를 비공개 처리하되, 한 번도
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
    """재시도 시나리오(Redis 실패 후 재호출) 대비: 두 번째
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
    """실제 suspend 엔드포인트를 태워 기존 세션이 즉시(재로그인
    없이) 차단되는지 확인한다 — `tests/test_suspension.py`는 마커를 직접 세팅해서
    검증했지만, 여기서는 API 경로 전체가 맞물리는지를 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)

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


async def test_unsuspend_clears_suspended_at_removes_marker_and_restores_the_suspended_content(
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
    assert await _status_and_flag(db_session, content) == (ModerationStatus.RESTRICTED, True)

    unsuspend_resp = await db_client.post(
        f"/admin/users/{user.id}/unsuspend", json={"adminComment": "해제합니다"}
    )
    assert unsuspend_resp.status_code == 200
    assert unsuspend_resp.json() == {"restoredContentCount": 1}

    await db_session.refresh(user)
    assert user.suspended_at is None
    assert await is_user_suspended(user.id) is False

    assert await _status_and_flag(db_session, content) == (ModerationStatus.NORMAL, False)

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(
                AdminActionLog.target_user_id == user.id,
                AdminActionLog.action_type == "user-unsuspend",
            )
        )
    ).all()
    assert len(logs) == 1

    # 작품별 알림도, 해제 알림도 없다 — 정지 때의 알림 1건뿐이다.
    notifications = (
        await db_session.scalars(sa.select(Notification).where(Notification.user_id == user.id))
    ).all()
    assert [n.type for n in notifications] == ["user-suspended"]


async def _suspend(db_client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await db_client.post(f"/admin/users/{user_id}/suspend", json={"reasonCategory": "spam"})
    assert resp.status_code == 200


async def _unsuspend(db_client: httpx.AsyncClient, user_id: uuid.UUID) -> int:
    resp = await db_client.post(f"/admin/users/{user_id}/unsuspend", json={"adminComment": "해제합니다"})
    assert resp.status_code == 200
    count = resp.json()["restoredContentCount"]
    assert isinstance(count, int)
    return count


async def _status_and_flag(db_session: AsyncSession, content: Content) -> tuple[ModerationStatus, bool]:
    await db_session.refresh(content)
    return content.moderation_status, content.restricted_by_suspension


async def test_unsuspend_restores_only_what_the_suspension_restricted_and_the_preview_matches(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지 전부터 제한·삭제였던 작품, 비공개 초안, 함께 정지된 다른 작가의 작품은 해제가 건드리지 않는다.
    상세의 `restorableContentCount` 는 해제 응답의 개수와 같아야 한다(해제 확인창의 예고)."""
    user = _make_user()
    other = _make_user()
    db_session.add_all([user, other])
    await db_session.flush()
    public = await _make_content(db_session, creator_user_id=user.id)
    link = await _make_content(db_session, creator_user_id=user.id, visibility=ContentVisibility.LINK)
    private = await _make_content(db_session, creator_user_id=user.id, visibility=ContentVisibility.PRIVATE)
    already_restricted = await _make_content(
        db_session, creator_user_id=user.id, moderation_status=ModerationStatus.RESTRICTED
    )
    already_deleted = await _make_content(
        db_session, creator_user_id=user.id, moderation_status=ModerationStatus.DELETED
    )
    others = await _make_content(db_session, creator_user_id=other.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)
    await _suspend(db_client, other.id)

    detail = await db_client.get(f"/admin/users/{user.id}")
    assert detail.status_code == 200
    assert detail.json()["restorableContentCount"] == 2

    assert await _unsuspend(db_client, user.id) == 2

    assert await _status_and_flag(db_session, public) == (ModerationStatus.NORMAL, False)
    assert await _status_and_flag(db_session, link) == (ModerationStatus.NORMAL, False)
    assert await _status_and_flag(db_session, private) == (ModerationStatus.NORMAL, False)
    assert await _status_and_flag(db_session, already_restricted) == (ModerationStatus.RESTRICTED, False)
    assert await _status_and_flag(db_session, already_deleted) == (ModerationStatus.DELETED, False)
    assert await _status_and_flag(db_session, others) == (ModerationStatus.RESTRICTED, True)

    after = await db_client.get(f"/admin/users/{user.id}")
    assert after.json()["restorableContentCount"] == 0


async def test_unsuspend_after_a_repeated_suspend_restores_the_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 번째 정지(복구용 재호출)는 이미 내린 작품을 다시 세지 않지만 표식도 지우지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id)
    await db_session.commit()
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    await _suspend(db_client, user.id)
    await _suspend(db_client, user.id)

    assert await _unsuspend(db_client, user.id) == 1
    assert await _status_and_flag(db_session, content) == (ModerationStatus.NORMAL, False)


async def test_unsuspend_again_restores_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_content(db_session, creator_user_id=user.id)
    await db_session.commit()
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)

    assert await _unsuspend(db_client, user.id) == 1
    assert await _unsuspend(db_client, user.id) == 0


async def test_report_restrict_during_suspension_keeps_the_content_restricted_after_unsuspend(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지로 이미 제한인 작품을 신고 조치로 다시 제한하면 상태는 그대로라 표식을 내리지 않으면 구분이 안 된다 —
    그 작품은 신고 때문에 제한된 것이므로 해제 뒤에도 남아야 한다."""
    user = _make_user()
    reporter = _make_user()
    db_session.add_all([user, reporter])
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id)
    report = await _make_report(db_session, reporter_user_id=reporter.id, content_id=content.id)
    await db_session.commit()
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)

    resp = await db_client.post(f"/admin/reports/{report.id}/action", json={"action": "restrict"})
    assert resp.status_code == 200
    assert await _status_and_flag(db_session, content) == (ModerationStatus.RESTRICTED, False)

    assert await _unsuspend(db_client, user.id) == 0
    assert await _status_and_flag(db_session, content) == (ModerationStatus.RESTRICTED, False)


async def test_report_reject_during_suspension_keeps_the_content_restorable(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    reporter = _make_user()
    db_session.add_all([user, reporter])
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id)
    report = await _make_report(db_session, reporter_user_id=reporter.id, content_id=content.id)
    await db_session.commit()
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)

    resp = await db_client.post(f"/admin/reports/{report.id}/action", json={"action": "reject"})
    assert resp.status_code == 200
    assert await _status_and_flag(db_session, content) == (ModerationStatus.RESTRICTED, True)

    assert await _unsuspend(db_client, user.id) == 1
    assert await _status_and_flag(db_session, content) == (ModerationStatus.NORMAL, False)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            {"action": "restrict", "reasonCategory": "spam"},
            (ModerationStatus.RESTRICTED, False),
            id="restrict",
        ),
        pytest.param(
            {"action": "delete", "reasonCategory": "spam"},
            (ModerationStatus.DELETED, False),
            id="delete",
        ),
        pytest.param(
            {"action": "lift-restriction", "adminComment": "풀어 줍니다"},
            (ModerationStatus.NORMAL, False),
            id="lift",
        ),
    ],
)
async def test_direct_action_during_suspension_takes_the_content_out_of_the_restore(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    body: dict[str, str],
    expected: tuple[ModerationStatus, bool],
) -> None:
    """정지 대상 작품은 현실에선 발행본이 있다 — 발행본이 있어야 제한 해제가 대화방을 최신 버전으로 올리는 쿼리를
    실제로 돌리고, 그 쿼리의 자동 flush 가 상태와 정지 표식이 어긋난 중간 값을 쓰지 않는지가 드러난다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, name="정지된 작가의 작품")
    await db_session.commit()
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)

    resp = await db_client.post(f"/admin/contents/{content.id}/action", json=body)
    assert resp.status_code == 200
    assert await _status_and_flag(db_session, content) == expected

    assert await _unsuspend(db_client, user.id) == 0
    assert await _status_and_flag(db_session, content) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param({"action": "restrict"}, (ModerationStatus.RESTRICTED, False), id="restrict"),
        pytest.param({"action": "delete"}, (ModerationStatus.DELETED, False), id="delete"),
        pytest.param(
            {"action": "lift-restriction", "adminComment": "풀어 줍니다"},
            (ModerationStatus.NORMAL, False),
            id="lift",
        ),
    ],
)
async def test_report_action_during_suspension_on_a_published_content_takes_it_out_of_the_restore(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    body: dict[str, str],
    expected: tuple[ModerationStatus, bool],
) -> None:
    """신고 처리 경로도 직접 조치와 같다 — 발행본이 있는 작품이라 제한 해제가 대화방 갱신 쿼리까지 돈다."""
    user = _make_user()
    reporter = _make_user()
    db_session.add_all([user, reporter])
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, name="정지된 작가의 작품")
    report = await _make_report(db_session, reporter_user_id=reporter.id, content_id=content.id)
    await db_session.commit()
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)

    resp = await db_client.post(f"/admin/reports/{report.id}/action", json=body)
    assert resp.status_code == 200
    assert await _status_and_flag(db_session, content) == expected

    assert await _unsuspend(db_client, user.id) == 0
    assert await _status_and_flag(db_session, content) == expected


async def test_appeal_accepted_during_suspension_clears_the_flag(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지 전에 낸 이의를 정지 중에 수용하면 작품은 정상이 되고 표식이 내려간다(제한 상태에서만 서는 표식이다)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id)
    admin_payload = await _create_admin(db_session)
    action = ModerationAction(
        content_id=content.id, admin_id=uuid.UUID(str(admin_payload["id"])), action=ModerationActionType.RESTRICT
    )
    db_session.add(action)
    await db_session.flush()
    appeal = Appeal(
        user_id=user.id,
        target_kind=AppealTargetKind.MODERATION_ACTION,
        target_id=action.id,
        reason_text="이의 있습니다.",
        status=AppealStatus.PENDING,
    )
    db_session.add(appeal)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)

    resp = await db_client.post(f"/admin/appeals/{appeal.id}/resolve", json={"verdict": "accepted"})
    assert resp.status_code == 200
    assert await _status_and_flag(db_session, content) == (ModerationStatus.NORMAL, False)

    assert await _unsuspend(db_client, user.id) == 0


async def test_unsuspend_does_not_move_rooms_to_the_latest_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """복구는 정지 전 상태 그대로다 — 작품별 해제(`lift-restriction`)와 달리 방을 최신 발행본으로 옮기지 않는다."""
    user = _make_user()
    reader = _make_user()
    db_session.add_all([user, reader])
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, name="작품")
    room = await _make_chat_room(db_session, user_id=reader.id, content=content)
    first_version_id = room.content_version_id
    newer = ContentVersion(
        content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description=""
    )
    db_session.add(newer)
    await db_session.flush()
    content.current_published_version_id = newer.id
    await db_session.commit()
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    await _suspend(db_client, user.id)

    assert await _unsuspend(db_client, user.id) == 1

    await db_session.refresh(room)
    assert room.content_version_id == first_version_id
    assert room.version_auto_upgraded is False


async def test_suspension_flag_on_unrestricted_content_is_rejected_by_the_database(
    db_session: AsyncSession,
) -> None:
    """표식은 제한 상태에서만 설 수 있다(CHECK). `alembic check` 가 CHECK 를 비교하지 않아 이 테스트가 유일한 검증이다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id)
    content.restricted_by_suspension = True

    with pytest.raises(IntegrityError):
        await db_session.flush()


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


# ---- 레이트리밋 면제 ----------------------------------------------------------


async def test_user_detail_exposes_rate_limit_exempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """플래그는 유저 상세에만 실린다(목록·필터 없음). 면제/비면제
    유저를 둘 다 조회한다 — 한쪽만 보면 상수를 내려도 통과하는 항진 테스트가 된다."""
    exempt_user = _make_user(rate_limit_exempt=True)
    plain_user = _make_user(rate_limit_exempt=False)
    db_session.add_all([exempt_user, plain_user])
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    exempt_resp = await db_client.get(f"/admin/users/{exempt_user.id}")
    assert exempt_resp.status_code == 200
    assert exempt_resp.json()["rateLimitExempt"] is True

    plain_resp = await db_client.get(f"/admin/users/{plain_user.id}")
    assert plain_resp.status_code == 200
    assert plain_resp.json()["rateLimitExempt"] is False


async def test_set_rate_limit_exempt_on_writes_column_and_exactly_one_action_log(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`users.rate_limit_exempt`를 바꾸는 유일한 경로가 이 토글이고,
    켠 사실은 `admin_action_logs`에 `user-rate-limit-exempt-on`으로 남는다. 로그가 정확히 1행인
    것까지 본다 — 켜기/끄기가 각각 한 행이어야 이력에서 시점을 셀 수 있다."""
    user = _make_user(rate_limit_exempt=False)
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/rate-limit-exempt",
        json={"exempt": True, "adminComment": "운영 테스트 계정"},
    )
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.rate_limit_exempt is True

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "user-rate-limit-exempt-on"
    assert logs[0].reason_text == "운영 테스트 계정"


async def test_set_rate_limit_exempt_off_writes_the_off_action_type(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """켤 때와 끌 때 액션 타입이 달라야 이력에서 구분된다 — 위 테스트의 짝이고 셋업이
    글자까지 같다(시드·`exempt`·그 결과 단언의 면제 불리언만 반대이고 `adminComment`까지 같은
    문자열이다). 그 불리언을 빼면 남는 차이는 `action_type` 리터럴 하나뿐이고, `reason_text`는
    양쪽이 같은 값을 본다 — 끌 때도 사유가 로그에 남는지는 여기서만 검증된다."""
    user = _make_user(rate_limit_exempt=True)
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/rate-limit-exempt",
        json={"exempt": False, "adminComment": "운영 테스트 계정"},
    )
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.rate_limit_exempt is False

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "user-rate-limit-exempt-off"
    assert logs[0].reason_text == "운영 테스트 계정"


async def test_set_rate_limit_exempt_blank_admin_comment_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`unsuspend`와 같은 규칙 — 사유 카테고리가 없는 대신 코멘트가 필수다. 라우터가
    손으로 하는 검증이라 pydantic이 아니라 이 테스트가 유일한 검증이다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/rate-limit-exempt", json={"exempt": True, "adminComment": "   "}
    )
    assert resp.status_code == 422

    await db_session.refresh(user)
    assert user.rate_limit_exempt is False


async def test_set_rate_limit_exempt_on_deleted_user_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(deleted_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/rate-limit-exempt", json={"exempt": True, "adminComment": "면제"}
    )
    assert resp.status_code == 404


# ---- 베타 참가자 지정 ---------------------------------------------------------


def _birth_date_turning(age: int, today: date) -> date:
    """`today` 에 만 `age` 세가 되는 생년월일. 2월 29일에는 그 해(평년)에 같은 날이 없으므로
    2월 28일생을 쓴다 — 그 사람도 오늘 이미 만 `age` 세다."""
    try:
        return today.replace(year=today.year - age)
    except ValueError:
        return date(today.year - age, 2, 28)


async def _beta_logs(db_session: AsyncSession, user_id: uuid.UUID) -> list[AdminActionLog]:
    return list(
        (
            await db_session.scalars(
                sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user_id)
            )
        ).all()
    )


async def test_set_beta_on_records_joined_at_and_the_on_action_log(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    before = datetime.now(UTC)
    resp = await db_client.post(
        f"/admin/users/{user.id}/beta", json={"beta": True, "adminComment": "구글폼 신청자"}
    )
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.beta_joined_at is not None
    assert user.beta_joined_at >= before - timedelta(seconds=5)

    logs = await _beta_logs(db_session, user.id)
    assert [(log.action_type, log.reason_text) for log in logs] == [("user-beta-on", "구글폼 신청자")]


async def test_set_beta_off_clears_joined_at_and_writes_the_off_action_log(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(beta_joined_at=datetime(2026, 9, 1, tzinfo=UTC))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/beta", json={"beta": False, "adminComment": "베타 종료"}
    )
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.beta_joined_at is None

    logs = await _beta_logs(db_session, user.id)
    assert [(log.action_type, log.reason_text) for log in logs] == [("user-beta-off", "베타 종료")]


async def test_set_beta_again_keeps_the_first_joined_at_but_still_logs(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """베타 코호트는 첫 지정 시각으로 묶이므로 다시 지정해도 시각이 바뀌면 안 된다.
    누른 사실은 감사 로그에 한 행 더 남는다."""
    first_joined_at = datetime(2026, 9, 1, 9, tzinfo=UTC)
    user = _make_user(beta_joined_at=first_joined_at)
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/beta", json={"beta": True, "adminComment": "다시 지정"}
    )
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.beta_joined_at == first_joined_at
    assert [log.action_type for log in await _beta_logs(db_session, user.id)] == ["user-beta-on"]


async def test_set_beta_blank_admin_comment_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/beta", json={"beta": True, "adminComment": "   "})
    assert resp.status_code == 422

    await db_session.refresh(user)
    assert user.beta_joined_at is None
    assert await _beta_logs(db_session, user.id) == []


async def test_set_beta_on_deleted_user_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(deleted_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/beta", json={"beta": True, "adminComment": "지정"})
    assert resp.status_code == 404


async def test_set_beta_allows_user_on_their_19th_birthday(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    today = datetime.now(UTC).date()
    user = _make_user(birth_date=_birth_date_turning(19, today))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/beta", json={"beta": True, "adminComment": "지정"})
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.beta_joined_at is not None


@pytest.mark.parametrize(
    "birth_date_for",
    [
        pytest.param(lambda today: _birth_date_turning(19, today) + timedelta(days=1), id="day-before-19th-birthday"),
        pytest.param(lambda today: None, id="birth-date-missing"),
    ],
)
async def test_set_beta_rejects_user_under_19_without_any_change(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    birth_date_for: Callable[[date], date | None],
) -> None:
    """만 19세 생일 하루 전이면 아직 만 18세라 거부한다. 생년월일이 비어 있으면(탈퇴 파기
    외에는 생기지 않는다) 나이를 확인할 수 없으므로 함께 거부한다. 거부는 컬럼도 감사
    로그도 남기지 않는다."""
    today = datetime.now(UTC).date()
    user = _make_user(birth_date=birth_date_for(today))
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/users/{user.id}/beta", json={"beta": True, "adminComment": "지정"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "BETA_AGE_RESTRICTED"

    await db_session.refresh(user)
    assert user.beta_joined_at is None
    assert await _beta_logs(db_session, user.id) == []


async def test_user_detail_and_list_expose_beta_joined_at(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    joined_at = datetime(2026, 9, 1, 9, tzinfo=UTC)
    beta_user = _make_user(beta_joined_at=joined_at)
    plain_user = _make_user()
    db_session.add_all([beta_user, plain_user])
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    beta_detail = (await db_client.get(f"/admin/users/{beta_user.id}")).json()
    assert datetime.fromisoformat(beta_detail["betaJoinedAt"]) == joined_at
    assert (await db_client.get(f"/admin/users/{plain_user.id}")).json()["betaJoinedAt"] is None

    items = {item["id"]: item for item in (await db_client.get("/admin/users?page=1")).json()["items"]}
    assert datetime.fromisoformat(items[str(beta_user.id)]["betaJoinedAt"]) == joined_at
    assert items[str(plain_user.id)]["betaJoinedAt"] is None


async def test_list_users_filters_by_beta(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    beta_user = _make_user(beta_joined_at=datetime.now(UTC))
    plain_user = _make_user()
    db_session.add_all([beta_user, plain_user])
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    ids = {item["id"] for item in (await db_client.get("/admin/users?page=1&beta=true")).json()["items"]}
    assert str(beta_user.id) in ids
    assert str(plain_user.id) not in ids

    ids = {item["id"] for item in (await db_client.get("/admin/users?page=1&beta=false")).json()["items"]}
    assert str(plain_user.id) in ids
    assert str(beta_user.id) not in ids
