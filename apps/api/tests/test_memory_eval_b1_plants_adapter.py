"""묶음 1 심기 표 꼴(작품별 분할 폴더, 영어 범주, 이름 없이 등장하는 모르는 인물)이 하네스의 프로브·판정·투입 경로로
읽히는가. 이름 없는 인물 비밀은 판정 입력에 그 역할을 모르는 인물로 싣고(이름 칸이 비어 줄째 빠지면 판정자가 누구를 볼지
모른다), 이름 있는 인물의 판정 입력은 바이트 그대로다. 개발 보기는 시험 id 를 거부한다."""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_eval import bundle_split, holdout, judge, plants as plants_mod
from memory_eval.seal import PREREGISTRATION_FILE
from memory_eval_fakes import fake_wording


def _secret(i: int, *, nameless: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": f"t-sec{i:02d}",
        "category": "secret",
        "subtype": "confided",
        "stratum": "secret:main",
        "primary": True,
        "people": ["탁여솔", "사용자"],
        "plant_turns": [20],
        "plants": [{"turn": 20, "line": "assistant", "who": "탁여솔", "assertedBy": "character", "keywords": ["탈춤 연습"]}],
        "keywords": ["탈춤 연습"],
        "ask_checkpoints": [300],
        "score_checkpoint": 300,
        "questionForm": "direct",
        "setup_turn_text": f"장면 설정 {i}",
        "question": f"비밀 질문 {i}",
        "secretOwner": "탁여솔",
        "unawareCharacter": None if nameless else "편소담",
        "answer_key": {
            "mode": "judge",
            "correct": "모르는 채로 그린다",
            "fail_if": "아는 듯 말한다",
            "leak_bundles": [["탈춤 연습"]],
        },
        "expected_fact": {"kind": "fact", "subject": "탁여솔", "attribute": "계획", "value": "탈춤 연습",
                          "truth_status": "confirmed", "said_by": "탁여솔", "known_by": ["탁여솔", "사용자"]},
    }  # fmt: skip
    if nameless:
        entry["unawareRole"] = "부두 창고의 처음 보는 목수"
    return entry


def _rephrase(i: int) -> dict[str, Any]:
    return {
        "id": f"t-rph{i:02d}",
        "category": "rephrase",
        "subtype": "object",
        "stratum": "rephrase",
        "primary": False,
        "plant_turns": [30],
        "plants": [{"turn": 30, "line": "user", "who": "사용자", "assertedBy": "user", "keywords": ["자개 단추"]}],
        "keywords": ["자개 단추"],
        "ask_checkpoints": [300],
        "score_checkpoint": 300,
        "questionForm": "anaphora" if i == 0 else "paraphrase",
        "contextTurn": {"userLine": "그때 맡긴 거 기억나?"},
        "question": f"바꿔 말한 질문 {i}",
        "answer_key": {"mode": "match", "bundles": [["자개 단추", "자개빛 단추"]], "correct": "자개 단추"},
        "expected_fact": {"kind": "fact", "subject": "사용자", "value": "자개 단추"},
    }


def _abstain(i: int) -> dict[str, Any]:
    return {
        "id": f"t-abs{i:02d}",
        "category": "abstain",
        "subtype": "pure",
        "stratum": "abstain",
        "primary": False,
        "ask_checkpoints": [300],
        "questionForm": "direct",
        "question": f"없던 일 {i}",
        "banned": ["카누장"],
        "answer_key": {"mode": "judge", "judge_kind": "abstain", "fact": "없었다"},
        "expected_fact": None,
    }


def _bundle(tmp_path: Path, *, lane: str | None = "story") -> tuple[Path, Path]:
    raw: dict[str, Any] = {
        "version": "t",
        "checkpoints": [100, 300],
        "plants": [_secret(i, nameless=i % 2 == 1) for i in range(8)] + [_rephrase(i) for i in range(4)],
        "abstains": [_abstain(i) for i in range(2)],
    }
    if lane is not None:
        raw["lane"] = lane
    tmp_path.mkdir(parents=True, exist_ok=True)
    plants = tmp_path / "plants-t.json"
    plants.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    config = tmp_path / "split-seeds.json"
    config.write_text(
        json.dumps(
            {"base": 1, "works": {"t": {"plants": plants.name, "strata": {"secret:main": 11, "rephrase": 12,
                                                                          "abstain": 13}}},
             "totals": []}
        ),
        encoding="utf-8",
    )  # fmt: skip
    root = tmp_path / "run" / "b1" / "split"
    assert bundle_split.write_bundle(config, root)["ok"]
    return plants, root / "t"


def _dev_view(tmp_path: Path, plants: Path, split_dir: Path) -> plants_mod.PlantSet:
    return holdout.load_view(
        plants, split_dir, {"dev"}, preregistration=tmp_path / "run" / PREREGISTRATION_FILE, seal_sha=None
    )


def test_bundle_split_folder_loads_as_a_dev_view_that_hides_test_ids(tmp_path: Path) -> None:
    plants, split_dir = _bundle(tmp_path)
    view = _dev_view(tmp_path, plants, split_dir)
    dev = set(json.loads((split_dir / holdout.DEV_IDS_FILE).read_text(encoding="utf-8")))
    test = json.loads((split_dir / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))
    assert {e["id"] for e in view.all_items()} == dev
    with pytest.raises(SystemExit, match="시험 문항"):
        view.item(test[0])


def test_probes_from_the_bundle_format_keep_two_turn_secrets_and_anaphora_context(tmp_path: Path) -> None:
    plants, split_dir = _bundle(tmp_path)
    view = _dev_view(tmp_path, plants, split_dir)
    probes = {p.item_id: p for p in plants_mod.opus_probes(view, 300)}
    assert set(probes) == {e["id"] for e in view.all_items()}
    for item_id, probe in probes.items():
        entry = view.item(item_id)
        if entry["category"] == "secret":
            assert probe.turns == [entry["setup_turn_text"], entry["question"]] and probe.guard_memory
        elif entry["questionForm"] == "anaphora":
            assert probe.turns == ["그때 맡긴 거 기억나?", entry["question"]] and not probe.guard_memory
        else:
            assert probe.turns == [entry["question"]]
        assert probe.kind == ("abstain" if entry["category"] == "abstain" else "plant")


def test_rephrase_is_scored_by_the_answer_bundles_without_a_judge() -> None:
    entry = _rephrase(1)
    assert judge.judge_kind(entry) is None
    assert judge.deterministic(entry, ["자개빛 단추를 맡겼지."])["hit"] is True
    assert judge.deterministic(entry, ["모르겠어."])["hit"] is False


def test_nameless_unaware_person_is_named_by_role_in_the_judge_input(tmp_path: Path) -> None:
    facts = judge.judge_facts("secret", _secret(1, nameless=True), fake_wording(tmp_path))
    block = facts.split("[모르는 인물]\n", 1)[1].split("\n[", 1)[0]
    assert "부두 창고의 처음 보는 목수" in block and "이름" in block


def test_named_unaware_person_judge_input_is_unchanged(tmp_path: Path) -> None:
    entry = _secret(0, nameless=False)
    expected = (
        "[장면 설정]\n장면 설정 0\n[질문]\n비밀 질문 0\n[비밀 주인]\n탁여솔\n[모르는 인물]\n편소담\n[비밀]\n계획 — 탈춤 연습"
        "\n[성공 기준]\n모르는 채로 그린다\n[실패 조건]\n아는 듯 말한다"
    )
    assert judge.judge_facts("secret", entry, fake_wording(tmp_path)) == expected


def test_nameless_secret_controls_use_the_role_and_carry_their_own_stratum(tmp_path: Path) -> None:
    entries = [holdout.harness_entry(_secret(i, nameless=i == 1), "dev", [100, 300]) for i in range(2)]
    view = plants_mod.PlantSet(raw={}, plants=entries, abstains=[])
    rows = [r for r in judge.controls(view, fake_wording(tmp_path)) if r["kind"] == "secret"]
    assert {r["item"] for r in rows} == {"t-sec00", "t-sec01"}
    assert {r["expected"] for r in rows} == {"kept", "leaked"}
    for row in rows:
        assert "None" not in row["reply"]
        if row["item"] == "t-sec01":
            assert row["reply"].startswith("부두 창고의 처음 보는 목수")
            assert row["stratum"] == "secret:nameless"
        else:
            assert row["reply"].startswith("편소담") and "stratum" not in row


def test_controls_report_shows_accuracy_for_the_nameless_stratum_without_changing_the_gate() -> None:
    rows = [
        {"kind": "secret", "expected": "kept", "judged": "kept"},
        {"kind": "secret", "expected": "leaked", "judged": "leaked"},
        {"kind": "secret", "expected": "kept", "judged": "leaked", "stratum": "secret:nameless"},
        {"kind": "secret", "expected": "leaked", "judged": "leaked", "stratum": "secret:nameless"},
    ]
    report = judge.controls_report(rows)
    assert report["observed"]["accuracyByStratum"] == {"secret:nameless": 0.5}
    assert report["gate"]["binaryAccuracy"] == {"secret": 0.75}


def test_plant_lane_comes_from_the_plants_file_and_an_unknown_lane_is_refused(tmp_path: Path) -> None:
    from memory_eval.insert import plant_lane

    for lane in ("story", "character"):
        plants, split_dir = _bundle(tmp_path / lane, lane=lane)
        assert plant_lane(_dev_view(tmp_path / lane, plants, split_dir)) == lane
    plants, split_dir = _bundle(tmp_path / "none", lane=None)
    assert plant_lane(_dev_view(tmp_path / "none", plants, split_dir)) is None
    bad = plants_mod.PlantSet(raw={"lane": "webtoon"}, plants=[], abstains=[])
    with pytest.raises(SystemExit, match="레인"):
        plant_lane(bad)


def _probe_argv(tmp_path: Path, plants: Path, split_dir: Path, arm: str) -> list[str]:
    return ["--run", str(tmp_path / "run"), "probe", "--plants", str(plants), "--split-dir", str(split_dir),
            "--stage", "b1", "--arm", arm, "--checkpoints", "300", "--dry-run"]  # fmt: skip


def test_probe_dry_run_takes_bundle_arms_by_lane_and_refuses_a_test_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    plants, split_dir = _bundle(tmp_path, lane="character")
    assert main(_probe_argv(tmp_path, plants, split_dir, "b1-B2")) == 0
    capsys.readouterr()
    assert main(_probe_argv(tmp_path, plants, split_dir, "b1-B1E")) == 2
    assert "캐릭터" in capsys.readouterr().err
    test_id = json.loads((split_dir / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))[0]
    assert main([*_probe_argv(tmp_path, plants, split_dir, "b1-A1"), "--items", test_id]) == 2
    assert "시험 문항" in capsys.readouterr().err


def test_probe_with_a_bundle_arm_needs_a_lane_in_the_plants_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    plants, split_dir = _bundle(tmp_path, lane=None)
    assert main(_probe_argv(tmp_path, plants, split_dir, "b1-A0")) == 2
    assert "레인" in capsys.readouterr().err
    assert main(_probe_argv(tmp_path, plants, split_dir, "A")) == 0


def test_probe_categories_plan_only_those_judged_kinds_and_the_halt_base_counts_only_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """안전 범주만 보내는 갈래는 그 범주 문항만 계획한다 — 불능 멈춤 기준도 그 계획의 프로브 수라, 보내지 않을
    문항까지 분모에 넣어 멈춤 선이 느슨해지지 않는다."""
    from memory_eval_cli import main

    plants, split_dir = _bundle(tmp_path)
    view = _dev_view(tmp_path, plants, split_dir)
    secrets = {
        p.item_id for p in plants_mod.opus_probes(view, 300) if judge.judge_kind(view.item(p.item_id)) == "secret"
    }
    others = {p.item_id for p in plants_mod.opus_probes(view, 300)} - secrets
    assert secrets and others
    argv = _probe_argv(tmp_path, plants, split_dir, "b1-B2")
    assert main([*argv, "--categories", "secret"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {p["item"] for p in out["plan"]} == secrets
    assert out["haltBase"] == len(secrets)
    assert main([*argv, "--categories", "secret,abstain"]) == 0
    assert {p["item"] for p in json.loads(capsys.readouterr().out)["plan"]} == secrets | {
        i for i in others if judge.judge_kind(view.item(i)) == "abstain"
    }
    with pytest.raises(SystemExit):  # 모르는 범주는 인자 해석에서 멈춘다
        main([*argv, "--categories", "nonsense"])
    capsys.readouterr()
    assert main(argv) == 0  # 주지 않으면 지금처럼 전부
    assert {p["item"] for p in json.loads(capsys.readouterr().out)["plan"]} == secrets | others
