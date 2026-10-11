"""평가 하네스의 순수 로직 — 체크포인트 지문, 프로브 실패 처리, 대본 기계 검사, 오프라인 회상 질의, 출처 귀속, 예산.

LLM·DB·서버 없이 돈다. 실제 실행 절차(템플릿 복원·서버 재기동·드라이버 호출)는 이 함수들의 판정을 따른다."""

from pathlib import Path
from typing import Any

import pytest

from memory_eval.attribution import attribute
from memory_eval.checkpoint import ensure_eval_db_name, fingerprint_diff, template_db_name
from memory_eval.ledger import BudgetExceededError, Ledger, budget_estimate, cost_usd
from memory_eval.plants import PlantSet, opus_probes, recompute_split
from memory_eval.probe import Attempt, BurstPacer, next_action, should_halt
from memory_eval.recall_offline import Episode, Ranked, build_queries, evaluate_query, gold_episode_ids
from memory_eval.transcript import LengthRule, ScriptTurn, check_script


def _plant(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "obj01",
        "category": "물건",
        "plantTurn": 3,
        "speaker": {"line": "assistant", "who": "태민", "assertedBy": "character"},
        "keywords": ["펭귄"],
        "answerKeys": [["펭귄"]],
        "cueNouns": ["열쇠고리"],
        "questionForm": "direct",
        "question": "태민이 달아 준 열쇠고리 무슨 동물이었지?",
        "probeCheckpoints": {"opus": [50], "offline": [50]},
        "split": "dev",
        "metrics": {"MR1": True, "MA1_pair": True},
        "reMentionTurns": [],
    }
    base.update(overrides)
    return base


def _abstain(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "abs01",
        "category": "기권",
        "question": "우리 같이 갔던 노래방 이름 뭐였지?",
        "banned": ["노래방"],
        "probeCheckpoints": {"opus": [50], "offline": [50]},
        "split": "dev",
    }
    base.update(overrides)
    return base


def _plant_set(plants: list[dict[str, Any]], abstains: list[dict[str, Any]] | None = None) -> PlantSet:
    return PlantSet(raw={"seed": 20261011}, plants=plants, abstains=abstains or [])


def _script(n: int, *, overrides: dict[int, tuple[str, str]] | None = None) -> list[ScriptTurn]:
    user = "그래 좋아 그럼 다 같이 동아리방으로 가 보자고 다들"
    narrator = "가" * 200
    turns = [ScriptTurn(turn=t, user=user, assistant=narrator) for t in range(1, n + 1)]
    for t, (u, a) in (overrides or {}).items():
        turns[t - 1] = ScriptTurn(turn=t, user=u, assistant=a)
    return turns


_RULE = LengthRule(user=(20, 120), narrator=(150, 350))


# ---------------------------------------------------------------- 체크포인트


def test_fingerprint_diff_lists_every_changed_field() -> None:
    frozen = {"turnCount": 50, "endingReached": False, "stats": {"a": "3"}, "memoryVersion": 4, "episodeCount": None}
    assert fingerprint_diff(frozen, dict(frozen)) == []
    drifted = {**frozen, "turnCount": 51, "stats": {"a": "4"}}
    diffs = fingerprint_diff(frozen, drifted)
    assert len(diffs) == 2
    assert any(d.startswith("turnCount") for d in diffs)
    assert any(d.startswith("stats") for d in diffs)


def test_fingerprint_diff_treats_missing_field_as_difference() -> None:
    assert fingerprint_diff({"turnCount": 50}, {"turnCount": 50, "cursor": None}) == [
        "cursor: 체크포인트 없음 → 지금 None"
    ]


def test_only_prefixed_databases_can_be_dropped_or_templated() -> None:
    assert template_db_name(50) == "lm_eval_cp50_frozen"
    ensure_eval_db_name("lm_eval_work")
    for bad in ("ai_character_chat", "ai_character_chat_test", "postgres", "lm_evalwork"):
        with pytest.raises(SystemExit):
            ensure_eval_db_name(bad)


# ---------------------------------------------------------------- 프로브 실패 처리


def test_success_is_accepted() -> None:
    assert next_action([Attempt(exit_code=0)]).kind == "accept"


def test_burst_waits_sixty_seconds_and_gives_up_after_three_retries() -> None:
    first = next_action([Attempt(exit_code=4)])
    assert (first.kind, first.wait_seconds) == ("retry", 60)
    assert next_action([Attempt(exit_code=4)] * 3).kind == "retry"
    assert next_action([Attempt(exit_code=4)] * 4).kind == "unprobeable"


def test_clover_shortage_tops_up_and_gives_up_after_three_retries() -> None:
    action = next_action([Attempt(exit_code=7)])
    assert (action.kind, action.top_up) == ("retry", True)
    assert next_action([Attempt(exit_code=7)] * 4).kind == "unprobeable"


def test_ending_reached_keeps_a_saved_response_and_retries_an_unsaved_one_twice() -> None:
    assert next_action([Attempt(exit_code=3, response_saved=True)]).kind == "accept"
    assert next_action([Attempt(exit_code=3, response_saved=False)] * 2).kind == "retry"
    assert next_action([Attempt(exit_code=3, response_saved=False)] * 3).kind == "unprobeable"


def test_other_errors_retry_twice_unless_the_stack_is_inside_recall_code() -> None:
    assert next_action([Attempt(exit_code=1)] * 2).kind == "retry"
    assert next_action([Attempt(exit_code=1)] * 3).kind == "unprobeable"
    assert next_action([Attempt(exit_code=1, recall_stack=True)]).kind == "count_wrong"


def test_retry_budgets_are_counted_per_reason() -> None:
    # 버스트 셋을 쓴 뒤의 다른 오류는 자기 몫(2회)이 따로 남아 있다.
    history = [Attempt(exit_code=4)] * 3 + [Attempt(exit_code=1)]
    assert next_action(history).kind == "retry"


def test_run_halts_when_unprobeable_exceeds_five_percent() -> None:
    assert not should_halt(3, 56)
    assert should_halt(4, 56)
    assert not should_halt(0, 0)


def test_burst_pacer_keeps_sends_under_the_per_minute_limit() -> None:
    pacer = BurstPacer(limit=2, window_seconds=60.0)
    assert pacer.wait_before_send(now=0.0) == 0.0
    pacer.record(0.0)
    pacer.record(10.0)
    assert pacer.wait_before_send(now=20.0) == pytest.approx(40.0)
    assert pacer.wait_before_send(now=61.0) == 0.0


# ---------------------------------------------------------------- 분할 다시 계산


def test_split_rules_recompute_category_and_role_strata() -> None:
    plants = [
        _plant(id="obj01", probeCheckpoints={"opus": [50], "offline": [50]}),
        _plant(id="obj02", probeCheckpoints={"opus": [], "offline": [50]}),
        _plant(id="spk01", category="화자"),
        _plant(id="spk02", category="화자"),
    ]
    abstains = [_abstain(id="abs01"), _abstain(id="abs02")]
    by_category = recompute_split(_plant_set(plants, abstains), rule="category", seed=1)
    by_role = recompute_split(_plant_set(plants, abstains), rule="role", seed=1)
    assert set(by_category) == set(by_role) == {"obj01", "obj02", "spk01", "spk02", "abs01", "abs02"}
    # 역할 층에서는 Opus 짝 대상(obj01)과 아닌 것(obj02)이 다른 층이라 둘 다 홀로 개발로 간다.
    assert by_role["obj01"] == by_role["obj02"] == "dev"
    # 범주 층에서는 둘이 한 층이라 하나만 개발이다.
    assert sorted([by_category["obj01"], by_category["obj02"]]) == ["dev", "test"]


# ---------------------------------------------------------------- 대본 기계 검사


def test_clean_script_has_no_violations() -> None:
    plants = [_plant(plantTurn=3, probeCheckpoints={"opus": [50], "offline": [50]})]
    script = _script(
        50,
        overrides={
            3: ("이거 귀엽다 고마워 태민아 잘 달고 다닐게 정말로", "태민이 펭귄 열쇠고리를 달아 준다." + "나" * 160)
        },
    )
    report = check_script(script, _plant_set(plants), work_text="", rule=_RULE, expected_turns=50)
    assert report["violations"] == []
    assert report["keywordTable"][0]["turns"] == [3]


def _rules(report: dict[str, Any]) -> set[str]:
    return {v["rule"] for v in report["violations"]}


def test_script_violations_are_named_by_rule() -> None:
    plants = [_plant(plantTurn=3, probeCheckpoints={"opus": [50], "offline": [50]})]
    abstains = [_abstain()]
    good_plant_line = "태민이 펭귄 열쇠고리를 달아 준다." + "나" * 160
    cases: dict[str, list[ScriptTurn]] = {
        "심는 줄에 핵심어 없음": _script(50),
        "핵심어 재등장": _script(
            50,
            overrides={
                3: ("고마워 태민아 정말 잘 달고 다닐게 진짜로", good_plant_line),
                10: ("펭귄 또 보고 싶다 진짜 귀엽더라 그치 응", "다" * 200),
            },
        ),
        "원문 윈도 후보 구간에 핵심어": _script(
            50,
            overrides={
                3: ("고마워 태민아 정말 잘 달고 다닐게 진짜로", good_plant_line),
                40: ("그 펭귄 아직 있지 가방에 달려 있잖아 봐", "다" * 200),
            },
        ),
        "사용자 줄 길이": _script(50, overrides={3: ("응", good_plant_line)}),
        "진행자 줄 길이": _script(50, overrides={3: ("고마워 태민아 정말 잘 달고 다닐게 진짜로", "펭귄")}),
        "기권 금지 낱말": _script(
            50,
            overrides={
                3: ("고마워 태민아 정말 잘 달고 다닐게 진짜로", good_plant_line),
                5: ("오늘 노래방 갈래 다 같이 가면 재밌을 거야", "다" * 200),
            },
        ),
        "체크포인트 진행자 줄에 핵심어·단서": _script(
            50,
            overrides={
                3: ("고마워 태민아 정말 잘 달고 다닐게 진짜로", good_plant_line),
                50: ("다들 모였네 오늘 회의 시작하자 그럼 이제", "열쇠고리를 만지작거린다." + "다" * 200),
            },
        ),
    }
    for rule, script in cases.items():
        report = check_script(script, _plant_set(plants, abstains), work_text="", rule=_RULE, expected_turns=50)
        assert rule in _rules(report), rule


def test_keyword_in_work_text_question_or_context_line_is_a_violation() -> None:
    good = _script(
        50,
        overrides={3: ("고마워 태민아 정말 잘 달고 다닐게 진짜로", "태민이 펭귄 열쇠고리를 달아 준다." + "나" * 160)},
    )
    in_question = _plant(question="그 펭귄 뭐였지?")
    in_context = _plant(
        questionForm="anaphora",
        question="그때 그거 뭐였지?",
        contextTurn={"cue": ["열쇠고리"], "userLine": "펭귄 열쇠고리 생각나네"},
    )
    assert "작품 글에 핵심어" in _rules(
        check_script(good, _plant_set([_plant()]), work_text="펭귄", rule=_RULE, expected_turns=50)
    )
    assert "질문에 핵심어" in _rules(
        check_script(good, _plant_set([in_question]), work_text="", rule=_RULE, expected_turns=50)
    )
    assert "맥락 문장에 핵심어" in _rules(
        check_script(good, _plant_set([in_context]), work_text="", rule=_RULE, expected_turns=50)
    )
    waived = _plant(question="그 펭귄 뭐였지?", exclusionWaiver="의도된 예외")
    assert "질문에 핵심어" not in _rules(
        check_script(good, _plant_set([waived]), work_text="", rule=_RULE, expected_turns=50)
    )


def test_listed_re_mention_is_reported_but_not_a_violation() -> None:
    plants = [_plant(plantTurn=3, reMentionTurns=[10], probeCheckpoints={"opus": [], "offline": [50]})]
    script = _script(
        50,
        overrides={
            3: ("고마워 태민아 정말 잘 달고 다닐게 진짜로", "태민이 펭귄 열쇠고리를 달아 준다." + "나" * 160),
            10: ("펭귄 또 보고 싶다 진짜 귀엽더라 그치 응", "다" * 200),
        },
    )
    report = check_script(script, _plant_set(plants), work_text="", rule=_RULE, expected_turns=50)
    assert "핵심어 재등장" not in _rules(report)
    assert report["keywordTable"][0]["turns"] == [3, 10]


def test_missing_or_out_of_order_turns_are_violations() -> None:
    script = _script(5)
    del script[2]
    report = check_script(script, _plant_set([]), work_text="", rule=_RULE, expected_turns=5)
    assert "턴 번호" in _rules(report)


# ---------------------------------------------------------------- 오프라인 회상 질의


def _anaphora_plant() -> dict[str, Any]:
    return _plant(
        id="obj03",
        plantTurn=14,
        questionForm="anaphora",
        question="그때 내가 빌려준 거 뭐였더라?",
        keywords=["우비"],
        answerKeys=[["우비"]],
        contextTurn={"cue": ["소나기"], "userLine": "비 오니까 소나기 쏟아졌던 날 생각난다."},
        counterfactualQuestion="그때 빌려준 거 뭐였더라?",
        split="test",
    )


def test_one_turn_question_pairs_with_the_checkpoint_last_narrator_line() -> None:
    script = _script(50, overrides={50: ("다들 모였네 오늘 회의 시작하자 그럼 이제", "마지막 진행자 줄")})
    queries = build_queries(_plant_set([_plant()]), script, 50, splits={"dev"})
    assert [(q.kind, q.user_text, q.previous_assistant, q.previous_source) for q in queries] == [
        ("question", _plant()["question"], "마지막 진행자 줄", "checkpoint_line")
    ]


def test_anaphora_question_uses_context_response_when_measured_and_the_context_line_as_proxy_otherwise() -> None:
    script = _script(50, overrides={50: ("다들 모였네 오늘 회의 시작하자 그럼 이제", "마지막 진행자 줄")})
    plants = _plant_set([_anaphora_plant()])
    proxy = {q.kind: q for q in build_queries(plants, script, 50, splits={"test"})}
    assert proxy["context"].user_text == "비 오니까 소나기 쏟아졌던 날 생각난다."
    assert proxy["context"].previous_assistant == "마지막 진행자 줄"
    assert proxy["question"].previous_assistant == "비 오니까 소나기 쏟아졌던 날 생각난다."
    assert proxy["question"].previous_source == "context_proxy"
    assert proxy["counterfactual"].user_text == "그때 빌려준 거 뭐였더라?"
    measured = {
        q.kind: q
        for q in build_queries(plants, script, 50, splits={"test"}, context_responses={("obj03", 50): "우비 이야기"})
    }
    assert measured["question"].previous_assistant == "우비 이야기"
    assert measured["question"].previous_source == "context_response"


def test_queries_only_cover_the_requested_split_and_offline_checkpoints() -> None:
    plants = _plant_set(
        [_plant(), _anaphora_plant(), _plant(id="obj09", probeCheckpoints={"opus": [], "offline": [300]})], [_abstain()]
    )
    script = _script(50)
    dev = build_queries(plants, script, 50, splits={"dev"})
    assert {q.item_id for q in dev} == {"obj01", "abs01"}
    assert {q.kind for q in dev if q.item_id == "abs01"} == {"abstain"}


def test_gold_episode_must_cover_the_plant_turn_and_carry_the_answer() -> None:
    plant = _plant(plantTurn=14, answerKeys=[["우비"]])
    episodes = [
        Episode(
            id="covers-with-key", start_turn=11, end_turn=15, title="소나기", detail="우비를 건넸다", asserted_by="user"
        ),
        Episode(
            id="covers-no-key", start_turn=14, end_turn=14, title="리딩", detail="첫 리딩", asserted_by="narration"
        ),
        Episode(id="key-elsewhere", start_turn=20, end_turn=22, title="비", detail="우비 이야기", asserted_by="user"),
    ]
    assert gold_episode_ids(plant, episodes) == ["covers-with-key"]


def test_recall_uses_injected_set_for_at_3_and_raw_rank_for_at_10() -> None:
    ranked = [
        Ranked(episode_id="e1", score=0.9, injected=True),
        Ranked(episode_id="e2", score=0.5, injected=True),
        Ranked(episode_id="gold", score=0.3, injected=False),
    ]
    result = evaluate_query(ranked, gold=["gold"])
    assert result["recall3"] is False
    assert result["recall10"] is True
    assert result["goldRank"] == 3
    assert result["injected"] == ["e1", "e2"]


def test_query_without_gold_is_excluded_from_recall() -> None:
    result = evaluate_query([Ranked(episode_id="e1", score=0.9, injected=True)], gold=[])
    assert result["recall3"] is None and result["recall10"] is None


# ---------------------------------------------------------------- 출처 귀속


_HEADER = "[지난 기억 — 참고]"


def test_attribution_names_each_place_the_answer_was_in() -> None:
    prompt = f"노트: 메모\n요약 본문 우비 있음\n대화 기록...\n{_HEADER}\n- 소나기: 우비를 건넸다\n\n이번 입력"
    result = attribute(
        [["우비"]], prompt, note="메모", summary="요약 본문 우비 있음", recall_header=_HEADER, static_texts=[]
    )
    assert result["places"] == ["요약", "회상"]


def test_attribution_reports_nowhere_and_raw_window() -> None:
    prompt = f"대화 기록 우비 원문\n{_HEADER}\n- 다른 장면\n\n이번 입력"
    assert attribute([["우비"]], prompt, note="", summary="", recall_header=_HEADER, static_texts=[])["places"] == [
        "원문 윈도"
    ]
    assert attribute([["펭귄"]], prompt, note="", summary="", recall_header=_HEADER, static_texts=[])["places"] == [
        "어디에도 없음"
    ]


def test_attribution_refuses_when_summary_is_not_in_the_dump() -> None:
    result = attribute([["우비"]], "다른 글", note="", summary="요약", recall_header=_HEADER, static_texts=[])
    assert "unattributable" in result


def test_attribution_marks_answers_carried_by_the_context_turn_response() -> None:
    prompt = "대화 기록: 진행자: 그때 우비 빌려줬잖아\n이번 입력"
    result = attribute(
        [["우비"]],
        prompt,
        note="",
        summary="",
        recall_header=_HEADER,
        static_texts=[],
        context_response="그때 우비 빌려줬잖아",
    )
    assert result["places"] == ["원문 창(맥락 턴)"]


# ---------------------------------------------------------------- 원가·예산


def test_cost_uses_cache_and_write_prices_and_rejects_unknown_models() -> None:
    cost = cost_usd(
        "claude-opus-5-5",
        input_tokens=10_000,
        cached_tokens=6_000,
        cache_write_tokens=2_000,
        output_tokens=500,
        thoughts_tokens=0,
    )
    assert cost == pytest.approx((2_000 * 4.0 + 6_000 * 0.2 + 2_000 * 5.0 + 500 * 20.0) / 1e6)
    haiku = cost_usd(
        "claude-haiku-5-5",
        input_tokens=1_000,
        cached_tokens=0,
        cache_write_tokens=0,
        output_tokens=100,
        thoughts_tokens=0,
    )
    assert haiku == pytest.approx((1_000 * 0.10 + 100 * 0.50) / 1e6)
    with pytest.raises(KeyError):
        cost_usd(
            "no-such-model", input_tokens=1, cached_tokens=0, cache_write_tokens=0, output_tokens=0, thoughts_tokens=0
        )


def test_ledger_refuses_a_call_that_would_cross_the_cap(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=1.0)
    ledger.append(
        stage="s4",
        call_site="chat_generate",
        model="claude-opus-5-5",
        input_tokens=100_000,
        cached_tokens=0,
        cache_write_tokens=0,
        output_tokens=10_000,
        thoughts_tokens=0,
    )
    assert ledger.total_usd() == pytest.approx(0.6)
    ledger.check_headroom(0.39)
    with pytest.raises(BudgetExceededError):
        ledger.check_headroom(0.41)
    # 다시 열어도 누적이 이어진다.
    assert Ledger(tmp_path / "ledger.jsonl", cap_usd=1.0).total_usd() == pytest.approx(0.6)


def test_budget_counts_context_turns_of_two_turn_probes_per_arm() -> None:
    plants = _plant_set(
        [_plant(), _anaphora_plant() | {"probeCheckpoints": {"opus": [50, 300], "offline": [50]}}],
        [_abstain(probeCheckpoints={"opus": [300], "offline": [50]})],
    )
    assert [p.turns for p in opus_probes(plants, 50)] == [
        [_plant()["question"]],
        ["비 오니까 소나기 쏟아졌던 날 생각난다.", "그때 내가 빌려준 거 뭐였더라?"],
    ]
    estimate = budget_estimate(
        plants, arms=3, opus_turn_usd=0.13, server_judgment_turn_usd=0.003, extras={"기타": 1.0}, cap_usd=30.0
    )
    # 문항 4(50: 2, 300: 2) + 두 턴 프로브 맥락 턴 2 = 갈래당 6턴, 세 갈래 18턴.
    assert estimate["opusTurnsPerArm"] == 6
    assert estimate["opusTurns"] == 18
    assert estimate["totalUsd"] == pytest.approx(18 * 0.13 + 18 * 0.003 + 1.0)
    assert estimate["breakEvenOpusTurnUsd"] == pytest.approx((30.0 - 18 * 0.003 - 1.0) / 18)


# ---------------------------------------------------------------- 봉인 전 시험 절반 금지 · 판정 규칙


def test_test_half_requires_the_sealed_v2_preregistration(tmp_path: Path) -> None:
    import hashlib

    from memory_eval.seal import require_seal

    prereg = tmp_path / "preregistration.md"
    sha_file = tmp_path / "preregistration.sha256"
    prereg.write_text("# 사전 등록 (v1.2)\n", encoding="utf-8")
    digest = hashlib.sha256(prereg.read_bytes()).hexdigest()
    sha_file.write_text(f"{digest}  preregistration.md\n", encoding="utf-8")
    require_seal({"dev"}, prereg, seal_sha=None)  # 개발 절반은 봉인 없이 된다
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha=None)
    with pytest.raises(SystemExit):
        require_seal({"dev", "test"}, prereg, seal_sha=digest)  # v2 가 아니다
    prereg.write_text("# 사전 등록 (v2)\n봉인\n", encoding="utf-8")
    sealed = hashlib.sha256(prereg.read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha=sealed)  # 해시 파일이 아직 옛 값
    sha_file.write_text(f"{sealed}  preregistration.md\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha="0" * 64)  # 준 해시가 파일과 다르다
    require_seal({"test"}, prereg, seal_sha=sealed)


def test_speaker_gold_episode_is_judged_by_keywords_not_attribution_keys() -> None:
    plant = _plant(category="화자", plantTurn=8, keywords=["취사병"], answerKeys=[["말한 적 없"], ["태민"]])
    episodes = [
        Episode(
            id="e",
            start_turn=6,
            end_turn=9,
            title="뒤풀이",
            detail="태민이 취사병 이야기를 지어냈다",
            asserted_by="character",
        )
    ]
    assert gold_episode_ids(plant, episodes) == ["e"]


def test_gold_episode_uses_number_normalization() -> None:
    plant = _plant(category="시점", plantTurn=40, answerKeys=[["8시10분"]])
    episodes = [
        Episode(id="e", start_turn=38, end_turn=41, title="첫차", detail="여덟 시 십 분 첫차", asserted_by="character")
    ]
    assert gold_episode_ids(plant, episodes) == ["e"]


def test_direct_passline_halts_below_five_and_drops_designed_failures() -> None:
    from memory_eval.recall_offline import direct_passline

    def row(item: str, recall3: bool | None) -> dict[str, Any]:
        return {
            "item_id": item,
            "kind": "question",
            "form": "direct",
            "checkpoint": 300,
            "split": "test",
            "recall3": recall3,
        }

    plants = _plant_set(
        [_plant(id=f"p{i}", split="test") for i in range(6)]
        + [_plant(id="loc04", split="test", limitProbe={"designedToFail": True})]
    )
    rows = [row(f"p{i}", True) for i in range(4)] + [row("p4", None), row("loc04", False)]
    verdict = direct_passline(rows, plants, threshold=0.7)
    assert verdict["status"] == "halt"
    assert verdict["n"] == 4
    assert verdict["designedToFail"] == ["loc04"]
    rows.append(row("p5", False))
    verdict = direct_passline(rows, plants, threshold=0.7)
    assert (verdict["status"], verdict["n"], verdict["k"]) == ("pass", 5, 4)


def test_leak_needs_both_a_deterministic_hit_and_an_asserted_memory() -> None:
    from memory_eval.judge import leak

    assert leak(hit=True, judged="asserted")
    assert not leak(hit=True, judged="guess")
    assert not leak(hit=False, judged="asserted")
    assert leak(hit=True, judged=None) is None  # 판정 불능은 결정론 부분만 표시한다


def test_tuning_objective_orders_direct_then_anaphora_then_injection_rate_then_larger_tau() -> None:
    from memory_eval.recall_offline import TuningResult, best_tuning

    results = [
        TuningResult(tau=0.30, common_ratio=0.3, direct=0.8, anaphora=0.4, injection_rate=0.3),
        TuningResult(tau=0.35, common_ratio=0.3, direct=0.8, anaphora=0.5, injection_rate=0.4),
        TuningResult(tau=0.40, common_ratio=0.3, direct=0.8, anaphora=0.5, injection_rate=0.2),
        TuningResult(tau=0.45, common_ratio=0.2, direct=0.8, anaphora=0.5, injection_rate=0.2),
        TuningResult(tau=0.60, common_ratio=0.4, direct=0.7, anaphora=0.9, injection_rate=0.0),
    ]
    assert best_tuning(results) == results[3]
