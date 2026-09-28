"""긴 방의 생성 프롬프트에 실을 히스토리(윈도우)를 정한다.

요약 스냅샷이 덮은 메시지(커서 이하)는 요약이 대신 싣고, 원문으로는 커서 **뒤** 메시지만 싣는다.
커서는 요약이 커밋될 때만 앞으로 가므로, 요약이 실패하거나 늦어도 요약되지 않은 메시지는 하나도
빠지지 않는다 — 윈도우는 턴 수나 글자 수를 세지 않는다. 스냅샷이 없는 방은 입력 그대로다.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatMessage, ChatMessageRole, ChatRoomMemorySnapshot

# 메시지의 정렬 키이자 스냅샷 커서의 모양. `created_at`이 같은 메시지도 `id`로 한 줄로 선다.
MessageKey = tuple[datetime, uuid.UUID]


async def load_summary_cursor(db: AsyncSession, room_id: uuid.UUID) -> MessageKey | None:
    """방의 현재 요약(커서가 가장 큰 스냅샷)의 커서. 스냅샷이 없으면 None."""
    row = (
        await db.execute(
            select(ChatRoomMemorySnapshot.cursor_created_at, ChatRoomMemorySnapshot.cursor_message_id)
            .where(ChatRoomMemorySnapshot.chat_room_id == room_id)
            .order_by(
                ChatRoomMemorySnapshot.cursor_created_at.desc(), ChatRoomMemorySnapshot.cursor_message_id.desc()
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return (row.cursor_created_at, row.cursor_message_id)


def prompt_window(messages: Sequence[ChatMessage], cursor: MessageKey | None) -> list[ChatMessage]:
    """`messages`는 방 메시지를 `(created_at, id)` 순으로 읽은 목록(의 앞부분)이다. 커서가 없으면
    그대로, 있으면 오프닝 + 키가 커서보다 큰 메시지.

    오프닝은 방의 첫 메시지가 어시스턴트 메시지일 때 그 메시지다 — 방을 만들거나 초기화할 때 그
    트랜잭션에 다른 메시지 없이 들어가므로 언제나 가장 앞에 선다. 캐릭터 챗의 인트로는 이 메시지로만
    실리고 스토리의 오프닝은 프롤로그와 다를 수 있어, 요약 커서가 지나가도 윈도우 맨 앞에 남긴다.
    사용자가 오프닝을 지웠으면 첫 메시지가 사용자 메시지라 고정할 것이 없다."""
    if cursor is None:
        return list(messages)
    opening = messages[0] if messages and messages[0].role == ChatMessageRole.ASSISTANT else None
    return [
        message
        for message in messages
        if message is opening or (message.created_at, message.id) > cursor
    ]
