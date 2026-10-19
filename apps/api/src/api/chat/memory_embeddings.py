"""장면·사실 기억 행을 임베딩해 `chat_memory_embeddings` 에 채운다.

턴이 끝난 뒤 요청의 background 로, 그 턴의 접기와 두 추출 **뒤에** 돈다(`chat/router.py` 의 `_fold_after_commit`). 새 세션을 열고
어떤 예외도 밖으로 내지 않는다 — background 태스크는 차례로 돌고 한 태스크가 예외를 내면 뒤 태스크가 돌지 않는다. 사용자가 시킨
호출이 아니라 클로버를 깎지 않고 레이트리밋에도 세지 않는다.

한 번 부르면 방에서 지금 모델·차원의 임베딩이 없는 장면·사실 행을 오래된 순서로 상한(`EMBED_BATCH_MAX`)까지 한 요청으로
임베딩한다. 어느 추출이 막 넣은 행인지 따지지 않고 "임베딩이 없는 행"을 찾으므로, 추출 순서와 묶이지 않고 실패했거나 스위치를
켜기 전에 쌓인 행도 다음 채우기가 따라잡는다. 오래된 순서는 스냅샷 커서 → 근거 원문의 끝 메시지 키 → 장면 먼저 → 순번이다.

정합과 교착은 추출(`chat/memory_episodes.py`·`chat/memory_facts.py`)과 같은 근거를 쓴다. 장면·사실 행과 그 임베딩은 되감기·초기화·
방 삭제의 스냅샷 DELETE 의 CASCADE 로만 지워지고, 이 모듈은 아무것도 지우거나 고쳐 쓰지 않는다(INSERT 만). 넣는 트랜잭션은
스냅샷마다 따로 열고 첫 문장에서 그 스냅샷을 `FOR KEY SHARE` 로 잡는다 — 되감기도 스냅샷부터 잡으므로 둘이 한 방향으로 줄을 선다.
잡지 않으면 임베딩 INSERT 의 FK 확인이 대상 행을 잡는 순서와 CASCADE 가 대상 행을 지우는 순서가 엇갈릴 때 교착한다. Voyage 는
세션 없이 부른다 — 기다리는 동안 커넥션도 잠금도 쥐지 않는다."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.memory_fact_section import fact_body
from api.chat.voyage_backoff import clear_voyage_backoff, record_voyage_failure, voyage_allowed
from api.core.sentry import capture_dependency_failure
from api.db.models import ChatMemoryEmbedding, ChatMemoryEpisode, ChatMemoryFact, ChatRoomMemorySnapshot
from api.llm.voyage import EmbeddingError, VoyageEmbeddingClient

logger = logging.getLogger(__name__)

# 사용량 기록의 호출 이름. LLM 호출 정책 표의 call_site 가 아니다(`llm/voyage.py`).
EMBEDDING_CALL_SITE = "chat_memory_embedding"
# 한 번에 임베딩하는 행 수의 상한. 접기 한 번이 넣는 행(장면 몇 개 + 사실 20개까지)을 한 번에 받고 남는 몫으로 밀린 행을
# 따라잡는다. 행 하나가 수십~수백 토큰이라 한 요청이 Voyage 의 요청당 입력 수·토큰 한도보다 한참 작다.
EMBED_BATCH_MAX = 64
# 외래 키 위반. 대상 행이 그사이 지워졌다는 뜻이라 경합이지 실패가 아니다.
_FOREIGN_KEY_VIOLATION = "23503"


@dataclass(frozen=True)
class _Pending:
    """임베딩할 행 하나 — 대상(장면 또는 사실)과 그 글, 정렬 키."""

    snapshot_id: uuid.UUID
    kind: Literal["episode", "fact"]
    target_id: uuid.UUID
    text: str
    order: tuple[datetime, uuid.UUID, datetime, uuid.UUID, int, int]


def episode_text(row: ChatMemoryEpisode) -> str:
    """장면의 임베딩 글 — 제목과 본문을 줄바꿈으로 잇는다(임베딩 오프라인 비교가 잰 글과 같은 꼴)."""
    return f"{row.title}\n{row.detail}"


async def fill_pending_embeddings(
    session_factory: async_sessionmaker[AsyncSession], client: VoyageEmbeddingClient, *, room_id: uuid.UUID
) -> None:
    """방에서 임베딩이 없는 장면·사실 행을 상한까지 임베딩해 넣는다. 절대 예외를 내지 않는다(취소만 통과시킨다).

    1. 새 세션에서 지금 모델·차원(`client.model`·`client.dims`)의 임베딩이 없는 행을 오래된 순서로 상한까지 고르고 세션을 닫는다.
       없으면 끝(Voyage 를 부르지 않는다).
    2. Voyage 연속 실패로 멈춘 동안이면 끝(`chat/voyage_backoff.py`). 아니면 세션 없이 Voyage 를 한 번 부른다(문서 종류). 그
       호출이 실패하면 연속 실패 수에 세고, 성공하면 지운다 — 뒤의 DB 실패는 Voyage 실패가 아니라 세지 않는다.
    3. 스냅샷마다 새 세션 한 트랜잭션: **먼저 스냅샷을 `FOR KEY SHARE` 로 잠근다**(없으면 되감겼다 — 그 스냅샷 몫은 건너뛴다).
       그다음 행마다 SAVEPOINT 를 두고 INSERT 한다 — 대상 행이 그사이 사라져 외래 키에 걸리면 그 행만 건너뛰고, 같은 대상·모델·
       차원 행이 이미 있으면(다른 작업이 먼저 넣었다) 넣지 않는다. 그리고 커밋한다.
    4. 실패(Voyage·DB·그 밖의 예외)는 경고로 남기고 Bugsink 로 올린다. 넣지 못한 행은 다음 채우기가 다시 고른다."""
    try:
        async with session_factory() as session:
            pending = await _pending_rows(session, room_id, client.model, client.dims)
        if not pending:
            return
        if not await voyage_allowed():
            logger.warning("대화방 %s 기억 임베딩 채우기를 Voyage 연속 실패 멈춤으로 건너뛴다", room_id)
            return
        try:
            vectors = await client.embed(
                [row.text for row in pending], input_type="document", call_site=EMBEDDING_CALL_SITE
            )
        except Exception:
            await record_voyage_failure()
            raise
        await clear_voyage_backoff()
        for snapshot_id in dict.fromkeys(row.snapshot_id for row in pending):
            share = [(row, vector) for row, vector in zip(pending, vectors, strict=True) if row.snapshot_id == snapshot_id]
            async with session_factory() as session:
                if not await _lock_snapshot(session, snapshot_id):
                    continue
                for row, vector in share:
                    await _insert_row(session, room_id, row, vector, client)
                await session.commit()
    # `BaseException`이 아니라 `Exception` — 클라이언트가 끊어 생긴 취소까지 삼키면 요청 정리가 막힌다.
    except Exception as exc:
        logger.warning("대화방 %s 기억 임베딩 채우기 실패 — 다음 턴 뒤에 다시 시도한다: %s", room_id, exc)
        capture_dependency_failure(exc, dependency=_dependency_tag(exc))


async def _pending_rows(session: AsyncSession, room_id: uuid.UUID, model: str, dims: int) -> list[_Pending]:
    """지금 모델·차원의 임베딩이 없는 장면·사실 행을 오래된 순서로 상한까지. 두 테이블을 따로 상한까지 읽어 합친 뒤 다시 자른다."""
    snapshot, embedding = ChatRoomMemorySnapshot, ChatMemoryEmbedding
    pending: list[_Pending] = []

    episode = ChatMemoryEpisode
    episode_done = exists().where(
        embedding.episode_id == episode.id, embedding.model == model, embedding.dims == dims
    )
    episode_rows = await session.execute(
        select(episode, snapshot.cursor_created_at, snapshot.cursor_message_id)
        .join(snapshot, snapshot.id == episode.snapshot_id)
        .where(episode.chat_room_id == room_id, ~episode_done)
        .order_by(
            snapshot.cursor_created_at,
            snapshot.cursor_message_id,
            episode.end_created_at,
            episode.end_message_id,
            episode.ordinal,
        )
        .limit(EMBED_BATCH_MAX)
    )
    for scene, cursor_at, cursor_id in episode_rows.tuples():
        order = (cursor_at, cursor_id, scene.end_created_at, scene.end_message_id, 0, scene.ordinal)
        pending.append(_Pending(scene.snapshot_id, "episode", scene.id, episode_text(scene), order))

    fact = ChatMemoryFact
    fact_done = exists().where(embedding.fact_id == fact.id, embedding.model == model, embedding.dims == dims)
    fact_rows = await session.execute(
        select(fact, snapshot.cursor_created_at, snapshot.cursor_message_id)
        .join(snapshot, snapshot.id == fact.snapshot_id)
        .where(fact.chat_room_id == room_id, ~fact_done)
        .order_by(
            snapshot.cursor_created_at,
            snapshot.cursor_message_id,
            fact.end_created_at,
            fact.end_message_id,
            fact.ordinal,
        )
        .limit(EMBED_BATCH_MAX)
    )
    for item, cursor_at, cursor_id in fact_rows.tuples():
        order = (cursor_at, cursor_id, item.end_created_at, item.end_message_id, 1, item.ordinal)
        pending.append(_Pending(item.snapshot_id, "fact", item.id, fact_body(item), order))

    return sorted(pending, key=lambda row: row.order)[:EMBED_BATCH_MAX]


async def _lock_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> bool:
    """넣는 트랜잭션의 첫 문장 — 스냅샷을 `FOR KEY SHARE` 로 잠근다(요약 편집의 제자리 UPDATE 는 막지 않고, 되감기의 스냅샷
    삭제는 이 트랜잭션이 끝날 때까지 기다리게 한다). 없으면 되감겼다."""
    locked = await session.scalar(
        select(ChatRoomMemorySnapshot.id)
        .where(ChatRoomMemorySnapshot.id == snapshot_id)
        .with_for_update(read=True, key_share=True)
    )
    return locked is not None


async def _insert_row(
    session: AsyncSession, room_id: uuid.UUID, row: _Pending, vector: Sequence[float], client: VoyageEmbeddingClient
) -> bool:
    """행 하나를 SAVEPOINT 안에서 넣는다. 대상 행이 사라져 외래 키에 걸리면 그 SAVEPOINT 만 되돌리고 False 다."""
    statement = (
        insert(ChatMemoryEmbedding)
        .values(
            chat_room_id=room_id,
            episode_id=row.target_id if row.kind == "episode" else None,
            fact_id=row.target_id if row.kind == "fact" else None,
            model=client.model,
            dims=client.dims,
            embedding=list(vector),
        )
        .on_conflict_do_nothing()
    )
    try:
        async with session.begin_nested():
            await session.execute(statement)
    except IntegrityError as exc:
        if _sqlstate(exc) != _FOREIGN_KEY_VIOLATION:
            raise
        logger.warning("기억 %s %s 의 임베딩을 넣지 못했다 — 그사이 지워졌다", row.kind, row.target_id)
        return False
    return True


def _sqlstate(exc: IntegrityError) -> str | None:
    """asyncpg 드라이버 오류의 SQLSTATE. SQLAlchemy 가 감싼 원래 오류(`exc.orig`)에 `sqlstate` 로 실린다."""
    state = getattr(exc.orig, "sqlstate", None)
    return state if isinstance(state, str) else None


def _dependency_tag(exc: Exception) -> str:
    """채우기 실패의 승격 태그. Voyage 실패는 쿼터 소진(429)을 갈라 `voyage_rate_limit`, 그 밖은 `voyage`. DB 실패는 `db`, 그 밖은
    `memory_embedding`."""
    if isinstance(exc, EmbeddingError):
        return "voyage_rate_limit" if exc.status == 429 else "voyage"
    if isinstance(exc, SQLAlchemyError):
        return "db"
    return "memory_embedding"
