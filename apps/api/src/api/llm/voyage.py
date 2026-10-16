"""Voyage 임베딩 클라이언트 — 임베딩 엔드포인트 하나를 `httpx` 로 직접 부른다(SDK 없음, 호출이 이 하나뿐이다).

LLM 호출 정책 표(`llm/call_policy.py`)에 넣지 않는다 — 그 표는 생성·구조화 호출의 공급자 능력과 시간 상한을 다루고 Voyage 는
그 공급자 목록에 없다. 원가는 같은 일 단위 사용량 기록(`llm/usage_store.py`)에 call_site 문자열로 더한다.

- 요청: `input`(글 목록)·`model`·`input_type`(`document` 는 저장할 글, `query` 는 찾는 글 — Voyage 가 종류마다 다른 검색용 머리말을
  붙인다)·`output_dimension`. 너무 긴 글은 Voyage 가 기본값대로 잘라서 받는다.
- 응답 벡터는 `index` 로 입력 순서에 맞춘다. 개수나 차원이 어긋나면 실패다 — 어느 행의 벡터인지 모르거나 차원 CHECK 에 막힌다.
- 시간 초과·연결 실패·429·5xx 는 지나가는 실패로 보고 `retry_delays` 만큼 쉬며 다시 보낸다. 그 밖의 4xx 는 요청이나 키가 틀린
  것이라 바로 실패다. 실패는 전부 `EmbeddingError` 로 올린다(키 값은 싣지 않는다).
- 응답을 받은 호출마다 `usage.total_tokens` 를 사용량 기록의 입력 토큰과 합계에 더한다 — 임베딩은 입력만 과금된다.
- 연결: 운영 클라이언트(`transport` 없음)는 프로세스 하나가 HTTP 클라이언트 하나를 나눠 쓴다. 요청마다 새로 열면 TCP·TLS 왕복이
  턴 안의 질의 임베딩 시간 상한 안에 그대로 더해진다(운영 VM 30회: 새 클라이언트 p50 224ms·p95 578ms, 다시 쓰는 연결 p50
  130ms·p95 482ms). 턴 사이 간격이 수십 초라 유휴 연결을 `KEEPALIVE_EXPIRY_SECONDS` 동안 쥔다(httpx 기본 5초면 거의 매 턴 새로
  연결한다). 연결은 연 이벤트 루프에 묶이므로 지금 루프가 연 풀이 아니면 새로 연다 — 스크립트가 `asyncio.run` 을 거듭 불러도 앞
  루프의 연결을 쓰지 않는다. 처음 부를 때 만들므로 import·의존성 해석만으로는 네트워크도 풀도 생기지 않는다. 서버가 내려갈 때
  `aclose_shared_client` 가 닫는다(`main.py` lifespan). 시간 상한에 취소된 요청의 연결은 httpcore 가 풀에 돌려놓지 않고 닫는다.
  `transport` 를 넘긴 클라이언트(테스트·측정 흉내)는 호출마다 그 트랜스포트로 클라이언트를 새로 연다."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from api.llm.usage_store import record_usage

VOYAGE_EMBEDDINGS_URL = "https://api.voyageai.com/v1/embeddings"
# 한 요청의 시간 상한(초). 백그라운드 채우기가 쓰는 값이라 턴을 기다리게 하지 않는다 — 넘기면 다시 보낸다. 턴 안의 질의
# 임베딩은 부르는 쪽(`chat/memory_vector.py`)이 훨씬 짧은 상한으로 호출 전체를 끊는다.
TIMEOUT_SECONDS = 10.0
# 다시 보내기 전 쉬는 시간(초). 길이 + 1 이 한 번 부를 때의 최대 시도 수다.
RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 4.0)
# 공유 풀이 유휴 연결을 쥐는 시간(초). 턴 사이 간격을 덮어야 다음 턴이 연결을 다시 쓴다.
KEEPALIVE_EXPIRY_SECONDS = 120.0

# 공유 HTTP 클라이언트와 그것을 연 이벤트 루프. 처음 부를 때 만든다.
_shared: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None

EmbeddingInputType = Literal["document", "query"]


class EmbeddingError(Exception):
    """임베딩 호출 실패. `status` 는 마지막 HTTP 상태 코드다(응답을 못 받았으면 None)."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class _VoyageUsage:
    """사용량 기록이 읽는 이름으로 옮긴 Voyage 사용량. 입력 토큰 하나뿐이라 입력과 합계가 같다."""

    prompt_token_count: int
    total_token_count: int


def _retryable(status: int) -> bool:
    return status == 429 or status >= 500


def _shared_client() -> httpx.AsyncClient:
    """지금 루프가 연 공유 클라이언트. 없거나 다른 루프가 열었거나 닫혔으면 새로 연다 — 다른 루프의 클라이언트는 그 루프에서만
    닫을 수 있어 닫지 않고 놓는다."""
    global _shared
    loop = asyncio.get_running_loop()
    if _shared is None or _shared[0] is not loop or _shared[1].is_closed:
        limits = httpx.Limits(keepalive_expiry=KEEPALIVE_EXPIRY_SECONDS)
        _shared = (loop, httpx.AsyncClient(timeout=TIMEOUT_SECONDS, limits=limits))
    return _shared[1]


async def aclose_shared_client() -> None:
    """공유 클라이언트를 닫는다(서버 종료 때). 다른 루프가 연 것이면 닫지 않고 놓는다."""
    global _shared
    if _shared is None:
        return
    loop, client = _shared
    _shared = None
    if loop is asyncio.get_running_loop():
        await client.aclose()


class VoyageEmbeddingClient:
    """`model`·`dims` 는 이 클라이언트가 내는 벡터의 모델 id 와 차원이다 — 임베딩 표의 같은 칸에 그대로 적는다.
    `transport` 는 테스트가 응답을 흉내 낼 때만 넘긴다. 넘기지 않으면 프로세스의 공유 HTTP 클라이언트로 보낸다(모듈 설명의 연결).
    이 객체는 키·모델·차원만 쥐므로 요청마다 새로 만들어도 연결은 다시 쓴다."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dims: int,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delays: Sequence[float] = RETRY_DELAYS_SECONDS,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.dims = dims
        self._transport = transport
        self._retry_delays = tuple(retry_delays)

    async def embed(self, texts: Sequence[str], *, input_type: EmbeddingInputType, call_site: str) -> list[list[float]]:
        """`texts` 의 벡터를 같은 순서로 돌려준다. `call_site` 는 사용량 기록의 호출 이름이다."""
        vectors, _tokens = await self.embed_with_usage(texts, input_type=input_type, call_site=call_site)
        return vectors

    async def embed_with_usage(
        self, texts: Sequence[str], *, input_type: EmbeddingInputType, call_site: str
    ) -> tuple[list[list[float]], int]:
        """`embed` 와 같고 그 호출이 보고한 토큰 수를 함께 돌려준다 — 턴 기록에 질의 임베딩의 사용량을 남기는 쪽이 쓴다."""
        body = {"input": list(texts), "model": self.model, "input_type": input_type, "output_dimension": self.dims}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._transport is None:
            return await self._post(_shared_client(), body, headers, len(texts), call_site)
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
            return await self._post(client, body, headers, len(texts), call_site)

    async def _post(
        self, client: httpx.AsyncClient, body: dict[str, Any], headers: dict[str, str], count: int, call_site: str
    ) -> tuple[list[list[float]], int]:
        attempts = len(self._retry_delays) + 1
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(self._retry_delays[attempt - 1])
            try:
                response = await client.post(VOYAGE_EMBEDDINGS_URL, json=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error = EmbeddingError(f"Voyage 요청 실패({type(exc).__name__}) — {attempt + 1}/{attempts}번째 시도")
                continue
            if response.status_code == 200:
                return await self._vectors(response, count, call_site)
            error = EmbeddingError(
                f"Voyage 응답 {response.status_code} — {attempt + 1}/{attempts}번째 시도", status=response.status_code
            )
            if not _retryable(response.status_code):
                raise error
        raise error

    async def _vectors(self, response: httpx.Response, count: int, call_site: str) -> tuple[list[list[float]], int]:
        try:
            payload = response.json()
            data = sorted(payload["data"], key=lambda item: int(item["index"]))
            vectors = [[float(x) for x in item["embedding"]] for item in data]
            tokens = int(payload["usage"]["total_tokens"])
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"Voyage 응답을 읽지 못했다({type(exc).__name__})", status=200) from exc
        await record_usage(call_site, self.model, _VoyageUsage(tokens, tokens))
        if len(vectors) != count:
            raise EmbeddingError(f"Voyage 응답 벡터 {len(vectors)}개가 입력 {count}개와 다르다", status=200)
        if any(len(vector) != self.dims for vector in vectors):
            raise EmbeddingError(f"Voyage 응답 벡터 차원이 {self.dims} 가 아니다", status=200)
        return vectors, tokens
