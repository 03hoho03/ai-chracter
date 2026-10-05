"""실험 스크립트 `experiments/filmclub_longturn/turn_watch.py` — 측정 방 10턴 감시기.

감시기는 방이 10턴을 지날 때마다 원가 한 줄을 쓰고 깨짐 기계 항목을 판정해, 멈춰야 하면 정지 파일만 만든다. 아래
테스트는 항목마다 정상 입력에서 조용하고(초록) 깨진 입력 한 군데에서 걸리는지(빨강), 직전 점검에서 이미 본 턴을 다시
걸지 않는지, 원가가 측정 방 줄만 세는지, 정지 파일과 경보 기록이 남는지를 본다. LLM·DB·Redis 는 쓰지 않는다.
"""

import json
from pathlib import Path
from typing import Any

from experiments.filmclub_longturn import turn_watch as w

ROOM = "6787bb78-c54d-4c65-966c-024e1dff0c74"
OTHER = "c3a19d00-e53e-4cfa-a377-ff100d3660e9"
AFF = ("도희 호감도", "유나 호감도", "세빈 호감도")


def _turn(n: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "turn": n,
        "attempt": n,
        "source": "simulator",
        "tag": "보통",
        "lost": False,
        "probe": False,
        "scored": True,
        "statusPresent": True,
        "statusFmtOk": True,
        "statusMimic": False,
        "bodyMimic": [],
        "dup": [],
        "statusTime": f"시간 {n}",
        "countdownBefore": 42.0,
        "countdownAfter": 42.0,
        "countdownDelta": 0.0,
        "affectionDelta": {name: 1.0 for name in AFF},
        "dayPhrases": [],
        "replyLen": 300,
        "seconds": 5.0,
        "usage": [],
        "logFailures": [],
        "calls": [],
        "memory": {"summaryLen": 0},
    }
    base.update(over)
    return base


def _turns(count: int, **over_by_turn: dict[str, Any]) -> list[dict[str, Any]]:
    return [_turn(n, **over_by_turn.get(f"t{n}", {})) for n in range(1, count + 1)]


# ---------------------------------------------------------------- B1 생성 유실·타임아웃


def test_b1_quiet_on_normal_turns() -> None:
    assert w.b1_generation(_turns(20), since=0) == []


def test_b1_catches_one_lost_turn_and_a_generation_timeout() -> None:
    turns = _turns(20, t12={"lost": True, "scored": False})
    assert w.b1_generation(turns, since=10)
    timeout = _turns(20, t15={"calls": [{"callSite": "chat_generate", "ok": False, "errorType": "ReadTimeout"}]})
    assert w.b1_generation(timeout, since=10)


def test_b1_does_not_repeat_turns_seen_by_the_previous_check() -> None:
    turns = _turns(20, t5={"lost": True, "scored": False})
    assert w.b1_generation(turns, since=10) == []


# ---------------------------------------------------------------- B2 판정 실패 10턴 창 2회


def test_b2_one_failure_is_not_enough() -> None:
    turns = _turns(20, t12={"logFailures": [{"failure": "stat_judgment", "timeout": False}]})
    assert w.b2_judgment(turns, since=10) == []


def test_b2_two_failures_of_one_call_site_within_ten_turns() -> None:
    turns = _turns(
        20,
        t8={"logFailures": [{"failure": "media_book_judgment", "timeout": False}]},
        t16={"calls": [{"callSite": "chat_media_book_image", "ok": False, "errorType": "ReadTimeout"}]},
    )
    assert w.b2_judgment(turns, since=10)


def test_b2_failures_of_different_call_sites_or_far_apart_do_not_pair() -> None:
    mixed = _turns(
        20,
        t12={"logFailures": [{"failure": "stat_judgment", "timeout": False}]},
        t14={"logFailures": [{"failure": "judgment", "timeout": False}]},
    )
    assert w.b2_judgment(mixed, since=10) == []
    far = _turns(
        30,
        t5={"logFailures": [{"failure": "stat_judgment", "timeout": False}]},
        t15={"logFailures": [{"failure": "stat_judgment", "timeout": False}]},
    )
    assert w.b2_judgment(far, since=10) == []


# ---------------------------------------------------------------- B3 상태창 2연속


def test_b3_single_bad_status_is_quiet_two_in_a_row_hit() -> None:
    one = _turns(20, t12={"statusFmtOk": False})
    assert w.b3_status(one, since=10) == []
    two = _turns(20, t12={"statusFmtOk": False}, t13={"statusPresent": False})
    assert w.b3_status(two, since=10)


def test_b3_run_already_seen_by_the_previous_check_is_not_repeated() -> None:
    turns = _turns(20, t5={"statusFmtOk": False}, t6={"statusFmtOk": False})
    assert w.b3_status(turns, since=10) == []


def test_b3_human_turn_between_does_not_break_the_run() -> None:
    turns = _turns(
        20,
        t12={"statusFmtOk": False},
        t13={"source": "human", "scored": False},
        t14={"statusFmtOk": False},
    )
    assert w.b3_status(turns, since=10)


# ---------------------------------------------------------------- B4 수치 노출


def test_b4_mimic_in_status_or_body() -> None:
    assert w.b4_mimic(_turns(20), since=10) == []
    assert w.b4_mimic(_turns(20, t11={"statusMimic": True}), since=10)
    assert w.b4_mimic(_turns(20, t19={"bodyMimic": ["도희 호감도 21"]}), since=10)


# ---------------------------------------------------------------- B6a 같은 출처 복제 3연속


def test_b6a_three_in_a_row_from_one_source() -> None:
    dup = {"dup": [{"src": "ex1", "sample": "…"}]}
    assert w.b6a_duplicate(_turns(20, t11=dup, t12=dup), since=10) == []
    assert w.b6a_duplicate(_turns(20, t11=dup, t12=dup, t13=dup), since=10)


def test_b6a_three_in_a_row_from_different_sources_is_quiet() -> None:
    turns = _turns(
        20,
        t11={"dup": [{"src": "ex1", "sample": "…"}]},
        t12={"dup": [{"src": "prev", "sample": "…"}]},
        t13={"dup": [{"src": "ex2", "sample": "…"}]},
    )
    assert w.b6a_duplicate(turns, since=10) == []


# ---------------------------------------------------------------- B6b 장거리 반복(보고만)


def test_b6b_reports_when_overlap_doubles_over_baseline() -> None:
    turns = _turns(70)
    fresh = {t["turn"]: " ".join(f"낱말{t['turn']}_{i}" for i in range(40)) for t in turns}
    assert w.b6b_long_repeat(turns, fresh) == []
    repeated = dict(fresh)
    for n in range(41, 71):
        repeated[n] = fresh[30]  # 기준 구간 밖 턴들이 같은 글을 되풀이한다
    assert w.b6b_long_repeat(turns, repeated)


# ---------------------------------------------------------------- B6c 상태창 시간 고착


def test_b6c_twenty_identical_times() -> None:
    same = {f"t{n}": {"statusTime": "월요일 저녁"} for n in range(1, 20)}
    assert w.b6c_time_stuck(_turns(25, **same), since=10) == []
    same20 = {f"t{n}": {"statusTime": "월요일 저녁"} for n in range(1, 21)}
    assert w.b6c_time_stuck(_turns(25, **same20), since=10)


def test_b6c_time_unchanged_on_two_consecutive_decrease_turns() -> None:
    one = _turns(
        20,
        t11={"statusTime": "화요일 밤"},
        t12={"statusTime": "화요일 밤", "countdownDelta": -1.0},
    )
    assert w.b6c_time_stuck(one, since=10) == []
    changed_then_stuck = _turns(
        20,
        t11={"statusTime": "화요일 밤"},
        t12={"statusTime": "수요일 낮", "countdownDelta": -1.0},
        t15={"statusTime": "수요일 낮"},
        t16={"statusTime": "수요일 낮", "countdownDelta": -2.0},
    )
    assert w.b6c_time_stuck(changed_then_stuck, since=10) == []
    two = _turns(
        20,
        t11={"statusTime": "화요일 밤"},
        t12={"statusTime": "화요일 밤", "countdownDelta": -1.0},
        t15={"statusTime": "수요일 낮"},
        t16={"statusTime": "수요일 낮", "countdownDelta": -2.0},
    )
    assert w.b6c_time_stuck(two, since=10)


# ---------------------------------------------------------------- B8 비용 급증


def _cost(turn: int, d: float) -> dict[str, Any]:
    return {"turn": turn, "dUsd": d}


def test_b8_cost_jump_against_turn_40_and_50_lines() -> None:
    lines = [_cost(40, 0.10), _cost(50, 0.12), _cost(60, 0.20)]
    assert w.b8_cost(_turns(60), lines, since=50) == []
    lines[-1] = _cost(60, 0.23)
    assert w.b8_cost(_turns(60), lines, since=50)


def _img(tokens: int) -> dict[str, Any]:
    return {"usage": [{"callSite": "chat_media_book_image", "promptTokens": tokens, "costUsd": 0.001}]}


def test_b8_image_judgment_input_over_one_and_a_half_times_the_plateau() -> None:
    plateau = {f"t{n}": _img(10_000) for n in range(40, 61)}
    calm = _turns(70, **plateau, t65=_img(14_000))
    assert w.b8_cost(calm, [], since=60) == []
    jump = _turns(70, **plateau, t65=_img(15_001))
    assert w.b8_cost(jump, [], since=60)


def test_b8_ending_judgment_input_against_the_first_call() -> None:
    def ending(tokens: int) -> dict[str, Any]:
        return {"usage": [{"callSite": "chat_ending_judgment", "promptTokens": tokens, "costUsd": 0.001}]}

    assert w.b8_cost(_turns(30, t10=ending(8000), t25=ending(12_000)), [], since=20) == []
    assert w.b8_cost(_turns(30, t10=ending(8000), t25=ending(12_001)), [], since=20)


# ---------------------------------------------------------------- B9 스탯 비정상


def test_b9_quiet_on_normal_moves() -> None:
    turns = _turns(20, t12={"countdownDelta": -3.0, "countdownAfter": 39.0})
    assert w.b9_stats(turns, {}, since=10) == []


def test_b9_countdown_increase_and_fraction() -> None:
    assert w.b9_stats(_turns(20, t12={"countdownDelta": 1.0}), {}, since=10)
    assert w.b9_stats(_turns(20, t12={"countdownAfter": 38.5}), {}, since=10)


def test_b9_no_longer_carries_affection_jumps() -> None:
    # 호감 급변은 정지 항목 B9 에서 빠져 보고만 항목 B9.affinity 로 옮겼다.
    jump = {name: 0.0 for name in AFF} | {"유나 호감도": 9.0}
    assert w.b9_stats(_turns(20, t12={"affectionDelta": jump}), {}, since=10) == []


def test_b9_affinity_catches_a_jump_over_eight_after_the_previous_check() -> None:
    jump = {name: 0.0 for name in AFF} | {"세빈 호감도": -35.0}
    assert w.b9_affinity(_turns(30, t25={"affectionDelta": jump}), since=20) == ["턴 25 세빈 호감도 Δ -35.0"]
    assert w.b9_affinity(_turns(30, t25={"affectionDelta": jump}), since=30) == []
    edge = {name: 0.0 for name in AFF} | {"세빈 호감도": 8.0}
    assert w.b9_affinity(_turns(30, t25={"affectionDelta": edge}), since=20) == []


def test_affinity_misread_tally_counts_every_turn_regardless_of_previous_checks() -> None:
    def jump(value: float) -> dict[str, Any]:
        return {"affectionDelta": {name: 0.0 for name in AFF} | {"세빈 호감도": value}}

    turns = _turns(40, t13=jump(-25.0), t25=jump(-35.0), t33=jump(9.5))
    assert w.affinity_misread_tally(turns) == {"b9AffinityMisreads": 3, "b9AffinityMisreadTurns": [13, 25, 33]}
    assert w.affinity_misread_tally(_turns(10)) == {"b9AffinityMisreads": 0, "b9AffinityMisreadTurns": []}


def test_b9_over_seven_request_twice_in_a_row_from_trace() -> None:
    def request(start: float, requested: float) -> list[dict[str, Any]]:
        return [{"name": "상영회까지", "start": start, "requested": requested}]

    once = {12: request(30, 20)}
    assert w.b9_stats(_turns(20), once, since=10) == []
    twice = {12: request(30, 20), 13: request(23, 14)}
    assert w.b9_stats(_turns(20), twice, since=10)


def test_b9_over_seven_proxy_without_trace() -> None:
    proxy = {"countdownDelta": -7.0, "dayPhrases": [{"text": "열흘 뒤", "days": 10}]}
    assert w.b9_stats(_turns(20, t12=proxy, t13=proxy), {}, since=10)
    # trace 가 있는 턴은 대리 지표를 쓰지 않는다 — 요청값이 7 이내면 걸리지 않는다
    traced = {12: [{"name": "상영회까지", "start": 30, "requested": 23}]}
    assert w.b9_stats(_turns(20, t12=proxy, t13=proxy), traced, since=10) == []


# ---------------------------------------------------------------- B11 접기 정체·백오프·첫 절단


def test_b11_raw_turns_backoff_and_first_truncation() -> None:
    state: dict[str, Any] = {}
    assert w.b11_memory(_turns(20), raw_turns=29, backoff_failures=0, state=state) == []
    assert w.b11_memory(_turns(20), raw_turns=40, backoff_failures=0, state={})
    assert w.b11_memory(_turns(20), raw_turns=25, backoff_failures=3, state={})
    long_summary = _turns(20, t18={"memory": {"summaryLen": 1500}})
    assert w.b11_memory(long_summary, raw_turns=25, backoff_failures=0, state=state)
    # 첫 절단만 멈춘다 — 다음 점검은 같은 절단으로 다시 걸지 않는다
    assert w.b11_memory(long_summary, raw_turns=25, backoff_failures=0, state=state) == []


# ---------------------------------------------------------------- B12 응답 크기·지연


def test_b12_reply_length_tripled_three_in_a_row_and_slow_turn() -> None:
    assert w.b12_size_latency(_turns(20), since=10) == []
    big = {"replyLen": 600}
    assert w.b12_size_latency(_turns(20, t12=big, t13=big), since=10) == []
    assert w.b12_size_latency(_turns(20, t12=big, t13=big, t14=big), since=10)
    assert w.b12_size_latency(_turns(20, t15={"seconds": 61.0}), since=10)


def test_b12_uses_the_previous_fifty_turn_bin_as_baseline() -> None:
    flat = {f"t{n}": {"replyLen": 100} for n in range(1, 61)}
    almost = {"replyLen": 199}
    assert w.b12_size_latency(_turns(60, **(flat | {"t52": almost, "t53": almost, "t54": almost})), since=50) == []
    big = {"replyLen": 200}
    assert w.b12_size_latency(_turns(60, **(flat | {"t52": big, "t53": big, "t54": big})), since=50)
    # 기준은 직전 구간만 — 지금 구간의 긴 응답이 기준을 끌어올리면 안 된다
    longer_now = {f"t{n}": {"replyLen": 100} for n in range(1, 51)} | {
        f"t{n}": {"replyLen": 150} for n in range(51, 101)
    }
    longer_now |= {"t81": big, "t82": big, "t83": big}
    assert w.b12_size_latency(_turns(100, **longer_now), since=80)


# ---------------------------------------------------------------- 원가


def _usage_line(room: str, site: str, prompt: str = "1000", total: str = "1100") -> str:
    return (
        f"2026-10-05T17:10:00.000+0900 gemini_usage call_site={site} model=gemini-3.5-flash-lite "
        f"prompt_tokens={prompt} cached_content_tokens=None candidates_tokens=100 thoughts_tokens=None "
        f"total_tokens={total} user_id=u room_id={room}"
    )


def test_room_cost_counts_only_the_measurement_room_and_skips_replays() -> None:
    lines = [
        _usage_line(ROOM, "chat_generate"),
        _usage_line(OTHER, "chat_generate"),
        _usage_line(ROOM, "replay_media_book_image"),
    ]
    cost = w.room_conversation_cost(lines, ROOM)
    single = w.room_conversation_cost([_usage_line(ROOM, "chat_generate")], ROOM)
    assert cost["total"] == single["total"] > 0
    assert set(cost["byCallSite"]) == {"chat_generate"}


def test_room_cost_restores_missing_prompt_tokens_from_total() -> None:
    restored = w.room_conversation_cost([_usage_line(ROOM, "chat_generate", prompt="None", total="1100")], ROOM)
    plain = w.room_conversation_cost([_usage_line(ROOM, "chat_generate", prompt="1000", total="1100")], ROOM)
    assert restored["total"] == plain["total"]


def test_redis_cost_splits_replay_from_conversation() -> None:
    hashes = {
        "llm_usage:2026-10-05": {
            "chat_generate|gemini-3.5-flash-lite|prompt": "1000",
            "chat_generate|gemini-3.5-flash-lite|candidates": "100",
            "chat_generate|gemini-3.5-flash-lite|total": "1100",
            "replay_media_book_image|gemini-3.5-flash-lite|prompt": "200000",
            "replay_media_book_image|gemini-3.5-flash-lite|total": "200050",
            "replay_media_book_image|gemini-3.5-flash-lite|candidates": "50",
        },
        "llm_usage:2026-10-04": {"chat_generate|gemini-3.5-flash-lite|prompt": "999999"},
    }
    cost = w.redis_cost(hashes, since_day="2026-10-05")
    assert 0 < cost["convAllRooms"] < cost["replay"]
    assert cost["unpriced"] == 0


def test_redis_cost_counts_stat_judgment_replay_as_replay() -> None:
    hashes = {
        "llm_usage:2026-10-05": {
            "replay_stat_judgment|gemini-3.1-flash-lite|prompt": "1743",
            "replay_stat_judgment|gemini-3.1-flash-lite|candidates": "76",
            "replay_stat_judgment|gemini-3.1-flash-lite|total": "1819",
        }
    }
    cost = w.redis_cost(hashes, since_day="2026-10-05")
    assert cost["replay"] > 0 and cost["convAllRooms"] == 0


def _line(conv: float, replay: float = 0.0, d: float = 0.01, unpriced: int = 0) -> dict[str, Any]:
    return {
        "turn": 10,
        "cConvUsd": conv,
        "cReplayUsd": replay,
        "dUsd": d,
        "unpricedCalls": unpriced,
        "redisConvAllRoomsUsd": conv,
    }


def test_cost_rules_quiet_then_each_stop() -> None:
    state: dict[str, Any] = {}
    assert w.judge_cost(_line(1.0), _line(0.9), state) == []
    stops = {a["item"] for a in w.judge_cost(_line(0.5), _line(0.9), {}) if a["stop"]}
    assert stops == {"cost.decrease"}
    stops = {a["item"] for a in w.judge_cost(_line(0.9, replay=0.1), _line(0.8, replay=0.2), {}) if a["stop"]}
    assert stops == {"cost.decrease"}
    assert {a["item"] for a in w.judge_cost(_line(9.6, d=0.4), _line(9.2), {}) if a["stop"]} >= {"cost.conversation10"}
    assert {
        a["item"] for a in w.judge_cost(_line(5.0, replay=19.8, d=0.3), _line(4.7, replay=19.8), {}) if a["stop"]
    } == {"cost.total25"}
    assert {a["item"] for a in w.judge_cost(_line(1.0, unpriced=1), _line(0.9), {}) if a["stop"]} == {"cost.unpriced"}


def test_cost_eight_dollars_is_reported_once_without_stopping() -> None:
    state: dict[str, Any] = {}
    first = w.judge_cost(_line(8.0, d=0.1), _line(7.9), state)
    assert [(a["item"], a["stop"]) for a in first] == [("cost.conversation8", False)]
    assert w.judge_cost(_line(8.1, d=0.1), _line(8.0), state) == []


# ---------------------------------------------------------------- 정지 파일·경보 기록


def test_outcome_writes_check_alerts_and_stop_file(tmp_path: Path) -> None:
    items = {"B3": {"hit": True, "evidence": ["턴 12·13"]}, "B4": {"hit": False, "evidence": []}}
    alerts = w.item_alerts(items, report_only=set())
    w.write_outcome(tmp_path, 20, items, alerts)
    assert (tmp_path / "STOP").exists()
    check = json.loads((tmp_path / "checks" / "t020.json").read_text(encoding="utf-8"))
    assert check["stop"] is True and check["items"]["B3"]["hit"] is True
    logged = [json.loads(x) for x in (tmp_path / "watch" / "alerts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(a["item"], a["stop"]) for a in logged] == [("B3", True)]


def test_report_only_items_and_long_repeat_never_touch_the_stop_file(tmp_path: Path) -> None:
    items = {"B3": {"hit": True, "evidence": ["턴 12·13"]}, "B6b": {"hit": True, "evidence": ["겹침 0.4"]}}
    alerts = w.item_alerts(items, report_only={"B3"})
    w.write_outcome(tmp_path, 20, items, alerts)
    assert not (tmp_path / "STOP").exists()
    assert all(a["stop"] is False for a in alerts) and len(alerts) == 2


def test_b9_countdown_items_stop_even_when_listed_as_report_only(tmp_path: Path) -> None:
    # 「상영회까지」 이상 이동은 재개 뒤에도 매번 멈춘다 — 재기동 인자에 B9 를 보고만으로 넣어도 정지가 풀리지 않는다.
    items = {"B9": {"hit": True, "evidence": ["턴 33 「상영회까지」 증가 2.0"]}, "B3": {"hit": True, "evidence": ["x"]}}
    alerts = w.item_alerts(items, report_only={"B9", "B3"})
    assert {a["item"]: a["stop"] for a in alerts} == {"B9": True, "B3": False}
    w.write_outcome(tmp_path, 40, items, alerts)
    assert (tmp_path / "STOP").exists()


def test_affection_jump_is_alerted_but_never_touches_the_stop_file(tmp_path: Path) -> None:
    items = {
        "B9": {"hit": False, "evidence": []},
        "B9.affinity": {"hit": True, "evidence": ["턴 33 세빈 호감도 Δ -20.0"]},
    }
    alerts = w.item_alerts(items, report_only=set())
    assert [(a["item"], a["stop"]) for a in alerts] == [("B9.affinity", False)]
    w.write_outcome(tmp_path, 40, items, alerts)
    assert not (tmp_path / "STOP").exists()
    assert "B9.affinity" in w.REPORT_ONLY_ALWAYS


def test_trace_reader_keeps_stats_when_the_record_also_carries_the_raw_judgment(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    stats = [{"name": "세빈 호감도", "start": 52.5, "requested": 27.5, "applied": 27.5}]
    record = {
        "kind": "stat_outcome",
        "turn": 13,
        "roomId": "r",
        "stats": stats,
        "judgmentOutput": {"stat_changes": [{"stat_id": "s", "new_value": 27.5}]},
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    assert w.trace_stat_outcomes(path, "r") == {13: stats}


# ---------------------------------------------------------------- E1 「상영회까지」 남은 턴의 엔딩 판정


def _ending_call() -> dict[str, Any]:
    return {"usage": [{"callSite": "chat_ending_judgment", "promptTokens": 8000, "costUsd": 0.001}]}


def test_e1_quiet_when_ending_judgment_runs_only_at_zero() -> None:
    at_zero = _turns(20, t15={"countdownAfter": 0.0, **_ending_call()})
    assert w.e1_ending_judgment(at_zero, since=10) == []


def test_e1_ending_judgment_attempt_while_countdown_remains() -> None:
    assert w.e1_ending_judgment(_turns(20, t15=_ending_call()), since=10)
    failed = {"logFailures": [{"failure": "judgment", "timeout": False}]}
    assert w.e1_ending_judgment(_turns(20, t15=failed), since=10)


def test_e1_skips_turns_whose_stat_judgment_failed_and_turns_already_seen() -> None:
    stat_failed = _ending_call() | {"logFailures": [{"failure": "stat_judgment", "timeout": False}]}
    assert w.e1_ending_judgment(_turns(20, t15=stat_failed), since=10) == []
    assert w.e1_ending_judgment(_turns(20, t5=_ending_call()), since=10) == []


def test_e1_trace_crosscheck_reports_a_call_missing_from_the_log() -> None:
    traced = {"calls": [{"callSite": "chat_ending_judgment", "ok": True}]}
    assert w.e1_ending_judgment(_turns(20, t15=traced), since=10) == []
    assert w.e1_crosscheck(_turns(20, t15=traced), since=10)
    assert w.e1_crosscheck(_turns(20), since=10) == []


# ---------------------------------------------------------------- E5 단계 노트 정확히 1


STAGES = {
    "준비 초반": "콘티를 짠다",
    "촬영 기간": "카메라가 돈다",
    "상영회 직전": "포스터를 붙인다",
    "상영회 당일": "불이 꺼진다",
}


def _dump(turn: int, prompt: str, room: str = ROOM) -> dict[str, Any]:
    return {"roomId": room, "turn": turn, "systemInstruction": "규칙", "prompt": prompt}


def test_e5_quiet_with_exactly_one_stage_note() -> None:
    records = [_dump(n, f"[현재 상황]\n{STAGES['준비 초반']}\n대화") for n in range(1, 21)]
    assert w.e5_stage_notes(records, STAGES, ROOM, since=0) == []


def test_e5_zero_or_two_stage_notes_in_one_record() -> None:
    none = [_dump(n, "[현재 상황]\n대화") if n == 15 else _dump(n, STAGES["촬영 기간"]) for n in range(1, 21)]
    assert w.e5_stage_notes(none, STAGES, ROOM, since=10)
    two = [_dump(15, STAGES["촬영 기간"] + "\n" + STAGES["상영회 직전"])]
    assert w.e5_stage_notes(two, STAGES, ROOM, since=10)


def test_e5_ignores_other_rooms_and_records_already_seen() -> None:
    records = [_dump(15, "대화", room=OTHER), _dump(5, "대화")]
    assert w.e5_stage_notes(records, STAGES, ROOM, since=10) == []


def test_e5_stage_texts_come_from_the_four_named_frame_notes(tmp_path: Path) -> None:
    notes = [{"name": name, "infoText": text} for name, text in STAGES.items()]
    notes.append({"name": "도희가 곁을 허락함", "infoText": "호감 노트"})
    frame = tmp_path / "frame.json"
    frame.write_text(json.dumps({"situationNotes": notes}, ensure_ascii=False), encoding="utf-8")
    assert w.stage_note_texts(frame) == STAGES


def test_e5_crosscheck_reports_turns_whose_recomputed_stage_is_not_one() -> None:
    def staged(**over: dict[str, Any]) -> list[dict[str, Any]]:
        turns = _turns(20, **over)
        for t in turns:
            t.setdefault("stage", ["준비 초반"])
        return turns

    assert w.e5_crosscheck(staged(), since=10) == []
    assert w.e5_crosscheck(staged(t15={"stage": []}), since=10)
    assert w.e5_crosscheck(staged(t15={"stage": ["준비 초반", "촬영 기간"]}), since=10)
