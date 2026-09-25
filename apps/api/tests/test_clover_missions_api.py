"""`/me/clover/missions` 조회·청구.

이 파일이 검증하는 성질:

1. 같은 키로 두 번 청구해도 한 번만 지급된다(멱등키 `mission:{user_id}:{key}`).
2. 3종 각각 미달성→달성 전이가 EXISTS 판정으로 정확히 일어난다 — `first_image`는
   `status='succeeded'` 필터, `first_message`는 `role='user'` 필터가 빠지면 오판한다.
3. 청구 전에 달성 신호가 사라졌다가(메시지 삭제) 다시 생기면(재대화) 다시 청구할 수
   있다 — 달성 상태를 저장하지 않기 때문이다.

셋업은 API를 거치지 않고 직접 ORM으로 행을 만든다 — 이 파일이 검증하는 것은 `clover/
missions.py`의 판정 쿼리이지 채팅·발행·이미지 생성 플로우 자체가 아니라서다.
"""

import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.clover import CloverLedger
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import ImageGenerationRequest
from factories import _get_genre, _login_as, _make_published_character, _make_user


async def _logged_in(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def _make_unpublished_content(db_session: AsyncSession, *, creator_user_id: uuid.UUID) -> None:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()


async def _make_room(
    db_session: AsyncSession, *, user_id: uuid.UUID, genre_id: uuid.UUID
) -> ChatRoom:
    content = await _make_published_character(db_session, creator_user_id=user_id, genre_id=genre_id)
    assert content.current_published_version_id is not None
    room = ChatRoom(
        user_id=user_id, content_id=content.id, content_version_id=content.current_published_version_id
    )
    db_session.add(room)
    await db_session.flush()
    return room


def _make_image_request(*, owner_user_id: uuid.UUID, status: str) -> ImageGenerationRequest:
    return ImageGenerationRequest(
        owner_user_id=owner_user_id,
        prompt="테스트 프롬프트",
        style="test-style",
        aspect_ratio="1:1",
        model="test-model",
        requested_count=1,
        status=status,
    )


async def _get_mission(db_client: httpx.AsyncClient, key: str) -> dict[str, object]:
    resp = await db_client.get("/me/clover/missions")
    assert resp.status_code == 200
    items = {item["key"]: item for item in resp.json()["missions"]}
    result: dict[str, object] = items[key]
    return result


# ── 판정 3종 — 미달성→달성 전이 ──────────────────────────────────────────
async def test_first_publish_achieved_flips_only_after_publishing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in(db_client, db_session)
    genre = await _get_genre(db_session)
    await _make_unpublished_content(db_session, creator_user_id=user.id)

    before = await _get_mission(db_client, "first_publish")
    assert before == {"key": "first_publish", "reward": 300, "achieved": False, "claimed": False}

    await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)

    after = await _get_mission(db_client, "first_publish")
    assert after["achieved"] is True


async def test_first_message_achieved_requires_a_user_role_message_not_just_a_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이 테스트가 빨개지는 조건: 판정이 `chat_rooms` 존재만 보고
    `role='user'` 필터를 빠뜨리면, 메시지가 0개(또는 assistant뿐)인 방만으로 달성 처리된다."""
    user = await _logged_in(db_client, db_session)
    genre = await _get_genre(db_session)
    room = await _make_room(db_session, user_id=user.id, genre_id=genre.id)

    # 방만 있고 메시지가 0개 — 미달성이어야 한다.
    empty = await _get_mission(db_client, "first_message")
    assert empty == {"key": "first_message", "reward": 100, "achieved": False, "claimed": False}

    # assistant 메시지만 있어도 여전히 미달성이어야 한다(유저가 보낸 것이 아니므로).
    db_session.add(ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content="안녕"))
    await db_session.flush()
    assistant_only = await _get_mission(db_client, "first_message")
    assert assistant_only["achieved"] is False

    db_session.add(ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="안녕"))
    await db_session.flush()
    after = await _get_mission(db_client, "first_message")
    assert after["achieved"] is True


async def test_first_image_achieved_requires_succeeded_status_not_just_a_request_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이 테스트가 빨개지는 조건: 판정이 `status='succeeded'` 필터를
    빠뜨리면 실패·차단 요청 행만으로도 달성 처리된다."""
    user = await _logged_in(db_client, db_session)

    for status in ("pending", "blocked", "failed"):
        db_session.add(_make_image_request(owner_user_id=user.id, status=status))
    await db_session.flush()
    before = await _get_mission(db_client, "first_image")
    assert before == {"key": "first_image", "reward": 200, "achieved": False, "claimed": False}

    db_session.add(_make_image_request(owner_user_id=user.id, status="succeeded"))
    await db_session.flush()
    after = await _get_mission(db_client, "first_image")
    assert after["achieved"] is True


# ── 청구 멱등 ────────────────────────────────────────────────────────────
async def test_claiming_the_same_mission_twice_grants_only_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이 테스트가 빨개지는 조건: 멱등키가 없거나 유저·키마다 결정적으로 파생되지 않으면
    더블클릭이 중복 지급된다."""
    user = await _logged_in(db_client, db_session)
    db_session.add(_make_image_request(owner_user_id=user.id, status="succeeded"))
    await db_session.flush()

    first = await db_client.post("/me/clover/missions/first_image/claim")
    second = await db_client.post("/me/clover/missions/first_image/claim")

    assert first.status_code == 200
    assert first.json() == {"granted": True, "balance": 200}
    assert second.status_code == 200
    assert second.json() == {"granted": False, "balance": 200}

    balance = await db_session.scalar(select(User.clover_balance).where(User.id == user.id))
    assert balance == 200
    ledger_rows = (
        await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user.id))
    ).all()
    assert [row.kind for row in ledger_rows] == ["mission_grant"]

    after = await _get_mission(db_client, "first_image")
    assert after == {"key": "first_image", "reward": 200, "achieved": True, "claimed": True}


async def test_claiming_an_unachieved_mission_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in(db_client, db_session)

    resp = await db_client.post("/me/clover/missions/first_image/claim")

    assert resp.status_code == 422


# ── 청구 전 신호 소실 → 재획득 → 재청구 가능 ─────────────────────────────
async def test_mission_is_claimable_again_after_the_achievement_signal_reappears(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이 테스트가 빨개지는 조건: 달성 상태를 저장하는 구현으로 바뀌면(EXISTS 재판정 대신
    캐시된 값을 본다), 메시지 삭제 후에도 여전히 달성으로 보이거나(신호 소실이 반영 안 됨) 그
    캐시가 굳어 재달성이 막힌다. 현재 구현(매 요청 EXISTS)은 둘 다 겪지 않는다."""
    user = await _logged_in(db_client, db_session)
    genre = await _get_genre(db_session)
    room = await _make_room(db_session, user_id=user.id, genre_id=genre.id)

    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="첫 메시지")
    db_session.add(message)
    await db_session.flush()

    achieved = await _get_mission(db_client, "first_message")
    assert achieved["achieved"] is True

    # 청구 전에 신호가 사라진다(메시지 삭제).
    await db_session.delete(message)
    await db_session.flush()

    vanished = await _get_mission(db_client, "first_message")
    assert vanished["achieved"] is False

    rejected = await db_client.post("/me/clover/missions/first_message/claim")
    assert rejected.status_code == 422

    # 재대화 — 신호가 다시 생긴다.
    db_session.add(ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="다시 메시지"))
    await db_session.flush()

    reachieved = await _get_mission(db_client, "first_message")
    assert reachieved["achieved"] is True

    claimed = await db_client.post("/me/clover/missions/first_message/claim")
    assert claimed.status_code == 200
    assert claimed.json() == {"granted": True, "balance": 100}
