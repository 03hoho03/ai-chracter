"""임베딩 회상의 벡터 쪽 — 턴마다 한 번 받는 질의 임베딩, 방의 장면·사실 임베딩과의 거리 순위, 명사 순위와 합치는 RRF.

장면 회상(`chat/memory_recall.py`)과 사실 섹션의 관련 몫(`chat/memory_fact_section.py`)이 같은 질의 임베딩을 쓴다. 생성 프롬프트
조립(`chat/turn_prompt.py`)이 회상·사실 섹션을 고르기 전에 한 번 부른다.

질의 글: 이번 사용자 메시지, 줄바꿈, 직전 AI 응답(키워드북·회상과 같은 스캔 글). 사용자 메시지를 앞에 둔다 — Voyage 는 너무 긴
글의 뒤를 잘라 받으므로 긴 응답이 붙어도 이번 턴의 말은 남는다. 찾는 글(`query`) 종류로 보낸다.

시간 상한: 질의 임베딩은 생성 앞에서 기다리므로 첫 글자 지연에 그대로 더해진다. 상한(`memory_embed_recall_timeout_ms`)을 넘기면
호출을 끊고 명사 단독으로 조립한다. 실패(키 거부·연결·응답 형식)도 같다 — 무엇이 실패하든 예외를 밖으로 내지 않는다(생성
프롬프트 조립은 SSE 제너레이터 본문 안이라 예외가 새면 무관한 요청까지 500 이 된다). 취소(`CancelledError`)는 `Exception` 이
아니라 그대로 올라간다.

거리 읽기: 방 단위 정확 탐색(인덱스 없음)이고 늘 `model = 질의 모델 AND dims = 질의 차원` 으로 거른다 — 임베딩 칸은 차원을 적지
않아 차원이 다른 행에 거리 연산이 걸리면 질의째 실패한다. 질의 벡터는 글자로 보내 `CAST(… AS halfvec)` 로 감싼다(`db/types.py`).
읽기는 요청 세션의 SAVEPOINT 안이고 실패하면 경고·승격을 남기고 벡터 쪽을 빈 것으로 본다 — 명사 쪽 결과는 그대로 남는다.

RRF: 순위 목록마다 `1/(k + 순위)`(순위는 1부터)를 더한 값의 내림차순. 같으면 앞 목록(명사)에서 순위가 높은 쪽이 먼저다 — 벡터
목록이 비면 명사 목록의 순서가 그대로 나온다."""

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import Executable, Float, bindparam, cast, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.core.sentry import capture_dependency_failure
from api.db.models.chat import ChatMemoryEmbedding, ChatMemoryEpisode, ChatMemoryFact, ChatRoomMemorySnapshot
from api.db.types import HalfVec
from api.llm.voyage import EmbeddingError, VoyageEmbeddingClient

logger = logging.getLogger(__name__)

# 사용량 기록과 턴 기록 호출 목록의 호출 이름. LLM 호출 정책 표의 call_site 가 아니다(`llm/voyage.py`).
QUERY_EMBEDDING_CALL_SITE = "chat_memory_query_embedding"

_T = TypeVar("_T", bound=Hashable)


@dataclass(frozen=True)
class QueryVector:
    """질의 임베딩 — 이 벡터를 낸 모델·차원과 함께. 거리 읽기는 이 모델·차원의 행만 본다."""

    model: str
    dims: int
    vector: list[float]


@dataclass(frozen=True)
class QueryEmbedding:
    """이번 턴의 질의 임베딩 결과. `vector` 는 실패·시간 초과면 None 이다. `record` 는 턴 기록 호출 목록(`chat_turns.llm_calls`)에
    더할 한 칸 `{callSite, model, dims, promptTokens, latencyMs, outcome}` 이고 `outcome` 은 `ok`·`timeout`·`failed` 다."""

    vector: QueryVector | None
    record: dict[str, Any]


def query_text(user_text: str, previous_assistant: str) -> str:
    return f"{user_text}\n{previous_assistant}" if previous_assistant else user_text


async def embed_query(
    client: VoyageEmbeddingClient, text: str, *, timeout_seconds: float, room_id: uuid.UUID
) -> QueryEmbedding:
    """질의 글 하나를 시간 상한 안에서 임베딩한다. 절대 예외를 내지 않는다(취소만 통과시킨다)."""
    started = time.monotonic()
    vector: QueryVector | None = None
    tokens: int | None = None
    outcome = "ok"
    try:
        async with asyncio.timeout(timeout_seconds):
            vectors, tokens = await client.embed_with_usage(
                [text], input_type="query", call_site=QUERY_EMBEDDING_CALL_SITE
            )
        vector = QueryVector(model=client.model, dims=client.dims, vector=vectors[0])
    except TimeoutError:
        outcome = "timeout"
        logger.warning(
            "대화방 %s 질의 임베딩이 %s초 안에 오지 않아 이번 턴은 명사 단독으로 회상한다", room_id, timeout_seconds
        )
    except Exception as exc:
        outcome = "failed"
        logger.warning("대화방 %s 질의 임베딩 실패 — 이번 턴은 명사 단독으로 회상한다: %s", room_id, exc)
        capture_dependency_failure(exc, dependency=_dependency_tag(exc))
    record = {
        "callSite": QUERY_EMBEDDING_CALL_SITE,
        "model": client.model,
        "dims": client.dims,
        "promptTokens": tokens,
        "latencyMs": round((time.monotonic() - started) * 1000),
        "outcome": outcome,
    }
    return QueryEmbedding(vector, record)


def _dependency_tag(exc: Exception) -> str:
    if isinstance(exc, EmbeddingError):
        return "voyage_rate_limit" if exc.status == 429 else "voyage"
    return "memory_embedding"


def rrf_order(rankings: Sequence[Sequence[_T]], *, k: int) -> list[_T]:
    """순위 목록들을 RRF 로 합친 순서(규칙은 모듈 설명)."""
    scores: dict[_T, float] = {}
    ranks: dict[_T, list[float]] = {}
    for position, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(item, [math.inf] * len(rankings))[position] = rank
    return sorted(scores, key=lambda item: (-scores[item], ranks[item]))


def _distance(query: QueryVector) -> Any:
    return ChatMemoryEmbedding.embedding.op("<=>", return_type=Float())(
        cast(bindparam("query_vector", query.vector, type_=HalfVec()), HalfVec())
    )


def _episode_distance_statement(room_id: uuid.UUID, cursor: MessageKey, query: QueryVector, limit: int) -> Executable:
    """그 방에서 회상 후보와 같은 조건(커서까지 접힌 스냅샷이 뽑았고 커서 이하에서 끝나는 장면)의 장면 임베딩을 질의와 가까운
    순으로 `limit` 개. 거리가 같으면 장면 id 순이다."""
    embedding, episode, snapshot = ChatMemoryEmbedding, ChatMemoryEpisode, ChatRoomMemorySnapshot
    distance = _distance(query)
    return (
        select(embedding.episode_id, distance)
        .join(episode, episode.id == embedding.episode_id)
        .join(snapshot, snapshot.id == episode.snapshot_id)
        .where(
            embedding.chat_room_id == room_id,
            embedding.model == query.model,
            embedding.dims == query.dims,
            tuple_(episode.end_created_at, episode.end_message_id) <= cursor,
            tuple_(snapshot.cursor_created_at, snapshot.cursor_message_id) <= cursor,
        )
        .order_by(distance, embedding.episode_id)
        .limit(limit)
    )


def _fact_distance_statement(room_id: uuid.UUID, cursor: MessageKey, query: QueryVector) -> Executable:
    """그 방에서 사실 섹션과 같은 조건(커서 이하로 접힌 스냅샷)의 사실 임베딩 거리 전부. 순위는 지식 범위 필터를 지난 행 사이에서
    매겨야 하므로 여기서 자르지 않는다."""
    embedding, fact, snapshot = ChatMemoryEmbedding, ChatMemoryFact, ChatRoomMemorySnapshot
    return (
        select(embedding.fact_id, _distance(query))
        .join(fact, fact.id == embedding.fact_id)
        .join(snapshot, snapshot.id == fact.snapshot_id)
        .where(
            embedding.chat_room_id == room_id,
            embedding.model == query.model,
            embedding.dims == query.dims,
            tuple_(snapshot.cursor_created_at, snapshot.cursor_message_id) <= cursor,
        )
    )


async def _read_distances(
    db: AsyncSession, statement: Executable, *, room_id: uuid.UUID, max_distance: float
) -> list[tuple[uuid.UUID, float]]:
    """거리 읽기를 SAVEPOINT 안에서 돌려 거리 상한 안의 (대상 id, 거리)를 읽은 순서로. 실패하면 경고·승격을 남기고 빈 목록이다."""
    try:
        async with db.begin_nested():
            rows = (await db.execute(statement)).all()
    except Exception as exc:
        logger.warning(
            "대화방 %s 기억 임베딩 거리를 읽지 못해 이번 턴은 명사 단독으로 고른다: %s", room_id, exc, exc_info=True
        )
        capture_dependency_failure(exc, dependency="db" if isinstance(exc, SQLAlchemyError) else "memory_embedding")
        return []
    return [(row[0], float(row[1])) for row in rows if row[0] is not None and float(row[1]) <= max_distance]


async def episode_distances(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    cursor: MessageKey,
    query: QueryVector,
    limit: int,
    max_distance: float,
) -> list[tuple[uuid.UUID, float]]:
    """회상 후보 장면의 (id, 거리)를 가까운 순으로 — 앞 `limit` 개 중 거리 상한 안의 것."""
    return await _read_distances(
        db, _episode_distance_statement(room_id, cursor, query, limit), room_id=room_id, max_distance=max_distance
    )


async def fact_distances(
    db: AsyncSession, *, room_id: uuid.UUID, cursor: MessageKey, query: QueryVector, max_distance: float
) -> dict[uuid.UUID, float]:
    """사실 섹션 후보 행의 id → 거리(거리 상한 안의 것만)."""
    return dict(
        await _read_distances(
            db, _fact_distance_statement(room_id, cursor, query), room_id=room_id, max_distance=max_distance
        )
    )
