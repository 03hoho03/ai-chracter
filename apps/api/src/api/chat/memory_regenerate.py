"""방의 지금 요약을 AI 로 다시 만든다 — 같은 구간을 같은 입력으로 다시 접어 같은 스냅샷 행을 제자리에서 고친다.

다시 접는 것은 지금 요약(커서가 가장 큰 스냅샷) 하나뿐이다. 입력은 바로 앞 스냅샷의 요약(없으면 빈 요약)과 두 커서 사이 원문으로,
그 접기가 받았던 입력과 같은 구간이다 — 그 구간의 메시지를 고치거나 지우면 되감기가 지금 스냅샷을 지우므로, 스냅샷이 살아 있는
한 구간은 바뀌지 않는다. 앞 스냅샷을 사용자가 고쳤으면 고친 글이 입력이다("지금의 앞 요약으로 다시 접기").

동시성은 접기와 같은 규칙이다. 방의 `memory_version` 을 가장 먼저 읽고(호출부가 요청의 버전과 맞대 본다), 요약을 기다리는
동안 커넥션을 쥐지 않고, 쓸 때 "버전이 읽은 값 그대로일 때만" 버전을 올리며 스냅샷을 고친다. 그사이 접기·편집·되감기가
버전을 바꿨으면 쓰지 않는다. 거꾸로 다시 만들기가 먼저 커밋하면 진행 중이던 접기가 버전이 달라진 것을 보고 결과를 버린다.

고치기 직전 글과 그 출처는 되돌리기 칸(`previous_text`·`previous_source`)에 들어간다 — 같은 구간을 다시 요약한 것이라 되돌려도
접힌 대화가 요약에서 빠지지 않는다. 칸은 하나라 사용자가 고친 요약을 다시 만들면 고친 글이 칸에 들어가고, 그 전의 글로는 돌아갈
수 없다. 다시 만든 요약의 출처는 AI(`"auto"`)다.

같은 방에는 한 번에 하나만 받는다(`hold_regenerate_lock`) — 두 번째 요청을 기다리게 하지 않고 바로 거절해, 같은 요약을 두 번
부르는 원가와 두 번 깎고 한 번 돌려주는 내역이 생기지 않게 한다. 클로버 차감·환불은 라우트(`chat/router.py`)가 한다.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from redis.exceptions import RedisError
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_fold import _load_unsummarized
from api.chat.memory_window import MessageKey, select_current_snapshot
from api.core.rate_limit_gate import _report_redis_failure
from api.core.redis import redis_client
from api.core.redis_lock import release_lock, try_acquire_lock
from api.db.models import ChatMessage, ChatRoom, ChatRoomMemorySnapshot

logger = logging.getLogger(__name__)

# 진행 표시의 수명. 요약 호출 하나에는 호출 시간 상한이 있어 정상이면 이보다 훨씬 짧다. 배포·크래시로 풀지 못한 표시는 이 시간이
# 지나 풀린다. 넘친 요청과 겹친 두 번째 요청이 들어와도 돈은 맞다 — 늦게 쓰는 쪽이 버전 충돌로 환불받는다.
REGENERATE_LOCK_TTL_MS = 60_000


class RegenerateInProgressError(Exception):
    """같은 방에서 다시 만들기가 이미 진행 중이다."""


class RegenerateRoomMissingError(Exception):
    """방이 없다(주인 확인 뒤 지워졌다)."""


class RegenerateVersionConflictError(Exception):
    """요청이 본 버전과 방의 버전이 다르거나, 요약을 기다리는 사이 기억이 바뀌었다."""


class RegenerateNothingToFoldError(Exception):
    """아직 요약이 없다(첫 접기 전)."""


@dataclass(frozen=True)
class RegenerateInput:
    """다시 접을 입력. `version` 은 읽을 때의 방 버전, `snapshot_id` 는 고칠 행이다."""

    version: int
    snapshot_id: uuid.UUID
    previous_summary: str
    turns: list[ChatMessage]


async def load_regenerate_input(db: AsyncSession, room_id: uuid.UUID, *, expected_version: int) -> RegenerateInput:
    """방의 버전을 먼저 읽어 `expected_version` 과 맞대고, 지금 스냅샷과 그 앞 스냅샷, 두 커서 사이 원문(오프닝 제외, 접기와 같은
    규칙)을 읽는다. 아무것도 쓰지 않는다. 버전을 다른 읽기보다 먼저 읽어야 그 사이 커밋된 되감기의 버전 증가를 이 값이 흡수하지
    않는다(접기와 같은 이유)."""
    version = await db.scalar(select(ChatRoom.memory_version).where(ChatRoom.id == room_id))
    if version is None:
        raise RegenerateRoomMissingError
    if version != expected_version:
        raise RegenerateVersionConflictError
    current = (
        await db.execute(
            select_current_snapshot(
                room_id,
                ChatRoomMemorySnapshot.id,
                ChatRoomMemorySnapshot.cursor_created_at,
                ChatRoomMemorySnapshot.cursor_message_id,
            )
        )
    ).first()
    if current is None:
        raise RegenerateNothingToFoldError
    cursor: MessageKey = (current.cursor_created_at, current.cursor_message_id)
    previous = (
        await db.execute(
            select(
                ChatRoomMemorySnapshot.cursor_created_at,
                ChatRoomMemorySnapshot.cursor_message_id,
                ChatRoomMemorySnapshot.summary_text,
            )
            .where(
                ChatRoomMemorySnapshot.chat_room_id == room_id,
                tuple_(ChatRoomMemorySnapshot.cursor_created_at, ChatRoomMemorySnapshot.cursor_message_id) < cursor,
            )
            .order_by(
                ChatRoomMemorySnapshot.cursor_created_at.desc(), ChatRoomMemorySnapshot.cursor_message_id.desc()
            )
            .limit(1)
        )
    ).first()
    previous_cursor: MessageKey | None = (
        (previous.cursor_created_at, previous.cursor_message_id) if previous is not None else None
    )
    after_previous = await _load_unsummarized(db, room_id, previous_cursor)
    return RegenerateInput(
        version=version,
        snapshot_id=current.id,
        previous_summary=previous.summary_text if previous is not None else "",
        turns=[message for message in after_previous if (message.created_at, message.id) <= cursor],
    )


async def write_regenerated(db: AsyncSession, room_id: uuid.UUID, source: RegenerateInput, summary: str) -> None:
    """버전이 `source.version` 그대로일 때만 버전을 올리고(방 행 잠금을 겸한다) 같은 스냅샷 행의 글을 바꾼다. 고치기 직전 글과
    출처는 되돌리기 칸으로 옮긴다. 버전이 달라졌으면 아무것도 쓰지 않고 `RegenerateVersionConflictError`. 커밋은 호출부가 한다."""
    claimed = await db.scalar(
        update(ChatRoom)
        .where(ChatRoom.id == room_id, ChatRoom.memory_version == source.version)
        .values(memory_version=ChatRoom.memory_version + 1)
        .returning(ChatRoom.id)
    )
    if claimed is None:
        raise RegenerateVersionConflictError
    await db.execute(
        update(ChatRoomMemorySnapshot)
        .where(ChatRoomMemorySnapshot.id == source.snapshot_id)
        .values(
            summary_text=summary,
            previous_text=ChatRoomMemorySnapshot.summary_text,
            previous_source=ChatRoomMemorySnapshot.source,
            source="auto",
            updated_at=func.now(),
        )
    )


def _lock_key(room_id: uuid.UUID) -> str:
    return f"chat_room:memory_regenerate_lock:{room_id}"


@asynccontextmanager
async def hold_regenerate_lock(room_id: uuid.UUID) -> AsyncIterator[None]:
    """방의 다시 만들기 진행 표시를 잡고, 블록이 어떻게 끝나든 푼다. 이미 누가 쥐고 있으면 블록에 들어가기 전에
    `RegenerateInProgressError`. 소유자 토큰으로 지우므로 늦게 끝난 요청이 뒤에 잡힌 표시를 지우지 않는다.

    Redis 장애면 표시 없이 진행한다(턴 락과 같은 선택). 겹친 두 요청이 둘 다 깎아도 늦게 쓰는 쪽이 버전 충돌로 환불받으므로 잃는
    것은 요약 호출 원가 한 번이다."""
    key = _lock_key(room_id)
    try:
        token = await try_acquire_lock(redis_client, key, ttl_ms=REGENERATE_LOCK_TTL_MS)
    except RedisError as exc:
        logger.warning("대화방 %s 요약 다시 만들기 표시를 잡지 못했다(Redis 장애) — 표시 없이 진행한다: %s", room_id, exc)
        _report_redis_failure()
        yield
        return
    if token is None:
        raise RegenerateInProgressError
    try:
        yield
    finally:
        try:
            await release_lock(redis_client, key, token)
        except RedisError as exc:
            logger.warning("대화방 %s 요약 다시 만들기 표시를 풀지 못했다 — 수명이 지나면 풀린다: %s", room_id, exc)
