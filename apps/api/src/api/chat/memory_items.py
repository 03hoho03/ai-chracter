"""방 주인에게 보여 주는 장면·사실 기억 목록(`GET /chat-rooms/{id}/memory/items`).

보이는 범위는 모델이 보는 범위와 같다 — 지운다·고친다가 뜻이 서려면 화면의 목록이 응답 프롬프트가 고르는 후보와 어긋나면 안
된다.
- 장면: 지금 요약 커서까지 접힌 스냅샷이 뽑았고 커서 이하에서 끝나는 것(회상 후보와 같은 조건, `chat/memory_recall.py`). 일어난
  순서(끝 메시지 키, 같으면 id)로 페이지씩.
- 사실: 같은 커서까지의 사실 행(사실 섹션과 같은 읽기 `fact_rows_statement`)을 키마다 이긴 행 하나로 줄인 것(사실 섹션과 같은
  규칙 `latest_by_key` — 반박된 값은 뒤의 같은 값 주장으로 되살아나지 않는다).
- 인상: 그 방의 인상 행 전부를 덮는 스냅샷 커서가 큰 것부터. 인상은 커서 이하의 스냅샷에서만 생기고 되감기가 스냅샷과 함께
  지우므로 커서로 거르지 않는다. 근거는 행 id 대신 지금 남은 근거 행에서 센 개수와 턴 범위만 낸다.

읽기만 하므로 생성·요약·추출 경로와 잠금을 나누지 않는다."""

import base64
import binascii
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ValidationError
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_facts import fact_rows_statement
from api.chat.memory_knowledge import latest_by_key
from api.chat.memory_window import load_current_summary, memory_model_in_scope
from api.core.config import settings
from api.db.models.chat import (
    ChatMemoryEpisode,
    ChatMemoryFact,
    ChatMemoryImpression,
    ChatRoom,
    ChatRoomMemorySnapshot,
    FactTruthStatus,
)
from api.llm.model_access import effective_room_model

EPISODE_PAGE_SIZE = 30

_TRUTH_LABELS: dict[FactTruthStatus, str] = {
    "confirmed": "이야기 속 사실",
    "claimed": "누군가의 말",
    "disproved": "나중에 아니라고 밝혀진 말",
}


def truth_label(status: FactTruthStatus) -> str:
    """사실의 진실 상태를 사용자에게 보일 말로. 확인됨은 이야기 안에서 일어난 일, 주장됨은 말한 사람만 그렇다고 한 것, 반박됨은
    뒤에서 아니라고 밝혀진 말이다."""
    return _TRUTH_LABELS[status]


class InvalidItemsCursorError(ValueError):
    """페이지 커서가 이 API 가 낸 모양이 아니다."""


class _EpisodeCursor(BaseModel):
    """다음 페이지가 이어질 자리 — 앞 페이지 마지막 장면의 정렬 키."""

    end_created_at: datetime
    end_message_id: uuid.UUID
    id: uuid.UUID


def _encode_cursor(row: ChatMemoryEpisode) -> str:
    cursor = _EpisodeCursor(end_created_at=row.end_created_at, end_message_id=row.end_message_id, id=row.id)
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode()


def _decode_cursor(raw: str) -> _EpisodeCursor:
    try:
        cursor = _EpisodeCursor.model_validate_json(base64.b64decode(raw, altchars=b"-_", validate=True))
    except (ValueError, ValidationError, binascii.Error):
        raise InvalidItemsCursorError from None
    if cursor.end_created_at.tzinfo is None:
        raise InvalidItemsCursorError
    return cursor


async def memory_items(
    db: AsyncSession, room_id: uuid.UUID, cursor: str | None
) -> tuple[list[ChatMemoryEpisode], str | None, list[ChatMemoryFact]]:
    """(장면 한 페이지, 다음 페이지 커서 — 마지막이면 None, 키마다 이긴 사실 행을 이긴 행을 쓴 순서로). 요약이 없으면 다 빈다.
    커서가 깨졌으면 `InvalidItemsCursorError`."""
    after = _decode_cursor(cursor) if cursor is not None else None
    summary = await load_current_summary(db, room_id)
    if summary is None:
        return [], None, []
    episode, snapshot = ChatMemoryEpisode, ChatRoomMemorySnapshot
    statement = (
        select(episode)
        .join(snapshot, snapshot.id == episode.snapshot_id)
        .where(
            episode.chat_room_id == room_id,
            tuple_(episode.end_created_at, episode.end_message_id) <= summary.cursor,
            tuple_(snapshot.cursor_created_at, snapshot.cursor_message_id) <= summary.cursor,
        )
        .order_by(episode.end_created_at, episode.end_message_id, episode.id)
        .limit(EPISODE_PAGE_SIZE + 1)
    )
    if after is not None:
        statement = statement.where(
            tuple_(episode.end_created_at, episode.end_message_id, episode.id)
            > (after.end_created_at, after.end_message_id, after.id)
        )
    rows = list((await db.scalars(statement)).all())
    page = rows[:EPISODE_PAGE_SIZE]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > EPISODE_PAGE_SIZE else None
    fact_rows: Sequence[ChatMemoryFact] = (await db.scalars(fact_rows_statement(room_id, summary.cursor))).all()
    facts = [row for _, row in sorted(latest_by_key(fact_rows), key=lambda winner: winner[0])]
    return page, next_cursor, facts


async def room_in_memory_scope(db: AsyncSession, room: ChatRoom) -> bool:
    """이 방의 레인과 다음 턴 글쓰기 모델(방이 고른 모델을 주인이 지금 쓸 수 있는 모델로 읽은 것 — 턴 차감과 같은 읽기)이 기억
    사용 범위에 드는가. 레인은 시작 설정이 있으면 스토리다."""
    lane = "story" if room.starting_setup_entity_id is not None else "character"
    model = await effective_room_model(db, room.user_id, room.chat_model)
    return memory_model_in_scope(lane, model, settings.memory_model_scope)


def used_in_replies(in_scope: bool) -> tuple[bool, bool]:
    """(장면, 사실)이 이 방의 다음 턴 응답 프롬프트에 실릴 수 있는가. 턴 조립과 같은 판정이다 — 생성 윈도우가 켜져 있고, 그
    기억의 스위치(회상·사실 주입)가 켜져 있고, 방이 기억 사용 범위에 들어야 한다(`in_scope`, `room_in_memory_scope`)."""
    usable = settings.memory_window_generation and in_scope
    return usable and settings.memory_episodes_recall, usable and settings.memory_facts_inject


@dataclass(frozen=True)
class ImpressionView:
    """인상 행 하나와 지금 남은 근거 행에서 센 것. 턴 범위는 근거 행이 하나도 없으면 None."""

    row: ChatMemoryImpression
    turn_start: int | None
    turn_end: int | None
    scene_count: int
    fact_count: int


async def memory_impressions(db: AsyncSession, room_id: uuid.UUID) -> list[ImpressionView]:
    """방의 인상을 덮는 스냅샷 커서가 큰 것부터. 질의는 인상 하나, 근거 장면 하나, 근거 사실 하나로 인상 수와 무관하다. 근거
    칸의 id 는 FK 가 아니므로 지금 남은 행만 센다 — 사실은 행이 아니라 서로 다른 키를 센다."""
    impression, snapshot = ChatMemoryImpression, ChatRoomMemorySnapshot
    rows = (
        await db.scalars(
            select(impression)
            .join(snapshot, snapshot.id == impression.snapshot_id)
            .where(impression.chat_room_id == room_id)
            .order_by(snapshot.cursor_created_at.desc(), snapshot.cursor_message_id.desc(), impression.id.desc())
        )
    ).all()
    sources = [({uuid.UUID(raw) for raw in row.episode_ids}, {uuid.UUID(raw) for raw in row.fact_ids}) for row in rows]
    all_episode_ids = set().union(*(episode_ids for episode_ids, _ in sources))
    all_fact_ids = set().union(*(fact_ids for _, fact_ids in sources))
    episodes: dict[uuid.UUID, tuple[int, int]] = {}
    if all_episode_ids:
        episode = ChatMemoryEpisode
        result = await db.execute(
            select(episode.id, episode.start_turn, episode.end_turn).where(
                episode.chat_room_id == room_id, episode.id.in_(all_episode_ids)
            )
        )
        episodes = {row_id: (start, end) for row_id, start, end in result.tuples()}
    facts: dict[uuid.UUID, tuple[str, int, int]] = {}
    if all_fact_ids:
        fact = ChatMemoryFact
        result_facts = await db.execute(
            select(fact.id, fact.fact_key, fact.start_turn, fact.end_turn).where(
                fact.chat_room_id == room_id, fact.id.in_(all_fact_ids)
            )
        )
        facts = {row_id: (key, start, end) for row_id, key, start, end in result_facts.tuples()}

    views: list[ImpressionView] = []
    for row, (episode_ids, fact_ids) in zip(rows, sources, strict=True):
        scene_spans = [episodes[row_id] for row_id in episode_ids if row_id in episodes]
        fact_rows = [facts[row_id] for row_id in fact_ids if row_id in facts]
        spans = scene_spans + [(start, end) for _, start, end in fact_rows]
        views.append(
            ImpressionView(
                row=row,
                turn_start=min(start for start, _ in spans) if spans else None,
                turn_end=max(end for _, end in spans) if spans else None,
                scene_count=len(scene_spans),
                fact_count=len({key for key, _, _ in fact_rows}),
            )
        )
    return views
