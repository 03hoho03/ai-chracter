"""채팅방과 그 자식 행을 지우는 단 한 곳.

방 삭제와 회원 탈퇴가 이 함수를 같이 쓴다. 두 경로가 자식 목록을 따로 가지면 자식 테이블이 늘
때 한쪽에만 더해지기 쉽고, 빠진 쪽은 방 DELETE가 FK 위반으로 500이 된다 — 그래서 사본을 두지
않는다. `ON DELETE CASCADE`가 없으므로(apps/api/CLAUDE.md 모델 규약) 자식을 먼저 지운다.

이 모듈은 라우터를 import하지 않는다 — `auth/router.py`가 import해도 순환이 생기지 않게."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.chat import ChatMessage, ChatRoom, ChatRoomMemorySnapshot, ChatRoomStat


async def delete_chat_rooms(db: AsyncSession, room_ids: Sequence[uuid.UUID]) -> None:
    """`room_ids` 방들을 자식(요약 스냅샷 → 스탯 → 메시지)부터 지우고 방 행을 지운다. 커밋은
    호출부가 한다 — 탈퇴는 같은 트랜잭션에서 다른 정리도 한다.

    첫 문장은 방 행의 `memory_version`을 올리는 UPDATE다. 요약 접기는 다른 세션에서 돌며
    "읽을 때의 버전이 그대로일 때만" 버전을 올리고 스냅샷을 넣는다. 이 UPDATE가 방 행을 먼저
    잠가 두면, 진행 중인 접기는 이 트랜잭션이 끝날 때까지 기다렸다가 버전이 바뀌었음을 보고
    물러난다. 순서가 반대(스냅샷 DELETE 먼저)면 그 사이 커밋된 접기 스냅샷이 남아 방 DELETE가
    FK 위반으로 실패한다. ORM 속성 대입이 아니라 명시 UPDATE 문인 이유는 두 가지다 — 탈퇴는 방을
    ORM 객체로 싣지 않고 id 목록만 넘기며, 증가를 SQL 쪽(`memory_version + 1`)에서 해야 먼저 읽어 둔
    값에 1을 더해 덮어쓰는 일 없이 원자적으로 오른다."""
    if not room_ids:
        return
    await db.execute(
        update(ChatRoom).where(ChatRoom.id.in_(room_ids)).values(memory_version=ChatRoom.memory_version + 1)
    )
    await db.execute(delete(ChatRoomMemorySnapshot).where(ChatRoomMemorySnapshot.chat_room_id.in_(room_ids)))
    await db.execute(delete(ChatRoomStat).where(ChatRoomStat.chat_room_id.in_(room_ids)))
    await db.execute(delete(ChatMessage).where(ChatMessage.chat_room_id.in_(room_ids)))
    await db.execute(delete(ChatRoom).where(ChatRoom.id.in_(room_ids)))
