"""대본 셋을 한꺼번에 나누는 분할 — 층마다 시드 파일의 시드로 섞고, 층 크기는 짝수여야 하며, 작품을 넘는 시험 합계 하한을
하나라도 못 채우면 어떤 작품의 분할 파일도 쓰지 않는다. 미리 보기는 개수만 찍고 파일을 만들지 않는다."""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_eval import bundle_split, holdout
from memory_eval.metrics import stratified_split
from memory_eval.seal import PREREGISTRATION_FILE


def _entry(item_id: str, category: str, stratum: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": item_id,
        "category": category,
        "primary": category in ("secret", "relation", "false_premise", "correction"),
        "ask_checkpoints": [300],
        "question": f"질문 {item_id}",
        "answer_key": {"mode": "match", "bundles": [["정답"]], "correct": f"정답 문장 {item_id}"},
    }
    if stratum is not None:
        entry["stratum"] = stratum
    return entry


def _plants(prefix: str, sizes: dict[str, int]) -> dict[str, Any]:
    plants: list[dict[str, Any]] = []
    for stratum, n in sizes.items():
        category = stratum.split(":")[0]
        plants += [_entry(f"{prefix}-{stratum}-{i:02d}", category, stratum) for i in range(n)]
    return {"version": "t", "checkpoints": [100, 300], "plants": plants, "abstains": []}


def _write_config(
    tmp_path: Path,
    works: dict[str, dict[str, int]],
    totals: list[dict[str, Any]],
    *,
    seeds: dict[str, dict[str, int]] | None = None,
) -> Path:
    cfg_works: dict[str, Any] = {}
    for name, sizes in works.items():
        path = tmp_path / f"plants-{name}.json"
        path.write_text(json.dumps(_plants(name, sizes), ensure_ascii=False), encoding="utf-8")
        strata_seeds = (seeds or {}).get(name) or {s: 1000 + k for k, s in enumerate(sizes)}
        cfg_works[name] = {"plants": path.name, "strata": strata_seeds}
    cfg = tmp_path / "split-seeds.json"
    cfg.write_text(json.dumps({"base": 7, "works": cfg_works, "totals": totals}, ensure_ascii=False), encoding="utf-8")
    return cfg


STORY = {"secret:early": 4, "secret:main": 6, "detail": 10}
TOTALS = [
    {"name": "비밀", "works": ["a", "b"], "categories": ["secret"], "min": 10},
    {"name": "디테일", "works": ["a", "b"], "categories": ["detail"], "min": 10},
]


def test_each_stratum_is_shuffled_with_the_seed_the_seed_file_gives_that_stratum(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, {"a": STORY}, [])
    plan = bundle_split.plan_bundle(cfg)
    raw = json.loads((tmp_path / "plants-a.json").read_text(encoding="utf-8"))
    for k, stratum in enumerate(STORY):
        ids = [e["id"] for e in raw["plants"] if e["stratum"] == stratum]
        expected = stratified_split({stratum: ids}, 1000 + k)
        assert {i: plan["halves"]["a"][i] for i in ids} == expected


def test_changing_one_stratum_seed_moves_only_that_stratum(tmp_path: Path) -> None:
    first = bundle_split.plan_bundle(_write_config(tmp_path, {"a": STORY}, []))["halves"]["a"]
    other = {"a": {"secret:early": 1000, "secret:main": 1001, "detail": 4242}}
    second = bundle_split.plan_bundle(_write_config(tmp_path, {"a": STORY}, [], seeds=other))["halves"]["a"]
    moved = {i for i in first if first[i] != second[i]}
    assert moved
    assert all("-detail-" in i for i in moved)


def test_secret_layers_are_separate_strata_so_each_layer_sends_exactly_half_to_test(tmp_path: Path) -> None:
    plan = bundle_split.plan_bundle(_write_config(tmp_path, {"a": STORY}, []))
    assert plan["counts"]["a"]["secret:early"] == {"dev": 2, "test": 2}
    assert plan["counts"]["a"]["secret:main"] == {"dev": 3, "test": 3}


def test_an_item_without_a_stratum_field_falls_back_to_its_category(tmp_path: Path) -> None:
    raw = {"plants": [_entry(f"x-{i}", "detail") for i in range(4)], "abstains": []}
    halves = bundle_split.split_with_seeds(raw, {"detail": 5})
    assert sorted(halves.values()) == ["dev", "dev", "test", "test"]


def test_a_stratum_missing_from_the_seed_file_is_refused(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, {"a": STORY}, [], seeds={"a": {"secret:early": 1, "secret:main": 2}})
    with pytest.raises(SystemExit, match="detail"):
        bundle_split.plan_bundle(cfg)


def test_a_seed_for_a_stratum_the_plants_do_not_have_is_refused(tmp_path: Path) -> None:
    seeds = {"a": {"secret:early": 1, "secret:main": 2, "detail": 3, "relation": 4}}
    with pytest.raises(SystemExit, match="relation"):
        bundle_split.plan_bundle(_write_config(tmp_path, {"a": STORY}, [], seeds=seeds))


def test_an_odd_stratum_is_refused_because_its_halves_would_differ_by_one(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="홀수"):
        bundle_split.plan_bundle(_write_config(tmp_path, {"a": {"detail": 5}}, []))


def test_totals_add_test_items_across_the_named_works_and_categories(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, {"a": STORY, "b": STORY}, TOTALS)
    plan = bundle_split.plan_bundle(cfg)
    by_name = {t["name"]: t for t in plan["totals"]}
    assert by_name["비밀"]["test"] == 10 and by_name["비밀"]["ok"]
    assert by_name["디테일"]["test"] == 10 and by_name["디테일"]["ok"]
    assert plan["ok"]


def test_one_item_below_a_floor_fails_that_total_by_name(tmp_path: Path) -> None:
    totals = [dict(TOTALS[0], min=11), TOTALS[1]]
    plan = bundle_split.plan_bundle(_write_config(tmp_path, {"a": STORY, "b": STORY}, totals))
    assert not plan["ok"]
    assert [t["name"] for t in plan["totals"] if not t["ok"]] == ["비밀"]


def test_a_failed_total_writes_no_split_file_for_any_work(tmp_path: Path) -> None:
    totals = [dict(TOTALS[0], min=11)]
    cfg = _write_config(tmp_path, {"a": STORY, "b": STORY}, totals)
    result = bundle_split.write_bundle(cfg, tmp_path / "split")
    assert not result["ok"]
    assert not (tmp_path / "split").exists()


def test_written_split_is_readable_by_the_dev_view_and_hides_test_items(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, {"a": STORY, "b": STORY}, TOTALS)
    result = bundle_split.write_bundle(cfg, tmp_path / "split")
    assert result["ok"]
    manifest = json.loads((tmp_path / "split" / "a" / holdout.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["strataSeeds"] == {"secret:early": 1000, "secret:main": 1001, "detail": 1002}
    view = holdout.load_view(
        tmp_path / "plants-a.json", tmp_path / "split" / "a", {"dev"}, preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=None
    )
    test_ids = json.loads((tmp_path / "split" / "a" / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))
    assert len(view.plants) == 10 and len(test_ids) == 10
    with pytest.raises(SystemExit, match="봉인"):
        view.item(test_ids[0])


def test_existing_split_files_are_never_overwritten(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, {"a": STORY, "b": STORY}, TOTALS)
    (tmp_path / "split" / "b").mkdir(parents=True)
    (tmp_path / "split" / "b" / holdout.TEST_IDS_FILE).write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="이미 있다"):
        bundle_split.write_bundle(cfg, tmp_path / "split")
    assert not (tmp_path / "split" / "a").exists()


def test_dry_run_prints_counts_and_totals_only_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    cfg = _write_config(tmp_path, {"a": STORY, "b": STORY}, TOTALS)
    assert main(["--run", str(tmp_path), "split-bundle", "--config", str(cfg), "--dry-run"]) == 0
    out = capsys.readouterr().out
    printed = json.loads(out)
    assert set(printed) == {"counts", "totals"}
    assert "질문" not in out and "정답" not in out and "a-secret" not in out
    assert not (tmp_path / "split").exists()


def test_cli_exits_one_when_a_total_fails(tmp_path: Path) -> None:
    from memory_eval_cli import main

    cfg = _write_config(tmp_path, {"a": STORY, "b": STORY}, [dict(TOTALS[0], min=11)])
    assert main(["--run", str(tmp_path), "split-bundle", "--config", str(cfg)]) == 1
    assert not (tmp_path / "split").exists()
