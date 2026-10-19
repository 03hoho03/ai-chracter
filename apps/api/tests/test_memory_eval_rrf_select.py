"""하이브리드 회상 RRF 격자에서 하나를 고르는 일이 목적함수의 `rrfGrid`(고르는 순서와 필수 조건)를 그대로 따르는지 본다.

순서는 적힌 기준을 앞에서부터 견준다(개발 절반 세 질문 형식 recall@3 합은 큰 쪽, 보통 턴 평균 주입은 작은 쪽). 필수 조건 —
임베딩을 끈 경로가 명사 단독과 행마다 같은가 — 을 어기거나 재지 않은 격자 점은 순위 밖이다. 목적함수는 실제 측정 데이터와
같은 꼴로 지어낸 것이다."""

from typing import Any

import pytest

from memory_eval import embed_compare as ec
from memory_eval import embed_offline as eo
from memory_eval import server_recall as sr
from memory_eval.recall_offline import Episode

def _objective() -> dict[str, Any]:
    return {
        "rrfGrid": {
            "order": ["recallAt3DevSum", "-normalTurnMeanInjected"],
            "requirements": {"nounOnlyMatchesReference": "지어낸 필수 조건 설명"},
        }
    }


def _row(label: str, recall: dict[str, float | None], mean: float, *, ok: int | None = 1) -> dict[str, Any]:
    by_form = {f: {"n": 4, "recall3": r} for f, r in recall.items()}
    row: dict[str, Any] = {
        "candidate": "voyage-4-lite@1024",
        "method": "rrf",
        "params": eo.HybridParams(rrf_k=int(label)).config(),
        "plainInjection": {"n": 10, "injected": int(mean * 10), "meanPerTurn": mean},
        "all": None,
        "byForm": by_form,
    }
    if ok is not None:
        row["requirements"] = {"nounOnlyMatchesReference": ok}
    return row


def test_the_objective_file_declares_recall_sum_then_smaller_normal_turn_injection_and_one_requirement() -> None:
    order, requirements = ec.rrf_grid_order(_objective())
    assert order == [("recallAt3DevSum", 1), ("normalTurnMeanInjected", -1)]
    assert requirements == ["nounOnlyMatchesReference"]


def test_recall_sum_adds_the_three_question_forms_recall_at_3() -> None:
    row = _row("60", {"direct": 0.5, "paraphrase": 0.25, "anaphora": 1.0, "other": 1.0}, 1.0)
    assert ec.rrf_criteria(row) == {"recallAt3DevSum": pytest.approx(1.75), "normalTurnMeanInjected": 1.0}
    # 정답 에피소드가 없어 recall 이 없는 형식은 0 으로 더한다 — 모든 격자 점이 같은 문항이라 순위를 바꾸지 않는다.
    assert ec.rrf_criteria(_row("60", {"direct": 0.5, "anaphora": None}, 1.0))["recallAt3DevSum"] == 0.5


def test_selection_takes_the_larger_recall_sum_before_the_smaller_injection() -> None:
    table = [
        _row("10", {"direct": 0.5, "paraphrase": 0.5, "anaphora": 0.5}, 0.2),
        _row("20", {"direct": 0.75, "paraphrase": 0.5, "anaphora": 0.5}, 2.5),
    ]
    assert ec.select_rrf(table, _objective())["chosen"]["params"]["memory_embed_recall_rrf_k"] == 20


def test_injection_is_the_second_criterion_and_decides_a_recall_tie() -> None:
    """주입 수는 recall 합이 같을 때 바로 다음 기준이다 — 그 사이에 다른 기준(대명사만 따로 등)을 끼우지 않는다."""
    table = [
        _row("10", {"direct": 1.0, "paraphrase": 0.5, "anaphora": 0.0}, 1.5),
        _row("20", {"direct": 0.5, "paraphrase": 0.5, "anaphora": 0.5}, 1.0),
    ]
    assert ec.select_rrf(table, _objective())["chosen"]["params"]["memory_embed_recall_rrf_k"] == 20


def test_selection_follows_the_order_the_file_declares() -> None:
    table = [
        _row("10", {"direct": 0.5, "paraphrase": 0.5, "anaphora": 0.5}, 0.2),
        _row("20", {"direct": 0.75, "paraphrase": 0.5, "anaphora": 0.5}, 2.5),
    ]
    flipped = _objective()
    flipped["rrfGrid"] = {**flipped["rrfGrid"], "order": ["-normalTurnMeanInjected", "recallAt3DevSum"]}
    assert ec.select_rrf(table, flipped)["chosen"]["params"]["memory_embed_recall_rrf_k"] == 10


def test_points_breaking_the_requirement_are_left_out_of_the_ranking() -> None:
    best_but_broken = _row("10", {"direct": 1.0, "paraphrase": 1.0, "anaphora": 1.0}, 0.0, ok=0)
    unchecked = _row("30", {"direct": 1.0, "paraphrase": 1.0, "anaphora": 1.0}, 0.0, ok=None)
    kept = _row("20", {"direct": 0.5, "paraphrase": 0.5, "anaphora": 0.5}, 1.0)
    selection = ec.select_rrf([best_but_broken, unchecked, kept], _objective())
    assert selection["chosen"]["params"]["memory_embed_recall_rrf_k"] == 20
    assert [r["params"]["memory_embed_recall_rrf_k"] for r in selection["excluded"]] == [10, 30]
    assert [r["params"]["memory_embed_recall_rrf_k"] for r in selection["ranked"]] == [20]


def test_only_rrf_rows_are_ranked_and_no_point_left_means_no_choice() -> None:
    vector = {**_row("10", {"direct": 1.0}, 0.0), "method": "vector"}
    broken = _row("20", {"direct": 1.0}, 0.0, ok=0)
    selection = ec.select_rrf([vector, broken], _objective())
    assert selection["chosen"] is None and selection["ranked"] == []


def test_unknown_criteria_or_requirements_in_the_objective_are_refused() -> None:
    grids: list[dict[str, Any]] = [
        {"order": ["recallAt3DevSum", "latency"], "requirements": {"nounOnlyMatchesReference": ""}},
        {"order": [], "requirements": {}},
        {"order": ["recallAt3DevSum"], "requirements": {"somethingElse": ""}},
    ]
    for grid in grids:
        with pytest.raises(SystemExit, match="목적함수"):
            ec.rrf_grid_order({"rrfGrid": grid})


# ---------------------------------------------------------------- 필수 조건: 임베딩이 꺼진 경로 = 명사 단독


def _ep(i: int, nouns: list[str]) -> Episode:
    return Episode(id=f"e{i}", start_turn=i * 10 + 1, end_turn=i * 10 + 5, title=f"장면 {i}", detail=f"본문 {i}",
                   asserted_by="user", nouns=tuple(nouns), importance=1, available_from_turn=1)  # fmt: skip


EPISODES = [_ep(0, ["우비"]), _ep(1, ["소나기"]), _ep(2, ["소나기"])] + [_ep(i, [f"채움{i}"]) for i in range(3, 10)]


def test_embedding_off_retriever_is_the_hybrid_with_an_empty_vector_side() -> None:
    """임베딩이 꺼지면(벡터 쪽이 비면) 하이브리드는 격자 점의 df 상한·k·상한과 상관없이 명사 단독 결과 그대로다."""
    kwargs: dict[str, Any] = {"user_text": "그때 우비 소나기", "previous_assistant": "진행", "current_turn": 120}
    expected = sr.retrieve_server(EPISODES, **kwargs)
    for params in (eo.DEFAULT_PARAMS, eo.HybridParams(df_max=1, max_cue=1, rrf_k=0)):
        assert eo.embedding_off_retriever(params)(EPISODES, **kwargs) == expected
