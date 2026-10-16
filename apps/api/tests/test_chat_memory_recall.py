"""매 턴 회상 — 방의 장면 기억에서 이번 턴과 이어질 장면을 골라 생성 프롬프트의 회상 섹션에 싣는다(LLM 호출 없음).

규칙(결과를 보기 전에 적었다):
- 스위치(`memory_episodes_recall`)와 생성 윈도우가 둘 다 켜져 있고 방에 요약 커서가 있을 때만 장면을 읽는다. 아니면
  장면 SELECT 도 없고 프롬프트는 스위치가 생기기 전과 바이트까지 같다.
- 질의는 키워드북과 같은 스캔 글(이번 사용자 메시지, 직전 AI 응답)에서 형태소기 없이 조사 하나를 뗀 토큰이다. 사용자
  쪽은 방 장면에 한 번이라도 나온 토큰만 남긴다. 그 집합이 비지 않으면 사용자 쪽으로 찾고, 비었고 시간 단서가 있으면 직전
  AI 응답 토큰(가장 최근 스냅샷 두 개의 장면 명사를 뺀 것)으로 찾는다. 그 밖은 회상 없음.
- 방 장면의 20% 넘게 나오는 명사는 질의에서 빠진다. 임계용 점수는 드문 명사 하나를 1 로 둔 절대 척도(상한 1)이고 순위는
  상한 없는 원점수다. 주입은 임계 0.60 이상이 회상 단서 턴에 3개, 그 밖의 턴에 1개. 장면 5개 미만이면 회상하지 않는다.
- 섹션은 대화 기록 뒤(캐시 블록 셋째)에 있고 줄은 일어난 순서다. 인물이 말한 장면은 꼬리표로 표시한다.
- 턴 기록(`chat_turns.memory_recall`)에 실은 장면의 id·점수·순위·글자 수·질의 쪽을 남기고, 리플레이는 그 id 로 줄을 다시
  렌더한다. 장면 읽기가 실패하면 회상 없이 턴을 계속한다.
- 임베딩 회상 스위치(`memory_embed_recall`)가 켜져 있으면 턴마다 질의 임베딩을 한 번(이번 사용자 메시지 + 직전 응답, 시간
  상한 안) 받아 방의 장면 임베딩(커서 이하, 지금 모델·차원만)과 거리 순위를 내고, 명사 순위(임계 이상)와 RRF
  `Σ 1/(k + 순위)` 로 합쳐 같은 상한만큼 싣는다. 벡터 쪽이 비면(스위치 꺼짐·시간 초과·호출 실패·임베딩 행 없음·벡터 읽기
  실패) 명사 단독과 프롬프트·턴 기록이 바이트까지 같다. 질의 임베딩의 사용량·지연·결과는 턴 기록의 호출 목록에 남고,
  리플레이는 기록 id 로 다시 렌더해 질의 임베딩을 다시 부르지 않는다.

순수 함수의 기대값은 평가 하네스의 시제품 구현이 낸 기준 벡터(`fixtures/memory_recall_vectors.json`)다 — 운영 코드는
하네스를 import 하지 않으므로, 두 구현이 갈리면 평가 수치가 운영 동작을 말하지 못한다."""

import asyncio
import json
import logging
import math
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import memory_recall
from api.chat.memory_nouns import episode_nouns
from api.chat.memory_recall import (
    RecallCandidate,
    RecallQuery,
    query_tokens,
    recall_cue,
    recall_line,
    score_episodes,
    select_injected,
)
from api.chat.memory_window import CurrentSummary, load_current_summary
from api.chat.prompt_builder import (
    MemorySummaryResult,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat.router import _resolve_starting_setup
from api.chat.turn_prompt import GenerationPrompt, InjectedTurnState, build_room_prompt
from api.core.config import settings
from api.db.models import (
    ChatMemoryEpisode,
    ChatMemoryFact,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
)
from api.db.models.chat import EPISODE_DETAIL_MAX, EPISODE_TITLE_MAX, ChatTurn
from api.llm.client import LLMCallContext, LLMClient, SegmentedPrompt, collect_usage
from api.llm.dependencies import get_embedding_client
from api.llm.voyage import VoyageEmbeddingClient
from api.main import app
from factories import (
    PRODUCTION_ENV_NAMES,
    Room,
    VoyageStub,
    _clear_llm_override,
    _count_queries,
    _make_memory_embedding,
    _make_memory_episode,
    _make_memory_fact,
    _open_room,
    _open_transaction_probe,
    _override_llm_client,
    _parse_sse_events,
    load_production_env,
)
from replay.logs import ReplayRefusedError
from replay.state import turn_recall_lines

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "memory_recall_vectors.json").read_text(encoding="utf-8"))
TOLERANCE = 1e-6
HEADER = "[지난 기억 — 참고]"
NO_OVERLAP_MARK = "(겹침 없는 행)"


# --- 기준 벡터 -----------------------------------------------------------------------------


def _candidates(rows: list[dict[str, Any]]) -> list[RecallCandidate]:
    return [
        RecallCandidate(
            id=row["id"],
            nouns=frozenset(row["nouns"]),
            importance=row["importance"],
            end_turn=row["endTurn"],
            snapshot=row["snapshot"],
        )
        for row in rows
    ]


def _assert_ranking(actual: list[memory_recall.ScoredEpisode], expected: list[dict[str, Any]]) -> None:
    """겹친 장면은 순서·점수·겹친 명사까지 같아야 하고, 겹침 없는 장면이 뒤에 있는지는 표지로 본다."""
    overlapping = [row for row in actual if row.overlap]
    want = [row for row in expected if row["id"] != NO_OVERLAP_MARK]
    assert [row.id for row in overlapping] == [row["id"] for row in want]
    for got, row in zip(overlapping, want, strict=True):
        assert sorted(got.overlap) == row["overlap"]
        assert math.isclose(got.s, row["s"], abs_tol=TOLERANCE), (got.id, got.s, row["s"])
        assert math.isclose(got.r, row["r"], abs_tol=TOLERANCE), (got.id, got.r, row["r"])
    assert any(not row.overlap for row in actual) == (len(want) != len(expected))


@pytest.mark.parametrize("case", VECTORS["queries"], ids=lambda case: case["userText"])
def test_query_tokens_match_the_reference_vectors(case: dict[str, Any]) -> None:
    query = query_tokens(
        case["userText"],
        case["previousAssistant"],
        episode_nouns=frozenset(case["episodeNounPool"]),
        names=case["names"],
    )
    assert sorted(query.user) == case["user"]
    assert sorted(query.assistant) == case["assistant"]
    assert query.time_cue == case["timeCue"]
    assert recall_cue(case["userText"]) == case["recallCue"]


@pytest.mark.parametrize("case", VECTORS["scoreCases"], ids=lambda case: case["name"])
def test_scores_match_the_reference_vectors(case: dict[str, Any]) -> None:
    query = RecallQuery(
        user=frozenset(case["query"]["user"]),
        assistant=frozenset(case["query"]["assistant"]),
        time_cue=case["query"]["timeCue"],
    )
    scored = score_episodes(_candidates(case["episodes"]), query, current_turn=case["currentTurn"])
    _assert_ranking(scored, case["expected"]["ranking"])
    assert [row.id for row in select_injected(scored, recall_cue=case["recallCue"])] == case["expected"]["injected"]
    assert bool(scored) == case["recall"]


# 기준 벡터 생성기가 쓴 장면 여덟 개 — 벡터 파일에는 결과만 있다. (id, 제목, 본문, 모델 명사, 중요도, 끝 턴, 스냅샷 순번)
_E2E_EPISODES: list[tuple[str, str, str, list[str], int, int, int]] = [
    (
        "e1",
        "밀알당에 간 날",
        "태민이랑 밀알당에서 소금빵을 먹었다. 내기에서 지면 닭강정을 사 준다고 했다.",
        ["밀알당", "소금빵", "닭강정"],
        4,
        12,
        1,
    ),
    (
        "e2",
        "동아리방 회의",
        "도희 선배가 동아리방에서 촬영 일정을 정했다. 정류장 장면은 토요일 오전.",
        ["동아리방", "촬영 일정", "정류장"],
        3,
        22,
        1,
    ),
    (
        "e3",
        "편의점",
        "도희가 편의점에서 우비를 사서 건넸다. 렌즈 케이스는 가방 앞주머니에 넣었다.",
        ["편의점", "우비", "렌즈 케이스", "가방"],
        3,
        35,
        2,
    ),
    (
        "e4",
        "정류장 리허설",
        "도희와 정류장에서 리허설을 했다. 빵 봉지를 들고 버스를 기다렸다.",
        ["정류장", "리허설", "빵", "버스"],
        2,
        48,
        3,
    ),
    ("e5", "옥상", "도희 선배와 옥상 정원에서 대본을 맞췄다.", ["옥상 정원", "대본"], 3, 60, 4),
    ("e6", "편집실", "세빈이 편집실 선풍기를 고쳤다. 도희 선배가 컷을 골랐다.", ["편집실", "선풍기", "컷"], 2, 75, 5),
    ("e7", "탁구장", "태민이 탁구장에서 잠수를 탔다.", ["탁구장", "잠수"], 3, 90, 6),
    (
        "e8",
        "단체 사진",
        "단체 사진을 찍고 도희 선배가 월미도에 다 같이 가자고 했다.",
        ["단체 사진", "월미도"],
        5,
        110,
        7,
    ),
]


@pytest.mark.parametrize("case", VECTORS["endToEnd"], ids=lambda case: case["userText"])
def test_recall_from_text_matches_the_reference_vectors(case: dict[str, Any]) -> None:
    """원문(사용자 메시지·직전 응답)부터 토큰·점수·순위·주입까지. 장면 명사는 쓰기 시점 규칙(`episode_nouns`)으로 만든다."""
    rows = [
        RecallCandidate(
            id=id_, nouns=frozenset(episode_nouns(nouns, title, detail)), importance=imp, end_turn=end, snapshot=snap
        )
        for id_, title, detail, nouns, imp, end, snap in _E2E_EPISODES
    ]
    pool = frozenset(noun for row in rows for noun in row.nouns)
    used = case.get("episodesUsed")
    if used is not None:
        rows = [row for row in rows if row.id in used]
    query = query_tokens(case["userText"], case["previousAssistant"], episode_nouns=pool, names=case.get("names", []))
    if "queryTokens" in case:
        assert sorted(query.user) == case["queryTokens"]["user"]
        assert sorted(query.assistant) == case["queryTokens"]["assistant"]
        assert (query.time_cue, recall_cue(case["userText"])) == (case["timeCue"], case["recallCue"])
    scored = score_episodes(rows, query, current_turn=case["currentTurn"])
    overlapping = [row for row in scored if row.overlap]
    assert [row.id for row in overlapping] == [row["id"] for row in case["expected"]["ranking"]]
    _assert_ranking(overlapping, case["expected"]["ranking"])
    injected = select_injected(scored, recall_cue=recall_cue(case["userText"]))
    assert [row.id for row in injected] == case["expected"]["injected"]
    assert bool(scored) == case["expected"]["recall"]


# --- 점수 함수의 경계 --------------------------------------------------------------------------


def _filler(count: int, *, start: int = 0) -> list[RecallCandidate]:
    return [
        RecallCandidate(id=f"f{start + i}", nouns=frozenset(), importance=1, end_turn=10, snapshot=1)
        for i in range(count)
    ]


def _sharing(noun: str, count: int, *, prefix: str) -> list[RecallCandidate]:
    return [
        RecallCandidate(id=f"{prefix}{i}", nouns=frozenset({noun}), importance=1, end_turn=20 + i, snapshot=2)
        for i in range(count)
    ]


@pytest.mark.parametrize(
    ("df", "injected"),
    [
        # N = 20, 중요도 1, 시간 단서(최근성 끔): s = 0.7·w(df)/w_rare. df 2 → 0.615, df 3 → 0.555(임계 0.60 아래).
        pytest.param(2, True, id="just-above-threshold"),
        pytest.param(3, False, id="just-below-threshold"),
    ],
)
def test_threshold_decides_injection_on_both_sides(df: int, injected: bool) -> None:
    rows = [*_sharing("등대", df, prefix="g"), *_filler(20 - df)]
    query = RecallQuery(user=frozenset({"등대"}), assistant=frozenset(), time_cue=True)
    scored = score_episodes(rows, query, current_turn=100)
    top = scored[0]
    assert top.overlap == {"등대"}
    assert (top.s >= memory_recall.TAU) is injected
    assert bool(select_injected(scored, recall_cue=True)) is injected


@pytest.mark.parametrize(
    ("df", "kept"),
    [
        # N = 20 에서 흔한 명사 비율 0.2 = df 4. 같으면 남고, 넘으면 질의에서 빠져 회상 자체가 없다.
        pytest.param(4, True, id="at-common-ratio"),
        pytest.param(5, False, id="over-common-ratio"),
    ],
)
def test_common_noun_ratio_boundary(df: int, kept: bool) -> None:
    rows = [*_sharing("촬영", df, prefix="c"), *_filler(20 - df)]
    query = RecallQuery(user=frozenset({"촬영"}), assistant=frozenset(), time_cue=False)
    scored = score_episodes(rows, query, current_turn=100)
    assert bool(scored) is kept
    assert any(row.overlap for row in scored) is kept


@pytest.mark.parametrize(("count", "recalls"), [pytest.param(4, False, id="four"), pytest.param(5, True, id="five")])
def test_fewer_than_five_episodes_recall_nothing(count: int, recalls: bool) -> None:
    """장면 다섯이면 드문 명사 하나로 실리고 넷이면 실리지 않는다. 흔한 명사 비율이 0.2 인 동안은 넷 이하의 방에서 어느
    명사든 df/N ≥ 1/4 이라 비율 규칙만으로도 빠진다 — 그래서 이 테스트가 가르는 것은 하한이 5 보다 커지는 쪽이다."""
    rows = [
        RecallCandidate(id="g", nouns=frozenset({"밀알당"}), importance=3, end_turn=5, snapshot=1),
        *_filler(count - 1),
    ]
    query = RecallQuery(user=frozenset({"밀알당"}), assistant=frozenset(), time_cue=False)
    scored = score_episodes(rows, query, current_turn=50)
    assert bool(select_injected(scored, recall_cue=True)) is recalls


def test_rare_noun_outranks_character_name_overlap() -> None:
    """이름(df 6 = 비율 0.2, 남는다)과 드문 명사(df 1)를 함께 물으면 드문 명사 장면이 1위다. 겹친 명사 수만 세는 식이면
    둘 다 1개라 최근이고 중요한 이름 장면이 이긴다."""
    named = [
        RecallCandidate(id=f"m{i}", nouns=frozenset({"민지"}), importance=5, end_turn=200 + i, snapshot=9)
        for i in range(6)
    ]
    rows = [
        RecallCandidate(id="g", nouns=frozenset({"베이커리"}), importance=1, end_turn=10, snapshot=1),
        *named,
        *_filler(23),
    ]
    query = RecallQuery(user=frozenset({"민지", "베이커리"}), assistant=frozenset(), time_cue=False)
    scored = score_episodes(rows, query, current_turn=300)
    assert scored[0].id == "g"
    assert [row.id for row in select_injected(scored, recall_cue=False)] == ["g"]


def test_more_rare_overlap_outranks_a_recent_single_overlap() -> None:
    """임계용 점수는 드문 명사 하나에서 상한(1)에 닿아, 드문 명사 둘을 가진 옛 장면과 하나를 가진 최근 장면이 최근성으로만
    갈린다. 순위는 상한 없는 원점수라 둘을 가진 장면이 1위이고, 보통 턴의 한 자리도 그 장면이 차지한다."""
    rows = [
        RecallCandidate(id="old-two", nouns=frozenset({"렌즈", "케이스"}), importance=1, end_turn=10, snapshot=1),
        RecallCandidate(id="recent-one", nouns=frozenset({"가방"}), importance=1, end_turn=290, snapshot=9),
        *_filler(28),
    ]
    query = RecallQuery(user=frozenset({"렌즈", "케이스", "가방"}), assistant=frozenset(), time_cue=False)
    scored = score_episodes(rows, query, current_turn=300)
    by_id = {row.id: row for row in scored}
    assert by_id["recent-one"].s > by_id["old-two"].s
    assert [row.id for row in select_injected(scored, recall_cue=False)] == ["old-two"]


def test_reply_words_alone_without_a_time_cue_recall_nothing() -> None:
    """사용자 메시지에 방 장면의 낱말이 없고 시간 단서도 없으면 직전 응답에 드문 낱말이 있어도 찾지 않는다 — 상시로 찾으면
    매 턴 현재 장면 낱말로 최근 장면이 실린다. 렌즈 장면은 최근 스냅샷 둘보다 앞이라, 시간 단서만 있으면 찾힌다."""
    rows = [*_old_lens_scene_and_recent_fillers()]
    reply = frozenset({"렌즈"})
    assert score_episodes(rows, RecallQuery(user=frozenset(), assistant=reply, time_cue=False), current_turn=100) == []
    cued = score_episodes(rows, RecallQuery(user=frozenset(), assistant=reply, time_cue=True), current_turn=100)
    assert [row.id for row in select_injected(cued, recall_cue=True)] == ["g"]


def test_common_only_user_query_does_not_fall_back_to_the_reply() -> None:
    """ "그때 촬영 어땠더라?" — 사용자 질의에 방 장면의 낱말(촬영)이 있었으면 그것이 흔해서 빠져도 직전 응답으로 넘어가지
    않는다(사용자가 꺼낸 화제가 흔한 것일 뿐 앞 맥락을 가리킨 것이 아니다). 응답에는 찾을 수 있는 드문 낱말이 있다."""
    rows = [*_old_lens_scene_and_recent_fillers(), *_sharing("촬영", 5, prefix="c")]
    query = RecallQuery(user=frozenset({"촬영"}), assistant=frozenset({"렌즈"}), time_cue=True)
    assert score_episodes(rows, query, current_turn=100) == []


def _old_lens_scene_and_recent_fillers() -> list[RecallCandidate]:
    """스냅샷 1 의 렌즈 장면 하나와, 그 뒤 스냅샷 2·3 의 빈 장면 아홉."""
    return [
        RecallCandidate(id="g", nouns=frozenset({"렌즈"}), importance=3, end_turn=10, snapshot=1),
        *[
            RecallCandidate(id=f"f{i}", nouns=frozenset(), importance=1, end_turn=30 + i, snapshot=2 + i % 2)
            for i in range(9)
        ],
    ]


def test_recall_noun_in_user_message_is_not_diluted_by_current_scene_nouns() -> None:
    """사용자가 드문 명사로 물으면 직전 응답의 현재 장면 명사 스무 개가 질의를 묽히지 않는다 — 정답 장면이 실리고 현재
    장면을 공유하는 최근 장면은 실리지 않는다."""
    current = frozenset(f"현재{i}" for i in range(20))
    rows = [
        RecallCandidate(id="G", nouns=frozenset({"베이커리"}), importance=3, end_turn=30, snapshot=1),
        RecallCandidate(id="R", nouns=current, importance=3, end_turn=285, snapshot=28),
        *_filler(28),
    ]
    query = RecallQuery(user=frozenset({"베이커리"}), assistant=current, time_cue=False)
    scored = score_episodes(rows, query, current_turn=300)
    assert [row.id for row in select_injected(scored, recall_cue=True)] == ["G"]
    assert next(row for row in scored if row.id == "R").s < memory_recall.TAU


def test_common_nouns_only_message_recalls_nothing() -> None:
    """ "민지야 오늘 촬영 어땠어?" — 이름과 촬영이 대부분의 장면에 나오면 질의가 비어 섹션이 없다(순위만 보면 못 잡는다)."""
    rows = [
        *[
            RecallCandidate(id=f"m{i}", nouns=frozenset({"민지", "촬영"}), importance=3, end_turn=100 + i, snapshot=4)
            for i in range(20)
        ],
        *[
            RecallCandidate(id=f"n{i}", nouns=frozenset({"민지"}), importance=3, end_turn=40 + i, snapshot=1)
            for i in range(8)
        ],
        *_filler(2),
    ]
    pool = frozenset(noun for row in rows for noun in row.nouns)
    query = query_tokens("민지야 오늘 촬영 어땠어?", "카메라가 돈다.", episode_nouns=pool, names=[])
    # "민지야" 는 조사 목록에 없는 호격이 붙어 장면 낱말과 다른 토큰이다 — 사용자 질의에 남는 것은 촬영뿐이다.
    assert query.user == {"촬영"}
    assert score_episodes(rows, query, current_turn=300) == []


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        pytest.param("빵 먹자", True, id="alone"),
        pytest.param("빵을 샀다", True, id="with-particle"),
        pytest.param("빵집 가자", False, id="inside-a-longer-word"),
    ],
)
def test_one_syllable_noun_matches_only_at_word_boundary(text: str, hit: bool) -> None:
    query = query_tokens(text, "", episode_nouns=frozenset({"빵", "정류장"}), names=[])
    assert ("빵" in query.user) is hit


def test_time_cue_turns_off_recency() -> None:
    rows = [RecallCandidate(id="g", nouns=frozenset({"밀알당"}), importance=1, end_turn=50, snapshot=1), *_filler(9)]
    plain = score_episodes(
        rows, RecallQuery(user=frozenset({"밀알당"}), assistant=frozenset(), time_cue=False), current_turn=100
    )
    cued = score_episodes(
        rows, RecallQuery(user=frozenset({"밀알당"}), assistant=frozenset(), time_cue=True), current_turn=100
    )
    assert math.isclose(plain[0].s - cued[0].s, 0.02 * 50 / 100, abs_tol=TOLERANCE)


def test_recall_cue_allows_three_and_a_plain_turn_one() -> None:
    """드문 명사 넷이 장면 넷에 하나씩 — 넷 다 임계를 넘고 순위는 최근 순이다."""
    marks = [f"표지{i}" for i in range(4)]
    rows = [
        *[
            RecallCandidate(id=f"g{i}", nouns=frozenset({mark}), importance=1, end_turn=20 + i, snapshot=2)
            for i, mark in enumerate(marks)
        ],
        *_filler(26),
    ]
    scored = score_episodes(
        rows, RecallQuery(user=frozenset(marks), assistant=frozenset(), time_cue=False), current_turn=100
    )
    assert all(row.s >= memory_recall.TAU for row in scored[:4])
    assert [row.id for row in select_injected(scored, recall_cue=True)] == ["g3", "g2", "g1"]
    assert [row.id for row in select_injected(scored, recall_cue=False)] == ["g3"]


@pytest.mark.parametrize(
    ("asserted_by", "tail"),
    [
        pytest.param("character", " (인물의 말)", id="character"),
        pytest.param("mixed", " (인물의 말 포함)", id="mixed"),
        pytest.param("user", " (사용자의 말)", id="user"),
        pytest.param("narration", "", id="narration"),
    ],
)
def test_spoken_scene_is_marked_with_its_speaker_and_narration_is_not(asserted_by: str, tail: str) -> None:
    assert (
        recall_line("빵집 약속", "토요일에 소금빵을 사 오기로 했다.", asserted_by)
        == f"- 빵집 약속: 토요일에 소금빵을 사 오기로 했다.{tail}"
    )


# --- 방 프롬프트 ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Scene:
    title: str
    detail: str
    nouns: list[str]
    turn: int
    asserted_by: str = "narration"
    importance: int = 3
    # 장면 id 를 정하고 싶을 때(id 순과 일어난 순서를 일부러 다르게 둔다).
    key: int | None = None


_FILLER_SCENES = [Scene(f"잡담 {i}", f"평범한 하루 {i}번째.", [f"일상{i}"], turn=1 + i % 4) for i in range(5)]
_BAKERY = Scene("밀알당에 간 날", "태민이랑 밀알당에서 소금빵을 먹었다.", ["밀알당", "소금빵"], turn=3)


async def _story_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, scenes: list[Scene], *, turns: int = 8
) -> Room:
    """`turns` 턴짜리 스토리 방에 스냅샷 셋(턴 2·4·6 응답까지 접힘)과 장면을 심는다. 장면은 끝 턴을 덮는 가장 이른 스냅샷에
    붙인다(턴 1~2 → 첫째, 3~4 → 둘째, 5~6 → 셋째)."""
    room = await _open_room(db_client, db_session, turns=turns, lane="story")
    snapshots: dict[int, uuid.UUID] = {}
    for turn in (2, 4, 6):
        assistant = room.turns[turn][1]
        snapshot = ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=assistant.created_at,
            cursor_message_id=assistant.id,
            summary_text=f"턴 {turn} 까지의 요약",
            source="auto",
        )
        db_session.add(snapshot)
        await db_session.flush()
        snapshots[turn] = snapshot.id
    for ordinal, scene in enumerate(scenes):
        await _add_scene(db_session, room, scene, snapshot_id=snapshots[2 * ((scene.turn + 1) // 2)], ordinal=ordinal)
    await db_session.commit()
    return room


async def _add_scene(
    db_session: AsyncSession,
    room: Room,
    scene: Scene,
    *,
    snapshot_id: uuid.UUID,
    ordinal: int,
    end: ChatMessage | None = None,
) -> ChatMemoryEpisode:
    start = room.turns[scene.turn][0]
    end = end or room.turns[scene.turn][1]
    episode = _make_memory_episode(
        room.room_id,
        snapshot_id,
        ordinal=ordinal,
        start_created_at=start.created_at,
        start_message_id=start.id,
        end_created_at=end.created_at,
        end_message_id=end.id,
        start_turn=scene.turn,
        end_turn=scene.turn,
        title=scene.title,
        detail=scene.detail,
        nouns=episode_nouns(scene.nouns, scene.title, scene.detail),
        asserted_by=scene.asserted_by,
        importance=scene.importance,
        **({"id": uuid.UUID(int=scene.key)} if scene.key is not None else {}),
    )
    db_session.add(episode)
    await db_session.flush()
    return episode


async def _history(db_session: AsyncSession, room_id: uuid.UUID) -> list[ChatMessage]:
    return list(
        (
            await db_session.scalars(
                sa.select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )


async def _build(
    db_session: AsyncSession,
    room: Room,
    user_content: str,
    *,
    turn_state: InjectedTurnState | None = None,
    embedding_client: VoyageEmbeddingClient | None = None,
) -> GenerationPrompt:
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    history = await _history(db_session, room.room_id)
    return await build_room_prompt(
        db_session,
        chat_room,
        setup,
        history,
        user_content,
        None,
        prompt_set,
        sections,
        turn_state=turn_state,
        embedding_client=embedding_client,
    )


def _recall_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_episodes_recall", True)


def _section(prompt: str) -> str:
    start = prompt.index(HEADER)
    end = prompt.find("\n\n", start)
    return prompt[start:] if end == -1 else prompt[start:end]


async def test_recall_off_keeps_generation_prompt_bytes_and_reads_no_episodes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """스위치가 꺼져 있으면 장면이 있어도 없을 때와 같은 프롬프트, 같은 SQL 문 수다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    with _count_queries() as with_scenes_count:
        with_scenes = await _build(db_session, room, "밀알당 기억나?")
        statements_with_scenes = with_scenes_count()
    await db_session.execute(sa.delete(ChatMemoryEpisode).where(ChatMemoryEpisode.chat_room_id == room.room_id))
    await db_session.commit()
    with _count_queries() as without_scenes_count:
        without_scenes = await _build(db_session, room, "밀알당 기억나?")
        statements_without_scenes = without_scenes_count()

    assert HEADER not in with_scenes.prompt
    assert with_scenes.prompt == without_scenes.prompt
    assert statements_with_scenes == statements_without_scenes
    assert with_scenes.memory_recall == ()


async def test_recall_section_follows_history_and_changes_nothing_else(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """켜면 회상 섹션 하나가 대화 기록 뒤에 더해질 뿐 노트·요약·기록은 꺼졌을 때와 같다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    off = await _build(db_session, room, "밀알당 기억나?")
    _recall_on(monkeypatch)
    on = await _build(db_session, room, "밀알당 기억나?")

    section = _section(on.prompt)
    assert section.endswith("- 밀알당에 간 날: 태민이랑 밀알당에서 소금빵을 먹었다.")
    assert on.prompt.replace(section + "\n\n", "", 1) == off.prompt
    last_history_line = room.turns[8][1].content
    assert on.prompt.index(last_history_line) < on.prompt.index(HEADER) < on.prompt.rindex("밀알당 기억나?")


async def test_recall_keeps_first_two_cache_blocks_identical(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    off = await _build(db_session, room, "밀알당 기억나?")
    _recall_on(monkeypatch)
    on = await _build(db_session, room, "밀알당 기억나?")

    assert isinstance(off.prompt, SegmentedPrompt) and isinstance(on.prompt, SegmentedPrompt)
    assert on.prompt.segments[0:2] == off.prompt.segments[0:2]
    assert HEADER in on.prompt.segments[2] and HEADER not in off.prompt.segments[2]


async def test_recall_result_is_recorded_on_the_prompt_for_the_harness(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """조립 결과의 `memory_recall` 칸에 실은 장면이 순위 순으로 남는다(평가 하네스가 이 칸을 JSON 으로 읽는다). 점수는 시간
    단서가 없는 턴이라 최근성까지 들어간 값이다 — 이번 턴 번호는 오프닝을 뺀 응답 8개 + 1 = 9, 장면 끝 턴 3."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    _recall_on(monkeypatch)
    on = await _build(db_session, room, "밀알당 가자")

    bakery_id = await db_session.scalar(sa.select(ChatMemoryEpisode.id).where(ChatMemoryEpisode.title == _BAKERY.title))
    [entry] = json.loads(json.dumps(on._asdict()["memory_recall"]))
    line = "- 밀알당에 간 날: 태민이랑 밀알당에서 소금빵을 먹었다."
    assert math.isclose(entry.pop("score"), 0.7 + 0.05 * (3 - 1) / 4 + 0.02 * 3 / 9, abs_tol=1e-9)
    assert entry == {"episodeId": str(bakery_id), "rank": 1, "chars": len(line), "path": "user"}


async def test_below_threshold_or_common_query_injects_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """겹치지만 임계 아래(흔하지 않지만 드물지도 않은 명사)면 섹션도 기록도 없다."""
    scenes = [
        *[Scene(f"등대 {i}", f"등대 아래에서 {i}번 만났다.", ["등대"], turn=1 + i % 4, importance=1) for i in range(2)],
        *_FILLER_SCENES,
    ]
    scenes += [Scene(f"다른 날 {i}", f"그냥 지나간 하루 {i}.", [f"하루{i}"], turn=2) for i in range(3)]
    room = await _story_room(db_client, db_session, scenes)
    _recall_on(monkeypatch)
    # N = 10, 등대 df 2(비율 0.2, 남는다), 중요도 1, 시간 단서(최근성 끔): s = 0.7·(ln(11/3)+1)/(ln(11/2)+1) ≈ 0.595 < 0.60.
    built = await _build(db_session, room, "등대 기억나?")
    assert HEADER not in built.prompt
    assert built.memory_recall == ()


async def test_rooms_with_fewer_than_five_episodes_get_no_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES[:3], _BAKERY])
    _recall_on(monkeypatch)
    assert HEADER not in (await _build(db_session, room, "밀알당 기억나?")).prompt


async def test_recall_caps_three_episodes_in_event_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """회상 단서 턴은 셋까지, 줄은 일어난 순서(끝 키 오름차순) — 순위(중요도)와 다른 순서로 심는다. 장면마다 드문 낱말이
    하나씩 있어 넷 다 임계를 넘고, 순위는 중요도가 가른다. id 순은 첫날·둘째·셋째라 일어난 순서와 다르다."""
    lamps = [
        Scene("등대 첫날", "등대 벤치에서 처음 만났다.", ["벤치"], turn=4, importance=5, key=1),
        Scene("등대 둘째", "등대 계단을 올랐다.", ["계단"], turn=1, importance=4, key=2),
        Scene("등대 셋째", "등대 불빛을 봤다.", ["불빛"], turn=3, importance=3, key=3),
        Scene("등대 넷째", "등대 자물쇠가 잠겼다.", ["자물쇠"], turn=2, importance=1, key=4),
    ]
    room = await _story_room(
        db_client, db_session, [*lamps, *[Scene(f"잡담 {i}", f"하루 {i}.", [f"일상{i}"], turn=2) for i in range(26)]]
    )
    _recall_on(monkeypatch)
    section = _section((await _build(db_session, room, "그때 벤치랑 계단이랑 불빛이랑 자물쇠 기억나?")).prompt)
    assert section.splitlines()[-4:] == [
        section.splitlines()[-4],
        "- 등대 둘째: 등대 계단을 올랐다.",
        "- 등대 셋째: 등대 불빛을 봤다.",
        "- 등대 첫날: 등대 벤치에서 처음 만났다.",
    ]
    assert not section.splitlines()[-4].startswith("- ")
    plain = await _build(db_session, room, "벤치 가자")
    assert _section(plain.prompt).splitlines()[-1] == "- 등대 첫날: 등대 벤치에서 처음 만났다."
    assert len(plain.memory_recall) == 1


async def test_pronoun_follow_up_searches_the_previous_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "그때 그거 어디 뒀더라?" — 사용자 메시지에 방 장면의 낱말이 없고 시간 단서가 있으면 직전 응답의 낱말로 찾는다."""
    lens = Scene("편의점", "렌즈 케이스는 가방 앞주머니에 넣었다.", ["렌즈 케이스", "가방"], turn=1)
    # 가장 최근 스냅샷 둘(턴 4·6)의 장면 낱말은 AI 쪽 질의에서 빠진다 — 렌즈 장면은 그보다 앞(턴 2) 스냅샷에 있다.
    recent = [Scene(f"최근 {i}", f"지금 장면 {i}.", [f"현재{i}"], turn=5 + i) for i in range(2)]
    room = await _story_room(db_client, db_session, [lens, *_FILLER_SCENES, *recent])
    await db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.id == room.turns[8][1].id).values(content="렌즈 케이스 얘기가 나왔다.")
    )
    await db_session.commit()
    _recall_on(monkeypatch)
    built = await _build(db_session, room, "그때 그거 어디 뒀더라?")
    assert _section(built.prompt).endswith("- 편의점: 렌즈 케이스는 가방 앞주머니에 넣었다.")
    assert [entry["path"] for entry in built.memory_recall] == ["assistant"]


async def test_recall_disabled_when_generation_window_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    _recall_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_window_generation", False)
    with _count_queries() as count:
        built = await _build(db_session, room, "밀알당 기억나?")
        statements = count()
    monkeypatch.setattr(settings, "memory_episodes_recall", False)
    with _count_queries() as count_off:
        await _build(db_session, room, "밀알당 기억나?")
    assert HEADER not in built.prompt
    assert statements == count_off()


async def test_recalled_episodes_never_reach_past_current_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """요약 커서 뒤(원문 윈도우 안)에서 끝나는 장면은 후보가 아니다. 지난 턴을 그때의 요약으로 다시 조립하면 그 뒤에 접힌
    스냅샷의 장면도 후보가 아니다 — 끝 키가 그 커서 앞이어도 그때는 없던 장면이다."""
    room = await _story_room(db_client, db_session, _FILLER_SCENES)
    latest = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.id)
        .where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
        .order_by(ChatRoomMemorySnapshot.cursor_created_at.desc())
        .limit(1)
    )
    assert latest is not None
    _recall_on(monkeypatch)

    # 지금 커서는 턴 6 응답. 턴 8 응답에서 끝나는 장면은 원문 윈도우 안이다(장면이 넷이 아니라 다섯이 되면 회상이 켜진다).
    past = Scene("밀알당 늦게", "밀알당에서 소금빵을 또 샀다.", ["밀알당"], turn=5)
    await _add_scene(db_session, room, past, snapshot_id=latest, ordinal=90, end=room.turns[8][1])
    await db_session.commit()
    assert HEADER not in (await _build(db_session, room, "밀알당 기억나?")).prompt

    # 턴 3 에서 끝나지만 턴 6 스냅샷에서 뽑힌 장면 — 지금은 후보이고, 턴 4 까지만 접혔던 그 턴에는 아니다.
    early = Scene("밀알당 이른", "밀알당에서 소금빵을 먹었다.", ["밀알당"], turn=3)
    await _add_scene(db_session, room, early, snapshot_id=latest, ordinal=91)
    await db_session.commit()
    assert HEADER in (await _build(db_session, room, "밀알당 기억나?")).prompt
    cursor = room.turns[4][1]
    then = InjectedTurnState(
        summary=CurrentSummary(cursor=(cursor.created_at, cursor.id), text="턴 4 까지의 요약"),
        memory_note="",
        stats={},
        persona=None,
    )
    assert HEADER not in (await _build(db_session, room, "밀알당 기억나?", turn_state=then)).prompt


async def test_recall_section_never_exceeds_its_computed_maximum(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """최대값 = 실제 머리글(DB 의 회상 섹션 본문에서 자리표시자를 뺀 것) + 줄 셋 × (기호·제목 상한·구분·본문 상한·가장 긴
    꼬리표) + 줄 사이 줄바꿈. 최대 길이 장면 셋을 실으면 섹션이 정확히 그 길이다."""
    _, sections = await load_active_prompt_set(db_session, lane="story")
    [body] = [section.body for section in sections if section.slot == "memory_recall"]
    header = body.replace("{memory_recall_lines}", "")
    longest_tail = max(len(" (인물의 말)"), len(" (인물의 말 포함)"))
    line_max = len("- ") + EPISODE_TITLE_MAX + len(": ") + EPISODE_DETAIL_MAX + longest_tail
    maximum = len(header) + memory_recall.MAX_INJECT_RECALL_CUE * line_max + (memory_recall.MAX_INJECT_RECALL_CUE - 1)

    big = [
        Scene(
            f"등대{i}".ljust(EPISODE_TITLE_MAX, "가"),
            f"등대{i}".ljust(EPISODE_DETAIL_MAX, "나"),
            ["등대"],
            turn=1 + i,
            asserted_by="mixed",
            importance=5,
        )
        for i in range(3)
    ]
    room = await _story_room(
        db_client, db_session, [*big, *[Scene(f"잡담 {i}", f"하루 {i}.", [f"일상{i}"], turn=2) for i in range(27)]]
    )
    _recall_on(monkeypatch)
    built = await _build(db_session, room, "그때 등대 기억나?")
    assert len(built.memory_recall) == 3
    assert len(_section(built.prompt)) == maximum


async def test_recall_read_failure_is_absorbed_and_the_turn_finishes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """장면 읽기가 DB 오류(실제로 실패한 문장)로 끝나면 회상 없이 턴을 마치고 경고·승격을 남긴다. 요청 세션은 다음 문장을
    계속 쓸 수 있어야 한다(턴 기록까지 커밋된다)."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    _recall_on(monkeypatch)
    monkeypatch.setattr(memory_recall, "_candidate_statement", lambda room_id, cursor: sa.text("SELECT 1/0"))
    captured: list[str] = []
    monkeypatch.setattr(
        memory_recall, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    fake = _PromptCapture()
    with caplog.at_level(logging.WARNING):
        await _send(
            db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "밀알당 기억나?"}, fake
        )

    assert HEADER not in fake.prompts[-1]
    assert captured == ["db"]
    assert any("회상" in record.getMessage() for record in caplog.records)
    assert [record.memory_recall for record in (await _records(db_session, room.room_id)).values()] == [[]]


async def test_recall_scoring_failure_is_absorbed_and_the_turn_finishes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DB 가 아닌 곳(토큰화·점수)에서 난 예외도 SSE 로 새지 않는다 — 회상 없이 턴을 마치고, 스택이 실린 경고와 승격을 남긴다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    _recall_on(monkeypatch)

    def broken(*_args: object, **_kwargs: object) -> list[memory_recall.ScoredEpisode]:
        raise ValueError("점수 계산 실패")

    monkeypatch.setattr(memory_recall, "score_episodes", broken)
    captured: list[str] = []
    monkeypatch.setattr(
        memory_recall, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    fake = _PromptCapture()
    with caplog.at_level(logging.WARNING):
        await _send(
            db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "밀알당 기억나?"}, fake
        )

    assert HEADER not in fake.prompts[-1]
    assert captured == ["memory_recall"]
    [warning] = [record for record in caplog.records if "회상" in record.getMessage()]
    assert warning.exc_info is not None and warning.exc_info[0] is ValueError
    assert [record.memory_recall for record in (await _records(db_session, room.room_id)).values()] == [[]]


# --- 턴 기록 · 리플레이 -----------------------------------------------------------------------


class _PromptCapture(LLMClient):
    """생성 프롬프트를 모으고 고정 응답을 낸다. 판정은 아무 규칙도 고르지 않는다. 생성은 실제 공급자 구현처럼 끝날 때 사용량을
    그 호출의 목록에 더한다(턴 기록 호출 목록의 생성 칸)."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        yield "응답"
        collect_usage(usage, "fake-generate", None)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=[])
        return MemorySummaryResult(summary="요약")


async def _send(
    client: httpx.AsyncClient, room: Room, method: str, path: str, body: dict[str, object] | None, fake: LLMClient
) -> None:
    _override_llm_client(fake)
    try:
        response = await client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    assert _parse_sse_events(response.text)[-1]["type"] == "done", response.text


async def _records(db_session: AsyncSession, room_id: uuid.UUID) -> dict[str, ChatTurn]:
    """방의 턴 기록을 종류별로. 한 테스트 안에서는 `created_at` 이 같아 순서로는 가를 수 없다. 심어 둔 메시지 객체를 만료시키지
    않도록 기록만 다시 읽는다."""
    records = (
        await db_session.scalars(
            sa.select(ChatTurn).where(ChatTurn.chat_room_id == room_id).execution_options(populate_existing=True)
        )
    ).all()
    by_kind: dict[str, ChatTurn] = {record.kind: record for record in records}
    assert len(by_kind) == len(records)
    return by_kind


async def test_send_regenerate_and_edit_record_their_own_recall(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """세 경로 모두 그 턴에 다시 검색해 실은 장면을 자기 기록 행에 남긴다 — 재생성은 앞 기록을 물려받지 않고, 수정은 고친
    글로 찾는다."""
    tower = Scene("등대 밤", "등대 불빛 아래에서 약속했다.", ["등대"], turn=1)
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, tower])
    _recall_on(monkeypatch)
    ids = {
        title: await db_session.scalar(sa.select(ChatMemoryEpisode.id).where(ChatMemoryEpisode.title == title))
        for title in (_BAKERY.title, tower.title)
    }
    fake = _PromptCapture()

    await _send(db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "밀알당 기억나?"}, fake)
    await _send(db_client, room, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, fake)
    user_id = await db_session.scalar(
        sa.select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room.room_id, ChatMessage.role == ChatMessageRole.USER)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    await _send(
        db_client, room, "PATCH", f"/chat-rooms/{room.room_id}/messages/{user_id}", {"content": "등대 기억나?"}, fake
    )

    records = await _records(db_session, room.room_id)
    assert {kind: [entry["episodeId"] for entry in record.memory_recall] for kind, record in records.items()} == {
        "send": [str(ids[_BAKERY.title])],
        "regenerate": [str(ids[_BAKERY.title])],
        "edit": [str(ids[tower.title])],
    }
    assert all(
        entry["path"] == "user" and entry["rank"] == 1 for record in records.values() for entry in record.memory_recall
    )
    assert all(HEADER in prompt for prompt in fake.prompts)


async def test_replay_rebuilds_recall_lines_from_turn_record(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """리플레이는 지금 장면으로 다시 찾지 않고 그 턴 기록의 id 로 줄을 다시 렌더한다 — 턴 뒤에 더 맞는 장면이 생겨도 그 턴의
    프롬프트를 바이트까지 다시 만든다. 기록한 장면이 사라졌으면 그 턴은 다시 만들 수 없다고 거부한다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    _recall_on(monkeypatch)
    before = await _history(db_session, room.room_id)
    fake = _PromptCapture()
    await _send(db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "밀알당 기억나?"}, fake)
    record = (await _records(db_session, room.room_id))["send"]

    snapshot_id = await db_session.scalar(
        sa.select(ChatMemoryEpisode.snapshot_id).where(ChatMemoryEpisode.title == _BAKERY.title)
    )
    assert snapshot_id is not None
    later = Scene("밀알당 다시", "밀알당에서 크루아상을 샀다.", ["밀알당"], turn=4, importance=5)
    await _add_scene(db_session, room, later, snapshot_id=snapshot_id, ordinal=50)
    await db_session.commit()

    lines = await turn_recall_lines(db_session, record.assistant_message_id)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    summary = await load_current_summary(db_session, room.room_id)
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    state = InjectedTurnState(summary=summary, memory_note="", stats={}, persona=None, recall_lines=lines)
    replayed = await build_room_prompt(
        db_session, chat_room, setup, before, "밀알당 기억나?", None, prompt_set, sections, turn_state=state
    )
    searched_now = await build_room_prompt(
        db_session, chat_room, setup, before, "밀알당 기억나?", None, prompt_set, sections
    )

    assert replayed.prompt == fake.prompts[0]
    assert searched_now.prompt != fake.prompts[0]

    await db_session.execute(sa.delete(ChatMemoryEpisode).where(ChatMemoryEpisode.title == _BAKERY.title))
    await db_session.commit()
    with pytest.raises(ReplayRefusedError):
        await turn_recall_lines(db_session, record.assistant_message_id)

    # 리플레이의 회상 스위치가 꺼져 있으면 회상 섹션을 싣지 않으므로 사라진 장면은 거부할 이유가 아니다.
    monkeypatch.setattr(settings, "memory_episodes_recall", False)
    assert await turn_recall_lines(db_session, record.assistant_message_id) == ""


async def test_replay_of_a_turn_without_recall_gets_no_lines(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session, _FILLER_SCENES)
    await _send(db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "안녕"}, _PromptCapture())
    record = (await _records(db_session, room.room_id))["send"]
    assert await turn_recall_lines(db_session, record.assistant_message_id) == ""
    assert await turn_recall_lines(db_session, uuid.uuid4()) == ""


# --- 하이브리드 회상(명사 + 임베딩 RRF) -----------------------------------------------------------
# 스텁은 입력 i 번째에 `[i + 1, 0.5, 0.5]` 를 돌려주므로 질의 벡터는 늘 `[1, 0.5, 0.5]` 다. 장면 벡터는 그 방향과의 코사인
# 거리로 놓는다(반정밀도라 거리는 근삿값이다).

_EMBED_MODEL = "voyage-test"
_NEAR = [1.0, 0.5, 0.5]  # 거리 0
_MID = [1.0, 0.0, 0.0]  # 거리 ≈ 0.18
_FAR = [0.0, 1.0, -1.0]  # 거리 1
# id 를 가장 작은 값으로 둔다 — RRF 동점을 id 순으로 깨면 정원이 앞서므로, 명사 쪽 먼저 규칙이 id 순과 갈린다.
_GARDEN = Scene("정원 산책", "비 갠 오후에 수국 길을 걸었다.", ["수국"], turn=5, key=1)
# 장면 명사와 하나도 겹치지 않고 시간 단서도 없는 턴 — 명사 쪽은 회상하지 않는다.
_PLAIN = "오늘 날씨 좋다"


def _embed_client(stub: VoyageStub) -> VoyageEmbeddingClient:
    return VoyageEmbeddingClient(
        api_key="test-key", model=_EMBED_MODEL, dims=stub.dims, transport=stub.transport(), retry_delays=(0.0, 0.0)
    )


async def _episode_id(db_session: AsyncSession, title: str) -> uuid.UUID:
    episode_id = await db_session.scalar(sa.select(ChatMemoryEpisode.id).where(ChatMemoryEpisode.title == title))
    assert episode_id is not None
    return episode_id


async def _embed_scene(
    db_session: AsyncSession, room: Room, title: str, vector: list[float], *, model: str = _EMBED_MODEL
) -> uuid.UUID:
    episode_id = await _episode_id(db_session, title)
    db_session.add(
        _make_memory_embedding(room.room_id, episode_id=episode_id, model=model, dims=len(vector), embedding=vector)
    )
    await db_session.commit()
    return episode_id


def _hybrid_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _recall_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_embed_recall", True)


def _vector_ids(built: GenerationPrompt) -> list[str]:
    return [entry["episodeId"] for entry in built.memory_recall]


def test_rrf_orders_by_summed_reciprocal_ranks_and_breaks_ties_toward_the_first_list() -> None:
    """두 목록에 다 있는 것(1/62 + 1/61)이 한 목록의 1위(1/61)를 이긴다. 한 목록에만 있는 둘이 같은 순위면 앞 목록(명사)의 것이
    먼저다. k 가 작으면 1위의 몫이 커져 순서가 바뀐다 — k 를 실제로 읽는다."""
    from api.chat.memory_vector import rrf_order

    assert rrf_order([["a", "b"], ["b", "c"]], k=60) == ["b", "a", "c"]
    assert rrf_order([["a"], ["c"]], k=60) == ["a", "c"]
    # id 순과 반대인 동점 — 앞 목록이 이긴다.
    assert rrf_order([["c"], ["a"]], k=60) == ["c", "a"]
    assert rrf_order([["a"], []], k=60) == ["a"]
    # k = 0: a = 1/1, b = 1/2 + 1/3 — a 가 앞선다. k = 60 이면 b 가 앞선다.
    assert rrf_order([["a", "b"], ["x", "x2", "b"]], k=0)[0] == "a"
    assert rrf_order([["a", "b"], ["x", "x2", "b"]], k=60)[0] == "b"


async def test_embed_recall_off_calls_no_voyage_and_keeps_prompt_and_statements(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """회상은 켜져 있고 임베딩도 있지만 임베딩 회상 스위치가 꺼져 있으면, 클라이언트를 넘겨도 Voyage 를 부르지 않고 프롬프트·
    턴 기록·SQL 문 수가 클라이언트 없이 조립한 것과 같다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    _recall_on(monkeypatch)
    stub = VoyageStub()

    with _count_queries() as without_client_count:
        without_client = await _build(db_session, room, "밀알당 기억나?")
        statements_without_client = without_client_count()
    with _count_queries() as with_client_count:
        with_client = await _build(db_session, room, "밀알당 기억나?", embedding_client=_embed_client(stub))
        statements_with_client = with_client_count()

    assert stub.bodies == []
    assert with_client.prompt == without_client.prompt
    assert with_client.memory_recall == without_client.memory_recall
    assert with_client.memory_query is None
    assert statements_with_client == statements_without_client


async def test_vector_neighbour_is_recalled_on_a_plain_turn_and_the_query_is_recorded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명사가 하나도 겹치지 않는 보통 턴이라 명사 쪽은 비지만, 질의와 가장 가까운 장면이 보통 턴 상한 1 만큼 실린다. 질의 글은
    이번 사용자 메시지 + 줄바꿈 + 직전 응답이고 찾는 글(`query`) 종류로 보낸다. 조립 결과에 그 호출의 사용량·결과가 남는다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    garden_id = await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    await _embed_scene(db_session, room, _BAKERY.title, _MID)
    _hybrid_on(monkeypatch)
    stub = VoyageStub()

    noun_only = await _build(db_session, room, _PLAIN)
    built = await _build(db_session, room, _PLAIN, embedding_client=_embed_client(stub))

    assert HEADER not in noun_only.prompt
    assert _section(built.prompt).endswith("- 정원 산책: 비 갠 오후에 수국 길을 걸었다.")
    assert _vector_ids(built) == [str(garden_id)]
    [entry] = built.memory_recall
    assert (entry["rank"], entry["score"], entry["vectorRank"]) == (None, None, 1)
    assert stub.bodies == [
        {
            "input": [f"{_PLAIN}\n{room.turns[8][1].content}"],
            "model": _EMBED_MODEL,
            "input_type": "query",
            "output_dimension": 3,
        }
    ]
    assert built.memory_query is not None
    assert {key: value for key, value in built.memory_query.items() if key != "latencyMs"} == {
        "callSite": "chat_memory_query_embedding",
        "model": _EMBED_MODEL,
        "dims": 3,
        "promptTokens": stub.total_tokens,
        "outcome": "ok",
    }
    assert isinstance(built.memory_query["latencyMs"], int)


async def test_noun_and_vector_hits_share_the_cue_cap_noun_first_on_a_tie(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """회상 단서 턴(상한 3)에 명사 1위(밀알당)와 벡터 1위(정원)가 둘 다 1/61 로 같으면 명사 쪽이 기록 앞이다. 섹션 줄은 일어난
    순서(밀알당 턴 3, 정원 턴 5)다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    garden_id = await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    bakery_id = await _episode_id(db_session, _BAKERY.title)
    _hybrid_on(monkeypatch)

    built = await _build(db_session, room, "밀알당 기억나?", embedding_client=_embed_client(VoyageStub()))

    assert _vector_ids(built) == [str(bakery_id), str(garden_id)]
    assert [(entry["rank"], entry["vectorRank"]) for entry in built.memory_recall] == [(1, None), (None, 1)]
    section = _section(built.prompt)
    assert section.index("밀알당에 간 날") < section.index("정원 산책")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("timeout", id="timeout"),
        pytest.param("rejected", id="key-rejected"),
        pytest.param("no-rows", id="no-embedding-rows"),
        pytest.param("too-far", id="beyond-distance-cap"),
    ],
)
async def test_empty_vector_side_keeps_noun_only_bytes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """벡터 쪽이 비면 명사 단독과 프롬프트·턴 기록이 바이트까지 같다 — 질의 임베딩이 시간 상한을 넘거나(턴을 그 상한보다 오래
    기다리게 하지 않는다) 키가 거부되거나, 방에 임베딩 행이 없거나, 모든 장면이 거리 상한 밖일 때. 정원이 실리면 결과가 달라지는
    배치라 같음이 우연이 아니다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    if case != "no-rows":
        await _embed_scene(db_session, room, _GARDEN.title, _FAR if case == "too-far" else _NEAR)
    _hybrid_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_embed_recall_timeout_ms", 100)
    monkeypatch.setattr(settings, "memory_embed_recall_max_distance", 0.5)

    async def _slow() -> None:
        await asyncio.sleep(5)

    stub = {
        "timeout": VoyageStub(before_answer=_slow),
        "rejected": VoyageStub(failures=[401]),
    }.get(case, VoyageStub())

    noun_only = await _build(db_session, room, "밀알당 기억나?")
    started = time.monotonic()
    built = await _build(db_session, room, "밀알당 기억나?", embedding_client=_embed_client(stub))
    elapsed = time.monotonic() - started

    assert HEADER in noun_only.prompt
    assert built.prompt == noun_only.prompt
    assert built.memory_recall == noun_only.memory_recall
    assert elapsed < 2
    assert built.memory_query is not None
    expected = {"timeout": "timeout", "rejected": "failed"}.get(case, "ok")
    assert built.memory_query["outcome"] == expected


async def test_vector_side_skips_rows_past_the_cursor_other_models_and_other_dims(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """가장 가까운 벡터들이 전부 탈락해야 하는 행이다 — 커서 뒤에서 끝나는 장면, 다른 모델의 행, 같은 모델의 다른 차원 행.
    차원이 섞이면 거리 연산이 질의째 실패해 명사 단독으로 떨어지므로, 남은 하나(거리 0.18)가 실리는 것이 세 거름을 다 본다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    await _embed_scene(db_session, room, _GARDEN.title, _NEAR, model="other-model")
    await _embed_scene(db_session, room, _BAKERY.title, [1.0, 0.5])
    kept = await _embed_scene(db_session, room, _FILLER_SCENES[0].title, _MID)
    snapshot_id = await db_session.scalar(
        sa.select(ChatMemoryEpisode.snapshot_id).where(ChatMemoryEpisode.title == _GARDEN.title)
    )
    assert snapshot_id is not None
    past = Scene("커서 뒤 장면", "아직 접히지 않은 일.", ["미래"], turn=6)
    await _add_scene(db_session, room, past, snapshot_id=snapshot_id, ordinal=90, end=room.turns[8][1])
    await db_session.commit()
    await _embed_scene(db_session, room, past.title, _NEAR)
    _hybrid_on(monkeypatch)

    built = await _build(db_session, room, _PLAIN, embedding_client=_embed_client(VoyageStub()))

    assert _vector_ids(built) == [str(kept)]


async def test_rows_past_the_cursor_do_not_take_the_vector_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """벡터 순위 길이가 1 이고 가장 가까운 임베딩이 커서 뒤 장면이어도, 그 행이 자리를 차지하지 않아 커서 안의 이웃이 실린다 —
    커서 거름이 거리 읽기 안에 있어야 한다(읽은 뒤에 후보와 맞춰 거르면 자리가 비어 버린다)."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    kept = await _embed_scene(db_session, room, _GARDEN.title, _MID)
    snapshot_id = await db_session.scalar(
        sa.select(ChatMemoryEpisode.snapshot_id).where(ChatMemoryEpisode.title == _GARDEN.title)
    )
    assert snapshot_id is not None
    past = Scene("커서 뒤 장면", "아직 접히지 않은 일.", ["미래"], turn=6)
    await _add_scene(db_session, room, past, snapshot_id=snapshot_id, ordinal=90, end=room.turns[8][1])
    await db_session.commit()
    await _embed_scene(db_session, room, past.title, _NEAR)
    _hybrid_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_embed_recall_vector_limit", 1)

    built = await _build(db_session, room, _PLAIN, embedding_client=_embed_client(VoyageStub()))

    assert _vector_ids(built) == [str(kept)]


async def test_hybrid_recall_stays_in_the_third_cache_block(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    off = await _build(db_session, room, _PLAIN)
    _hybrid_on(monkeypatch)
    on = await _build(db_session, room, _PLAIN, embedding_client=_embed_client(VoyageStub()))

    assert isinstance(off.prompt, SegmentedPrompt) and isinstance(on.prompt, SegmentedPrompt)
    assert on.prompt.segments[0:2] == off.prompt.segments[0:2]
    assert HEADER in on.prompt.segments[2] and HEADER not in off.prompt.segments[2]


async def test_vector_read_failure_falls_back_to_noun_only(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """벡터 순위 읽기가 DB 오류로 끝나도 명사 회상은 남는다(회상 전체를 잃지 않는다) — 명사 단독과 바이트가 같고 경고·승격을
    남긴다. 요청 세션은 다음 문장을 계속 쓴다."""
    from api.chat import memory_vector

    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    _hybrid_on(monkeypatch)
    noun_only = await _build(db_session, room, "밀알당 기억나?")
    monkeypatch.setattr(memory_vector, "_episode_distance_statement", lambda *args, **kwargs: sa.text("SELECT 1/0"))
    captured: list[str] = []
    monkeypatch.setattr(
        memory_vector, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )

    with caplog.at_level(logging.WARNING):
        built = await _build(db_session, room, "밀알당 기억나?", embedding_client=_embed_client(VoyageStub()))

    assert built.prompt == noun_only.prompt
    assert built.memory_recall == noun_only.memory_recall
    assert captured == ["db"]
    assert any("임베딩" in record.getMessage() for record in caplog.records)
    assert await db_session.scalar(sa.select(sa.literal(1))) == 1


async def _send_with_embedding(
    client: httpx.AsyncClient, room: Room, method: str, path: str, body: dict[str, object] | None, stub: VoyageStub
) -> None:
    app.dependency_overrides[get_embedding_client] = lambda: _embed_client(stub)
    try:
        await _send(client, room, method, path, body, _PromptCapture())
    finally:
        app.dependency_overrides.pop(get_embedding_client, None)


async def test_send_records_the_query_embedding_and_holds_no_transaction_while_waiting(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """보내기 턴은 질의 임베딩을 기다리는 동안 요청 세션의 트랜잭션을 쥐지 않는다(생성 LLM 을 기다릴 때와 같은 규칙). 턴 기록의
    호출 목록 맨 앞에 그 호출이 남고, 회상 기록에 벡터로 실은 장면이 남는다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    garden_id = await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    _hybrid_on(monkeypatch)
    open_at_call: list[int] = []
    with _open_transaction_probe() as open_sessions:

        async def _record_open_sessions() -> None:
            open_at_call.append(len(open_sessions))

        stub = VoyageStub(before_answer=_record_open_sessions)
        await _send_with_embedding(
            db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": _PLAIN}, stub
        )

    assert open_at_call == [0]
    record = (await _records(db_session, room.room_id))["send"]
    assert [entry["episodeId"] for entry in record.memory_recall] == [str(garden_id)]
    first_call = record.llm_calls[0]
    assert (first_call["callSite"], first_call["model"], first_call["promptTokens"], first_call["outcome"]) == (
        "chat_memory_query_embedding",
        _EMBED_MODEL,
        stub.total_tokens,
        "ok",
    )
    assert record.llm_calls[1]["callSite"] == "chat_generate"


async def test_turn_record_has_no_query_embedding_call_when_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    _recall_on(monkeypatch)
    stub = VoyageStub()
    await _send_with_embedding(
        db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": _PLAIN}, stub
    )

    record = (await _records(db_session, room.room_id))["send"]
    assert stub.bodies == []
    assert "chat_memory_query_embedding" not in [call["callSite"] for call in record.llm_calls]


async def test_replay_rebuilds_hybrid_recall_without_calling_voyage(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """리플레이는 턴 기록의 장면 id 로 줄을 다시 렌더한다 — 벡터로 실은 장면도 같고, 질의 임베딩을 다시 부르지 않는다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    await _embed_scene(db_session, room, _GARDEN.title, _NEAR)
    _hybrid_on(monkeypatch)
    before = await _history(db_session, room.room_id)
    stub = VoyageStub()
    fake = _PromptCapture()
    app.dependency_overrides[get_embedding_client] = lambda: _embed_client(stub)
    try:
        await _send(db_client, room, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": _PLAIN}, fake)
    finally:
        app.dependency_overrides.pop(get_embedding_client, None)
    record = (await _records(db_session, room.room_id))["send"]
    calls_after_turn = len(stub.bodies)

    lines = await turn_recall_lines(db_session, record.assistant_message_id)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    summary = await load_current_summary(db_session, room.room_id)
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    state = InjectedTurnState(summary=summary, memory_note="", stats={}, persona=None, recall_lines=lines)
    replayed = await build_room_prompt(
        db_session,
        chat_room,
        setup,
        before,
        _PLAIN,
        None,
        prompt_set,
        sections,
        turn_state=state,
        embedding_client=_embed_client(stub),
    )

    assert "정원 산책" in lines
    assert replayed.prompt == fake.prompts[0]
    assert len(stub.bodies) == calls_after_turn == 1


def test_embed_recall_needs_a_voyage_key_and_production_leaves_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """키 없이 켜진 임베딩 회상은 매 턴 실패해 명사 단독으로 떨어질 뿐이라 켠 것이 성공한 것처럼 보인다 — 기동을 막는다. 운영
    env 에는 아직 이 스위치가 없어 꺼진 채 뜨고, 주입 상한의 기본값은 명사 단독의 상한과 같다."""
    assert "MEMORY_EMBED_RECALL" not in PRODUCTION_ENV_NAMES
    production = load_production_env(monkeypatch)
    assert not production.memory_embed_recall
    assert (production.memory_embed_recall_max_plain, production.memory_embed_recall_max_cue) == (
        memory_recall.MAX_INJECT_PLAIN,
        memory_recall.MAX_INJECT_RECALL_CUE,
    )
    # k 는 회상 품질 측정이 고른 값이다 — 스위치만 켜도 측정한 설정으로 돈다.
    assert production.memory_embed_recall_rrf_k == 20
    with pytest.raises(ValidationError, match="MEMORY_EMBED_RECALL"):
        load_production_env(monkeypatch, MEMORY_EMBED_RECALL="true")
    assert load_production_env(monkeypatch, MEMORY_EMBED_RECALL="true", VOYAGE_API_KEY="k").memory_embed_recall


# --- 인물이 말한 장면 ------------------------------------------------------------------------
# 인물이 대사로 말한 장면(`asserted_by = 'character'`)은 확인되지 않은 말이라 회상 줄에 싣지 않는다. 섞임·사용자·서술 장면은
# 그대로 싣는다. 명사 쪽은 방 장면 전부로 통계(장면 수·흔한 명사·사용자 토큰 풀·최근 스냅샷 둘)를 낸 뒤 순위에서 빼고, 벡터 쪽은
# 거리 읽기 안에서 빼서 거리 순위 길이를 자격 있는 장면이 채운다. 리플레이는 기록한 장면을 그때처럼 렌더한다.


def _lines(prompt: str) -> list[str]:
    """회상 섹션의 장면 줄(머리글 문안을 뺀 것)."""
    return [line for line in _section(prompt).splitlines() if line.startswith("- ")]


async def test_top_ranked_character_scene_gives_way_to_the_next_eligible_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """보통 턴(상한 1)에 명사 1위는 중요도가 높은 인물 장면이다. 그 장면은 빠지고 2위 서술 장면이 실린다 — 상한을 채운 뒤에
    빼면 섹션이 빈다."""
    spoken = Scene("밀알당 고백", "민수가 밀알당 얘기를 꺼냈다.", ["밀알당"], turn=3, asserted_by="character", importance=5)
    walk = Scene("소금빵 산책", "소금빵을 들고 걸었다.", ["소금빵"], turn=5, importance=1)
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, spoken, walk])
    _recall_on(monkeypatch)

    built = await _build(db_session, room, "밀알당 소금빵 가자")

    assert _lines(built.prompt) == ["- 소금빵 산책: 소금빵을 들고 걸었다."]
    assert [entry["episodeId"] for entry in built.memory_recall] == [str(await _episode_id(db_session, walk.title))]


async def test_mixed_user_and_narration_scenes_are_still_recalled_with_their_tails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """섞임 장면(인물의 말이 섞인 장면)·사용자 장면·서술 장면은 그대로 실린다 — 빼는 것은 인물만 말한 장면뿐이다."""
    scenes = [
        Scene("등대 약속", "등대 앞에서 둘이 약속을 나눴다.", ["등대"], turn=1, asserted_by="mixed"),
        Scene("자물쇠 이야기", "사용자가 자물쇠를 잃어버렸다고 했다.", ["자물쇠"], turn=3, asserted_by="user"),
        Scene("벤치 오후", "벤치에 앉아 해를 봤다.", ["벤치"], turn=5),
    ]
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, *scenes])
    _recall_on(monkeypatch)

    built = await _build(db_session, room, "그때 등대랑 자물쇠랑 벤치 기억나?")

    assert _lines(built.prompt) == [
        "- 등대 약속: 등대 앞에서 둘이 약속을 나눴다. (인물의 말 포함)",
        "- 자물쇠 이야기: 사용자가 자물쇠를 잃어버렸다고 했다. (사용자의 말)",
        "- 벤치 오후: 벤치에 앉아 해를 봤다.",
    ]


async def test_character_scenes_still_count_toward_the_minimum_episode_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """장면 여섯 중 둘이 인물 장면인 방 — 장면 수 하한(5)은 방 장면 전부로 센다. 인물 장면을 먼저 빼면 넷이라 회상이 통째로
    꺼진다."""
    scenes = [
        Scene("등대 밤", "등대 불빛 아래를 걸었다.", ["등대"], turn=1),
        *[Scene(f"잡담 {i}", f"평범한 하루 {i}번째.", [f"일상{i}"], turn=2 + i) for i in range(3)],
        *[
            Scene(f"말 {i}", f"민수가 이야기 {i}을 했다.", [f"대사{i}"], turn=1 + i, asserted_by="character")
            for i in range(2)
        ],
    ]
    room = await _story_room(db_client, db_session, scenes)
    _recall_on(monkeypatch)

    built = await _build(db_session, room, "등대 기억나?")

    assert _lines(built.prompt) == ["- 등대 밤: 등대 불빛 아래를 걸었다."]


async def test_character_scenes_still_count_as_the_two_most_recent_snapshots(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """가장 최근 스냅샷(턴 5~6)의 장면이 전부 인물 장면인 방에서 대명사 후속 질문은 직전 응답 낱말 중 최근 스냅샷 둘(턴 3~6)의
    낱말을 빼고 찾는다 — 우산(턴 3)은 빠지고 렌즈(턴 1)가 실린다. 인물 장면을 먼저 빼면 최근 스냅샷 둘이 턴 1~4 로 밀려 렌즈도
    빠진다."""
    scenes = [
        Scene("편의점", "렌즈 케이스는 가방 앞주머니에 넣었다.", ["렌즈 케이스", "가방"], turn=1),
        Scene("비 오는 날", "우산을 같이 썼다.", ["우산"], turn=3),
        *[
            Scene(f"지금 {i}", f"민수가 지금 장면 {i} 얘기를 했다.", [f"현재{i}"], turn=5 + i, asserted_by="character")
            for i in range(2)
        ],
        *_FILLER_SCENES,
    ]
    room = await _story_room(db_client, db_session, scenes)
    await db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.id == room.turns[8][1].id).values(content="렌즈 우산 얘기가 나왔다.")
    )
    await db_session.commit()
    _recall_on(monkeypatch)

    built = await _build(db_session, room, "그때 그거 어디 뒀더라?")

    assert _lines(built.prompt) == ["- 편의점: 렌즈 케이스는 가방 앞주머니에 넣었다."]
    assert [entry["path"] for entry in built.memory_recall] == ["assistant"]


async def test_a_noun_only_in_character_scenes_still_keeps_the_user_side_query(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """사용자 질의 토큰은 방 장면 전부의 낱말로 거른다 — 인물 장면에만 나온 소금빵을 물으면 사용자 쪽으로 찾고, 그 장면이
    빠지니 회상이 없다. 인물 장면을 먼저 빼면 사용자 질의가 비어 직전 응답(렌즈)으로 넘어가 엉뚱한 장면이 실린다."""
    scenes = [
        Scene("편의점", "렌즈 케이스는 가방 앞주머니에 넣었다.", ["렌즈 케이스", "가방"], turn=1),
        Scene("빵 이야기", "민수가 소금빵을 자랑했다.", ["소금빵"], turn=3, asserted_by="character"),
        *[Scene(f"최근 {i}", f"지금 장면 {i}.", [f"현재{i}"], turn=5 + i) for i in range(2)],
        *_FILLER_SCENES,
    ]
    room = await _story_room(db_client, db_session, scenes)
    await db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.id == room.turns[8][1].id).values(content="렌즈 얘기가 나왔다.")
    )
    await db_session.commit()
    _recall_on(monkeypatch)

    built = await _build(db_session, room, "그때 소금빵 어디 뒀더라?")

    assert HEADER not in built.prompt
    assert built.memory_recall == ()


async def test_vector_limit_is_filled_by_eligible_scenes_not_character_scenes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """거리 순위 길이가 1 이고 질의와 가장 가까운 장면이 인물 장면이면, 그 장면은 거리 읽기에서 빠져 그다음 서술 장면(정원)이
    실린다 — 읽은 뒤에 빼면 자리가 비어 회상이 없다."""
    spoken = Scene("고백", "민수가 비밀을 털어놓았다.", ["비밀"], turn=5, asserted_by="character")
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _GARDEN, spoken])
    await _embed_scene(db_session, room, spoken.title, _NEAR)
    garden_id = await _embed_scene(db_session, room, _GARDEN.title, _MID)
    _hybrid_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_embed_recall_vector_limit", 1)

    built = await _build(db_session, room, _PLAIN, embedding_client=_embed_client(VoyageStub()))

    assert _vector_ids(built) == [str(garden_id)]
    assert [entry["vectorRank"] for entry in built.memory_recall] == [1]


async def test_replay_renders_a_recorded_character_scene_as_it_was(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """리플레이는 기록한 장면을 고르지 않고 렌더만 한다 — 이 거름이 생기기 전 턴에 실린 인물 장면도 그때처럼 인물 꼬리표로
    다시 만든다."""
    spoken = Scene("고백", "민수가 비밀을 털어놓았다.", ["비밀"], turn=3, asserted_by="character")
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, spoken])
    spoken_id = await _episode_id(db_session, spoken.title)

    lines = await memory_recall.recall_lines_from_record(db_session, [{"episodeId": str(spoken_id)}])

    assert lines == "- 고백: 민수가 비밀을 털어놓았다. (인물의 말)"


# --- 회상 줄의 지식 범위 ---------------------------------------------------------------------
# 장면 행에는 아는 사람 칸이 없어, 회상은 같은 턴에 방 사실 행을 읽어 비밀 장면을 끌어낸다 — 키별 최신 행의 아는 사람이 이번
# 장면 인물(이번 사용자 메시지·직전 응답에 나온 방 이름, 사용자 제외)에 없는 키의 어느 행과든 근거 범위가 겹치는 장면을 뺀다.
# 회상 스위치에 묶여 사실 주입·지식 범위 필터 스위치와 무관하게 걸리고, 사실 읽기가 실패하면 회상 없이 조립한다(걸러지지
# 않은 회상을 싣지 않는다).


async def _snapshot_for(db_session: AsyncSession, room: Room, turn: int) -> uuid.UUID:
    """`_story_room` 이 그 턴을 접은 스냅샷(턴 1~2 → 턴 2 응답 커서, 3~4 → 4, 5~6 → 6)."""
    cursor = room.turns[2 * ((turn + 1) // 2)][1]
    snapshot_id = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.id).where(ChatRoomMemorySnapshot.cursor_message_id == cursor.id)
    )
    assert snapshot_id is not None
    return snapshot_id


async def _plant_fact(
    db_session: AsyncSession,
    room: Room,
    *,
    turn: int,
    known_by: list[str] | None,
    value: str = "전학",
    ordinal: int = 0,
    snapshot_turn: int | None = None,
) -> None:
    """유나의 비밀 사실 한 행 — 근거는 `turn` 턴의 사용자 메시지~응답. `snapshot_turn` 을 주면 그 턴을 접은 스냅샷에 붙인다."""
    start, end = room.turns[turn]
    db_session.add(
        _make_memory_fact(
            room.room_id,
            await _snapshot_for(db_session, room, snapshot_turn or turn),
            ordinal=ordinal,
            kind="fact",
            subject="유나",
            object=None,
            attribute="비밀",
            fact_key="fact|유나|비밀",
            value=value,
            asserted_by="narration",
            known_by=known_by,
            start_created_at=start.created_at,
            start_message_id=start.id,
            end_created_at=end.created_at,
            end_message_id=end.id,
            start_turn=turn,
            end_turn=turn,
        )
    )
    await db_session.commit()


async def test_scene_overlapping_a_secret_drops_unless_someone_who_knows_is_in_the_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """밀알당 장면(턴 3)이 민수만 아는 비밀과 같은 턴에 걸쳐 있다. 사실 주입이 꺼져 있어도 회상에서 빠지고, 이번 사용자 메시지에
    민수가 나오면 남는다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    await _plant_fact(db_session, room, turn=3, known_by=["민수"])
    _recall_on(monkeypatch)
    assert not settings.memory_facts_inject and not settings.memory_knowledge_filter

    hidden = await _build(db_session, room, "밀알당 기억나?")
    known = await _build(db_session, room, "민수랑 밀알당 기억나?")

    assert HEADER not in hidden.prompt
    assert hidden.memory_recall == ()
    assert _lines(known.prompt) == ["- 밀알당에 간 날: 태민이랑 밀알당에서 소금빵을 먹었다."]


async def test_secret_only_the_user_knows_always_hides_its_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """사용자는 장면 인물이 아니다 — 사용자만 아는 비밀과 겹치는 장면은 사용자 표기가 대사에 나와도 빠진다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    await _plant_fact(db_session, room, turn=3, known_by=["사용자 인물"])
    _recall_on(monkeypatch)

    assert HEADER not in (await _build(db_session, room, "사용자 인물이랑 밀알당 기억나?")).prompt


async def test_secret_whose_latest_value_is_public_no_longer_hides_its_scenes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 키의 뒤 행(턴 5 근거, 턴 6 스냅샷)이 공개면 그 키는 가려지지 않는다 — 옛 비밀 행과 겹치는 장면도 실린다. 반대로 뒤
    행이 여전히 비밀이면 옛 행과만 겹치는 장면도 빠진다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    await _plant_fact(db_session, room, turn=3, known_by=["민수"])
    await _plant_fact(db_session, room, turn=5, known_by=["민수"], value="유학")
    _recall_on(monkeypatch)
    assert HEADER not in (await _build(db_session, room, "밀알당 기억나?")).prompt

    await _plant_fact(db_session, room, turn=5, known_by=None, value="졸업", ordinal=1)

    assert _lines((await _build(db_session, room, "밀알당 기억나?")).prompt) == [
        "- 밀알당에 간 날: 태민이랑 밀알당에서 소금빵을 먹었다."
    ]


async def test_vector_limit_is_filled_past_a_hidden_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """거리 순위 길이 1 에서 가장 가까운 장면(밀알당)이 가려지면 그 장면은 거리 읽기에서 빠져 그다음 정원이 실린다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY, _GARDEN])
    await _plant_fact(db_session, room, turn=3, known_by=["민수"])
    await _embed_scene(db_session, room, _BAKERY.title, _NEAR)
    garden_id = await _embed_scene(db_session, room, _GARDEN.title, _MID)
    _hybrid_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_embed_recall_vector_limit", 1)

    built = await _build(db_session, room, _PLAIN, embedding_client=_embed_client(VoyageStub()))

    assert _vector_ids(built) == [str(garden_id)]


async def test_fact_read_failure_drops_the_recall_with_a_warning(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """비밀 장면을 가릴 사실 행을 읽지 못하면 걸러지지 않은 회상을 싣지 않는다 — 회상 없이 조립하고 경고·승격을 남긴다. 요청
    세션은 다음 문장을 계속 쓴다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    _recall_on(monkeypatch)
    assert HEADER in (await _build(db_session, room, "밀알당 기억나?")).prompt
    monkeypatch.setattr(memory_recall, "fact_rows_statement", lambda room_id, cursor: sa.text("SELECT 1/0"))
    captured: list[str] = []
    monkeypatch.setattr(
        memory_recall, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )

    with caplog.at_level(logging.WARNING):
        built = await _build(db_session, room, "밀알당 기억나?")

    assert HEADER not in built.prompt
    assert built.memory_recall == ()
    assert captured == ["db"]
    assert any("회상" in record.getMessage() for record in caplog.records)
    assert await db_session.scalar(sa.select(sa.literal(1))) == 1


async def test_recall_off_reads_no_facts_either(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """회상 스위치가 꺼져 있으면 장면도 사실도 읽지 않는다 — 장면·사실이 있는 방과 없는 방의 프롬프트·SQL 문 수가 같다. 켜면
    사실 주입이 꺼져 있어도 사실을 한 번 더 읽는다."""
    room = await _story_room(db_client, db_session, [*_FILLER_SCENES, _BAKERY])
    await _plant_fact(db_session, room, turn=3, known_by=["민수"])
    with _count_queries() as with_memory_count:
        with_memory = await _build(db_session, room, "민수랑 밀알당 기억나?")
        statements_with_memory = with_memory_count()
    _recall_on(monkeypatch)
    with _count_queries() as recall_on_count:
        await _build(db_session, room, "민수랑 밀알당 기억나?")
        statements_recall_on = recall_on_count()
    monkeypatch.setattr(settings, "memory_episodes_recall", False)
    await db_session.execute(sa.delete(ChatMemoryFact).where(ChatMemoryFact.chat_room_id == room.room_id))
    await db_session.execute(sa.delete(ChatMemoryEpisode).where(ChatMemoryEpisode.chat_room_id == room.room_id))
    await db_session.commit()
    with _count_queries() as without_memory_count:
        without_memory = await _build(db_session, room, "민수랑 밀알당 기억나?")
        statements_without_memory = without_memory_count()

    assert with_memory.prompt == without_memory.prompt
    assert statements_with_memory == statements_without_memory
    # 켠 턴: SAVEPOINT·장면 후보·사실 행·줄 렌더·RELEASE 다섯 문장이 더해진다.
    assert statements_recall_on == statements_with_memory + 5
