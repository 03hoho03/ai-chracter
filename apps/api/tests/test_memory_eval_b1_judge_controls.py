"""묶음 1 판정자 대조군 — 세 작품의 실제 응답을 대조군으로 쓰는 길.

라벨링 입력은 이름 없는 인물 비밀 응답에 층 표시를 달아(관찰 정확도를 따로 보려고), 종류마다 정한 수만큼 층·갈래를 고르게
시드로 뽑는다. 대조군 명령은 작품마다 돌리되 넣을 출처(심기 표 합성·추가 대조군·경계 견본)를 고르고 꼬리 이름으로 따로 쓰며,
합치기 명령이 그 결과들을 한 대조군 기록으로 합쳐 관문을 다시 계산한다(경계 견본이 두 번 들어가면 거부). 본 판정은 대조군이
같은 입력으로 이미 판정한 응답을 다시 부르지 않고 그 판정을 가져다 쓴다 — 입력이 달라졌으면 거부한다."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from memory_eval import judge as judge_mod
from memory_eval.judge import (
    NAMELESS_STRATUM,
    JudgeVerdict,
    labeling_pack,
    load_extra_controls,
    sample_label_pack,
)
from memory_eval.plants import PlantSet
from memory_eval_fakes import fake_boundary_rows, fake_wording_now, write_fake_data_dir

SONNET = "claude-sonnet-5-5"
WORDING = fake_wording_now()


def _data(tmp_path: Path) -> Path:
    return write_fake_data_dir(tmp_path / "data")


def _secret(item: str, *, nameless: bool, split: str = "dev") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": item,
        "category": "secret",
        "split": split,
        "setup_turn_text": "장면 설정",
        "question": "비밀 질문",
        "secretOwner": "가상주인",
        "unawareCharacter": None if nameless else "가상모름이",
        "answer_key": {"mode": "judge", "leak_bundles": [["가상계획"]]},
        "expected_fact": {"attribute": "계획", "value": "가상계획"},
    }
    if nameless:
        entry["unawareRole"] = "처음 보는 가상역할"
    return entry


def _premise(item: str, *, split: str = "dev") -> dict[str, Any]:
    return {
        "id": item,
        "category": "false_premise",
        "subtype": "character_claim",
        "split": split,
        "question": "그때 그 일 기억나?",
        "answer_key": {"mode": "judge", "premise": "없던 일", "truth": "그런 일 없음"},
    }


def _probe(item: str, arm: str, *, checkpoint: int = 300, split: str = "dev") -> dict[str, Any]:
    return {
        "stage": "s",
        "arm": arm,
        "checkpoint": checkpoint,
        "item": item,
        "split": split,
        "status": "accept",
        "turns": [{"reply": f"{item} {arm} 첫 응답"}, {"reply": f"{item} {arm} 둘째 응답"}],
    }


def _set(*entries: dict[str, Any]) -> PlantSet:
    return PlantSet(raw={}, plants=list(entries), abstains=[])


# ---------------------------------------------------------------- 라벨링 입력의 층 표시


def test_label_pack_marks_nameless_secret_replies_with_their_stratum_and_leaves_others_unmarked() -> None:
    plant_set = _set(_secret("s1", nameless=True), _secret("s2", nameless=False), _premise("f1"))
    rows = labeling_pack(plant_set, [_probe("s1", "A0"), _probe("s2", "A0"), _probe("f1", "A0")], WORDING)
    by_item = {r["item"]: r for r in rows}
    assert by_item["s1"]["stratum"] == NAMELESS_STRATUM
    assert "stratum" not in by_item["s2"] and "stratum" not in by_item["f1"]


def test_a_labelled_nameless_row_keeps_its_stratum_through_the_controls_report(tmp_path: Path) -> None:
    plant_set = _set(_secret("s1", nameless=True))
    row = {**labeling_pack(plant_set, [_probe("s1", "A0")], WORDING)[0], "expected": "kept"}
    path = tmp_path / "labelled.json"
    path.write_text(json.dumps({"rows": [row]}, ensure_ascii=False), encoding="utf-8")
    loaded = load_extra_controls(path, plant_set)
    report = judge_mod.controls_report([{**loaded[0], "judged": "leaked"}])
    assert report["observed"]["accuracyByStratum"] == {NAMELESS_STRATUM: 0.0}


# ---------------------------------------------------------------- 층별 시드 표본


def _population() -> tuple[PlantSet, list[dict[str, Any]]]:
    entries = [_secret(f"s{i}", nameless=i < 4) for i in range(12)] + [_premise(f"f{i}") for i in range(5)]
    probes = [_probe(e["id"], arm) for e in entries for arm in ("b1-A0", "b1-A1")]
    return _set(*entries), labeling_pack(_set(*entries), probes, WORDING)


def test_a_kind_without_a_quota_keeps_every_row_and_a_quota_keeps_exactly_that_many() -> None:
    _, rows = _population()
    chosen, meta = sample_label_pack(rows, {"secret": 10}, seed=7)
    kinds = Counter(r["kind"] for r in chosen)
    assert kinds == {"secret": 10, "false_premise": 10}
    assert meta["chosen"] == {"false_premise": 10, "secret": 10}
    assert meta["population"] == {"false_premise": 10, "secret": 24}
    # 10 × 4/24 = 1.67 · 10 × 8/24 = 3.33 → 내림 1·1·3·3, 남은 2 는 나머지가 큰 이름 없는 층 두 칸으로.
    assert meta["byStratum"]["secret"] == {
        f"{NAMELESS_STRATUM}|b1-A0": [2, 4],
        f"{NAMELESS_STRATUM}|b1-A1": [2, 4],
        "|b1-A0": [3, 8],
        "|b1-A1": [3, 8],
    }


def test_the_quota_is_spread_over_strata_and_arms_in_proportion_and_prefers_unseen_items() -> None:
    _, rows = _population()
    chosen, _ = sample_label_pack(rows, {"secret": 12}, seed=7)
    secret = [r for r in chosen if r["kind"] == "secret"]
    strata = Counter((r.get("stratum", ""), r["arm"]) for r in secret)
    # 이름 없는 층 8줄·이름 있는 층 16줄 → 12 중 4·8, 각 층 안에서 갈래 반반.
    assert strata == {
        (NAMELESS_STRATUM, "b1-A0"): 2,
        (NAMELESS_STRATUM, "b1-A1"): 2,
        ("", "b1-A0"): 4,
        ("", "b1-A1"): 4,
    }
    # 문항 12개에서 12줄을 뽑으면 같은 문항이 두 번 들지 않는다.
    assert len({r["item"] for r in secret}) == 12


def test_the_sample_is_fixed_by_the_seed_and_keeps_the_pack_order() -> None:
    _, rows = _population()
    first, _ = sample_label_pack(rows, {"secret": 9}, seed=7)
    again, _ = sample_label_pack(rows, {"secret": 9}, seed=7)
    other, _ = sample_label_pack(rows, {"secret": 9}, seed=8)
    assert [r["key"] for r in first] == [r["key"] for r in again]
    assert [r["key"] for r in first] != [r["key"] for r in other]
    order = [r["key"] for r in rows]
    assert [r["key"] for r in first] == sorted((r["key"] for r in first), key=order.index)


def test_a_quota_larger_than_the_kind_keeps_all_rows_and_an_unknown_kind_is_refused() -> None:
    _, rows = _population()
    chosen, _ = sample_label_pack(rows, {"secret": 999}, seed=1)
    assert len(chosen) == len(rows)
    with pytest.raises(SystemExit, match="relation"):
        sample_label_pack(rows, {"relation": 3}, seed=1)


def _v1_plants(tmp_path: Path, *entries: dict[str, Any]) -> Path:
    path = tmp_path / "plants.json"
    path.write_text(json.dumps({"seed": 1, "plants": list(entries), "abstains": []}, ensure_ascii=False), "utf-8")
    return path


def _probes_file(tmp_path: Path, rows: list[dict[str, Any]], name: str = "probes.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def test_label_pack_command_filters_kinds_samples_with_the_seed_and_prints_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    entries = [_secret(f"s{i}", nameless=i == 0) for i in range(4)] + [_premise("f0")]
    entries.append({"id": "r0", "category": "relation", "split": "dev", "question": "q", "answer_key": {}})
    probes = _probes_file(tmp_path, [_probe(e["id"], arm) for e in entries for arm in ("b1-A0", "b1-A1")])
    out = tmp_path / "pack.json"
    argv = [
        "--run",
        str(tmp_path),
        "--data-dir",
        str(_data(tmp_path)),
        "label-pack",
        "--plants",
        str(_v1_plants(tmp_path, *entries)),
    ]
    argv += ["--probes", str(probes), "--out", str(out), "--kinds", "secret,false_premise"]
    assert main([*argv, "--sample", "secret=4", "--seed", "3"]) == 0
    printed = capsys.readouterr().out
    assert "응답" not in printed
    summary = json.loads(printed)
    assert summary["byKind"] == {"false_premise": 2, "secret": 4}
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["sample"]["seed"] == 3 and written["sample"]["quotas"] == {"secret": 4}
    assert {r["kind"] for r in written["rows"]} == {"secret", "false_premise"}


# ---------------------------------------------------------------- 작품별 대조군과 합치기


def _fake_judge(monkeypatch: pytest.MonkeyPatch, answer: Any, calls: list[str] | None = None) -> None:
    class FakeJudge:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def verdict(self, prompt: str) -> JudgeVerdict:
            if calls is not None:
                calls.append(prompt)
            return JudgeVerdict(verdict=answer(prompt), reason="r")

    monkeypatch.setattr(judge_mod, "HaikuJudge", FakeJudge)


def _labelled(tmp_path: Path, plant_set: PlantSet, probes: list[dict[str, Any]], expected: str, name: str) -> Path:
    rows = [{**r, "expected": expected} for r in labeling_pack(plant_set, probes, WORDING)]
    path = tmp_path / name
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def _paid(tmp_path: Path) -> list[str]:
    return [
        "--run",
        str(tmp_path),
        "--data-dir",
        str(_data(tmp_path)),
        "--cap-usd",
        "1",
        "--halt-usd",
        "1",
        "--bundle",
        "t",
    ]


def test_controls_can_skip_synthetic_rows_and_write_a_tagged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    entries = [_secret("s1", nameless=False)]
    plants = _v1_plants(tmp_path, *entries)
    extra = _labelled(tmp_path, _set(*entries), [_probe("s1", "b1-A0")], "kept", "l.json")
    _fake_judge(monkeypatch, lambda _p: "kept")
    argv = [*_paid(tmp_path), "judge", "--plants", str(plants), "--controls", "--allow-paid", "--judge-model", SONNET]
    argv += ["--extra-controls", str(extra), "--control-sources", "extra", "--controls-tag", "fc"]
    assert main(argv) == 0
    assert sorted(p.name for p in (tmp_path / "judge").iterdir()) == ["controls-sonnet-fc.json"]
    result = json.loads((tmp_path / "judge" / "controls-sonnet-fc.json").read_text(encoding="utf-8"))
    assert [r["source"] for r in result["rows"]] == ["real"]
    assert result["judgeModel"] == SONNET
    assert len(result["rows"][0]["promptSha256"]) == 64


def test_an_unknown_control_source_is_refused(tmp_path: Path) -> None:
    from memory_eval_cli import main

    plants = _v1_plants(tmp_path, _secret("s1", nameless=False))
    with pytest.raises(SystemExit):
        main(["--run", str(tmp_path), "--data-dir", str(_data(tmp_path)), "judge", "--plants", str(plants), "--controls", "--dry-run",
              "--control-sources", "plants,mystery"])  # fmt: skip


def _tagged_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str, item: str, sources: str, answer: Any
) -> Path:
    from memory_eval_cli import main

    entries = [_secret(item, nameless=False)]
    plants = _v1_plants(tmp_path, *entries)
    extra = _labelled(tmp_path, _set(*entries), [_probe(item, "b1-A0")], "kept", f"l-{tag}.json")
    _fake_judge(monkeypatch, answer)
    argv = [*_paid(tmp_path), "judge", "--plants", str(plants), "--controls", "--allow-paid", "--judge-model", SONNET]
    argv += ["--extra-controls", str(extra), "--control-sources", sources, "--controls-tag", tag]
    assert main(argv) == 0
    return tmp_path / "judge" / f"controls-sonnet-{tag}.json"


def _boundary_answer(prompt: str) -> str:
    expected = {
        judge_mod.judge_prompt(r["kind"], r["entry"], r["replies"], WORDING): r["expected"]
        for r in fake_boundary_rows()
    }
    return str(expected.get(prompt, "kept"))


def test_merge_pools_tagged_results_into_the_gate_file_and_recomputes_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    first = _tagged_run(tmp_path, monkeypatch, "fc", "s1", "extra,boundary", _boundary_answer)
    second = _tagged_run(tmp_path, monkeypatch, "gt", "s2", "extra", lambda _p: "leaked")
    argv = [
        "--run",
        str(tmp_path),
        "judge-controls-merge",
        "--judge-model",
        SONNET,
        "--inputs",
        str(first),
        str(second),
    ]
    assert main(argv) == 0
    merged = json.loads((tmp_path / "judge" / "controls-sonnet.json").read_text(encoding="utf-8"))
    assert Counter(r["source"] for r in merged["rows"]) == {"real": 2, "boundary": len(fake_boundary_rows())}
    secret_rows = [r for r in merged["rows"] if r["kind"] == "secret"]
    wrong = sum(1 for r in secret_rows if not judge_mod.control_correct(r))
    assert wrong == 1
    assert merged["gate"]["binaryAccuracy"]["secret"] == pytest.approx(1 - 1 / len(secret_rows))
    assert merged["judgeModel"] == SONNET
    assert [Path(p["path"]).name for p in merged["inputs"]] == [first.name, second.name]


def test_merge_refuses_a_boundary_sample_that_appears_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    first = _tagged_run(tmp_path, monkeypatch, "fc", "s1", "extra,boundary", _boundary_answer)
    second = _tagged_run(tmp_path, monkeypatch, "gt", "s2", "extra,boundary", _boundary_answer)
    argv = [
        "--run",
        str(tmp_path),
        "judge-controls-merge",
        "--judge-model",
        SONNET,
        "--inputs",
        str(first),
        str(second),
    ]
    assert main(argv) == 2
    assert "두 번" in capsys.readouterr().err
    assert not (tmp_path / "judge" / "controls-sonnet.json").exists()


def test_merge_refuses_results_from_another_judge_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    first = _tagged_run(tmp_path, monkeypatch, "fc", "s1", "extra", lambda _p: "kept")
    argv = ["--run", str(tmp_path), "judge-controls-merge", "--judge-model", judge_mod.JUDGE_MODEL]
    assert main([*argv, "--inputs", str(first)]) == 2
    assert "판정자" in capsys.readouterr().err


# ---------------------------------------------------------------- 대조군 판정을 본 판정에 다시 쓰기


def _main_judge_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, list[str]]:
    """대조군(s1 A0 한 줄)을 합쳐 통과 기록을 만들고, 본 판정 입력(s1 A0·A1)을 준비한다."""
    from memory_eval_cli import main

    tagged = _tagged_run(tmp_path, monkeypatch, "fc", "s1", "extra,boundary", _boundary_answer)
    argv = ["--run", str(tmp_path), "judge-controls-merge", "--judge-model", SONNET, "--inputs", str(tagged)]
    assert main(argv) == 0
    probes = _probes_file(tmp_path, [_probe("s1", "b1-A0"), _probe("s1", "b1-A1")], "p3.jsonl")
    calls: list[str] = []
    _fake_judge(monkeypatch, lambda _p: "leaked", calls)
    return tmp_path / "judge" / "controls-sonnet.json", probes, calls


def test_the_main_judge_reuses_control_verdicts_for_the_same_input_and_calls_only_for_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    pooled, probes, calls = _main_judge_setup(tmp_path, monkeypatch)
    out = tmp_path / "judged.json"
    argv = [*_paid(tmp_path), "judge", "--plants", str(tmp_path / "plants.json"), "--allow-paid"]
    argv += ["--judge-model", SONNET, "--probes", str(probes), "--out", str(out), "--reuse-judged", str(pooled)]
    assert main(argv) == 0
    judged = {r["arm"]: r for r in json.loads(out.read_text(encoding="utf-8"))}
    assert judged["b1-A0"]["judged"] == "kept" and judged["b1-A0"]["reused"] is True
    assert judged["b1-A1"]["judged"] == "leaked" and "reused" not in judged["b1-A1"]
    assert len(calls) == 2  # 다시 쓰지 못한 한 줄만 판정 — 같은 답 두 표라 셋째는 부르지 않는다


def test_the_dry_run_counts_only_the_calls_left_after_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    pooled, probes, _ = _main_judge_setup(tmp_path, monkeypatch)
    capsys.readouterr()
    argv = [
        "--run",
        str(tmp_path),
        "--data-dir",
        str(_data(tmp_path)),
        "judge",
        "--plants",
        str(tmp_path / "plants.json"),
        "--dry-run",
    ]
    argv += ["--judge-model", SONNET, "--probes", str(probes), "--reuse-judged", str(pooled)]
    assert main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["calls"] == 1 and printed["reused"] == 1


def test_reuse_is_refused_when_the_judge_input_changed_since_the_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    pooled, probes, _ = _main_judge_setup(tmp_path, monkeypatch)
    data = json.loads(pooled.read_text(encoding="utf-8"))
    for row in data["rows"]:
        if row["source"] == "real":
            row["promptSha256"] = "0" * 64
    pooled.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    argv = [
        "--run",
        str(tmp_path),
        "--data-dir",
        str(_data(tmp_path)),
        "judge",
        "--plants",
        str(tmp_path / "plants.json"),
        "--dry-run",
    ]
    argv += ["--judge-model", SONNET, "--probes", str(probes), "--reuse-judged", str(pooled)]
    capsys.readouterr()
    assert main(argv) == 2
    assert "판정 입력이 대조군 때와 다르다" in capsys.readouterr().err


def test_reuse_is_refused_when_the_controls_record_is_from_another_judge_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    pooled, probes, _ = _main_judge_setup(tmp_path, monkeypatch)
    argv = [
        "--run",
        str(tmp_path),
        "--data-dir",
        str(_data(tmp_path)),
        "judge",
        "--plants",
        str(tmp_path / "plants.json"),
        "--dry-run",
    ]
    argv += ["--judge-model", "claude-opus-5-5", "--probes", str(probes), "--reuse-judged", str(pooled)]
    capsys.readouterr()
    assert main(argv) == 2
    assert "판정자 모델이 다르다" in capsys.readouterr().err


# ---------------------------------------------------------------- 관문 미달 대조군을 사용자 결정으로 받아들이기


def _fail_controls(pooled: Path) -> str:
    """합친 대조군 기록의 경계 견본 한 줄을 판정 불능으로 바꿔 관문을 떨어뜨리고, 바뀐 파일의 sha256 을 돌려준다."""
    import hashlib

    data = json.loads(pooled.read_text(encoding="utf-8"))
    next(r for r in data["rows"] if r["source"] == "boundary")["judged"] = None
    data |= judge_mod.controls_report(data["rows"])
    pooled.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert data["passed"] is False
    return hashlib.sha256(pooled.read_bytes()).hexdigest()


def _main_judge_argv(tmp_path: Path, probes: Path, out: Path) -> list[str]:
    argv = [*_paid(tmp_path), "judge", "--plants", str(tmp_path / "plants.json"), "--allow-paid"]
    return [*argv, "--judge-model", SONNET, "--probes", str(probes), "--out", str(out)]


def test_a_failed_controls_record_stops_the_main_judge_without_an_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    pooled, probes, calls = _main_judge_setup(tmp_path, monkeypatch)
    _fail_controls(pooled)
    out = tmp_path / "judged.json"
    capsys.readouterr()
    assert main(_main_judge_argv(tmp_path, probes, out)) == 2
    assert "관문을 못 넘었다" in capsys.readouterr().err
    assert calls == [] and not out.exists()


def test_an_override_naming_the_failed_record_by_its_sha_runs_and_marks_every_judged_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    pooled, probes, calls = _main_judge_setup(tmp_path, monkeypatch)
    sha = _fail_controls(pooled)
    out = tmp_path / "judged.json"
    argv = [*_main_judge_argv(tmp_path, probes, out), "--accept-failed-controls", sha, "--accept-reason", "사용자 결정"]
    assert main(argv) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert len(rows) == 2 and len(calls) == 2 * 2  # 줄마다 같은 답 두 표 — 셋째는 부르지 않는다
    for row in rows:
        override = row["controlsOverride"]
        assert override["sha256"] == sha and override["reason"] == "사용자 결정"
        assert override["gate"]["undecided"] == 1


def test_an_override_whose_sha_does_not_match_the_controls_record_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    pooled, probes, calls = _main_judge_setup(tmp_path, monkeypatch)
    _fail_controls(pooled)
    out = tmp_path / "judged.json"
    argv = [*_main_judge_argv(tmp_path, probes, out), "--accept-failed-controls", "a" * 64, "--accept-reason", "r"]
    capsys.readouterr()
    assert main(argv) == 2
    assert "sha256" in capsys.readouterr().err
    assert calls == [] and not out.exists()


def test_an_override_on_a_controls_record_that_passed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib

    from memory_eval_cli import main

    pooled, probes, calls = _main_judge_setup(tmp_path, monkeypatch)
    sha = hashlib.sha256(pooled.read_bytes()).hexdigest()
    out = tmp_path / "judged.json"
    argv = [*_main_judge_argv(tmp_path, probes, out), "--accept-failed-controls", sha, "--accept-reason", "r"]
    capsys.readouterr()
    assert main(argv) == 2
    assert "관문을 넘은" in capsys.readouterr().err
    assert calls == []


def test_an_override_needs_a_reason_and_is_only_for_the_main_judge(tmp_path: Path) -> None:
    from memory_eval_cli import main

    plants = _v1_plants(tmp_path, _secret("s1", nameless=False))
    base = ["--run", str(tmp_path), "--data-dir", str(_data(tmp_path)), "judge", "--plants", str(plants), "--dry-run"]
    assert main([*base, "--accept-failed-controls", "a" * 64]) == 2
    assert main([*base, "--controls", "--accept-failed-controls", "a" * 64, "--accept-reason", "r"]) == 2
    with pytest.raises(SystemExit):
        main([*base, "--accept-failed-controls", "not-a-sha", "--accept-reason", "r"])


def test_the_dry_run_checks_the_override_sha_and_prints_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    pooled, probes, _ = _main_judge_setup(tmp_path, monkeypatch)
    sha = _fail_controls(pooled)
    argv = [
        "--run",
        str(tmp_path),
        "--data-dir",
        str(_data(tmp_path)),
        "judge",
        "--plants",
        str(tmp_path / "plants.json"),
        "--dry-run",
    ]
    argv += ["--judge-model", SONNET, "--probes", str(probes), "--accept-reason", "r"]
    capsys.readouterr()
    assert main([*argv, "--accept-failed-controls", "a" * 64]) == 2
    capsys.readouterr()
    assert main([*argv, "--accept-failed-controls", sha]) == 0
    assert json.loads(capsys.readouterr().out)["controlsOverride"]["sha256"] == sha


def test_an_undecided_control_row_is_reused_as_undecided_and_not_paid_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """대조군에서 세 표가 갈려 불능이 된 응답은 본 판정에서 다시 굴리지 않는다 — 다시 굴리면 불능이 판정으로 바뀔 기회를 그 줄에만
    한 번 더 주는 셈이라, 불능을 그 갈래에 불리하게 세는 규칙과 어긋난다."""
    import hashlib

    from memory_eval_cli import main

    pooled, probes, calls = _main_judge_setup(tmp_path, monkeypatch)
    data = json.loads(pooled.read_text(encoding="utf-8"))
    next(r for r in data["rows"] if r["source"] == "real")["judged"] = None
    data |= judge_mod.controls_report(data["rows"])
    pooled.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert data["passed"] is False
    sha = hashlib.sha256(pooled.read_bytes()).hexdigest()
    out = tmp_path / "judged.json"
    argv = [*_main_judge_argv(tmp_path, probes, out), "--reuse-judged", str(pooled)]
    assert main([*argv, "--accept-failed-controls", sha, "--accept-reason", "r"]) == 0
    judged = {r["arm"]: r for r in json.loads(out.read_text(encoding="utf-8"))}
    assert judged["b1-A0"]["judged"] is None and judged["b1-A0"]["reused"] is True
    assert len(calls) == 2  # 불능 줄은 다시 부르지 않고 나머지 한 줄만 판정 — 같은 답 두 표에서 멈춘다
