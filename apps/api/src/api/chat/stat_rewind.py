"""메시지 수정·삭제가 지우는 턴의 스탯과 턴 수를 되돌린다 — 지운 턴이 없던 상태로.

근거는 턴 기록(`chat_turns`)의 스탯 변화 `{스탯: [반영 전, 반영 뒤]}` 다. 반영 전 값을 덮어 되돌린다. 규칙에 적힌 명목
변화량(예: +5)을 빼면 범위 끝에서 잘린 턴이 잘린 만큼 틀어진다. 기록의 반영 뒤 − 반영 전 차이는 잘린 뒤의 차이라 지금 값이 기록의
반영 뒤 값과 같으면 덮을 때와 같은 값이 나오지만, 반영 전 값이 비어 있는 스탯(그 턴 전에 행이 없던 스탯)은 차이를 낼 수 없고,
지금 값이 기록 밖에서 바뀐 방(기록을 쓰기 전의 옛 턴이 섞인 방)에서는 그만큼 그 턴 전 값에서 벗어난다.

기록은 지운 AI 응답의 메시지 id 로 찾는다 — 재생성 체인의 옛 행은 이미 지워진 응답의 것이라 잡히지 않고, 지금 보이는 응답의
기록이 그 턴 전체의 효과를 맡는다(재생성 기록의 반영 전 값은 원 턴의 것과 같다). 엔딩 상태와 해금 기록은 건드리지 않는다.

결과(`StatRewind`)는 화면이 안내 문구를 고르는 데 쓴다.
- `rewound`: 지운 턴의 스탯을 전부 되돌렸다.
- `partial`: 지운 턴에 기록을 쓰기 전에 보낸 옛 턴이 섞여 기록 있는 턴만 되돌렸다(하나도 못 되돌렸을 수 있다).
- `kept`: 되돌리지 않았다 — 중간 응답 삭제처럼 정확히 되돌릴 수 없는 경우.
- None: 지운 턴이 없거나 스탯이 없는 방이라 알릴 것이 없다.

부르는 쪽이 방 행을 먼저 잡은 트랜잭션에서 부른다(요약 되감기의 방 행 UPDATE 나 방 행 `FOR NO KEY UPDATE`). 이 모듈은 그 뒤에
스탯 행만 쓴다 — 턴 쓰기 구간·되돌리기·요약 되감기·잊게 하기도 방 행을 먼저 잡으므로 서로 거꾸로 기다리지 않는다. 커밋은 부르는
쪽이 한다. 이 모듈은 라우터를 import 하지 않는다."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.room_stats import load_room_stats
from api.chat.schemas import StatRewind
from api.chat.turn_judgments import _starting_values
from api.chat.turn_store import _write_room_stat
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomStat, ChatTurn
from api.db.models.story import StartingSetup, StatDef


async def rewind_removed_turns(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup | None, removed_reply_ids: Sequence[uuid.UUID]
) -> StatRewind | None:
    """수정이 편집 지점 뒤에서 지우는 AI 응답들(`removed_reply_ids`, 일어난 순서)의 스탯 효과를 되돌린다. 턴 수는 부르는 쪽이
    줄인다. 기록을 늦은 턴부터 이른 턴 순으로 접어 각 기록의 반영 전 값을 덮으므로, 스탯마다 그 스탯을 바꾼 가장 이른 지운 턴의
    반영 전 값이 남는다. 지운 응답은 아직 지우기 전이어도, 이미 지웠어도 된다(기록은 메시지와 FK 가 없다)."""
    if setup is None or not removed_reply_ids:
        return None
    records = {
        record.assistant_message_id: record
        for record in (
            await db.scalars(select(ChatTurn).where(ChatTurn.assistant_message_id.in_(removed_reply_ids)))
        ).all()
    }
    if records:
        stat_defs, stat_rows, values = await load_room_stats(db, room.id, setup.id)
        target = values
        for reply_id in reversed(removed_reply_ids):
            record = records.get(reply_id)
            if record is not None:
                target = _starting_values(target, record.stat_changes, stat_defs)
        _write_changed(db, room, stat_defs, stat_rows, values, target)
    return "rewound" if len(records) == len(removed_reply_ids) else "partial"


async def rewind_deleted_message(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup | None, message: ChatMessage
) -> StatRewind | None:
    """메시지 하나를 지우기 직전에 부른다. 방의 마지막 AI 응답이고 그 기록이 방의 마지막 턴(`turn_number == turn_count`)이면 그
    기록의 반영 전 값으로 되돌리고 `turn_count` 를 하나 줄인다 — 남은 마지막 응답의 기록 번호가 다시 방 턴 수와 같아져 재생성
    재판정·되돌리기가 그 응답을 그대로 다룬다.

    그 밖에는 스탯도 턴 수도 그대로 둔다.
    - 사용자 메시지: 턴 효과는 응답의 기록에 있다(None).
    - 중간 응답: 반영 전 값은 절대값이라 덮으면 뒤에 남은 턴들의 효과까지 사라진다. 턴 수를 줄이면 남은 마지막 응답의 기록 번호가
      방 턴 수보다 커져 재생성 재판정·되돌리기에서 빠지고, 다음 턴이 같은 번호를 받는다(`kept`).
    - 기록이 없는 마지막 응답: 방에 턴이 없으면 오프닝이라 되돌릴 것이 없고(None), 있으면 기록을 쓰기 전에 보낸 옛 턴이라 무엇을
      되돌릴지 모른다(`partial`).
    - 기록 번호가 방 턴 수와 다른 마지막 응답: 턴 수를 줄이지 않던 옛 삭제가 뒤 턴을 지운 방이다. 그 기록의 반영 전 값은 옛 삭제가
      남긴 효과까지 지우므로 재생성·되돌리기와 같은 조건으로 되돌리지 않는다(`kept`).

    스탯이 없는 방(캐릭터 방)도 턴 수는 같은 규칙으로 줄이고, 알릴 것은 없다(None)."""
    if message.role != ChatMessageRole.ASSISTANT:
        return None
    notice: StatRewind | None = "kept" if setup is not None else None
    last_reply_id = await db.scalar(
        select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room.id, ChatMessage.role == ChatMessageRole.ASSISTANT)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    if last_reply_id != message.id:
        return notice
    record = await db.scalar(select(ChatTurn).where(ChatTurn.assistant_message_id == message.id))
    if record is None:
        return "partial" if setup is not None and room.turn_count > 0 else None
    if record.turn_number != room.turn_count:
        return notice
    room.turn_count -= 1
    if setup is None:
        return None
    stat_defs, stat_rows, values = await load_room_stats(db, room.id, setup.id)
    _write_changed(db, room, stat_defs, stat_rows, values, _starting_values(values, record.stat_changes, stat_defs))
    return "rewound"


def _write_changed(
    db: AsyncSession,
    room: ChatRoom,
    stat_defs: list[StatDef],
    stat_rows: dict[str, ChatRoomStat],
    values: dict[str, float],
    target: dict[str, float],
) -> None:
    """지금 정의에 있는 스탯 중 값이 바뀌는 것만 쓴다. 정의에 없는 스탯(그 스탯이 없는 버전으로 옮긴 방)은 화면에도 판정에도
    쓰이지 않아 고칠 이유가 없다 — `_starting_values` 는 그런 스탯도 기록의 반영 전 값으로 돌려주므로 여기서 거른다."""
    for stat_def in stat_defs:
        stat_id = str(stat_def.entity_id)
        if target[stat_id] != values[stat_id]:
            _write_room_stat(db, room.id, stat_rows, stat_id, target[stat_id])
