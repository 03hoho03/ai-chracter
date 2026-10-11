"""시제품 회상 점수 — 기술 명세 「검색」 절의 사례표(①·①변형·②·③·④·⑥)를 값으로 단언하고, 임계·흔한 명사 비율·에피소드
하한·1자 명사 어절 경계는 경계 값을 둘 이상 쓴다(한 값만 쓰면 그 값에서 우연히 같아지는 버그를 못 본다).

사례표의 공통 조건: 에피소드 N = 30, w_rare = ln(31/2) + 1 ≈ 3.74, 중요도 3(+0.025), 최근성은 끝 턴/현재 턴 300."""

import math
import uuid

import pytest

from api.db.models import ChatMessage, ChatMessageRole

from memory_eval.recall_offline import Episode
from memory_eval.prototype_extract import PrototypeEpisode, PrototypeResult, Window, episode_rows, truncate_detail
from memory_eval.prototype_recall import (
    EpisodeNouns,
    Params,
    Query,
    Scored,
    episode_nouns_substring,
    query_nouns_rule,
    query_nouns_substring,
    recall_cue,
    retrieve_e,
    rule_tokens,
    episode_nouns_rule,
    score_episodes,
    select_injected,
    time_cue,
)

W_RARE = math.log(31 / 2) + 1


def _w(df: int, n: int = 30) -> float:
    return math.log((n + 1) / (df + 1)) + 1


def _filler(
    count: int, *, start: int = 0, snapshot: int = 1, nouns: frozenset[str] = frozenset()
) -> list[EpisodeNouns]:
    return [
        EpisodeNouns(id=f"f{start + i}", nouns=nouns, importance=3, end_turn=40 + start + i, snapshot=snapshot)
        for i in range(count)
    ]


def _with_df(noun: str, df: int, *, start: int) -> list[EpisodeNouns]:
    return _filler(df, start=start, nouns=frozenset({noun}))


def _by_id(scored: list[Scored]) -> dict[str, Scored]:
    return {s.id: s for s in scored}


def test_case1_rare_noun_injects_gold_only() -> None:
    current = frozenset(f"현재{i}" for i in range(20))
    gold = EpisodeNouns(id="G", nouns=frozenset({"베이커리", "크루아상"}), importance=3, end_turn=30, snapshot=1)
    recent = EpisodeNouns(id="R", nouns=current, importance=3, end_turn=285, snapshot=28)
    rows = [gold, recent, *_filler(28, snapshot=2)]
    query = Query(user=frozenset({"베이커리"}), assistant=current, time_cue=False)
    scored = _by_id(score_episodes(rows, query, current_turn=300, params=Params()))
    assert scored["G"].s == pytest.approx(0.7 + 0.025 + 0.02 * 30 / 300)
    assert scored["R"].s == pytest.approx(0.025 + 0.02 * 285 / 300)
    assert select_injected(
        score_episodes(rows, query, current_turn=300, params=Params()), Params(), recall_cue=True
    ) == ["G"]


def test_case1_variant_same_noun_in_three_scenes_injects_all_three() -> None:
    scenes = [
        EpisodeNouns(id=f"B{i}", nouns=frozenset({"베이커리"}), importance=3, end_turn=30 + i, snapshot=1)
        for i in range(3)
    ]
    rows = [*scenes, *_filler(27, snapshot=2)]
    query = Query(user=frozenset({"베이커리"}), assistant=frozenset(), time_cue=False)
    scored = score_episodes(rows, query, current_turn=300, params=Params())
    by_id = _by_id(scored)
    assert by_id["B0"].s == pytest.approx(0.7 * _w(3) / W_RARE + 0.025 + 0.02 * 30 / 300)
    assert by_id["B0"].s == pytest.approx(0.597, abs=0.001)
    assert sorted(select_injected(scored, Params(), recall_cue=True)) == ["B0", "B1", "B2"]


def test_case2_anaphora_follow_up_uses_assistant_nouns_minus_recent_two_snapshots() -> None:
    # 현재 장면 명사를 최근 두 스냅샷에 반씩 나눠 둔다 — 가장 최근 하나만 빼는 구현이면 R2 의 명사가 남아 R2 가 걸린다.
    current_a = frozenset(f"현재{i}" for i in range(10))
    current_b = frozenset(f"현재{i}" for i in range(10, 20))
    current = current_a | current_b
    gold = EpisodeNouns(id="G", nouns=frozenset({"렌즈", "케이스", "가방"}), importance=3, end_turn=60, snapshot=3)
    bag_only = _with_df("가방", 3, start=100)
    recent = [
        EpisodeNouns(id="R1", nouns=current_a, importance=3, end_turn=290, snapshot=28),
        EpisodeNouns(id="R2", nouns=current_b, importance=3, end_turn=280, snapshot=27),
    ]
    rows = [gold, *bag_only, *recent, *_filler(24, snapshot=2)]
    query = Query(user=frozenset(), assistant=frozenset({"렌즈", "케이스", "가방"}) | current, time_cue=True)
    scored = score_episodes(rows, query, current_turn=300, params=Params())
    by_id = _by_id(scored)
    assert by_id["G"].s == pytest.approx(0.7 + 0.025)
    assert by_id["G"].r == pytest.approx(2 * W_RARE + _w(4) + W_RARE * 0.025 / 0.7)
    assert by_id["G"].r == pytest.approx(10.4, abs=0.1)
    assert by_id["f100"].s == pytest.approx(0.7 * _w(4) / W_RARE + 0.025)
    assert by_id["R1"].overlap == frozenset()
    assert by_id["R2"].overlap == frozenset()
    assert select_injected(scored, Params(), recall_cue=True)[0] == "G"


@pytest.mark.parametrize(
    ("cue", "recalled"), [pytest.param(True, True, id="cue"), pytest.param(False, False, id="no-cue")]
)
def test_case2_assistant_path_needs_time_cue(cue: bool, recalled: bool) -> None:
    gold = EpisodeNouns(id="G", nouns=frozenset({"렌즈"}), importance=3, end_turn=60, snapshot=3)
    rows = [gold, *_filler(27, snapshot=2), *_filler(1, start=50, snapshot=8), *_filler(1, start=60, snapshot=9)]
    query = Query(user=frozenset(), assistant=frozenset({"렌즈"}), time_cue=cue)
    scored = score_episodes(rows, query, current_turn=300, params=Params())
    assert (select_injected(scored, Params(), recall_cue=True) == ["G"]) is recalled


def test_case3_only_common_nouns_has_no_section() -> None:
    rows = [
        *_with_df("민지", 8, start=0),
        *[
            EpisodeNouns(id=f"m{i}", nouns=frozenset({"민지", "촬영"}), importance=3, end_turn=100 + i, snapshot=4)
            for i in range(20)
        ],
        *_filler(2, start=50, snapshot=2),
    ]
    query = Query(user=frozenset({"민지", "촬영"}), assistant=frozenset({"카메라"}), time_cue=False)
    assert score_episodes(rows, query, current_turn=300, params=Params()) == []


def test_case4_common_name_plus_rare_noun_keeps_rare_noun_only() -> None:
    gold = EpisodeNouns(id="G", nouns=frozenset({"민지", "베이커리"}), importance=3, end_turn=30, snapshot=1)
    named = [
        EpisodeNouns(id=f"m{i}", nouns=frozenset({"민지"}), importance=3, end_turn=100 + i, snapshot=4)
        for i in range(27)
    ]
    rows = [gold, *named, *_filler(2, start=60, snapshot=2)]
    query = Query(user=frozenset({"민지", "베이커리"}), assistant=frozenset(), time_cue=True)
    scored = score_episodes(rows, query, current_turn=300, params=Params())
    by_id = _by_id(scored)
    assert by_id["G"].s == pytest.approx(0.7 + 0.025)
    assert by_id["m0"].s == pytest.approx(0.025)
    assert select_injected(scored, Params(), recall_cue=True) == ["G"]


def test_case6_user_query_emptied_by_common_noun_does_not_take_assistant_path() -> None:
    rows = [
        *_with_df("촬영장", 15, start=0),
        EpisodeNouns(id="G", nouns=frozenset({"렌즈"}), importance=3, end_turn=60, snapshot=3),
        *_filler(14, start=40, snapshot=2),
    ]
    query = Query(user=frozenset({"촬영장"}), assistant=frozenset({"렌즈"}), time_cue=True)
    assert score_episodes(rows, query, current_turn=300, params=Params()) == []


@pytest.mark.parametrize(
    ("delta", "injected"),
    [
        pytest.param(-1e-6, True, id="tau-just-below-score"),
        pytest.param(0.0, True, id="tau-equal-score"),
        pytest.param(1e-6, False, id="tau-just-above-score"),
    ],
)
def test_threshold_boundary(delta: float, injected: bool) -> None:
    gold = EpisodeNouns(id="G", nouns=frozenset({"베이커리"}), importance=3, end_turn=30, snapshot=1)
    rows = [gold, *_filler(29, snapshot=2)]
    query = Query(user=frozenset({"베이커리"}), assistant=frozenset(), time_cue=False)
    s = score_episodes(rows, query, current_turn=300, params=Params())[0].s
    assert s == pytest.approx(0.7 + 0.025 + 0.02 * 30 / 300)
    params = Params(tau=s + delta)
    assert (
        select_injected(score_episodes(rows, query, current_turn=300, params=params), params, recall_cue=True) == ["G"]
    ) is injected


@pytest.mark.parametrize(
    ("df", "kept"),
    [pytest.param(9, True, id="df-ratio-equal-0.3-kept"), pytest.param(10, False, id="df-ratio-above-0.3-dropped")],
)
def test_common_ratio_boundary(df: int, kept: bool) -> None:
    rows = [*_with_df("카페", df, start=0), *_filler(30 - df, start=100, snapshot=2)]
    query = Query(user=frozenset({"카페"}), assistant=frozenset(), time_cue=False)
    scored = score_episodes(rows, query, current_turn=300, params=Params())
    assert bool(scored) is kept
    if kept:
        assert _by_id(scored)["f0"].s == pytest.approx(0.7 * _w(9) / W_RARE + 0.025 + 0.02 * 40 / 300)


def test_common_ratio_is_a_parameter() -> None:
    rows = [*_with_df("카페", 10, start=0), *_filler(20, start=100, snapshot=2)]
    query = Query(user=frozenset({"카페"}), assistant=frozenset(), time_cue=False)
    assert score_episodes(rows, query, current_turn=300, params=Params(common_ratio=0.3)) == []
    assert score_episodes(rows, query, current_turn=300, params=Params(common_ratio=0.4)) != []


@pytest.mark.parametrize(("n", "active"), [pytest.param(4, False, id="N4-off"), pytest.param(5, True, id="N5-on")])
def test_min_episode_boundary(n: int, active: bool) -> None:
    gold = EpisodeNouns(id="G", nouns=frozenset({"베이커리"}), importance=3, end_turn=30, snapshot=1)
    rows = [gold, *_filler(n - 1, snapshot=2)]
    query = Query(user=frozenset({"베이커리"}), assistant=frozenset(), time_cue=False)
    assert bool(score_episodes(rows, query, current_turn=300, params=Params())) is active


def test_inject_at_most_three_ranked_by_uncapped_score() -> None:
    both = EpisodeNouns(id="both", nouns=frozenset({"렌즈", "케이스"}), importance=1, end_turn=10, snapshot=1)
    singles = [
        EpisodeNouns(id=f"s{i}", nouns=frozenset({f"단서{i}"}), importance=5, end_turn=200 + i, snapshot=5)
        for i in range(4)
    ]
    rows = [both, *singles, *_filler(25, snapshot=2)]
    query = Query(
        user=frozenset({"렌즈", "케이스", "단서0", "단서1", "단서2", "단서3"}), assistant=frozenset(), time_cue=False
    )
    injected = select_injected(
        score_episodes(rows, query, current_turn=300, params=Params()), Params(), recall_cue=True
    )
    assert len(injected) == 3
    assert injected[0] == "both"


def test_keyword_similarity_counts_only_above_threshold() -> None:
    gold = EpisodeNouns(id="G", nouns=frozenset({"베이커리"}), importance=3, end_turn=30, snapshot=1, kw_sim=0.6)
    other = EpisodeNouns(id="O", nouns=frozenset({"베이커리"}), importance=3, end_turn=30, snapshot=1, kw_sim=0.4)
    rows = [gold, other, *_filler(28, snapshot=2)]
    query = Query(user=frozenset({"베이커리"}), assistant=frozenset(), time_cue=False)
    params = Params(use_kw=True, kw_threshold=0.5)
    by_id = _by_id(score_episodes(rows, query, current_turn=300, params=params))
    base = 0.7 * _w(2) / W_RARE + 0.025 + 0.002
    assert by_id["G"].s == pytest.approx(base + 0.3 * 0.6)
    assert by_id["O"].s == pytest.approx(base)


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        pytest.param("빵 먹으러 가자", True, id="bare"),
        pytest.param("그때 빵을 샀지", True, id="with-particle"),
        pytest.param("빵.", True, id="before-punctuation"),
        pytest.param("빵집 가자", False, id="inside-longer-word"),
        pytest.param("식빵 사자", False, id="word-final-inside"),
    ],
)
def test_one_char_noun_matches_only_at_word_boundary(text: str, hit: bool) -> None:
    query = query_nouns_substring(text, "", episode_nouns=frozenset({"빵"}), names=())
    assert ("빵" in query.user) is hit


def test_substring_query_matches_two_char_nouns_inside_words_and_splits_user_from_assistant() -> None:
    query = query_nouns_substring(
        "그 베이커리에서 뭐 먹었지?",
        "가방에 넣어 둔 렌즈 이야기",
        episode_nouns=frozenset({"베이커리", "렌즈", "가방"}),
        names=(),
    )
    assert query.user == frozenset({"베이커리"})
    assert query.assistant == frozenset({"렌즈", "가방"})
    assert query.time_cue is False


def test_episode_nouns_split_on_spaces_and_keep_one_char() -> None:
    assert episode_nouns_substring(["렌즈 케이스", "빵", "기억", "  가방! "]) == frozenset(
        {"렌즈", "케이스", "빵", "가방"}
    )


@pytest.mark.parametrize(
    ("text", "cue"),
    [
        pytest.param("그때 그거 어디 뒀더라?", True, id="geuttae"),
        pytest.param("우리 처음 만난 데 기억나?", True, id="cheoeum"),
        pytest.param("그거 어디 뒀더라?", False, id="no-cue"),
    ],
)
def test_time_cue(text: str, cue: bool) -> None:
    assert time_cue(text) is cue


def test_kiwi_query_nouns() -> None:
    pytest.importorskip("kiwipiepy")
    from memory_eval.prototype_recall import query_nouns_kiwi

    query = query_nouns_kiwi("우리 그 베이커리에서 뭐 먹었지?", "가방에 넣어 둔 렌즈 케이스", names=())
    assert query.user == frozenset({"베이커리"})
    assert {"가방", "렌즈", "케이스"} <= query.assistant
    empty = query_nouns_kiwi("그때 그거 어디 뒀더라?", "", names=())
    assert empty.user == frozenset()
    assert empty.time_cue is True


# ---------------------------------------------------------------- 추출 결과 정규화(서버가 저장 전에 하는 것과 같게)


def _window(n_lines: int = 4) -> Window:
    roles = [ChatMessageRole.USER, ChatMessageRole.ASSISTANT] * (n_lines // 2)
    return Window(
        snapshot_id=uuid.UUID(int=1),
        messages=[ChatMessage(role=r, content="") for r in roles],
        turn_before=10,
        fold_turn=20,
    )


def _item(detail: str, *, title: str = "장면") -> PrototypeEpisode:
    return PrototypeEpisode(
        title=title,
        detail=detail,
        nouns=[],
        keywords=[],
        asserted_by="narration",
        evidence=[],
        importance=3,
        start_line=1,
        end_line=2,
    )


def test_episode_rows_drop_empty_detail_before_the_ten_cap() -> None:
    items = [_item(""), *[_item(f"본문{i}") for i in range(11)]]
    rows = episode_rows(_window(), PrototypeResult(episodes=items), version="t")
    assert [r["detail"] for r in rows] == [f"본문{i}" for i in range(10)]
    assert (rows[0]["rawCount"], rows[0]["rawEmpty"]) == (12, 1)


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        pytest.param("가" * 300, "가" * 300, id="at-limit-untouched"),
        pytest.param("가" * 290 + "갔다. " + "나" * 20, "가" * 290 + "갔다.", id="cut-after-sentence-end"),
        pytest.param("가" * 301, "가" * 300, id="no-sentence-end-cut-by-char"),
    ],
)
def test_detail_is_cut_to_300_chars(detail: str, expected: str) -> None:
    assert truncate_detail(detail) == expected


def test_title_is_cut_to_60_chars() -> None:
    rows = episode_rows(_window(), PrototypeResult(episodes=[_item("본문", title="제" * 61)]), version="t")
    assert rows[0]["title"] == "제" * 60
    assert rows[0]["truncated"] is False


# ---------------------------------------------------------------- 보통 턴 주입 상한(회상 단서가 없는 턴은 최고점 1개)


def _three_above_threshold() -> list[Scored]:
    scenes = [
        EpisodeNouns(id=f"B{i}", nouns=frozenset({"베이커리"}), importance=3, end_turn=30 + i, snapshot=1)
        for i in range(3)
    ]
    query = Query(user=frozenset({"베이커리"}), assistant=frozenset(), time_cue=False)
    return score_episodes([*scenes, *_filler(27, snapshot=2)], query, current_turn=300, params=Params())


@pytest.mark.parametrize(
    ("cue", "expected"),
    [
        pytest.param(True, ["B2", "B1", "B0"], id="recall-cue-three"),
        pytest.param(False, ["B2"], id="plain-turn-top-one"),
    ],
)
def test_plain_turn_injects_only_the_top_episode(cue: bool, expected: list[str]) -> None:
    assert select_injected(_three_above_threshold(), Params(), recall_cue=cue) == expected


def test_plain_turn_cap_is_a_parameter() -> None:
    assert len(select_injected(_three_above_threshold(), Params(max_inject_plain=2), recall_cue=False)) == 2


def test_plain_turn_below_threshold_injects_nothing() -> None:
    assert select_injected(_three_above_threshold(), Params(tau=0.99), recall_cue=False) == []


@pytest.mark.parametrize(
    ("text", "cue"),
    [
        pytest.param("태민이랑 빵 먹으러 갔던 데, 이름 뭐였지?", True, id="mwoyeotji"),
        pytest.param("지각하면 문 잠근다던 회의, 몇 시 시작이었지?", True, id="eotji"),
        pytest.param("그때 거기 어디라고 했더라?", True, id="time-cue"),
        pytest.param("그거 기억 안 나?", True, id="gieok-an"),
        pytest.param("내가 군대에서 취사병이었다고 말한 적 있었나?", True, id="malhan-jeok"),
        pytest.param("전에 말한 그 카페 가자", True, id="jeone-malhan"),
        pytest.param("세빈이 오이 먹던가?", False, id="no-marker"),
        pytest.param("오늘 촬영 진짜 힘들었지만 재밌었어", False, id="past-tense-statement"),
    ],
)
def test_recall_cue(text: str, cue: bool) -> None:
    assert recall_cue(text) is cue


# ---------------------------------------------------------------- 형태소기 없는 결정론 보충(조사·어미 떼기)


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        pytest.param("정류장에서 카메라를 들고", ["정류장", "카메라", "들고"], id="strip-particles"),
        pytest.param("도희에게 우비랑 렌즈까지", ["도희", "우비", "렌즈"], id="two-char-particles"),
        pytest.param("빵. 차를", [], id="drop-one-char"),
        pytest.param("가방이, 「밀알당」으로!", ["가방", "밀알당"], id="punctuation"),
        pytest.param("가방이 가방을", ["가방"], id="dedupe"),
    ],
)
def test_rule_tokens(text: str, tokens: list[str]) -> None:
    assert rule_tokens(text) == tokens


def test_rule_tokens_drop_stopwords() -> None:
    assert rule_tokens("우리 처음 기억이 정류장") == ["정류장"]


def test_episode_nouns_rule_merges_llm_pieces_and_body_tokens() -> None:
    nouns = episode_nouns_rule(["렌즈 케이스", "빵"], "편의점 장면", "도희가 편의점에서 우비를 샀다")
    assert {"렌즈", "케이스", "빵", "편의점", "장면", "도희", "우비", "샀다"} == nouns


def test_query_nouns_rule_tokenizes_user_and_matches_one_char_nouns_at_word_boundary() -> None:
    query = query_nouns_rule(
        "빵 먹으러 정류장에서 만났지?", "가방에 렌즈", episode_nouns=frozenset({"빵", "정류장"}), names=()
    )
    assert {"빵", "정류장", "먹으러", "만났지"} == query.user
    assert {"가방", "렌즈"} == query.assistant


def _episode(eid: str, detail: str, *, end_turn: int, snapshot_turn: int) -> Episode:
    return Episode(
        id=eid,
        start_turn=end_turn,
        end_turn=end_turn,
        title="장면",
        detail=detail,
        asserted_by="narration",
        nouns=(),
        importance=3,
        available_from_turn=snapshot_turn,
    )


def test_retrieve_e_tokenizes_body_without_morphology_and_caps_plain_turns() -> None:
    episodes = [
        _episode("G", "태민이랑 밀알당에서 소금빵을 먹었다", end_turn=12, snapshot_turn=31),
        *[_episode(f"o{i}", f"동아리방에서 회의{i}를 했다", end_turn=20 + i, snapshot_turn=41) for i in range(6)],
    ]
    asked = retrieve_e(episodes, user_text="밀알당에서 뭐 먹었지?", previous_assistant="", current_turn=300)
    assert [r.episode_id for r in asked if r.injected] == ["G"]
    plain = retrieve_e(episodes, user_text="회의0 회의1 회의2 다 끝났어", previous_assistant="", current_turn=300)
    assert sum(r.injected for r in plain) == 1
