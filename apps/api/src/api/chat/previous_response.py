"""재생성이 밀어낸 직전 응답(`chat_previous_responses`, 방당 한 행)으로 되돌리기, 그 행을 지우기, 방 응답에 실을 "되돌릴 답
있음" 판정.

보관은 재생성의 쓰기 구간이 옛 응답을 지우는 같은 트랜잭션에서 한다(`chat/turn_store.py` 의 `RoomTurnStore`). 이 모듈은
라우터를 import 하지 않는다(라우터가 이 모듈을 import 한다)."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_rewind import rewind_memory
from api.chat.room_stats import load_room_stats
from api.chat.turn_judgments import _starting_values
from api.chat.turn_store import _write_room_stat
from api.db.models.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatPreviousResponse,
    ChatRoom,
    ChatTurn,
    DiscardedResponse,
)
from api.db.models.story import StartingSetup


async def clear_previous_response(db: AsyncSession, room_id: uuid.UUID) -> None:
    """방의 보관 행을 지운다. 대화를 바꾸는 경로(보내기·수정·메시지 삭제·초기화)가 그 변경과 같은 커밋에서 부른다 — 바뀐 대화에
    밀려난 응답을 다시 끼워 넣지 않게. 커밋은 부르는 쪽이 한다."""
    await db.execute(delete(ChatPreviousResponse).where(ChatPreviousResponse.chat_room_id == room_id))


async def previous_response_for(
    db: AsyncSession, room_id: uuid.UUID, last_message_id: uuid.UUID | None
) -> uuid.UUID | None:
    """되돌릴 수 있는 응답의 id — 보관 행을 밀어낸 응답이 지금 방의 마지막 메시지(`last_message_id`)이면 그 id, 아니면 None.
    되돌리기 요청이 거절되는 조건과 같은 비교라, 화면이 이 값으로 띄운 메뉴는 그 사이 대화가 바뀌지 않았으면 성공한다."""
    if last_message_id is None:
        return None
    replaced_by = await db.scalar(
        select(ChatPreviousResponse.replaced_by_message_id).where(ChatPreviousResponse.chat_room_id == room_id)
    )
    return replaced_by if replaced_by == last_message_id else None


async def restore_previous_response(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup | None, message_id: uuid.UUID
) -> bool:
    """`message_id`(지금 보이는 응답)를 보관한 직전 응답과 맞바꾼다. 되돌렸으면 True, 되돌릴 수 없으면 False 다. 커밋은 부르는
    쪽이 한다 — False 여도 커밋한다(낡은 보관 행을 지웠을 수 있다).

    부르는 쪽이 방 턴 락과 방 행 잠금(`FOR NO KEY UPDATE`)을 먼저 잡는다. 그 뒤 보관 행 → 메시지 → 스탯 순서로 쓴다 — 턴 쓰기
    구간·방 삭제·요약 되감기·접기도 방 행을 먼저 잡으므로 서로 거꾸로 기다리지 않는다.

    - 보관 행이 없거나, 그 행을 밀어낸 응답이 방의 마지막 메시지가 아니면 되돌리지 않는다. 마지막 메시지를 가리키지 않는 행은
      낡았으므로(이 테이블을 모르는 옛 이미지가 대화를 바꿨다) 여기서 지운다. 행은 맞지만 `message_id` 가 그 응답이 아니면
      (같은 되돌리기가 두 번 왔다) 행을 그대로 두고 거절한다.
    - 요약은 두 응답 중 앞선 키부터 되감는다. 되살릴 응답이 더 앞이면 지금 응답까지 덮던 요약이, 다시 맞바꾸는 경우처럼 지금
      응답이 더 앞이면 그 응답을 덮던 요약이 사라진다.
    - 스탯은 `_restore_stats`, 메시지는 원래 id·시각 그대로 다시 넣고 지운 지금 응답을 보관 행에 옮겨 적는다. 턴 기록은 쓰지
      않는다 — 두 응답의 기록이 메시지 id 로 이미 남아 있어 다음 재생성이 되살린 응답의 기록으로 정확히 되돌린다. 엔딩은 손대지
      않는다."""
    kept = await db.scalar(
        select(ChatPreviousResponse).where(ChatPreviousResponse.chat_room_id == room.id).with_for_update()
    )
    if kept is None:
        return False
    last = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.chat_room_id == room.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    if last is None or kept.replaced_by_message_id != last.id:
        await db.delete(kept)
        return False
    if message_id != last.id:
        return False

    restored_id = kept.message_id
    await rewind_memory(db, room.id, min((kept.message_created_at, restored_id), (last.created_at, last.id)))
    if setup is not None:
        await _restore_stats(db, room, setup, current_message_id=last.id, restored_message_id=restored_id)

    await db.execute(delete(ChatMessage).where(ChatMessage.id == last.id))
    db.add(
        ChatMessage(
            id=restored_id,
            chat_room_id=room.id,
            role=ChatMessageRole.ASSISTANT,
            content=kept.content,
            created_at=kept.message_created_at,
            image_id=kept.image_id,
        )
    )
    kept.replaced_by_message_id = restored_id
    kept.message_id = last.id
    kept.message_created_at = last.created_at
    kept.content = last.content
    kept.image_id = last.image_id
    db.add(DiscardedResponse(user_id=room.user_id, chat_room_id=room.id, kind="undo", discarded_count=1))
    return True


async def _restore_stats(
    db: AsyncSession,
    room: ChatRoom,
    setup: StartingSetup,
    *,
    current_message_id: uuid.UUID,
    restored_message_id: uuid.UUID,
) -> None:
    """지금 응답의 턴 효과를 그 기록의 반영 전 값으로 되돌린 값(재생성 재판정과 같은 `_starting_values`) 위에, 되살릴 응답의 기록이
    남긴 반영 뒤 값을 덮어 쓴다. 재생성 재판정과 같은 조건에서만 한다 — 두 응답의 기록이 다 있고, 둘 다 엔딩이 없고, 방이 엔딩
    전이고, 그 턴이 방의 마지막 턴이다. 재판정 없이 옛 효과를 이어받은 재생성은 두 기록의 변화가 같아 결과가 지금 값과 같다.

    지금 정의에 없는 스탯(그 스탯이 없는 버전으로 옮긴 방)은 쓰지 않는다 — 화면에도 판정에도 쓰이지 않아 고칠 이유가 없다.
    `_starting_values` 는 정의 없는 스탯도 기록의 반영 전 값으로 돌려주므로 여기서 정의로 거른다."""
    if room.ending_reached:
        return
    records = {
        record.assistant_message_id: record
        for record in (
            await db.scalars(
                select(ChatTurn).where(ChatTurn.assistant_message_id.in_([current_message_id, restored_message_id]))
            )
        ).all()
    }
    current = records.get(current_message_id)
    restored = records.get(restored_message_id)
    if (
        current is None
        or restored is None
        or current.ending_entity_id is not None
        or restored.ending_entity_id is not None
        or current.turn_number != room.turn_count
    ):
        return
    stat_defs, stat_rows, values = await load_room_stats(db, room.id, setup.id)
    target = _starting_values(values, current.stat_changes, stat_defs)
    for stat_id, (_before, after) in restored.stat_changes.items():
        target[stat_id] = float(after)
    for stat_def in stat_defs:
        stat_id = str(stat_def.entity_id)
        if target[stat_id] != values[stat_id]:
            _write_room_stat(db, room.id, stat_rows, stat_id, target[stat_id])
