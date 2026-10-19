"""평가 하네스 리뷰 지적 — 합격선 대상 필터, 옛 원장 형식, 판정자 상한 예외, 숫자 경계, 재실행 멱등성, 서버 로그 원가,
공유 서버 거부, 추출 연속 실패·빈 에피소드, 최종 짝 비교 집계, 회상 칸·머리글, 단계별 템플릿 이름, 스택 블록 판정."""

import json
import os
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from memory_eval.ledger import BudgetExceededError, Ledger
from memory_eval.metrics import answer_matches
from memory_eval.plants import PlantSet, load_plants


def _entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "obj01",
        "category": "물건",
        "plantTurn": 3,
        "keywords": ["펭귄"],
        "answerKeys": [["펭귄"]],
        "questionForm": "direct",
        "question": "무슨 동물이었지?",
        "probeCheckpoints": {"opus": [300], "offline": [300]},
        "split": "test",
        "metrics": {"MR1_passline": True, "MA1_pair": True, "MA1_300": True},
    }
    base.update(overrides)
    return base


def _set(plants: list[dict[str, Any]], abstains: list[dict[str, Any]] | None = None) -> PlantSet:
    return PlantSet(raw={"seed": 1, "checkpoints": [50, 100, 300]}, plants=plants, abstains=abstains or [])


# ---------------------------------------------------------------- 1. 직접 형식 합격선의 대상


def _offline_row(item: str, recall3: bool | None = True) -> dict[str, Any]:
    return {
        "item_id": item,
        "kind": "question",
        "form": "direct",
        "checkpoint": 300,
        "split": "test",
        "recall3": recall3,
    }


def test_direct_passline_counts_only_items_marked_for_the_passline() -> None:
    from memory_eval.recall_offline import direct_passline

    plants = _set([_entry(id="obj06"), _entry(id="spk04", category="화자", metrics={"MR1_passline": False})])
    verdict = direct_passline([_offline_row("obj06"), _offline_row("spk04")], plants, threshold=0.7)
    assert verdict["n"] == 1
    assert verdict["excluded"] == ["spk04"]


_REAL_PLANTS = os.environ.get("MEMORY_EVAL_PLANTS")


@pytest.mark.skipif(not _REAL_PLANTS, reason="실제 심기 표 경로(MEMORY_EVAL_PLANTS)가 없다")
def test_direct_passline_on_the_registered_plant_table_has_the_seven_registered_items() -> None:
    from memory_eval.recall_offline import direct_passline

    assert _REAL_PLANTS is not None
    plants = load_plants(Path(_REAL_PLANTS))
    rows = [
        _offline_row(str(p["id"]))
        for p in plants.plants
        if p["split"] == "test" and p["questionForm"] == "direct" and 300 in p["probeCheckpoints"]["offline"]
    ]
    verdict = direct_passline(rows, plants, threshold=0.7)
    assert verdict["n"] == 7
    assert verdict["items"] == sorted(["obj04", "obj06", "obj10", "loc01", "prom04", "time04", "time06"])


# ---------------------------------------------------------------- 2. 옛 원장 형식


def test_ledger_reads_rows_written_with_snake_case_cost(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        json.dumps({"stage": "S3-smoke", "call_site": "chat_stat_judgment", "cost_usd": 0.133, "cumulative_usd": 0.133})
        + "\n",
        encoding="utf-8",
    )
    book = Ledger(path, cap_usd=30.0)
    assert book.total_usd() == pytest.approx(0.133)
    book.check_headroom(29.867)
    with pytest.raises(BudgetExceededError):
        book.check_headroom(29.9)
    row = book.append(
        stage="s4", call_site="x", model="claude-haiku-5-5", input_tokens=1000, cached_tokens=0,
        cache_write_tokens=0, output_tokens=0, thoughts_tokens=0,
    )  # fmt: skip
    assert row["cumulativeUsd"] == pytest.approx(0.133 + 0.0001)


# ---------------------------------------------------------------- 3. 판정자 상한 예외·대조군 불능


def test_judge_retry_does_not_swallow_the_budget_stop() -> None:
    import asyncio

    from memory_eval.judge import judged_or_none

    class Broke:
        async def verdict(self, prompt: str) -> Any:
            raise BudgetExceededError("상한")

    with pytest.raises(BudgetExceededError):
        asyncio.run(judged_or_none(Broke(), "abstain", "p"))  # type: ignore[arg-type]


def test_control_gate_fails_when_any_control_was_not_judged(tmp_path: Path) -> None:
    from memory_eval.judge import controls_pass

    kept = {"kind": "secret", "expected": "kept", "judged": "kept"}
    rows = [kept] * 19 + [{"kind": "secret", "expected": "kept", "judged": None}]
    assert not controls_pass(rows)
    assert controls_pass([kept] * 20)
    assert not controls_pass([{"kind": "secret", "expected": "kept", "judged": "leaked"}] * 3 + [kept] * 17)


# ---------------------------------------------------------------- 4. 숫자 경계(앞뒤 각각)


@pytest.mark.parametrize(
    ("text", "key"),
    [
        pytest.param("12월 13일 1시", "12월13일", id="day-then-hour"),
        pytest.param("1월 15일 3시에", "1월15일", id="day-then-hour-particle"),
        pytest.param("6시 32분 2초", "6시32분", id="minute-then-second"),
    ],
)
def test_digit_boundary_is_checked_only_on_the_digit_ends_of_the_spelling(text: str, key: str) -> None:
    assert answer_matches(text, [[key]])


def test_digit_boundary_still_rejects_a_longer_number_in_front() -> None:
    assert not answer_matches("11월15일", [["1월15일"]])
    assert not answer_matches("16시32분", [["6시32분"]])


# ---------------------------------------------------------------- 5. 재실행 멱등성


def test_probe_resume_skips_finished_items_and_carries_unprobeable_count() -> None:
    from memory_eval.plants import Probe
    from memory_eval.probe import pending_probes

    probes = [
        Probe(item_id=i, checkpoint=cp, turns=["q"], kind="plant", split="dev")
        for i, cp in [("a", 50), ("b", 50), ("a", 300)]
    ]
    done = [
        {"item": "a", "checkpoint": 50, "status": "accept"},
        {"item": "b", "checkpoint": 50, "status": "unprobeable"},
    ]
    todo, unprobeable = pending_probes(probes, done)
    assert [(p.item_id, p.checkpoint) for p in todo] == [("a", 300)]
    assert unprobeable == 1


def test_score_refuses_duplicate_probe_rows() -> None:
    from memory_eval.judge import ensure_unique_probe_rows

    row = {"stage": "s4", "arm": "baseline", "checkpoint": 50, "item": "obj01"}
    ensure_unique_probe_rows([row, {**row, "checkpoint": 100}])
    with pytest.raises(SystemExit):
        ensure_unique_probe_rows([row, dict(row)])


# ---------------------------------------------------------------- 6. 서버 로그 원가


_LOG = (
    "anthropic_usage call_site=chat_generate model=claude-opus-5-5 prompt_tokens=6350 cached_content_tokens=0 "
    "cache_write_tokens=5203 candidates_tokens=576 thoughts_tokens=90 total_tokens=6926 user_id=u room_id=r\n"
    "INFO 그 밖의 줄\n"
    "anthropic_usage call_site=chat_memory_summary model=claude-haiku-5-5 prompt_tokens=None cached_content_tokens=None "
    "cache_write_tokens=None candidates_tokens=None thoughts_tokens=None total_tokens=None user_id=u room_id=r usage=missing\n"
    "gemini_usage call_site=chat_stat_judgment model=gemini-3.5-flash-lite prompt_tokens=10\n"
)


def test_usage_is_read_from_server_log_lines_including_missing_and_other_providers() -> None:
    from memory_eval.probe import parse_usage_log

    calls = parse_usage_log(_LOG)
    assert [c["callSite"] for c in calls] == ["chat_generate", "chat_memory_summary", "chat_stat_judgment"]
    assert calls[0] == {
        "provider": "anthropic", "callSite": "chat_generate", "model": "claude-opus-5-5", "promptTokens": 6350,
        "cachedTokens": 0, "cacheWriteTokens": 5203, "outputTokens": 576, "thoughtsTokens": 90, "missing": False,
    }  # fmt: skip
    assert calls[1]["missing"] is True
    assert calls[2]["provider"] == "gemini"


# ---------------------------------------------------------------- 7. 같은 Redis·DB 를 쓰는 다른 서버


def test_other_servers_on_the_shared_trees_are_conflicts() -> None:
    from memory_eval.server import conflicting_servers

    trees = ["/w/long-memory-prep", "/w/long-memory-eval"]
    procs = [(1, "/w/long-memory-prep/apps/api"), (2, "/w/main/apps/api"), (3, "/w/long-memory-eval/apps/api")]
    assert conflicting_servers(procs, trees, own_pids={3}) == [(1, "/w/long-memory-prep/apps/api")]


# ---------------------------------------------------------------- 8. 추출 연속 실패·빈 에피소드


def test_extraction_streak_stops_at_the_limit_and_resets_on_progress() -> None:
    from memory_eval.insert import ExtractionStreak

    streak = ExtractionStreak(limit=3)
    assert not streak.observe(pending_before=1, done_before=0, done_after=0)
    assert not streak.observe(pending_before=1, done_before=0, done_after=0)
    assert not streak.observe(pending_before=1, done_before=0, done_after=1)  # 진행 → 초기화
    assert not streak.observe(pending_before=0, done_before=1, done_after=1)  # 할 일 없음은 실패가 아니다
    for _ in range(2):
        assert not streak.observe(pending_before=1, done_before=1, done_after=1)
    assert streak.observe(pending_before=1, done_before=1, done_after=1)


def test_freezing_with_extraction_requires_episodes() -> None:
    from memory_eval.checkpoint import require_episodes

    require_episodes({"episodeCount": 0}, required=False)
    require_episodes({"episodeCount": 4}, required=True)
    for bad in ({"episodeCount": 0}, {"episodeCount": None}):
        with pytest.raises(SystemExit):
            require_episodes(bad, required=True)


# ---------------------------------------------------------------- 9. 최종 짝 비교 집계


def _score(item: str, arm: str, hit: bool, *, cp: int = 300, status: str = "accept") -> dict[str, Any]:
    return {
        "stage": "s8",
        "arm": arm,
        "checkpoint": cp,
        "item": item,
        "split": "test",
        "status": status,
        "scored": status != "unprobeable",
        "hit": hit,
    }


def test_s8_pairs_use_the_last_checkpoint_and_drop_items_unprobeable_in_either_arm() -> None:
    from memory_eval.verdict import s8_verdict

    items = [f"p{i}" for i in range(8)]
    plants = _set([_entry(id=i) for i in items])
    rows = []
    for i in items[:5]:  # B 만 맞힘 5쌍
        rows += [
            _score(i, "A", False),
            _score(i, "B", True),
            _score(i, "A", True, cp=100),
            _score(i, "B", True, cp=100),
        ]
    rows += [_score("p5", "A", True), _score("p5", "B", True)]  # 둘 다 맞음
    rows += [_score("p6", "A", False), _score("p6", "B", False, status="unprobeable")]  # 한 갈래 불능 → 빠짐
    rows += [_score("p7", "A", True), _score("p7", "B", False, status="count_wrong")]  # 회상 오류 = B 오답
    result = s8_verdict(plants, _both_halves(rows), judge_rows=[], offline_rows=[])
    first = result["1"]
    assert (first["n"], first["bOnly"], first["aOnly"]) == (7, 5, 1)
    assert first["excludedUnprobeable"] == ["p6"]
    assert first["p"] == pytest.approx(7 / 64)
    assert first["pass"] is False  # p ≥ 0.05


def test_s8_rewind_leak_and_abstain_rules() -> None:
    from memory_eval.verdict import s8_verdict

    plants = _set(
        [_entry(id="rew01", category="되감기", metrics={}, answerKeys=[["스쿠버"]])],
        [
            {
                "id": f"abs0{i}",
                "category": "기권",
                "split": "dev",
                "question": "q",
                "probeCheckpoints": {"opus": [300], "offline": []},
            }
            for i in (1, 2)
        ],
    )
    rows = [_score("rew01", "A", True), _score("rew01", "B", True)]
    rows[0]["split"] = rows[1]["split"] = "dev"
    judge_rows = [
        {"item": "rew01", "arm": "B", "checkpoint": 300, "judged": "guess"},
        {"item": "rew01", "arm": "A", "checkpoint": 300, "judged": "asserted"},
        {"item": "abs01", "arm": "B", "checkpoint": 300, "judged": "fabricated"},
        {"item": "abs02", "arm": "B", "checkpoint": 300, "judged": "fabricated"},
        {"item": "abs01", "arm": "A", "checkpoint": 300, "judged": "declined"},
        {"item": "abs02", "arm": "A", "checkpoint": 300, "judged": "declined"},
    ]
    result = s8_verdict(plants, _both_halves(rows), judge_rows=judge_rows, offline_rows=[])
    assert result["5"]["leaksB"] == 0 and result["5"]["hitsA"] == 1 and result["5"]["pass"] is True
    assert result["4"]["fabricatedB"] - result["4"]["fabricatedA"] == 2 and result["4"]["pass"] is False


# ---------------------------------------------------------------- 사소


class _WithRecall(NamedTuple):
    prompt: str
    memory_recall: tuple[Any, ...]


class _WithoutRecall(NamedTuple):
    prompt: str


def test_recall_field_is_required_on_the_recall_arm_and_empty_differs_from_missing() -> None:
    from memory_eval.trajectory import recall_result

    assert recall_result(_WithRecall("p", ()), field="memory_recall", arm="B") == []
    assert recall_result(_WithoutRecall("p"), field="memory_recall", arm="A") is None
    with pytest.raises(SystemExit):
        recall_result(_WithoutRecall("p"), field="memory_recall", arm="B")


def test_injected_recall_without_its_header_is_refused() -> None:
    from memory_eval.trajectory import check_recall_section

    check_recall_section([], section="")
    check_recall_section([{"episodeId": "e"}], section="[머리글]\n- 줄")
    with pytest.raises(SystemExit):
        check_recall_section([{"episodeId": "e"}], section="")


def test_template_and_dump_names_carry_the_stage_label() -> None:
    from memory_eval.checkpoint import dump_path, fingerprint_path, template_db_name

    assert template_db_name(50, "s4") == "lm_eval_s4_cp50_frozen"
    assert template_db_name(50, "s8") != template_db_name(50, "s4")
    assert fingerprint_path(Path("d"), 50, "s8") == Path("d/s8-cp50.fingerprint.json")
    assert dump_path(Path("d"), 300, "s4") == Path("d/s4-cp300.dump")


def test_recall_stack_is_judged_per_traceback_block() -> None:
    from memory_eval.probe import recall_stack_in

    unrelated = (
        'Traceback (most recent call last):\n  File "api/chat/router.py", line 1, in send\nValueError: x\n'
        "WARNING 회상 memory_recall 비어 있음\n"
    )
    assert not recall_stack_in(unrelated)
    inside = 'Traceback (most recent call last):\n  File "api/chat/memory_recall.py", line 9, in score\nKeyError: y\n'
    assert recall_stack_in(unrelated + inside)


# ---------------------------------------------------------------- 재리뷰: 칸 4·5 입력 누락


def _rewind_set() -> PlantSet:
    rewinds = [
        _entry(id=i, category="되감기", split=s, metrics={}, answerKeys=[["스쿠버"]])
        for i, s in (("rew01", "dev"), ("rew02", "test"))
    ]
    abstains = [
        {
            "id": f"abs0{i}",
            "category": "기권",
            "split": "dev" if i <= 3 else "test",
            "question": "q",
            "probeCheckpoints": {"opus": [300], "offline": []},
        }
        for i in range(1, 7)
    ]
    return _set(rewinds, abstains)


def _both_halves(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """칸 4·5 는 전체 기준이라 집계 입력에 두 절반이 다 있어야 한다 — 다른 절반의 짝 대상 없는 줄을 하나 더한다."""
    present = {r["split"] for r in rows}
    filler = {
        "stage": "s8",
        "arm": "A",
        "checkpoint": 50,
        "item": "filler",
        "status": "accept",
        "scored": True,
        "hit": False,
    }
    return rows + [{**filler, "split": s, "item": f"filler-{s}"} for s in ("dev", "test") if s not in present]


def test_s8_rewind_with_a_missing_item_halts_instead_of_passing() -> None:
    from memory_eval.verdict import s8_verdict

    rows = [{**_score("rew02", arm, False), "split": "test"} for arm in ("A", "B")]
    result = s8_verdict(_rewind_set(), _both_halves(rows), judge_rows=[], offline_rows=[])
    assert result["5"]["status"] == "halt"
    assert result["5"]["missingB"] == ["rew01"]
    assert result["5"]["pass"] is False
    assert result["status"] == "halt"


def test_s8_rewind_hit_without_a_score_value_halts() -> None:
    from memory_eval.verdict import s8_verdict

    rows = [
        {**_score(i, "B", False), "split": s, "status": "unprobeable", "scored": False}
        for i, s in (("rew01", "dev"), ("rew02", "test"))
    ]
    result = s8_verdict(_rewind_set(), _both_halves(rows), judge_rows=[], offline_rows=[])
    # 불능 항목은 빼고 계속하지만(고친 규칙), 둘 다 빠지면 분모가 0 이라 멈춘다.
    assert result["5"]["status"] == "halt"
    assert result["5"]["excluded"] == ["rew01", "rew02"]
    assert result["5"]["n"] == 0


def test_s8_abstain_without_all_six_judgments_halts_and_names_the_missing() -> None:
    from memory_eval.verdict import s8_verdict

    result = s8_verdict(_rewind_set(), _both_halves([]), judge_rows=[], offline_rows=[])
    assert result["4"]["status"] == "halt"
    assert result["4"]["pass"] is False
    assert result["4"]["missing"] == [f"abs0{i}" for i in range(1, 7)]


def test_s8_refuses_input_that_lacks_one_half() -> None:
    from memory_eval.verdict import s8_verdict

    only_test = [{**_score("rew02", "B", False), "split": "test"}]
    with pytest.raises(SystemExit, match="--splits dev,test"):
        s8_verdict(_rewind_set(), only_test, judge_rows=[], offline_rows=[])


def test_unreadable_working_directory_counts_as_a_conflict() -> None:
    from memory_eval.server import conflicting_servers

    assert conflicting_servers([(9, "")], ["/w/long-memory-eval"], own_pids=set()) == [(9, "")]
