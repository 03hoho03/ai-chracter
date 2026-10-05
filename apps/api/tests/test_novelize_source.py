"""소설 장의 원문 — 구간 읽기, 경계 후보 읽기, 다음 장 시작 계산, 구간 해시, 원문 줄 형식.

방은 `_open_room` 으로 만든다(오프닝은 앱이 넣고, 그 뒤 턴마다 사용자·모델 메시지를 1초 간격으로 심는다)."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptNames
from api.db.models import ChatMessage, ChatMessageRole, NovelChapter
from api.novelize.source import (
    SourceTurn,
    format_turn_lines,
    group_turns,
    load_candidates,
    load_segment,
    message_key,
    next_chapter_start,
    segment_hash,
)
from factories import Room, _open_room


async def _messages(db: AsyncSession, room: Room) -> list[ChatMessage]:
    rows = await db.scalars(
        sa.select(ChatMessage)
        .where(ChatMessage.chat_room_id == room.room_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    return list(rows.all())


def _message(room_id: uuid.UUID, role: ChatMessageRole, content: str, at: datetime) -> ChatMessage:
    return ChatMessage(id=uuid.uuid4(), chat_room_id=room_id, role=role, content=content, created_at=at)


def _chapter_ending_at(message: ChatMessage) -> NovelChapter:
    return NovelChapter(end_message_id=message.id, end_message_created_at=message.created_at)


# ── 구간 ────────────────────────────────────────────────────────────────────
async def test_load_segment_is_inclusive_and_breaks_time_ties_by_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=3)
    u2, a2 = room.turns[2]
    # 끝 메시지와 같은 시각인 메시지 둘 — id 가 끝보다 작으면 구간 안, 크면 밖이다.
    low = _message(room.room_id, ChatMessageRole.USER, "같은 시각 앞", a2.created_at)
    high = _message(room.room_id, ChatMessageRole.USER, "같은 시각 뒤", a2.created_at)
    low.id = uuid.UUID(int=a2.id.int - 1)
    high.id = uuid.UUID(int=a2.id.int + 1)
    db_session.add_all([low, high])
    await db_session.flush()

    segment = await load_segment(db_session, room.room_id, message_key(u2), message_key(a2))

    assert [m.id for m in segment] == [u2.id, low.id, a2.id]


# ── 경계 후보 ───────────────────────────────────────────────────────────────
async def test_candidates_stop_at_the_nth_reply_and_drop_a_trailing_unanswered_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=3)
    messages = await _messages(db_session, room)
    opening = messages[0]

    picked = await load_candidates(db_session, room.room_id, message_key(opening), 2)
    assert [m.id for m in picked] == [opening.id, room.turns[1][0].id, room.turns[1][1].id]

    trailing = _message(room.room_id, ChatMessageRole.USER, "응답 없는 마지막 말", room.base + timedelta(minutes=5))
    db_session.add(trailing)
    await db_session.flush()
    picked = await load_candidates(db_session, room.room_id, message_key(room.turns[3][0]), 10)
    assert [m.id for m in picked] == [room.turns[3][0].id, room.turns[3][1].id]


async def test_candidates_read_past_a_run_of_user_messages_longer_than_one_page(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """한 번에 읽는 개수보다 사용자 메시지가 길게 이어져도 다음 응답까지 이어 읽는다."""
    room = await _open_room(db_client, db_session, turns=1)
    start = room.base + timedelta(minutes=1)
    users = [_message(room.room_id, ChatMessageRole.USER, f"말 {i}", start + timedelta(seconds=i)) for i in range(6)]
    reply = _message(room.room_id, ChatMessageRole.ASSISTANT, "응답", start + timedelta(seconds=10))
    db_session.add_all([*users, reply])
    await db_session.flush()

    picked = await load_candidates(db_session, room.room_id, message_key(users[0]), 1)

    assert [m.id for m in picked] == [*(u.id for u in users), reply.id]


# ── 다음 장 시작 ────────────────────────────────────────────────────────────
async def test_first_chapter_starts_at_the_opening_and_the_next_one_right_after_the_stored_end_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=3)
    opening = (await _messages(db_session, room))[0]
    a2 = room.turns[2][1]

    first = await next_chapter_start(db_session, room.room_id, None)
    assert first is not None and first.id == opening.id

    after = await next_chapter_start(db_session, room.room_id, _chapter_ending_at(a2))
    assert after is not None and after.id == room.turns[3][0].id

    # 끝 메시지와 같은 시각이지만 키가 더 큰 메시지는 다음 장에 들어간다.
    tie = _message(room.room_id, ChatMessageRole.USER, "같은 시각", a2.created_at)
    tie.id = uuid.UUID(int=a2.id.int + 1)
    db_session.add(tie)
    await db_session.flush()
    after_tie = await next_chapter_start(db_session, room.room_id, _chapter_ending_at(a2))
    assert after_tie is not None and after_tie.id == tie.id


async def test_next_start_survives_a_deleted_end_message_and_follows_a_reset_to_the_new_opening(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=3)
    a2 = room.turns[2][1]
    chapter = _chapter_ending_at(a2)

    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == a2.id))
    after_delete = await next_chapter_start(db_session, room.room_id, chapter)
    assert after_delete is not None and after_delete.id == room.turns[3][0].id

    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.chat_room_id == room.room_id))
    new_opening = _message(room.room_id, ChatMessageRole.ASSISTANT, "새 오프닝", datetime.now(UTC))
    db_session.add(new_opening)
    await db_session.flush()
    after_reset = await next_chapter_start(db_session, room.room_id, chapter)
    assert after_reset is not None and after_reset.id == new_opening.id

    caught_up = await next_chapter_start(db_session, room.room_id, _chapter_ending_at(new_opening))
    assert caught_up is None


# ── 해시 ────────────────────────────────────────────────────────────────────
def test_segment_hash_is_sha256_of_role_and_raw_content_in_key_order() -> None:
    room_id = uuid.uuid4()
    at = datetime.now(UTC)
    messages = [
        _message(room_id, ChatMessageRole.ASSISTANT, "왔어? {{user}}", at),
        _message(room_id, ChatMessageRole.USER, "응 \"늦었지\"", at),
    ]
    expected_payload = '[["assistant","왔어? {{user}}"],["user","응 \\"늦었지\\""]]'
    assert segment_hash(messages) == hashlib.sha256(expected_payload.encode("utf-8")).hexdigest()
    assert json.loads(expected_payload)[0] == ["assistant", "왔어? {{user}}"]

    other_ids = [_message(room_id, m.role, m.content, at) for m in messages]
    assert segment_hash(other_ids) == segment_hash(messages)
    swapped = [_message(room_id, ChatMessageRole.USER, messages[0].content, at), messages[1]]
    assert segment_hash(swapped) != segment_hash(messages)
    edited = [messages[0], _message(room_id, ChatMessageRole.USER, "응 늦었지", at)]
    assert segment_hash(edited) != segment_hash(messages)


# ── 원문 줄 ─────────────────────────────────────────────────────────────────
def test_turn_lines_number_each_message_by_turn_and_expand_names_only_in_replies() -> None:
    room_id = uuid.uuid4()
    at = datetime.now(UTC)
    opening = _message(room_id, ChatMessageRole.ASSISTANT, "*창밖을 보던 {{char}}가 돌아본다.* 왔어, {{user}}?", at)
    u1 = _message(room_id, ChatMessageRole.USER, "*가방을 내려놓으며* 응 {{user}}", at)
    a1 = _message(room_id, ChatMessageRole.ASSISTANT, "괜찮아. {{img::도윤/웃음}}*잔을 민다*\n오늘은 조용하네.", at)
    u2a = _message(room_id, ChatMessageRole.USER, "그러게.", at)
    u2b = _message(room_id, ChatMessageRole.USER, "(OOC: 길게 써 줘)", at)
    a2 = _message(room_id, ChatMessageRole.ASSISTANT, "*잔을 내려놓는다*", at)
    tail = _message(room_id, ChatMessageRole.USER, "응답 없는 말", at)

    turns = group_turns([opening, u1, a1, u2a, u2b, a2, tail])
    assert turns == [
        SourceTurn(users=(), assistant=opening),
        SourceTurn(users=(u1,), assistant=a1),
        SourceTurn(users=(u2a, u2b), assistant=a2),
    ]

    names = PromptNames(persona_name="서진", default_user_name="", char_name="도윤")
    lines = format_turn_lines(turns, names=names, user_label="사용자", assistant_label="캐릭터")

    assert lines == (
        "[턴 1] 캐릭터: *창밖을 보던 도윤이 돌아본다.* 왔어, 서진?\n"
        "[턴 2] 사용자: *가방을 내려놓으며* 응 {{user}}\n"
        "[턴 2] 캐릭터: 괜찮아. *잔을 민다*\n"
        "오늘은 조용하네.\n"
        "[턴 3] 사용자: 그러게.\n"
        "[턴 3] 사용자: (OOC: 길게 써 줘)\n"
        "[턴 3] 캐릭터: *잔을 내려놓는다*"
    )
