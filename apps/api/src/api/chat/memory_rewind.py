"""대화를 되감으면(메시지 편집·삭제, 재생성, 초기화) 요약도 되감는다.

요약 스냅샷은 커서 이하 대화를 덮는다. 그 구간의 메시지가 바뀌거나 사라졌는데 스냅샷이 남으면 지운
대화가 요약에 실려 계속 전송된다. 그래서 바뀐 지점 이상을 덮는 스냅샷을 지우고 직전 스냅샷으로
돌아간다. 복귀한 스냅샷의 커서 뒤 메시지는 전부 원문으로 다시 실리므로(윈도우는 커서 뒤를 하나도
빼지 않는다) 잃는 대화가 없고 요약을 새로 부르지도 않는다.

이 모듈은 라우터를 import하지 않는다."""

import uuid

from sqlalchemy import delete, func, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.db.models import ChatRoom, ChatRoomMemorySnapshot


async def rewind_memory(db: AsyncSession, room_id: uuid.UUID, from_key: MessageKey | None) -> None:
    """`from_key` 메시지가 바뀌거나 사라지는 방의 요약을 되감는다. `from_key`가 None이면(초기화) 요약을
    전부 지운다. 커밋은 호출부가 한다 — 메시지 편집·삭제와 같은 트랜잭션이어야 중간 상태가 안 보인다.

    1. 첫 문장은 방 행의 `memory_version`을 올리는 UPDATE다. 버전은 되감을 스냅샷이 없어도 **항상**
       오른다 — 요약 접기는 "처음 읽은 버전 그대로일 때만" 커밋하므로, 지금 도는 접기가 바뀌기 전
       대화로 만든 요약을 넣지 못하게 된다. 이 UPDATE가 방 행 락을 겸한다.
    2. 락을 잡은 **뒤에** 스냅샷을 지운다. 순서가 반대면, 이미 방 행을 잡고 커밋 직전인 접기의
       스냅샷을 DELETE가 못 본 채 지나가고, 접기가 커밋한 뒤에야 버전이 올라 지운 대화를 덮는
       스냅샷이 남는다. 락 뒤의 DELETE는 그 커밋까지 본다.
    3. 지우는 대상은 커서가 `from_key` 이상인 스냅샷이다 — 바뀐 메시지를 덮는 스냅샷과 그 뒤
       스냅샷 전부. 현재 커서(가장 큰 커서)가 `from_key`보다 작으면 대상이 없어 스냅샷은 그대로다.
       판정은 키 비교뿐이다(오프닝이라고 예외를 두지 않는다 — 오프닝을 지우면 모든 스냅샷이 지워진다).
    4. 한 행이라도 지웠으면 롤백 시각을 적는다(사용자에게 "요약이 되돌아갔다"를 알리는 근거). 초기화는
       롤백 안내 대상이 아니라서 그 시각을 비운다.

    남는 스냅샷은 고쳐 쓰지 않는다 — 사용자가 고친 요약과 되돌리기 버퍼가 그대로 돌아온다."""
    snapshots = ChatRoomMemorySnapshot
    if from_key is None:
        await db.execute(
            update(ChatRoom)
            .where(ChatRoom.id == room_id)
            .values(memory_version=ChatRoom.memory_version + 1, memory_rolled_back_at=None)
        )
        await db.execute(delete(snapshots).where(snapshots.chat_room_id == room_id))
        return

    await db.execute(
        update(ChatRoom).where(ChatRoom.id == room_id).values(memory_version=ChatRoom.memory_version + 1)
    )
    removed = (
        await db.scalars(
            delete(snapshots)
            .where(
                snapshots.chat_room_id == room_id,
                tuple_(snapshots.cursor_created_at, snapshots.cursor_message_id) >= from_key,
            )
            .returning(snapshots.id)
        )
    ).all()
    if removed:
        await db.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(memory_rolled_back_at=func.now()))
