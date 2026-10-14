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
        "banned": ["노래방"],
        "answer_key": {"mode": "judge", "judge_kind": "abstain", "fact": "실제 장면", "nothing": "노래방"},
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


def _seal(run: Path, *, header: str = "# 사전 등록 (v3)") -> str:
    doc = run / "preregistration.md"
    doc.write_text(f"{header}\n본문\n", encoding="utf-8")
    sha = hashlib.sha256(doc.read_bytes()).hexdigest()
    (run / "preregistration.sha256").write_text(f"{sha}  preregistration.md\n", encoding="utf-8")
    return sha


# ---------------------------------------------------------------- 분할


def test_split_shuffles_each_category_with_its_own_seeded_generator_and_sends_the_first_half_up_to_dev() -> None:
    raw = _plants()
    halves = holdout.compute_split(raw)
    by_category: dict[str, list[str]] = {}
    for e in raw["plants"] + raw["abstains"]:
        by_category.setdefault(e["category"], []).append(e["id"])
    assert halves == stratified_split(by_category, holdout.SPLIT_SEED)
    for category, ids in by_category.items():
        dev = [i for i in ids if halves[i] == "dev"]
        assert len(dev) == math.ceil(len(ids) / 2), category
    assert holdout.compute_split(raw, seed=1) != halves


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
    view = holdout.load_view(plants, split_dir, {"dev"}, preregistration=tmp_path / "preregistration.md", seal_sha=None)
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
    view = holdout.load_view(plants, split_dir, {"dev"}, preregistration=tmp_path / "preregistration.md", seal_sha=None)
    assert view.plants


def test_test_view_needs_the_seal_hash(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    _seal(tmp_path)
    with pytest.raises(SystemExit, match="봉인"):
        holdout.load_view(plants, split_dir, {"test"}, preregistration=tmp_path / "preregistration.md", seal_sha=None)


def test_test_view_refuses_an_older_edition_preregistration(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    sha = _seal(tmp_path, header="# 사전 등록 (v2)")
    with pytest.raises(SystemExit, match="v3"):
        holdout.load_view(plants, split_dir, {"test"}, preregistration=tmp_path / "preregistration.md", seal_sha=sha)


def test_sealed_test_view_takes_test_items_from_the_test_keys_file(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    sha = _seal(tmp_path)
    keys = json.loads((split_dir / holdout.TEST_KEYS_FILE).read_text(encoding="utf-8"))
    view = holdout.load_view(
        plants, split_dir, {"dev", "test"}, preregistration=tmp_path / "preregistration.md", seal_sha=sha
    )
    assert {e["id"] for e in view.all_items() if e["split"] == "test"} == {e["id"] for e in keys["items"]}
    assert view.hidden == frozenset()
    only_test = holdout.load_view(
        plants, split_dir, {"test"}, preregistration=tmp_path / "preregistration.md", seal_sha=sha
    )
    assert {e["split"] for e in only_test.all_items()} == {"test"}


def test_tampered_test_keys_file_is_refused(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    sha = _seal(tmp_path)
    path = split_dir / holdout.TEST_KEYS_FILE
    path.write_text(path.read_text(encoding="utf-8").replace("정답 문장", "바뀐 문장"), encoding="utf-8")
    with pytest.raises(SystemExit, match="sha256"):
        holdout.load_view(plants, split_dir, {"test"}, preregistration=tmp_path / "preregistration.md", seal_sha=sha)


def test_plants_changed_after_the_split_are_refused(tmp_path: Path) -> None:
    plants, split_dir = _split_run(tmp_path)
    raw = _plants()
    raw["plants"][0]["question"] = "고친 질문"
    plants.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="분할 때와 다르다"):
        holdout.load_view(plants, split_dir, {"dev"}, preregistration=tmp_path / "preregistration.md", seal_sha=None)


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
