"""대화를 되감으면 요약도 되감긴다.

- 메시지 편집·삭제·재생성이 요약 스냅샷이 덮는 구간(커서 이하)을 건드리면 그 지점 이상을 덮는 스냅샷을
  지우고 직전 스냅샷으로 돌아간다. 사용자가 고친 요약도 함께 지워지고, 남는 스냅샷은 고쳐 쓰지 않는다.
- 커서 뒤를 건드리면 스냅샷은 그대로다. 어느 쪽이든 방의 기억 버전은 올라간다(진행 중인 접기가 낡은
  입력으로 커밋하지 못하게).
- 초기화는 요약만 지우고 노트는 남긴다.
- 스냅샷에서 뽑은 장면 기억과 추출 기록은 스냅샷 DELETE 의 CASCADE 로 함께 사라진다. 되감기·초기화·방 삭제의 DELETE 문장은
  이 두 테이블을 모르는 옛 이미지와 같으므로, 아래 세 경로 테스트가 옛 이미지가 새 스키마 위에서 FK 위반 없이 지우는지도 본다.
- 롤백은 방 행을 먼저 잠근 뒤 스냅샷을 지운다 — 그래야 동시에 도는 접기가 지운 대화를 담은 스냅샷을
  남기지 못한다. 이 경합은 한 커넥션 위에서는 재현되지 않으므로(같은 트랜잭션끼리는 락을 다투지
  않는다) 아래 경합 테스트는 커밋되는 독립 커넥션을 쓴다.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.chat import memory_episodes, memory_facts, memory_fold
from api.chat.memory_episodes import extract_pending_episode
from api.chat.memory_facts import extract_pending_facts
from api.chat.memory_fold import fold_memory
from api.chat.memory_rewind import rewind_memory
from api.chat.prompt_builder import (
    MemoryEpisodeItem,
    MemoryEpisodeResult,
    MemoryFactItem,
    MemoryFactResult,
    MemorySummaryResult,
    PromptNames,
    load_active_prompt_set,
)
from api.chat.room_deletion import delete_chat_rooms
from api.db.models import (
    Asset,
    CharacterVersionDetail,
    ChatMemoryEmbedding,
    ChatMemoryEpisode,
    ChatMemoryExtraction,
    ChatMemoryFact,
    ChatMemoryFactExtraction,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    ChatTurn,
    CloverLedger,
    CloverLot,
    CloverSpendAllocation,
    CloverSpendRefund,
    CloverSpendUsage,
    Content,
    ContentVersion,
    User,
)
from api.db.session import get_db_session, get_session_factory
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.main import app
from factories import (
    Room,
    SnapshotRow,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_chat_turn,
    _make_memory_embedding,
    _make_memory_episode,
    _make_memory_extraction,
    _make_memory_fact,
    _make_memory_fact_extraction,
    _make_published_character,
    _make_user,
    _memory_version,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _plant_snapshot,
    _snapshots,
)


class RecordingLLMClient(LLMClient):
    """생성 프롬프트를 모으고 고정 응답을 준다. `fail`이면 생성이 실패한다. `during_generation`은
    생성 도중(스트림이 열린 뒤) 한 번 불린다."""

    def __init__(
        self, *, fail: bool = False, during_generation: Callable[[], Awaitable[None]] | None = None
    ) -> None:
        self.fail = fail
        self.during_generation = during_generation
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        if self.during_generation is not None:
            await self.during_generation()
        if self.fail:
            raise LLMClientError("boom")
        yield "새 응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        assert response_schema is MemorySummaryResult, response_schema
        return MemorySummaryResult(summary="[FOLDED]")


async def _edit(db_client: httpx.AsyncClient, room: Room, message: ChatMessage, fake: LLMClient) -> list[str]:
    _override_llm_client(fake)
    try:
        response = await db_client.patch(
            f"/chat-rooms/{room.room_id}/messages/{message.id}", json={"content": "고친 메시지"}
        )
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    return [event["type"] for event in _parse_sse_events(response.text)]


async def _regenerate(db_client: httpx.AsyncClient, room: Room, fake: LLMClient) -> list[str]:
    _override_llm_client(fake)
    try:
        response = await db_client.post(f"/chat-rooms/{room.room_id}/regenerate")
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    return [event["type"] for event in _parse_sse_events(response.text)]


async def _delete(db_client: httpx.AsyncClient, room: Room, message: ChatMessage) -> None:
    response = await db_client.delete(f"/chat-rooms/{room.room_id}/messages/{message.id}")
    assert response.status_code == 204, response.text


async def _rewind_via(action: str, db_client: httpx.AsyncClient, room: Room, message: ChatMessage) -> None:
    if action == "edit":
        await _edit(db_client, room, message, RecordingLLMClient())
    else:
        await _delete(db_client, room, message)


async def _rolled_back_at(db_session: AsyncSession, room: Room) -> datetime | None:
    value: datetime | None = await db_session.scalar(
        sa.select(ChatRoom.memory_rolled_back_at).where(ChatRoom.id == room.room_id)
    )
    return value


async def _assert_cursors_exist(db_session: AsyncSession, room: Room) -> None:
    """롤백 뒤 남은 스냅샷의 커서는 전부 지금 방에 있는 메시지다(지운 메시지를 가리키는 커서가 없다)."""
    message_ids = set(
        (await db_session.scalars(sa.select(ChatMessage.id).where(ChatMessage.chat_room_id == room.room_id))).all()
    )
    for row in await _snapshots(db_session, room):
        assert row.cursor_message_id in message_ids


async def _room_with_two_snapshots(db_client: httpx.AsyncClient, db_session: AsyncSession, turns: int) -> Room:
    room = await _open_room(db_client, db_session, turns=turns)
    await _plant_snapshot(db_session, room, turn=10, text="[S10]")
    await _plant_snapshot(db_session, room, turn=20, text="[S20]")
    return room


# --- 편집·삭제 ------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["edit", "delete"])
async def test_rewinding_inside_the_summarized_part_returns_to_the_previous_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)

    await _rewind_via(action, db_client, room, room.turns[15][0])

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]"]
    assert await _memory_version(db_session, room) == 1
    assert await _rolled_back_at(db_session, room) is not None
    await _assert_cursors_exist(db_session, room)


@pytest.mark.parametrize("action", ["edit", "delete"])
async def test_rewinding_after_the_cursor_keeps_the_snapshots_but_bumps_the_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)

    await _rewind_via(action, db_client, room, room.turns[22][0])

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]", "[S20]"]
    assert await _memory_version(db_session, room) == 1
    assert await _rolled_back_at(db_session, room) is None


async def test_deleting_the_cursor_message_itself_drops_its_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)

    await _delete(db_client, room, room.turns[20][1])

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]"]
    await _assert_cursors_exist(db_session, room)


async def test_deleting_the_opening_drops_every_snapshot(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """오프닝은 모든 커서보다 앞이다 — 오프닝이라고 예외를 두지 않는다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    opening = await db_session.scalar(
        sa.select(ChatMessage)
        .where(ChatMessage.chat_room_id == room.room_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .limit(1)
    )
    assert opening is not None and opening.role == ChatMessageRole.ASSISTANT

    await _delete(db_client, room, opening)

    assert await _snapshots(db_session, room) == []


async def test_the_restored_snapshot_keeps_the_users_edit_and_undo_buffer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """롤백은 남는 스냅샷을 고쳐 쓰지 않는다 — 사용자가 고친 요약과 되돌리기 버퍼가 그대로 돌아온다.
    지워지는 스냅샷은 사용자가 고친 것이어도 지워진다."""
    room = await _open_room(db_client, db_session, turns=24)
    tenth, twentieth = room.turns[10][1], room.turns[20][1]
    db_session.add_all(
        [
            ChatRoomMemorySnapshot(
                chat_room_id=room.room_id,
                cursor_created_at=tenth.created_at,
                cursor_message_id=tenth.id,
                summary_text="[S10 고침]",
                previous_text="[S10 자동]",
                source="user",
            ),
            ChatRoomMemorySnapshot(
                chat_room_id=room.room_id,
                cursor_created_at=twentieth.created_at,
                cursor_message_id=twentieth.id,
                summary_text="[S20 고침]",
                previous_text="[S20 자동]",
                source="user",
            ),
        ]
    )
    await db_session.commit()

    await _delete(db_client, room, room.turns[15][0])

    assert await _snapshots(db_session, room) == [
        SnapshotRow(tenth.created_at, tenth.id, "[S10 고침]", "[S10 자동]", "user")
    ]


# --- 롤백 뒤 윈도우 ---------------------------------------------------------------------------


async def test_edit_inside_the_summarized_part_builds_the_prompt_from_the_restored_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """롤백이 윈도우 계산보다 먼저다 — 그래야 편집 지점 앞 메시지가 복귀한 커서 기준으로 실린다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    fake = RecordingLLMClient()

    await _edit(db_client, room, room.turns[15][0], fake)

    prompt = fake.prompts[0]
    assert prompt.count("[S10]") == 1
    assert "[S20]" not in prompt
    for turn in range(11, 15):
        assert f"[U{turn:02d}]" in prompt and f"[A{turn:02d}]" in prompt
    for turn in range(1, 11):
        assert f"[U{turn:02d}]" not in prompt and f"[A{turn:02d}]" not in prompt
    assert "고친 메시지" in prompt


async def test_regenerating_the_cursor_message_drops_its_snapshot_and_sends_the_full_history(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """커서 뒤를 전부 지운 방에서는 마지막 응답이 곧 커서 메시지다. 재생성이 그 응답을 바꾸므로 그
    스냅샷은 지워지고, 요약이 덮던 대화는 원문으로 돌아온다."""
    room = await _open_room(db_client, db_session, turns=20)
    await _plant_snapshot(db_session, room, turn=20, text="[S20]")
    fake = RecordingLLMClient()

    await _regenerate(db_client, room, fake)

    assert await _snapshots(db_session, room) == []
    prompt = fake.prompts[0]
    assert "[S20]" not in prompt
    for turn in range(1, 20):
        assert f"[U{turn:02d}]" in prompt and f"[A{turn:02d}]" in prompt
    assert "[U20]" in prompt


async def test_ordinary_regenerate_keeps_the_snapshot_but_bumps_the_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    await _plant_snapshot(db_session, room, turn=10, text="[S10]")

    await _regenerate(db_client, room, RecordingLLMClient())

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]"]
    assert await _memory_version(db_session, room) == 1


# --- 초기화 -----------------------------------------------------------------------------------


async def test_reset_clears_the_summary_and_keeps_the_note(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    note = "[NOTE] 우산은 파란색\n  앞뒤 공백도 그대로 "
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    await db_session.execute(
        sa.update(ChatRoom)
        .where(ChatRoom.id == room.room_id)
        .values(memory_note=note, memory_rolled_back_at=datetime.now(UTC))
    )
    await db_session.commit()

    response = await db_client.post(f"/chat-rooms/{room.room_id}/reset")

    assert response.status_code == 200, response.text
    assert await _snapshots(db_session, room) == []
    assert await db_session.scalar(sa.select(ChatRoom.memory_note).where(ChatRoom.id == room.room_id)) == note
    assert await _rolled_back_at(db_session, room) is None
    assert await _memory_version(db_session, room) == 1


# --- 장면 기억 · 추출 기록 -----------------------------------------------------------------------


async def _seed_episodes_on_every_snapshot(db_session: AsyncSession, room: Room) -> dict[str, uuid.UUID]:
    """방의 스냅샷마다 장면 하나와 추출 기록 하나를 넣고 `{요약 글: 스냅샷 id}` 를 돌려준다."""
    snapshots = (
        await db_session.execute(
            sa.select(ChatRoomMemorySnapshot.id, ChatRoomMemorySnapshot.summary_text).where(
                ChatRoomMemorySnapshot.chat_room_id == room.room_id
            )
        )
    ).all()
    for snapshot in snapshots:
        db_session.add(_make_memory_episode(room.room_id, snapshot.id))
        db_session.add(_make_memory_extraction(room.room_id, snapshot.id))
    await db_session.commit()
    return {snapshot.summary_text: snapshot.id for snapshot in snapshots}


async def _episode_snapshot_ids(db_session: AsyncSession, room_id: uuid.UUID) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """방에 남은 (장면 기억의 스냅샷 id 들, 추출 기록의 스냅샷 id 들)."""
    episodes = await db_session.scalars(
        sa.select(ChatMemoryEpisode.snapshot_id).where(ChatMemoryEpisode.chat_room_id == room_id)
    )
    extractions = await db_session.scalars(
        sa.select(ChatMemoryExtraction.snapshot_id).where(ChatMemoryExtraction.chat_room_id == room_id)
    )
    return set(episodes.all()), set(extractions.all())


async def test_rewinding_memory_deletes_episodes_of_rewound_snapshots(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약 구간 안의 메시지를 지우면 그 지점 이상을 덮는 스냅샷이 지워지고, 그 스냅샷에서 뽑은 장면·추출 기록도 함께
    사라진다. 남은 스냅샷의 것은 그대로다 — 지운 대화의 장면만 잊는다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    snapshot_ids = await _seed_episodes_on_every_snapshot(db_session, room)

    await _delete(db_client, room, room.turns[15][0])

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]"]
    kept = {snapshot_ids["[S10]"]}
    assert await _episode_snapshot_ids(db_session, room.room_id) == (kept, kept)


@pytest.mark.parametrize("action", ["reset", "delete"])
async def test_room_reset_and_deletion_leave_no_episode_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    """초기화는 방의 스냅샷을 전부, 방 삭제(탈퇴도 같은 함수)는 방까지 지운다. 장면·추출 기록은 그 DELETE 의 CASCADE 로
    0행이 되고, 방 DELETE 가 남은 자식 때문에 FK 위반으로 실패하지 않는다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    await _seed_episodes_on_every_snapshot(db_session, room)

    if action == "reset":
        response = await db_client.post(f"/chat-rooms/{room.room_id}/reset")
        assert response.status_code == 200, response.text
    else:
        response = await db_client.delete(f"/chat-rooms/{room.room_id}")
        assert response.status_code == 204, response.text
        assert await db_session.scalar(sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id)) is None

    assert await _episode_snapshot_ids(db_session, room.room_id) == (set(), set())


# --- 사실 기억 · 추출 기록 -----------------------------------------------------------------------
#
# 장면 기억과 같은 CASCADE 로 지워진다. 경로의 DELETE 문장은 사실 계층을 모르던 이미지와 같으므로, 아래 두 테스트는 옛
# 이미지가 사실 행이 있는 스키마 위에서 FK 위반 없이 되감고 지우는지도 본다.


async def _seed_facts_on_every_snapshot(db_session: AsyncSession, room: Room) -> dict[str, uuid.UUID]:
    """방의 스냅샷마다 사실 하나와 사실 추출 기록 하나를 넣고 `{요약 글: 스냅샷 id}` 를 돌려준다."""
    snapshots = (
        await db_session.execute(
            sa.select(ChatRoomMemorySnapshot.id, ChatRoomMemorySnapshot.summary_text).where(
                ChatRoomMemorySnapshot.chat_room_id == room.room_id
            )
        )
    ).all()
    for snapshot in snapshots:
        db_session.add(_make_memory_fact(room.room_id, snapshot.id))
        db_session.add(_make_memory_fact_extraction(room.room_id, snapshot.id))
    await db_session.commit()
    return {snapshot.summary_text: snapshot.id for snapshot in snapshots}


async def _fact_snapshot_ids(db_session: AsyncSession, room_id: uuid.UUID) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """방에 남은 (사실 기억의 스냅샷 id 들, 사실 추출 기록의 스냅샷 id 들)."""
    facts = await db_session.scalars(sa.select(ChatMemoryFact.snapshot_id).where(ChatMemoryFact.chat_room_id == room_id))
    extractions = await db_session.scalars(
        sa.select(ChatMemoryFactExtraction.snapshot_id).where(ChatMemoryFactExtraction.chat_room_id == room_id)
    )
    return set(facts.all()), set(extractions.all())


async def test_rewinding_memory_deletes_facts_of_rewound_snapshots(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약 구간 안의 메시지를 지우면 그 지점 이상을 덮는 스냅샷과 함께 그 스냅샷에서 뽑은 사실·추출 기록도 사라진다.
    남은 스냅샷의 것은 그대로다 — 지운 대화의 사실만 잊는다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    snapshot_ids = await _seed_facts_on_every_snapshot(db_session, room)

    await _delete(db_client, room, room.turns[15][0])

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]"]
    kept = {snapshot_ids["[S10]"]}
    assert await _fact_snapshot_ids(db_session, room.room_id) == (kept, kept)


@pytest.mark.parametrize("action", ["reset", "delete"])
async def test_room_reset_and_deletion_leave_no_fact_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    """초기화는 방의 스냅샷을 전부, 방 삭제(탈퇴도 같은 함수)는 방까지 지운다. 사실·추출 기록은 그 DELETE 의 CASCADE 로
    0행이 되고, 방 DELETE 가 남은 자식 때문에 FK 위반으로 실패하지 않는다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    await _seed_facts_on_every_snapshot(db_session, room)

    if action == "reset":
        response = await db_client.post(f"/chat-rooms/{room.room_id}/reset")
        assert response.status_code == 200, response.text
    else:
        response = await db_client.delete(f"/chat-rooms/{room.room_id}")
        assert response.status_code == 204, response.text
        assert await db_session.scalar(sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id)) is None

    assert await _fact_snapshot_ids(db_session, room.room_id) == (set(), set())


# --- 임베딩 ---------------------------------------------------------------------------------------
#
# 장면·사실 행 FK 의 CASCADE 로 지워진다(스냅샷 → 장면·사실 → 임베딩). 경로의 DELETE 문장은 임베딩 표를 모르던 이미지와
# 같으므로, 아래 두 테스트는 옛 이미지가 임베딩이 있는 스키마 위에서 FK 위반 없이 되감고 지우는지도 본다.


async def _seed_embeddings_on_every_snapshot(db_session: AsyncSession, room: Room) -> dict[str, uuid.UUID]:
    """방의 스냅샷마다 장면·사실 하나씩과 그 둘의 임베딩을 넣고 `{요약 글: 스냅샷 id}` 를 돌려준다."""
    snapshots = (
        await db_session.execute(
            sa.select(ChatRoomMemorySnapshot.id, ChatRoomMemorySnapshot.summary_text).where(
                ChatRoomMemorySnapshot.chat_room_id == room.room_id
            )
        )
    ).all()
    for snapshot in snapshots:
        episode = _make_memory_episode(room.room_id, snapshot.id)
        fact = _make_memory_fact(room.room_id, snapshot.id)
        db_session.add_all([episode, fact])
        await db_session.flush()
        db_session.add(_make_memory_embedding(room.room_id, episode_id=episode.id))
        db_session.add(_make_memory_embedding(room.room_id, fact_id=fact.id))
    await db_session.commit()
    return {snapshot.summary_text: snapshot.id for snapshot in snapshots}


async def _embedding_snapshot_ids(db_session: AsyncSession, room_id: uuid.UUID) -> list[uuid.UUID]:
    """방에 남은 임베딩마다 그 대상 행이 뽑힌 스냅샷 id(정렬)."""
    rows = await db_session.scalars(
        sa.select(sa.func.coalesce(ChatMemoryEpisode.snapshot_id, ChatMemoryFact.snapshot_id))
        .select_from(ChatMemoryEmbedding)
        .outerjoin(ChatMemoryEpisode, ChatMemoryEpisode.id == ChatMemoryEmbedding.episode_id)
        .outerjoin(ChatMemoryFact, ChatMemoryFact.id == ChatMemoryEmbedding.fact_id)
        .where(ChatMemoryEmbedding.chat_room_id == room_id)
    )
    return sorted(rows.all())


async def test_rewinding_memory_deletes_embeddings_of_rewound_snapshots(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약 구간 안의 메시지를 지우면 그 지점 이상을 덮는 스냅샷의 장면·사실과 함께 그 임베딩도 사라진다. 남은 스냅샷의
    장면·사실 임베딩은 그대로다 — 지운 대화의 벡터만 잊는다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    snapshot_ids = await _seed_embeddings_on_every_snapshot(db_session, room)

    await _delete(db_client, room, room.turns[15][0])

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]"]
    assert await _embedding_snapshot_ids(db_session, room.room_id) == [snapshot_ids["[S10]"]] * 2


@pytest.mark.parametrize("action", ["reset", "delete", "withdraw"])
async def test_room_reset_deletion_and_withdrawal_leave_no_embedding_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    """초기화는 방의 스냅샷을 전부, 방 삭제와 탈퇴는 방까지 지운다. 임베딩은 그 DELETE 의 CASCADE 로 0행이 되고, 방
    DELETE 가 방 FK 로 남은 임베딩 때문에 FK 위반으로 실패하지 않는다."""
    room = await _room_with_two_snapshots(db_client, db_session, turns=24)
    await _seed_embeddings_on_every_snapshot(db_session, room)

    if action == "reset":
        response = await db_client.post(f"/chat-rooms/{room.room_id}/reset")
        assert response.status_code == 200, response.text
    else:
        response = await db_client.delete(f"/chat-rooms/{room.room_id}" if action == "delete" else "/me")
        assert response.status_code == 204, response.text
        assert await db_session.scalar(sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id)) is None

    count = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(ChatMemoryEmbedding)
        .where(ChatMemoryEmbedding.chat_room_id == room.room_id)
    )
    assert count == 0


# --- 커밋되는 독립 커넥션 ---------------------------------------------------------------------
#
# 아래 테스트는 `db_session`(롤백되는 한 커넥션)을 쓰지 않는다. 락 경합과 "요청이 실제로 커밋했는가"는
# 한 트랜잭션 안에서는 드러나지 않는다. 여기서 쓴 행은 커밋되므로 픽스처가 표지로 골라 지운다.

_MARKER_DOMAIN = "memory-rewind.test"


@pytest_asyncio.fixture
async def committed_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """테스트 DB에 붙는 별도 엔진. 락을 기다리다 영영 멈추지 않게 모든 커넥션에 `lock_timeout`을 건다
    (공용 엔진의 풀 커넥션에 세션 설정을 남기지 않으려고 풀 없는 엔진을 따로 만든다)."""
    committed = create_async_engine(
        db_engine.url.render_as_string(hide_password=False),
        poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "5s"}},
    )
    yield committed
    factory = async_sessionmaker(committed, expire_on_commit=False)
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(sa.select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            room_ids = (await cleanup.scalars(sa.select(ChatRoom.id).where(ChatRoom.user_id.in_(user_ids)))).all()
            await delete_chat_rooms(cleanup, room_ids)
            # 사용처가 작품·원장을, 환급 행이 배분·원장을 FK 로 잡으므로 작품·배분·원장보다 먼저 지운다.
            spend_ledger_ids = sa.select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
            await cleanup.execute(
                sa.delete(CloverSpendRefund).where(
                    CloverSpendRefund.allocation_id.in_(
                        sa.select(CloverSpendAllocation.id).where(
                            CloverSpendAllocation.spend_ledger_id.in_(spend_ledger_ids)
                        )
                    )
                )
            )
            await cleanup.execute(
                sa.delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(spend_ledger_ids))
            )
            content_ids = (
                await cleanup.scalars(sa.select(Content.id).where(Content.creator_user_id.in_(user_ids)))
            ).all()
            version_ids = (
                await cleanup.scalars(sa.select(ContentVersion.id).where(ContentVersion.content_id.in_(content_ids)))
            ).all()
            await cleanup.execute(
                sa.delete(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id.in_(version_ids))
            )
            await cleanup.execute(
                sa.update(Content).where(Content.id.in_(content_ids)).values(current_published_version_id=None)
            )
            await cleanup.execute(sa.delete(ContentVersion).where(ContentVersion.id.in_(version_ids)))
            await cleanup.execute(sa.delete(Content).where(Content.id.in_(content_ids)))
            await cleanup.execute(sa.delete(Asset).where(Asset.owner_user_id.in_(user_ids)))
            # 배분이 원장·로트를 둘 다 FK 로 잡으므로 원장보다 먼저 지운다.
            await cleanup.execute(
                sa.delete(CloverSpendAllocation).where(
                    CloverSpendAllocation.spend_ledger_id.in_(
                        sa.select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
                    )
                )
            )
            await cleanup.execute(sa.delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(sa.delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
            await cleanup.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()
    await committed.dispose()


async def _seed_committed_room(engine: AsyncEngine, *, turns: int) -> Room:
    """발행 캐릭터 방 하나에 오프닝 + `turns`턴을 `created_at`을 명시해 넣고 커밋한다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base = datetime.now(UTC) - timedelta(days=1)
    async with factory() as session:
        user = _make_user(email=f"owner-{uuid.uuid4()}@{_MARKER_DOMAIN}")
        session.add(user)
        await session.flush()
        genre = await _get_genre(session)
        content = await _make_published_character(session, creator_user_id=user.id, genre_id=genre.id)
        assert content.current_published_version_id is not None
        room = ChatRoom(
            user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id
        )
        session.add(room)
        await session.flush()
        session.add(
            ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content="오프닝", created_at=base)
        )
        seeded: dict[int, tuple[ChatMessage, ChatMessage]] = {}
        for turn in range(1, turns + 1):
            pair = (
                ChatMessage(
                    id=uuid.uuid4(),
                    chat_room_id=room.id,
                    role=ChatMessageRole.USER,
                    content=f"[U{turn:02d}]",
                    created_at=base + timedelta(seconds=2 * turn - 1),
                ),
                ChatMessage(
                    id=uuid.uuid4(),
                    chat_room_id=room.id,
                    role=ChatMessageRole.ASSISTANT,
                    content=f"[A{turn:02d}]",
                    created_at=base + timedelta(seconds=2 * turn),
                ),
            )
            session.add_all(pair)
            seeded[turn] = pair
        room.turn_count = turns
        await session.commit()
    return Room(room_id=room.id, user_id=user.id, base=base, turns=seeded)


async def _committed_snapshots(engine: AsyncEngine, room: Room) -> list[SnapshotRow]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return await _snapshots(session, room)


async def _committed_version(engine: AsyncEngine, room: Room) -> int | None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return await _memory_version(session, room)


async def _wait_until_a_lock_is_awaited(engine: AsyncEngine) -> None:
    """어떤 트랜잭션이 락을 기다리기 시작할 때까지 기다린다(시간이 아니라 상태로 순서를 강제). 행 락
    대기는 상대 트랜잭션 id를 기다리는 모양이라 `pg_locks`의 데이터베이스 열이 비어 있다 — 그래서
    `pg_stat_activity`의 대기 종류로 본다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with asyncio.timeout(5):
        while True:
            async with factory() as probe:
                waiting = await probe.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                    )
                )
            if waiting:
                return
            await asyncio.sleep(0.01)


# --- 재생성 롤백은 스트림 전에 커밋된다 --------------------------------------------------------


async def test_regenerate_commits_its_rewind_before_streaming(
    committed_engine: AsyncEngine, db_client: httpx.AsyncClient
) -> None:
    """롤백은 생성보다 먼저 커밋된다 — 생성이 실패해도 롤백은 남고, 생성을 기다리는 동안 방 행 락을
    쥐고 있지 않는다(락을 쥐면 그동안 같은 방의 접기·편집이 전부 멈춘다)."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    room = await _seed_committed_room(committed_engine, turns=20)
    last = room.turns[20][1]
    async with factory() as session:
        session.add(
            ChatRoomMemorySnapshot(
                chat_room_id=room.room_id,
                cursor_created_at=last.created_at,
                cursor_message_id=last.id,
                summary_text="[S20]",
                source="auto",
            )
        )
        await session.commit()

    lock_probe: list[str] = []

    async def _is_the_room_row_free() -> None:
        async with factory() as probe:
            try:
                await probe.execute(
                    sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id).with_for_update(nowait=True)
                )
                lock_probe.append("free")
            except sa.exc.DBAPIError:
                lock_probe.append("locked")
            await probe.rollback()

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    # `db_client`가 건 오버라이드(롤백되는 한 커넥션)를 이 요청 동안만 독립 커넥션으로 바꾼다.
    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        await _login_as(db_client, room.user_id)
        events = await _regenerate(
            db_client, room, RecordingLLMClient(fail=True, during_generation=_is_the_room_row_free)
        )
    finally:
        app.dependency_overrides.update(saved)

    assert events == ["error"]
    assert lock_probe == ["free"]
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_version(committed_engine, room) == 1


# --- 접기와 롤백·방 삭제의 경합 ----------------------------------------------------------------


class _Gate:
    """접기의 쓰기 트랜잭션을 커밋 직전에 세운다 — 방 행 락을 쥐고 스냅샷을 넣은(아직 커밋 전) 상태."""

    def __init__(self) -> None:
        self.holding = asyncio.Event()
        self.release = asyncio.Event()


def _fold_factory_stopping_before_commit(engine: AsyncEngine, gate: _Gate) -> async_sessionmaker[AsyncSession]:
    class _StoppingSession(AsyncSession):
        async def commit(self) -> None:
            await self.flush()
            gate.holding.set()
            await gate.release.wait()
            await super().commit()

    return async_sessionmaker(engine, class_=_StoppingSession, expire_on_commit=False)


class _FixedSummaryClient(LLMClient):
    """요약만 부른다. `before_answer`는 요약을 돌려주기 전에(접기가 입력을 다 읽은 뒤) 불린다."""

    def __init__(self, before_answer: Callable[[], Awaitable[None]] | None = None) -> None:
        self.before_answer = before_answer

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("접기는 생성을 부르지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        assert response_schema is MemorySummaryResult, response_schema
        if self.before_answer is not None:
            await self.before_answer()
        return MemorySummaryResult(summary="[FOLDED]")


async def _run_fold(engine: AsyncEngine, room: Room, factory: async_sessionmaker[AsyncSession], llm: LLMClient) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        prompt_set, sections = await load_active_prompt_set(session, lane="character")
    await fold_memory(
        factory,
        llm,
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=False,
        names=PromptNames(persona_name=None, char_name=None),
    )


async def _delete_message_committed(engine: AsyncEngine, room: Room, message: ChatMessage) -> None:
    """`delete_message` 라우트 본문과 같은 순서: 롤백 → 메시지 삭제 → 커밋."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await rewind_memory(session, room.room_id, (message.created_at, message.id))
        await session.execute(sa.delete(ChatMessage).where(ChatMessage.id == message.id))
        await session.commit()


async def _delete_room_committed(engine: AsyncEngine, room: Room) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await delete_chat_rooms(session, [room.room_id])
        await session.commit()


async def _while_a_fold_holds_the_room(
    engine: AsyncEngine, room: Room, write: Callable[[], Coroutine[Any, Any, None]]
) -> None:
    """접기가 방 행을 잠그고 스냅샷을 넣은 채 커밋 직전에 멈춘 동안 `write`를 시작하고, `write`가 락을
    기다리기 시작한 것을 확인한 뒤에 접기를 커밋시킨다. 어떤 단계가 실패해도 접기를 풀어 주고 두
    작업을 끝까지 기다린다(락을 쥔 채 남아 뒤 테스트를 막지 않게)."""
    gate = _Gate()
    fold = asyncio.create_task(
        _run_fold(engine, room, _fold_factory_stopping_before_commit(engine, gate), _FixedSummaryClient())
    )
    other: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(gate.holding.wait(), 5)
        other = asyncio.create_task(write())
        await _wait_until_a_lock_is_awaited(engine)
    finally:
        gate.release.set()
        await asyncio.wait_for(fold, 10)
        if other is not None:
            await asyncio.wait_for(other, 10)


async def test_a_message_deleted_while_a_fold_holds_the_room_leaves_no_snapshot_over_it(
    committed_engine: AsyncEngine,
) -> None:
    """접기가 방 행을 잠그고 스냅샷을 넣은 채 커밋 직전에 있을 때 사용자가 그 스냅샷이 덮는 메시지를
    지운다. 삭제는 락을 기다렸다가, 접기가 커밋한 뒤 그 스냅샷까지 보고 지운다."""
    room = await _seed_committed_room(committed_engine, turns=30)

    await _while_a_fold_holds_the_room(
        committed_engine, room, lambda: _delete_message_committed(committed_engine, room, room.turns[5][0])
    )

    assert await _committed_snapshots(committed_engine, room) == []


async def test_a_fold_that_waits_on_a_rewind_discards_its_summary(committed_engine: AsyncEngine) -> None:
    """반대 순서 — 롤백이 방 행을 잡은 채(미커밋) 있는 동안 접기가 커밋하려 한다. 접기는 락을
    기다렸다가 버전이 바뀐 것을 보고 결과를 버린다."""
    room = await _seed_committed_room(committed_engine, turns=30)
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    rewind_session = factory()
    committer: list[asyncio.Task[None]] = []

    async def _commit_when_the_fold_waits() -> None:
        try:
            await _wait_until_a_lock_is_awaited(committed_engine)
            await rewind_session.commit()
        finally:
            await rewind_session.close()

    async def _rewind_and_hold() -> None:
        target = room.turns[5][0]
        await rewind_memory(rewind_session, room.room_id, (target.created_at, target.id))
        await rewind_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == target.id))
        committer.append(asyncio.create_task(_commit_when_the_fold_waits()))

    await _run_fold(committed_engine, room, factory, _FixedSummaryClient(before_answer=_rewind_and_hold))
    await committer[0]

    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_version(committed_engine, room) == 1


async def test_a_room_deleted_while_a_fold_holds_it_is_deleted_cleanly(committed_engine: AsyncEngine) -> None:
    """방 삭제가 스냅샷을 먼저 지우고 나서 락을 잡으면, 그사이 커밋된 접기 스냅샷이 남아 방 DELETE가
    FK 위반으로 실패한다. 락을 먼저 잡으면 접기 커밋 뒤의 스냅샷까지 보고 지운다."""
    room = await _seed_committed_room(committed_engine, turns=30)

    await _while_a_fold_holds_the_room(committed_engine, room, lambda: _delete_room_committed(committed_engine, room))

    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        assert await session.scalar(sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id)) is None
    assert await _committed_snapshots(committed_engine, room) == []


async def test_a_room_deleted_while_a_turn_write_holds_it_takes_the_turn_record_too(
    committed_engine: AsyncEngine,
) -> None:
    """턴 쓰기 구간은 방 행을 `FOR NO KEY UPDATE` 로 잡고 응답과 턴 기록을 한 커밋에 넣는다. 그 구간이 커밋 직전일 때 방을
    지운다. 삭제가 기록을 방 행 잠금보다 먼저 지우면 그 뒤 커밋된 기록을 못 보고 방 DELETE 가 FK 위반으로 실패한다. 잠금을
    먼저 잡으면 턴 커밋을 기다렸다가 그 기록까지 지운다."""
    room = await _seed_committed_room(committed_engine, turns=1)
    turn_write = async_sessionmaker(committed_engine, expire_on_commit=False)()
    deletion: asyncio.Task[None] | None = None
    try:
        await turn_write.scalar(
            sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id).with_for_update(key_share=True)
        )
        turn_write.add(_make_chat_turn(room.room_id, assistant_message_id=room.turns[1][1].id))
        await turn_write.flush()
        deletion = asyncio.create_task(_delete_room_committed(committed_engine, room))
        await _wait_until_a_lock_is_awaited(committed_engine)
        await turn_write.commit()
    finally:
        await turn_write.close()
        if deletion is not None:
            await asyncio.wait_for(deletion, 10)

    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        assert await session.scalar(sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id)) is None
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(ChatTurn).where(ChatTurn.chat_room_id == room.room_id)
            )
            == 0
        )


async def test_a_message_deleted_after_the_fold_read_its_input_voids_the_fold(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """접기가 입력(버전·커서 뒤 메시지)을 다 읽은 직후 사용자가 그 입력 안의 메시지를 지운다. 접기는
    버전을 메시지보다 먼저 읽었으므로 삭제의 버전 증가를 보고 결과를 버린다."""
    room = await _seed_committed_room(committed_engine, turns=30)
    load_unsummarized = memory_fold._load_unsummarized

    async def _then_the_user_deletes_a_message(*args: Any, **kwargs: Any) -> list[ChatMessage]:
        messages = await load_unsummarized(*args, **kwargs)
        await _delete_message_committed(committed_engine, room, room.turns[5][0])
        return messages

    monkeypatch.setattr(memory_fold, "_load_unsummarized", _then_the_user_deletes_a_message)

    await _run_fold(
        committed_engine, room, async_sessionmaker(committed_engine, expire_on_commit=False), _FixedSummaryClient()
    )

    assert await _committed_snapshots(committed_engine, room) == []

# --- 장면 기억 추출과 되감기·다른 추출의 경합 ---------------------------------------------------
#
# 추출의 마지막 트랜잭션은 스냅샷을 `FOR KEY SHARE` 로 먼저 잡고 나서 추출 기록을 갱신하고 장면을 넣는다. 되감기는 방 행을
# 잠근 뒤 스냅샷을 지우고, 장면·추출 기록은 그 DELETE 의 CASCADE 가 지운다. 둘 다 스냅샷부터 잡으므로 한 방향으로만 줄을
# 선다 — 아래 테스트가 그 순서를 실제 두 세션으로 본다.


class _EpisodeClient(LLMClient):
    """장면 추출만 부른다. `before_answer` 는 결과를 돌려주기 전에(추출이 창을 다 읽고 세션을 닫은 뒤) 불린다."""

    def __init__(self, before_answer: Callable[[], Awaitable[None]] | None = None) -> None:
        self.before_answer = before_answer
        self.calls = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("추출은 생성을 부르지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        assert response_schema is MemoryEpisodeResult, response_schema
        self.calls += 1
        if self.before_answer is not None:
            await self.before_answer()
        return MemoryEpisodeResult(
            episodes=[
                MemoryEpisodeItem(
                    title="정류장",
                    detail="정류장에서 우산을 빌렸다.",
                    nouns=["정류장", "우산"],
                    keywords=[],
                    asserted_by="user",
                    evidence=[],
                    importance=3,
                    start_line=1,
                    end_line=20,
                )
            ]
        )


async def _commit_snapshot(engine: AsyncEngine, room: Room, *, turn: int) -> None:
    assistant = room.turns[turn][1]
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(
            ChatRoomMemorySnapshot(
                chat_room_id=room.room_id,
                cursor_created_at=assistant.created_at,
                cursor_message_id=assistant.id,
                summary_text=f"[S{turn}]",
                source="auto",
            )
        )
        await session.commit()


async def _run_extraction(engine: AsyncEngine, room: Room, llm: LLMClient) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        prompt_set, sections = await load_active_prompt_set(session, lane="character")
    await extract_pending_episode(
        async_sessionmaker(engine, expire_on_commit=False),
        llm,
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=False,
        names=PromptNames(persona_name=None, char_name=None),
    )


async def _committed_episode_state(engine: AsyncEngine, room: Room) -> tuple[int, list[tuple[str, int]]]:
    """(장면 수, 추출 기록의 (상태, 시도) 목록)."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        episodes = await session.scalar(
            sa.select(sa.func.count())
            .select_from(ChatMemoryEpisode)
            .where(ChatMemoryEpisode.chat_room_id == room.room_id)
        )
        extractions = (
            await session.execute(
                sa.select(ChatMemoryExtraction.status, ChatMemoryExtraction.attempts).where(
                    ChatMemoryExtraction.chat_room_id == room.room_id
                )
            )
        ).all()
    return int(episodes or 0), [(row.status, row.attempts) for row in extractions]


def _capture_episode_failures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(
        memory_episodes, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    return captured


async def test_message_deleted_during_extraction_drops_its_episodes(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """추출이 창을 읽고 모델을 기다리는 사이 사용자가 창 안 메시지를 지운다. 되감기가 스냅샷을 지우면 추출 기록도 함께
    사라지고, 추출은 마지막 트랜잭션에서 스냅샷이 없음을 보고 아무것도 쓰지 않는다 — 실패로 세지도 않는다."""
    captured = _capture_episode_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)

    async def _user_deletes_a_message_in_the_window() -> None:
        await _delete_message_committed(committed_engine, room, room.turns[5][0])

    llm = _EpisodeClient(before_answer=_user_deletes_a_message_in_the_window)
    await _run_extraction(committed_engine, room, llm)

    assert llm.calls == 1
    assert captured == []
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_episode_state(committed_engine, room) == (0, [])


@pytest.mark.parametrize(
    "pause_after",
    [
        # 스냅샷 잠금만 쥔 채 — 되감기가 추출 기록을 스냅샷보다 먼저 지우면 여기서 교착이 난다.
        pytest.param("_lock_snapshot", id="holding-the-snapshot-lock"),
        # 추출 기록까지 갱신한 채 — 스냅샷을 먼저 잠그지 않으면 되감기의 CASCADE 와 장면 INSERT 의 FK 확인이 교착한다.
        pytest.param("_finish_claim", id="holding-the-claim-update"),
    ],
)
async def test_rewind_during_extraction_finishes_without_deadlock(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, pause_after: str
) -> None:
    """추출이 마지막 트랜잭션 중간에 멈춘 사이 되감기(창 안 메시지 삭제)가 시작된다. 되감기는 추출 커밋을 기다렸다가
    스냅샷을 지우고, CASCADE 가 방금 넣은 장면과 추출 기록까지 지운다. 어느 쪽도 교착으로 끊기지 않는다."""
    captured = _capture_episode_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    gate = _Gate()
    original = getattr(memory_episodes, pause_after)

    async def _pause_there(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        gate.holding.set()
        await gate.release.wait()
        return result

    monkeypatch.setattr(memory_episodes, pause_after, _pause_there)
    extraction = asyncio.create_task(_run_extraction(committed_engine, room, _EpisodeClient()))
    rewind: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(gate.holding.wait(), 5)
        rewind = asyncio.create_task(_delete_message_committed(committed_engine, room, room.turns[5][0]))
        await _wait_until_a_lock_is_awaited(committed_engine)
    finally:
        gate.release.set()
        await asyncio.wait_for(extraction, 15)
        if rewind is not None:
            await asyncio.wait_for(rewind, 15)

    assert captured == []
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_episode_state(committed_engine, room) == (0, [])


async def test_concurrent_extractions_of_one_snapshot_call_llm_once(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 턴의 백그라운드가 다른 워커에서 같은 스냅샷을 골랐다. 선점은 하나만 이기고, 모델은 한 번만 불린다."""
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    both_picked = asyncio.Barrier(2)
    pick = memory_episodes._next_candidate

    async def _both_pick_before_either_claims(*args: Any, **kwargs: Any) -> Any:
        candidate = await pick(*args, **kwargs)
        await both_picked.wait()
        return candidate

    monkeypatch.setattr(memory_episodes, "_next_candidate", _both_pick_before_either_claims)
    llm = _EpisodeClient()

    await asyncio.wait_for(
        asyncio.gather(_run_extraction(committed_engine, room, llm), _run_extraction(committed_engine, room, llm)), 15
    )

    assert llm.calls == 1
    assert await _committed_episode_state(committed_engine, room) == (1, [("done", 1)])


# --- 사실 기억 추출과 되감기·다른 추출의 경합 ---------------------------------------------------
#
# 사실 추출도 장면 추출과 같은 순서를 따른다 — 마지막 트랜잭션이 스냅샷을 `FOR KEY SHARE` 로 먼저 잡고 나서 추출 기록을 갱신하고
# 사실을 넣는다. 사실·추출 기록은 되감기의 스냅샷 DELETE 의 CASCADE 로만 지워진다.


class _FactClient(LLMClient):
    """사실 추출만 부른다. `before_answer` 는 결과를 돌려주기 전에(추출이 창을 다 읽고 세션을 닫은 뒤) 불린다."""

    def __init__(self, before_answer: Callable[[], Awaitable[None]] | None = None) -> None:
        self.before_answer = before_answer
        self.calls = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("추출은 생성을 부르지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        assert response_schema is MemoryFactResult, response_schema
        self.calls += 1
        if self.before_answer is not None:
            await self.before_answer()
        return MemoryFactResult(
            facts=[
                MemoryFactItem(
                    kind="relation",
                    subject="민수",
                    object="지아",
                    attribute="",
                    value="소꿉친구",
                    truth_status="confirmed",
                    asserted_by="user",
                    speaker="",
                    known_by=[],
                    importance=3,
                    start_line=1,
                    end_line=20,
                )
            ]
        )


async def _run_fact_extraction(engine: AsyncEngine, room: Room, llm: LLMClient) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        prompt_set, sections = await load_active_prompt_set(session, lane="character")
    await extract_pending_facts(
        async_sessionmaker(engine, expire_on_commit=False),
        llm,
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=False,
        names=PromptNames(persona_name=None, char_name=None),
    )


async def _committed_fact_state(engine: AsyncEngine, room: Room) -> tuple[int, list[tuple[str, int]]]:
    """(사실 수, 사실 추출 기록의 (상태, 시도) 목록)."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        facts = await session.scalar(
            sa.select(sa.func.count()).select_from(ChatMemoryFact).where(ChatMemoryFact.chat_room_id == room.room_id)
        )
        extractions = (
            await session.execute(
                sa.select(ChatMemoryFactExtraction.status, ChatMemoryFactExtraction.attempts).where(
                    ChatMemoryFactExtraction.chat_room_id == room.room_id
                )
            )
        ).all()
    return int(facts or 0), [(row.status, row.attempts) for row in extractions]


def _capture_fact_failures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(
        memory_facts, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    return captured


async def _reached(event: asyncio.Event, seconds: float) -> bool:
    """`event` 가 `seconds` 안에 서는가 — 멈춤 지점에 닿지 못한 것을 시간 초과 예외가 아니라 단언 실패로 드러낸다."""
    try:
        await asyncio.wait_for(event.wait(), seconds)
    except TimeoutError:
        return False
    return True


async def test_message_deleted_during_fact_extraction_drops_its_facts(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """추출이 창을 읽고 모델을 기다리는 사이 사용자가 창 안 메시지를 지운다. 되감기가 스냅샷을 지우면 사실 추출 기록도 함께
    사라지고, 추출은 마지막 트랜잭션에서 스냅샷이 없음을 보고 아무것도 쓰지 않는다 — 실패로 세지도 않는다."""
    captured = _capture_fact_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)

    async def _user_deletes_a_message_in_the_window() -> None:
        await _delete_message_committed(committed_engine, room, room.turns[5][0])

    llm = _FactClient(before_answer=_user_deletes_a_message_in_the_window)
    await _run_fact_extraction(committed_engine, room, llm)

    assert llm.calls == 1
    assert captured == []
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_fact_state(committed_engine, room) == (0, [])


async def test_snapshot_rewound_between_pick_and_fact_claim_is_skipped_without_counting_a_failure(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """추출이 후보를 고른 뒤 선점하기 전에, 다른 세션의 되감기가 그 스냅샷을 지우고 커밋한다. 선점 INSERT 가 외래 키(23503)에
    걸리지만 경합이라 실패로 세지 않고 모델도 부르지 않는다."""
    captured = _capture_fact_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    pick = memory_facts._next_candidate
    rewound: list[bool] = []

    async def _then_another_session_rewinds(*args: Any, **kwargs: Any) -> Any:
        candidate = await pick(*args, **kwargs)
        await _delete_message_committed(committed_engine, room, room.turns[5][0])
        rewound.append(True)
        return candidate

    monkeypatch.setattr(memory_facts, "_next_candidate", _then_another_session_rewinds)
    llm = _FactClient()

    await _run_fact_extraction(committed_engine, room, llm)

    assert rewound == [True]
    assert llm.calls == 0
    assert captured == []
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_fact_state(committed_engine, room) == (0, [])


@pytest.mark.parametrize(
    "pause_after",
    [
        # 스냅샷 잠금만 쥔 채 — 되감기가 추출 기록을 스냅샷보다 먼저 지우면 여기서 교착이 난다.
        pytest.param("_lock_snapshot", id="holding-the-snapshot-lock"),
        # 추출 기록까지 갱신한 채 — 스냅샷을 먼저 잠그지 않으면 되감기의 CASCADE 와 사실 INSERT 의 FK 확인이 교착한다.
        pytest.param("_finish_claim", id="holding-the-claim-update"),
    ],
)
async def test_rewind_during_fact_extraction_finishes_without_deadlock(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, pause_after: str
) -> None:
    """추출이 마지막 트랜잭션 중간에 멈춘 사이 되감기(창 안 메시지 삭제)가 시작된다. 되감기는 추출 커밋을 기다렸다가
    스냅샷을 지우고, CASCADE 가 방금 넣은 사실과 추출 기록까지 지운다. 어느 쪽도 교착으로 끊기지 않는다."""
    captured = _capture_fact_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    gate = _Gate()
    original = getattr(memory_facts, pause_after)

    async def _pause_there(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        gate.holding.set()
        await gate.release.wait()
        return result

    monkeypatch.setattr(memory_facts, pause_after, _pause_there)
    extraction = asyncio.create_task(_run_fact_extraction(committed_engine, room, _FactClient()))
    rewind: asyncio.Task[None] | None = None
    try:
        paused = await _reached(gate.holding, 5)
        if paused:
            rewind = asyncio.create_task(_delete_message_committed(committed_engine, room, room.turns[5][0]))
            await _wait_until_a_lock_is_awaited(committed_engine)
    finally:
        gate.release.set()
        await asyncio.wait_for(extraction, 15)
        if rewind is not None:
            await asyncio.wait_for(rewind, 15)

    assert paused
    assert captured == []
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_fact_state(committed_engine, room) == (0, [])


async def test_concurrent_fact_extractions_of_one_snapshot_call_llm_once(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 턴의 백그라운드가 다른 워커에서 같은 스냅샷을 골랐다. 선점은 하나만 이기고, 모델은 한 번만 불린다."""
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    both_picked = asyncio.Barrier(2)
    pick = memory_facts._next_candidate

    async def _both_pick_before_either_claims(*args: Any, **kwargs: Any) -> Any:
        candidate = await pick(*args, **kwargs)
        await both_picked.wait()
        return candidate

    monkeypatch.setattr(memory_facts, "_next_candidate", _both_pick_before_either_claims)
    llm = _FactClient()

    await asyncio.wait_for(
        asyncio.gather(
            _run_fact_extraction(committed_engine, room, llm), _run_fact_extraction(committed_engine, room, llm)
        ),
        15,
    )

    assert llm.calls == 1
    assert await _committed_fact_state(committed_engine, room) == (1, [("done", 1)])
