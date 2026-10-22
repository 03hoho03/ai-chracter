"""시험 문항 빼기 — 분할 뒤 시험 쪽에서 문항을 빼는 일은 심기 표를 고치지 않고 id 목록 파일 하나로만 하고, 그 파일의 sha256 을
봉인 문서 머리에 적어 둔 것과 맞아야 시험 보기가 열린다. 빼는 이유는 둘이다: 개발 절반에서 응답 회피가 많았던 질문 꼴을 시험
쪽에서 꼴 표지로만 거르는 것과, 심기 여유로 늘어난 관문 범주 시험 문항을 고정 시드로 하한까지 줄이는 것. 분할과 축소는 시드
파일의 sha256 이 실행자가 준 값과 같을 때만 돈다. 값은 모두 지어낸 것이다."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from memory_eval import bundle_split, holdout, holdout_trim
from memory_eval.seal import PREREGISTRATION_FILE, SEALED_EDITION


def _entry(item_id: str, category: str, stratum: str, form: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": item_id,
        "category": category,
        "stratum": stratum,
        "primary": category in ("secret", "false_premise"),
        "ask_checkpoints": [300],
        "question": f"질문 {item_id}",
        "answer_key": {"mode": "judge", "correct": f"정답 문장 {item_id}"},
    }
    if form is not None:
        entry["askForm"] = form
    return entry


# 거짓 전제는 두 꼴을 층으로 반씩, 비밀은 한 층, 디테일은 관문 밖.
WORK = {
    "false_premise:premise_followup": ("false_premise", "premise_followup", 8),
    "false_premise:closed_confirm": ("false_premise", "closed_confirm", 8),
    "secret:main": ("secret", None, 8),
    "detail": ("detail", None, 4),
}
TOTALS = [
    {"name": "거짓 전제", "works": ["a", "b"], "categories": ["false_premise"], "min": 10},
    {"name": "비밀", "works": ["a", "b"], "categories": ["secret"], "min": 5},
]


def _write_bundle(
    tmp_path: Path,
    *,
    shrink_seed: int | None = 99,
    work: dict[str, tuple[str, str | None, int]] = WORK,
    totals: list[dict[str, Any]] = TOTALS,
) -> tuple[Path, str]:
    works: dict[str, Any] = {}
    for name in ("a", "b"):
        plants = [
            _entry(f"{name}-{stratum}-{i:02d}", category, stratum, form)
            for stratum, (category, form, n) in work.items()
            for i in range(n)
        ]
        path = tmp_path / f"plants-{name}.json"
        path.write_text(json.dumps({"checkpoints": [100, 300], "plants": plants, "abstains": []}), encoding="utf-8")
        works[name] = {"plants": path.name, "strata": {s: 500 + k for k, s in enumerate(work)}}
    config: dict[str, Any] = {"base": 7, "works": works, "totals": totals}
    if shrink_seed is not None:
        config["shrinkSeed"] = shrink_seed
    cfg = tmp_path / "split-seeds.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return cfg, hashlib.sha256(cfg.read_bytes()).hexdigest()


def _split(tmp_path: Path) -> tuple[Path, str, Path]:
    cfg, sha = _write_bundle(tmp_path)
    assert bundle_split.write_bundle(cfg, tmp_path / "split", seed_sha=sha)["ok"]
    return cfg, sha, tmp_path / "split"


def _test_ids(split_root: Path, work: str) -> list[str]:
    return [str(i) for i in json.loads((split_root / work / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))]


def _seal(run: Path, *, drop_sha: str | None) -> str:
    doc = run / PREREGISTRATION_FILE
    head = f"# 사전 등록 ({SEALED_EDITION})\n"
    if drop_sha is not None:
        head += f"{holdout_trim.SEAL_HEADER_KEY} {drop_sha}\n"
    doc.write_text(head + "\n본문\n", encoding="utf-8")
    sha = hashlib.sha256(doc.read_bytes()).hexdigest()
    doc.with_suffix(".sha256").write_text(f"{sha}  {PREREGISTRATION_FILE}\n", encoding="utf-8")
    return sha


def _write_drop(tmp_path: Path, ids: list[str]) -> tuple[Path, str]:
    path = tmp_path / "test-drop.json"
    path.write_text(json.dumps({"drop": ids}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 시드 sha


def test_the_split_is_refused_when_the_seed_file_differs_from_the_sha_the_runner_gives(tmp_path: Path) -> None:
    cfg, _ = _write_bundle(tmp_path)
    with pytest.raises(SystemExit, match="sha256"):
        bundle_split.write_bundle(cfg, tmp_path / "split", seed_sha="0" * 64)
    assert not (tmp_path / "split").exists()


def test_the_split_command_needs_the_seed_sha_and_checks_it_on_a_dry_run_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    cfg, sha = _write_bundle(tmp_path)
    base = ["--run", str(tmp_path), "split-bundle", "--config", str(cfg)]
    with pytest.raises(SystemExit):
        main([*base, "--dry-run"])
    capsys.readouterr()
    assert main([*base, "--dry-run", "--seed-sha", "f" * 64]) == 2
    assert "sha256" in capsys.readouterr().err
    assert main([*base, "--seed-sha", "f" * 64]) == 2
    assert not (tmp_path / "split").exists()
    assert main([*base, "--dry-run", "--seed-sha", sha]) == 0
    assert main([*base, "--seed-sha", sha]) == 0
    assert (tmp_path / "split" / "a" / holdout.MANIFEST_FILE).exists()


# ---------------------------------------------------------------- 빼기 목록 만들기


def test_dropping_a_form_lists_only_test_items_of_that_form(tmp_path: Path) -> None:
    cfg, sha, split_root = _split(tmp_path)
    out = holdout_trim.build_drop(cfg, split_root, seed_sha=sha, forms=["closed_confirm"], shrink=False)
    test = set(_test_ids(split_root, "a")) | set(_test_ids(split_root, "b"))
    assert out["drop"] and set(out["drop"]) <= test
    assert all("closed_confirm" in i for i in out["drop"])
    assert len(out["drop"]) == 8


def test_dropping_the_plain_form_takes_only_plain_false_premise_items_and_counts_them_by_category(
    tmp_path: Path,
) -> None:
    # 꼴별 회피 비율은 거짓 전제에서만 잰다 — 꼴 칸이 없는 다른 범주 문항이 기본 꼴로 함께 빠지면 안 된다.
    work = {
        "false_premise": ("false_premise", None, 4),
        "false_premise:closed_confirm": ("false_premise", "closed_confirm", 4),
        "secret:main": ("secret", None, 4),
        "relation": ("relation", None, 4),
        "detail": ("detail", None, 4),
    }
    cfg, sha = _write_bundle(tmp_path, work=work, totals=[])
    assert bundle_split.write_bundle(cfg, tmp_path / "split", seed_sha=sha)["ok"]
    out = holdout_trim.build_drop(cfg, tmp_path / "split", seed_sha=sha, forms=["plain"], shrink=False)
    assert len(out["drop"]) == 4
    assert all("-false_premise-" in i for i in out["drop"])
    assert out["byCategory"] == {"form": {"false_premise": 4}, "shrink": {}}


def test_the_shrink_target_is_the_floor_plus_ten_percent_rounded_up() -> None:
    assert [holdout_trim.shrink_target(n) for n in (5, 6, 10, 20, 21)] == [6, 7, 11, 22, 24]


def test_shrinking_stops_at_the_floor_margin_in_pairs_within_a_stratum(tmp_path: Path) -> None:
    cfg, sha, split_root = _split(tmp_path)
    out = holdout_trim.build_drop(cfg, split_root, seed_sha=sha, forms=[], shrink=True)
    test = [i for w in ("a", "b") for i in _test_ids(split_root, w)]
    left = [i for i in test if i not in set(out["drop"])]
    premise = [i for i in left if "-false_premise:" in i]
    secret = [i for i in left if "-secret:" in i]
    # 하한 10·5 에 10% 올림 여유면 목표는 11·6 — 둘씩 빼므로 거짓 전제는 16 → 12 에서 멈추고(10 은 목표 밑), 비밀은 8 → 6.
    assert (len(premise), len(secret)) == (12, 6)
    assert out["byCategory"]["shrink"] == {"false_premise": 4, "secret": 2}
    assert all("-detail-" not in i for i in out["drop"])
    cut = Counter(i.rsplit("-", 1)[0] for i in out["drop"])
    assert all(n % 2 == 0 for n in cut.values())


def test_shrinking_is_fixed_by_the_shrink_seed_and_the_seed_file_cannot_change_after_the_split(tmp_path: Path) -> None:
    cfg, sha, split_root = _split(tmp_path)
    first = holdout_trim.build_drop(cfg, split_root, seed_sha=sha, forms=[], shrink=True)["drop"]
    again = holdout_trim.build_drop(cfg, split_root, seed_sha=sha, forms=[], shrink=True)["drop"]
    assert first == again
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["shrinkSeed"] = 12345
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    other_sha = hashlib.sha256(cfg.read_bytes()).hexdigest()
    with pytest.raises(SystemExit, match="분할 때"):
        holdout_trim.build_drop(cfg, split_root, seed_sha=other_sha, forms=[], shrink=True)


def test_shrinking_after_a_form_drop_counts_the_form_drop_first(tmp_path: Path) -> None:
    cfg, sha, split_root = _split(tmp_path)
    out = holdout_trim.build_drop(cfg, split_root, seed_sha=sha, forms=["closed_confirm"], shrink=True)
    test = [i for w in ("a", "b") for i in _test_ids(split_root, w)]
    left = [i for i in test if i not in set(out["drop"])]
    # 꼴을 빼고 나니 거짓 전제가 하한 밑이라 더 줄이지 않고 합계 미달로 알린다(대본을 더 쓸지 관찰로 돌릴지는 사람이 정한다).
    assert len([i for i in left if "-false_premise:" in i]) == 8
    assert {t["name"]: t["ok"] for t in out["totals"]} == {"거짓 전제": False, "비밀": True}
    assert all("closed_confirm" not in i for i in left)
    assert len([i for i in left if "-secret:" in i]) == 6


def test_shrinking_without_a_shrink_seed_in_the_seed_file_is_refused(tmp_path: Path) -> None:
    cfg, sha = _write_bundle(tmp_path, shrink_seed=None)
    assert bundle_split.write_bundle(cfg, tmp_path / "split", seed_sha=sha)["ok"]
    with pytest.raises(SystemExit, match="shrinkSeed"):
        holdout_trim.build_drop(cfg, tmp_path / "split", seed_sha=sha, forms=[], shrink=True)


def test_building_the_drop_list_checks_the_seed_sha(tmp_path: Path) -> None:
    cfg, _, split_root = _split(tmp_path)
    with pytest.raises(SystemExit, match="sha256"):
        holdout_trim.build_drop(cfg, split_root, seed_sha="0" * 64, forms=[], shrink=True)


def test_the_drop_command_writes_the_list_and_prints_counts_and_its_sha_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    cfg, sha, split_root = _split(tmp_path)
    out = tmp_path / "drop.json"
    argv = ["--run", str(tmp_path), "test-drop", "--config", str(cfg), "--seed-sha", sha]
    assert main([*argv, "--split-root", str(split_root), "--shrink", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert hashlib.sha256(out.read_bytes()).hexdigest() in printed
    assert "질문" not in printed and "-secret:" not in printed
    assert json.loads(out.read_text(encoding="utf-8"))["drop"]


# ---------------------------------------------------------------- 봉인·시험 보기


def test_the_sealed_test_view_leaves_out_the_listed_ids_when_the_seal_header_names_the_list(tmp_path: Path) -> None:
    _, _, split_root = _split(tmp_path)
    test = _test_ids(split_root, "a")
    drop, drop_sha = _write_drop(tmp_path, test[:2])
    seal = _seal(tmp_path, drop_sha=drop_sha)
    view = holdout.load_view(
        tmp_path / "plants-a.json", split_root / "a", {"test"},
        preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=seal, test_drop=drop,
    )  # fmt: skip
    assert {e["id"] for e in view.all_items()} == set(test[2:])


def test_a_drop_list_whose_sha_is_not_in_the_seal_header_is_refused(tmp_path: Path) -> None:
    _, _, split_root = _split(tmp_path)
    drop, _ = _write_drop(tmp_path, _test_ids(split_root, "a")[:2])
    seal = _seal(tmp_path, drop_sha="0" * 64)
    with pytest.raises(SystemExit, match="봉인 문서"):
        holdout.load_view(
            tmp_path / "plants-a.json", split_root / "a", {"test"},
            preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=seal, test_drop=drop,
        )  # fmt: skip


def test_a_seal_header_that_names_a_drop_list_refuses_a_run_without_it(tmp_path: Path) -> None:
    _, _, split_root = _split(tmp_path)
    _, drop_sha = _write_drop(tmp_path, _test_ids(split_root, "a")[:2])
    seal = _seal(tmp_path, drop_sha=drop_sha)
    with pytest.raises(SystemExit, match="빼기 목록"):
        holdout.load_view(
            tmp_path / "plants-a.json", split_root / "a", {"test"},
            preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=seal,
        )  # fmt: skip


def test_a_drop_list_given_to_a_seal_without_one_in_its_header_is_refused(tmp_path: Path) -> None:
    _, _, split_root = _split(tmp_path)
    drop, _ = _write_drop(tmp_path, _test_ids(split_root, "a")[:2])
    seal = _seal(tmp_path, drop_sha=None)
    with pytest.raises(SystemExit, match="봉인 문서"):
        holdout.load_view(
            tmp_path / "plants-a.json", split_root / "a", {"test"},
            preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=seal, test_drop=drop,
        )  # fmt: skip


def test_a_drop_list_naming_a_dev_item_is_refused(tmp_path: Path) -> None:
    _, _, split_root = _split(tmp_path)
    dev = json.loads((split_root / "a" / holdout.DEV_IDS_FILE).read_text(encoding="utf-8"))
    drop, drop_sha = _write_drop(tmp_path, [dev[0]])
    seal = _seal(tmp_path, drop_sha=drop_sha)
    with pytest.raises(SystemExit, match="개발"):
        holdout.load_view(
            tmp_path / "plants-a.json", split_root / "a", {"dev", "test"},
            preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=seal, test_drop=drop,
        )  # fmt: skip


def test_the_dev_view_ignores_the_drop_list(tmp_path: Path) -> None:
    _, _, split_root = _split(tmp_path)
    view = holdout.load_view(
        tmp_path / "plants-a.json", split_root / "a", {"dev"},
        preregistration=tmp_path / PREREGISTRATION_FILE, seal_sha=None, test_drop=tmp_path / "not-there.json",
    )  # fmt: skip
    assert view.plants
