import uuid
from datetime import datetime, timedelta, timezone, UTC

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import (
    AdminActionLog,
    AdminUser,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    Notification,
)
from factories import _login_as_admin, _make_user

# 파일 간 헬퍼 비공유 관례(apps/api/CLAUDE.md) — test_admin_users_api.py의 팩토리
# 패턴을 그대로 본떠 이 파일 안에 다시 만든다.


async def _make_content(db_session: AsyncSession, *, creator_user_id: uuid.UUID) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def _make_chat_room(db_session: AsyncSession, *, user_id: uuid.UUID, content: Content) -> ChatRoom:
    """`chat_rooms.content_version_id`는 NOT NULL이라, 발행 버전이 없는(`_make_content`)
    콘텐츠라면 채팅방용 최소 버전 행을 하나 만든다(test_admin_users_api.py와 동일)."""
    version = ContentVersion(
        content_id=content.id, version_number=None, published_at=None, detail_description=""
    )
    db_session.add(version)
    await db_session.flush()

    room = ChatRoom(user_id=user_id, content_id=content.id, content_version_id=version.id)
    db_session.add(room)
    await db_session.flush()
    return room


async def _add_chat_message(
    db_session: AsyncSession,
    *,
    chat_room_id: uuid.UUID,
    role: ChatMessageRole = ChatMessageRole.USER,
    created_at: datetime | None = None,
) -> ChatMessage:
    message = ChatMessage(chat_room_id=chat_room_id, role=role, content="메시지")
    if created_at is not None:
        message.created_at = created_at
    db_session.add(message)
    await db_session.flush()
    return message


async def _seed_messages(
    db_session: AsyncSession, *, chat_room_id: uuid.UUID, count: int, start: datetime
) -> list[ChatMessage]:
    """`_add_chat_message`는 호출마다 flush해 다수 생성 시 느리다 — 100개 초과
    페이지네이션 테스트 전용 벌크 시더. 초 단위로 겹치지 않게 타임스탬프를 흩뿌린다."""
    messages = [
        ChatMessage(
            chat_room_id=chat_room_id,
            role=ChatMessageRole.USER,
            content=f"메시지 {i}",
            created_at=start + timedelta(seconds=i),
        )
        for i in range(count)
    ]
    db_session.add_all(messages)
    await db_session.flush()
    return messages


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


async def _setup_room(db_session: AsyncSession) -> ChatRoom:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id)
    room = await _make_chat_room(db_session, user_id=user.id, content=content)
    await db_session.commit()
    return room


# ---- 인증 -------------------------------------------------------------------


async def test_view_requires_admin_session(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room_id = uuid.uuid4()
    await _assert_requires_admin_session(
        db_client,
        db_session,
        "post",
        f"/admin/chat-rooms/{room_id}/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )


async def test_messages_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room_id = uuid.uuid4()
    await _assert_requires_admin_session(db_client, db_session, "get", f"/admin/chat-rooms/{room_id}/messages")


# ---- 404 --------------------------------------------------------------------


async def test_view_unknown_room_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/chat-rooms/{uuid.uuid4()}/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )
    assert resp.status_code == 404


async def test_messages_unknown_room_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/chat-rooms/{uuid.uuid4()}/messages")
    assert resp.status_code == 404


# ---- 요청 바디 검증 ------------------------------------------------------------


async def test_view_missing_reason_category_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _setup_room(db_session)

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/chat-rooms/{room.id}/view", json={"reasonText": "확인"})
    assert resp.status_code == 422


async def test_view_invalid_reason_category_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _setup_room(db_session)

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "spam", "reasonText": "확인"},  # ReportReasonCategory 값이지 ChatViewReasonCategory 아님
    )
    assert resp.status_code == 422


async def test_view_blank_reason_text_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _setup_room(db_session)

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "other", "reasonText": "   "},
    )
    assert resp.status_code == 422


# ---- 로그 --------------------------------------------------------------------


async def test_view_creates_exactly_one_action_log_with_category_and_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _setup_room(db_session)
    await _add_chat_message(db_session, chat_room_id=room.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "report-investigation", "reasonText": "신고 확인차 열람"},
    )
    assert resp.status_code == 200

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_chat_room_id == room.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "chat-view"
    assert logs[0].reason_category == "report-investigation"
    assert logs[0].reason_text == "신고 확인차 열람"


async def test_view_action_log_targets_room_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """유저 상세의 조치 이력(`admin/users.py`)이 `target_user_id == user.id`로 거르므로,
    열람 로그가 그 화면에 걸리려면 `target_user_id`가 어드민 자신이나 null이 아니라
    **방 소유자**여야 한다. `target_chat_room_id`도 여전히 채워지는지 함께 확인한다."""
    room = await _setup_room(db_session)
    await _add_chat_message(db_session, chat_room_id=room.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )
    assert resp.status_code == 200

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_chat_room_id == room.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].target_user_id == room.user_id
    assert logs[0].target_chat_room_id == room.id


async def test_view_creates_no_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """D-12: 채팅 열람은 대상 유저에게 통지되지 않는다."""
    room = await _setup_room(db_session)
    await _add_chat_message(db_session, chat_room_id=room.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )
    assert resp.status_code == 200

    notifications = (
        await db_session.scalars(sa.select(Notification).where(Notification.user_id == room.user_id))
    ).all()
    assert notifications == []


async def test_get_more_five_times_still_one_log_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T-6 검증 기준의 핵심 — 더보기(GET)를 몇 번 불러도 로그는 늘지 않는다."""
    room = await _setup_room(db_session)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    await _seed_messages(db_session, chat_room_id=room.id, count=210, start=start)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    view_resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )
    assert view_resp.status_code == 200
    cursor = view_resp.json()

    for _ in range(5):
        assert cursor["beforeCreatedAt"] is not None
        assert cursor["beforeId"] is not None
        more_resp = await db_client.get(
            f"/admin/chat-rooms/{room.id}/messages",
            params={
                "beforeCreatedAt": cursor["beforeCreatedAt"],
                "beforeId": cursor["beforeId"],
                "limit": 20,
            },
        )
        assert more_resp.status_code == 200
        cursor = more_resp.json()

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_chat_room_id == room.id)
        )
    ).all()
    assert len(logs) == 1


# ---- 페이지네이션 --------------------------------------------------------------


async def test_view_returns_most_recent_100_messages_newest_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _setup_room(db_session)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    messages = await _seed_messages(db_session, chat_room_id=room.id, count=105, start=start)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/chat-rooms/{room.id}/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["items"]) == 100
    # 최근 105개 중 최근 100개(인덱스 5~104)를 최신순(내림차순)으로.
    expected_ids = [str(m.id) for m in reversed(messages[5:105])]
    assert [item["id"] for item in body["items"]] == expected_ids


async def test_cursor_load_more_continues_without_overlap(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _setup_room(db_session)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    messages = await _seed_messages(db_session, chat_room_id=room.id, count=30, start=start)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    page1_resp = await db_client.get(
        f"/admin/chat-rooms/{room.id}/messages", params={"limit": 10}
    )
    assert page1_resp.status_code == 200
    page1 = page1_resp.json()
    assert len(page1["items"]) == 10
    page1_ids = [item["id"] for item in page1["items"]]
    assert page1_ids == [str(m.id) for m in reversed(messages[20:30])]

    page2_resp = await db_client.get(
        f"/admin/chat-rooms/{room.id}/messages",
        params={
            "beforeCreatedAt": page1["beforeCreatedAt"],
            "beforeId": page1["beforeId"],
            "limit": 10,
        },
    )
    assert page2_resp.status_code == 200
    page2 = page2_resp.json()
    page2_ids = [item["id"] for item in page2["items"]]

    assert set(page1_ids) & set(page2_ids) == set()  # 안 겹침
    assert page2_ids == [str(m.id) for m in reversed(messages[10:20])]  # 안 끊김


async def test_cursor_boundary_with_duplicate_created_at_not_lost_or_duplicated(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """가장 중요한 회귀 테스트: 한 턴의 user·assistant 메시지가 같은 트랜잭션에 커밋돼
    `created_at`이 같을 수 있다 — `created_at`만으로 커서를 비교하면 경계에서 그 중
    하나가 유실되거나 중복된다. `(created_at, id)` 튜플 비교라야 안전하다."""
    room = await _setup_room(db_session)
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)  # m2, m3 공유
    t2 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)

    m1 = await _add_chat_message(db_session, chat_room_id=room.id, created_at=t0)
    m2 = await _add_chat_message(db_session, chat_room_id=room.id, created_at=t1)
    m3 = await _add_chat_message(
        db_session, chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, created_at=t1
    )
    m4 = await _add_chat_message(db_session, chat_room_id=room.id, created_at=t2)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    all_ids = {str(m.id) for m in (m1, m2, m3, m4)}

    page1_resp = await db_client.get(
        f"/admin/chat-rooms/{room.id}/messages", params={"limit": 2}
    )
    assert page1_resp.status_code == 200
    page1 = page1_resp.json()
    page1_ids = {item["id"] for item in page1["items"]}
    assert len(page1_ids) == 2
    assert str(m4.id) in page1_ids  # t2가 항상 가장 최근
    assert len(page1_ids & {str(m2.id), str(m3.id)}) == 1  # t1 두 개 중 하나만

    assert page1["beforeCreatedAt"] is not None
    assert page1["beforeId"] is not None

    page2_resp = await db_client.get(
        f"/admin/chat-rooms/{room.id}/messages",
        params={
            "beforeCreatedAt": page1["beforeCreatedAt"],
            "beforeId": page1["beforeId"],
            "limit": 2,
        },
    )
    assert page2_resp.status_code == 200
    page2_ids = {item["id"] for item in page2_resp.json()["items"]}

    # 유실도 중복도 없이 나머지 두 개(m1 + t1 짝 중 나머지 하나)가 정확히 이어진다.
    assert page2_ids == all_ids - page1_ids
    assert len(page2_ids) == 2
