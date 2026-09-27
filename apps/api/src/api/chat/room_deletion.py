"""채팅방과 그 자식 행을 지우는 단 한 곳.

방 삭제와 회원 탈퇴가 이 함수를 같이 쓴다. 두 경로가 자식 목록을 따로 가지면 자식 테이블이 늘
때 한쪽에만 더해지기 쉽고, 빠진 쪽은 방 DELETE가 FK 위반으로 500이 된다 — 그래서 사본을 두지
않는다. `ON DELETE CASCADE`가 없으므로(apps/api/CLAUDE.md 모델 규약) 자식을 먼저 지운다.

이 모듈은 라우터를 import하지 않는다 — `auth/router.py`가 import해도 순환이 생기지 않게."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.chat import ChatMessage, ChatRoom, ChatRoomStat


async def delete_chat_rooms(db: AsyncSession, room_ids: Sequence[uuid.UUID]) -> None:
    """`room_ids` 방들을 자식(스탯 → 메시지)부터 지우고 방 행을 지운다. 커밋은 호출부가 한다 —
    탈퇴는 같은 트랜잭션에서 다른 정리도 한다."""
    if not room_ids:
        return
    await db.execute(delete(ChatRoomStat).where(ChatRoomStat.chat_room_id.in_(room_ids)))
    await db.execute(delete(ChatMessage).where(ChatMessage.chat_room_id.in_(room_ids)))
    await db.execute(delete(ChatRoom).where(ChatRoom.id.in_(room_ids)))
