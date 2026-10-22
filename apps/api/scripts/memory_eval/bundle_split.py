"""대본 셋(작품 여럿)의 심기 표를 한꺼번에 개발/시험으로 나눈다.

시드 파일(대본을 확정하기 전에 커밋한다) 꼴:

    {"base": 정수,
     "shrinkSeed": 정수,
     "works": {"<작품>": {"plants": "<시드 파일 기준 상대 경로>", "strata": {"<층>": 시드, ...}}, ...},
     "totals": [{"name": "...", "works": ["<작품>", ...], "categories": ["<범주>", ...], "min": 정수}, ...]}

- 시드 파일은 결과를 보기 전에 고정한다. 분할은 시드 파일의 sha256 이 실행자가 준 값과 같을 때만 돈다 — 커밋해 둔 시드가 아닌
  파일로 나뉘면 사전에 고정했다는 말이 거짓이 된다.
- `shrinkSeed` 는 분할 뒤 관문 범주 시험 문항을 하한까지 줄일 때 쓰는 시드다(`holdout_trim`). 분할에는 쓰지 않지만 같은 파일에
  두어 분할 시드와 함께 결과 전에 고정된다. 없으면 축소 명령이 거부한다.

- 층은 항목의 `stratum` 칸(없으면 `category`)이다. 층마다 시드 파일이 준 시드로 `stratified_split` 한다 — 층마다 따로
  적힌 시드라 한 층의 시드를 바꿔도 다른 층의 배정은 그대로다.
- 시드 파일의 층 목록과 심기 표의 층 목록이 다르면 거부한다. 빠진 층을 기본 시드로 채우거나 남는 층을 조용히 버리면,
  커밋해 둔 시드가 실제 분할을 정하지 않게 된다.
- 층 크기가 홀수면 거부한다. 개발 절반이 하나 더 가져가서 시험 수가 층 크기의 절반이 아니게 되고, 하한을 계산한 셈과 어긋난다.
- 합계 하한(`totals`)은 이름 붙인 작품들의 이름 붙인 범주에서 시험으로 간 항목 수의 합이다. 하나라도 못 채우면 어떤 작품의
  분할 파일도 쓰지 않는다 — 일부 작품만 나뉜 상태가 남으면 다시 나눌 때 이미 본 개발 결과와 문항 집합이 어긋난다.

작품마다 쓰는 파일은 2차 분할과 같은 넷(`holdout` 의 이름)이고, 매니페스트에 층별 시드를 함께 적는다. 개발·시험 보기는
`holdout.load_view` 가 그대로 읽는다. 표준출력에는 개수·합계·해시만 나간다."""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from memory_eval import holdout
from memory_eval.metrics import stratified_split


def stratum_of(entry: Mapping[str, Any]) -> str:
    return str(entry.get("stratum") or entry["category"])


def _entries(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(raw.get("plants", [])) + list(raw.get("abstains", []))


def split_with_seeds(raw: Mapping[str, Any], seeds: Mapping[str, int], *, work: str = "") -> dict[str, str]:
    strata: dict[str, list[str]] = {}
    for entry in _entries(raw):
        strata.setdefault(stratum_of(entry), []).append(str(entry["id"]))
    missing = sorted(set(strata) - set(seeds))
    extra = sorted(set(seeds) - set(strata))
    if missing or extra:
        raise SystemExit(
            f"{work} 시드 파일의 층과 심기 표의 층이 다르다 — 시드 없는 층 {missing}, 심기 표에 없는 층 {extra}"
        )
    odd = sorted(f"{name} {len(ids)}" for name, ids in strata.items() if len(ids) % 2)
    if odd:
        raise SystemExit(f"{work} 층 크기가 홀수다(시험 수가 절반이 아니게 된다): {odd}")
    halves: dict[str, str] = {}
    for name, ids in strata.items():
        halves.update(stratified_split({name: ids}, int(seeds[name])))
    return halves


def _counts(raw: Mapping[str, Any], halves: Mapping[str, str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for entry in _entries(raw):
        row = counts.setdefault(stratum_of(entry), {"dev": 0, "test": 0})
        row[halves[str(entry["id"])]] += 1
    return dict(sorted(counts.items()))


def require_seed_sha(config_path: Path, seed_sha: str) -> None:
    actual = holdout.sha256_file(config_path)
    if actual != seed_sha:
        raise SystemExit(f"시드 파일의 sha256 이 준 값과 다르다(고정한 시드 파일이 아니다): {seed_sha} ≠ {actual}")


def plan_bundle(config_path: Path) -> dict[str, Any]:
    """파일을 쓰지 않고 분할·개수·합계 판정만 계산한다."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    raws: dict[str, dict[str, Any]] = {}
    halves: dict[str, dict[str, str]] = {}
    counts: dict[str, dict[str, dict[str, int]]] = {}
    for work, spec in config["works"].items():
        raw = json.loads((config_path.parent / spec["plants"]).read_text(encoding="utf-8"))
        raws[work] = raw
        halves[work] = split_with_seeds(raw, spec["strata"], work=work)
        counts[work] = _counts(raw, halves[work])
    totals = []
    for rule in config.get("totals", []):
        test = sum(
            1
            for work in rule["works"]
            for entry in _entries(raws[work])
            if entry["category"] in rule["categories"] and halves[work][str(entry["id"])] == "test"
        )
        totals.append({"name": rule["name"], "test": test, "min": int(rule["min"]), "ok": test >= int(rule["min"])})
    return {
        "config": config,
        "raws": raws,
        "halves": halves,
        "counts": counts,
        "totals": totals,
        "ok": all(t["ok"] for t in totals),
    }


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def write_bundle(config_path: Path, out_root: Path, *, seed_sha: str) -> dict[str, Any]:
    require_seed_sha(config_path, seed_sha)
    plan = plan_bundle(config_path)
    public = {"counts": plan["counts"], "totals": plan["totals"]}
    if not plan["ok"]:
        return {**public, "ok": False, "testKeysSha256": {}}
    existing = [
        str(out_root / work / name)
        for work in plan["halves"]
        for name in holdout.SPLIT_FILES
        if (out_root / work / name).exists()
    ]
    if existing:
        raise SystemExit(f"분할 파일이 이미 있다(덮어쓰지 않는다): {existing}")
    config = plan["config"]
    shas: dict[str, str] = {}
    for work, halves in plan["halves"].items():
        raw = plan["raws"][work]
        spec = config["works"][work]
        order = [str(e["id"]) for e in _entries(raw)]
        keys_bytes = _dump(
            {"seed": int(config["base"]), "items": [e for e in _entries(raw) if halves[str(e["id"])] == "test"]}
        )
        shas[work] = hashlib.sha256(keys_bytes).hexdigest()
        out = out_root / work
        out.mkdir(parents=True, exist_ok=True)
        (out / holdout.DEV_IDS_FILE).write_bytes(_dump([i for i in order if halves[i] == "dev"]))
        (out / holdout.TEST_IDS_FILE).write_bytes(_dump([i for i in order if halves[i] == "test"]))
        (out / holdout.TEST_KEYS_FILE).write_bytes(keys_bytes)
        manifest = {
            "seed": int(config["base"]),
            "strataSeeds": {k: int(v) for k, v in spec["strata"].items()},
            "seedFileSha256": holdout.sha256_file(config_path),
            "plantsSha256": holdout.sha256_file(config_path.parent / spec["plants"]),
            "testKeysSha256": shas[work],
            "counts": plan["counts"][work],
        }
        (out / holdout.MANIFEST_FILE).write_bytes(_dump(manifest))
    return {**public, "ok": True, "testKeysSha256": shas}
