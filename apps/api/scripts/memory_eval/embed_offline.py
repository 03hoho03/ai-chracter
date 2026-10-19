"""임베딩 오프라인 회상 — 미리 계산한 벡터 파일로 벡터 단독 순위와, 운영 하이브리드 회상(앱의 임베딩 회상 스위치 뒤 절차)과
같은 규격의 명사·벡터 RRF 순위를 낸다. LLM·임베딩 호출 없음. 결과는 `recall_offline` 의 검색 함수 꼴이라 recall@3·@10 집계가
명사 단독과 같은 코드로 돈다.

벡터 파일은 줄마다 `{"model", "dims", "inputType": "document"|"query", "sha256", "vector"}` 다. 글은 sha256 으로만 찾는다 —
같은 글이면 어느 문항·장면에서 나왔든 같은 벡터다. 고른 모델·차원이 아닌 줄은 읽지 않는다(한 파일에 여러 후보를 둘 수 있다).
필요한 벡터가 없으면 조용히 명사 단독으로 떨어지지 않고 거부한다 — 빠진 글 목록(`missing_texts`)을 먼저 만들어 벡터를 채운다.

운영과 맞춘 규격(`rrf_order`·`query_text` 는 운영 `api.chat.memory_vector` 의 것을 그대로 쓴다 — 사본을 두지 않는다):

- 장면 글 = 제목 + 줄바꿈 + 본문. 질의 글 = 이번 사용자 메시지 + 줄바꿈 + 직전 응답(직전 응답이 없으면 사용자 메시지만).
- 벡터 순위: 코사인 거리(1 - 코사인 유사도) 가까운 순(같으면 id 순) 앞 `vector_limit` 개를 자른 뒤 거리 상한 밖을 뺀다.
- 하이브리드(`rrf_retriever`): 명사 쪽은 운영 회상 점수에서 임계(`TAU`) 이상인 장면의 순위만(긴 방 df 상한 `df_max` 를 건
  점수), 벡터 쪽은 위 순위. 둘을 `Σ 1/(k + 순위)` 로 합치고 같으면 명사 쪽 순위가 높은 쪽이 먼저다. 회상 단서 턴은 `max_cue`,
  보통 턴은 `max_plain` 개를 싣는다. 벡터 쪽이 비거나 장면이 회상 최소 수보다 적으면 명사 단독(`server_recall.retrieve_server`)
  결과 그대로다.
- 벡터 단독(`vector_retriever`): 벡터 순위만으로 같은 상한을 건다(운영에는 없는 비교군).

상한·k·거리 상한·벡터 LIMIT·df 상한(`HybridParams`)의 이름과 기본값은 운영 설정(`memory_embed_recall_*`)과 같다."""

import hashlib
import json
import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

from api.chat import memory_recall as mr
from api.chat.memory_vector import query_text as query_text
from api.chat.memory_vector import rrf_order as rrf_order

from memory_eval import server_recall as sr
from memory_eval.recall_offline import Episode, Ranked, Retriever

INPUT_TYPES = ("document", "query")

_T = TypeVar("_T", bound=Hashable)


def rrf_scores(rankings: Sequence[Sequence[_T]], *, k: int) -> dict[_T, float]:
    scores: dict[_T, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


CONFIG_PREFIX = "memory_embed_recall_"


@dataclass(frozen=True)
class HybridParams:
    """하이브리드 회상의 설정 — 이름은 운영 설정에서 `memory_embed_recall_` 를 뗀 것이고 기본값은 운영 기본값이다."""

    rrf_k: int = 20
    max_plain: int = 1
    max_cue: int = 3
    max_distance: float = 2.0
    vector_limit: int = 10
    df_max: int | None = None

    def config(self) -> dict[str, Any]:
        return {f"{CONFIG_PREFIX}{name}": value for name, value in asdict(self).items()}


CONFIG_NAMES = tuple(f"{CONFIG_PREFIX}{f.name}" for f in fields(HybridParams))
DEFAULT_PARAMS = HybridParams()


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def episode_text(episode: Episode) -> str:
    return f"{episode.title}\n{episode.detail}"


@dataclass(frozen=True)
class EmbeddingTable:
    model: str
    dims: int
    vectors: Mapping[tuple[str, str], list[float]]

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]], *, model: str, dims: int) -> "EmbeddingTable":
        vectors: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            if row["model"] != model or int(row["dims"]) != dims:
                continue
            kind = str(row["inputType"])
            if kind not in INPUT_TYPES:
                raise SystemExit(f"벡터 파일의 inputType 은 {INPUT_TYPES} 중 하나다: {kind!r}")
            vector = [float(v) for v in row["vector"]]
            if len(vector) != dims:
                raise SystemExit(f"벡터 길이 {len(vector)} 가 차원 {dims} 와 다르다: {row['sha256']}")
            vectors[(kind, str(row["sha256"]))] = vector
        return cls(model=model, dims=dims, vectors=vectors)

    @classmethod
    def load(cls, path: Path, *, model: str, dims: int) -> "EmbeddingTable":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return cls.from_rows(rows, model=model, dims=dims)

    def has(self, kind: str, text: str) -> bool:
        return (kind, text_sha(text)) in self.vectors

    def vector(self, kind: str, text: str) -> list[float]:
        found = self.vectors.get((kind, text_sha(text)))
        if found is None:
            raise SystemExit(
                f"{self.model}·{self.dims} 벡터가 없는 {kind} 글이 있다 — embed-plan 으로 빠진 글을 채운 뒤 다시: {text[:40]!r}"
            )
        return found


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def _cap(params: HybridParams, user_text: str) -> int:
    return params.max_cue if mr.recall_cue(user_text) else params.max_plain


def nearest(
    table: EmbeddingTable, episodes: Sequence[Episode], text: str, *, limit: int, max_distance: float
) -> list[tuple[str, float]]:
    """질의 글과 가까운 순(같으면 id 순) 앞 `limit` 개 가운데 거리 상한 안의 (장면 id, 코사인 거리)."""
    query = table.vector("query", text)
    distances = [(e.id, 1.0 - cosine(query, table.vector("document", episode_text(e)))) for e in episodes]
    distances.sort(key=lambda pair: (pair[1], pair[0]))
    return [pair for pair in distances[:limit] if pair[1] <= max_distance]


def vector_retriever(table: EmbeddingTable, params: HybridParams = DEFAULT_PARAMS) -> Retriever:
    def retrieve(
        episodes: Sequence[Episode], *, user_text: str, previous_assistant: str, current_turn: int
    ) -> list[Ranked]:
        near = nearest(
            table,
            episodes,
            query_text(user_text, previous_assistant),
            limit=params.vector_limit,
            max_distance=params.max_distance,
        )
        cap = _cap(params, user_text)
        return [Ranked(episode_id, 1.0 - distance, i < cap) for i, (episode_id, distance) in enumerate(near)]

    return retrieve


def _fused(
    episodes: Sequence[Episode], vector_ids: Sequence[str], params: HybridParams, kwargs: dict[str, Any]
) -> list[Ranked]:
    """벡터 순위를 받은 뒤의 하이브리드 — 벡터 쪽이 비면 명사 단독(`server_recall.retrieve_server`) 결과 그대로다."""
    if not vector_ids:
        return sr.retrieve_server(episodes, **kwargs)
    scored = sr.score_server(episodes, **kwargs, df_max=params.df_max)
    rankings = [[row.id for row in scored if row.s >= mr.TAU], list(vector_ids)]
    order = rrf_order(rankings, k=params.rrf_k)
    scores = rrf_scores(rankings, k=params.rrf_k)
    cap = _cap(params, kwargs["user_text"])
    return [Ranked(episode_id, scores[episode_id], i < cap) for i, episode_id in enumerate(order)]


def rrf_retriever(table: EmbeddingTable, params: HybridParams = DEFAULT_PARAMS) -> Retriever:
    def retrieve(
        episodes: Sequence[Episode], *, user_text: str, previous_assistant: str, current_turn: int
    ) -> list[Ranked]:
        kwargs: dict[str, Any] = {
            "user_text": user_text,
            "previous_assistant": previous_assistant,
            "current_turn": current_turn,
        }
        if len(episodes) < mr.MIN_EPISODES:
            return sr.retrieve_server(episodes, **kwargs)
        near = nearest(
            table,
            episodes,
            query_text(user_text, previous_assistant),
            limit=params.vector_limit,
            max_distance=params.max_distance,
        )
        return _fused(episodes, [episode_id for episode_id, _ in near], params, kwargs)

    return retrieve


def embedding_off_retriever(params: HybridParams = DEFAULT_PARAMS) -> Retriever:
    """이 격자 점의 하이브리드에서 임베딩이 꺼진 경로(벡터 쪽이 빔) — 하이브리드와 같은 코드로 돈다. 격자 선택의 필수 조건
    (명사 단독 결과와 행 일치)을 이것으로 잰다."""

    def retrieve(
        episodes: Sequence[Episode], *, user_text: str, previous_assistant: str, current_turn: int
    ) -> list[Ranked]:
        kwargs: dict[str, Any] = {
            "user_text": user_text,
            "previous_assistant": previous_assistant,
            "current_turn": current_turn,
        }
        return _fused(episodes, [], params, kwargs)

    return retrieve


def missing_texts(table: EmbeddingTable, episodes: Sequence[Episode], queries: Iterable[str]) -> list[dict[str, str]]:
    """벡터가 없는 장면 글·질의 글(같은 글은 한 번). 벡터를 계산할 입력이다."""
    wanted = [("document", episode_text(e)) for e in episodes] + [("query", q) for q in queries]
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, body in wanted:
        key = (kind, text_sha(body))
        if key in seen or key in table.vectors:
            continue
        seen.add(key)
        out.append({"inputType": kind, "sha256": key[1], "text": body})
    return out
