"""오프라인 하이브리드 회상이 운영 하이브리드 회상(앱의 임베딩 회상 스위치 뒤 절차)과 같은 규격인지 본다.

운영 규격: 질의 글은 이번 사용자 메시지 + 줄바꿈 + 직전 응답이다. 장면 벡터 순위는 질의와 가까운 순 앞 `vector_limit` 개 중 거리
상한 안의 것이고, 명사 쪽은 임계(`TAU`) 이상인 장면의 순위만이다. 둘을 RRF(같으면 명사 쪽 순위가 높은 쪽 먼저)로 합쳐 보통 턴
1·회상 단서 턴 3 개를 싣는다. 벡터 쪽이 비면 명사 단독 절차와 결과가 같다. 질의 글·RRF 는 하네스가 운영 함수
(`api.chat.memory_vector`)를 그대로 쓴다 — 사본을 두면 운영과 갈라진다. 기대 순서는 운영 함수로 같은 입력을 돌려 얻은 값이다."""

import inspect
import math
from collections.abc import Sequence
from typing import Any

import pytest

from api.chat import memory_recall as mr
from api.chat import memory_vector as mv
from api.core.config import Settings
from memory_eval import embed_offline as eo
from memory_eval import recall_offline as ro
from memory_eval import server_recall as sr
from memory_eval.recall_offline import Episode, Ranked

MODEL, DIMS = "voyage-test", 3
LAST = "진행자 마지막 줄"


def _ep(i: int, nouns: Sequence[str]) -> Episode:
    return Episode(
        id=f"e{i}",
        start_turn=i * 10 + 1,
        end_turn=1,
        title=f"장면 {i}",
        detail=f"본문 {i}",
        asserted_by="user",
        nouns=tuple(nouns),
        importance=1,
        available_from_turn=1,
    )


# 열 장면. 우비는 한 장면에만(임계 이상), 소나기는 두 장면에(흔해서 점수가 임계 아래) 나온다.
EPISODES = [_ep(0, ["우비"]), _ep(1, ["소나기"]), _ep(2, ["소나기"])] + [_ep(i, [f"채움{i}"]) for i in range(3, 10)]


def _unit(angle_deg: float) -> list[float]:
    a = math.radians(angle_deg)
    return [math.cos(a), math.sin(a), 0.0]


def _table(query: str, near: dict[str, float]) -> eo.EmbeddingTable:
    """질의 글 하나의 벡터는 x 축, 장면 벡터는 `near` 에 적은 각도(나머지는 직교 = 거리 1)."""
    rows: list[dict[str, Any]] = [
        {"model": MODEL, "dims": DIMS, "inputType": "query", "sha256": eo.text_sha(query), "vector": [1.0, 0.0, 0.0]}
    ]
    for e in EPISODES:
        vector = _unit(near[e.id]) if e.id in near else [0.0, 0.0, 1.0]
        rows.append(
            {"model": MODEL, "dims": DIMS, "inputType": "document", "sha256": eo.text_sha(eo.episode_text(e)),
             "vector": vector}
        )  # fmt: skip
    return eo.EmbeddingTable.from_rows(rows, model=MODEL, dims=DIMS)


def _ids(ranked: Sequence[Ranked]) -> list[str]:
    return [r.episode_id for r in ranked]


def _injected(ranked: Sequence[Ranked]) -> list[str]:
    return [r.episode_id for r in ranked if r.injected]


# ---------------------------------------------------------------- 질의 글·RRF·기본값


def test_query_text_is_this_user_message_then_a_newline_then_the_previous_reply() -> None:
    assert eo.query_text("이번 말", "직전 응답") == "이번 말\n직전 응답"
    assert eo.query_text("이번 말", "") == "이번 말"


def test_rrf_order_breaks_ties_by_the_noun_rank_first_like_production() -> None:
    assert eo.rrf_order([["y", "x"], ["x", "y"]], k=60) == ["y", "x"]
    assert eo.rrf_order([["a", "b", "c"], ["c", "a"]], k=60) == ["a", "c", "b"]
    assert eo.rrf_order([["n"], ["v"]], k=60) == ["n", "v"]
    assert eo.rrf_order([["b", "a", "c"], []], k=60) == ["b", "a", "c"]
    assert eo.rrf_order([[], ["e5", "e6"]], k=60) == ["e5", "e6"]
    # k 가 작으면 한 목록의 1위가, 크면 두 목록에 함께 든 쪽이 앞선다.
    assert eo.rrf_order([["a", "x", "b"], ["y", "z", "b"]], k=0) == ["a", "y", "b", "x", "z"]
    assert eo.rrf_order([["a", "x", "b"], ["y", "z", "b"]], k=60) == ["b", "a", "y", "x", "z"]
    assert eo.rrf_scores([["a", "b"], ["b"]], k=60) == pytest.approx({"a": 1 / 61, "b": 1 / 62 + 1 / 61})


def test_hybrid_params_default_to_the_production_defaults() -> None:
    p = eo.HybridParams()
    assert (p.rrf_k, p.max_plain, p.max_cue, p.max_distance, p.vector_limit, p.df_max) == (20, 1, 3, 2.0, 10, None)
    assert {f"memory_embed_recall_{name}" for name in eo.HybridParams.__dataclass_fields__} == set(eo.CONFIG_NAMES)


def test_hybrid_params_match_production_config_names_and_defaults() -> None:
    for name, field in eo.HybridParams.__dataclass_fields__.items():
        assert Settings.model_fields[f"memory_embed_recall_{name}"].default == field.default


def test_harness_uses_the_production_rrf_and_query_text_without_a_local_copy() -> None:
    assert eo.rrf_order is mv.rrf_order
    assert eo.query_text is mv.query_text
    own = [n for n, v in vars(eo).items() if inspect.isfunction(v) and v.__module__ == eo.__name__]
    assert [n for n in own if "rrf_order" in n or "query_text" in n] == []


def test_df_max_scoring_matches_production() -> None:
    production: Any = mr.score_episodes
    rows = sr.candidates(EPISODES)
    for user_text, previous in [("우비 소나기", ""), ("그때 소나기", "우비 이야기"), ("소나기", "")]:
        query = sr.recall_query(rows, user_text=user_text, previous_assistant=previous)
        expected = production(rows, query, current_turn=100, df_max=1)
        got = sr.score_server(EPISODES, user_text=user_text, previous_assistant=previous, current_turn=100, df_max=1)
        assert got == expected


# ---------------------------------------------------------------- 벡터 순위


def test_nearest_takes_the_vector_limit_first_then_drops_rows_beyond_the_distance_cap() -> None:
    query = eo.query_text("우비", LAST)
    table = _table(query, {"e5": 10.0, "e6": 10.0, "e4": 50.0, "e7": 80.0})
    near = eo.nearest(table, EPISODES, query, limit=3, max_distance=2.0)
    # 거리가 같으면 id 순, 앞 3 개만.
    assert [eid for eid, _ in near] == ["e5", "e6", "e4"]
    assert near[0][1] == pytest.approx(1 - math.cos(math.radians(10.0)))
    # 거리 상한은 LIMIT 뒤에 건다 — e7(거리 약 0.83)은 상한 0.9 안이지만 LIMIT 밖이라 돌아오지 않는다.
    cut = eo.nearest(table, EPISODES, query, limit=3, max_distance=0.9)
    assert [eid for eid, _ in cut] == ["e5", "e6", "e4"]
    assert [eid for eid, _ in eo.nearest(table, EPISODES, query, limit=4, max_distance=0.9)] == ["e5", "e6", "e4", "e7"]
    assert [eid for eid, _ in eo.nearest(table, EPISODES, query, limit=10, max_distance=0.1)] == ["e5", "e6"]


def test_vector_side_embeds_the_user_message_joined_with_the_previous_reply() -> None:
    query = eo.query_text("우비 소나기", LAST)
    table = _table(query, {"e5": 10.0})
    ranked = eo.rrf_retriever(table)(EPISODES, user_text="우비 소나기", previous_assistant=LAST, current_turn=100)
    assert "e5" in _ids(ranked)
    with pytest.raises(SystemExit, match="벡터"):
        eo.rrf_retriever(table)(EPISODES, user_text="우비 소나기", previous_assistant="다른 응답", current_turn=100)


# ---------------------------------------------------------------- 하이브리드


def test_noun_side_carries_only_episodes_at_or_above_the_threshold() -> None:
    query = eo.query_text("우비 소나기", LAST)
    table = _table(query, {"e5": 10.0})
    ranked = eo.rrf_retriever(table, eo.HybridParams(max_distance=0.5))(
        EPISODES, user_text="우비 소나기", previous_assistant=LAST, current_turn=100
    )
    # 소나기 장면(e1·e2)은 명사가 겹치지만 임계 아래라 RRF 에 들지 않는다.
    assert _ids(ranked) == eo.rrf_order([["e0"], ["e5"]], k=20) == ["e0", "e5"]
    assert {r.episode_id: r.score for r in ranked} == pytest.approx(eo.rrf_scores([["e0"], ["e5"]], k=20))


def test_plain_turn_injects_one_and_a_recall_cue_turn_three() -> None:
    plain_query = eo.query_text("우비 소나기", LAST)
    near = {"e5": 10.0, "e6": 20.0, "e7": 30.0}
    plain = eo.rrf_retriever(_table(plain_query, near), eo.HybridParams(max_distance=0.5))(
        EPISODES, user_text="우비 소나기", previous_assistant=LAST, current_turn=100
    )
    assert _injected(plain) == ["e0"]
    assert _ids(plain) == ["e0", "e5", "e6", "e7"]
    cue_text = "그때 우비 기억나?"
    assert mr.recall_cue(cue_text)
    cue = eo.rrf_retriever(_table(eo.query_text(cue_text, LAST), near), eo.HybridParams(max_distance=0.5))(
        EPISODES, user_text=cue_text, previous_assistant=LAST, current_turn=100
    )
    assert _injected(cue) == ["e0", "e5", "e6"]
    wide = eo.rrf_retriever(_table(plain_query, near), eo.HybridParams(max_distance=0.5, max_plain=2))(
        EPISODES, user_text="우비 소나기", previous_assistant=LAST, current_turn=100
    )
    assert _injected(wide) == ["e0", "e5"]


@pytest.mark.parametrize(
    "params", [eo.HybridParams(max_distance=0.01), eo.HybridParams(vector_limit=0)], ids=["distance", "limit"]
)
def test_empty_vector_side_gives_exactly_the_noun_only_result(params: eo.HybridParams) -> None:
    query = eo.query_text("우비 소나기", LAST)
    table = _table(query, {"e5": 30.0})
    kwargs: dict[str, Any] = {"user_text": "우비 소나기", "previous_assistant": LAST, "current_turn": 100}
    hybrid = eo.rrf_retriever(table, params)(EPISODES, **kwargs)
    nouns = sr.retrieve_server(EPISODES, **kwargs)
    assert hybrid == nouns
    # 명사 단독은 임계 아래 장면도 순위에 남긴다(recall@10 용) — 하이브리드의 명사 쪽과 다른 목록이다.
    assert _ids(nouns) == ["e0", "e1", "e2"] and _injected(nouns) == ["e0"]


def test_too_few_episodes_gives_the_noun_only_result_without_reading_vectors() -> None:
    few = EPISODES[: mr.MIN_EPISODES - 1]
    empty = eo.EmbeddingTable(model=MODEL, dims=DIMS, vectors={})
    kwargs: dict[str, Any] = {"user_text": "우비", "previous_assistant": LAST, "current_turn": 100}
    assert eo.rrf_retriever(empty)(few, **kwargs) == sr.retrieve_server(few, **kwargs) == []


def test_df_max_drops_nouns_in_more_episodes_than_the_cap_only_on_the_hybrid_path() -> None:
    query = eo.query_text("소나기", LAST)
    table = _table(query, {"e5": 10.0})
    kwargs: dict[str, Any] = {"user_text": "소나기", "previous_assistant": LAST, "current_turn": 100}
    capped = eo.rrf_retriever(table, eo.HybridParams(max_distance=0.5, df_max=1))(EPISODES, **kwargs)
    assert _ids(capped) == ["e5"]
    scored = sr.score_server(EPISODES, user_text="소나기", previous_assistant=LAST, current_turn=100, df_max=1)
    assert scored == []
    assert [r.id for r in sr.score_server(EPISODES, **kwargs)] == ["e1", "e2"] + [f"e{i}" for i in [0, *range(3, 10)]]


def test_df_max_emptying_the_user_side_does_not_fall_through_to_the_reply_side() -> None:
    # 시간 단서 + 사용자 쪽 명사가 전부 df 상한에 걸리면 운영은 회상 없음이다(직전 응답 쪽으로 넘어가지 않는다).
    scored = sr.score_server(
        EPISODES, user_text="그때 소나기", previous_assistant="우비 이야기", current_turn=100, df_max=1
    )
    assert scored == []
    assert [r.id for r in sr.score_server(EPISODES, user_text="그때 소나기", previous_assistant="우비 이야기",
                                          current_turn=100)][:2] == ["e1", "e2"]  # fmt: skip


def test_vector_only_applies_the_same_caps_and_limits() -> None:
    query = eo.query_text("우비 소나기", LAST)
    table = _table(query, {"e5": 10.0, "e6": 20.0})
    ranked = eo.vector_retriever(table, eo.HybridParams(max_distance=0.5))(
        EPISODES, user_text="우비 소나기", previous_assistant=LAST, current_turn=100
    )
    assert _ids(ranked) == ["e5", "e6"] and _injected(ranked) == ["e5"]


# ---------------------------------------------------------------- 지표·맥락 턴


def test_plain_turn_injection_counts_only_turns_without_a_recall_cue() -> None:
    rows = [
        {"user_text": "우비 소나기", "injected": ["e0"]},
        {"user_text": "아무 말", "injected": []},
        {"user_text": "그때 우비 기억나?", "injected": ["e0", "e5", "e6"]},
    ]
    assert ro.plain_injection(rows) == {"n": 2, "injected": 1, "meanPerTurn": 0.5}
    assert ro.plain_injection([]) == {"n": 0, "injected": 0, "meanPerTurn": None}


def test_fusion_queries_refuse_the_context_line_proxy_and_use_the_measured_context_reply() -> None:
    queries = [
        ro.RecallQuery("a1", 300, "context", "anaphora", "dev", "그때 그 자리", LAST, "checkpoint_line"),
        ro.RecallQuery("a1", 300, "question", "anaphora", "dev", "그거 뭐였지?", "그 자리 응답", "context_response"),
    ]
    assert ro.fusion_query_texts(queries) == ["그때 그 자리\n" + LAST, "그거 뭐였지?\n그 자리 응답"]
    proxy = ro.RecallQuery("a1", 300, "question", "anaphora", "dev", "그거 뭐였지?", "그때 그 자리", "context_proxy")
    with pytest.raises(SystemExit, match="맥락 턴 응답"):
        ro.fusion_query_texts([proxy])
