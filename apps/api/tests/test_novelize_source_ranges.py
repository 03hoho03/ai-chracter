"""원문 관문의 구간 읽기 — 여러 구간을 키 순으로 읽고 그 사이는 읽지 않는다, 그리고 옛 흐름 어댑터가 옮기기 전과 같은 행을 낸다.

옛 흐름(마지막 화 끝 다음부터 이어 읽기)은 "구간 선택이 없으면 지금처럼 연속 구간 하나"로 관문을 부른다. 같은 행을 내는지는
옮기기 전의 질의를 이 파일에 그대로 둔 기준 구현과 비교해 본다 — 같은 시각 메시지, 한 번에 읽는 개수보다 긴 사용자 메시지 줄,
응답 없는 마지막 사용자 메시지가 섞인 방에서 시작점·상한·끝점을 모두 바꿔 가며."""

import uuid
from datetime import timedelta

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.db.models import ChatMessage, ChatMessageRole, NovelChapter, NovelSourceSection, NovelSourceSelection
from api.novelize.source import (
    SourceRange,
    count_turns_from,
    load_candidates,
    load_segment,
    message_key,
    next_chapter_start,
    read_source,
    section_ranges,
    segment_hash,
)
from factories import Room, _make_novel_tree, _open_room

_EXCLUDED = "빼기로-한-구간-표지"
_CONTEXT = "참고로-보낸-구간-표지"


def _message(room_id: uuid.UUID, role: ChatMessageRole, content: str, key: MessageKey) -> ChatMessage:
    return ChatMessage(id=key[1], chat_room_id=room_id, role=role, content=content, created_at=key[0])


async def _all(db: AsyncSession, room_id: uuid.UUID) -> list[ChatMessage]:
    rows = await db.scalars(
        sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id).order_by(ChatMessage.created_at, ChatMessage.id)
    )
    return list(rows.all())


async def _mark(db: AsyncSession, messages: list[ChatMessage], marker: str) -> None:
    for message in messages:
        message.content = f"{message.content} {marker}"
    await db.flush()


# ── 옮기기 전 질의(기준 구현) ────────────────────────────────────────────────
_KEY = sa.tuple_(ChatMessage.created_at, ChatMessage.id)
_ORDER = (ChatMessage.created_at.asc(), ChatMessage.id.asc())


async def _old_segment(db: AsyncSession, room_id: uuid.UUID, start: MessageKey, end: MessageKey) -> list[uuid.UUID]:
    rows = await db.scalars(
        sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id, _KEY >= start, _KEY <= end).order_by(*_ORDER)
    )
    return [m.id for m in rows.all()]


async def _old_candidates(db: AsyncSession, room_id: uuid.UUID, start: MessageKey, max_turns: int) -> list[uuid.UUID]:
    if max_turns < 1:
        return []
    batch = max_turns * 2 + 2
    picked: list[ChatMessage] = []
    assistants = 0
    cursor: MessageKey | None = None
    while True:
        query = sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
        query = query.where(_KEY > cursor) if cursor is not None else query.where(_KEY >= start)
        rows = list((await db.scalars(query.order_by(*_ORDER).limit(batch))).all())
        for message in rows:
            picked.append(message)
            if message.role == ChatMessageRole.ASSISTANT:
                assistants += 1
                if assistants == max_turns:
                    return [m.id for m in picked]
        if len(rows) < batch:
            break
        cursor = (rows[-1].created_at, rows[-1].id)
    while picked and picked[-1].role == ChatMessageRole.USER:
        picked.pop()
    return [m.id for m in picked]


async def _old_next_start(db: AsyncSession, room_id: uuid.UUID, end: MessageKey | None) -> uuid.UUID | None:
    query = sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    if end is not None:
        query = query.where(_KEY > end)
    message = await db.scalar(query.order_by(*_ORDER).limit(1))
    return None if message is None else message.id


async def _old_remaining(db: AsyncSession, room_id: uuid.UUID, start: MessageKey) -> int:
    count = await db.scalar(
        sa.select(sa.func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.ASSISTANT, _KEY >= start)
    )
    return int(count or 0)


async def _tangled_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Room, list[ChatMessage]]:
    """오프닝 + 5턴에, 끝 응답과 같은 시각의 메시지 둘(id 가 작고 큰 것), 여섯 개가 이어지는 사용자 메시지 줄과 그 응답,
    응답 없는 마지막 사용자 메시지를 더한 방. 다른 방 메시지도 하나 둔다(방 조건이 빠지면 섞인다)."""
    room = await _open_room(db_client, db_session, turns=5)
    other = await _open_room(db_client, db_session, turns=1)
    a3 = room.turns[3][1]
    tie_low = (a3.created_at, uuid.UUID(int=a3.id.int - 1))
    tie_high = (a3.created_at, uuid.UUID(int=a3.id.int + 1))
    tail = room.base + timedelta(minutes=10)
    extra = [
        _message(room.room_id, ChatMessageRole.USER, "같은 시각 앞", tie_low),
        _message(room.room_id, ChatMessageRole.ASSISTANT, "같은 시각 뒤 응답", tie_high),
        *(
            _message(room.room_id, ChatMessageRole.USER, f"이어지는 말 {i}", (tail + timedelta(seconds=i), uuid.uuid4()))
            for i in range(6)
        ),
        _message(room.room_id, ChatMessageRole.ASSISTANT, "긴 줄 뒤 응답", (tail + timedelta(seconds=10), uuid.uuid4())),
        _message(room.room_id, ChatMessageRole.USER, "응답 없는 마지막 말", (tail + timedelta(seconds=20), uuid.uuid4())),
        _message(other.room_id, ChatMessageRole.ASSISTANT, "다른 방", (tail + timedelta(seconds=5), uuid.uuid4())),
    ]
    db_session.add_all(extra)
    await db_session.flush()
    return room, await _all(db_session, room.room_id)


# ── 옛 흐름 어댑터 = 옮기기 전과 같은 행 ────────────────────────────────────
async def test_the_old_flow_reads_the_same_rows_through_the_gateway(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """구간 읽기(시작·끝 모든 짝), 경계 후보(모든 시작 × 상한 0~5와 방 전체보다 큰 상한), 다음 화 시작(모든 끝 + 첫 화), 남은 턴
    수(모든 시작)가 옮기기 전 질의와 같다. 깨지는 시나리오: 관문으로 옮기며 키 비교를 `>=`/`>` 로 바꾸거나, 같은 시각 메시지의
    순서를 시각만으로 정하거나, 후보가 한 번에 읽는 개수에서 멈추거나, 끝의 응답 없는 사용자 말을 남겨 옛 흐름의 경계·해시가
    달라진다."""
    room, messages = await _tangled_room(db_client, db_session)
    keys = [message_key(m) for m in messages]
    room_id = room.room_id

    mismatches: list[str] = []
    for i, start in enumerate(keys):
        for end in keys[i:]:
            got = [m.id for m in await load_segment(db_session, room_id, start, end)]
            if got != await _old_segment(db_session, room_id, start, end):
                mismatches.append(f"segment {start}..{end}")
        for cap in (0, 1, 2, 3, 4, 5, 100):
            got = [m.id for m in await load_candidates(db_session, room_id, start, cap)]
            if got != await _old_candidates(db_session, room_id, start, cap):
                mismatches.append(f"candidates {start} cap={cap}")
        if await count_turns_from(db_session, room_id, start) != await _old_remaining(db_session, room_id, start):
            mismatches.append(f"remaining {start}")
    for end_key in [None, *keys]:
        chapter = None if end_key is None else NovelChapter(end_message_created_at=end_key[0], end_message_id=end_key[1])
        got_start = await next_chapter_start(db_session, room_id, chapter)
        if (None if got_start is None else got_start.id) != await _old_next_start(db_session, room_id, end_key):
            mismatches.append(f"next after {end_key}")

    assert mismatches == []
    assert len(keys) == 21  # 오프닝 1 + 5턴 10 + 같은 시각 2 + 긴 줄 6 + 그 응답 1 + 마지막 말 1


# ── 여러 구간 ───────────────────────────────────────────────────────────────
async def test_reading_ranges_returns_them_in_order_and_never_the_messages_between(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """구간 둘(1~2턴, 4~5턴)을 읽으면 그 메시지만 키 순으로 나오고 사이(3턴)는 나오지 않는다. 구간을 거꾸로 넘겨도 넘긴 순서대로
    읽는다(정렬은 호출자 몫). 깨지는 시나리오: 관문이 첫 구간 시작부터 마지막 구간 끝까지 한 번에 읽어 사용자가 뺀 구간이 모델에
    간다."""
    room = await _open_room(db_client, db_session, turns=5)
    await _mark(db_session, list(room.turns[3]), _EXCLUDED)
    first = SourceRange(message_key(room.turns[1][0]), message_key(room.turns[2][1]))
    second = SourceRange(message_key(room.turns[4][0]), message_key(room.turns[5][1]))

    read = await read_source(db_session, room.room_id, [first, second])
    flipped = await read_source(db_session, room.room_id, [second, first])

    expected = [m.id for turn in (1, 2, 4, 5) for m in room.turns[turn]]
    assert [m.id for m in read] == expected
    assert not any(_EXCLUDED in m.content for m in read)
    assert [m.id for m in flipped] == expected[4:] + expected[:4]


async def test_a_turn_cap_counts_replies_across_ranges_and_drops_a_trailing_unanswered_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상한은 구간을 건너 이어 센다 — 응답 3개 상한이면 첫 구간(응답 2개) 다음 구간의 첫 응답에서 멈춘다. 끝이 열린 구간이 응답
    없는 사용자 말로 끝나면 그 말은 뺀다. 상한 0 은 빈 목록. 깨지는 시나리오: 구간마다 상한을 새로 세 모델 턴 상한(작업 시간
    상한에서 나온 값)을 넘는 원문을 싣는다."""
    room = await _open_room(db_client, db_session, turns=5)
    trailing = _message(
        room.room_id, ChatMessageRole.USER, "응답 없는 말", (room.base + timedelta(minutes=5), uuid.uuid4())
    )
    db_session.add(trailing)
    await db_session.flush()
    first = SourceRange(message_key(room.turns[1][0]), message_key(room.turns[2][1]))
    open_ended = SourceRange(message_key(room.turns[4][0]), None)

    capped = await read_source(db_session, room.room_id, [first, open_ended], turn_cap=3)
    uncapped = await read_source(db_session, room.room_id, [first, open_ended], turn_cap=10)
    nothing = await read_source(db_session, room.room_id, [first], turn_cap=0)

    assert [m.id for m in capped] == [m.id for turn in (1, 2, 4) for m in room.turns[turn]]
    assert [m.id for m in uncapped] == [m.id for turn in (1, 2, 4, 5) for m in room.turns[turn]]
    assert nothing == []


async def test_a_stored_selection_reads_include_and_context_sections_and_never_the_gaps(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """저장된 구간 선택(include 1~2턴, context 3턴, include 5턴 — 행은 뒤섞어 넣음)을 관문으로 읽으면 구간 행이 키 순으로 나오고,
    선택하지 않은 4턴(곧 exclude)과 고정 끝 뒤의 6턴은 나오지 않는다. 구간마다의 해시는 그 구간을 다시 읽은 해시와 같다. 깨지는
    시나리오: 구간 행을 넣은 순서대로 읽어 원문이 뒤섞이거나, 사이 공백·승인 뒤 새 메시지가 실린다."""
    room = await _open_room(db_client, db_session, turns=6)
    tree = await _make_novel_tree(db_session, room.user_id, chat_room_id=room.room_id)
    await _mark(db_session, list(room.turns[4]) + list(room.turns[6]), _EXCLUDED)
    await _mark(db_session, list(room.turns[3]), _CONTEXT)

    def section(mode: str, first: int, last: int) -> NovelSourceSection:
        messages = [m for turn in range(first, last + 1) for m in room.turns[turn]]
        return NovelSourceSection(
            mode=mode,
            start_message_id=messages[0].id,
            start_message_created_at=messages[0].created_at,
            end_message_id=messages[-1].id,
            end_message_created_at=messages[-1].created_at,
            assistant_message_count=last - first + 1,
            source_hash=segment_hash(messages),
        )

    selection = NovelSourceSelection(
        novel_id=tree.novel.id,
        revision=1,
        room_end_message_id=room.turns[5][1].id,
        room_end_message_created_at=room.turns[5][1].created_at,
    )
    db_session.add(selection)
    await db_session.flush()
    sections = [section("include", 5, 5), section("include", 1, 2), section("context", 3, 3)]
    for row in sections:
        row.selection_id = selection.id
    db_session.add_all(sections)
    await db_session.flush()

    include = section_ranges(sections, mode="include")
    context = section_ranges(sections, mode="context")
    read = await read_source(db_session, room.room_id, include)
    read_context = await read_source(db_session, room.room_id, context)
    rehashed = [segment_hash(await read_source(db_session, room.room_id, [r])) for r in include + context]

    assert [m.id for m in read] == [m.id for turn in (1, 2, 5) for m in room.turns[turn]]
    assert [m.id for m in read_context] == [m.id for m in room.turns[3]]
    assert not any(_EXCLUDED in m.content for m in read + read_context)
    assert not any(_CONTEXT in m.content for m in read)
    assert rehashed == [s.source_hash for s in (sections[1], sections[0], sections[2])]
