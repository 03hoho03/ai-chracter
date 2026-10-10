"""생성 리플레이가 드라이버 로그·덤프에서 지난 턴의 상태를 고르는 규칙, 작품 글 치환 단언, 호출 상한·장부, CLI 인자 규칙을
DB·LLM 없이 본다."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from generation_replay import parse_args
from replay import logs as replay_logs
from replay.budget import UNKNOWN_CALL_USD, CallBudget, ledger_paths, sum_ledger
from replay.logs import DriverLogs, ReplayRefusedError
from replay.swap import SwapSlot, check_swap, load_swap_table, unique_fragments

ROOM = uuid.uuid4()


def _write(path: Path, records: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    return path


def _after(turn_count: int, value: float, source: str = "sse") -> dict[str, Any]:
    return {"turnCount": turn_count, "stats": {"신뢰": value}, "endingReached": False, "source": source}


def _logs(lines: list[dict[str, Any]], snapshots: list[dict[str, Any]] | None = None) -> DriverLogs:
    return DriverLogs(room_id=ROOM, lines=lines, snapshots=snapshots or [])


# ---- 덤프 ------------------------------------------------------------------------------------


def test_dump_record_takes_the_last_line_of_that_room_and_turn(tmp_path: Path) -> None:
    dump = _write(
        tmp_path / "dump.jsonl",
        [
            {"roomId": str(ROOM), "turn": 5, "systemInstruction": "s", "prompt": "유실된 첫 시도"},
            {"roomId": str(uuid.uuid4()), "turn": 5, "systemInstruction": "s", "prompt": "다른 방"},
            {"roomId": str(ROOM), "turn": 5, "systemInstruction": "s", "prompt": "응답이 남은 재시도"},
            {"roomId": str(ROOM), "turn": 6, "systemInstruction": "s", "prompt": "다음 턴"},
        ],
    )
    record, count = replay_logs.dump_record(dump, ROOM, 5)
    assert (record["prompt"], count) == ("응답이 남은 재시도", 2)
    with pytest.raises(ReplayRefusedError, match="덤프에 턴 7"):
        replay_logs.dump_record(dump, ROOM, 7)


def test_dump_record_picks_the_generation_line_even_when_judgment_lines_follow_it(tmp_path: Path) -> None:
    """측정 서버는 판정 프롬프트도 같은 덤프에 남기고, 판정은 생성 뒤에 돈다 — 판정 줄이 그 턴의 마지막 줄이 된다. 리플레이는
    생성 줄(`kind` 가 없는 옛 줄이나 `generation`)만 고르고 세야 한다. 판정 줄을 세면 유실 턴 재시도처럼 보이고, 판정 줄을
    고르면 지시문이 없는 줄로 조립을 대조한다."""
    dump = _write(
        tmp_path / "dump.jsonl",
        [
            {"roomId": str(ROOM), "turn": 4, "systemInstruction": "s", "prompt": "옛 덤프의 생성 줄"},
            {"roomId": str(ROOM), "turn": 4, "kind": "judgment", "callSite": "chat_stat_judgment", "prompt": "판정"},
            {"roomId": str(ROOM), "turn": 5, "kind": "generation", "systemInstruction": "s", "prompt": "생성"},
            {"roomId": str(ROOM), "turn": 5, "kind": "judgment", "callSite": "chat_stat_judgment", "prompt": "스탯"},
            {"roomId": str(ROOM), "turn": 5, "kind": "judgment", "callSite": "chat_media_book_image", "prompt": "칸"},
            {"roomId": str(ROOM), "turn": 6, "kind": "judgment", "callSite": "chat_stat_judgment", "prompt": "판정만"},
        ],
    )
    assert replay_logs.dump_record(dump, ROOM, 4) == (
        {"roomId": str(ROOM), "turn": 4, "systemInstruction": "s", "prompt": "옛 덤프의 생성 줄"},
        1,
    )
    record, count = replay_logs.dump_record(dump, ROOM, 5)
    assert (record["prompt"], count) == ("생성", 1)
    # 판정 줄만 있는 턴은 생성 덤프가 없는 턴이다.
    with pytest.raises(ReplayRefusedError, match="덤프에 턴 6"):
        replay_logs.dump_record(dump, ROOM, 6)


# ---- 스탯 기준 줄 ------------------------------------------------------------------------------


def test_stats_for_the_first_turn_come_from_the_opening_line() -> None:
    lines: list[dict[str, Any]] = [
        {"kind": "opening", "roomAfter": _after(0, 50, "create")},
        {"kind": "turn", "clientTurn": 1, "turnBefore": 0, "http": 200, "done": True, "roomAfter": _after(1, 60)},
    ]
    index, record = replay_logs.stats_line(_logs(lines), 1)
    assert (index, record["kind"], record["roomAfter"]["stats"]) == (0, "opening", {"신뢰": 50})


def test_after_a_lost_turn_the_rebase_line_is_the_stats_source_and_partial_reply_is_ignored() -> None:
    lines: list[dict[str, Any]] = [
        {"kind": "opening", "roomAfter": _after(0, 50, "create")},
        {"kind": "turn", "clientTurn": 1, "turnBefore": 0, "http": 200, "done": True, "roomAfter": _after(1, 60)},
        # 완료 없이 끝난 턴(200 인데 done 없음)과 전송 실패 턴은 roomAfter 가 비어 출처가 되지 않는다.
        {
            "kind": "turn",
            "clientTurn": 2,
            "turnBefore": 1,
            "http": 200,
            "done": False,
            "reply": "",
            "partialReply": "잘린 조각",
            "roomAfter": None,
        },
        {"kind": "turn", "clientTurn": 2, "turnBefore": 1, "http": None, "done": False, "roomAfter": None},
        {"kind": "rebase", "roomAfter": _after(1, 61, "refetch")},
        {"kind": "turn", "clientTurn": 2, "turnBefore": 1, "http": 200, "done": True, "roomAfter": _after(2, 70)},
        {"kind": "check", "roomAfter": _after(2, 70, "refetch")},
        {"kind": "turn", "clientTurn": 3, "turnBefore": 2, "http": 200, "done": True, "roomAfter": _after(3, 75)},
    ]
    logs = _logs(lines)
    index, record = replay_logs.stats_line(logs, 2)
    assert (index, record["kind"], record["roomAfter"]["stats"]["신뢰"]) == (4, "rebase", 61)
    # 턴 2 를 마친 줄은 재시도 줄이다.
    assert replay_logs.turn_line(logs, 2)[0] == 5
    # 턴 3 은 턴 2 뒤의 마지막 줄(대조 줄)에서.
    assert replay_logs.stats_line(logs, 3)[1]["kind"] == "check"


def test_a_turn_completed_by_the_server_without_a_done_event_is_still_found() -> None:
    lines: list[dict[str, Any]] = [
        {"kind": "opening", "roomAfter": _after(0, 50, "create")},
        {"kind": "turn", "clientTurn": 1, "turnBefore": 0, "http": 200, "done": False, "shortcutId": "s"},
        {"kind": "rebase", "roomAfter": _after(1, 55, "refetch")},
    ]
    index, record = replay_logs.turn_line(_logs(lines), 1)
    assert (index, record["shortcutId"]) == (1, "s")
    assert replay_logs.stats_line(_logs(lines), 1)[1]["kind"] == "opening"


def test_a_human_supplement_line_counts_as_the_turn_line() -> None:
    lines: list[dict[str, Any]] = [
        {"kind": "turn", "clientTurn": 104, "turnBefore": 103, "http": 200, "done": True, "roomAfter": _after(104, 4)},
        {"kind": "pause", "turnCount": 104},
        {"kind": "turn", "source": "human", "http": 200, "done": True, "roomAfter": _after(105, 0, "db+trace")},
    ]
    assert replay_logs.turn_line(_logs(lines), 105)[0] == 2
    assert replay_logs.stats_line(_logs(lines), 105)[0] == 0


def test_missing_stats_line_or_turn_line_is_refused() -> None:
    lines: list[dict[str, Any]] = [
        {"kind": "turn", "clientTurn": 3, "turnBefore": 2, "http": 200, "done": True, "roomAfter": _after(3, 1)}
    ]
    with pytest.raises(ReplayRefusedError, match="턴 수 2"):
        replay_logs.stats_line(_logs(lines), 3)
    with pytest.raises(ReplayRefusedError, match="턴 4 줄이 없다"):
        replay_logs.turn_line(_logs(lines), 4)


# ---- 기억 스냅숏 ------------------------------------------------------------------------------


def test_memory_snapshot_is_the_last_one_at_or_before_the_turn_in_file_order() -> None:
    snapshots: list[dict[str, Any]] = [
        {"kind": "memorySnapshot", "turn": 1, "note": "1턴"},
        {"kind": "roomStatic"},
        {"kind": "memorySnapshot", "turn": 7, "note": "7턴 첫 시도"},
        # 유실 턴과 재시도 사이에 노트를 바꾸면 같은 턴 번호가 둘이다 — 재시도 때 보낸 것이 뒤에 있다.
        {"kind": "memorySnapshot", "turn": 7, "note": "7턴 재시도"},
    ]
    logs = _logs([], snapshots)
    notes = [replay_logs.memory_snapshot(logs, t)["note"] for t in (1, 6, 7, 30)]
    assert notes == ["1턴", "1턴", "7턴 재시도", "7턴 재시도"]
    with pytest.raises(ReplayRefusedError, match="이하"):
        replay_logs.memory_snapshot(_logs([], snapshots[2:]), 6)


# ---- roomStatic -------------------------------------------------------------------------------


def _static(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "kind": "roomStatic",
        "stats": [{"id": "a", "name": "신뢰", "unit": ""}, {"id": "b", "name": "용기", "unit": ""}],
        "shortcuts": [{"id": "s", "name": "넘기기", "prompt": "p"}],
        "effectiveChatModel": "gemini",
    }
    return record | changes


def test_room_static_maps_names_and_reads_an_old_record_as_having_no_fixed_values() -> None:
    static = replay_logs.room_static(_logs([], [_static(), _static()]))
    assert static.stat_ids == {"신뢰": "a", "용기": "b"}
    assert static.shortcut_ids == {"넘기기": "s"}
    assert static.fixed is None


def test_room_static_refuses_records_that_disagree_or_duplicate_stat_names() -> None:
    other = _static(stats=[{"id": "x", "name": "신뢰", "unit": ""}])
    with pytest.raises(ReplayRefusedError, match="기록마다 다르다"):
        replay_logs.room_static(_logs([], [_static(), other]))
    twice = _static(stats=[{"id": "a", "name": "신뢰", "unit": ""}, {"id": "b", "name": "신뢰", "unit": ""}])
    with pytest.raises(ReplayRefusedError, match="이름이 같은"):
        replay_logs.room_static(_logs([], [twice]))
    with pytest.raises(ReplayRefusedError, match="roomStatic 이 없다"):
        replay_logs.room_static(_logs([], []))


def test_room_static_names_the_cause_when_old_and_new_records_are_mixed() -> None:
    # 고정값 기록이 없는 옛 로그를 기준을 다시 잡아 이어 친 방 — 기록이 "없음/있음"으로 섞여 방 전체를 거부한다.
    fixed = _static(contentVersionId=str(uuid.uuid4()), defaultUserName="나")
    for records in ([_static(), fixed], [fixed, _static()]):
        with pytest.raises(ReplayRefusedError, match="고정값이 있는 기록과 없는 기록이 섞였다"):
            replay_logs.room_static(_logs([], records))
    # 고정값끼리 다르면 섞였다고 하지 않는다.
    other = _static(contentVersionId=str(uuid.uuid4()), defaultUserName="나")
    with pytest.raises(ReplayRefusedError, match="기록마다 다르다") as refused:
        replay_logs.room_static(_logs([], [fixed, other]))
    assert "섞였다" not in str(refused.value)


# ---- 치환 표 ----------------------------------------------------------------------------------


def _slots() -> list[SwapSlot]:
    return [
        SwapSlot(key="무대", before="사흘 뒤처럼", after="다음 날·이틀 뒤처럼"),
        SwapSlot(key="직전", before="일주일도 안 남았다.", after="코앞이다."),
    ]


def _check(swapped: str, slots: list[SwapSlot], base: str = "[무대] 사흘 뒤처럼 적는다. [대화]") -> Any:
    return check_swap(base_prompt=base, base_system="s", swapped_prompt=swapped, swapped_system="s", slots=slots)


def test_swap_check_passes_only_when_every_loaded_slot_was_swapped_and_nothing_else_changed() -> None:
    ok = _check("[무대] 다음 날·이틀 뒤처럼 적는다. [대화]", _slots())
    assert ok["passed"] and ok["loadedSlots"] == ["무대"] and ok["swapCounts"] == {"무대": 1, "직전": 0}
    # 덜 바꿔 끼움 — 되돌리면 같지만 양성 단언이 잡는다.
    under = _check("[무대] 사흘 뒤처럼 적는다. [대화]", _slots())
    assert under["reverseIdentical"] and under["missingSlots"] == ["무대"] and not under["passed"]
    # 표 밖 변경 — 개수·잔존은 맞고 역치환만 잡는다.
    extra = _check("[무대] 다음 날·이틀 뒤처럼 적는다. [대화!]", _slots())
    assert not extra["countMismatch"] and not extra["uniqueFragmentResidue"] and not extra["missingSlots"]
    assert not extra["reverseIdentical"] and extra["firstDifferenceAt"] == 20 and not extra["passed"]
    # 실리지 않은 칸의 바꾼 글이 생김.
    leaked = _check("[무대] 다음 날·이틀 뒤처럼 적는다. 코앞이다. [대화]", _slots())
    assert leaked["unexpectedSlots"] == ["직전"] and not leaked["passed"]
    # 그 턴에 실린 칸이 하나도 없으면 두 갈래가 같은 프롬프트라 비교할 것이 없다.
    nothing = _check("[대화]", _slots(), base="[대화]")
    assert nothing["reverseIdentical"] and not nothing["loadedSlots"] and not nothing["passed"]


def test_swap_check_fails_when_only_one_of_two_places_of_the_same_text_was_swapped() -> None:
    base = "[무대] 사흘 뒤처럼 적는다. [예시] 사흘 뒤처럼 적는다. [대화]"
    half = _check("[무대] 다음 날·이틀 뒤처럼 적는다. [예시] 사흘 뒤처럼 적는다. [대화]", _slots(), base=base)
    assert half["reverseIdentical"] and not half["missingSlots"]
    assert half["countMismatch"] == ["무대"] and half["beforeLeftover"] == {"무대": 1} and not half["passed"]
    full = _check("[무대] 다음 날·이틀 뒤처럼 적는다. [예시] 다음 날·이틀 뒤처럼 적는다. [대화]", _slots(), base=base)
    assert full["passed"] and full["baseCounts"]["무대"] == full["swapCounts"]["무대"] == 2


def test_unique_fragment_residue_counts_history_copies_and_catches_old_text_outside_the_slot() -> None:
    slot = SwapSlot(key="규칙", before="시간 | 요일과 때", after="시간 | 날짜·요일과 때")
    (fragment,) = unique_fragments(slot.before, slot.after)
    assert fragment in slot.before and fragment not in slot.after
    base = "[규칙] 시간 | 요일과 때 [대화] 시간 | 요일과 때"
    result = check_swap(
        base_prompt=base,
        base_system="s",
        swapped_prompt="[규칙] 시간 | 날짜·요일과 때 [대화] 시간 | 요일과 때",
        swapped_system="s",
        slots=[slot],
    )
    assert result["swapCounts"] == {"규칙": 1} and result["countMismatch"] == ["규칙"] and not result["passed"]


def test_prompt_form_lets_the_check_compare_author_text_with_the_rendered_prompt() -> None:
    slot = SwapSlot(key="설정", before="{{user}}의 사흘 뒤", after="{{user}}의 다음 날")
    result = check_swap(
        base_prompt="[설정] 하늘의 사흘 뒤",
        base_system="s",
        swapped_prompt="[설정] 하늘의 다음 날",
        swapped_system="s",
        slots=[slot],
        prompt_form=lambda text: text.replace("{{user}}", "하늘"),
    )
    assert result["passed"]


def test_swap_table_rejects_empty_duplicate_unchanged_and_unknown_targets(tmp_path: Path) -> None:
    path = tmp_path / "table.json"
    for slots, message in (
        ([], "칸이 없다"),
        ([{"key": "a", "before": "x", "after": "y"}] * 2, "같은 칸"),
        ([{"key": "a", "before": "x", "after": "x"}], "같다"),
        ([{"key": "a", "before": "x", "after": "y", "target": "stat"}], "모른다"),
        (
            [
                {"key": "a", "before": "x", "after": "y", "target": "historyOpening"},
                {"key": "b", "before": "z", "after": "w", "target": "historyOpening"},
            ],
            "하나뿐",
        ),
    ):
        path.write_text(json.dumps({"slots": slots}), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_swap_table(path)


# ---- 상한·장부 --------------------------------------------------------------------------------


def test_budget_stops_on_calls_or_on_actual_cost_including_the_ledger(tmp_path: Path) -> None:
    budget = CallBudget(5, usd_limit=0.01, spent_usd=0.004)
    assert budget.take()
    budget.charge({"costUsd": 0.005})
    assert budget.take()
    budget.charge({"costUsd": 0.002})  # 누적 0.011 ≥ 0.01
    assert not budget.take() and budget.used == 2
    calls = CallBudget(1)
    assert calls.take() and not calls.take()
    unknown = CallBudget(5, usd_limit=0.015)
    assert unknown.take()
    unknown.charge({"costUsd": None})  # 원가를 모르면 넉넉히 센다
    assert unknown.spent_usd == UNKNOWN_CALL_USD
    ledger = tmp_path / "a" / "gen.jsonl"
    ledger.parent.mkdir()
    _write(ledger, [{"kind": "plan"}, {"kind": "call", "costUsd": 0.002}, {"kind": "call", "costUsd": None}])
    total = sum_ledger(ledger_paths(str(tmp_path / "**" / "*.jsonl")))
    assert (total.calls, total.unknown_calls) == (2, 1)
    assert total.charged_usd == pytest.approx(0.002 + UNKNOWN_CALL_USD)


# ---- CLI 인자 ---------------------------------------------------------------------------------

_BASE = ["--room", str(ROOM), "--turn", "3", "--dump", "d", "--log", "l", "--snapshot-log", "s"]
_BASE += ["--limit-calls", "4", "--out", "o"]


def test_window_only_dry_run_takes_no_arm_name() -> None:
    args, arm = parse_args(_BASE)
    assert arm is None and args.reps == 2 and not args.execute
    with pytest.raises(SystemExit):
        parse_args([*_BASE, "--arm", "B"])


def test_the_same_turn_twice_is_refused() -> None:
    with pytest.raises(SystemExit):
        parse_args([*_BASE, "--turn", "3"])


def test_a_call_without_known_cost_is_charged_at_its_recorded_ceiling(tmp_path: Path) -> None:
    budget = CallBudget(5, usd_limit=0.1)
    assert budget.take()
    budget.charge({"costUsd": None, "costCeilingUsd": 0.12})
    assert budget.spent_usd == pytest.approx(0.12) and not budget.take()
    ledger = _write(
        tmp_path / "gen.jsonl",
        [{"kind": "call", "costUsd": None, "costCeilingUsd": 0.12}, {"kind": "call", "costUsd": 0.002}],
    )
    assert sum_ledger([ledger]).charged_usd == pytest.approx(0.122)


def test_axes_need_an_arm_name_and_only_set_and_model_combine() -> None:
    _, arm = parse_args([*_BASE, "--set", "draft", "--model", "sonnet", "--arm", "draft-sonnet"])
    assert arm is not None and (arm.variant, arm.set_draft, arm.model) == ("set", True, "sonnet")
    _, arm = parse_args([*_BASE, "--model", "opus", "--arm", "opus"])
    assert arm is not None and (arm.variant, arm.model) == ("model", "opus")
    for extra in (
        ["--model", "sonnet"],  # 이름 없음
        ["--model", "sonnet", "--version", str(uuid.uuid4()), "--arm", "x"],  # 두 축
        ["--set", "draft", "--version", str(uuid.uuid4()), "--arm", "x"],
        ["--model", "sonnet", "--arm", "window"],  # 현행 갈래 이름
        ["--model", "sonnet", "--arm", "a/b"],  # 파일 이름에 못 쓰는 글자
        ["--set", "not-a-uuid", "--arm", "x"],
        ["--skip-window-calls"],  # 축 없이
    ):
        with pytest.raises(SystemExit):
            parse_args([*_BASE, *extra])


def test_swap_axis_loads_the_table_and_labels_it_with_the_arm(tmp_path: Path) -> None:
    table = tmp_path / "t.json"
    table.write_text(json.dumps({"slots": [{"key": "a", "before": "x", "after": "y"}]}), encoding="utf-8")
    _, arm = parse_args([*_BASE, "--swap-table", str(table), "--arm", "W"])
    assert arm is not None and (arm.variant, arm.arm, arm.swap) == ("swap", "W", (SwapSlot("a", "x", "y"),))


def test_window_set_and_room_take_only_ids_as_argument_errors() -> None:
    args, _ = parse_args([*_BASE, "--window-set", str(ROOM)])
    assert args.window_set == ROOM
    room_at = _BASE.index("--room") + 1
    for argv in ([*_BASE, "--window-set", "not-a-uuid"], [*_BASE[:room_at], "room-1", *_BASE[room_at + 1 :]]):
        with pytest.raises(SystemExit) as exited:
            parse_args(argv)
        assert exited.value.code == 2
