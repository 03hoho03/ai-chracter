"""넣기 절차의 임베딩 따라잡기 — 운영 채우기 함수(`api.chat.memory_embeddings.fill_pending_embeddings`)를 넣기 자리에서 부른다.

운영은 턴 뒤 접기·두 추출 다음에 같은 함수를 background 로 한 번 부른다. 넣기도 턴마다 사실 추출 따라잡기 다음에 한 번 부른다 —
한 번에 상한(`EMBED_BATCH_MAX`)까지 오래된 행부터 채우므로 밀린 행도 다음 턴이 따라잡는다. 그 함수는 실패해도 예외를 내지
않으므로(경고만 남긴다) 진전은 앞뒤 행 수로 본다: 이 클라이언트의 모델·차원 임베딩이 없는 장면·사실 행 수(`pendingBefore`)와
그 모델·차원의 임베딩 행 수(`doneBefore`·`doneAfter`). 연속 진전 없음 판정은 부르는 쪽(`insert.ExtractionStreak`)이 한다.

얼리기 직전에는 남은 행이 없을 때까지 따라잡는다(`finish_embeddings`) — 덜 채운 템플릿에서는 임베딩 읽기 갈래의 벡터 순위가
빠진 행 없이 매겨져 갈래 사이 비교가 행 집합부터 어긋난다.

클라이언트: 가짜 실행은 네트워크 없이 글의 해시로 벡터를 내는 흉내 응답(`fake_embedding_client`), 유료 실행은 원장 상한을 먼저
보고 호출마다 원장에 적는 Voyage 클라이언트(`LedgerVoyageClient`)다. 운영 채우기는 어떤 예외도 삼키므로, 원장 상한에 걸린 멈춤은
클라이언트가 기억해 두고 따라잡기가 다시 올린다 — 안 그러면 진전 없음으로 보여 세 턴을 더 돈다."""

import hashlib
import json
import struct
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_embeddings
from api.llm.voyage import EmbeddingInputType, VoyageEmbeddingClient

from memory_eval.embed_api import estimate_tokens_total, price_usd
from memory_eval.ledger import BudgetExceededError, Ledger

SessionFactory = async_sessionmaker[AsyncSession]

_PENDING_SQL = (
    "SELECT (SELECT count(*) FROM chat_memory_episodes e WHERE e.chat_room_id = :room AND NOT EXISTS "
    "(SELECT 1 FROM chat_memory_embeddings m WHERE m.episode_id = e.id AND m.model = :model AND m.dims = :dims)) + "
    "(SELECT count(*) FROM chat_memory_facts f WHERE f.chat_room_id = :room AND NOT EXISTS "
    "(SELECT 1 FROM chat_memory_embeddings m WHERE m.fact_id = f.id AND m.model = :model AND m.dims = :dims))"
)
_DONE_SQL = "SELECT count(*) FROM chat_memory_embeddings WHERE chat_room_id = :room AND model = :model AND dims = :dims"


def _fake_vector(text_: str, dims: int) -> list[float]:
    digest = b""
    counter = 0
    while len(digest) < dims * 4:
        digest += hashlib.sha256(f"{counter}:{text_}".encode()).digest()
        counter += 1
    return [(struct.unpack_from(">I", digest, i * 4)[0] / 2**32) - 0.5 for i in range(dims)]


def fake_embedding_client(*, model: str, dims: int) -> VoyageEmbeddingClient:
    """가짜 실행용 — Voyage 응답 꼴을 흉내 내는 처리기로 같은 글에 같은 벡터를 낸다(네트워크·키 없음)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        data = [{"index": i, "embedding": _fake_vector(t, dims)} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 0}})

    return VoyageEmbeddingClient(
        api_key="fake-not-used", model=model, dims=dims, transport=httpx.MockTransport(handler)
    )


class LedgerVoyageClient(VoyageEmbeddingClient):
    """부르기 전에 원장 상한을 보고(넘으면 보내지 않는다), 응답을 받은 호출마다 보고된 토큰을 원장에 한 줄 적는다."""

    def __init__(self, *, ledger: Ledger, stage: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ledger = ledger
        self.stage = stage
        self.refused: BudgetExceededError | None = None

    async def embed_with_usage(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType,
        call_site: str,
        retry_delays: Sequence[float] | None = None,
    ) -> tuple[list[list[float]], int]:
        try:
            self.ledger.check_headroom(price_usd(self.model, estimate_tokens_total(texts)))
        except BudgetExceededError as exc:
            self.refused = exc
            raise
        vectors, tokens = await super().embed_with_usage(
            texts, input_type=input_type, call_site=call_site, retry_delays=retry_delays
        )
        self.ledger.append(
            stage=self.stage, call_site=call_site, model=self.model, input_tokens=tokens, cached_tokens=0,
            cache_write_tokens=0, output_tokens=0, thoughts_tokens=0,
            note=f"{self.dims}차원 {input_type} {len(texts)}개",
        )  # fmt: skip
        return vectors, tokens


class EmbeddingFill(Protocol):
    async def run_once(self, session_factory: SessionFactory, room_id: uuid.UUID) -> dict[str, Any]: ...

    async def pending(self, session_factory: SessionFactory, room_id: uuid.UUID) -> int: ...


@dataclass
class EmbeddingCatchUp:
    client: VoyageEmbeddingClient

    async def _count(self, db: AsyncSession, sql: str, room_id: uuid.UUID) -> int:
        params = {"room": room_id, "model": self.client.model, "dims": self.client.dims}
        return int(await db.scalar(text(sql), params) or 0)

    async def pending(self, session_factory: SessionFactory, room_id: uuid.UUID) -> int:
        async with session_factory() as db:
            return await self._count(db, _PENDING_SQL, room_id)

    async def run_once(self, session_factory: SessionFactory, room_id: uuid.UUID) -> dict[str, Any]:
        """한 번 따라잡는다. 할 일이 없으면 채우기 함수를 부르지 않는다(운영 함수도 그때는 Voyage 를 부르지 않는다)."""
        async with session_factory() as db:
            pending = await self._count(db, _PENDING_SQL, room_id)
            done_before = await self._count(db, _DONE_SQL, room_id)
        done_after = done_before
        if pending:
            await memory_embeddings.fill_pending_embeddings(session_factory, self.client, room_id=room_id)
            refused = getattr(self.client, "refused", None)
            if refused is not None:
                raise refused
            async with session_factory() as db:
                done_after = await self._count(db, _DONE_SQL, room_id)
        return {
            "model": self.client.model,
            "dims": self.client.dims,
            "pendingBefore": pending,
            "doneBefore": done_before,
            "doneAfter": done_after,
        }


async def finish_embeddings(
    fill: EmbeddingFill, session_factory: SessionFactory, room_id: uuid.UUID, *, attempts: int
) -> Sequence[dict[str, Any]]:
    """남은 행이 없을 때까지 `attempts` 번까지 따라잡는다. 그 안에 끝나지 않으면 얼리지 않고 멈춘다."""
    states: list[dict[str, Any]] = []
    for _ in range(attempts):
        if await fill.pending(session_factory, room_id) == 0:
            return states
        states.append(await fill.run_once(session_factory, room_id))
    left = await fill.pending(session_factory, room_id)
    if left:
        raise SystemExit(f"얼리기 전 임베딩 따라잡기가 {attempts}번 안에 끝나지 않았다 — 임베딩 없는 행 {left}개")
    return states
