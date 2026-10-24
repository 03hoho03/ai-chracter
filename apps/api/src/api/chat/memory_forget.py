"""방 주인이 고른 장면·사실 기억을 지운다(잊게 하기 — `DELETE /chat-rooms/{id}/memory/episodes/{episodeId}`·
`DELETE /chat-rooms/{id}/memory/facts?key=`).

무엇을 지우나
- 장면 하나: 그 행. 임베딩은 장면 FK 의 CASCADE 가 함께 지운다.
- 사실 키 하나: 그 방의 같은 키 행 전부(옛 값 포함)와 그 임베딩(CASCADE). 최신 행만 지우면 바로 앞 행이 키의 값으로 올라와 지운
  것이 그대로 보인다. 사실은 접힌 구간에서만 뽑히므로 방의 모든 사실 행이 지금 요약 커서 이하다 — 커서로 거르지 않는다.
- 비밀 사실(키마다 이긴 행 — 사실 섹션과 같은 규칙 `latest_by_key` — 의 아는 사람이 정해진 키)이면 그 키의 어느 행과든 근거 메시지
  범위가 겹치는(양 끝 포함) 장면도 함께 지운다. 회상은 그 키를 모르는 인물 앞에서 이 장면들을 가리는데(`chat/memory_knowledge.py`),
  사실만 지우면 가림이 풀려 잊은 비밀이 장면으로 다시 실린다. 이긴 행이 공개면 회상이 그 키로 아무것도 가리지 않으므로 장면을
  지우지 않는다. 확인 대화가 함께 지울 장면 수를 미리 보여 주므로 미리 보기와 지우기가 같은 함수(`fact_forget_plan`)로 고른다.

잠금 순서 — 한 트랜잭션, 커밋은 호출부
1. 방 행 `FOR NO KEY UPDATE`. 스냅샷을 지우는 경로(되감기·초기화·방 삭제)와 요약 접기 커밋·요약 편집이 모두 방 행을 먼저 잡으므로
   그들과는 여기서 줄을 선다. 방이 이미 지워졌으면 `RoomMissingError`. 스냅샷을 지우는 새 경로도 방 행을 먼저 잡아야 한다 — 아니면
   아래 2 와 다른 순서로 스냅샷을 잡아 교착할 수 있다.
2. 그 방 스냅샷 전부 `FOR UPDATE`(커서 순). 장면·사실 추출과 임베딩 채우기는 방 행을 잡지 않고 마지막 트랜잭션에서 자기 스냅샷
   하나만 `FOR KEY SHARE` 로 잡는데, 그것과 충돌하는 행 잠금은 `FOR UPDATE` 뿐이다. 그래서 그들이 먼저 잡았으면 잊기가 그 커밋을
   기다렸다가(대상은 기다린 뒤의 문장으로 고르므로) 방금 들어간 행까지 보고 지우고, 잊기가 먼저면 그들이 잊기 커밋을 기다린다.
   그들은 스냅샷 하나만 쥐고 잊기가 쥔 다른 잠금을 기다리지 않으므로 순환이 없다. 임베딩 채우기가 지운 행에 넣으려 하면 FK 위반을
   경합으로 보고 건너뛴다(`chat/memory_embeddings.py`).
3. 대상을 고르고 DELETE. 사실을 지웠으면 같은 트랜잭션에서 방의 잊기 세대(`memory_forget_generation`)를 하나 올린다 — 잊기 전에
   입력(앞 사실 목록)을 읽은 사실 추출은 그 키를 다시 낼 수 있고, 잊기 전에 창을 읽은 장면 추출은 잊은 비밀과 겹치는 장면을 가려
   줄 사실 없이 넣게 된다(함께 지우는 장면은 잊는 순간 있던 것뿐이다). 그래서 두 추출 모두 넣기 직전에 세대가 바뀐 것을 보면 결과를
   버린다(`chat/memory_facts.py`·`chat/memory_episodes.py`). 버린 스냅샷은 다시 쥐어지고 창 원문은 그대로라 같은 장면·사실이 다시
   뽑힐 수 있다 — 세대 확인은 잊기와 겹친 그 한 번의 결과만 막는다.

`memory_version` 은 올리지 않는다 — 요약이 바뀌지 않으므로 진행 중 접기와 열려 있던 요약 편집을 버릴 이유가 없다.

다시 생길 수 있는 것: 잊게 하기는 원문을 지우지 않으므로 같은 장면·사실이 다시 뽑힐 수 있다. 되감기는 커서가 바뀐 메시지 이상인
스냅샷을 전부 지운다(`chat/memory_rewind.py`) — 그래서 잊은 행을 뽑은 스냅샷이 덮는 구간 안이나 그보다 앞의 메시지를 고치거나
지우거나 재생성하면 그 구간이 다시 접히고, 같은 원문에서 같은 행이 다시 나올 수 있다. 되감기가 없어도 아직 접히지 않은 대화나 그 뒤에
이어진 대화에 같은 내용이 있으면 다음 접기에서 새로 뽑힌다. 요약 글과 원문 창에는 처음부터 남는다. 턴 기록에는 실었던 행의 id 만
남는다(글 없음)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_knowledge import latest_by_key, overlaps
from api.chat.memory_window import MessageKey
from api.db.models.chat import ChatMemoryEpisode, ChatMemoryFact, ChatRoom, ChatRoomMemorySnapshot


class RoomMissingError(LookupError):
    """방이 주인 확인 뒤 지워졌다."""


class MemoryItemMissingError(LookupError):
    """그 방에 지울 장면이나 키가 없다."""


@dataclass(frozen=True)
class FactForgetPlan:
    """키 하나를 잊을 때 함께 지울 장면 id(일어난 순서). 비밀 사실이 아니면 빈 목록이다."""

    episode_ids: list[uuid.UUID]


async def _lock_room_memory(db: AsyncSession, room_id: uuid.UUID) -> None:
    """잠금 순서 1·2(모듈 설명). 방이 없으면 `RoomMissingError`."""
    locked = await db.scalar(select(ChatRoom.id).where(ChatRoom.id == room_id).with_for_update(key_share=True))
    if locked is None:
        raise RoomMissingError
    snapshot = ChatRoomMemorySnapshot
    await db.execute(
        select(snapshot.id)
        .where(snapshot.chat_room_id == room_id)
        .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id)
        .with_for_update()
    )


def _span(row: ChatMemoryEpisode | ChatMemoryFact) -> tuple[MessageKey, MessageKey]:
    return (row.start_created_at, row.start_message_id), (row.end_created_at, row.end_message_id)


async def fact_forget_plan(db: AsyncSession, room_id: uuid.UUID, key: str) -> FactForgetPlan:
    """키 `key` 를 잊으면 무엇이 지워지나(모듈 설명). 그 방에 그 키 행이 없으면 `MemoryItemMissingError`."""
    fact, snapshot = ChatMemoryFact, ChatRoomMemorySnapshot
    rows: Sequence[ChatMemoryFact] = (
        await db.scalars(
            select(fact)
            .join(snapshot, snapshot.id == fact.snapshot_id)
            .where(fact.chat_room_id == room_id, fact.fact_key == key)
            .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id, fact.ordinal)
        )
    ).all()
    if not rows:
        raise MemoryItemMissingError
    [(_, winner)] = latest_by_key(rows)
    if not winner.known_by:
        return FactForgetPlan(episode_ids=[])
    spans = [_span(row) for row in rows]
    episodes = (
        await db.scalars(
            select(ChatMemoryEpisode)
            .where(ChatMemoryEpisode.chat_room_id == room_id)
            .order_by(ChatMemoryEpisode.end_created_at, ChatMemoryEpisode.end_message_id, ChatMemoryEpisode.id)
        )
    ).all()
    overlapping = [row.id for row in episodes if any(overlaps(_span(row), span) for span in spans)]
    return FactForgetPlan(episode_ids=overlapping)


async def forget_episode(db: AsyncSession, room_id: uuid.UUID, episode_id: uuid.UUID) -> None:
    """방의 장면 하나를 지운다(커밋은 호출부). 방이 없으면 `RoomMissingError`, 그 방의 장면이 아니면 `MemoryItemMissingError`."""
    await _lock_room_memory(db, room_id)
    removed = await db.scalar(
        delete(ChatMemoryEpisode)
        .where(ChatMemoryEpisode.id == episode_id, ChatMemoryEpisode.chat_room_id == room_id)
        .returning(ChatMemoryEpisode.id)
    )
    if removed is None:
        raise MemoryItemMissingError


async def forget_fact_key(db: AsyncSession, room_id: uuid.UUID, key: str) -> None:
    """방의 사실 키 하나(비밀이면 겹치는 장면까지)를 지우고 잊기 세대를 올린다(커밋은 호출부). 방이 없으면 `RoomMissingError`,
    그 키 행이 없으면 `MemoryItemMissingError`."""
    await _lock_room_memory(db, room_id)
    plan = await fact_forget_plan(db, room_id, key)
    await db.execute(
        delete(ChatMemoryFact).where(ChatMemoryFact.chat_room_id == room_id, ChatMemoryFact.fact_key == key)
    )
    if plan.episode_ids:
        await db.execute(delete(ChatMemoryEpisode).where(ChatMemoryEpisode.id.in_(plan.episode_ids)))
    await db.execute(
        update(ChatRoom)
        .where(ChatRoom.id == room_id)
        .values(memory_forget_generation=ChatRoom.memory_forget_generation + 1)
    )
