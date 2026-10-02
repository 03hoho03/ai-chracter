"""이용제한(RESTRICTED)·삭제(DELETED)된 작품에서는 대화를 새로 만들지도 이어가지도 못한다.

막는 자리는 모델을 부르거나 새 방을 만드는 다섯 경로(전송·재생성·편집·새 방·시작설정 변경)이고, 지난 대화를 읽고
지우고 초기화하는 것은 그대로 된다. 작가 본인의 실제 방도 막힌다.

🔴 차감 단언의 셋업: 잔액 100 + 오늘치 클로버 동의 + `CHAT_DAILY_LIMIT` 0 이다. 이 조합에서 게이트가 한 번이라도
돌면 클로버가 깎이므로(`test_clover_gate.py` 의 `test_daily_exhausted_with_balance_spends_clover_and_passes`),
"잔액·원장 그대로"는 검사가 게이트보다 앞이라는 뜻이다. 같은 셋업에서 정상 작품은 깎인다는 짝 테스트가 아래에 있다 —
그 짝이 없으면 "안 깎였다"가 셋업 탓일 수 있다.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover, rate_limit_gate
from api.db.models import ChatMessage, ChatRoom, Content, StartingSetup, User
from api.db.models.chat import ChatMessageRole
from api.db.models.clover import CloverLedger
from api.db.models.content import ModerationStatus
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_published_story,
    _make_user_with_clover_lot,
    _NeverCalledLLMClient,
    _override_llm_client,
)

_BLOCKED = [
    pytest.param(ModerationStatus.RESTRICTED, id="restricted"),
    pytest.param(ModerationStatus.DELETED, id="deleted"),
]


async def _player(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def _character_room_with_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, creator_id: uuid.UUID
) -> tuple[Content, uuid.UUID, uuid.UUID]:
    """정상 작품에 방을 열고 사용자·응답 한 턴을 넣어 둔다(재생성·편집이 검증 단계를 지나도록).
    (작품, 방 id, 사용자 메시지 id)를 돌려준다."""
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator_id, genre_id=genre.id)
    await db_session.commit()
    resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    assert resp.status_code == 201
    room_id = uuid.UUID(resp.json()["id"])
    user_message = ChatMessage(chat_room_id=room_id, role=ChatMessageRole.USER, content="안녕")
    db_session.add(user_message)
    await db_session.flush()
    db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.ASSISTANT, content="반가워"))
    await db_session.commit()
    return content, room_id, user_message.id


async def _set_status(db_session: AsyncSession, content: Content, moderation_status: ModerationStatus) -> None:
    content.moderation_status = moderation_status
    await db_session.commit()


async def _message_count(db_session: AsyncSession, room_id: uuid.UUID) -> int:
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    )
    return count or 0


async def _ledger_count(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(CloverLedger).where(CloverLedger.user_id == user_id)
    )
    return count or 0


_StreamCall = Callable[[httpx.AsyncClient, uuid.UUID, uuid.UUID], Awaitable[httpx.Response]]


async def _send(client: httpx.AsyncClient, room_id: uuid.UUID, _message_id: uuid.UUID) -> httpx.Response:
    return await client.post(f"/chat-rooms/{room_id}/messages", json={"content": "다음 말"})


async def _regenerate(client: httpx.AsyncClient, room_id: uuid.UUID, _message_id: uuid.UUID) -> httpx.Response:
    return await client.post(f"/chat-rooms/{room_id}/regenerate")


async def _edit(client: httpx.AsyncClient, room_id: uuid.UUID, message_id: uuid.UUID) -> httpx.Response:
    return await client.patch(f"/chat-rooms/{room_id}/messages/{message_id}", json={"content": "고친 말"})


_STREAM_ROUTES = [
    pytest.param(_send, id="send"),
    pytest.param(_regenerate, id="regenerate"),
    pytest.param(_edit, id="edit"),
]


@pytest.mark.parametrize("moderation_status", _BLOCKED)
@pytest.mark.parametrize("call", _STREAM_ROUTES)
async def test_stream_route_on_unavailable_content_is_refused_before_any_charge(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    call: _StreamCall,
    moderation_status: ModerationStatus,
) -> None:
    user = await _player(db_client, db_session)
    other = await _make_user_with_clover_lot(db_session, clover_balance=0)
    content, room_id, message_id = await _character_room_with_turn(db_client, db_session, other.id)
    await _set_status(db_session, content, moderation_status)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_NeverCalledLLMClient())
    try:
        resp = await call(db_client, room_id, message_id)
    finally:
        _clear_llm_override()

    assert resp.status_code == 403
    assert resp.json() == {"detail": {"code": "CONTENT_RESTRICTED"}}
    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_count(db_session, user.id) == 0
    assert await _message_count(db_session, room_id) == 3  # 오프닝 + 한 턴, 그대로


async def test_send_on_normal_content_with_the_same_setup_spends_clover(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """위 테스트의 짝 — 셋업이 같고 작품만 정상이면 게이트가 돌아 클로버가 깎인다."""
    user = await _player(db_client, db_session)
    other = await _make_user_with_clover_lot(db_session, clover_balance=0)
    _, room_id, message_id = await _character_room_with_turn(db_client, db_session, other.id)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_FakeLLMClient(tokens=["응"]))
    try:
        resp = await _send(db_client, room_id, message_id)
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.clover_balance == 100 - clover.CHAT_TURN_COST


async def test_creator_cannot_continue_a_room_on_own_restricted_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = await _player(db_client, db_session)
    content, room_id, message_id = await _character_room_with_turn(db_client, db_session, creator.id)
    await _set_status(db_session, content, ModerationStatus.RESTRICTED)

    _override_llm_client(_NeverCalledLLMClient())
    try:
        resp = await _send(db_client, room_id, message_id)
    finally:
        _clear_llm_override()

    assert resp.status_code == 403
    assert resp.json() == {"detail": {"code": "CONTENT_RESTRICTED"}}


@pytest.mark.parametrize("moderation_status", _BLOCKED)
async def test_create_chat_room_on_unavailable_content_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, moderation_status: ModerationStatus
) -> None:
    user = await _player(db_client, db_session)
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    content.moderation_status = moderation_status
    await db_session.commit()

    resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})

    assert resp.status_code == 403
    assert resp.json() == {"detail": {"code": "CONTENT_RESTRICTED"}}
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.content_id == content.id)
    )
    assert count == 0


async def test_change_starting_setup_on_restricted_content_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _player(db_client, db_session)
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert story.current_published_version_id is not None
    setups = []
    for order in (1, 2):
        setup = StartingSetup(
            entity_id=uuid.uuid4(),
            content_version_id=story.current_published_version_id,
            name=f"시작 {order}",
            prologue="프롤로그",
            opening_message="오프닝",
            order=order,
        )
        db_session.add(setup)
        setups.append(setup)
    await db_session.commit()
    resp = await db_client.post(
        "/chat-rooms",
        json={"contentId": str(story.id), "contentType": "story", "startingSetupId": str(setups[0].id)},
    )
    assert resp.status_code == 201
    room_id = resp.json()["id"]
    await _set_status(db_session, story, ModerationStatus.RESTRICTED)

    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(setups[1].id)}
    )

    assert resp.status_code == 403
    assert resp.json() == {"detail": {"code": "CONTENT_RESTRICTED"}}
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.content_id == story.id)
    )
    assert count == 1


async def test_room_on_restricted_content_can_still_be_read_reset_and_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _player(db_client, db_session)
    other = await _make_user_with_clover_lot(db_session, clover_balance=0)
    content, room_id, _ = await _character_room_with_turn(db_client, db_session, other.id)
    await _set_status(db_session, content, ModerationStatus.RESTRICTED)

    read = await db_client.get(f"/chat-rooms/{room_id}")
    assert read.status_code == 200
    assert read.json()["contentRestricted"] is True
    assert [m["content"] for m in read.json()["messages"]][-2:] == ["안녕", "반가워"]

    listed = await db_client.get("/chat-rooms", params={"contentId": str(content.id)})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [str(room_id)]

    reset = await db_client.post(f"/chat-rooms/{room_id}/reset")
    assert reset.status_code == 200
    assert reset.json()["contentRestricted"] is True
    assert await _message_count(db_session, room_id) == 1

    deleted = await db_client.delete(f"/chat-rooms/{room_id}")
    assert deleted.status_code == 204
    await db_session.refresh(user)
    assert user.clover_balance == 100


async def test_room_on_normal_content_is_not_marked_restricted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _player(db_client, db_session)
    other = await _make_user_with_clover_lot(db_session, clover_balance=0)
    _, room_id, _ = await _character_room_with_turn(db_client, db_session, other.id)

    read = await db_client.get(f"/chat-rooms/{room_id}")

    assert read.status_code == 200
    assert read.json()["contentRestricted"] is False
