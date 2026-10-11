"""서버 회상(`api.chat.memory_recall`)의 순수 함수를 오프라인 회상의 검색 함수 모양으로 감싼 어댑터와, DB 에서 읽은 장면을
오프라인 회상 입력으로 내보내는 일. LLM 없음.

어댑터는 서버가 한 턴에 하는 일 중 DB 읽기만 빼고 같은 함수를 같은 순서로 부른다: 후보(저장된 명사를 그대로) → 질의 토큰 →
점수·순위 → 주입. 시제품(`prototype_recall.retrieve_e`)과 달리 제목·본문에서 명사를 다시 뽑지 않는다 — 서버는 저장할 때 뽑은
명사만 읽기 때문이다. 그래서 입력 장면의 `nouns` 는 DB 에 저장된 값이어야 한다(`export_episodes` 가 그렇게 내보낸다).

스냅샷 순서: 서버는 장면을 뽑은 스냅샷의 커서 키 순서로, 어댑터는 그 스냅샷이 검색 대상이 되는 첫 턴(`available_from_turn`
= 스냅샷 생성 시각까지 들어온 어시스턴트 메시지 수(오프닝 제외) + 1) 순서로 매긴다. 접기는 한 턴에 많아야 한 번이고 나중
접기의 커서가 앞 접기의 커서보다 뒤에 있으므로, 생성 순서와 커서 순서가 같고 서로 다른 턴의 접기는 첫 턴이 다르다.

이름 제외: 서버는 방 프로필 이름·캐릭터 이름을 질의에서 뺀다. 평가 방은 프로필이 없는 스토리 방이라 뺄 이름이 없다(`NAMES`)."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from api.chat import memory_recall as mr

from memory_eval.recall_offline import Episode, Ranked


# 평가 방(프로필 없는 스토리 방)에서 서버가 질의에서 빼는 이름.
NAMES: tuple[str, ...] = ()


def retrieve_server(
    episodes: Sequence[Episode], *, user_text: str, previous_assistant: str, current_turn: int
) -> list[Ranked]:
    """순위 목록에는 질의 낱말과 겹친 장면만 싣는다(시제품 어댑터와 같은 범위)."""
    snapshots = {t: i for i, t in enumerate(sorted({e.available_from_turn or 0 for e in episodes}))}
    rows = [
        mr.RecallCandidate(
            id=e.id,
            nouns=frozenset(e.nouns),
            importance=e.importance,
            end_turn=e.end_turn,
            snapshot=snapshots[e.available_from_turn or 0],
        )
        for e in episodes
    ]
    query = mr.query_tokens(
        user_text,
        previous_assistant,
        episode_nouns=frozenset(noun for row in rows for noun in row.nouns),
        names=NAMES,
    )
    scored = mr.score_episodes(rows, query, current_turn=current_turn)
    injected = {row.id for row in mr.select_injected(scored, recall_cue=mr.recall_cue(user_text))}
    return [Ranked(row.id, row.s, row.id in injected) for row in scored if row.overlap]


def available_from_turns(markers: Sequence[Any], assistant_keys: Sequence[Any]) -> dict[Any, int]:
    """기준점마다 그 기준점 이하인 어시스턴트 메시지 수(오프닝 제외) + 1. 기준점과 메시지는 같은 꼴(시각, 또는 정렬 키)로 준다."""
    return {marker: 1 + sum(1 for key in assistant_keys if key <= marker) for marker in markers}


def export_rows(pairs: Sequence[tuple[Any, datetime]], assistant_times: Sequence[datetime]) -> list[dict[str, Any]]:
    """(장면, 그 장면을 쓴 스냅샷의 생성 시각) 쌍을 오프라인 회상 입력 꼴로. 검색 대상이 되는 첫 턴 = 스냅샷 생성 시각까지 들어온
    어시스턴트 메시지 수(오프닝 제외) + 1 — 그 스냅샷이 접힌 턴의 다음 턴이다(커서가 덮은 끝이 아니다)."""
    first_turn = available_from_turns(sorted({created for _, created in pairs}), assistant_times)
    return [
        {
            "id": str(episode.id),
            "snapshot_id": str(episode.snapshot_id),
            "ordinal": episode.ordinal,
            "start_turn": episode.start_turn,
            "end_turn": episode.end_turn,
            "title": episode.title,
            "detail": episode.detail,
            "asserted_by": episode.asserted_by,
            "nouns": list(episode.nouns),
            "keywords": list(episode.keywords),
            "importance": episode.importance,
            "available_from_turn": first_turn[created],
        }
        for episode, created in pairs
    ]


async def export_episodes(db: Any, room_id: uuid.UUID) -> list[dict[str, Any]]:
    """방의 장면 전부를 오프라인 회상 입력 꼴(`recall_offline.load_episodes_json`)로. 명사는 저장된 값 그대로."""
    from sqlalchemy import select

    from api.chat.memory_window import opening_message
    from api.db.models import ChatMessage, ChatMessageRole
    from api.db.models.chat import ChatMemoryEpisode, ChatRoomMemorySnapshot

    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )
    opening = opening_message(messages)
    assistant = [m.created_at for m in messages if m.role == ChatMessageRole.ASSISTANT and m is not opening]
    rows = (
        await db.execute(
            select(ChatMemoryEpisode, ChatRoomMemorySnapshot.created_at)
            .join(ChatRoomMemorySnapshot, ChatRoomMemorySnapshot.id == ChatMemoryEpisode.snapshot_id)
            .where(ChatMemoryEpisode.chat_room_id == room_id)
            .order_by(ChatMemoryEpisode.end_created_at, ChatMemoryEpisode.end_message_id)
        )
    ).all()
    return export_rows([(episode, created) for episode, created in rows], assistant)
