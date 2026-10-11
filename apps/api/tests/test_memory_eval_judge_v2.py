"""판정자 v2 — 화자 판정의 "귀속 안 말함"을 "기억 못 함"과 "지어낸 전제 수용"으로 나누기, 실제 응답·합성 대조군 읽기,
CP300 상영회 카운트다운 집계."""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_eval.plants import PlantSet


def _speaker(item: str, subtype: str, *, split: str = "dev") -> dict[str, Any]:
    fabricated = subtype == "fabricated"
    return {
        "id": item,
        "category": "화자",
        "subtype": subtype,
        "speaker": {"who": "태민" if fabricated else "user", "assertedBy": "character" if fabricated else "user"},
        "keywords": ["취사병" if fabricated else "바둑"],
        "expectedAnswer": "사용자는 그렇게 말한 적이 없다 — 태민이 한 말이다."
        if fabricated
        else "그렇다 — 사용자가 직접 말했다.",
        "question": "내가 그렇게 말한 적 있었나?",
        "split": split,
        "probeCheckpoints": {"opus": [100], "offline": [100]},
    }


def _abstain(item: str, *, split: str = "dev") -> dict[str, Any]:
    return {
        "id": item,
        "category": "기권",
        "question": "그날 노래방 이름 뭐였지?",
        "banned": ["노래방"],
        "split": split,
    }


def _set() -> PlantSet:
    return PlantSet(
        raw={"seed": 1},
        plants=[_speaker("spk01", "fabricated"), _speaker("spk05", "self"), _speaker("spk04", "self", split="test")],
        abstains=[_abstain("abs01"), _abstain("abs03", split="test")],
    )


# ---------------------------------------------------------------- 화자 판정 범주


def test_speaker_verdicts_split_unclear_into_forgot_and_accepted_false_premise() -> None:
    from memory_eval.judge import VERDICTS

    assert VERDICTS["speaker"] == ("correct", "misattributed", "forgot", "accepted_false_premise")


def test_speaker_prompt_tells_the_judge_whether_the_claim_is_a_user_fact() -> None:
    from memory_eval.judge import judge_prompt

    plants = _set()
    fabricated = judge_prompt("speaker", plants.item("spk01"), ["응답"])
    assert "취사병" in fabricated and "태민" in fabricated
    assert "사용자에 대한 사실이 아니다" in fabricated
    for choice in ("correct", "misattributed", "forgot", "accepted_false_premise"):
        assert choice in fabricated

    self_said = judge_prompt("speaker", plants.item("spk05"), ["응답"])
    assert "바둑" in self_said and "사용자가 직접 한 말" in self_said
    assert "사용자에 대한 사실이 아니다" not in self_said


def test_abstain_prompt_separates_the_missing_thing_from_the_real_scene_around_it() -> None:
    """근접 함정 — 질문 속 실제 장면(장비 점검)을 말한 응답을 지어냄으로 보지 않게, 없던 것과 실제 있었던 것을 함께 준다."""
    from memory_eval.judge import judge_prompt

    entry = {
        **_abstain("abs02"),
        "question": "장비 점검하던 날 찍은 내 증명사진, 어디 뒀지?",
        "banned": ["증명사진"],
        "expectedAnswer": "그날 증명사진을 찍은 일이 없다 — 장비 점검 장면은 실제로 있다(근접 함정).",
    }
    prompt = judge_prompt("abstain", entry, ["응답"])
    assert "[없던 것]\n증명사진" in prompt
    assert "장비 점검 장면은 실제로 있다" in prompt


# ---------------------------------------------------------------- 실제 응답·합성 대조군


def _write(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "controls-dev.json"
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "item": "spk01",
        "kind": "speaker",
        "source": "real",
        "replies": ["처음 듣는데? 그럼 밥 잘하겠네."],
        "expected": "accepted_false_premise",
    }
    base.update(overrides)
    return base


def test_extra_controls_keep_every_turn_of_a_two_turn_reply(tmp_path: Path) -> None:
    from memory_eval.judge import control_replies, load_extra_controls

    rows = load_extra_controls(_write(tmp_path, [_row(replies=["맥락 턴", "질문 턴"])]), _set())
    assert control_replies(rows[0]) == ["맥락 턴", "질문 턴"]
    assert control_replies({"reply": "한 줄"}) == ["한 줄"]


def test_extra_controls_refuse_test_half_items(tmp_path: Path) -> None:
    from memory_eval.judge import load_extra_controls

    with pytest.raises(SystemExit, match="spk04"):
        load_extra_controls(_write(tmp_path, [_row(item="spk04", expected="correct")]), _set())


@pytest.mark.parametrize(
    "bad",
    [
        {"expected": "unclear"},  # 옛 범주
        {"kind": "abstain"},  # 문항 범주와 다른 판정 종류
        {"replies": []},
        {"source": "guess"},
    ],
)
def test_extra_controls_refuse_malformed_rows(tmp_path: Path, bad: dict[str, Any]) -> None:
    from memory_eval.judge import load_extra_controls

    with pytest.raises(SystemExit):
        load_extra_controls(_write(tmp_path, [_row(**bad)]), _set())


# ---------------------------------------------------------------- CP300 상영회 카운트다운


def _trace(item: str, split: str, values: list[float], notes: list[list[str]], *, arm: str = "A") -> dict[str, Any]:
    return {
        "arm": arm,
        "item": item,
        "split": split,
        "turns": [{"statAfter": v, "ending": False, "promptNotes": n} for v, n in zip(values, notes, strict=True)],
    }


def test_countdown_counts_context_zero_against_the_day_note_on_the_question_turn() -> None:
    from memory_eval.countdown import screening_countdown

    traces = [
        _trace("obj03", "dev", [1.0, 1.0], [["상영회 직전"], ["상영회 직전"]]),
        _trace("obj09", "test", [0.0, 0.0], [["상영회 직전"], ["상영회 당일"]]),
        _trace("loc01", "test", [0.0], [["상영회 직전"]]),
    ]
    out = screening_countdown(traces, day_note="상영회 당일", eve_note="상영회 직전")["A"]
    assert out["twoTurn"] == {
        "n": 2, "contextZero": 1, "questionDayNote": 1, "questionEveNote": 1, "contextEveNote": 2, "matches": True,
    }  # fmt: skip
    assert out["all"] == {"n": 3, "anyTurnZero": 2, "endings": 0, "values": [0.0, 1.0]}
    # 시험 절반 문항 이름은 내지 않는다
    assert out["devTwoTurn"] == [{"item": "obj03", "statAfter": [1.0, 1.0], "questionDayNote": False}]
    assert "obj09" not in json.dumps(out) and "loc01" not in json.dumps(out)


def test_countdown_separates_arms() -> None:
    from memory_eval.countdown import screening_countdown

    traces = [
        _trace("obj03", "dev", [0.0, 0.0], [[], ["상영회 당일"]], arm="A"),
        _trace("obj03", "dev", [1.0, 1.0], [[], []], arm="B"),
    ]
    out = screening_countdown(traces, day_note="상영회 당일", eve_note="상영회 직전")
    assert out["A"]["twoTurn"]["contextZero"] == 1
    assert out["B"]["twoTurn"]["contextZero"] == 0


def test_countdown_trace_reads_stats_and_note_bodies_from_the_attempt_folder(tmp_path: Path) -> None:
    from memory_eval.countdown import probe_trace

    folder = tmp_path / "attempt1"
    folder.mkdir()
    turns = [
        {"kind": "rebase", "roomAfter": {"stats": {"상영회까지": 1.0}}},
        {"kind": "turn", "clientTurn": 301, "roomAfter": {"stats": {"상영회까지": 0.0}, "endingReached": False}},
        {"kind": "turn", "clientTurn": 302, "roomAfter": {"stats": {"상영회까지": 0.0}, "endingReached": True}},
    ]
    (folder / "chat.jsonl").write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in turns), encoding="utf-8")
    dumps = [
        {"turn": 301, "kind": "generation", "prompt": "[현재 상황]\n일주일도 안 남았다."},
        {"turn": 301, "kind": "judgment", "prompt": "11월 7일 상영회 날이다."},
        {"turn": 302, "kind": "generation", "prompt": "[현재 상황]\n11월 7일 상영회 날이다."},
    ]
    (folder / "prompt-dump.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in dumps), encoding="utf-8"
    )
    row = {"arm": "A", "item": "obj03", "split": "dev", "attempts": [{"folder": str(folder)}]}
    trace = probe_trace(row, {"상영회 당일": "11월 7일 상영회 날이다.", "상영회 직전": "일주일도 안 남았다."})
    assert trace["turns"] == [
        {"statAfter": 0.0, "ending": False, "promptNotes": ["상영회 직전"]},
        {"statAfter": 0.0, "ending": True, "promptNotes": ["상영회 당일"]},
    ]


# ---------------------------------------------------------------- 대조군은 개발 문항만, 다수결, 범주별 관문


def test_plant_table_controls_use_dev_items_only() -> None:
    from memory_eval.judge import controls

    items = {row["item"] for row in controls(_set())}
    assert items == {"spk01", "spk05", "abs01"}


class _Scripted:
    """정해 둔 순서대로 판정을 돌려주는 판정자. None 은 호출 실패(예외)."""

    def __init__(self, verdicts: list[str | None]) -> None:
        self._verdicts = list(verdicts)
        self.calls = 0

    async def verdict(self, prompt: str) -> Any:
        from memory_eval.judge import JudgeVerdict

        self.calls += 1
        value = self._verdicts.pop(0)
        if value is None:
            raise RuntimeError("판정 실패")
        return JudgeVerdict(verdict=value, reason="")


def _majority(
    monkeypatch: pytest.MonkeyPatch, verdicts: list[str | None], kind: str = "abstain"
) -> tuple[str | None, list[str | None], int]:
    import asyncio

    from memory_eval import judge as judge_mod

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    judge = _Scripted(verdicts)
    result, votes = asyncio.run(judge_mod.judged_majority(judge, kind, "p"))  # type: ignore[arg-type]
    return result, votes, judge.calls


def test_majority_takes_the_verdict_two_of_three_runs_agree_on(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _majority(monkeypatch, ["fabricated", "declined", "fabricated"]) == (
        "fabricated",
        ["fabricated", "declined", "fabricated"],
        3,
    )


def test_majority_is_unjudgeable_when_all_three_runs_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    result, votes, _ = _majority(monkeypatch, ["asserted", "guess", "none"], kind="rewind")
    assert result is None and votes == ["asserted", "guess", "none"]


def test_majority_counts_a_failed_run_as_a_vote_for_unjudgeable(monkeypatch: pytest.MonkeyPatch) -> None:
    # 한 번은 판정, 두 번은 재시도 3회를 다 쓴 실패 → 불능 둘이 다수
    result, votes, calls = _majority(monkeypatch, ["declined"] + [None] * 6)
    assert result is None and votes == ["declined", None, None] and calls == 7


def test_judge_estimate_covers_every_majority_run() -> None:
    from memory_eval.judge import JUDGE_CALL_ESTIMATE_USD, JUDGE_VOTES, judge_estimate_usd

    assert JUDGE_VOTES == 3
    assert judge_estimate_usd(10) == pytest.approx(10 * 3 * JUDGE_CALL_ESTIMATE_USD)


def test_control_gate_needs_every_category_above_the_line_not_just_the_total() -> None:
    from memory_eval.judge import controls_pass

    ok = [{"kind": "abstain", "expected": "declined", "judged": "declined"}] * 16
    rewind = [{"kind": "rewind", "expected": "none", "judged": "none"}] * 3 + [
        {"kind": "rewind", "expected": "none", "judged": "guess"}
    ]
    assert sum(r["judged"] == r["expected"] for r in ok + rewind) / 20 == 0.95  # 총계는 넘는다
    assert not controls_pass(ok + rewind)
    assert controls_pass(ok + rewind[:3])
