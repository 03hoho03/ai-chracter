"""2차 형식 심기 표의 개발/시험 분할과 보기 — 분할은 한 번만(덮어쓰기 거부), 표준출력엔 개수와 해시만, 시험 주 지표 하한,
개발 보기는 시험 문항을 숨기고 시험 정답 파일을 열지 않으며, 시험 보기는 봉인 확인과 해시 대조를 지나야 열린다."""

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from memory_eval import holdout
from memory_eval.metrics import stratified_split
from memory_eval.plants import opus_probes
from memory_eval.seal import PREREGISTRATION_FILE, SEALED_EDITION

PRIMARY = ("relation", "secret", "false_premise", "correction")


def _item(category: str, i: int, *, primary: bool) -> dict[str, Any]:
    turn = 20 + i
    return {
        "id": f"{category}-{i:02d}",
        "category": category,
        "primary": primary,
        "subtype": "x",
        "plant_turns": [turn],
        "plants": [
            {"turn": turn, "line": "assistant", "who": "민지", "assertedBy": "narration", "keywords": [f"단서{i}"]}
        ],
        "keywords": [f"단서{i}"],
        "ask_checkpoints": [100, 300],
        "score_checkpoint": 300,
        "questionForm": "direct",
        "question": f"비밀 질문 {category} {i}",
        "answer_key": {"mode": "match", "bundles": [[f"단서{i}"]], "correct": f"정답 문장 {i}"},
        "expected_fact": None,
    }


def _abstain(i: int) -> dict[str, Any]:
    return {
        "id": f"abstain-{i:02d}",
        "category": "abstain",
        "primary": False,
        "ask_checkpoints": [300],
        "questionForm": "direct",
        "question": f"없던 일 질문 {i}",
        "banned": ["꾸룽돌"],
        "answer_key": {"mode": "judge", "judge_kind": "abstain", "fact": "실제 장면", "nothing": "꾸룽돌"},
        "expected_fact": None,
    }


def _plants(per_primary: int = 13) -> dict[str, Any]:
    plants = [_item(c, i, primary=True) for c in PRIMARY for i in range(per_primary)]
    plants += [_item("detail", i, primary=False) for i in range(5)]
    return {
        "version": "v2",
        "checkpoints": [50, 100, 300],
        "plants": plants,
        "abstains": [_abstain(i) for i in range(4)],
    }


def _write_plants(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "plants.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def _seal(run: Path, *, header: str = f"# 사전 등록 ({SEALED_EDITION})") -> str:
    doc = run / PREREGISTRATION_FILE
    doc.write_text(f"{header}\n본문\n", encoding="utf-8")
    sha = hashlib.sha256(doc.read_bytes()).hexdigest()
    (run / PREREGISTRATION_FILE).with_suffix(".sha256").write_text(f"{sha}  {PREREGISTRATION_FILE}\n", encoding="utf-8")
    return sha


# ---------------------------------------------------------------- 분할


def test_split_shuffles_each_category_with_its_own_seeded_generator_and_sends_the_first_half_up_to_dev() -> None:
    raw = _plants()
    halves = holdout.compute_split(raw)
    by_category: dict[str, list[str]] = {}
    for e in raw["plants"] + raw["abstains"]:
        by_category.setdefault(e["category"], []).append(e["id"])
    expected = {
        item: half
        for category, ids in by_category.items()
        for item, half in stratified_split({category: ids}, holdout.stratum_seed(holdout.SPLIT_SEED, category)).items()
    }
    assert halves == expected
    for category, ids in by_category.items():
        dev = [i for i in ids if halves[i] == "dev"]
        assert len(dev) == math.ceil(len(ids) / 2), category
    assert holdout.compute_split(raw, seed=1) != halves


def test_strata_of_the_same_size_do_not_share_one_positional_permutation() -> None:
    """층마다 같은 시드로 섞으면 크기가 같은 층은 정렬 순 같은 자리가 모두 같은 절반으로 간다 — id 번호 순서가 심은 순서·난이도를
    따라가면 그 쏠림이 층을 넘어 한쪽 절반에 모인다. 시드에 층 이름 해시를 더해 층마다 다른 순열을 쓴다."""
    raw = _plants()  # 주 지표 네 층이 모두 13개
    halves = holdout.compute_split(raw)
    patterns = {
        tuple(halves[e["id"]] for e in sorted(raw["plants"], key=lambda e: e["id"]) if e["category"] == c)
        for c in PRIMARY
    }
    assert len(patterns) == len(PRIMARY)
    assert holdout.stratum_seed(holdout.SPLIT_SEED, "relation") == holdout.stratum_seed(holdout.SPLIT_SEED, "relation")
    assert holdout.stratum_seed(holdout.SPLIT_SEED, "relation") != holdout.stratum_seed(holdout.SPLIT_SEED, "secret")


def test_split_command_prints_only_counts_and_the_test_keys_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    plants = _write_plants(tmp_path, _plants())
    assert main(["--run", str(tmp_path), "split", "--plants", str(plants)]) == 0
    out = capsys.readouterr().out
    printed = json.loads(out)
    assert set(printed) == {"counts", "testKeysSha256"}
    assert printed["counts"]["relation"] == {"dev": 7, "test": 6}
    keys = tmp_path / "split" / holdout.TEST_KEYS_FILE
    assert printed["testKeysSha256"] == hashlib.sha256(keys.read_bytes()).hexdigest()
    assert "비밀 질문" not in out and "단서" not in out and "relation-" not in out


def test_split_writes_ids_only_for_both_halves_and_full_test_items_with_the_answer_key(tmp_path: Path) -> None:
    raw = _plants()
    result = holdout.write_split(_write_plants(tmp_path, raw), tmp_path / "split")
    dev = json.loads((tmp_path / "split" / holdout.DEV_IDS_FILE).read_text(encoding="utf-8"))
    test = json.loads((tmp_path / "split" / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))
    keys = json.loads((tmp_path / "split" / holdout.TEST_KEYS_FILE).read_text(encoding="utf-8"))
    assert all(isinstance(i, str) for i in dev + test)
    assert not set(dev) & set(test)
    assert len(dev) + len(test) == len(raw["plants"]) + len(raw["abstains"])
    assert [e["id"] for e in keys["items"]] == test
    assert all("answer_key" in e and "question" in e for e in keys["items"])
    assert result["testPrimary"] == 24


def test_split_refuses_to_overwrite_any_existing_split_file(tmp_path: Path) -> None:
    plants = _write_plants(tmp_path, _plants())
    (tmp_path / "split").mkdir()
    (tmp_path / "split" / holdout.TEST_IDS_FILE).write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="이미 있다"):
        holdout.write_split(plants, tmp_path / "split")
    assert not (tmp_path / "split" / holdout.TEST_KEYS_FILE).exists()


def test_split_with_too_few_primary_items_in_the_test_half_exits_one_without_writing(tmp_path: Path) -> None:
    from memory_eval_cli import main

    plants = _write_plants(tmp_path, _plants(per_primary=11))  # 층마다 시험 5개 → 20
    assert main(["--run", str(tmp_path), "split", "--plants", str(plants)]) == 1
    assert not (tmp_path / "split").exists()


# ---------------------------------------------------------------- 보기


def _split_run(tmp_path: Path) -> tuple[Path, Path]:
    plants = _write_plants(tmp_path, _plants())
    holdout.write_split(plants, tmp_path / "split")
    return plants, tmp_path / "split"


def test_dev_view_holds_only_dev_items_and_refuses_a_test_item_lookup(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    test_ids = json.loads((split_dir / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))
    view = holdout.load_view(plants, split_dir, {"dev"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=None)
    assert {e["split"] for e in view.all_items()} == {"dev"}
    assert not {e["id"] for e in view.all_items()} & set(test_ids)
    with pytest.raises(SystemExit, match="시험 문항"):
        view.item(test_ids[0])
    with pytest.raises(KeyError):
        view.item("없는-문항")
    assert all(p.split == "dev" for p in opus_probes(view, 300))


def test_dev_view_never_opens_the_test_keys_file(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    (split_dir / holdout.TEST_KEYS_FILE).unlink()
    view = holdout.load_view(plants, split_dir, {"dev"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=None)
    assert view.plants


def test_test_view_needs_the_seal_hash(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    _seal(tmp_path)
    with pytest.raises(SystemExit, match="봉인"):
        holdout.load_view(plants, split_dir, {"test"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=None)


def test_test_view_refuses_an_older_edition_preregistration(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    sha = _seal(tmp_path, header="# 사전 등록 (v2)")
    with pytest.raises(SystemExit, match=SEALED_EDITION):
        holdout.load_view(plants, split_dir, {"test"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=sha)


def test_sealed_test_view_takes_test_items_from_the_test_keys_file(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    sha = _seal(tmp_path)
    keys = json.loads((split_dir / holdout.TEST_KEYS_FILE).read_text(encoding="utf-8"))
    view = holdout.load_view(
        plants, split_dir, {"dev", "test"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=sha
    )
    assert {e["id"] for e in view.all_items() if e["split"] == "test"} == {e["id"] for e in keys["items"]}
    assert view.hidden == frozenset()
    only_test = holdout.load_view(
        plants, split_dir, {"test"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=sha
    )
    assert {e["split"] for e in only_test.all_items()} == {"test"}


def test_tampered_test_keys_file_is_refused(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    sha = _seal(tmp_path)
    path = split_dir / holdout.TEST_KEYS_FILE
    path.write_text(path.read_text(encoding="utf-8").replace("정답 문장", "바뀐 문장"), encoding="utf-8")
    with pytest.raises(SystemExit, match="sha256"):
        holdout.load_view(plants, split_dir, {"test"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=sha)


def test_plants_changed_after_the_split_are_refused(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    raw = _plants()
    raw["plants"][0]["question"] = "고친 질문"
    plants.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="분할 때와 다르다"):
        holdout.load_view(plants, split_dir, {"dev"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=None)


def test_harness_entry_maps_second_format_fields_to_the_ones_the_probe_and_recall_code_read() -> None:
    entry = _item("correction", 1, primary=True) | {"plant_turns": [40, 61]}
    entry["plants"] = [
        {"turn": 40, "line": "assistant", "who": "민지", "assertedBy": "character"},
        {"turn": 61, "line": "assistant", "who": "narration", "assertedBy": "narration"},
    ]
    out = holdout.harness_entry(entry, "dev", [50, 100, 300])
    assert out["plantTurn"] == 61 and out["plantTurns"] == [40, 61]
    assert out["speaker"]["assertedBy"] == "narration"
    # 마지막 심기 61턴이 접혔다고 볼 수 있는 체크포인트는 61 ≤ cp − 30 인 것뿐이다(91 이상).
    assert out["probeCheckpoints"] == {"opus": [100, 300], "offline": [100, 300]}
    assert out["answerKeys"] == [["단서1"]]
    assert out["expectedAnswer"] == "정답 문장 1"
    abstain = holdout.harness_entry(_abstain(0), "dev", [50, 100, 300])
    assert abstain["probeCheckpoints"]["offline"] == [300]
    assert abstain["expectedAnswer"] == "실제 장면"


def test_harness_entry_turns_the_plants_refuted_status_into_disproved_in_one_place() -> None:
    entry = _item("correction", 2, primary=True)
    entry["expected_fact"] = {
        "kind": "fact",
        "subject": "민지",
        "attribute": "생일",
        "value": "6월",
        "truth_status": "confirmed",
        "superseded": [{"value": "5월", "truth_status": "refuted", "said_by": "태민"}],
    }
    claim = _item("false_premise", 3, primary=True) | {
        "expected_fact": {
            "kind": "fact",
            "subject": "도희",
            "attribute": "수상",
            "value": "없음",
            "truth_status": "refuted",
        }
    }
    out = holdout.harness_entry(entry, "dev", [300])
    assert out["expected_fact"]["superseded"][0]["truth_status"] == "disproved"
    assert out["expected_fact"]["truth_status"] == "confirmed"
    assert holdout.harness_entry(claim, "dev", [300])["expected_fact"]["truth_status"] == "disproved"
    assert entry["expected_fact"]["superseded"][0]["truth_status"] == "refuted"  # 원본은 건드리지 않는다


def test_probe_dry_run_in_dev_mode_refuses_a_test_item_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from memory_eval_cli import main

    plants, split_dir = _split_run(tmp_path)
    test_id = json.loads((split_dir / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))[0]
    argv = ["--run", str(tmp_path), "probe", "--plants", str(plants), "--stage", "s8", "--arm", "A", "--dry-run"]
    assert main([*argv, "--items", test_id]) == 2
    assert "시험 문항" in capsys.readouterr().err
    assert main(argv) == 0
    plan = json.loads(capsys.readouterr().out)["plan"]
    assert plan and not {p["item"] for p in plan} & {test_id}


def test_first_format_commands_refuse_a_second_format_plants_file(tmp_path: Path) -> None:
    from memory_eval_cli import main

    plants = _write_plants(tmp_path, _plants())
    assert main(["--run", str(tmp_path), "split-check", "--plants", str(plants)]) == 2


def test_probe_halt_base_is_the_planned_probe_count_and_a_stale_explicit_base_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """불능 멈춤의 5% 기준은 이번 실행이 사전 등록 문항으로 계획한 프로브 수다 — 앞 측정의 문항 수가 기본값으로 남아 있으면
    문항 수가 다른 측정에서 멈춤 선이 조용히 어긋난다."""
    from memory_eval_cli import main

    plants, split_dir = _split_run(tmp_path)
    view = holdout.load_view(plants, split_dir, {"dev"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=None)
    planned = sum(len(opus_probes(view, cp)) for cp in (50, 100, 300))
    assert planned != 56
    argv = ["--run", str(tmp_path), "probe", "--plants", str(plants), "--stage", "s8", "--arm", "A", "--dry-run"]
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["haltBase"] == planned
    one = view.plants[0]["id"]
    assert main([*argv, "--items", one]) == 0  # 일부 문항만 다시 돌려도 기준은 계획 전체다
    assert json.loads(capsys.readouterr().out)["haltBase"] == planned
    assert main([*argv, "--halt-base", "56"]) == 2
    assert "멈춤 기준" in capsys.readouterr().err
    assert main([*argv, "--halt-base", str(planned)]) == 0
