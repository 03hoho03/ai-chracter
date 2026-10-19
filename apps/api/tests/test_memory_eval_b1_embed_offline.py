"""임베딩 오프라인 회상 — 미리 계산한 벡터 파일로 벡터 단독·RRF 순위를 내고, 기존 recall@3·@10 집계가 그대로 읽는다. 벡터가
빠진 글이 있으면 조용히 명사 단독으로 떨어지지 않고 거부하며, 빠진 글 목록(벡터를 계산할 입력)은 개발 보기의 질의만 담는다."""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_eval import embed_offline as eo
from memory_eval.recall_offline import Episode, evaluate_query

MODEL, DIMS = "voyage-test", 3


def _ep(eid: str, title: str, detail: str) -> Episode:
    return Episode(id=eid, start_turn=1, end_turn=10, title=title, detail=detail, asserted_by="user")


EPISODES = [_ep("e1", "카페", "창가 자리"), _ep("e2", "편집실", "하드 디스크"), _ep("e3", "정류장", "우산")]


def _table(vectors: dict[tuple[str, str], list[float]]) -> eo.EmbeddingTable:
    rows = [
        {"model": MODEL, "dims": DIMS, "inputType": kind, "sha256": eo.text_sha(text), "vector": vec}
        for (kind, text), vec in vectors.items()
    ]
    return eo.EmbeddingTable.from_rows(rows, model=MODEL, dims=DIMS)


def _doc_vectors() -> dict[tuple[str, str], list[float]]:
    return {
        ("document", eo.episode_text(EPISODES[0])): [1.0, 0.0, 0.0],
        ("document", eo.episode_text(EPISODES[1])): [0.0, 1.0, 0.0],
        ("document", eo.episode_text(EPISODES[2])): [0.6, 0.0, 0.8],
    }


def test_vector_retriever_ranks_by_cosine_and_injects_one_on_a_plain_turn() -> None:
    query = eo.query_text("창가에 앉았던 날", "직전 응답")
    table = _table({**_doc_vectors(), ("query", query): [0.9, 0.1, 0.3]})
    retrieve = eo.vector_retriever(table)
    ranked = retrieve(EPISODES, user_text="창가에 앉았던 날", previous_assistant="직전 응답", current_turn=11)
    assert [r.episode_id for r in ranked] == ["e1", "e3", "e2"]
    # 회상 단서가 없는 보통 턴 — 운영 상한대로 하나만 싣는다.
    assert [r.injected for r in ranked] == [True, False, False]
    assert ranked[0].score > ranked[1].score > ranked[2].score
    result = evaluate_query(ranked, gold=["e2"])
    assert result["goldRank"] == 3 and result["recall3"] is False and result["recall10"] is True


def test_missing_vector_is_refused_rather_than_falling_back_to_nouns() -> None:
    table = _table(_doc_vectors())
    with pytest.raises(SystemExit, match="벡터"):
        eo.vector_retriever(table)(EPISODES, user_text="없는 질의", previous_assistant="", current_turn=11)


def test_table_refuses_a_vector_of_the_wrong_length_and_keeps_only_the_chosen_model_and_dims() -> None:
    sha = eo.text_sha("글")
    with pytest.raises(SystemExit, match="차원"):
        eo.EmbeddingTable.from_rows(
            [{"model": MODEL, "dims": DIMS, "inputType": "query", "sha256": sha, "vector": [1.0, 0.0]}],
            model=MODEL,
            dims=DIMS,
        )
    rows = [
        {"model": MODEL, "dims": DIMS, "inputType": "query", "sha256": sha, "vector": [1.0, 0.0, 0.0]},
        {"model": "other", "dims": DIMS, "inputType": "query", "sha256": sha, "vector": [0.0, 1.0, 0.0]},
        {"model": MODEL, "dims": 2, "inputType": "query", "sha256": sha, "vector": [0.0, 1.0]},
    ]
    table = eo.EmbeddingTable.from_rows(rows, model=MODEL, dims=DIMS)
    assert table.vector("query", "글") == [1.0, 0.0, 0.0]


def test_missing_texts_lists_each_absent_episode_and_query_once(tmp_path: Path) -> None:
    table = _table({("document", eo.episode_text(EPISODES[0])): [1.0, 0.0, 0.0]})
    rows = eo.missing_texts(table, EPISODES, ["질의 하나", "질의 하나", "질의 둘"])
    assert {(r["inputType"], r["text"]) for r in rows} == {
        ("document", eo.episode_text(EPISODES[1])),
        ("document", eo.episode_text(EPISODES[2])),
        ("query", "질의 하나"),
        ("query", "질의 둘"),
    }
    assert len(rows) == 4
    assert all(r["sha256"] == eo.text_sha(r["text"]) for r in rows)


# ---------------------------------------------------------------- CLI: 개발 보기만, 시험 id 거부


def _v2_run(tmp_path: Path, *, anaphora_line: str | None = None) -> tuple[Path, Path, Path, Path]:
    from memory_eval import holdout

    plants: dict[str, Any] = {
        "checkpoints": [300],
        "plants": [
            {
                "id": f"d{i}",
                "category": "detail",
                "primary": True,
                "questionForm": "direct",
                "question": f"개발 질문 {i}" if i % 2 == 0 else f"시험 질문 {i}",
                "plant_turns": [5],
                "ask_checkpoints": [300],
                "answer_key": {"mode": "match", "bundles": [["창가"]], "correct": "창가"},
            }
            for i in range(4)
        ],
        "abstains": [],
    }
    if anaphora_line:
        plants["plants"][0] |= {"questionForm": "anaphora", "contextTurn": {"userLine": anaphora_line}}
    run = tmp_path / "run"
    split_dir = run / "split"
    split_dir.mkdir(parents=True)
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
        "\n".join(json.dumps({"turn": t, "user": "u", "assistant": f"진행 {t}"}) for t in range(1, 301)) + "\n",
        encoding="utf-8",
    )
    episodes = tmp_path / "episodes.json"
    episodes.write_text(
        json.dumps([{"id": "e1", "start_turn": 1, "end_turn": 10, "title": "카페", "detail": "창가 자리"}]),
        encoding="utf-8",
    )
    return run, plants_path, transcript, episodes


def test_embed_plan_writes_only_dev_queries_and_never_opens_the_test_keys(tmp_path: Path) -> None:
    from memory_eval_cli import main

    run, plants, transcript, episodes = _v2_run(tmp_path)
    out = tmp_path / "need.jsonl"
    code = main(
        ["--run", str(run), "embed-plan", "--plants", str(plants), "--transcript", str(transcript),
         "--episodes", str(episodes), "--checkpoints", "300", "--embed-model", MODEL, "--embed-dims", str(DIMS),
         "--out", str(out)]
    )  # fmt: skip
    assert code == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    texts = {r["text"] for r in rows if r["inputType"] == "query"}
    # 질의 글은 운영과 같이 이번 사용자 메시지 + 줄바꿈 + 직전 응답(체크포인트 마지막 진행자 줄)이다.
    assert texts == {"개발 질문 0\n진행 300", "개발 질문 2\n진행 300"}
    assert not any("시험" in r["text"] for r in rows)
    assert {r["text"] for r in rows if r["inputType"] == "document"} == {"카페\n창가 자리"}


def test_embed_plan_test_half_needs_the_seal(tmp_path: Path) -> None:
    from memory_eval_cli import main

    run, plants, transcript, episodes = _v2_run(tmp_path)
    out = tmp_path / "x.jsonl"
    code = main(
        ["--run", str(run), "embed-plan", "--plants", str(plants), "--transcript", str(transcript),
         "--episodes", str(episodes), "--splits", "test", "--embed-model", MODEL, "--embed-dims", str(DIMS),
         "--out", str(out)]
    )  # fmt: skip
    assert code == 2 and not out.exists()


def test_recall_offline_with_vector_fusion_reports_recall_from_the_embedding_file(tmp_path: Path) -> None:
    from memory_eval_cli import main

    run, plants, transcript, episodes = _v2_run(tmp_path)
    emb = tmp_path / "emb.jsonl"
    lines = [
        {"model": MODEL, "dims": DIMS, "inputType": "document", "sha256": eo.text_sha("카페\n창가 자리"),
         "vector": [1.0, 0.0, 0.0]},
        {"model": MODEL, "dims": DIMS, "inputType": "query", "sha256": eo.text_sha("개발 질문 0\n진행 300"),
         "vector": [1.0, 0.0, 0.0]},
        {"model": MODEL, "dims": DIMS, "inputType": "query", "sha256": eo.text_sha("개발 질문 2\n진행 300"),
         "vector": [0.0, 1.0, 0.0]},
    ]  # fmt: skip
    emb.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    out = tmp_path / "recall.json"
    code = main(
        ["--run", str(run), "recall-offline", "--plants", str(plants), "--transcript", str(transcript),
         "--episodes", str(episodes), "--checkpoints", "300", "--fusion", "vector", "--embeddings", str(emb),
         "--embed-model", MODEL, "--embed-dims", str(DIMS), "--out", str(out)]
    )  # fmt: skip
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert {r["item_id"] for r in report["rows"]} == {"d0", "d2"}
    assert report["fusion"] == {
        "method": "vector", "model": MODEL, "dims": DIMS,
        "params": {"memory_embed_recall_rrf_k": 20, "memory_embed_recall_max_plain": 1,
                   "memory_embed_recall_max_cue": 3, "memory_embed_recall_max_distance": 2.0,
                   "memory_embed_recall_vector_limit": 10, "memory_embed_recall_df_max": None},
    }  # fmt: skip
    assert report["plainInjection"] == {"n": 2, "injected": 2, "meanPerTurn": 1.0}
    assert all(r["top10"] == ["e1"] for r in report["rows"])
    assert all(r["recall3"] is True for r in report["rows"])


def test_embed_plan_and_fusion_refuse_the_context_line_proxy_without_measured_context_replies(tmp_path: Path) -> None:
    from memory_eval_cli import main

    run, plants, transcript, episodes = _v2_run(tmp_path, anaphora_line="그때 그 자리 말이야")
    common = ["--plants", str(plants), "--transcript", str(transcript), "--episodes", str(episodes),
              "--checkpoints", "300", "--embed-model", MODEL, "--embed-dims", str(DIMS)]  # fmt: skip
    need = tmp_path / "need.jsonl"
    assert main(["--run", str(run), "embed-plan", *common, "--out", str(need)]) == 2
    assert not need.exists()


def test_embed_plan_covers_the_context_turn_and_the_question_after_the_measured_context_reply(tmp_path: Path) -> None:
    from memory_eval_cli import main

    run, plants, transcript, episodes = _v2_run(tmp_path, anaphora_line="그때 그 자리 말이야")
    replies = tmp_path / "replies.json"
    replies.write_text(json.dumps([{"item": "d0", "checkpoint": 300, "reply": "창가 자리 말이구나"}]), "utf-8")
    common = ["--plants", str(plants), "--transcript", str(transcript), "--episodes", str(episodes),
              "--checkpoints", "300", "--embed-model", MODEL, "--embed-dims", str(DIMS),
              "--context-responses", str(replies)]  # fmt: skip
    need = tmp_path / "need.jsonl"
    assert main(["--run", str(run), "embed-plan", *common, "--out", str(need)]) == 0
    rows = [json.loads(line) for line in need.read_text(encoding="utf-8").splitlines()]
    queries = {r["text"] for r in rows if r["inputType"] == "query"}
    # 맥락 턴(사용자 = 맥락 턴 문장, 직전 = 체크포인트 마지막 줄)과 질문 턴(직전 = 잰 맥락 턴 응답).
    assert "그때 그 자리 말이야\n진행 300" in queries
    assert "개발 질문 0\n창가 자리 말이구나" in queries
    assert not any(q.endswith("\n그때 그 자리 말이야") for q in queries)
    emb = tmp_path / "emb.jsonl"
    vectors = [
        {"model": MODEL, "dims": DIMS, "inputType": r["inputType"], "sha256": r["sha256"], "vector": [1.0, 0.0, 0.0]}
        for r in rows
    ]
    emb.write_text("".join(json.dumps(v) + "\n" for v in vectors), encoding="utf-8")
    out = tmp_path / "recall.json"
    code = main(
        ["--run", str(run), "recall-offline", *common, "--fusion", "vector", "--embeddings", str(emb),
         "--out", str(out)]
    )  # fmt: skip
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert ("d0", "context") in {(r["item_id"], r["kind"]) for r in report["rows"]}


def test_recall_offline_takes_the_hybrid_settings_under_the_production_config_names(tmp_path: Path) -> None:
    from memory_eval_cli import main

    run, plants, transcript, episodes = _v2_run(tmp_path)
    emb = tmp_path / "emb.jsonl"
    texts = [("document", "카페\n창가 자리"), ("query", "개발 질문 0\n진행 300"), ("query", "개발 질문 2\n진행 300")]
    emb.write_text("".join(json.dumps({"model": MODEL, "dims": DIMS, "inputType": k, "sha256": eo.text_sha(t),
                                       "vector": [1.0, 0.0, 0.0]}) + "\n" for k, t in texts), "utf-8")  # fmt: skip
    out = tmp_path / "recall.json"
    code = main(
        ["--run", str(run), "recall-offline", "--plants", str(plants), "--transcript", str(transcript),
         "--episodes", str(episodes), "--checkpoints", "300", "--fusion", "rrf", "--embeddings", str(emb),
         "--embed-model", MODEL, "--embed-dims", str(DIMS), "--memory-embed-recall-rrf-k", "10",
         "--memory-embed-recall-max-plain", "2", "--memory-embed-recall-max-cue", "4",
         "--memory-embed-recall-max-distance", "0.5", "--memory-embed-recall-vector-limit", "5",
         "--memory-embed-recall-df-max", "3", "--out", str(out)]
    )  # fmt: skip
    assert code == 0
    params = json.loads(out.read_text(encoding="utf-8"))["fusion"]["params"]
    assert params == {"memory_embed_recall_rrf_k": 10, "memory_embed_recall_max_plain": 2,
                      "memory_embed_recall_max_cue": 4, "memory_embed_recall_max_distance": 0.5,
                      "memory_embed_recall_vector_limit": 5, "memory_embed_recall_df_max": 3}  # fmt: skip
