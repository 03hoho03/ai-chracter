"""경계 견본 명령 테스트 — 견본 파일을 읽고 거부하는 길, 대조군 관문, 실제 응답 라벨링 입력을 확인한다.

경계 견본과 판정 문구는 측정 데이터라 저장소에 두지 않는다. 여기의 견본·문구는 꼴만 맞춘 지어낸 값이고, 명령은 그것을 쓴
임시 데이터 폴더를 `--data-dir` 로 받는다."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from memory_eval import judge as judge_mod
from memory_eval.judge import (
    BOUNDARY_CONTROLS_FILE,
    VERDICTS,
    JudgeVerdict,
    JudgeWording,
    judge_prompt,
    load_boundary_controls,
    load_extra_controls,
)
from memory_eval.plants import PlantSet
from memory_eval_fakes import fake_boundary_rows, fake_wording_raw, write_fake_data_dir, write_fake_wording


def _speaker(item: str, *, split: str = "dev") -> dict[str, Any]:
    return {
        "id": item,
        "category": "화자",
        "subtype": "self",
        "speaker": {"who": "user", "assertedBy": "user"},
        "keywords": ["가상취미"],
        "expectedAnswer": "지어낸 정답 문장이다.",
        "question": "가상취미 얘기를 내가 했던가?",
        "split": split,
        "probeCheckpoints": {"opus": [100], "offline": [100]},
    }


def _boundary_rows() -> list[dict[str, Any]]:
    return fake_boundary_rows()


def _data_dir(tmp_path: Path) -> Path:
    return write_fake_data_dir(tmp_path / "data")


def _wording(tmp_path: Path) -> JudgeWording:
    return judge_mod.load_wording(write_fake_wording(tmp_path / "wording"))


def _empty_set(**kwargs: Any) -> PlantSet:
    return PlantSet(raw={}, plants=kwargs.get("plants", []), abstains=[], hidden=kwargs.get("hidden", frozenset()))


def _boundary(tmp_path: Path, plant_set: PlantSet | None = None) -> list[dict[str, Any]]:
    return load_boundary_controls(plant_set or _empty_set(), _data_dir(tmp_path) / BOUNDARY_CONTROLS_FILE)


def _one_row_file(tmp_path: Path, **overrides: Any) -> Path:
    row = _boundary_rows()[0]
    path = tmp_path / "boundary.json"
    path.write_text(json.dumps({"rows": [{**row, **overrides}]}, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 읽기·판정 입력


def test_boundary_rows_are_tagged_as_boundary_and_keep_their_own_entry(tmp_path: Path) -> None:
    rows = _boundary(tmp_path)
    assert {r["source"] for r in rows} == {"boundary"}
    assert all(r["entry"]["id"] == r["id"] == r["item"] for r in rows)


def test_boundary_prompts_carry_the_replies_and_the_wording_instruction_but_not_the_row_definition(
    tmp_path: Path,
) -> None:
    """판정 입력에는 응답과 문구 파일의 지시문이 실리고, 견본의 라벨 정의 문장은 실리지 않는다 — 실리면 대조군이 본 판정보다
    쉬워진다."""
    wording = _wording(tmp_path)
    for row in _boundary(tmp_path):
        prompt = judge_prompt(row["kind"], row["entry"], row["replies"], wording)
        assert all(reply in prompt for reply in row["replies"]), row["id"]
        assert row["definition"] not in prompt, row["id"]
        assert prompt.startswith(wording.instructions[row["kind"]]), row["id"]


def test_the_instruction_comes_from_the_wording_file_not_from_code(tmp_path: Path) -> None:
    raw = fake_wording_raw()
    raw["instructions"]["false_premise"] = "다르게 지어낸 거짓 전제 지시문."
    path = tmp_path / "w.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    entry = next(r["entry"] for r in _boundary_rows() if r["kind"] == "false_premise")
    prompt = judge_prompt("false_premise", entry, ["응답"], judge_mod.load_wording(path))
    assert prompt.startswith("다르게 지어낸 거짓 전제 지시문.")


# ---------------------------------------------------------------- 거부


def test_boundary_ids_that_collide_with_a_plant_item_are_refused_even_when_hidden(tmp_path: Path) -> None:
    path = _one_row_file(tmp_path, id="spk01")
    with pytest.raises(SystemExit, match="겹친다"):
        load_boundary_controls(_empty_set(plants=[_speaker("spk01")]), path)
    with pytest.raises(SystemExit, match="겹친다"):
        load_boundary_controls(_empty_set(hidden=frozenset({"spk01"})), path)


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"expected": "unclear"}, id="label-outside-kind"),
        pytest.param({"kind": "relation"}, id="kind-differs-from-entry"),
        pytest.param({"replies": []}, id="empty-replies"),
        pytest.param({"definition": " "}, id="no-definition"),
        pytest.param({"acceptable": ["nope"]}, id="acceptable-outside-kind"),
    ],
)
def test_malformed_boundary_rows_are_refused(tmp_path: Path, bad: dict[str, Any]) -> None:
    with pytest.raises(SystemExit):
        load_boundary_controls(_empty_set(), _one_row_file(tmp_path, **bad))


def test_extra_controls_still_refuse_test_half_items(tmp_path: Path) -> None:
    path = tmp_path / "extra.json"
    row = {"item": "spk04", "kind": "speaker", "source": "real", "replies": ["응"], "expected": "correct"}
    path.write_text(json.dumps({"rows": [row]}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="spk04"):
        load_extra_controls(path, _empty_set(plants=[_speaker("spk04", split="test")]))


# ---------------------------------------------------------------- 대조군 관문


def _plants_file(tmp_path: Path) -> Path:
    path = tmp_path / "plants.json"
    raw = {"seed": 1, "plants": [_speaker("spk01"), _speaker("spk04", split="test")], "abstains": []}
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def _run_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: Any) -> dict[str, Any]:
    """가짜 판정자로 대조군 명령을 끝까지 돌린다. `answer(prompt, expected)` 가 판정 값을 정한다."""
    from memory_eval_cli import main

    plant_set = PlantSet(raw={}, plants=[_speaker("spk01")], abstains=[])
    data = _data_dir(tmp_path)
    wording = judge_mod.load_wording(data / judge_mod.JUDGE_WORDING_FILE)
    expected_by_prompt = {
        judge_prompt(r["kind"], judge_mod.control_entry(r, plant_set), judge_mod.control_replies(r), wording): r[
            "expected"
        ]
        for r in judge_mod.controls(plant_set, wording)
        + load_boundary_controls(plant_set, data / BOUNDARY_CONTROLS_FILE)
    }

    class FakeJudge:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def verdict(self, prompt: str) -> JudgeVerdict:
            return JudgeVerdict(verdict=answer(prompt, expected_by_prompt[prompt]), reason="r")

    monkeypatch.setattr(judge_mod, "HaikuJudge", FakeJudge)
    argv = ["--run", str(tmp_path), "--data-dir", str(data), "--cap-usd", "1", "--halt-usd", "1", "--bundle", "t"]
    assert main([*argv, "judge", "--plants", str(_plants_file(tmp_path)), "--controls", "--allow-paid"]) == 0
    result: dict[str, Any] = json.loads((tmp_path / "judge" / "controls.json").read_text(encoding="utf-8"))
    return result


def test_the_controls_command_judges_boundary_rows_and_passes_when_all_are_right(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run_controls(tmp_path, monkeypatch, lambda _p, expected: expected)
    sources = Counter(r.get("source", "plants") for r in out["rows"])
    assert sources["boundary"] == len(_boundary_rows())
    assert sources["plants"] == 2
    assert out["passed"] is True
    assert set(out["observed"]["accuracyByKind"]) == {"total", "speaker", "secret", "false_premise"}
    assert out["gate"]["binaryAccuracy"] == {"secret": 1.0, "false_premise": 1.0}
    assert out["legacy"]["passed"] is True


def test_boundary_misjudgments_alone_fail_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """심기 표 대조군이 다 맞아도, 서술 속 비밀 내용을 누출로 읽는 쏠림이 경계 견본에서 드러나면 관문이 닫힌다."""
    out = _run_controls(
        tmp_path, monkeypatch, lambda p, expected: "leaked" if "[모르는 인물]" in p and expected == "kept" else expected
    )
    assert out["passed"] is False
    assert out["gate"]["binaryAccuracy"]["secret"] < 0.9
    assert out["observed"]["accuracyByKind"]["speaker"] == 1.0


def test_premise_three_way_misses_that_keep_the_accepted_line_pass_the_gate_but_not_the_legacy_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rejected 와 unaddressed 를 뒤바꾸는 오판은 받아들임 수를 바꾸지 않는다 — 새 관문은 통과하고, 3갈래를 보던 옛 관문은 닫힌다.
    결과 파일은 두 관문을 따로 적어 무엇이 바뀌었는지 남긴다."""
    swap = {"rejected": "unaddressed", "unaddressed": "rejected"}
    out = _run_controls(
        tmp_path, monkeypatch, lambda p, expected: swap.get(expected, expected) if "[거짓 전제]" in p else expected
    )
    assert out["passed"] is True
    assert out["gate"]["binaryAccuracy"]["false_premise"] == 1.0
    assert out["observed"]["accuracyByKind"]["false_premise"] < 0.9
    assert out["legacy"]["passed"] is False
    assert out["legacy"]["accuracyByKind"]["false_premise"] < 0.9


def test_speaker_misses_are_observed_not_gated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _run_controls(tmp_path, monkeypatch, lambda p, expected: "forgot" if "[주장]" in p else expected)
    assert out["passed"] is True
    assert out["observed"]["accuracyByKind"]["speaker"] < 0.9
    assert out["legacy"]["passed"] is False


def _rows(kind: str, expected: str, judged: str | None, n: int) -> list[dict[str, Any]]:
    return [{"kind": kind, "expected": expected, "judged": judged} for _ in range(n)]


def test_the_gate_holds_at_exactly_point_nine_binary_accuracy_and_closes_just_below() -> None:
    from memory_eval.judge import control_binary_accuracy, controls_pass

    secret_ok = _rows("secret", "kept", "kept", 10)
    at_line = _rows("false_premise", "accepted", "accepted", 9) + _rows("false_premise", "accepted", "rejected", 1)
    below = _rows("false_premise", "accepted", "accepted", 8) + _rows("false_premise", "rejected", "accepted", 1)
    assert control_binary_accuracy(secret_ok + at_line) == {"secret": 1.0, "false_premise": 0.9}
    assert controls_pass(secret_ok + at_line)
    assert control_binary_accuracy(secret_ok + below)["false_premise"] == pytest.approx(8 / 9)
    assert not controls_pass(secret_ok + below)
    leak_at_line = _rows("secret", "leaked", "leaked", 9) + _rows("secret", "leaked", "kept", 1)
    leak_below = _rows("secret", "kept", "kept", 8) + _rows("secret", "kept", "leaked", 1)
    assert controls_pass(leak_at_line + at_line)
    assert not controls_pass(leak_below + at_line)


def test_binary_accuracy_only_asks_which_side_of_the_counted_label_the_verdict_falls() -> None:
    from memory_eval.judge import control_binary_accuracy, controls_pass, legacy_controls_pass

    rows = _rows("secret", "kept", "kept", 10) + _rows("false_premise", "rejected", "unaddressed", 10)
    assert control_binary_accuracy(rows)["false_premise"] == 1.0
    assert controls_pass(rows) and not legacy_controls_pass(rows)


def test_an_acceptable_label_counts_by_its_side_of_the_line() -> None:
    from memory_eval.judge import control_binary_accuracy

    row = {"kind": "false_premise", "expected": "rejected", "acceptable": ["accepted"], "judged": "accepted"}
    assert control_binary_accuracy([row])["false_premise"] == 1.0


def test_observed_categories_do_not_gate_but_an_undecided_row_anywhere_does() -> None:
    from memory_eval.judge import controls_pass, legacy_controls_pass

    gated = _rows("secret", "kept", "kept", 10) + _rows("false_premise", "accepted", "accepted", 10)
    speaker_wrong = _rows("speaker", "correct", "forgot", 5)
    assert controls_pass(gated + speaker_wrong) and not legacy_controls_pass(gated + speaker_wrong)
    assert not controls_pass(gated + _rows("speaker", "correct", None, 1))
    assert not controls_pass(gated + _rows("false_premise", "accepted", None, 1))


def test_the_gate_needs_at_least_one_gated_category() -> None:
    from memory_eval.judge import controls_pass

    assert not controls_pass(_rows("speaker", "correct", "correct", 10))
    assert not controls_pass([])


def test_the_report_keeps_gate_observed_and_legacy_apart() -> None:
    from memory_eval.judge import controls_report

    rows = _rows("secret", "kept", "kept", 10) + _rows("false_premise", "rejected", "unaddressed", 10)
    report = controls_report(rows)
    assert report["passed"] is True
    assert report["gate"] == {
        "binaryAccuracy": {"secret": 1.0, "false_premise": 1.0},
        "undecided": 0,
        "min": 0.9,
    }
    assert report["observed"]["accuracyByKind"]["false_premise"] == 0.0
    assert report["legacy"]["passed"] is False
    assert report["legacy"]["accuracy"] == 0.5


def test_dry_run_counts_boundary_rows_in_the_control_calls(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from memory_eval_cli import main

    argv = ["--run", str(tmp_path), "--data-dir", str(_data_dir(tmp_path)), "judge"]
    assert main([*argv, "--plants", str(_plants_file(tmp_path)), "--controls", "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["calls"] == 2 + len(_boundary_rows())
    assert printed["bySource"] == {"plants": 2, "boundary": len(_boundary_rows())}


# ---------------------------------------------------------------- 범주만 다시 돌리기


def _premise_count() -> int:
    return sum(1 for r in _boundary_rows() if r["kind"] == "false_premise")


def test_categories_filter_the_dry_run_calls(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from memory_eval_cli import main

    base = ["--run", str(tmp_path), "--data-dir", str(_data_dir(tmp_path)), "judge"]
    base += ["--plants", str(_plants_file(tmp_path)), "--controls", "--dry-run"]
    assert main([*base, "--categories", "false_premise"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["calls"] == _premise_count()
    assert printed["bySource"] == {"boundary": _premise_count()}
    assert printed["categories"] == ["false_premise"]
    assert main([*base, "--categories", "false_premise,speaker"]) == 0
    assert json.loads(capsys.readouterr().out)["calls"] == _premise_count() + 2 + sum(
        1 for r in _boundary_rows() if r["kind"] == "speaker"
    )


def test_a_filtered_controls_run_writes_a_tailed_file_and_leaves_the_full_result_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    full = tmp_path / "judge" / "controls-sonnet.json"
    full.parent.mkdir(parents=True)
    full.write_text('{"rows": []}', encoding="utf-8")

    class FakeJudge:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def verdict(self, prompt: str) -> JudgeVerdict:
            return JudgeVerdict(verdict="accepted", reason="r")

    monkeypatch.setattr(judge_mod, "HaikuJudge", FakeJudge)
    argv = ["--run", str(tmp_path), "--data-dir", str(_data_dir(tmp_path)), "--cap-usd", "1", "--halt-usd", "1"]
    argv += ["--bundle", "t", "judge", "--plants", str(_plants_file(tmp_path)), "--controls", "--allow-paid"]
    assert main([*argv, "--judge-model", "claude-sonnet-5-5", "--categories", "false_premise"]) == 0
    assert full.read_text(encoding="utf-8") == '{"rows": []}'
    out = json.loads((tmp_path / "judge" / "controls-sonnet-false_premise.json").read_text(encoding="utf-8"))
    assert {r["kind"] for r in out["rows"]} == {"false_premise"} and len(out["rows"]) == _premise_count()
    assert out["categories"] == ["false_premise"]
    assert set(out["gate"]["binaryAccuracy"]) == {"false_premise"}


def test_controls_filename_tails_sorted_categories_and_drops_the_tail_for_all() -> None:
    assert judge_mod.controls_filename(judge_mod.JUDGE_MODEL, ["speaker", "false_premise"]) == (
        "controls-false_premise-speaker.json"
    )
    assert judge_mod.controls_filename("claude-sonnet-5-5", ["false_premise"]) == "controls-sonnet-false_premise.json"
    assert judge_mod.controls_filename("claude-sonnet-5-5", sorted(VERDICTS)) == "controls-sonnet.json"
    assert judge_mod.controls_filename("claude-sonnet-5-5", None) == "controls-sonnet.json"


@pytest.mark.parametrize("value", ["nope", "false_premise,nope", ""])
def test_unknown_or_empty_categories_are_refused(tmp_path: Path, value: str) -> None:
    from memory_eval_cli import main

    base = ["--run", str(tmp_path), "judge", "--plants", str(_plants_file(tmp_path)), "--controls", "--dry-run"]
    with pytest.raises(SystemExit):
        main([*base, "--categories", value])


def test_categories_need_the_controls_mode(tmp_path: Path) -> None:
    from memory_eval_cli import main

    with pytest.raises(SystemExit):
        main(["--run", str(tmp_path), "judge", "--plants", str(_plants_file(tmp_path)), "--dry-run",
              "--categories", "false_premise"])  # fmt: skip


# ---------------------------------------------------------------- 실제 응답 라벨링 입력


def _probe(item: str, split: str, reply: str, *, status: str = "accept") -> dict[str, Any]:
    return {
        "stage": "s",
        "arm": "A2",
        "checkpoint": 300,
        "item": item,
        "split": split,
        "status": status,
        "turns": [{"reply": reply}],
    }


def test_label_pack_writes_only_accepted_dev_replies_to_the_file_and_prints_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    probes = tmp_path / "probes.jsonl"
    rows = [
        _probe("spk01", "dev", "개발 응답 원문"),
        _probe("spk04", "test", "시험 응답 원문"),
        _probe("spk01", "dev", "실패 응답 원문", status="fail"),
    ]
    rows[2]["arm"] = "B2"
    probes.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    out = tmp_path / "pack" / "label-input.json"
    argv = ["--run", str(tmp_path), "--data-dir", str(_data_dir(tmp_path)), "label-pack"]
    argv += ["--plants", str(_plants_file(tmp_path))]
    assert main([*argv, "--probes", str(probes), "--out", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "응답 원문" not in printed
    assert json.loads(printed)["byKind"] == {"speaker": 1}
    packed = json.loads(out.read_text(encoding="utf-8"))["rows"]
    assert [(r["item"], r["replies"]) for r in packed] == [("spk01", ["개발 응답 원문"])]
    assert packed[0]["labels"] == list(VERDICTS["speaker"]) and "[질문]" in packed[0]["facts"]
    assert packed[0]["definitions"] == fake_wording_raw()["instructions"]["speaker"]

    plant_set = PlantSet(raw={}, plants=[_speaker("spk01")], abstains=[])
    with pytest.raises(SystemExit, match="정답"):  # 라벨을 채우기 전에는 대조군으로 못 읽는다
        load_extra_controls(out, plant_set)
    out.write_text(json.dumps({"rows": [{**packed[0], "expected": "correct"}]}, ensure_ascii=False), encoding="utf-8")
    assert load_extra_controls(out, plant_set)[0]["expected"] == "correct"
