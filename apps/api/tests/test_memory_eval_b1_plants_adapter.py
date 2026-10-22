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
    assert bundle_split.write_bundle(config, root, seed_sha=holdout.sha256_file(config))["ok"]
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
    assert main(_probe_argv(tmp_path, plants, split_dir, "b1-B1E")) == 0
    capsys.readouterr()
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


def _kinds(tmp_path: Path, plants: Path, split_dir: Path) -> tuple[list[str], list[str]]:
    view = _dev_view(tmp_path, plants, split_dir)
    ids = sorted(p.item_id for p in plants_mod.opus_probes(view, 300))
    secrets = [i for i in ids if judge.judge_kind(view.item(i)) == "secret"]
    return secrets, [i for i in ids if i not in secrets]


def test_probe_items_left_out_of_the_plan_by_category_or_checkpoint_are_refused_by_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """요청한 문항이 범주 거르기나 체크포인트 조건으로 계획에서 빠지면 아무것도 돌지 않은 채 정상 종료하던 것을 막는다 — 다시
    돌렸다고 믿은 문항의 결과가 비어 있게 된다."""
    from memory_eval_cli import main

    plants, split_dir = _bundle(tmp_path)
    secrets, others = _kinds(tmp_path, plants, split_dir)
    argv = _probe_argv(tmp_path, plants, split_dir, "b1-B2")
    assert main([*argv, "--categories", "secret", "--items", others[0]]) == 2  # 전부 범주 밖
    err = capsys.readouterr().err
    assert others[0] in err and "범주" in err
    assert main([*argv, "--categories", "secret", "--items", f"{secrets[0]},{others[0]}"]) == 2  # 일부만 밖
    err = capsys.readouterr().err
    assert others[0] in err and secrets[0] not in err
    assert main([*argv, "--checkpoints", "100", "--items", secrets[0]]) == 2  # 그 체크포인트에서 묻지 않는 문항
    err = capsys.readouterr().err
    assert secrets[0] in err and "체크포인트" in err


def test_probe_items_whose_results_are_all_on_file_finish_cleanly_and_an_unknown_id_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    plants, split_dir = _bundle(tmp_path)
    secrets, _ = _kinds(tmp_path, plants, split_dir)
    out = tmp_path / "run" / "probes" / "b1-b1-B2.jsonl"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"checkpoint": 300, "item": secrets[0], "status": "ok"}) + "\n", encoding="utf-8")
    argv = _probe_argv(tmp_path, plants, split_dir, "b1-B2")
    assert main([*argv, "--items", secrets[0]]) == 0  # 계획에는 들었고 결과가 이미 있다 — 남은 게 없을 뿐이다
    assert json.loads(capsys.readouterr().out)["plan"] == []
    assert main([*argv, "--items", f"{secrets[0]},t-지어낸문항"]) == 2
    err = capsys.readouterr().err
    assert "t-지어낸문항" in err and "없는" in err


def _probe_rows_file(tmp_path: Path, units: list[tuple[int, str]]) -> Path:
    out = tmp_path / "run" / "probes" / "b1-b1-B2.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps({"checkpoint": cp, "item": item, "status": "ok"}) + "\n" for cp, item in units),
        encoding="utf-8",
    )
    return out


def test_probe_redo_plans_only_the_named_units_and_refuses_a_repeat_or_an_unplanned_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """다시 돌릴 단위는 결과가 있어도 계획에 든다. 드라이런은 결과 파일·폴더를 옮기지 않는다."""
    from memory_eval_cli import main

    plants, split_dir = _bundle(tmp_path)
    secrets, _ = _kinds(tmp_path, plants, split_dir)
    out = _probe_rows_file(tmp_path, [(300, secrets[0]), (300, secrets[1])])
    before = out.read_bytes()
    argv = _probe_argv(tmp_path, plants, split_dir, "b1-B2")
    assert main([*argv, "--redo", f"300:{secrets[0]}"]) == 0
    plan = json.loads(capsys.readouterr().out)["plan"]
    assert [(p["cp"], p["item"]) for p in plan] == [(300, secrets[0])]
    assert out.read_bytes() == before
    assert main([*argv, "--redo", f"300:{secrets[2]}"]) == 0  # 결과가 없는 단위는 보통 실행처럼 돈다
    assert [(p["cp"], p["item"]) for p in json.loads(capsys.readouterr().out)["plan"]] == [(300, secrets[2])]
    assert main([*argv, "--redo", f"300:{secrets[0]},300:{secrets[0]}"]) == 2
    assert "중복" in capsys.readouterr().err
    # 그 체크포인트에서는 묻지 않는 문항이라 계획에 없다
    assert main([*argv, "--checkpoints", "100,300", "--redo", f"100:{secrets[0]}"]) == 2
    assert f"100:{secrets[0]}" in capsys.readouterr().err


def test_setting_aside_redo_units_moves_their_rows_and_folders_under_stale_and_keeps_the_rest(tmp_path: Path) -> None:
    from memory_eval.probe import set_aside_units

    run = tmp_path / "run"
    out = _probe_rows_file(tmp_path, [(300, "q1"), (300, "q2"), (100, "q1")])
    for cp, item in ((300, "q1"), (300, "q2"), (100, "q1")):
        attempt = run / "probes" / f"b1-cp{cp}-b1-B2" / item / "attempt1"
        attempt.mkdir(parents=True)
        (attempt / "server.log").write_text(f"{cp}-{item}\n", encoding="utf-8")

    stale = set_aside_units(run, stage="b1", arm="b1-B2", out=out, units={(300, "q1")})

    assert stale is not None and stale.parent == run / "probes" and stale.name.startswith("stale-")
    kept = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [(r["checkpoint"], r["item"]) for r in kept] == [(300, "q2"), (100, "q1")]
    moved = [json.loads(line) for line in (stale / out.name).read_text(encoding="utf-8").splitlines()]
    assert [(r["checkpoint"], r["item"]) for r in moved] == [(300, "q1")]
    assert not (run / "probes" / "b1-cp300-b1-B2" / "q1").exists()
    log = stale / "b1-cp300-b1-B2" / "q1" / "attempt1" / "server.log"
    assert log.read_text(encoding="utf-8") == "300-q1\n"
    for cp, item in ((300, "q2"), (100, "q1")):
        assert (run / "probes" / f"b1-cp{cp}-b1-B2" / item / "attempt1" / "server.log").exists()
    assert sorted(p.name for p in out.parent.iterdir() if p.is_file()) == [out.name]  # 임시 파일이 남지 않는다
    # 결과 행이 없는 단위는 옮길 것이 없다
    assert set_aside_units(run, stage="b1", arm="b1-B2", out=out, units={(300, "q9")}) is None


def test_a_failure_while_rewriting_the_results_leaves_the_result_file_whole_and_the_moved_rows_under_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남길 행을 다시 쓰다 멈춰도(바꿔 끼우기 직전 실패) 결과 파일은 원래 바이트 그대로이고, 뺀 행은 stale 아래에 이미 있다 —
    결과 파일을 그 자리에서 덮어쓰면 반쯤 쓰인 파일이 남아 끝난 단위가 사라진다."""
    from memory_eval import probe

    run = tmp_path / "run"
    out = _probe_rows_file(tmp_path, [(300, "q1"), (300, "q2"), (100, "q1")])
    before = out.read_bytes()

    def broken_replace(src: object, dst: object) -> None:
        raise OSError("지어낸 쓰기 실패")

    monkeypatch.setattr("memory_eval.probe.os.replace", broken_replace)
    with pytest.raises(OSError, match="지어낸 쓰기 실패"):
        probe.set_aside_units(run, stage="b1", arm="b1-B2", out=out, units={(300, "q1")})
    assert out.read_bytes() == before
    (stale,) = (run / "probes").glob("stale-*")
    moved = [json.loads(line) for line in (stale / out.name).read_text(encoding="utf-8").splitlines()]
    assert [(r["checkpoint"], r["item"]) for r in moved] == [(300, "q1")]


def test_the_targeted_table_asks_each_category_in_every_arm_its_comparisons_need() -> None:
    """범주마다 묻는 갈래 — 비밀·거짓 전제는 다섯 갈래, 관계·정정은 넷, 바꿔 말하기는 B1·B1E, 디테일은 A0·A1. 판정이 견주는
    쌍·효과·비열등의 두 갈래가 그 범주를 묻는 갈래에 모두 들어 있어야 한다(빠지면 그 비교가 입력 누락으로 멈춘다)."""
    from memory_eval import verdict_v4 as v4

    five = ("b1-A0", "b1-A1", "b1-B1", "b1-B1E", "b1-B2")
    assert v4.TARGETED_ARMS == {
        "secret": five, "false_premise": five,
        "relation": five[1:], "correction": five[1:],
        "rephrase": ("b1-B1", "b1-B1E"), "detail": ("b1-A0", "b1-A1"),
    }  # fmt: skip
    needs: list[tuple[tuple[str, str], tuple[str, ...]]] = [
        ((a, b), (v4.SECRET_CATEGORY, v4.PREMISE_CATEGORY)) for a, b, _ in v4.SAFETY_PAIRS + v4.REFERENCE_PAIRS
    ]
    needs += [((a, b), cats) for a, b, cats, _ in v4.EFFECTS.values()]
    needs += [(v4.NONINFERIORITY[:2], v4.NONINFERIORITY[2])]
    for arms, categories in needs:
        for category in categories:
            assert set(arms) <= set(v4.TARGETED_ARMS[category]), (arms, category)


def test_probe_targeted_plans_only_the_categories_that_arm_is_asked_and_keeps_unlisted_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """표적형은 사람이 문항 id 목록을 만들지 않고 범주 → 갈래 표로 계획을 고른다. 표에 없는 범주(기권 등 관찰 범주)는 모든
    갈래에서 묻는다. 표에 없는 갈래(A0M)는 거부한다 — 그 갈래가 무엇을 물어야 하는지 표가 정하지 않았다."""
    from memory_eval_cli import main

    plants, split_dir = _bundle(tmp_path)
    view = _dev_view(tmp_path, plants, split_dir)
    by_category: dict[str, set[str]] = {}
    for probe in plants_mod.opus_probes(view, 300):
        by_category.setdefault(str(view.item(probe.item_id)["category"]), set()).add(probe.item_id)
    assert {"secret", "rephrase", "abstain"} <= set(by_category)
    expected = {
        "b1-A0": by_category["secret"] | by_category["abstain"],
        "b1-B1E": by_category["secret"] | by_category["rephrase"] | by_category["abstain"],
    }
    for arm, items in expected.items():
        assert main([*_probe_argv(tmp_path, plants, split_dir, arm), "--targeted"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert {p["item"] for p in out["plan"]} == items, arm
        assert out["haltBase"] == len(items)
    assert main([*_probe_argv(tmp_path, plants, split_dir, "b1-B1E"), "--targeted", "--categories", "secret"]) == 0
    assert {p["item"] for p in json.loads(capsys.readouterr().out)["plan"]} == by_category["secret"]
    rephrase = sorted(by_category["rephrase"])[0]
    assert main([*_probe_argv(tmp_path, plants, split_dir, "b1-A0"), "--targeted", "--items", rephrase]) == 2
    assert rephrase in capsys.readouterr().err
    assert main([*_probe_argv(tmp_path, plants, split_dir, "b1-A0M"), "--targeted"]) == 2
    assert "A0M" in capsys.readouterr().err
