"""Voyage 임베딩 클라이언트 — 임베딩 엔드포인트 하나를 `httpx` 로 직접 부른다(SDK 없음, 호출이 이 하나뿐이다).

LLM 호출 정책 표(`llm/call_policy.py`)에 넣지 않는다 — 그 표는 생성·구조화 호출의 공급자 능력과 시간 상한을 다루고 Voyage 는
그 공급자 목록에 없다. 원가는 같은 일 단위 사용량 기록(`llm/usage_store.py`)에 call_site 문자열로 더한다.

- 요청: `input`(글 목록)·`model`·`input_type`(`document` 는 저장할 글, `query` 는 찾는 글 — Voyage 가 종류마다 다른 검색용 머리말을
  붙인다)·`output_dimension`. 너무 긴 글은 Voyage 가 기본값대로 잘라서 받는다.
- 응답 벡터는 `index` 로 입력 순서에 맞춘다. 개수나 차원이 어긋나면 실패다 — 어느 행의 벡터인지 모르거나 차원 CHECK 에 막힌다.
- 시간 초과·연결 실패·429·5xx 는 지나가는 실패로 보고 `retry_delays` 만큼 쉬며 다시 보낸다. 그 밖의 4xx 는 요청이나 키가 틀린
  것이라 바로 실패다. 실패는 전부 `EmbeddingError` 로 올린다(키 값은 싣지 않는다).
- 응답을 받은 호출마다 `usage.total_tokens` 를 사용량 기록의 입력 토큰과 합계에 더한다 — 임베딩은 입력만 과금된다."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from api.llm.usage_store import record_usage

VOYAGE_EMBEDDINGS_URL = "https://api.voyageai.com/v1/embeddings"
# 한 요청의 시간 상한(초). 백그라운드 채우기가 쓰는 값이라 턴을 기다리게 하지 않는다 — 넘기면 다시 보낸다.
TIMEOUT_SECONDS = 10.0
# 다시 보내기 전 쉬는 시간(초). 길이 + 1 이 한 번 부를 때의 최대 시도 수다.
RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 4.0)

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


class VoyageEmbeddingClient:
    """`model`·`dims` 는 이 클라이언트가 내는 벡터의 모델 id 와 차원이다 — 임베딩 표의 같은 칸에 그대로 적는다.
    `transport` 는 테스트가 응답을 흉내 낼 때만 넘긴다. 호출마다 HTTP 클라이언트를 새로 연다(백그라운드 채우기는 턴마다 많아야
    한 번 부른다)."""

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
        body = {"input": list(texts), "model": self.model, "input_type": input_type, "output_dimension": self.dims}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        attempts = len(self._retry_delays) + 1
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
            for attempt in range(attempts):
                if attempt:
                    await asyncio.sleep(self._retry_delays[attempt - 1])
                try:
                    response = await client.post(VOYAGE_EMBEDDINGS_URL, json=body, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    error = EmbeddingError(f"Voyage 요청 실패({type(exc).__name__}) — {attempt + 1}/{attempts}번째 시도")
                    continue
                if response.status_code == 200:
                    return await self._vectors(response, len(texts), call_site)
                error = EmbeddingError(
                    f"Voyage 응답 {response.status_code} — {attempt + 1}/{attempts}번째 시도", status=response.status_code
                )
                if not _retryable(response.status_code):
                    raise error
        raise error

    async def _vectors(self, response: httpx.Response, count: int, call_site: str) -> list[list[float]]:
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
        return vectors
