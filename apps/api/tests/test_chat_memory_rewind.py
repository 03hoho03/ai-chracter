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

from api.chat import memory_embeddings, memory_episodes, memory_facts, memory_fold, memory_forget, memory_impressions
from api.chat.memory_embeddings import fill_pending_embeddings
from api.chat.memory_episodes import extract_pending_episode
from api.chat.memory_facts import extract_pending_facts
from api.chat.memory_fold import fold_memory
from api.chat.memory_impressions import generate_pending_impression
from api.chat.memory_rewind import rewind_memory
from api.chat.prompt_builder import (
    MemoryEpisodeItem,
    MemoryEpisodeResult,
    MemoryFactItem,
    MemoryFactResult,
    MemoryImpressionResult,
    MemorySummaryResult,
    PromptNames,
    load_active_prompt_set,
)
from api.chat.room_deletion import delete_chat_rooms
from api.core.config import settings
from api.db.models import (
    Asset,
    CharacterVersionDetail,
    ChatMemoryEmbedding,
    ChatMemoryEpisode,
    ChatMemoryExtraction,
    ChatMemoryFact,
    ChatMemoryFactExtraction,
    ChatMemoryImpression,
    ChatMemoryImpressionAttempt,
    ChatMessage,
    ChatMessageRole,
    ChatPreviousResponse,
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
    DiscardedResponse,
    User,
)
from api.db.session import get_db_session, get_session_factory
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.llm.voyage import VoyageEmbeddingClient
from api.main import app
from factories import (
    Room,
    SnapshotRow,
    VoyageStub,
    _clear_llm_override,
    _get_genre,
    _impression_sections,
    _login_as,
    _make_chat_turn,
    _make_memory_embedding,
    _make_memory_episode,
    _make_memory_extraction,
    _make_memory_fact,
    _make_memory_fact_extraction,
    _make_paying_user,
    _make_published_character,
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
    assert response.status_code == 200, response.text


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


async def _room_with_two_snapshots(
    db_client: httpx.AsyncClient, db_session: AsyncSession, turns: int, *, paid_turns: int = 0
) -> Room:
    room = await _open_room(db_client, db_session, turns=turns, paid_turns=paid_turns)
    await _plant_snapshot(db_session, room, turn=10, text="[S10]")
    await _plant_snapshot(db_session, room, turn=20, text="[S20]")
    return room


# --- 편집·삭제 ------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["edit", "delete"])
async def test_rewinding_inside_the_summarized_part_returns_to_the_previous_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    room = await _room_with_two_snapshots(db_client, db_session, turns=24, paid_turns=1 if action == "edit" else 0)

    await _rewind_via(action, db_client, room, room.turns[15][0])

    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["[S10]"]
    assert await _memory_version(db_session, room) == 1
    assert await _rolled_back_at(db_session, room) is not None
    await _assert_cursors_exist(db_session, room)


@pytest.mark.parametrize("action", ["edit", "delete"])
async def test_rewinding_after_the_cursor_keeps_the_snapshots_but_bumps_the_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    room = await _room_with_two_snapshots(db_client, db_session, turns=24, paid_turns=1 if action == "edit" else 0)

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
    room = await _room_with_two_snapshots(db_client, db_session, turns=24, paid_turns=1)
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
    room = await _open_room(db_client, db_session, turns=20, paid_turns=1)
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
    room = await _open_room(db_client, db_session, turns=20, paid_turns=1)
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
            # 직전 응답 되돌리기가 남기는 버린 응답 기록은 방이 지워져도 사용자를 FK 로 잡는다.
            await cleanup.execute(sa.delete(DiscardedResponse).where(DiscardedResponse.user_id.in_(user_ids)))
            await cleanup.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()
    await committed.dispose()


async def _seed_committed_room(engine: AsyncEngine, *, turns: int, paid_turns: int = 0) -> Room:
    """발행 캐릭터 방 하나에 오프닝 + `turns`턴을 `created_at`을 명시해 넣고 커밋한다. `paid_turns` 는 방 주인에게 줄 기본
    모델 턴 수다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base = datetime.now(UTC) - timedelta(days=1)
    async with factory() as session:
        user = await _make_paying_user(session, turns=paid_turns, email=f"owner-{uuid.uuid4()}@{_MARKER_DOMAIN}")
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
    room = await _seed_committed_room(committed_engine, turns=20, paid_turns=1)
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
        writing_model="gemini",
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


async def test_a_last_reply_deleted_while_a_turn_count_write_holds_the_room_sees_the_new_count(
    committed_engine: AsyncEngine, db_client: httpx.AsyncClient
) -> None:
    """메시지 삭제는 마지막 응답의 기록 번호가 방 턴 수와 같을 때만 턴 수를 하나 줄인다. 다른 트랜잭션이 방 행을 잡고 턴 수를
    올린 채 커밋 직전일 때 마지막 응답을 지운다. 삭제가 방 행을 잠그며 다시 읽으면 그 커밋을 기다렸다가 올라간 턴 수를 보고,
    번호가 어긋나니 턴 수를 그대로 둔다. 잠그지 않고 읽으면 옛 턴 수로 판단해 줄인 값을 써서 다른 쪽이 올린 것을 덮어쓴다."""
    room = await _seed_committed_room(committed_engine, turns=1)
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_make_chat_turn(room.room_id, assistant_message_id=room.turns[1][1].id, turn_number=1))
        await session.commit()

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    writer = factory()
    deletion: asyncio.Task[httpx.Response] | None = None
    try:
        await _login_as(db_client, room.user_id)
        await writer.execute(
            sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(turn_count=ChatRoom.turn_count + 1)
        )
        deletion = asyncio.create_task(db_client.delete(f"/chat-rooms/{room.room_id}/messages/{room.turns[1][1].id}"))
        await _wait_until_a_lock_is_awaited(committed_engine)
        await writer.commit()
    finally:
        await writer.close()
        response = await asyncio.wait_for(deletion, 10) if deletion is not None else None
        app.dependency_overrides.update(saved)

    assert response is not None
    assert response.status_code == 200, response.text
    async with factory() as session:
        assert await session.scalar(sa.select(ChatRoom.turn_count).where(ChatRoom.id == room.room_id)) == 2


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
                    known_by=[],
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


# --- 임베딩 채우기와 되감기의 경합 ---------------------------------------------------------------
#
# 채우기도 추출과 같은 순서를 따른다 — Voyage 는 세션 없이 부르고, 넣는 트랜잭션은 스냅샷을 `FOR KEY SHARE` 로 먼저 잡은 뒤 행마다
# INSERT 한다. 임베딩은 되감기의 스냅샷 DELETE → 장면·사실 CASCADE → 임베딩 CASCADE 로만 지워진다.


def _voyage(stub: VoyageStub) -> VoyageEmbeddingClient:
    return VoyageEmbeddingClient(
        api_key="test-key", model="voyage-test", dims=stub.dims, transport=stub.transport(), retry_delays=()
    )


async def _run_fill(engine: AsyncEngine, room: Room, stub: VoyageStub) -> None:
    await fill_pending_embeddings(
        async_sessionmaker(engine, expire_on_commit=False), _voyage(stub), room_id=room.room_id
    )


async def _commit_facts_against_source_order(engine: AsyncEngine, room: Room, *, turn: int) -> None:
    """턴 `turn` 스냅샷에 사실 둘을 순번 순서로 넣는다. 순번 0 의 근거는 턴 9, 순번 1 의 근거는 턴 2 라 원문 순서는 그 반대다 —
    채우기는 원문 순서로 넣고, 스냅샷 DELETE 의 CASCADE 는 순번(유니크 인덱스·넣은 순서) 순서로 지운다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        snapshot_id = await session.scalar(
            sa.select(ChatRoomMemorySnapshot.id).where(
                ChatRoomMemorySnapshot.chat_room_id == room.room_id,
                ChatRoomMemorySnapshot.cursor_message_id == room.turns[turn][1].id,
            )
        )
        assert snapshot_id is not None
        facts = []
        for ordinal, source_turn in enumerate((9, 2)):
            message = room.turns[source_turn][1]
            facts.append(
                _make_memory_fact(
                    room.room_id,
                    snapshot_id,
                    ordinal=ordinal,
                    value=f"근거 턴 {source_turn}",
                    start_created_at=message.created_at,
                    start_message_id=message.id,
                    end_created_at=message.created_at,
                    end_message_id=message.id,
                    start_turn=source_turn,
                    end_turn=source_turn,
                )
            )
        for fact in facts:
            session.add(fact)
            await session.flush()
        await session.commit()


async def _committed_embedding_count(engine: AsyncEngine, room: Room) -> int:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(ChatMemoryEmbedding)
            .where(ChatMemoryEmbedding.chat_room_id == room.room_id)
        )
    return int(count or 0)


def _capture_embedding_failures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(
        memory_embeddings, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    return captured


async def test_a_rewind_while_voyage_answers_does_not_wait_for_the_fill(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Voyage 가 답하지 않는 동안 사용자가 창 안 메시지를 지운다. 채우기는 그동안 아무 잠금도 쥐지 않아 되감기가 곧바로 끝난다
    (기다리면 시간 상한에 걸린다). Voyage 가 답한 뒤 채우기는 스냅샷이 없음을 보고 아무것도 넣지 않고, 실패로 세지 않는다."""
    captured = _capture_embedding_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    await _commit_facts_against_source_order(committed_engine, room, turn=10)
    gate = _Gate()

    async def _voyage_hangs() -> None:
        gate.holding.set()
        await gate.release.wait()

    stub = VoyageStub(before_answer=_voyage_hangs)
    fill = asyncio.create_task(_run_fill(committed_engine, room, stub))
    rewound = False
    try:
        if await _reached(gate.holding, 5):
            await asyncio.wait_for(_delete_message_committed(committed_engine, room, room.turns[5][0]), 3)
            rewound = True
    finally:
        gate.release.set()
        await asyncio.wait_for(fill, 15)

    assert rewound
    assert len(stub.inputs) == 1
    assert captured == []
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_embedding_count(committed_engine, room) == 0


async def test_rewind_during_the_embedding_inserts_finishes_without_deadlock(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채우기가 첫 행을 넣고(그 사실 행에 FK 확인 잠금을 쥔 채) 멈춘 사이 되감기가 시작된다. 채우기가 스냅샷을 먼저 잡았으므로
    되감기는 스냅샷 DELETE 에서 채우기 커밋을 기다리고, 채우기는 둘째 행까지 넣고 커밋한다. 그 뒤 CASCADE 가 사실과 임베딩을
    지운다. 스냅샷을 먼저 잡지 않으면 되감기의 CASCADE 가 둘째 행(순번 0)을 먼저 지우고 첫 행에서 기다리는 사이 채우기가 둘째 행의
    FK 확인으로 되감기를 기다려 교착이 난다 — 넣는 순서(원문 순)와 지우는 순서(순번 순)를 일부러 엇갈리게 두었다."""
    captured = _capture_embedding_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    await _commit_facts_against_source_order(committed_engine, room, turn=10)
    gate = _Gate()
    original = memory_embeddings._insert_row
    inserted: list[bool] = []

    async def _pause_after_the_first_row(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        if not inserted:
            inserted.append(result)
            gate.holding.set()
            await gate.release.wait()
        return result

    monkeypatch.setattr(memory_embeddings, "_insert_row", _pause_after_the_first_row)
    fill = asyncio.create_task(_run_fill(committed_engine, room, VoyageStub()))
    rewind: asyncio.Task[None] | None = None
    try:
        paused = await _reached(gate.holding, 5)
        if paused:
            rewind = asyncio.create_task(_delete_message_committed(committed_engine, room, room.turns[5][0]))
            await _wait_until_a_lock_is_awaited(committed_engine)
    finally:
        gate.release.set()
        await asyncio.wait_for(fill, 15)
        if rewind is not None:
            await asyncio.wait_for(rewind, 15)

    assert paused
    assert inserted == [True]
    assert captured == []
    assert await _committed_snapshots(committed_engine, room) == []
    assert await _committed_embedding_count(committed_engine, room) == 0

# --- 노트 쓰기와 방 삭제의 경합 ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "body"), [("PUT", {"note": "새 메모"}), ("DELETE", None)], ids=["save note", "clear note"]
)
async def test_a_note_write_that_overlaps_a_room_deletion_is_not_found(
    committed_engine: AsyncEngine, db_client: httpx.AsyncClient, method: str, body: dict[str, str] | None
) -> None:
    """노트 저장·비우기가 주인 확인을 마친 뒤 다른 세션이 그 방을 지우고 커밋한다. 쓰기가 방 행을 잠그지 않으면
    UPDATE 가 0행을 고친 채 커밋하고, 커밋 뒤 응답을 만들려고 방 행을 다시 읽다가 빈 결과로 500 이 난다. 쓰기 전에
    방 행을 잠그면 삭제 커밋을 기다렸다가 방이 없음을 보고 404 로 끝난다."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    room = await _seed_committed_room(committed_engine, turns=1)

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    deletion = factory()
    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    write: asyncio.Task[httpx.Response] | None = None
    try:
        await _login_as(db_client, room.user_id)
        await delete_chat_rooms(deletion, [room.room_id])
        write = asyncio.create_task(db_client.request(method, f"/chat-rooms/{room.room_id}/memory/note", json=body))
        await _wait_until_a_lock_is_awaited(committed_engine)
        await deletion.commit()
        resp = await asyncio.wait_for(write, 10)
    finally:
        await deletion.close()
        if write is not None and not write.done():
            write.cancel()
        app.dependency_overrides.update(saved)

    assert resp.status_code == 404


# --- 요약 고치기·되돌리기와 직전 응답 되돌리기의 방 삭제 경합 ------------------------------------------


async def _request_with_the_room_deleted_right_after_commit(
    engine: AsyncEngine,
    db_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    room: Room,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> httpx.Response:
    """요청이 커밋한 바로 다음, 다른 세션이 그 방을 지우고 커밋한다. 요청이 방 행을 잠근 동안 삭제는 그 잠금을
    기다리다가 요청의 커밋과 함께 풀려 곧장 커밋하므로, 커밋 뒤에 응답을 만들려고 방을 다시 읽는 요청은 이 틈에
    걸릴 수 있다. 시간 대신 커밋을 감싸 그 순서를 매번 같게 만든다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            commit = session.commit

            async def _commit_then_delete_the_room() -> None:
                await commit()
                await _delete_room_committed(engine, room)

            monkeypatch.setattr(session, "commit", _commit_then_delete_the_room)
            yield session

    await _login_as(db_client, room.user_id)
    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        return await db_client.request(method, path, json=body)
    finally:
        app.dependency_overrides.update(saved)


@pytest.mark.parametrize(
    ("path", "body"),
    [("summary", {"summary": "고친 요약", "version": 0}), ("summary/revert", {"version": 1})],
    ids=["edit summary", "revert summary"],
)
async def test_a_summary_write_answers_with_what_it_saved_even_if_the_room_is_deleted_right_after(
    committed_engine: AsyncEngine,
    db_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    body: dict[str, object],
) -> None:
    """요약 고치기·되돌리기는 성공해 커밋했다. 그 직후 방이 지워져도 응답은 저장한 요약이어야 한다 — 커밋 뒤에 방 행을
    다시 읽으면 빈 결과로 500 이 나고, 화면은 저장이 실패한 줄 안다."""
    room = await _seed_committed_room(committed_engine, turns=1)
    await _commit_snapshot(committed_engine, room, turn=1)
    if path == "summary/revert":
        async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
            await session.execute(
                sa.update(ChatRoomMemorySnapshot)
                .where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
                .values(summary_text="고친 요약", source="user", previous_text="[S1]", previous_source="auto")
            )
            await session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_version=1))
            await session.commit()

    resp = await _request_with_the_room_deleted_right_after_commit(
        committed_engine,
        db_client,
        monkeypatch,
        room,
        "POST" if path.endswith("revert") else "PUT",
        f"/chat-rooms/{room.room_id}/memory/{path}",
        body,
    )

    assert resp.status_code == 200
    expected = "고친 요약" if path == "summary" else "[S1]"
    assert resp.json()["summary"]["text"] == expected
    assert await _committed_version(committed_engine, room) is None


@pytest.mark.parametrize(
    ("method", "body", "expected"),
    [("PUT", {"note": "새 메모"}, "새 메모"), ("DELETE", None, "")],
    ids=["save note", "clear note"],
)
async def test_a_note_write_answers_with_what_it_saved_even_if_the_room_is_deleted_right_after(
    committed_engine: AsyncEngine,
    db_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    body: dict[str, object] | None,
    expected: str,
) -> None:
    """노트 저장·비우기는 성공해 커밋했다. 그 직후 방이 지워져도 응답은 저장한 노트여야 한다 — 커밋 뒤에 방 행을
    다시 읽으면 빈 결과로 500 이 나고, 화면은 저장이 실패한 줄 안다."""
    room = await _seed_committed_room(committed_engine, turns=1)
    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        await session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_note="옛 메모"))
        await session.commit()

    resp = await _request_with_the_room_deleted_right_after_commit(
        committed_engine, db_client, monkeypatch, room, method, f"/chat-rooms/{room.room_id}/memory/note", body
    )

    assert resp.status_code == 200
    assert resp.json()["note"] == expected
    assert await _committed_version(committed_engine, room) is None


@pytest.mark.parametrize(
    ("path", "body"),
    [("summary", {"summary": "고친 요약", "version": 0}), ("summary/revert", {"version": 0})],
    ids=["edit summary", "revert summary"],
)
async def test_a_summary_write_that_overlaps_a_room_deletion_is_not_found(
    committed_engine: AsyncEngine, db_client: httpx.AsyncClient, path: str, body: dict[str, object]
) -> None:
    """요약 고치기·되돌리기가 주인 확인을 마친 뒤 다른 세션이 그 방을 지우고 커밋한다. 방 행 잠금은 삭제 커밋을 기다렸다가
    빈 결과를 받는다 — 그 빈 값을 버전 불일치로 읽으면 409 가 나가 화면은 요약을 다시 받으러 간다. 방이 없으니 404 다."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    room = await _seed_committed_room(committed_engine, turns=1)
    await _commit_snapshot(committed_engine, room, turn=1)

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    deletion = factory()
    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    write: asyncio.Task[httpx.Response] | None = None
    try:
        await _login_as(db_client, room.user_id)
        await delete_chat_rooms(deletion, [room.room_id])
        method = "POST" if path.endswith("revert") else "PUT"
        write = asyncio.create_task(db_client.request(method, f"/chat-rooms/{room.room_id}/memory/{path}", json=body))
        await _wait_until_a_lock_is_awaited(committed_engine)
        await deletion.commit()
        resp = await asyncio.wait_for(write, 10)
    finally:
        await deletion.close()
        if write is not None and not write.done():
            write.cancel()
        app.dependency_overrides.update(saved)

    assert resp.status_code == 404


async def test_restoring_the_previous_reply_answers_with_the_room_even_if_the_room_is_deleted_right_after(
    committed_engine: AsyncEngine, db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """재생성이 밀어낸 직전 응답으로 되돌리기는 성공해 커밋했다. 그 직후 방이 지워져도 응답은 되돌린 방 상태여야 한다 —
    커밋 뒤에 방 응답을 만들면 같은 작품의 방 목록에서 이 방을 못 찾아 500 이 난다."""
    room = await _seed_committed_room(committed_engine, turns=1)
    current = room.turns[1][1]
    restored_id = uuid.uuid4()
    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        session.add(
            ChatPreviousResponse(
                chat_room_id=room.room_id,
                replaced_by_message_id=current.id,
                message_id=restored_id,
                message_created_at=current.created_at - timedelta(milliseconds=500),
                content="밀려난 응답",
            )
        )
        await session.commit()

    resp = await _request_with_the_room_deleted_right_after_commit(
        committed_engine,
        db_client,
        monkeypatch,
        room,
        "POST",
        f"/chat-rooms/{room.room_id}/messages/{current.id}/restore-previous",
        None,
    )

    assert resp.status_code == 200
    last = resp.json()["messages"][-1]
    assert (last["id"], last["content"]) == (str(restored_id), "밀려난 응답")
    assert await _committed_version(committed_engine, room) is None

# --- 잊게 하기와 추출·채우기·되감기의 경합 ---------------------------------------------------------
#
# 잊게 하기는 방 행(`FOR NO KEY UPDATE`) → 그 방 스냅샷 전부(`FOR UPDATE`) → 행 DELETE 순으로 잡는다. 되감기·방 삭제와는 방 행에서
# 줄을 서고, 방 행을 잡지 않는 추출·채우기와는 스냅샷에서 줄을 선다(그들의 `FOR KEY SHARE` 와 충돌하는 행 잠금은 `FOR UPDATE`
# 뿐이다). 장면이나 사실을 잊으면 방의 잊기 세대가 오르고, 그 전에 입력을 읽은 추출·인상 생성은 넣기 직전에 세대가 바뀐 것을 보고
# 결과를 버린다.

_FORGOTTEN_KEY = "relation|민수|지아"


async def _forget_committed(
    engine: AsyncEngine, room: Room, *, episode_id: uuid.UUID | None = None, key: str | None = None
) -> str:
    """잊게 하기 라우트 본문과 같은 순서로 지우고 커밋한다. 대상이 그사이 사라졌으면 `"missing"`."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        try:
            if episode_id is not None:
                await memory_forget.forget_episode(session, room.room_id, episode_id)
            else:
                assert key is not None
                await memory_forget.forget_fact_key(session, room.room_id, key)
        except memory_forget.MemoryItemMissingError:
            return "missing"
        await session.commit()
    return "forgotten"


async def _snapshot_id_at(engine: AsyncEngine, room: Room, *, turn: int) -> uuid.UUID:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        snapshot_id = await session.scalar(
            sa.select(ChatRoomMemorySnapshot.id).where(
                ChatRoomMemorySnapshot.chat_room_id == room.room_id,
                ChatRoomMemorySnapshot.cursor_message_id == room.turns[turn][1].id,
            )
        )
    assert snapshot_id is not None
    return snapshot_id


async def _room_with_an_extracted_first_part(engine: AsyncEngine) -> tuple[Room, uuid.UUID]:
    """20턴 방. 턴 10 스냅샷은 장면 하나·사실 하나(잊을 키)를 이미 뽑았고(두 추출 기록 끝남), 턴 20 스냅샷은 아직 안 뽑았다.
    (방, 그 장면 id)."""
    room = await _seed_committed_room(engine, turns=20)
    await _commit_snapshot(engine, room, turn=10)
    first = await _snapshot_id_at(engine, room, turn=10)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        episode = _make_memory_episode(room.room_id, first, title="옛 장면", detail="옛 장면 이야기.")
        session.add_all(
            [
                episode,
                _make_memory_extraction(room.room_id, first),
                _make_memory_fact(room.room_id, first, fact_key=_FORGOTTEN_KEY, value="이웃"),
                _make_memory_fact_extraction(room.room_id, first),
            ]
        )
        await session.commit()
    await _commit_snapshot(engine, room, turn=20)
    return room, episode.id


async def _count_rows(engine: AsyncEngine, *where: Any, model: Any) -> int:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return int(await session.scalar(sa.select(sa.func.count()).select_from(model).where(*where)) or 0)


def _pause_after(monkeypatch: pytest.MonkeyPatch, module: Any, name: str, gate: _Gate) -> None:
    original = getattr(module, name)

    async def _pause_there(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        gate.holding.set()
        await gate.release.wait()
        return result

    monkeypatch.setattr(module, name, _pause_there)


async def _forget_while_paused(
    engine: AsyncEngine, gate: _Gate, background: asyncio.Task[None], forget: Callable[[], Coroutine[Any, Any, str]]
) -> tuple[bool, str | None]:
    """백그라운드 작업이 멈춤 지점에 닿으면 잊기를 시작하고, 잊기가 잠금을 기다리기 시작한 것을 본 뒤 작업을 풀어 준다. 어떤
    단계가 실패해도 작업을 풀어 두 쪽을 끝까지 기다린다. (멈춤 지점에 닿았나, 잊기 결과)."""
    other: asyncio.Task[str] | None = None
    try:
        paused = await _reached(gate.holding, 5)
        if paused:
            other = asyncio.create_task(forget())
            await _wait_until_a_lock_is_awaited(engine)
    finally:
        gate.release.set()
        await asyncio.wait_for(background, 15)
        outcome = await asyncio.wait_for(other, 15) if other is not None else None
    return paused, outcome


async def test_a_key_forgotten_while_a_fact_extraction_holds_its_snapshot_takes_the_rows_it_wrote(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """턴 20 사실 추출이 마지막 트랜잭션에서 자기 스냅샷을 잡고 추출 기록까지 갱신한 채 멈췄다(넣을 행에 잊을 키가 있다). 그때
    사용자가 그 키를 잊는다. 잊기는 스냅샷 `FOR UPDATE` 에서 추출 커밋을 기다렸다가 방금 들어간 행까지 지운다 — 어느 쪽도 교착으로
    끊기지 않고 키 행이 하나도 남지 않는다. 스냅샷 잠금이 없으면 잊기가 기다리지 않고 먼저 끝나 추출이 키를 다시 넣는다."""
    captured = _capture_fact_failures(monkeypatch)
    room, _ = await _room_with_an_extracted_first_part(committed_engine)
    gate = _Gate()
    _pause_after(monkeypatch, memory_facts, "_finish_claim", gate)
    extraction = asyncio.create_task(_run_fact_extraction(committed_engine, room, _FactClient()))

    paused, outcome = await _forget_while_paused(
        committed_engine, gate, extraction, lambda: _forget_committed(committed_engine, room, key=_FORGOTTEN_KEY)
    )

    assert (paused, outcome) == (True, "forgotten")
    assert captured == []
    assert await _count_rows(committed_engine, ChatMemoryFact.chat_room_id == room.room_id, model=ChatMemoryFact) == 0
    assert sorted((await _committed_fact_state(committed_engine, room))[1]) == [("done", 1), ("done", 1)]


async def test_a_fact_extraction_that_read_its_input_before_a_forget_discards_its_result(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """턴 20 사실 추출이 입력(앞 사실 목록 — 잊을 키가 있다)을 읽고 모델을 기다리는 사이 사용자가 그 키를 잊고 커밋한다. 추출은
    넣기 직전에 방의 잊기 세대가 바뀐 것을 보고 결과를 버리고 그 스냅샷을 다시 쥘 수 있게 실패로 적는다(시도 하나를 쓴다). Bugsink
    로 올리지 않는다 — 장애가 아니다. 세대를 다시 확인하지 않으면 잊은 키가 추출 결과로 되살아난다."""
    captured = _capture_fact_failures(monkeypatch)
    room, _ = await _room_with_an_extracted_first_part(committed_engine)
    outcomes: list[str] = []

    async def _user_forgets_the_key() -> None:
        outcomes.append(await _forget_committed(committed_engine, room, key=_FORGOTTEN_KEY))

    llm = _FactClient(before_answer=_user_forgets_the_key)
    await _run_fact_extraction(committed_engine, room, llm)

    assert (llm.calls, outcomes, captured) == (1, ["forgotten"], [])
    assert await _count_rows(committed_engine, ChatMemoryFact.chat_room_id == room.room_id, model=ChatMemoryFact) == 0
    assert sorted((await _committed_fact_state(committed_engine, room))[1]) == [("done", 1), ("failed", 1)]


async def test_a_scene_forgotten_while_a_scene_extraction_holds_another_snapshot_finishes_without_deadlock(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """턴 20 장면 추출이 마지막 트랜잭션에서 자기 스냅샷을 잡고 추출 기록까지 갱신한 채 멈췄을 때 사용자가 턴 10 의 장면을 잊는다.
    잊기는 추출 커밋을 기다렸다가 끝난다. 잊은 장면만 사라지고 추출이 넣은 장면은 남는다."""
    captured = _capture_episode_failures(monkeypatch)
    room, forgotten = await _room_with_an_extracted_first_part(committed_engine)
    gate = _Gate()
    _pause_after(monkeypatch, memory_episodes, "_finish_claim", gate)
    extraction = asyncio.create_task(_run_extraction(committed_engine, room, _EpisodeClient()))

    paused, outcome = await _forget_while_paused(
        committed_engine, gate, extraction, lambda: _forget_committed(committed_engine, room, episode_id=forgotten)
    )

    assert (paused, outcome, captured) == (True, "forgotten", [])
    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        titles = (
            await session.scalars(
                sa.select(ChatMemoryEpisode.title).where(ChatMemoryEpisode.chat_room_id == room.room_id)
            )
        ).all()
    assert titles == ["정류장"]


async def test_a_scene_forgotten_while_the_fill_writes_its_embedding_takes_the_embedding_too(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """임베딩 채우기가 잊을 장면의 임베딩을 넣은 채(그 장면 행을 FK 로 잡은 채) 커밋 전에 멈췄다. 사용자가 그 장면을 잊는다. 잊기는
    채우기 커밋을 기다렸다가 장면을 지우고, CASCADE 가 방금 넣은 임베딩까지 지운다."""
    room, forgotten = await _room_with_an_extracted_first_part(committed_engine)
    gate = _Gate()
    _pause_after(monkeypatch, memory_embeddings, "_insert_row", gate)
    fill = asyncio.create_task(_run_fill(committed_engine, room, VoyageStub()))

    paused, outcome = await _forget_while_paused(
        committed_engine, gate, fill, lambda: _forget_committed(committed_engine, room, episode_id=forgotten)
    )

    assert (paused, outcome) == (True, "forgotten")
    assert await _count_rows(committed_engine, ChatMemoryEpisode.id == forgotten, model=ChatMemoryEpisode) == 0
    assert (
        await _count_rows(committed_engine, ChatMemoryEmbedding.episode_id == forgotten, model=ChatMemoryEmbedding) == 0
    )


async def test_a_forget_waits_for_a_rewind_that_holds_the_room_row(committed_engine: AsyncEngine) -> None:
    """되감기가 첫 문장(방 행 UPDATE)만 하고 아직 스냅샷을 지우지 않은 채 열려 있다. 잊기는 방 행에서 기다리고, 되감기가 턴 10
    스냅샷을 지우고 커밋한 뒤에야 돌아 그 장면이 이미 없다고 본다. 방 행 잠금이 없으면 잊기가 되감기와 다른 순서로 스냅샷을 잡는다
    — 이 테스트에서는 기다리지 않고 먼저 끝나 빨개진다."""
    room, forgotten = await _room_with_an_extracted_first_part(committed_engine)
    deleted = room.turns[5][0]
    rewind = async_sessionmaker(committed_engine, expire_on_commit=False)()
    forget: asyncio.Task[str] | None = None
    try:
        await rewind.execute(
            sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_version=ChatRoom.memory_version + 1)
        )
        forget = asyncio.create_task(_forget_committed(committed_engine, room, episode_id=forgotten))
        await _wait_until_a_lock_is_awaited(committed_engine)
        await rewind_memory(rewind, room.room_id, (deleted.created_at, deleted.id))
        await rewind.execute(sa.delete(ChatMessage).where(ChatMessage.id == deleted.id))
        await rewind.commit()
        outcome = await asyncio.wait_for(forget, 10)
    finally:
        await rewind.close()
        if forget is not None and not forget.done():
            forget.cancel()

    assert outcome == "missing"
    assert (
        await _count_rows(committed_engine, ChatMemoryEpisode.chat_room_id == room.room_id, model=ChatMemoryEpisode)
        == 0
    )


async def _scene_titles(engine: AsyncEngine, room: Room) -> list[str]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return list(
            (
                await session.scalars(
                    sa.select(ChatMemoryEpisode.title).where(ChatMemoryEpisode.chat_room_id == room.room_id)
                )
            ).all()
        )


async def _fact_keys(engine: AsyncEngine, room: Room) -> list[str]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return list(
            (
                await session.scalars(
                    sa.select(ChatMemoryFact.fact_key).where(ChatMemoryFact.chat_room_id == room.room_id)
                )
            ).all()
        )


async def test_a_forgotten_scene_and_fact_come_back_when_a_rewind_refolds_their_part(
    committed_engine: AsyncEngine,
) -> None:
    """잊게 하기 안내 문구("앞 대화를 고치거나 재생성하면 다시 생길 수 있어요")의 근거. 턴 10 스냅샷이 장면·사실을 뽑았고 사용자가
    둘 다 잊었다. 그 구간 안 메시지를 지우면 되감기가 스냅샷을 지우고, 같은 구간이 다시 접히면(새 스냅샷) 두 추출이 같은 원문에서
    같은 장면·사실을 다시 뽑는다. 되감기 없이 다시 돌리면 이미 뽑은 스냅샷이라 아무것도 생기지 않는다."""
    room = await _seed_committed_room(committed_engine, turns=10)
    await _commit_snapshot(committed_engine, room, turn=10)
    await _run_extraction(committed_engine, room, _EpisodeClient())
    await _run_fact_extraction(committed_engine, room, _FactClient())
    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        [scene_id] = (
            await session.scalars(sa.select(ChatMemoryEpisode.id).where(ChatMemoryEpisode.chat_room_id == room.room_id))
        ).all()
    assert await _forget_committed(committed_engine, room, episode_id=scene_id) == "forgotten"
    assert await _forget_committed(committed_engine, room, key=_FORGOTTEN_KEY) == "forgotten"

    await _run_extraction(committed_engine, room, _EpisodeClient())
    await _run_fact_extraction(committed_engine, room, _FactClient())
    without_rewind = (await _scene_titles(committed_engine, room), await _fact_keys(committed_engine, room))
    await _delete_message_committed(committed_engine, room, room.turns[5][0])
    await _commit_snapshot(committed_engine, room, turn=10)
    await _run_extraction(committed_engine, room, _EpisodeClient())
    await _run_fact_extraction(committed_engine, room, _FactClient())

    assert without_rewind == ([], [])
    assert await _scene_titles(committed_engine, room) == ["정류장"]
    assert await _fact_keys(committed_engine, room) == [_FORGOTTEN_KEY]


async def test_a_scene_extraction_that_read_its_window_before_a_secret_fact_was_forgotten_discards_its_scene(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """턴 20 스냅샷의 사실 추출은 끝났고(지아만 아는 사실 — 근거 턴 15) 장면 추출은 아직이다. 장면 추출이 창을 읽고 모델을 기다리는
    사이 사용자가 그 비밀 사실을 잊고 커밋한다. 그때는 겹치는 장면이 아직 없어 함께 지울 것이 없고, 추출이 곧 넣을 장면(턴 11~20)은
    그 비밀과 겹치지만 가려 줄 사실이 사라졌다. 추출은 넣기 직전에 방의 잊기 세대가 바뀐 것을 보고 결과를 버리고 실패로 적는다
    (시도 하나를 쓴다, Bugsink 로 올리지 않는다). 세대를 다시 확인하지 않으면 그 장면이 가림 없이 남는다.

    한계도 함께 고정한다 — 버린 스냅샷은 다음 턴 뒤 다시 쥐어지고, 창 원문은 그대로라 같은 장면이 다시 뽑힌다(가리던 사실은
    이미 없다). 세대 확인은 잊기와 겹친 그 한 번의 결과를 막을 뿐이다."""
    captured = _capture_episode_failures(monkeypatch)
    room = await _seed_committed_room(committed_engine, turns=20)
    await _commit_snapshot(committed_engine, room, turn=10)
    await _commit_snapshot(committed_engine, room, turn=20)
    first = await _snapshot_id_at(committed_engine, room, turn=10)
    second = await _snapshot_id_at(committed_engine, room, turn=20)
    secret_turn = room.turns[15][1]
    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                _make_memory_extraction(room.room_id, first),
                _make_memory_fact(
                    room.room_id,
                    second,
                    fact_key=_FORGOTTEN_KEY,
                    value="몰래 사귐",
                    known_by=["지아"],
                    start_created_at=secret_turn.created_at,
                    start_message_id=secret_turn.id,
                    end_created_at=secret_turn.created_at,
                    end_message_id=secret_turn.id,
                ),
                _make_memory_fact_extraction(room.room_id, second),
            ]
        )
        await session.commit()
    outcomes: list[str] = []

    async def _user_forgets_the_secret() -> None:
        outcomes.append(await _forget_committed(committed_engine, room, key=_FORGOTTEN_KEY))

    llm = _EpisodeClient(before_answer=_user_forgets_the_secret)
    await _run_extraction(committed_engine, room, llm)

    assert (llm.calls, outcomes, captured) == (1, ["forgotten"], [])
    episodes, records = await _committed_episode_state(committed_engine, room)
    assert (episodes, sorted(records)) == (0, [("done", 1), ("failed", 1)])

    await _run_extraction(committed_engine, room, _EpisodeClient())
    assert await _scene_titles(committed_engine, room) == ["정류장"]


# --- 인상 생성과 잊게 하기의 경합 -----------------------------------------------------------------
#
# 인상 생성의 마지막 트랜잭션은 묶음의 가장 새 스냅샷을 `FOR KEY SHARE` 로 먼저 잡은 뒤 방의 잊기 세대를 다시 읽고 행을 넣는다.
# 잊게 하기(장면·사실)는 그 방 스냅샷 전부를 `FOR UPDATE` 로 잡은 뒤 지우는 행을 근거로 쓴 인상과 그 묶음의 `done` 시도 기록을
# 지우고 세대를 올린다. 근거는 잠금을 얻은 뒤 읽으므로 기다리는 동안 커밋된 인상의 근거까지 본다.


class _ImpressionClient(LLMClient):
    """인상만 부른다. `before_answer` 는 결과를 돌려주기 전에(생성이 입력을 다 읽고 세션을 닫은 뒤) 불린다."""

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
        raise AssertionError("인상 생성은 대화 생성을 부르지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        assert response_schema is MemoryImpressionResult, response_schema
        self.calls += 1
        if self.before_answer is not None:
            await self.before_answer()
        return MemoryImpressionResult(impression="정류장 장면 뒤로 서로를 믿기 시작했다.")


async def _room_ready_for_an_impression(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> tuple[Room, uuid.UUID]:
    """20턴 방, 묶음 크기 2. 턴 10·20 스냅샷 모두 장면 하나씩과 두 추출 기록(끝남)이 있다. (방, 턴 20 장면 id)."""
    monkeypatch.setattr(settings, "memory_impression_every_n_folds", 2)
    room = await _seed_committed_room(engine, turns=20)
    await _commit_snapshot(engine, room, turn=10)
    await _commit_snapshot(engine, room, turn=20)
    first = await _snapshot_id_at(engine, room, turn=10)
    second = await _snapshot_id_at(engine, room, turn=20)
    later = _make_memory_episode(room.room_id, second, title="빵집", detail="빵집 앞에서 다시 만났다.")
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                _make_memory_episode(room.room_id, first, title="정류장", detail="정류장에서 우산을 나눠 썼다."),
                later,
                _make_memory_extraction(room.room_id, first),
                _make_memory_extraction(room.room_id, second),
                _make_memory_fact_extraction(room.room_id, first, fact_count=0),
                _make_memory_fact_extraction(room.room_id, second, fact_count=0),
            ]
        )
        await session.commit()
    return room, later.id


async def _run_impression(engine: AsyncEngine, room: Room, llm: LLMClient) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        prompt_set, sections = await load_active_prompt_set(session, lane="character")
    await generate_pending_impression(
        async_sessionmaker(engine, expire_on_commit=False),
        llm,
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=prompt_set,
        sections=_impression_sections(prompt_set, sections),
        is_story_chat=False,
        writing_model="opus",
    )


async def _committed_impressions(engine: AsyncEngine, room: Room) -> int:
    return await _count_rows(engine, ChatMemoryImpression.chat_room_id == room.room_id, model=ChatMemoryImpression)


async def test_a_scene_forgotten_while_an_impression_holds_its_snapshot_takes_the_impression_it_wrote(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인상 생성이 마지막 트랜잭션에서 스냅샷을 잡고 세대 확인을 지나 행까지 넣은 채(커밋 전) 멈췄다. 그때 사용자가 근거 장면 하나를
    잊는다. 잊기는 스냅샷 `FOR UPDATE` 에서 생성 커밋을 기다렸다가 방금 들어간 인상까지 지운다 — 어느 쪽도 교착으로 끊기지 않고 잊은
    장면을 품은 인상이 남지 않는다."""
    room, scene_id = await _room_ready_for_an_impression(committed_engine, monkeypatch)
    gate = _Gate()
    _pause_after(monkeypatch, memory_impressions, "_insert_impression", gate)
    generation = asyncio.create_task(_run_impression(committed_engine, room, _ImpressionClient()))

    paused, outcome = await _forget_while_paused(
        committed_engine, gate, generation, lambda: _forget_committed(committed_engine, room, episode_id=scene_id)
    )

    assert (paused, outcome) == (True, "forgotten")
    assert await _committed_impressions(committed_engine, room) == 0


async def _impression_attempt_states(engine: AsyncEngine, room: Room) -> list[str]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return list(
            (
                await session.scalars(
                    sa.select(ChatMemoryImpressionAttempt.status).where(
                        ChatMemoryImpressionAttempt.chat_room_id == room.room_id
                    )
                )
            ).all()
        )


async def test_a_key_forgotten_while_an_impression_holds_its_snapshot_takes_the_impression_and_its_done_attempt(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인상 생성이 마지막 트랜잭션에서 스냅샷을 잡고 시도 기록을 `done` 으로 바꾸고 행까지 넣은 채(커밋 전) 멈췄다(입력에 잊을 키의
    행이 있다). 그때 사용자가 그 키를 잊는다. 잊기는 스냅샷 `FOR UPDATE` 에서 생성 커밋을 기다렸다가, 방금 들어간 인상의 근거에서
    잊는 키의 행을 보고 그 인상과 `done` 기록을 함께 지운다 — 어느 쪽도 교착으로 끊기지 않는다. 근거를 잠금 전에 읽으면 방금
    들어간 인상을 못 보고 남긴다."""
    room, _ = await _room_ready_for_an_impression(committed_engine, monkeypatch)
    first = await _snapshot_id_at(committed_engine, room, turn=10)
    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        session.add(_make_memory_fact(room.room_id, first, fact_key=_FORGOTTEN_KEY, value="이웃"))
        await session.commit()
    gate = _Gate()
    _pause_after(monkeypatch, memory_impressions, "_insert_impression", gate)
    generation = asyncio.create_task(_run_impression(committed_engine, room, _ImpressionClient()))

    paused, outcome = await _forget_while_paused(
        committed_engine, gate, generation, lambda: _forget_committed(committed_engine, room, key=_FORGOTTEN_KEY)
    )

    assert (paused, outcome) == (True, "forgotten")
    assert await _committed_impressions(committed_engine, room) == 0
    assert await _impression_attempt_states(committed_engine, room) == []


async def test_a_scene_added_after_an_impression_read_its_input_is_forgotten_without_taking_that_impression(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인상 생성이 행을 넣은 채(커밋 전) 멈춘 사이 그 묶음 스냅샷에 장면 하나가 더 커밋되고(인상의 입력에 없었다), 사용자가 그
    장면을 잊는다. 잊기는 생성 커밋을 기다린 뒤 그 인상의 근거를 보고 잊는 장면이 없으니 인상과 `done` 기록을 남긴다 — 교착
    없이 둘 다 끝난다. 근거와 무관하게 방의 인상을 다 지우면 잊은 내용을 품지 않은 인상까지 사라진다."""
    room, _ = await _room_ready_for_an_impression(committed_engine, monkeypatch)
    first = await _snapshot_id_at(committed_engine, room, turn=10)
    gate = _Gate()
    _pause_after(monkeypatch, memory_impressions, "_insert_impression", gate)
    generation = asyncio.create_task(_run_impression(committed_engine, room, _ImpressionClient()))

    async def _add_then_forget_a_late_scene() -> str:
        late = _make_memory_episode(room.room_id, first, ordinal=1, title="늦은 장면", detail="나중에 들어온 장면.")
        async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
            session.add(late)
            await session.commit()
        return await _forget_committed(committed_engine, room, episode_id=late.id)

    paused, outcome = await _forget_while_paused(committed_engine, gate, generation, _add_then_forget_a_late_scene)

    assert (paused, outcome) == (True, "forgotten")
    assert await _committed_impressions(committed_engine, room) == 1
    assert await _impression_attempt_states(committed_engine, room) == ["done"]


async def test_an_impression_that_read_its_input_before_a_scene_was_forgotten_discards_its_result(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인상 생성이 입력(잊을 장면이 있다)을 읽고 모델을 기다리는 사이 사용자가 그 장면을 잊고 커밋한다. 그때는 지울 인상이 아직
    없다. 장면 잊기도 잊기 세대를 올리므로 생성은 넣기 직전에 그것을 보고 결과를 버린다. 세대가 그대로거나 다시 확인하지 않으면 잊은
    장면을 품은 인상이 남는다."""
    room, scene_id = await _room_ready_for_an_impression(committed_engine, monkeypatch)
    outcomes: list[str] = []

    async def _user_forgets_the_scene() -> None:
        outcomes.append(await _forget_committed(committed_engine, room, episode_id=scene_id))

    llm = _ImpressionClient(before_answer=_user_forgets_the_scene)
    await _run_impression(committed_engine, room, llm)

    assert (llm.calls, outcomes) == (1, ["forgotten"])
    assert await _committed_impressions(committed_engine, room) == 0


async def test_concurrent_impressions_of_one_group_call_the_model_once(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 턴의 백그라운드가 다른 워커에서 같은 묶음을 골랐다(앞 턴의 호출이 끝나기 전에 다음 턴이 끝났다). 선점은 하나만 이기고
    모델은 한 번만 불린다 — 인상 행의 스냅샷 유니크는 두 번째 행만 막을 뿐 두 번째 호출의 원가는 막지 못한다. 두 작업은 묶음을
    고른 직후(선점 전)에 서로를 기다려 순서를 시간이 아니라 상태로 강제한다."""
    room, _ = await _room_ready_for_an_impression(committed_engine, monkeypatch)
    both_picked = asyncio.Barrier(2)
    pick = memory_impressions._due_group

    async def _both_pick_before_either_claims(*args: Any, **kwargs: Any) -> Any:
        group = await pick(*args, **kwargs)
        await both_picked.wait()
        return group

    monkeypatch.setattr(memory_impressions, "_due_group", _both_pick_before_either_claims)
    llm = _ImpressionClient()

    await asyncio.wait_for(
        asyncio.gather(_run_impression(committed_engine, room, llm), _run_impression(committed_engine, room, llm)), 15
    )

    assert llm.calls == 1
    assert await _committed_impressions(committed_engine, room) == 1
    async with async_sessionmaker(committed_engine, expire_on_commit=False)() as session:
        attempts = (
            await session.execute(
                sa.select(ChatMemoryImpressionAttempt.status, ChatMemoryImpressionAttempt.attempts).where(
                    ChatMemoryImpressionAttempt.chat_room_id == room.room_id
                )
            )
        ).all()
    assert [tuple(row) for row in attempts] == [("done", 1)]
