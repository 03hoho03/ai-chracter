"""판정기 일치율 도구 — 덤프 판정 줄 읽기, 결과 정규화, 후보 판정기(Haiku) 자기 반복 일치율(발동한 줄만의 값 포함)과 합격
판정, 최빈 결과 분포, 구조화 실패 집계, 카운트다운 층 기대값, 망친 입력 대조군 반응률, 드라이런 견적, 원장 상한 없는 유료
실행 거부. 판정기는 전부 가짜 클라이언트다(유료 호출 0).

측정 전에 정한 정의(일치 단위·합격선·보류 조건)가 코드에서 바뀌지 않았는지 지킨다."""

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.chat.prompt_builder import ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.llm.client import LLMClientError
from memory_eval import judge_agreement as ja
from memory_eval.ledger import Ledger

STAT_PROMPT = (
    "규칙 판정 지시\n\n"
    "윤결 신뢰 / 범위 [0, 100] / 윤결이 사용자를 믿는 정도\n"
    "- a1: 사용자가 바게트를 다 구웠다\n"
    "- a2: 사용자가 가게 문을 늦게 열었다\n\n"
    "상영회까지 / 범위 [0, 46] / 상영회 날까지 남은 날수\n"
    "- b1: 이번 응답에서 밤이 한 번 지나갔다\n"
    "- b2: 이번 응답에서 밤이 두 번 지나갔다\n\n"
    "나: 윤결아 바게트 남았어?\n진행자: 그 밤, 윤결이 빈손을 펴 보였다."
)

ENDING_PROMPT = "엔딩 판정 지시\n엔딩: 상영회 성공\n대화: …"
IMAGE_ID = "6f1c2a8e-0000-4000-8000-000000000001"
IMAGE_PROMPT = f"그림 고르기\n- imageEntityId={IMAGE_ID}, 노출 조건=유나가 웃는 순간"


def _dump(path: Path, records: Sequence[Mapping[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


def _judgment(
    call_site: str, schema: str, prompt: str, *, turn: int, room: str = "room-1", model: str = "gemini-3.5-flash-lite"
) -> dict[str, Any]:
    return {
        "roomId": room,
        "turn": turn,
        "kind": "judgment",
        "callSite": call_site,
        "model": model,
        "schema": schema,
        "prompt": prompt,
    }


def _standard_dump(tmp_path: Path) -> Path:
    return _dump(
        tmp_path / "dump.jsonl",
        [
            {"roomId": "room-1", "turn": 1, "kind": "generation", "prompt": "생성"},
            _judgment("chat_stat_judgment", "StatRuleJudgmentResult", STAT_PROMPT, turn=1),
            _judgment("chat_ending_judgment", "EndingJudgmentResult", ENDING_PROMPT, turn=1),
            _judgment("chat_situational_image", "ImageMatchJudgmentResult", IMAGE_PROMPT, turn=2, room="room-2"),
            _judgment("chat_memory_summary", "MemorySummaryResult", "요약", turn=2),
        ],
    )


def _model(label: str, answer: ja.FakeAnswer) -> ja.JudgeModel:
    model_id = "gemini-3.5-flash-lite" if label == "gemini" else "claude-haiku-5-5"
    return ja.JudgeModel(label=label, model_id=model_id, client=ja.FakeJudgeLLM(model_id, answer))


async def _run(
    tmp_path: Path, lines: list[ja.JudgmentLine], models: list[ja.JudgeModel], reps: int
) -> list[dict[str, Any]]:
    calls = tmp_path / "out" / "calls.jsonl"
    await ja.run_calls(
        lines,
        models,
        reps,
        ledger=Ledger(tmp_path / "out" / "ledger.jsonl"),
        calls_path=calls,
        stage="test",
        rates={},
        output_tokens=60,
    )
    return ja.read_calls(calls)


def test_load_lines_keeps_only_judgment_lines_in_scope_with_stable_ids(tmp_path: Path) -> None:
    lines = ja.load_lines([_standard_dump(tmp_path)])
    assert [(line.line_id, line.call_site) for line in lines] == [
        ("dump.jsonl:2", "chat_stat_judgment"),
        ("dump.jsonl:3", "chat_ending_judgment"),
        ("dump.jsonl:4", "chat_situational_image"),
    ]


def test_load_lines_refuses_a_judgment_line_with_a_separate_instruction(tmp_path: Path) -> None:
    record = _judgment("chat_stat_judgment", "StatRuleJudgmentResult", STAT_PROMPT, turn=1)
    record["systemInstruction"] = "따로 실은 지시문"
    with pytest.raises(SystemExit, match="지시문"):
        ja.load_lines([_dump(tmp_path / "d.jsonl", [record])])


def test_normalize_drops_rule_ids_and_image_ids_the_prompt_never_offered(tmp_path: Path) -> None:
    stat, _, image = ja.load_lines([_standard_dump(tmp_path)])
    assert ja.normalize(stat, StatRuleJudgmentResult(fired_rule_ids=["b1", "z9", "a2", "b1"])) == ["a2", "b1"]
    assert ja.normalize(image, ImageMatchJudgmentResult(matched_image_entity_id=IMAGE_ID)) == IMAGE_ID
    assert ja.normalize(image, ImageMatchJudgmentResult(matched_image_entity_id="밖의-id")) is None


def test_countdown_rule_ids_are_only_the_rules_under_that_stat_header() -> None:
    assert ja.stat_rule_ids(STAT_PROMPT, "상영회까지") == {"b1", "b2"}
    assert ja.stat_rule_ids(STAT_PROMPT, "윤결 신뢰") == {"a1", "a2"}


def test_pairwise_agreement_counts_equal_pairs_over_all_pairs() -> None:
    assert ja.self_agreement([["a1"], ["a1"], []]) == pytest.approx(1 / 3)
    assert ja.self_agreement([True]) is None
    assert ja.cross_agreement([True, True], [True, False]) == pytest.approx(0.5)
    assert ja.cross_agreement([], [True]) is None


def _stat_lines(tmp_path: Path, count: int) -> list[ja.JudgmentLine]:
    """턴마다 프롬프트가 다른 스탯 판정 줄 `count` 개(턴 1부터)."""
    records = [
        _judgment("chat_stat_judgment", "StatRuleJudgmentResult", f"{STAT_PROMPT}\n턴 표시 {turn}", turn=turn)
        for turn in range(1, count + 1)
    ]
    return ja.load_lines([_dump(tmp_path / "stat-dump.jsonl", records)])


def _turn_of(prompt: str) -> int:
    return int(prompt.rsplit("턴 표시 ", 1)[1])


def _per_line_sequence(answers: Mapping[int, list[list[str]]]) -> ja.FakeAnswer:
    """턴마다 반복 순서대로 낼 발동 규칙 목록. 목록에 없는 턴은 늘 빈 결과."""
    seen: dict[int, int] = {}

    def answer(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        turn = _turn_of(prompt)
        index = seen.get(turn, 0)
        seen[turn] = index + 1
        sequence = answers.get(turn)
        return {"fired_rule_ids": sequence[index % len(sequence)] if sequence else []}

    return answer


async def test_verdict_passes_on_the_candidate_self_agreement_alone_when_enough_lines_fired(tmp_path: Path) -> None:
    lines = _stat_lines(tmp_path, 10)
    haiku = _per_line_sequence({turn: [["a1"]] for turn in range(1, 6)})
    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=4)
    entry = ja.summarize(lines, calls)["callSites"]["chat_stat_judgment"]
    assert entry["models"]["haiku"]["selfAgreement"] == 1.0
    assert entry["models"]["haiku"]["firedSelfAgreement"] == 1.0
    assert entry["firedLines"] == 5
    assert "cross" not in entry
    assert entry["verdict"]["pass"] is True


async def test_agreement_on_lines_where_nothing_fired_does_not_hide_a_judge_that_wavers_when_something_does(
    tmp_path: Path,
) -> None:
    lines = _stat_lines(tmp_path, 20)
    # 18줄은 늘 아무 일도 없고, 발동한 두 줄에서는 반복마다 결과가 오간다.
    haiku = _per_line_sequence({19: [["a1"], []], 20: [["a2"], []]})
    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=4)
    entry = ja.summarize(lines, calls, min_fired_lines=2)["callSites"]["chat_stat_judgment"]
    model = entry["models"]["haiku"]
    # 전체 줄 일치율만 보면 하한을 넘는다 — 아무 일도 없는 줄이 대부분이라서다.
    assert model["selfAgreement"] == pytest.approx((18 + 2 / 6 * 2) / 20)
    assert model["selfAgreement"] >= ja.DEFAULT_MIN_SELF_AGREEMENT
    assert model["firedSelfAgreement"] == pytest.approx(2 / 6)
    assert entry["firedLines"] == 2
    assert entry["verdict"]["pass"] is False


async def test_fewer_fired_lines_than_the_minimum_holds_the_verdict(tmp_path: Path) -> None:
    lines = _stat_lines(tmp_path, 10)
    haiku = _per_line_sequence({1: [["a1"]], 2: [["a1"]]})
    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=3)
    entry = ja.summarize(lines, calls, min_fired_lines=3)["callSites"]["chat_stat_judgment"]
    assert entry["firedLines"] == 2
    assert entry["verdict"]["pass"] is None
    assert "발동" in entry["verdict"]["reason"]
    assert ja.summarize(lines, calls, min_fired_lines=2)["callSites"]["chat_stat_judgment"]["verdict"]["pass"] is True


async def test_self_agreement_below_the_lower_bound_fails(tmp_path: Path) -> None:
    lines = _stat_lines(tmp_path, 5)
    haiku = _per_line_sequence({turn: [["a1"], ["a1"], ["a1"], []] for turn in range(1, 6)})
    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=4)
    # 줄마다 [a1, a1, a1, 빈] → 같은 쌍 3/6 = 0.5.
    assert ja.summarize(lines, calls, min_self=0.5)["callSites"]["chat_stat_judgment"]["verdict"]["pass"] is True
    assert ja.summarize(lines, calls, min_self=0.51)["callSites"]["chat_stat_judgment"]["verdict"]["pass"] is False


async def test_modal_result_distribution_is_reported_per_call_site(tmp_path: Path) -> None:
    stat_lines = _stat_lines(tmp_path, 4)
    stat = await _run(tmp_path, stat_lines, [_model("haiku", _per_line_sequence({1: [["a1"]]}))], reps=3)
    stat_modal = ja.summarize(stat_lines, stat)["callSites"]["chat_stat_judgment"]["models"]["haiku"]["modal"]
    assert stat_modal == {"lines": 4, "emptyRate": 0.75}

    other = [line for line in ja.load_lines([_standard_dump(tmp_path)]) if line.call_site != "chat_stat_judgment"]

    def haiku(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        if schema == "EndingJudgmentResult":
            return {"triggered": True}
        return {"matched_image_entity_id": None}

    calls = await _run(tmp_path / "other", other, [_model("haiku", haiku)], reps=3)
    sites = ja.summarize(other, calls)["callSites"]
    assert sites["chat_ending_judgment"]["models"]["haiku"]["modal"] == {"lines": 1, "trueRate": 1.0}
    assert sites["chat_situational_image"]["models"]["haiku"]["modal"] == {"lines": 1, "chosenRate": 0.0}


async def test_a_reference_model_is_reported_against_the_candidate_but_does_not_decide_the_verdict(
    tmp_path: Path,
) -> None:
    lines = _stat_lines(tmp_path, 5)
    haiku = _per_line_sequence({turn: [["a1"]] for turn in range(1, 6)})
    gemini = _per_line_sequence({})
    calls = await _run(tmp_path, lines, [_model("gemini", gemini), _model("haiku", haiku)], reps=3)
    entry = ja.summarize(lines, calls, baseline="gemini")["callSites"]["chat_stat_judgment"]
    assert entry["cross"]["agreement"] == 0.0
    assert entry["verdict"]["pass"] is True


def _transport_error() -> LLMClientError:
    try:
        raise httpx.ConnectError("끊김")
    except httpx.ConnectError as cause:
        error = LLMClientError("전송 실패")
        error.__cause__ = cause
        return error


async def test_a_call_error_left_in_the_results_holds_the_verdict(tmp_path: Path) -> None:
    lines = _stat_lines(tmp_path, 5)
    calls_made = {"n": 0}

    def haiku(prompt: str, schema: str, call_site: str) -> dict[str, Any] | Exception:
        calls_made["n"] += 1
        # 시간 초과는 앱도 다시 부르지 않아 전송 오류로 남는다(연결 끊김은 같은 호출 안에서 다시 불려 살아난다).
        return _timeout_error() if calls_made["n"] == 2 else {"fired_rule_ids": ["a1"]}

    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=3)
    entry = ja.summarize(lines, calls)["callSites"]["chat_stat_judgment"]
    assert entry["models"]["haiku"]["callErrors"] == 1
    # 남은 성공만으로도 일치율은 1.0 이지만, 빠진 호출이 있으면 판정하지 않는다.
    assert entry["models"]["haiku"]["selfAgreement"] == 1.0
    assert entry["verdict"]["pass"] is None
    assert "전송 오류" in entry["verdict"]["reason"]


async def test_a_line_without_two_successes_holds_the_verdict(tmp_path: Path) -> None:
    lines = _stat_lines(tmp_path, 5)
    haiku = _per_line_sequence({turn: [["a1"]] for turn in range(1, 6)})
    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=3)
    # 중간에 끊긴 실행처럼 마지막 줄의 결과가 하나만 남았다.
    last = lines[-1].line_id
    kept = [row for row in calls if row["lineId"] != last or row["rep"] == 0]
    entry = ja.summarize(lines, kept)["callSites"]["chat_stat_judgment"]
    assert entry["models"]["haiku"]["selfAgreementLines"] == 4
    assert entry["verdict"]["pass"] is None
    assert "줄" in entry["verdict"]["reason"]


async def test_reference_cross_and_both_self_agreements_use_the_same_lines(tmp_path: Path) -> None:
    lines = _stat_lines(tmp_path, 5)
    haiku = _per_line_sequence({turn: [["a1"]] for turn in range(1, 6)})
    gemini = _per_line_sequence({turn: [["a1"]] for turn in range(1, 5)})
    calls = await _run(tmp_path, lines, [_model("gemini", gemini), _model("haiku", haiku)], reps=3)
    last = lines[-1].line_id
    # Gemini 는 마지막 줄에 성공이 하나뿐이다 — 자기 반복을 낼 수 없는 줄이라 교차에서도 뺀다.
    kept = [row for row in calls if not (row["lineId"] == last and row["model"] == "gemini" and row["rep"] > 0)]
    entry = ja.summarize(lines, kept, baseline="gemini")["callSites"]["chat_stat_judgment"]
    cross = entry["cross"]
    assert cross["lines"] == 4
    assert cross["agreement"] == 1.0
    assert cross["baselineSelfAgreementLines"] == 4
    assert cross["candidateSelfAgreementLines"] == 4
    # 판정은 후보 자기 반복만 보므로 후보는 다섯 줄 모두로 판정된다.
    assert entry["models"]["haiku"]["selfAgreementLines"] == 5
    assert entry["verdict"]["pass"] is True


def _timeout_error() -> LLMClientError:
    try:
        raise httpx.ReadTimeout("시간 초과")
    except httpx.ReadTimeout as cause:
        error = LLMClientError("시간 초과")
        error.__cause__ = cause
        return error


async def test_a_parse_failure_is_called_again_once_like_the_app_and_only_a_second_failure_counts(
    tmp_path: Path,
) -> None:
    lines = [line for line in ja.load_lines([_standard_dump(tmp_path)]) if line.call_site == "chat_ending_judgment"]
    # 반복마다 (첫 시도, 다시 부른 시도). 반복 0: 파싱 실패 뒤 성공 · 1: 두 번 파싱 실패 · 2: 연결 끊김 뒤 성공
    # · 3: 시간 초과(다시 부르지 않는다) · 4: 곧바로 성공.
    script: list[Any] = [
        LLMClientError("스키마로 읽히지 않았다"),
        {"triggered": True},
        LLMClientError("스키마로 읽히지 않았다"),
        LLMClientError("스키마로 읽히지 않았다"),
        _transport_error(),
        {"triggered": True},
        _timeout_error(),
        {"triggered": True},
    ]

    def haiku(prompt: str, schema: str, call_site: str) -> dict[str, Any] | Exception:
        return script.pop(0) if script else {"triggered": True}

    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=5)
    by_rep = {row["rep"]: row for row in calls}
    assert [(by_rep[r]["status"], by_rep[r]["attempts"]) for r in range(5)] == [
        ("ok", 2),
        ("structured_failure", 2),
        ("ok", 2),
        ("call_error", 1),
        ("ok", 1),
    ]
    entry = ja.summarize(lines, calls)["callSites"]["chat_ending_judgment"]["models"]["haiku"]
    assert entry["structuredFailures"] == 1
    assert entry["firstAttemptStructuredFailures"] == 2
    assert entry["callErrors"] == 1
    assert entry["ok"] == 3


async def test_structured_failures_fail_the_verdict_and_a_rerun_only_calls_the_call_errors_again(
    tmp_path: Path,
) -> None:
    lines = [line for line in ja.load_lines([_standard_dump(tmp_path)]) if line.call_site == "chat_ending_judgment"]
    attempts = {"n": 0}

    def haiku(prompt: str, schema: str, call_site: str) -> dict[str, Any] | Exception:
        attempts["n"] += 1
        if attempts["n"] in (1, 2):
            return LLMClientError("스키마로 읽히지 않았다")
        if attempts["n"] == 3:
            return _timeout_error()
        return {"triggered": True}

    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=3)
    entry = ja.summarize(lines, calls)["callSites"]["chat_ending_judgment"]
    assert (entry["models"]["haiku"]["structuredFailures"], entry["models"]["haiku"]["callErrors"]) == (1, 1)
    assert entry["verdict"]["pass"] is False

    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=3)
    assert attempts["n"] == 5
    again = ja.summarize(lines, calls)["callSites"]["chat_ending_judgment"]["models"]["haiku"]
    assert (again["ok"], again["structuredFailures"], again["callErrors"]) == (2, 1, 0)


def test_the_same_judgment_call_dumped_twice_is_read_as_one_line(tmp_path: Path) -> None:
    stat = _judgment("chat_stat_judgment", "StatRuleJudgmentResult", STAT_PROMPT, turn=1)
    other_prompt = _judgment("chat_stat_judgment", "StatRuleJudgmentResult", STAT_PROMPT + "\n다시 쓴 응답", turn=1)
    other_room = _judgment("chat_stat_judgment", "StatRuleJudgmentResult", STAT_PROMPT, turn=1, room="room-2")
    lines = ja.load_lines([_dump(tmp_path / "d.jsonl", [stat, stat, other_prompt, other_room, stat])])
    assert [(line.line_id, line.duplicates) for line in lines] == [("d.jsonl:1", 2), ("d.jsonl:3", 0), ("d.jsonl:4", 0)]


async def test_results_left_from_a_different_prompt_under_the_same_call_key_stop_the_run(tmp_path: Path) -> None:
    dump = tmp_path / "dump.jsonl"
    first = ja.load_lines(
        [_dump(dump, [_judgment("chat_ending_judgment", "EndingJudgmentResult", ENDING_PROMPT, turn=1)])]
    )
    calls = await _run(tmp_path, first, [_model("haiku", lambda p, s, c: {"triggered": True})], reps=2)
    assert {row["promptSha"] for row in calls} == {first[0].prompt_sha}

    # 같은 이름의 덤프를 다시 만들어 같은 줄 번호에 다른 프롬프트가 왔다 — 줄 id 가 같아 옛 결과가 새 줄의 것처럼 읽힌다.
    rewritten = _judgment("chat_ending_judgment", "EndingJudgmentResult", ENDING_PROMPT + " 바뀐 대화", turn=1)
    second = ja.load_lines([_dump(dump, [rewritten])])
    assert second[0].line_id == first[0].line_id
    with pytest.raises(SystemExit, match="프롬프트"):
        await _run(tmp_path, second, [_model("haiku", lambda p, s, c: {"triggered": True})], reps=2)
    with pytest.raises(SystemExit, match="프롬프트"):
        ja.summarize(second, calls)


async def test_countdown_decrement_rate_is_per_model_on_turns_where_time_did_not_move(tmp_path: Path) -> None:
    lines = [line for line in ja.load_lines([_standard_dump(tmp_path)]) if line.call_site == "chat_stat_judgment"]

    def gemini(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        return {"fired_rule_ids": ["a1"]}

    def haiku(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        # 다른 스탯 규칙만 고른 결과는 감소가 아니고, 카운트다운 규칙이 섞이면 감소다.
        return {"fired_rule_ids": ["a1", "b2"]}

    calls = await _run(tmp_path, lines, [_model("gemini", gemini), _model("haiku", haiku)], reps=4)
    strata: dict[tuple[str | None, int], dict[str, Any]] = {
        ("room-1", 1): {"roomId": "room-1", "turn": 1, "stratum": "relative_past", "expectDecrement": False}
    }
    countdown = ja.summarize(lines, calls, strata=strata)["countdown"]["relative_past"]
    assert countdown["expectDecrement"] is False
    assert countdown["models"]["gemini"] == {"results": 4, "decrements": 0, "decrementRate": 0.0}
    assert countdown["models"]["haiku"] == {"results": 4, "decrements": 4, "decrementRate": 1.0}
    assert countdown["verdict"]["pass"] is False


async def test_countdown_strata_are_judged_against_their_expected_direction(tmp_path: Path) -> None:
    lines = _stat_lines(tmp_path, 2)
    # 턴 1 은 시간이 움직이지 않은 층, 턴 2 는 움직인 층. 둘 다 네 번 중 한 번 감소를 고른다.
    haiku = _per_line_sequence({1: [["b1"], [], [], []], 2: [["b1"], [], [], []]})
    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=4)
    strata: dict[tuple[str | None, int], dict[str, Any]] = {
        ("room-1", 1): {"roomId": "room-1", "turn": 1, "stratum": "quiet", "expectDecrement": False},
        ("room-1", 2): {"roomId": "room-1", "turn": 2, "stratum": "moved", "expectDecrement": True},
    }
    summary = ja.summarize(lines, calls, strata=strata, max_quiet_decrement=0.25, min_decrement=0.25)
    assert summary["countdown"]["quiet"]["verdict"]["pass"] is True
    assert summary["countdown"]["moved"]["verdict"]["pass"] is True
    strict = ja.summarize(lines, calls, strata=strata, max_quiet_decrement=0.24, min_decrement=0.26)
    assert strict["countdown"]["quiet"]["verdict"]["pass"] is False
    assert strict["countdown"]["moved"]["verdict"]["pass"] is False
    assert strict["verdict"]["pass"] is False


async def test_corrupted_input_controls_report_whether_each_judge_changed_its_answer(tmp_path: Path) -> None:
    base = [line for line in ja.load_lines([_standard_dump(tmp_path)]) if line.call_site == "chat_stat_judgment"]
    spec = [
        {
            "id": "next-morning",
            "base": {"roomId": "room-1", "turn": 1, "callSite": "chat_stat_judgment"},
            "replace": [["그 밤", "다음 날 아침"]],
        }
    ]
    lines = base + ja.control_lines(base, spec)

    def gemini(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        return {"fired_rule_ids": ["b1"] if "다음 날 아침" in prompt else []}

    def haiku(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        return {"fired_rule_ids": []}

    calls = await _run(tmp_path, lines, [_model("gemini", gemini), _model("haiku", haiku)], reps=2)
    summary = ja.summarize(lines, calls)
    assert summary["controls"]["next-morning"]["reacted"] == {"gemini": True, "haiku": False}
    assert summary["controlReaction"]["gemini"]["rate"] == 1.0
    assert summary["controlReaction"]["haiku"]["rate"] == 0.0
    # 판정은 후보(Haiku) 하나의 반응률로 한다.
    assert summary["controlReaction"]["verdict"]["pass"] is False
    assert ja.summarize(lines, calls, candidate="gemini")["controlReaction"]["verdict"]["pass"] is True
    # 대조군 줄은 일치율 집계에 들지 않는다.
    assert summary["callSites"]["chat_stat_judgment"]["lines"] == 1


def test_a_control_whose_text_is_not_exactly_once_in_the_prompt_is_refused(tmp_path: Path) -> None:
    base = ja.load_lines([_standard_dump(tmp_path)])
    spec = [
        {
            "id": "absent",
            "base": {"roomId": "room-1", "turn": 1, "callSite": "chat_stat_judgment"},
            "replace": [["없는 글", "x"]],
        }
    ]
    with pytest.raises(SystemExit, match="0번"):
        ja.control_lines(base, spec)


def test_rejudging_defaults_to_haiku_whatever_model_made_the_dump_and_reports_the_dump_models(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from api.core.config import settings
    from memory_eval_cli import main

    records = [
        _judgment("chat_stat_judgment", "StatRuleJudgmentResult", STAT_PROMPT, turn=1),
        _judgment(
            "chat_stat_judgment", "StatRuleJudgmentResult", STAT_PROMPT + "\n둘째", turn=2, model="claude-haiku-5-5"
        ),
    ]
    dump = _dump(tmp_path / "dump.jsonl", records)
    assert [line.dump_model for line in ja.load_lines([dump])] == ["gemini-3.5-flash-lite", "claude-haiku-5-5"]
    code = main(["--run", str(tmp_path / "run"), "judge-agreement", "--dumps", str(dump), "--reps", "2", "--fake-llm"])
    assert code == 0
    meta = json.loads(capsys.readouterr().out)["meta"]
    assert meta["models"] == {"haiku": settings.anthropic_haiku_model_id}
    assert meta["dumpModels"] == {"chat_stat_judgment": {"claude-haiku-5-5": 1, "gemini-3.5-flash-lite": 1}}
    # 한 줄이 Gemini 로 판정된 덤프다 — 그 줄의 프롬프트는 Gemini 판정 문안으로 조립됐다.
    assert meta["dumpJudgedByCandidateModel"] is False


def test_dry_run_prints_call_count_and_cost_without_calling(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from memory_eval_cli import main

    dump = _standard_dump(tmp_path)
    code = main(
        [
            "--run",
            str(tmp_path / "run"),
            "judge-agreement",
            "--dumps",
            str(dump),
            "--models",
            "haiku",
            "--reps",
            "3",
            "--tokens-per-char",
            "haiku=2.0",
            "--output-tokens",
            "40",
            "--dry-run",
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    chars = [len(STAT_PROMPT), len(ENDING_PROMPT), len(IMAGE_PROMPT)]
    assert report["calls"] == 3 * 3 * 1
    assert report["linesByCallSite"] == {
        "chat_ending_judgment": 1,
        "chat_situational_image": 1,
        "chat_stat_judgment": 1,
    }
    expected = sum((math.ceil(c * 2.0) * 0.10 + 40 * 0.50) / 1_000_000 for c in chars) * 3
    assert report["totalUsd"] == pytest.approx(expected)
    assert not (tmp_path / "run" / "judge-agreement").exists()


def test_paid_run_without_ledger_limits_is_refused_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    dump = _standard_dump(tmp_path)
    code = main(
        [
            "--run",
            str(tmp_path / "run"),
            "--bundle",
            "b1",
            "judge-agreement",
            "--dumps",
            str(dump),
            "--gemini-model",
            "gemini-3.5-flash-lite",
            "--allow-paid",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "--cap-usd" in err and "--halt-usd" in err
    assert not (tmp_path / "run" / "judge-agreement").exists()


async def test_paid_style_run_stops_at_the_ledger_cap_before_the_call_that_would_cross_it(tmp_path: Path) -> None:
    from memory_eval.ledger import BudgetExceededError

    lines = ja.load_lines([_standard_dump(tmp_path)])
    model = _model("haiku", lambda prompt, schema, call_site: ja._FAKE_DEFAULTS[schema])
    per_call = ja.call_estimate_usd(lines[0], model, rates={}, output_tokens=60)
    # 가짜 판정기의 실제 원가는 견적보다 작다(출력 5토큰 대 견적 60토큰) — 두 번째 호출 앞에서 누적 + 견적이 상한을 넘는다.
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=per_call * 1.01, halt_usd=per_call * 1.01, bundle="b")
    with pytest.raises(BudgetExceededError):
        await ja.run_calls(
            lines,
            [model],
            3,
            ledger=ledger,
            calls_path=tmp_path / "calls.jsonl",
            stage="t",
            rates={},
            output_tokens=60,
        )
    assert len(ja.read_calls(tmp_path / "calls.jsonl")) == 1
    assert len(ledger.rows()) == 1


def _two_branch_dumps(tmp_path: Path) -> list[ja.JudgmentLine]:
    """엔딩 갈래 둘 — 같은 방·같은 턴 40 이고 덤프 파일만 다르다."""
    paths = [
        _dump(
            tmp_path / f"dump-story-{branch}.jsonl",
            [_judgment("chat_ending_judgment", "EndingJudgmentResult", f"{ENDING_PROMPT}\n나: {say}", turn=40)],
        )
        for branch, say in (("E1", "맞는 장면"), ("E7", "무관한 장면"))
    ]
    return ja.load_lines(paths)


def test_a_control_names_its_base_line_by_line_id_or_branch_whatever_the_dump_order(tmp_path: Path) -> None:
    lines = _two_branch_dumps(tmp_path)
    by_id = [{"id": "a", "base": {"lineId": "dump-story-E7.jsonl:1"}, "replace": [["무관한 장면", "사건"]]}]
    by_branch = [
        {"id": "b", "base": {"branch": "E7", "callSite": "chat_ending_judgment"}, "replace": [["무관한 장면", "사건"]]}
    ]
    for spec in (by_id, by_branch):
        for ordered in (lines, list(reversed(lines))):
            (control,) = ja.control_lines(ordered, spec)
            assert control.base_id == "dump-story-E7.jsonl:1"
            assert control.prompt.endswith("나: 사건")


def test_a_control_named_by_room_and_turn_is_refused_when_lines_from_several_dumps_match(tmp_path: Path) -> None:
    # 갈래들은 같은 방·같은 턴이라 방·턴으로 고르면 `--dumps` 순서가 원래 줄을 정한다.
    lines = _two_branch_dumps(tmp_path)
    spec = [
        {
            "id": "c",
            "base": {"roomId": "room-1", "turn": 40, "callSite": "chat_ending_judgment"},
            "replace": [["엔딩 판정 지시", "x"]],
        }
    ]
    with pytest.raises(SystemExit, match="덤프"):
        ja.control_lines(lines, spec)


async def test_control_reaction_counts_only_changes_in_the_expected_direction(tmp_path: Path) -> None:
    # 스탯은 카운트다운 규칙이 새로 생겨야, 엔딩은 거짓에서 참으로, 그림은 고르지 않음에서 고름으로 바뀌어야 반응이다. 반대 방향
    # 변화는 반응이 아니라 따로 보고하고, 원래 줄이 이미 기대 상태면 반응을 잴 수 없다(반응률에서 뺀다).
    stat_base = _stat_lines(tmp_path, 3)
    ending_base = [
        line
        for line in ja.load_lines([_dump(tmp_path / "ending.jsonl", [
            _judgment("chat_ending_judgment", "EndingJudgmentResult", f"{ENDING_PROMPT}\n턴 표시 9", turn=9)
        ])])
    ]  # fmt: skip
    base = stat_base + ending_base
    spec = [
        {
            "id": f"s{turn}",
            "base": {"lineId": f"stat-dump.jsonl:{turn}"},
            "replace": [[f"턴 표시 {turn}", f"턴 표시 {turn}0"]],
        }
        for turn in (1, 2, 3)
    ] + [{"id": "e", "base": {"lineId": "ending.jsonl:1"}, "replace": [["턴 표시 9", "턴 표시 90"]]}]
    lines = base + ja.control_lines(base, spec)
    stat_answers = {1: [], 10: ["b1"], 2: [], 20: ["a2"], 3: ["b2"], 30: ["b2"]}

    def haiku(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        if call_site == "chat_ending_judgment":
            return {"triggered": _turn_of(prompt) == 9}
        return {"fired_rule_ids": stat_answers[_turn_of(prompt)]}

    calls = await _run(tmp_path, lines, [_model("haiku", haiku)], reps=2)
    summary = ja.summarize(lines, calls)
    controls = summary["controls"]
    assert controls["s1"]["reacted"]["haiku"] is True
    assert controls["s2"]["reacted"]["haiku"] is False  # 다른 규칙으로 바뀐 것은 반응이 아니다
    assert controls["s3"]["reacted"]["haiku"] is None  # 원래 줄이 이미 감소였다
    assert controls["s3"]["opposite"]["haiku"] is False
    # 엔딩 원래 줄은 이미 참이라 반응은 잴 수 없고, 거짓으로 뒤집힌 것은 반대 방향 변화로만 남는다.
    assert controls["e"]["reacted"]["haiku"] is None and controls["e"]["opposite"]["haiku"] is True
    assert summary["controlReaction"]["haiku"] == {"controls": 2, "reacted": 1, "opposite": 1, "rate": 0.5}


# ---------------------------------------------------------------- 호출 순서


def _two_stat_lines(tmp_path: Path) -> list[ja.JudgmentLine]:
    return ja.load_lines(
        [
            _dump(
                tmp_path / "order.jsonl",
                [
                    _judgment("chat_stat_judgment", "StatRuleJudgmentResult", f"{STAT_PROMPT}\n턴 {turn}", turn=turn)
                    for turn in (1, 2)
                ],
            )
        ]
    )


async def _call_order(tmp_path: Path, order_seed: int | None) -> list[str]:
    lines = _two_stat_lines(tmp_path)
    models = [
        _model(label, lambda prompt, schema, call_site: ja._FAKE_DEFAULTS[schema]) for label in ("gemini", "haiku")
    ]
    calls = tmp_path / "out" / "calls.jsonl"
    await ja.run_calls(
        lines,
        models,
        2,
        ledger=Ledger(tmp_path / "out" / "ledger.jsonl"),
        calls_path=calls,
        stage="test",
        rates={},
        output_tokens=60,
        order_seed=order_seed,
    )
    return [str(row["key"]) for row in ja.read_calls(calls)]


NESTED_ORDER = [
    f"order.jsonl:{line}|{label}|{rep}" for line in (1, 2) for label in ("gemini", "haiku") for rep in (0, 1)
]


async def test_calls_go_line_then_model_then_rep_without_an_order_seed(tmp_path: Path) -> None:
    assert await _call_order(tmp_path, None) == NESTED_ORDER


async def test_an_order_seed_shuffles_every_call_key_reproducibly(tmp_path: Path) -> None:
    first = await _call_order(tmp_path / "a", 7)
    again = await _call_order(tmp_path / "b", 7)
    other = await _call_order(tmp_path / "c", 8)
    assert first == again
    assert sorted(first) == sorted(NESTED_ORDER)
    assert first != NESTED_ORDER
    assert first != other


# ---------------------------------------------------------------- 다수결 plug-in


def _row(line: str, rep: int, result: Any, *, model: str = "haiku", status: str = "ok") -> dict[str, Any]:
    return {
        "key": f"{line}|{model}|{rep}",
        "lineId": line,
        "model": model,
        "rep": rep,
        "status": status,
        "result": result,
    }


DELTAS = {"a1": 3, "a2": -2, "a3": 3, "b1": -1}
# 줄 1: {a1}·{a1}·{a2}. 줄 2: {a1}·{a3}·{} — a1 과 a3 은 폭이 같아 앱 반영 변화량이 같다.
MAJORITY_CALLS = [
    _row("d:1", 0, ["a1"]),
    _row("d:1", 1, ["a1"]),
    _row("d:1", 2, ["a2"]),
    _row("d:2", 0, ["a1"]),
    _row("d:2", 1, ["a3"]),
    _row("d:2", 2, []),
    # 세지 않는 줄: 다른 판, 호출 오류, 대조군, 스탯이 아닌 판정, 성공 결과가 하나뿐인 줄.
    _row("d:1", 3, ["b1"], model="gemini"),
    _row("d:1", 4, None, status="call_error"),
    _row("control:x", 0, ["a1"]),
    _row("control:x", 1, []),
    _row("d:3", 0, True),
    _row("d:3", 1, False),
    _row("d:4", 0, ["a1"]),
]


def test_majority_of_three_by_hand_when_voting_on_the_rule_set() -> None:
    report = ja.majority_agreement(MAJORITY_CALLS, model="haiku", k=3, vote="ruleSet", deltas=DELTAS)
    assert report["lines"] == 2
    assert report["skippedLines"] == 1
    metrics = report["metrics"]
    # 줄 1: p = (2/3, 1/3) → 단일 5/9, 세 표 최빈 q = (20/27, 7/27) → 449/729.
    # 줄 2: 셋이 다 달라 단일·다수결 모두 1/3. 변화량으로는 {a:3} 이 2/3 이라 5/9 가 둘 다.
    assert metrics["ruleSet"] == {
        "single": pytest.approx((5 / 9 + 1 / 3) / 2),
        "majority": pytest.approx((449 / 729 + 1 / 3) / 2),
        "lines": 2,
    }
    assert metrics["appliedChange"] == {
        "single": pytest.approx((5 / 9 + 5 / 9) / 2),
        "majority": pytest.approx((449 / 729 + 5 / 9) / 2),
        "lines": 2,
    }
    assert metrics["direction"] == metrics["appliedChange"]
    assert metrics["fired"] == {
        "single": pytest.approx((1 + 5 / 9) / 2),
        "majority": pytest.approx((1 + 5 / 9) / 2),
        "lines": 2,
    }


def test_majority_of_three_by_hand_when_voting_on_the_applied_change() -> None:
    report = ja.majority_agreement(MAJORITY_CALLS, model="haiku", k=3, vote="appliedChange", deltas=DELTAS)
    metrics = report["metrics"]
    # 줄 2 도 변화량 공간에서는 (2/3, 1/3) 이라 다수결이 449/729 로 오른다. 규칙 집합은 표를 던진 공간이 아니라 없다.
    assert metrics["ruleSet"] is None
    assert metrics["appliedChange"]["single"] == pytest.approx(5 / 9)
    assert metrics["appliedChange"]["majority"] == pytest.approx(449 / 729)


def test_a_single_vote_majority_is_the_single_judgment() -> None:
    report = ja.majority_agreement(MAJORITY_CALLS, model="haiku", k=1, vote="ruleSet", deltas=DELTAS)
    for entry in report["metrics"].values():
        assert entry["majority"] == pytest.approx(entry["single"])


def test_majority_without_deltas_keeps_only_the_rule_set_and_fired_metrics() -> None:
    report = ja.majority_agreement(MAJORITY_CALLS, model="haiku", k=3, vote="ruleSet")
    assert report["metrics"]["appliedChange"] is None
    assert report["metrics"]["direction"] is None
    assert report["metrics"]["ruleSet"]["majority"] == pytest.approx((449 / 729 + 1 / 3) / 2)
    with pytest.raises(SystemExit, match="폭"):
        ja.majority_agreement(MAJORITY_CALLS, model="haiku", k=3, vote="appliedChange")


def test_majority_refuses_a_rule_id_missing_from_the_delta_table() -> None:
    with pytest.raises(SystemExit, match="폭"):
        ja.majority_agreement(MAJORITY_CALLS, model="haiku", k=3, vote="ruleSet", deltas={"a1": 3})


def test_applied_change_takes_the_widest_rule_per_stat_and_the_earlier_one_on_a_tie() -> None:
    deltas = {"a1": 1, "a2": -4, "a3": 4, "b1": -1, "b2": 2}
    assert ja.applied_change(["a1", "a2", "a3", "b1"], deltas) == {"a": -4, "b": -1}
    assert ja.applied_change(["a3", "b2"], deltas) == {"a": 4, "b": 2}
    assert ja.applied_change([], deltas) == {}
