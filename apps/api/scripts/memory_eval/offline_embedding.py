"""궤적 재조립의 오프라인 질의 임베딩 — 앱 조립 함수(`build_room_prompt`)에 넘길 가짜 임베딩 클라이언트. 질의 벡터를 미리 계산한
벡터 파일(오프라인 비교의 `embed-plan`·`embed-run` 이 쓰는 꼴, `embed_offline.EmbeddingTable`)에서 글의 sha256 으로 읽는다. 외부
호출이 없고 같은 파일이면 같은 벡터라 재조립이 결정론이다.

왜 필요한가: 앱은 클라이언트를 받지 못하면 임베딩 회상 스위치가 켜져 있어도 질의 임베딩을 부르지 않고 명사 단독으로 조립한다.
측정 서버는 Voyage 클라이언트를 받으므로, 클라이언트 없이 재조립한 임베딩 회상 갈래는 서버와 다른 프롬프트를 잰다.

질의 글은 앱이 만든다(운영 `api.chat.memory_vector.query_text` — 이번 사용자 메시지 + 줄바꿈 + 직전 응답). 이 클라이언트는 받은
글의 해시로 찾기만 하므로 벡터 파일의 키가 운영 질의 글과 저절로 맞는다.

벡터가 없는 질의 글이면 `SystemExit` 로 멈춘다. 앱의 질의 임베딩은 실패(`Exception`)를 흡수해 그 턴을 명사 단독으로 조립하는데,
`SystemExit` 는 `Exception` 이 아니라 그 흡수를 뚫고 올라온다 — 임베딩 회상 갈래가 벡터 없이 명사 단독으로 재진 점은 측정이
무효다. 계획 모드(`missing` 목록을 준 것)에서만 멈추지 않고 빠진 글을 `embed-plan` 출력 꼴(`{"inputType", "sha256", "text"}`)로
모은 뒤 그 턴은 흡수되는 실패로 넘긴다 — 모은 글을 `embed-run` 으로 채워 다시 재조립하고, 계획 모드의 점은 쓰지 않는다.

프로브 턴 기록(`chat_turns.llm_calls`)의 질의 임베딩 칸은 호출 이름·모델·차원·토큰·지연·결과만 남기고 벡터를 남기지 않아 벡터
출처가 될 수 없다."""

import contextlib
from collections.abc import Iterator, Sequence

from api.core.config import settings
from api.llm.voyage import EmbeddingInputType, VoyageEmbeddingClient

from memory_eval.embed_offline import EmbeddingTable, HybridParams, text_sha
from memory_eval.runtime import ARMS


class MissingQueryVectorError(Exception):
    """계획 모드에서 벡터가 없는 질의 글 — 앱이 흡수하는 실패로 그 턴을 넘긴다(계획 모드의 점은 쓰지 않는다)."""


class OfflineQueryEmbeddingClient(VoyageEmbeddingClient):
    """앱 임베딩 클라이언트와 같은 꼴(`model`·`dims`·`embed`·`embed_with_usage`)이고 벡터 파일에서만 읽는다. 장면·사실 글
    (`document`)은 재조립이 부를 일이 없으므로 받지 않는다."""

    def __init__(self, table: EmbeddingTable, *, missing: list[dict[str, str]] | None = None) -> None:
        super().__init__(api_key="", model=table.model, dims=table.dims)
        self._table = table
        self._missing = missing

    async def embed(self, texts: Sequence[str], *, input_type: EmbeddingInputType, call_site: str) -> list[list[float]]:
        vectors, _tokens = await self.embed_with_usage(texts, input_type=input_type, call_site=call_site)
        return vectors

    async def embed_with_usage(
        self, texts: Sequence[str], *, input_type: EmbeddingInputType, call_site: str
    ) -> tuple[list[list[float]], int]:
        if input_type != "query":
            raise SystemExit(f"오프라인 질의 임베딩은 질의 글만 받는다 — {input_type} 글을 부른 곳을 확인한다")
        for text in texts:
            if self._table.has("query", text):
                continue
            if self._missing is None:
                raise SystemExit(
                    f"{self.model}·{self.dims} 질의 벡터가 없는 글이 있어 이 갈래 재조립을 멈춘다(명사 단독으로 재면 측정 "
                    f"무효) — --embed-plan-out 으로 빠진 글을 모아 embed-run 으로 채운 뒤 다시: {text[:40]!r}"
                )
            row = {"inputType": "query", "sha256": text_sha(text), "text": text}
            if row not in self._missing:
                self._missing.append(row)
            raise MissingQueryVectorError(row["sha256"])
        return [self._table.vector("query", text) for text in texts], 0


def embeds_recall(arm: str) -> bool:
    return bool(ARMS[arm].get("memory_embed_recall"))


def embedding_arms(arms: Sequence[str]) -> list[str]:
    return [arm for arm in arms if embeds_recall(arm)]


def client_for(
    arm: str, table: EmbeddingTable | None, *, missing: list[dict[str, str]] | None = None
) -> OfflineQueryEmbeddingClient | None:
    """임베딩 회상을 켠 갈래면 오프라인 클라이언트, 꺼진 갈래면 None(클라이언트 없이 — 지금 조립 그대로). 켠 갈래인데 벡터
    파일이 없으면 거부한다."""
    if not embeds_recall(arm):
        return None
    if table is None:
        raise SystemExit(
            f"갈래 {arm} 은 임베딩 회상을 켠다 — 질의 벡터 파일(--embeddings·--embed-model·--embed-dims) 없이 재조립하면 "
            "명사 단독으로 잰다"
        )
    return OfflineQueryEmbeddingClient(table, missing=missing)


@contextlib.contextmanager
def recall_settings(params: HybridParams) -> Iterator[None]:
    """하이브리드 회상 설정(`memory_embed_recall_*`)을 이 프로세스의 `settings` 에 잠시 씌운다 — 재조립 프로세스는 `.env` 를
    읽고 뜨므로, 씌우지 않으면 측정 서버에 준 값이 아니라 `.env` 값이나 앱 기본값으로 고른다. df 상한 '없음'(None)도 씌운다."""
    overrides = params.config()
    saved = {name: getattr(settings, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)
