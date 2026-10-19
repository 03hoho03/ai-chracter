"""임베딩 오프라인 비교 — Voyage·Gemini 호출기가 요청을 입력 수·토큰 한도 안으로 나누고, 429·5xx·시간 초과만 다시 시도하며,
매 요청 전에 묶음 멈춤 선을 보고 응답 사용량(없으면 보수 견적)을 정가로 원장에 적는지, 키가 없으면 거부하는지 본다. 비교
실행기는 개발 보기 문항만으로 견적과 명사·벡터·RRF recall 표를 낸다. 외부 호출 없음 — HTTP 는 `MockTransport`, Gemini 는 가짜
클라이언트다."""

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from memory_eval import embed_api as ea
from memory_eval import embed_offline as eo
from memory_eval.recall_offline import Ranked
from memory_eval.ledger import BudgetExceededError, Ledger


def _plan(texts: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"inputType": kind, "sha256": eo.text_sha(text), "text": text} for kind, text in texts]


def _voyage_ok(request: httpx.Request, *, dims: int, tokens_per_input: int = 7) -> httpx.Response:
    body = json.loads(request.content)
    data = [{"object": "embedding", "index": i, "embedding": [float(i + 1)] * dims} for i in range(len(body["input"]))]
    return httpx.Response(
        200, json={"object": "list", "data": data[::-1], "model": body["model"],
                   "usage": {"total_tokens": tokens_per_input * len(body["input"])}},
    )  # fmt: skip


class _Recorder:
    def __init__(self, responder: Any) -> None:
        self.requests: list[httpx.Request] = []
        self.responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response: httpx.Response = self.responder(request, len(self.requests))
        return response

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def _voyage(recorder: _Recorder, *, model: str = "voyage-4-lite", dims: int = 4, **kw: Any) -> ea.VoyageEmbedder:
    return ea.VoyageEmbedder(
        model=model, dims=dims, api_key="sk-test-secret", client=recorder.client(), sleep=lambda s: None, **kw
    )


def _ledger(tmp_path: Path, **kw: Any) -> Ledger:
    return Ledger(tmp_path / "ledger.jsonl", cap_usd=kw.get("cap", 1.0), halt_usd=kw.get("halt", 0.5), bundle="b1-s5")


# ---------------------------------------------------------------- Voyage 요청 꼴·배치


def test_voyage_request_carries_model_dims_input_type_and_bearer_key() -> None:
    rec = _Recorder(lambda req, n: _voyage_ok(req, dims=4))
    vectors, tokens = _voyage(rec).embed(["장면 하나", "장면 둘"], input_type="document")
    (request,) = rec.requests
    assert str(request.url) == ea.VOYAGE_URL
    assert request.headers["authorization"] == "Bearer sk-test-secret"
    assert rec.bodies()[0] == {
        "input": ["장면 하나", "장면 둘"], "model": "voyage-4-lite", "input_type": "document", "output_dimension": 4,
    }  # fmt: skip
    # 응답 순서가 뒤집혀 와도 index 로 입력 순서에 맞춘다.
    assert vectors == [[1.0] * 4, [2.0] * 4]
    assert tokens == 14


def test_batches_keep_one_input_type_per_request_and_stay_within_input_and_token_caps() -> None:
    rows = _plan([("document", "가" * 30), ("query", "나" * 10), ("document", "다" * 30), ("document", "라" * 30)])
    batches = ea.make_batches(rows, max_inputs=2, max_tokens=70)
    assert [[r["text"][0] for r in b] for b in batches] == [["가", "다"], ["라"], ["나"]]
    assert all(len({r["inputType"] for r in b}) == 1 for b in batches)
    with pytest.raises(SystemExit, match="한도"):
        ea.make_batches(_plan([("document", "가" * 80)]), max_inputs=2, max_tokens=70)


def test_voyage_model_table_uses_the_official_request_caps_and_dims() -> None:
    assert ea.VOYAGE_REQUEST_TOKENS == {"voyage-4-large": 120_000, "voyage-4": 320_000, "voyage-4-lite": 1_000_000}
    assert ea.VOYAGE_MAX_INPUTS == 1000
    assert ea.VOYAGE_DIMS == (256, 512, 1024, 2048)
    with pytest.raises(SystemExit, match="차원"):
        ea.Candidate.parse("voyage-4@768")
    with pytest.raises(SystemExit, match="모델"):
        ea.Candidate.parse("voyage-3@1024")


# ---------------------------------------------------------------- 재시도·거부


def test_voyage_retries_429_5xx_and_timeouts_then_succeeds() -> None:
    def responder(req: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            return httpx.Response(429, json={"detail": "rate"})
        if n == 2:
            raise httpx.ReadTimeout("slow", request=req)
        if n == 3:
            return httpx.Response(503, text="busy")
        return _voyage_ok(req, dims=4)

    rec = _Recorder(responder)
    slept: list[float] = []
    embedder = ea.VoyageEmbedder(
        model="voyage-4", dims=4, api_key="k", client=rec.client(), sleep=slept.append, max_attempts=4
    )
    vectors, _ = embedder.embed(["질의"], input_type="query")
    assert len(rec.requests) == 4 and len(slept) == 3 and vectors == [[1.0] * 4]


def test_voyage_gives_up_after_max_attempts_and_does_not_retry_other_4xx() -> None:
    rec = _Recorder(lambda req, n: httpx.Response(500, text="down"))
    with pytest.raises(ea.EmbedError, match="500"):
        _voyage(rec, max_attempts=3).embed(["x"], input_type="query")
    assert len(rec.requests) == 3

    rec = _Recorder(lambda req, n: httpx.Response(401, json={"detail": "bad key"}))
    with pytest.raises(ea.EmbedError) as err:
        _voyage(rec, max_attempts=3).embed(["x"], input_type="query")
    assert len(rec.requests) == 1
    assert "sk-test-secret" not in str(err.value)


def test_voyage_refuses_a_response_with_the_wrong_count_or_dims() -> None:
    rec = _Recorder(lambda req, n: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 3}],
                                                             "usage": {"total_tokens": 1}}))  # fmt: skip
    with pytest.raises(ea.EmbedError, match="차원"):
        _voyage(rec, dims=4).embed(["x"], input_type="query")
    rec = _Recorder(lambda req, n: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 4}],
                                                             "usage": {"total_tokens": 1}}))  # fmt: skip
    with pytest.raises(ea.EmbedError, match="개수"):
        _voyage(rec, dims=4).embed(["x", "y"], input_type="query")


def test_missing_keys_are_refused_without_printing_any_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="VOYAGE_API_KEY"):
        ea.require_key("VOYAGE_API_KEY")
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        ea.require_key("GEMINI_API_KEY")
    monkeypatch.setenv("VOYAGE_API_KEY", "real-looking-value")
    assert ea.require_key("VOYAGE_API_KEY") == "real-looking-value"


# ---------------------------------------------------------------- 원장·벡터 파일


def test_embed_rows_writes_vectors_and_one_ledger_row_per_request_at_list_price(tmp_path: Path) -> None:
    rec = _Recorder(lambda req, n: _voyage_ok(req, dims=4, tokens_per_input=1000))
    rows = _plan([("document", "카페\n창가 자리"), ("document", "편집실\n하드"), ("query", "창가에 앉았던 날")])
    out = tmp_path / "emb.jsonl"
    ledger = _ledger(tmp_path)
    summary = ea.embed_rows(
        rows, _voyage(rec, model="voyage-4-large"), ledger=ledger, out=out, stage="s5", max_inputs=2
    )
    assert summary["requests"] == 2 and summary["tokens"] == 3000
    lines = ledger.rows()
    assert [r["inputTokens"] for r in lines] == [2000, 1000]
    assert all(r["model"] == "voyage-4-large" and r["bundle"] == "b1-s5" for r in lines)
    assert lines[0]["costUsd"] == pytest.approx(2000 * 0.12 / 1_000_000)
    assert summary["usd"] == pytest.approx(3000 * 0.12 / 1_000_000)
    table = eo.EmbeddingTable.load(out, model="voyage-4-large", dims=4)
    assert table.has("document", "카페\n창가 자리") and table.has("query", "창가에 앉았던 날")


def test_list_prices_for_each_model_are_in_the_ledger_price_table() -> None:
    from memory_eval.ledger import price_for

    assert price_for("voyage-4").input_usd_per_million == 0.06
    assert price_for("voyage-4-lite").input_usd_per_million == 0.02
    assert price_for("voyage-4-large").input_usd_per_million == 0.12
    assert price_for(ea.GEMINI_MODEL).input_usd_per_million == 0.20


def test_headroom_is_checked_before_each_request_so_nothing_is_sent_past_the_halt_line(tmp_path: Path) -> None:
    rec = _Recorder(lambda req, n: _voyage_ok(req, dims=4))
    ledger = _ledger(tmp_path, cap=1.0, halt=0.000001)
    with pytest.raises(BudgetExceededError):
        ea.embed_rows(_plan([("query", "가" * 100)]), _voyage(rec), ledger=ledger, out=tmp_path / "e.jsonl", stage="s5")
    assert rec.requests == [] and ledger.rows() == []


def test_a_failed_batch_keeps_the_vectors_already_written(tmp_path: Path) -> None:
    rec = _Recorder(lambda req, n: _voyage_ok(req, dims=4) if n == 1 else httpx.Response(400, text="bad"))
    out = tmp_path / "e.jsonl"
    with pytest.raises(ea.EmbedError):
        ea.embed_rows(_plan([("query", "하나"), ("query", "둘")]), _voyage(rec), ledger=_ledger(tmp_path), out=out,
                      stage="s5", max_inputs=1)  # fmt: skip
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1
    assert len(_ledger(tmp_path).rows()) == 1


# ---------------------------------------------------------------- Gemini 비교군


class _FakeModels:
    def __init__(self, fail_first: int = 0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_first = fail_first

    def embed_content(self, *, model: str, contents: Any, config: Any) -> Any:
        from google.genai import errors, types

        self.calls.append({"model": model, "contents": contents, "config": config})
        if len(self.calls) <= self.fail_first:
            raise errors.APIError(429, {"error": {"message": "quota"}})
        dims = config.output_dimensionality
        return types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=[0.5] * dims) for _ in contents])


class _FakeGenai:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def test_gemini_sends_one_content_per_text_with_the_retrieval_prefixes_and_dimension() -> None:
    from google.genai import types

    fake = _FakeModels()
    embedder = ea.GeminiEmbedder(model=ea.GEMINI_MODEL, dims=8, client=_FakeGenai(fake), sleep=lambda s: None)
    vectors, tokens = embedder.embed(["카페\n창가 자리", "편집실\n하드"], input_type="document")
    (call,) = fake.calls
    # 문자열 목록을 그대로 넘기면 SDK 가 한 Content 의 여러 Part 로 합쳐 임베딩 하나를 돌려준다 — 글마다 Content 하나.
    assert all(isinstance(c, types.Content) and len(c.parts or []) == 1 for c in call["contents"])
    assert [c.parts[0].text for c in call["contents"]] == [
        "title: 카페 | text: 창가 자리",
        "title: 편집실 | text: 하드",
    ]
    assert call["config"].output_dimensionality == 8
    assert len(vectors) == 2 and all(len(v) == 8 for v in vectors)
    # Gemini SDK 응답에는 토큰 사용량이 없어 보낸 글의 보수 견적을 쓴다.
    sent = sum(len(c.parts[0].text) for c in call["contents"])
    assert tokens == ea.estimate_tokens_total([c.parts[0].text for c in call["contents"]]) and tokens >= sent
    embedder.embed(["창가에 앉았던 날"], input_type="query")
    assert fake.calls[1]["contents"][0].parts[0].text == "task: search result | query: 창가에 앉았던 날"


def test_gemini_retries_429_and_writes_estimated_usage_to_the_ledger(tmp_path: Path) -> None:
    fake = _FakeModels(fail_first=2)
    embedder = ea.GeminiEmbedder(model=ea.GEMINI_MODEL, dims=8, client=_FakeGenai(fake), sleep=lambda s: None)
    ledger = _ledger(tmp_path)
    ea.embed_rows(_plan([("query", "질의")]), embedder, ledger=ledger, out=tmp_path / "e.jsonl", stage="s5")
    assert len(fake.calls) == 3
    (row,) = ledger.rows()
    assert row["model"] == ea.GEMINI_MODEL and row["inputTokens"] > 0 and "견적" in row["note"]


# ---------------------------------------------------------------- 견적


def test_estimate_counts_tokens_per_candidate_and_checks_the_free_allowance_against_the_ledger(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.append(stage="old", call_site=ea.CALL_SITE, model="voyage-4", input_tokens=199_999_990, cached_tokens=0,
                  cache_write_tokens=0, output_tokens=0, thoughts_tokens=0)  # fmt: skip
    rows = _plan([("document", "가" * 20)])
    lite = ea.estimate(rows, ea.Candidate.parse("voyage-4-lite@512"), ledger_rows=ledger.rows())
    four = ea.estimate(rows, ea.Candidate.parse("voyage-4@512"), ledger_rows=ledger.rows())
    assert lite["tokens"] == four["tokens"] == ea.estimate_tokens_total(["가" * 20])
    assert lite["usd"] == pytest.approx(lite["tokens"] * 0.02 / 1_000_000)
    assert lite["withinFree"] is True and four["withinFree"] is False
    gemini = ea.estimate(rows, ea.Candidate.parse(f"{ea.GEMINI_MODEL}@768"), ledger_rows=[])
    assert gemini["withinFree"] is None


# ---------------------------------------------------------------- CLI


def _cli_run(tmp_path: Path) -> tuple[Path, Path]:
    plan = tmp_path / "need.jsonl"
    plan.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _plan([("query", "질의")])), "utf-8")
    run = tmp_path / "run"
    run.mkdir()
    return run, plan


def test_cli_embed_run_without_allow_paid_only_estimates_and_needs_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.setattr(ea, "make_http_client", lambda: pytest.fail("견적에서 HTTP 클라이언트를 만들었다"))
    run, plan = _cli_run(tmp_path)
    out = tmp_path / "emb.jsonl"
    code = main(["--run", str(run), "embed-run", "--plan", str(plan), "--candidate", "voyage-4@1024",
                 "--embeddings", str(out)])  # fmt: skip
    assert code == 0 and not out.exists() and not (run / "ledger.jsonl").exists()


def test_cli_embed_run_paid_needs_ledger_flags_and_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(ea, "make_http_client", lambda: pytest.fail("거부 경로에서 HTTP 클라이언트를 만들었다"))
    run, plan = _cli_run(tmp_path)
    common = ["embed-run", "--plan", str(plan), "--candidate", "voyage-4@1024", "--embeddings", str(tmp_path / "e"),
              "--allow-paid"]  # fmt: skip
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    assert main(["--run", str(run), *common]) == 2
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    flags = ["--cap-usd", "1", "--halt-usd", "0.5", "--bundle", "b1-s5"]
    assert main(["--run", str(run), *flags, *common]) == 2


def test_cli_embed_run_paid_writes_vectors_and_ledger_through_the_http_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    rec = _Recorder(lambda req, n: _voyage_ok(req, dims=256))
    monkeypatch.setattr(ea, "make_http_client", rec.client)
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    run, plan = _cli_run(tmp_path)
    out = tmp_path / "emb.jsonl"
    code = main(["--run", str(run), "--cap-usd", "1", "--halt-usd", "0.5", "--bundle", "b1-s5", "embed-run",
                 "--plan", str(plan), "--candidate", "voyage-4-lite@256", "--embeddings", str(out), "--allow-paid"])  # fmt: skip
    assert code == 0 and len(rec.requests) == 1
    assert eo.EmbeddingTable.load(out, model="voyage-4-lite", dims=256).has("query", "질의")
    assert Ledger(run / "ledger.jsonl").rows()[0]["bundle"] == "b1-s5"


def _work(tmp_path: Path) -> Path:
    """2차 형식 심기 표 하나(개발 d0·d2, 시험 d1·d3)와 분할 파일 — 시험 정답 파일은 만들지 않는다(열면 실패한다)."""
    from memory_eval import holdout

    answers = [("창가", 5), ("창가", 5), ("하드", 15), ("하드", 15)]
    plants = {
        "checkpoints": [300],
        "plants": [
            {"id": f"d{i}", "category": "detail", "primary": True, "questionForm": "direct",
             "question": f"개발 질문 {i}" if i % 2 == 0 else f"시험 질문 {i}", "plant_turns": [turn],
             "ask_checkpoints": [300], "answer_key": {"mode": "match", "bundles": [[word]], "correct": word}}
            for i, (word, turn) in enumerate(answers)
        ],
        "abstains": [],
    }  # fmt: skip
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    plants_path = tmp_path / "plants.json"
    plants_path.write_text(json.dumps(plants, ensure_ascii=False), encoding="utf-8")
    (split_dir / holdout.DEV_IDS_FILE).write_text(json.dumps(["d0", "d2"]), encoding="utf-8")
    (split_dir / holdout.TEST_IDS_FILE).write_text(json.dumps(["d1", "d3"]), encoding="utf-8")
    (split_dir / holdout.MANIFEST_FILE).write_text(
        json.dumps({"seed": 1, "plantsSha256": holdout.sha256_file(plants_path), "testKeysSha256": "x"}),
        encoding="utf-8",
    )
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "".join(json.dumps({"turn": t, "user": "u", "assistant": f"진행 {t}"}) + "\n" for t in range(1, 301)),
        encoding="utf-8",
    )
    episodes = tmp_path / "episodes.json"
    episodes.write_text(json.dumps([
        {"id": "e1", "start_turn": 1, "end_turn": 10, "title": "카페", "detail": "창가 자리", "nouns": ["창가", "카페"],
         "available_from_turn": 11},
        {"id": "e2", "start_turn": 11, "end_turn": 20, "title": "편집실", "detail": "하드 디스크", "nouns": ["편집실"],
         "available_from_turn": 21},
    ], ensure_ascii=False), encoding="utf-8")  # fmt: skip
    manifest = tmp_path / "works.json"
    manifest.write_text(json.dumps([{"work": "w", "plants": str(plants_path), "splitDir": str(split_dir),
                                     "transcript": str(transcript), "episodes": {"300": str(episodes)}}]), "utf-8")  # fmt: skip
    return manifest


def test_compare_dry_run_estimates_only_dev_texts_per_candidate(tmp_path: Path) -> None:
    from memory_eval_cli import main

    manifest = _work(tmp_path)
    run = tmp_path / "cmp"
    out = tmp_path / "report.json"
    code = main(["--run", str(run), "embed-compare", "--works", str(manifest), "--embeddings",
                 str(tmp_path / "emb.jsonl"), "--candidates", "voyage-4-lite@256,voyage-4@512", "--out", str(out), "--dry-run"])  # fmt: skip
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    est = {e["candidate"]: e for e in report["estimate"]}
    # 장면 둘 + 개발 질문 둘(시험 질문은 없다).
    assert est["voyage-4-lite@256"]["texts"] == 4 and est["voyage-4@512"]["texts"] == 4
    assert report["estimateTotal"]["usd"] == pytest.approx(sum(e["usd"] for e in report["estimate"]))
    assert report["table"] == []


def test_compare_reports_noun_vector_and_rrf_recall_for_a_fully_embedded_candidate(tmp_path: Path) -> None:
    from memory_eval_cli import main

    manifest = _work(tmp_path)
    emb = tmp_path / "emb.jsonl"
    dims = 256
    one, two = [1.0] + [0.0] * (dims - 1), [0.0, 1.0] + [0.0] * (dims - 2)
    vecs = {("document", "카페\n창가 자리"): one, ("document", "편집실\n하드 디스크"): two,
            ("query", "개발 질문 0\n진행 300"): one, ("query", "개발 질문 2\n진행 300"): two}  # fmt: skip
    emb.write_text("".join(json.dumps({"model": "voyage-4-lite", "dims": dims, "inputType": k, "sha256": eo.text_sha(t),
                                       "vector": v}) + "\n" for (k, t), v in vecs.items()), "utf-8")  # fmt: skip
    out = tmp_path / "report.json"
    code = main(["--run", str(tmp_path / "cmp"), "embed-compare", "--works", str(manifest), "--embeddings", str(emb),
                 "--candidates", "voyage-4-lite@256", "--out", str(out)])  # fmt: skip
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    methods = {(r["candidate"], r["method"]) for r in report["table"]}
    assert methods == {("-", "nouns"), ("voyage-4-lite@256", "vector"), ("voyage-4-lite@256", "rrf")}
    vector = next(r for r in report["table"] if r["method"] == "vector")
    assert vector["all"]["n"] == 2 and vector["all"]["recall3"] == 1.0
    assert set(vector["byForm"]) == {"direct"}
    assert vector["plainInjection"] == {"n": 2, "injected": 2, "meanPerTurn": 1.0}


def test_compare_runs_one_vector_and_rrf_row_per_point_of_the_hybrid_settings_grid(tmp_path: Path) -> None:
    from memory_eval_cli import main

    manifest = _work(tmp_path)
    emb = tmp_path / "emb.jsonl"
    dims = 256
    one, two = [1.0] + [0.0] * (dims - 1), [0.0, 1.0] + [0.0] * (dims - 2)
    vecs = {("document", "카페\n창가 자리"): one, ("document", "편집실\n하드 디스크"): two,
            ("query", "개발 질문 0\n진행 300"): one, ("query", "개발 질문 2\n진행 300"): two}  # fmt: skip
    emb.write_text("".join(json.dumps({"model": "voyage-4-lite", "dims": dims, "inputType": k, "sha256": eo.text_sha(t),
                                       "vector": v}) + "\n" for (k, t), v in vecs.items()), "utf-8")  # fmt: skip
    out = tmp_path / "report.json"
    code = main(["--run", str(tmp_path / "cmp"), "embed-compare", "--works", str(manifest), "--embeddings", str(emb),
                 "--candidates", "voyage-4-lite@256", "--memory-embed-recall-max-plain", "1,2",
                 "--memory-embed-recall-df-max", "none,20", "--out", str(out)])  # fmt: skip
    assert code == 0
    table = json.loads(out.read_text(encoding="utf-8"))["table"]
    rrf = [r for r in table if r["method"] == "rrf"]
    points = {(r["params"]["memory_embed_recall_max_plain"], r["params"]["memory_embed_recall_df_max"]) for r in rrf}
    assert points == {(1, None), (1, 20), (2, None), (2, 20)}
    assert len([r for r in table if r["method"] == "vector"]) == 4
    assert all(r["params"]["memory_embed_recall_rrf_k"] == 20 for r in rrf)
    two_cap = next(r for r in table if r["method"] == "vector" and r["params"]["memory_embed_recall_max_plain"] == 2)
    assert two_cap["plainInjection"] == {"n": 2, "injected": 4, "meanPerTurn": 2.0}


def test_compare_refuses_a_noun_side_other_than_production_recall_for_the_hybrid(tmp_path: Path) -> None:
    from memory_eval_cli import main

    manifest = _work(tmp_path)
    code = main(["--run", str(tmp_path / "cmp"), "embed-compare", "--works", str(manifest), "--embeddings",
                 str(tmp_path / "emb.jsonl"), "--candidates", "voyage-4-lite@256",
                 "--retriever", "memory_eval.prototype_recall:retrieve_e", "--out", str(tmp_path / "r.json")])  # fmt: skip
    assert code == 2


# 목적함수의 RRF 격자 칸만 실제 꼴로 지어낸 것 — 기준 순서와 필수 조건은 코드가 아는 이름이다.
OBJECTIVE_RRF = {
    "rrfGrid": {
        "order": ["recallAt3DevSum", "-normalTurnMeanInjected"],
        "requirements": {"nounOnlyMatchesReference": "지어낸 필수 조건 설명"},
    }
}


def _git_run(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return done.stdout.strip()


def test_compare_marks_each_rrf_point_with_the_requirement_and_the_command_selects_by_the_committed_objective(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    manifest = _work(tmp_path)
    emb = tmp_path / "emb.jsonl"
    dims = 256
    one, two = [1.0] + [0.0] * (dims - 1), [0.0, 1.0] + [0.0] * (dims - 2)
    vecs = {("document", "카페\n창가 자리"): one, ("document", "편집실\n하드 디스크"): two,
            ("query", "개발 질문 0\n진행 300"): one, ("query", "개발 질문 2\n진행 300"): two}  # fmt: skip
    emb.write_text("".join(json.dumps({"model": "voyage-4-lite", "dims": dims, "inputType": k, "sha256": eo.text_sha(t),
                                       "vector": v}) + "\n" for (k, t), v in vecs.items()), "utf-8")  # fmt: skip
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_run(repo, "init", "-q")
    objective = repo / "objective.json"
    objective.write_text(json.dumps(OBJECTIVE_RRF, ensure_ascii=False), encoding="utf-8")
    _git_run(repo, "add", "objective.json")
    _git_run(repo, "commit", "-qm", "objective")

    # 명사 단독과 어긋나는 격자 점(보통 턴 상한 2)을 흉내 — 꺼진 경로가 그 점에서만 장면 하나를 더 싣는다.
    real = eo.embedding_off_retriever

    def drifting(params: eo.HybridParams) -> Any:
        inner = real(params)

        def retrieve(*a: Any, **kw: Any) -> Any:
            ranked = inner(*a, **kw)
            return [Ranked("e1", 0.0, True), *ranked] if params.max_plain == 2 else ranked

        return retrieve

    monkeypatch.setattr(eo, "embedding_off_retriever", drifting)
    out = tmp_path / "report.json"
    code = main(["--run", str(tmp_path / "cmp"), "embed-compare", "--works", str(manifest), "--embeddings", str(emb),
                 "--candidates", "voyage-4-lite@256", "--memory-embed-recall-max-plain", "1,2",
                 "--objective", str(objective), "--out", str(out)])  # fmt: skip
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    rrf = {r["params"]["memory_embed_recall_max_plain"]: r for r in report["table"] if r["method"] == "rrf"}
    assert rrf[1]["requirements"] == {"nounOnlyMatchesReference": 1}
    assert rrf[2]["requirements"] == {"nounOnlyMatchesReference": 0}
    selection = report["selection"]
    assert selection["chosen"]["params"]["memory_embed_recall_max_plain"] == 1
    assert [r["params"]["memory_embed_recall_max_plain"] for r in selection["excluded"]] == [2]
    assert selection["objective"]["sha256"] and selection["objective"]["commit"] == _git_run(repo, "rev-parse", "HEAD")
