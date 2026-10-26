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
        "question": "우리 같이 갔던 카누장 이름 뭐였지?",
        "banned": ["카누장"],
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
    assert template_db_name(50, "s4") == "lm_eval_s4_cp50_frozen"
    ensure_eval_db_name("lm_eval_work")
    for bad in ("ai_character_chat", "ai_character_chat_test", "postgres", "lm_evalwork", "lm_eval_"):
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
            3: ("이거 귀엽다 고마워 휘솔아 잘 달고 다닐게 정말로", "태민이 펭귄 열쇠고리를 달아 준다." + "나" * 160)
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
                3: ("고마워 휘솔아 정말 잘 달고 다닐게 진짜로", good_plant_line),
                10: ("펭귄 또 보고 싶다 진짜 귀엽더라 그치 응", "다" * 200),
            },
        ),
        "원문 윈도 후보 구간에 핵심어": _script(
            50,
            overrides={
                3: ("고마워 휘솔아 정말 잘 달고 다닐게 진짜로", good_plant_line),
                40: ("그 펭귄 아직 있지 가방에 달려 있잖아 봐", "다" * 200),
            },
        ),
        "사용자 줄 길이": _script(50, overrides={3: ("응", good_plant_line)}),
        "진행자 줄 길이": _script(50, overrides={3: ("고마워 휘솔아 정말 잘 달고 다닐게 진짜로", "펭귄")}),
        "기권 금지 낱말": _script(
            50,
            overrides={
                3: ("고마워 휘솔아 정말 잘 달고 다닐게 진짜로", good_plant_line),
                5: ("오늘 카누장 갈래 다 같이 가면 재밌을 거야", "다" * 200),
            },
        ),
        "체크포인트 진행자 줄에 핵심어·단서": _script(
            50,
            overrides={
                3: ("고마워 휘솔아 정말 잘 달고 다닐게 진짜로", good_plant_line),
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
        overrides={3: ("고마워 휘솔아 정말 잘 달고 다닐게 진짜로", "태민이 펭귄 열쇠고리를 달아 준다." + "나" * 160)},
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
            3: ("고마워 휘솔아 정말 잘 달고 다닐게 진짜로", "태민이 펭귄 열쇠고리를 달아 준다." + "나" * 160),
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


_FACT_HEADER = "[관계와 사실]"
_WINDOW_HEADER = "[대화 기록]"
_USER_LABEL = "사용자"
_ASSISTANT_LABEL = "진행자"


def _guided_prompt() -> str:
    """사실 섹션 안내문이 회상 머리글 이름을 문장 속에서 부르는 프롬프트 — 운영 문안의 모양을 줄인 합성 견본."""
    return (
        "요약: 지난 줄거리\n\n"
        f"{_WINDOW_HEADER}\n진행자: 민지가 무릎을 털었다\n사용자: 괜찮아?\n\n"
        f"{_FACT_HEADER}\n아래 줄이 {_HEADER} 와 다르면 이 줄을 따른다\n- 상영회 · 시작 시각: 7시\n"
        "- 민지 · 비밀: 무릎 부상을 숨긴다 (사용자만 앎)\n\n"
        f"{_HEADER}\n- 소나기: 우비를 건넸다\n\n{_USER_LABEL}: 이번 입력\n{_ASSISTANT_LABEL}:"
    )


def _generation_sections(history_header: str = _WINDOW_HEADER) -> list[Any]:
    """서버 생성 채널의 대화 기록 뒤 섹션들 — 운영 세트의 순서와 모양을 줄인 합성 견본."""
    from api.db.models.prompt import PromptSection

    def section(slot: str, body: str, order: int, *, scope: str = "both", conditional: bool = True) -> PromptSection:
        return PromptSection(
            channel="generation", scope=scope, slot=slot, variant="", body=body, conditional=conditional, order=order
        )

    return [
        section("memory_summary", "[지난 줄거리]\n{memory_summary}", 1),
        section("history", f"{history_header}\n{{history_lines}}", 2),
        section("memory_facts", f"{_FACT_HEADER}\n{{memory_fact_lines}}", 3),
        section("memory_recall", f"{_HEADER}\n{{memory_recall_lines}}", 4),
        section("keyword_notes", "[키워드북]\n{keyword_note_lines}", 5, scope="story"),
        section("situation_notes", "[상황 노트]\n{situation_note_lines}", 6, scope="story"),
        section("shortcut_prompt", "[단축어]\n{shortcut_prompt}", 7, scope="story"),
        section("final_frame", "{user_label}: {user_message}\n{assistant_label}:", 8, conditional=False),
    ]


def _layout(history_header: str = _WINDOW_HEADER) -> Any:
    from memory_eval.attribution import window_layout

    return window_layout(
        _generation_sections(history_header), scope="story", user_label=_USER_LABEL, assistant_label=_ASSISTANT_LABEL
    )


def test_attribution_finds_section_headers_only_at_line_start_even_when_a_guide_names_another_header() -> None:
    def places(keys: list[list[str]]) -> dict[str, Any]:
        return attribute(
            keys, _guided_prompt(), note="", summary="", recall_header=_HEADER, static_texts=[],
            fact_header=_FACT_HEADER, old_keys=[["7시"]],
        )  # fmt: skip

    assert places([["7시"]])["places"] == ["사실"]
    assert places([["7시"]])["factSectionOld"] is True
    assert places([["우비"]])["places"] == ["회상"]


def test_secret_item_attributes_where_the_leak_bundle_sits_apart_from_the_empty_answer_keys() -> None:
    result = attribute(
        [], _guided_prompt(), note="", summary="", recall_header=_HEADER, static_texts=[],
        fact_header=_FACT_HEADER, leak_keys=[["무릎"]],
    )  # fmt: skip
    assert result["places"] == ["어디에도 없음"]  # 판정자 문항이라 정답 묶음이 없다
    assert result["leakPlaces"] == ["사실", "원문 윈도"]
    plain = attribute([["7시"]], _guided_prompt(), note="", summary="", recall_header=_HEADER, static_texts=[])
    assert "leakPlaces" not in plain


def test_secret_item_flags_when_the_leak_bundle_also_sits_in_the_authors_text() -> None:
    """비밀 문항은 정답 묶음이 없어 정답으로 본 작가 글 표시가 늘 거짓이다 — 비밀 묶음으로도 같은 표시를 따로 낸다."""
    authors = ["민지는 무릎 부상을 숨긴 채 상영회를 준비한다"]
    result = attribute(
        [], _guided_prompt(), note="", summary="", recall_header=_HEADER, static_texts=authors,
        fact_header=_FACT_HEADER, leak_keys=[["무릎"]],
    )  # fmt: skip
    assert result["staticTextHit"] is False
    assert result["staticTextLeakHit"] is True
    elsewhere = attribute(
        [], _guided_prompt(), note="", summary="", recall_header=_HEADER, static_texts=["상영회는 7시다"],
        leak_keys=[["무릎"]],
    )  # fmt: skip
    assert elsewhere["staticTextLeakHit"] is False
    plain = attribute([["7시"]], _guided_prompt(), note="", summary="", recall_header=_HEADER, static_texts=authors)
    assert "staticTextLeakHit" not in plain


def test_secret_covariates_mark_content_and_owner_name_per_section_of_the_question_turn() -> None:
    from memory_eval.attribution import secret_covariates

    prompt = _guided_prompt()
    flags = secret_covariates(
        prompt, summary="요약: 지난 줄거리", recall_header=_HEADER, fact_header=_FACT_HEADER,
        layout=_layout(), user_message="이번 입력", leak_keys=[["무릎"]], owner="김민지",
    )  # fmt: skip
    assert list(flags) == ["원문 창", "요약", "사실", "회상"]
    assert flags["원문 창"] == {"content": True, "owner": True, "together": True}
    assert flags["사실"] == {"content": True, "owner": True, "together": True}  # 성 뺀 이름으로도 주인을 찾는다
    assert flags["요약"] == {"content": False, "owner": False, "together": False}
    assert flags["회상"] == {"content": False, "owner": False, "together": False}
    # 표기와 주인이 다른 줄에 있으면 각각은 참이어도 함께는 거짓이다.
    apart = prompt.replace("민지가 무릎을 털었다", "무릎을 털었다").replace("사용자: 괜찮아?", "사용자: 민지 괜찮아?")
    window = secret_covariates(
        apart, summary="", recall_header=_HEADER, fact_header=_FACT_HEADER, layout=_layout(),
        user_message="이번 입력", leak_keys=[["무릎"]], owner="김민지",
    )["원문 창"]  # fmt: skip
    assert window == {"content": True, "owner": True, "together": False}


def test_raw_window_stops_at_every_section_the_server_puts_after_history_even_without_facts_or_recall() -> None:
    """사실·회상이 빈 턴은 두 섹션째 빠진다 — 그때도 원문 창이 키워드북·상황 노트·질문까지 늘어나면 안 된다. 응답 속 빈 줄은
    섹션 경계가 아니다."""
    from api.chat.prompt_builder import render_prompt_channel
    from memory_eval.attribution import secret_covariates, window_section

    values = {
        "memory_summary": "",
        "history_lines": "진행자: 민지가 웃었다\n\n민지가 우산을 접었다\n사용자: 괜찮아?",
        "memory_fact_lines": "",
        "memory_recall_lines": "",
        "keyword_note_lines": "민지는 무릎 부상을 숨긴다",
        "situation_note_lines": "민지가 무릎을 감싼다",
        "shortcut_prompt": "",
        "user_label": _USER_LABEL,
        "user_message": "민지 무릎 괜찮아?",
        "assistant_label": _ASSISTANT_LABEL,
    }
    prompt = render_prompt_channel(_generation_sections(), channel="generation", scope="story", values=values)
    window = window_section(prompt, _layout(), user_message=values["user_message"])
    assert window.startswith(_WINDOW_HEADER) and "우산을 접었다" in window  # 응답 속 빈 줄 뒤도 원문 창이다
    assert "[키워드북]" not in window and "무릎" not in window
    flags = secret_covariates(
        prompt, summary="", recall_header=_HEADER, fact_header=_FACT_HEADER, layout=_layout(),
        user_message=values["user_message"], leak_keys=[["무릎"]], owner="김민지",
    )  # fmt: skip
    assert flags["원문 창"] == {"content": False, "owner": True, "together": False}
    # 대화 기록 뒤에 마지막 프레임만 남아도 질문 문장은 원문 창이 아니다.
    bare = render_prompt_channel(
        _generation_sections(), channel="generation", scope="story",
        values=values | {"keyword_note_lines": "", "situation_note_lines": ""},
    )  # fmt: skip
    assert "무릎" not in window_section(bare, _layout(), user_message=values["user_message"])


def test_window_header_comes_from_the_sets_history_section_and_a_prompt_missing_it_is_refused(tmp_path: Path) -> None:
    """원문 창 머리글은 세트의 대화 기록 섹션 첫 줄이다. 프롬프트에서 그 머리글이나 질문 프레임을 못 찾으면 빈 원문 창으로
    거짓 공변량을 내지 않고 거부한다."""
    from memory_eval.attribution import secret_covariates
    from memory_eval_cli import build_parser

    layout = _layout("[지난 대화]")
    assert layout.header == "[지난 대화]"
    assert layout.stop_headers == (_FACT_HEADER, _HEADER, "[키워드북]", "[상황 노트]", "[단축어]")

    def covariates(prompt: str, user_message: str) -> dict[str, dict[str, bool]]:
        return secret_covariates(
            prompt, summary="", recall_header=_HEADER, fact_header=_FACT_HEADER, layout=layout,
            user_message=user_message, leak_keys=[["무릎"]], owner="김민지",
        )  # fmt: skip

    with pytest.raises(SystemExit, match="머리글"):
        covariates(_guided_prompt(), "이번 입력")  # 세트는 [지난 대화] 인데 프롬프트는 [대화 기록]
    renamed = _guided_prompt().replace(_WINDOW_HEADER, "[지난 대화]")
    assert covariates(renamed, "이번 입력")["원문 창"]["content"] is True
    with pytest.raises(SystemExit, match="프레임"):
        covariates(renamed, "보내지 않은 질문")
    argv = ["--run", str(tmp_path), "attribution", "--plants", "p.json", "--probes", "x.jsonl", "--out", "o.json"]
    with pytest.raises(SystemExit):
        build_parser().parse_args([*argv, "--window-header", "[대화 기록]"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)  # 방이 없으면 세트를 읽을 수 없다
    room = "00000000-0000-0000-0000-000000000001"
    assert str(build_parser().parse_args([*argv, "--room", room]).room) == room


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
    ledger.check_headroom(0.4)  # 상한과 정확히 같은 누적은 허용한다(넘을 때만 멈춘다)
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


def test_test_half_requires_this_runs_sealed_edition_and_rejects_the_spent_v2(tmp_path: Path) -> None:
    import hashlib

    from memory_eval.seal import PREREGISTRATION_FILE, SEALED_EDITION, require_seal

    prereg = tmp_path / PREREGISTRATION_FILE
    sha_file = prereg.with_suffix(".sha256")

    def seal(text: str) -> str:
        prereg.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(prereg.read_bytes()).hexdigest()
        sha_file.write_text(f"{digest}  {PREREGISTRATION_FILE}\n", encoding="utf-8")
        return digest

    digest = seal("# 사전 등록 (v1.2)\n")
    require_seal({"dev"}, prereg, seal_sha=None)  # 개발 절반은 봉인 없이 된다
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha=None)
    with pytest.raises(SystemExit):
        require_seal({"dev", "test"}, prereg, seal_sha=digest)  # 봉인 판이 아니다
    # 앞 런의 v2 는 해시까지 맞게 봉인돼 있어도 시험 절반을 열지 못한다 — 그 시험 절반은 이미 한 번 썼다
    spent = seal("# 사전 등록 (v2)\n봉인\n")
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha=spent)
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha=seal("# 사전 등록 (v2.1)\n봉인\n"))
    with pytest.raises(SystemExit):  # 판 번호가 앞만 같다
        require_seal({"test"}, prereg, seal_sha=seal(f"# 사전 등록 ({SEALED_EDITION}0)\n봉인\n"))
    prereg.write_text(f"# 사전 등록 ({SEALED_EDITION})\n봉인\n", encoding="utf-8")
    sealed = hashlib.sha256(prereg.read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha=sealed)  # 해시 파일이 아직 옛 값
    sha_file.write_text(f"{sealed}  {PREREGISTRATION_FILE}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        require_seal({"test"}, prereg, seal_sha="0" * 64)  # 준 해시가 파일과 다르다
    require_seal({"test"}, prereg, seal_sha=sealed)
    require_seal({"test"}, prereg, seal_sha=seal(f"# 사전 등록 ({SEALED_EDITION}.1)\n봉인\n"))


def test_a_preregistration_sealed_under_the_spent_v3_edition_cannot_open_the_test_half(tmp_path: Path) -> None:
    """v3 판의 시험 절반은 앞 측정이 이미 열어 썼다 — 해시가 맞게 봉인돼 있어도 다시 열 수 없다."""
    import hashlib

    from memory_eval.seal import PREREGISTRATION_FILE, require_seal

    prereg = tmp_path / PREREGISTRATION_FILE
    for header in ("# 사전 등록 (v3)", "# 사전 등록 (v3.2)"):
        prereg.write_text(f"{header}\n봉인\n", encoding="utf-8")
        digest = hashlib.sha256(prereg.read_bytes()).hexdigest()
        prereg.with_suffix(".sha256").write_text(f"{digest}  {PREREGISTRATION_FILE}\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="봉인 판"):
            require_seal({"test"}, prereg, seal_sha=digest)


def test_a_preregistration_sealed_under_the_spent_v4_edition_cannot_open_the_test_half(tmp_path: Path) -> None:
    """v4 판의 시험 절반도 앞 측정이 이미 열어 썼다 — 해시가 맞게 봉인돼 있어도 다시 열 수 없다."""
    import hashlib

    from memory_eval.seal import PREREGISTRATION_FILE, require_seal

    prereg = tmp_path / PREREGISTRATION_FILE
    for header in ("# 사전 등록 (v4)", "# 사전 등록 (v4.1)"):
        prereg.write_text(f"{header}\n봉인\n", encoding="utf-8")
        digest = hashlib.sha256(prereg.read_bytes()).hexdigest()
        prereg.with_suffix(".sha256").write_text(f"{digest}  {PREREGISTRATION_FILE}\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="봉인 판"):
            require_seal({"test"}, prereg, seal_sha=digest)


def test_a_preregistration_sealed_under_the_spent_v5_edition_cannot_open_the_test_half(tmp_path: Path) -> None:
    """v5 판의 시험 절반도 앞 측정이 이미 열어 썼다 — 해시가 맞게 봉인돼 있어도 사실 주입 재측정의 시험 절반을 열 수 없다.
    이번 판 머리로 봉인한 문서만 연다."""
    import hashlib

    from memory_eval.seal import PREREGISTRATION_FILE, SEALED_EDITION, require_seal

    prereg = tmp_path / PREREGISTRATION_FILE

    def seal(header: str) -> str:
        prereg.write_text(f"{header}\n봉인\n", encoding="utf-8")
        digest = hashlib.sha256(prereg.read_bytes()).hexdigest()
        prereg.with_suffix(".sha256").write_text(f"{digest}  {PREREGISTRATION_FILE}\n", encoding="utf-8")
        return digest

    assert SEALED_EDITION == "v6"
    for header in ("# 사전 등록 (v5)", "# 사전 등록 (v5.1)"):
        digest = seal(header)
        with pytest.raises(SystemExit, match="봉인 판"):
            require_seal({"test"}, prereg, seal_sha=digest)
    require_seal({"test"}, prereg, seal_sha=seal("# 사전 등록 (v6)"))


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
        [_plant(id=f"p{i}", split="test", metrics={"MR1_passline": True}) for i in range(6)]
        + [_plant(id="loc04", split="test", limitProbe={"designedToFail": True}, metrics={"MR1_passline": False})]
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


# ---------------------------------------------------------------- 프로브 실행 순서(복원·서버·드라이버를 흉내)


def _fake_probe_world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, say_codes: list[int]) -> dict[str, Any]:
    import json
    import uuid as uuid_mod

    from memory_eval import checkpoint as checkpoint_mod
    from memory_eval import probe as probe_mod
    from memory_eval import server as server_mod

    calls: dict[str, Any] = {
        "restore": 0, "restoreBSeries": [], "start": [], "stop": 0, "sleep": [], "topup": 0, "driver": [], "consent": []
    }  # fmt: skip
    codes = iter(say_codes)

    async def restore(*_: Any, **kwargs: Any) -> dict[str, Any]:
        calls["restore"] += 1
        calls["restoreBSeries"].append(kwargs["b_series"])
        return {"fingerprint": {"turnCount": 100}}

    def start(overrides: dict[str, str], **kwargs: Any) -> Any:
        calls["start"].append(overrides)
        kwargs["log"].write_text("")
        return server_mod.ServerHandle(process=None, base="http://fake", log=kwargs["log"])  # type: ignore[arg-type]

    def driver(run: Any, base: str, folder: Path, *extra: str) -> int:
        calls["driver"].append(extra[0])
        if extra[0] == "--rebase":
            return 0
        code = next(codes)
        reply = "" if code not in (0, 3) else f"응답 {len(calls['driver'])}"
        # 서버가 부른 호출은 서버 로그의 사용량 줄로 남는다(원장 기준).
        with (folder / "server.log").open("a", encoding="utf-8") as log:
            log.write(
                "anthropic_usage call_site=chat_generate model=claude-opus-5-5 prompt_tokens=10000 cached_content_tokens=0 "
                "cache_write_tokens=0 candidates_tokens=500 thoughts_tokens=0 total_tokens=10500 user_id=u room_id=r\n"
            )
        with (folder / "chat.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "turn", "reply": reply, "clientTurn": 101}) + "\n")
        return code

    async def memory_facts(*_: Any) -> list[list[dict[str, Any]]]:
        return [[{"factId": "f1", "chars": 10}]]

    async def memory_recall(*_: Any) -> list[list[dict[str, Any]]]:
        return [[{"episodeId": "e1", "rank": None, "vectorRank": 1}]]

    async def usage(*_: Any) -> list[dict[str, Any]]:
        return [
            {"callSite": "chat_generate", "model": "claude-opus-5-5", "promptTokens": 10_000, "outputTokens": 500},
            {"callSite": "chat_memory_query_embedding", "model": "voyage-4-large", "latencyMs": 420, "outcome": "ok"},
        ]

    async def top_up(*_: Any) -> None:
        calls["topup"] += 1

    async def consent(_url: str, room_id: uuid_mod.UUID) -> None:
        calls["consent"].append(room_id)

    monkeypatch.setattr(checkpoint_mod, "restore", restore)
    monkeypatch.setattr(server_mod, "start", start)
    monkeypatch.setattr(server_mod, "stop", lambda _h: calls.__setitem__("stop", calls["stop"] + 1))
    monkeypatch.setattr(probe_mod, "_driver", driver)
    monkeypatch.setattr(probe_mod, "_turn_usage", usage)
    # 턴 기록의 실은 사실 행 읽기도 DB 를 타므로 같은 자리에서 흉내 낸다(필터 재계산이 결과의 `memoryFacts` 를 읽는다).
    monkeypatch.setattr(probe_mod, "_turn_memory_facts", memory_facts)
    # 턴 기록의 회상 줄 기록(장면 id·명사 순위·벡터 순위)도 같은 까닭으로 흉내 낸다.
    monkeypatch.setattr(probe_mod, "_turn_memory_recall", memory_recall)
    monkeypatch.setattr(probe_mod, "_top_up", top_up)
    # 복원 뒤 약관 동의 맞추기도 측정 DB 를 타므로 같은 자리에서 흉내 내고, 복원마다 불렸는지 센다.
    monkeypatch.setattr(probe_mod, "_ensure_consent", consent)
    monkeypatch.setattr("time.sleep", lambda s: calls["sleep"].append(s))
    calls["run"] = probe_mod.ProbeRun(
        stage="s4",
        arm="B",
        room_id=uuid_mod.uuid4(),
        run_dir=tmp_path,
        database_url="postgresql+asyncpg://x@localhost/lm_eval_work",
        cred_file=tmp_path / "cred",
        cookie_file=tmp_path / "cookie",
        port=8130,
        server_overrides={"CHAT_PREMIUM_MODELS_ENABLED": "true"},
        allow_paid=False,
        opus_turn_usd=0.13,
        judgment_turn_usd=0.003,
        ledger=Ledger(tmp_path / "ledger.jsonl", cap_usd=30.0),
        pacer=BurstPacer(limit=9, window_seconds=60.0),
    )
    return calls


@pytest.mark.parametrize(
    ("arm", "b_series"),
    [
        pytest.param("b1-B1", True, id="b-series-arm"),
        pytest.param("b1-A1", False, id="a-series-arm"),
        pytest.param("b1-A0M", True, id="marking-without-recall"),
        pytest.param("B", False, id="outside-bundle-1"),
    ],
)
def test_probe_tells_restore_the_template_series_of_its_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arm: str, b_series: bool
) -> None:
    # 요약 표기를 켠 묶음 1 갈래만 B 계열 템플릿에서 돈다. 묶음 1 밖 갈래(2차 런 갈래 등)는 A 계열이다.
    import dataclasses

    from memory_eval.plants import Probe
    from memory_eval.probe import run_probe

    calls = _fake_probe_world(monkeypatch, tmp_path, say_codes=[0])
    run = dataclasses.replace(calls["run"], arm=arm)
    run_probe(run, Probe(item_id="obj01", checkpoint=100, turns=["질문"], kind="plant", split="dev"))
    assert calls["restoreBSeries"] == [b_series]


def test_probe_restores_and_restarts_for_every_retry_and_records_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from memory_eval.plants import Probe
    from memory_eval.probe import run_probe

    calls = _fake_probe_world(monkeypatch, tmp_path, say_codes=[4, 0])
    result = run_probe(calls["run"], Probe(item_id="obj01", checkpoint=100, turns=["질문"], kind="plant", split="dev"))
    assert result["status"] == "accept"
    assert [a["action"] for a in result["attempts"]] == ["retry", "accept"]
    assert result["memoryFacts"] == [[{"factId": "f1", "chars": 10}]]  # 마지막 시도의 턴 기록
    # 작업 DB 는 다음 복원에서 지워지므로 회상 줄 기록과 질의 임베딩 호출(결과·지연)도 결과에 남는다 — 생성 호출은 빼고.
    assert result["memoryRecall"] == [[{"episodeId": "e1", "rank": None, "vectorRank": 1}]]
    assert result["queryEmbeddings"] == [
        {"callSite": "chat_memory_query_embedding", "model": "voyage-4-large", "latencyMs": 420, "outcome": "ok"}
    ]
    assert result["embedRecallTimeoutMs"] is None  # 이 측정 서버 env 에 상한 줄이 없다


def test_probe_records_the_query_embedding_timeout_it_gave_the_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """견주는 두 갈래가 같은 상한으로 돌았는지 집계 때 보려면 프로브 행에 그 값이 남아야 한다."""
    from memory_eval.plants import Probe
    from memory_eval.probe import run_probe

    calls = _fake_probe_world(monkeypatch, tmp_path, say_codes=[0])
    calls["run"].server_overrides["MEMORY_EMBED_RECALL_TIMEOUT_MS"] = "3000"
    result = run_probe(calls["run"], Probe(item_id="obj01", checkpoint=100, turns=["질문"], kind="plant", split="dev"))
    assert result["embedRecallTimeoutMs"] == "3000"
    assert calls["restore"] == 2 and len(calls["start"]) == 2 and calls["stop"] == 2
    assert calls["consent"] == [calls["run"].room_id] * 2
    assert 60 in calls["sleep"]
    assert calls["driver"] == ["--rebase", "--say", "--rebase", "--say"]
    # 프로브마다 덤프 파일이 따로이고 갈래 설정이 서버 env 에 실린다.
    dumps = {o["PROMPT_DUMP_PATH"] for o in calls["start"]}
    assert len(dumps) == 2
    assert all(o["MEMORY_EPISODES_RECALL"] == "true" for o in calls["start"])
    assert len(calls["run"].ledger.rows()) == 2


def test_two_turn_probe_tops_up_clover_and_keeps_both_replies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_eval.plants import Probe
    from memory_eval.probe import run_probe

    calls = _fake_probe_world(monkeypatch, tmp_path, say_codes=[0, 7, 0, 0])
    result = run_probe(
        calls["run"], Probe(item_id="obj03", checkpoint=50, turns=["맥락", "질문"], kind="plant", split="test")
    )
    assert result["status"] == "accept"
    assert calls["topup"] == 1
    assert calls["consent"] == [calls["run"].room_id] * calls["restore"]
    assert [t["user"] for t in result["turns"]] == ["맥락", "질문"]
    assert all(t["reply"] for t in result["turns"])


def test_lost_generation_with_exit_zero_counts_as_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_eval.plants import Probe
    from memory_eval.probe import run_probe

    # 드라이버가 0 으로 끝나도 응답이 비면(생성 오류로 유실) 그 밖의 오류로 세어 두 번 재시도 뒤 불능.
    calls = _fake_probe_world(monkeypatch, tmp_path, say_codes=[0, 0, 0])
    monkeypatch.setattr("memory_eval.probe._last_turn", lambda _f: {"reply": ""})
    result = run_probe(calls["run"], Probe(item_id="obj01", checkpoint=100, turns=["질문"], kind="plant", split="dev"))
    assert result["status"] == "unprobeable"
    assert calls["restore"] == 3
    assert calls["consent"] == [calls["run"].room_id] * 3


def test_probe_stops_before_a_call_that_would_cross_the_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_eval.plants import Probe
    from memory_eval.probe import run_probe

    calls = _fake_probe_world(monkeypatch, tmp_path, say_codes=[0])
    calls["run"].ledger.cap_usd = 0.1
    with pytest.raises(BudgetExceededError):
        run_probe(calls["run"], Probe(item_id="obj01", checkpoint=100, turns=["질문"], kind="plant", split="dev"))
    assert calls["restore"] == 0
