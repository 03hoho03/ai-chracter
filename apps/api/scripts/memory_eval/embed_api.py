"""임베딩 오프라인 비교의 호출기 — `embed-plan` 이 낸 글 목록(`{"inputType", "sha256", "text"}` 줄)을 Voyage 또는 Gemini 로
임베딩해 `embed_offline` 이 읽는 벡터 파일(`{"model", "dims", "inputType", "sha256", "vector"}` 줄)에 덧붙인다.

- Voyage: `httpx` 로 임베딩 엔드포인트 하나만 부른다(SDK 없음). 장면 글은 `input_type=document`, 질의 글은 `query`. 요청당 입력
  1,000개·모델별 요청당 토큰 한도(공식 문서 값) 안으로 나눈다. 원장 토큰은 응답의 `usage.total_tokens` 다.
- Gemini 비교군: 앱이 쓰는 `google-genai` 로 `gemini-embedding-2`. 이 모델은 `task_type` 을 받지 않고 글 앞에 검색용 접두를
  붙이라고 공식 문서가 적는다(질의 `task: search result | query: …`, 문서 `title: … | text: …`). 문자열 목록을 그대로 넘기면 SDK 가
  한 Content 의 여러 Part 로 합쳐 임베딩 하나만 돌아오므로 글마다 Content 하나를 만든다. SDK 응답에는 토큰 사용량이 없어서
  원장에는 보낸 글(접두 포함)의 보수 견적을 적는다.
- 요청 전마다 원장의 묶음 상한·멈춤 선을 그 요청의 견적으로 본다(넘을 것 같으면 보내기 전에 멈춘다). 원장 원가는 무료 몫과
  상관없이 정가로 적는다 — 무료 몫이 모델끼리 공유되는지 문서에 없어서 보수적으로 센다.
- 429·5xx·시간 초과·연결 실패만 다시 시도하고(상한 있음) 그 밖의 4xx 는 바로 실패다. 오류 문구에 키 값은 싣지 않는다.
- 한 요청이 성공할 때마다 벡터를 파일에 덧붙이고 원장에 한 줄 적는다 — 중간에 실패해도 앞 요청분은 남는다.

토큰 견적은 글자 수 × `TOKENS_PER_CHAR`(한국어는 글자당 1토큰 아래로 잘리므로 넉넉한 쪽)."""

import json
import math
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from memory_eval.embed_offline import INPUT_TYPES
from memory_eval.ledger import Ledger, cost_usd

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
# 요청당 총 토큰 한도(모델별)와 입력 수 한도, 출력 차원 — Voyage 공식 문서 값.
VOYAGE_REQUEST_TOKENS: dict[str, int] = {"voyage-4-large": 120_000, "voyage-4": 320_000, "voyage-4-lite": 1_000_000}
VOYAGE_MAX_INPUTS = 1000
VOYAGE_CONTEXT_TOKENS = 32_000
VOYAGE_DIMS = (256, 512, 1024, 2048)
# Voyage 가격표가 모델마다 적는 무료 몫(Batch API 제외).
VOYAGE_FREE_TOKENS = 200_000_000

GEMINI_MODEL = "gemini-embedding-2"
GEMINI_DIM_RANGE = (128, 3072)
GEMINI_INPUT_TOKENS = 8192
# 요청당 입력 수 한도는 공식 문서에 숫자가 없다 — 한 요청을 작게 둔다.
GEMINI_MAX_INPUTS = 100

TOKENS_PER_CHAR = 1.0
TIMEOUT_S = 30.0
MAX_ATTEMPTS = 4
CALL_SITE = "memory_eval_embedding"
DEFAULT_GRID = ",".join(
    [f"{m}@{d}" for m in ("voyage-4-lite", "voyage-4", "voyage-4-large") for d in VOYAGE_DIMS]
    + [f"{GEMINI_MODEL}@1536"]
)


class EmbedError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    provider: str  # voyage · gemini
    model: str
    dims: int

    @property
    def label(self) -> str:
        return f"{self.model}@{self.dims}"

    @classmethod
    def parse(cls, raw: str) -> "Candidate":
        model, _, dims_raw = raw.strip().partition("@")
        if not dims_raw.isdigit():
            raise SystemExit(f"후보는 '모델@차원' 꼴이다: {raw!r}")
        dims = int(dims_raw)
        if model in VOYAGE_REQUEST_TOKENS:
            if dims not in VOYAGE_DIMS:
                raise SystemExit(f"Voyage 출력 차원은 {VOYAGE_DIMS} 중 하나다: {raw!r}")
            return cls("voyage", model, dims)
        if model == GEMINI_MODEL:
            low, high = GEMINI_DIM_RANGE
            if not low <= dims <= high:
                raise SystemExit(f"Gemini 출력 차원은 {low}~{high} 다: {raw!r}")
            return cls("gemini", model, dims)
        raise SystemExit(f"모르는 임베딩 모델: {model!r} (Voyage {sorted(VOYAGE_REQUEST_TOKENS)} · {GEMINI_MODEL})")


def parse_candidates(raw: str) -> list[Candidate]:
    return [Candidate.parse(part) for part in raw.split(",") if part.strip()]


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) * TOKENS_PER_CHAR))


def estimate_tokens_total(texts: Iterable[str]) -> int:
    return sum(estimate_tokens(t) for t in texts)


def price_usd(model: str, tokens: int) -> float:
    return cost_usd(
        model, input_tokens=tokens, cached_tokens=0, cache_write_tokens=0, output_tokens=0, thoughts_tokens=0
    )


def make_batches(
    rows: Sequence[Mapping[str, str]], *, max_inputs: int, max_tokens: int
) -> list[list[Mapping[str, str]]]:
    """입력 종류마다(한 요청에는 한 종류만) 앞에서부터 입력 수·토큰 견적 한도 안으로 채운다."""
    batches: list[list[Mapping[str, str]]] = []
    for kind in INPUT_TYPES:
        current: list[Mapping[str, str]] = []
        used = 0
        for row in (r for r in rows if r["inputType"] == kind):
            tokens = estimate_tokens(row["text"])
            if tokens > max_tokens:
                raise SystemExit(f"글 하나가 요청 토큰 한도 {max_tokens} 를 넘는다(견적 {tokens}): {row['sha256']}")
            if current and (len(current) >= max_inputs or used + tokens > max_tokens):
                batches.append(current)
                current, used = [], 0
            current.append(row)
            used += tokens
        if current:
            batches.append(current)
    return batches


def require_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} 가 비어 있다 — 유료 임베딩 실행은 키가 있어야 한다")
    return value


def make_http_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_S)


def _backoff(attempt: int, retry_after: str | None = None) -> float:
    if retry_after is not None:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return float(min(2**attempt, 30))


class Embedder(Protocol):
    model: str
    dims: int
    max_inputs: int
    max_request_tokens: int
    max_input_tokens: int
    usage_note: str

    def embed(self, texts: Sequence[str], *, input_type: str) -> tuple[list[list[float]], int]: ...


def _check_vectors(provider: str, vectors: list[list[float]], *, count: int, dims: int) -> list[list[float]]:
    if len(vectors) != count:
        raise EmbedError(f"{provider} 응답 벡터 개수 {len(vectors)} 가 입력 {count} 와 다르다")
    if any(len(v) != dims for v in vectors):
        raise EmbedError(f"{provider} 응답 벡터 차원이 {dims} 가 아니다")
    return vectors


class VoyageEmbedder:
    usage_note = ""

    def __init__(
        self,
        *,
        model: str,
        dims: int,
        api_key: str,
        client: httpx.Client,
        timeout_s: float = TIMEOUT_S,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.dims = dims
        self.max_inputs = VOYAGE_MAX_INPUTS
        self.max_request_tokens = VOYAGE_REQUEST_TOKENS[model]
        self.max_input_tokens = VOYAGE_CONTEXT_TOKENS
        self._key = api_key
        self._client = client
        self._timeout = timeout_s
        self._attempts = max_attempts
        self._sleep = sleep

    def embed(self, texts: Sequence[str], *, input_type: str) -> tuple[list[list[float]], int]:
        body = {"input": list(texts), "model": self.model, "input_type": input_type, "output_dimension": self.dims}
        headers = {"Authorization": f"Bearer {self._key}"}
        last = ""
        for attempt in range(1, self._attempts + 1):
            try:
                response = self._client.post(VOYAGE_URL, json=body, headers=headers, timeout=self._timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = f"Voyage 요청 실패({type(exc).__name__})"
                retry_after = None
            else:
                if response.status_code == 200:
                    payload = response.json()
                    data = sorted(payload.get("data") or [], key=lambda d: int(d["index"]))
                    vectors = [[float(x) for x in d["embedding"]] for d in data]
                    _check_vectors("Voyage", vectors, count=len(texts), dims=self.dims)
                    return vectors, int(payload["usage"]["total_tokens"])
                last = f"Voyage 응답 {response.status_code}: {response.text[:200]}"
                if response.status_code != 429 and response.status_code < 500:
                    raise EmbedError(last)
                retry_after = response.headers.get("retry-after")
            if attempt < self._attempts:
                self._sleep(_backoff(attempt, retry_after))
        raise EmbedError(f"{last} — {self._attempts}번 시도 뒤 포기")


def gemini_text(text: str, input_type: str) -> str:
    if input_type == "query":
        return f"task: search result | query: {text}"
    title, sep, body = text.partition("\n")
    return f"title: {title} | text: {body}" if sep else f"title: none | text: {text}"


class GeminiEmbedder:
    usage_note = "토큰은 보낸 글(접두 포함)의 보수 견적 — SDK 응답에 사용량이 없다"

    def __init__(
        self,
        *,
        model: str,
        dims: int,
        client: Any,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.dims = dims
        self.max_inputs = GEMINI_MAX_INPUTS
        self.max_request_tokens = GEMINI_MAX_INPUTS * GEMINI_INPUT_TOKENS
        self.max_input_tokens = GEMINI_INPUT_TOKENS
        self._client = client
        self._attempts = max_attempts
        self._sleep = sleep

    def embed(self, texts: Sequence[str], *, input_type: str) -> tuple[list[list[float]], int]:
        from google.genai import errors, types

        sent = [gemini_text(t, input_type) for t in texts]
        contents = [types.Content(parts=[types.Part(text=t)]) for t in sent]
        config = types.EmbedContentConfig(output_dimensionality=self.dims)
        last = ""
        for attempt in range(1, self._attempts + 1):
            try:
                response = self._client.models.embed_content(model=self.model, contents=contents, config=config)
            except errors.APIError as exc:
                last = f"Gemini 응답 {exc.code}: {(exc.message or '')[:200]}"
                if exc.code != 429 and exc.code < 500:
                    raise EmbedError(last) from exc
            except httpx.HTTPError as exc:
                last = f"Gemini 요청 실패({type(exc).__name__})"
            else:
                vectors = [[float(x) for x in (e.values or [])] for e in (response.embeddings or [])]
                _check_vectors("Gemini", vectors, count=len(texts), dims=self.dims)
                return vectors, estimate_tokens_total(sent)
            if attempt < self._attempts:
                self._sleep(_backoff(attempt))
        raise EmbedError(f"{last} — {self._attempts}번 시도 뒤 포기")


def make_embedder(candidate: Candidate) -> Embedder:
    """키를 먼저 확인한 뒤에 클라이언트를 만든다(키가 없으면 아무 연결도 만들지 않는다)."""
    if candidate.provider == "voyage":
        key = require_key("VOYAGE_API_KEY")
        return VoyageEmbedder(model=candidate.model, dims=candidate.dims, api_key=key, client=make_http_client())
    from google import genai
    from google.genai import types

    key = require_key("GEMINI_API_KEY")
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(TIMEOUT_S * 1000)))
    return GeminiEmbedder(model=candidate.model, dims=candidate.dims, client=client)


def embed_rows(
    rows: Sequence[Mapping[str, str]],
    embedder: Embedder,
    *,
    ledger: Ledger,
    out: Path,
    stage: str,
    max_inputs: int | None = None,
) -> dict[str, Any]:
    too_long = [r["sha256"] for r in rows if estimate_tokens(r["text"]) > embedder.max_input_tokens]
    if too_long:
        raise SystemExit(f"입력 토큰 한도 {embedder.max_input_tokens} 를 넘는 글 {len(too_long)}개: {too_long[:3]}")
    batches = make_batches(rows, max_inputs=max_inputs or embedder.max_inputs, max_tokens=embedder.max_request_tokens)
    out.parent.mkdir(parents=True, exist_ok=True)
    tokens_total = 0
    usd_total = 0.0
    for batch in batches:
        texts = [r["text"] for r in batch]
        ledger.check_headroom(price_usd(embedder.model, estimate_tokens_total(texts)))
        vectors, tokens = embedder.embed(texts, input_type=batch[0]["inputType"])
        row = ledger.append(
            stage=stage, call_site=CALL_SITE, model=embedder.model, input_tokens=tokens, cached_tokens=0,
            cache_write_tokens=0, output_tokens=0, thoughts_tokens=0,
            note=f"{embedder.dims}차원 {batch[0]['inputType']} {len(batch)}개 {embedder.usage_note}".strip(),
        )  # fmt: skip
        with out.open("a", encoding="utf-8") as handle:
            for source, vector in zip(batch, vectors, strict=True):
                line = {"model": embedder.model, "dims": embedder.dims, "inputType": source["inputType"],
                        "sha256": source["sha256"], "vector": vector}  # fmt: skip
                handle.write(json.dumps(line) + "\n")
        tokens_total += tokens
        usd_total += float(row["costUsd"])
    return {"model": embedder.model, "dims": embedder.dims, "requests": len(batches), "texts": len(rows),
            "tokens": tokens_total, "usd": usd_total}  # fmt: skip


def estimate(
    rows: Sequence[Mapping[str, str]], candidate: Candidate, *, ledger_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """보낼 글의 토큰 견적·정가 원가와 무료 몫 안인지(원장 전체에서 그 모델이 이미 쓴 토큰 + 견적). Gemini 무료 몫은 키의
    등급(무료·유료)에 달려 여기서 판정하지 않는다(None)."""
    sent = (
        [gemini_text(r["text"], r["inputType"]) for r in rows]
        if candidate.provider == "gemini"
        else [r["text"] for r in rows]
    )
    tokens = estimate_tokens_total(sent) if rows else 0
    used = sum(int(r.get("inputTokens") or 0) for r in ledger_rows if r.get("model") == candidate.model)
    within = used + tokens <= VOYAGE_FREE_TOKENS if candidate.provider == "voyage" else None
    max_tokens = VOYAGE_REQUEST_TOKENS.get(candidate.model, GEMINI_MAX_INPUTS * GEMINI_INPUT_TOKENS)
    max_inputs = VOYAGE_MAX_INPUTS if candidate.provider == "voyage" else GEMINI_MAX_INPUTS
    return {
        "candidate": candidate.label,
        "texts": len(rows),
        "requests": len(make_batches(rows, max_inputs=max_inputs, max_tokens=max_tokens)) if rows else 0,
        "tokens": tokens,
        "usd": price_usd(candidate.model, tokens),
        "modelTokensInLedger": used,
        "withinFree": within,
    }


def read_plan(path: Path) -> list[dict[str, str]]:
    from memory_eval.embed_offline import text_sha

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["inputType"] not in INPUT_TYPES or text_sha(row["text"]) != row["sha256"]:
            raise SystemExit(f"글 목록 줄의 inputType 또는 sha256 이 맞지 않는다: {row.get('sha256')}")
    return rows
