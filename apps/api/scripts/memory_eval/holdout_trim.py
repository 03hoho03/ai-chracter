"""분할 뒤 시험 쪽에서 뺄 문항 id 목록 — 심기 표와 분할 파일은 고치지 않고 목록 파일 하나만 만든다.

빼는 이유는 둘이다.

- 질문 꼴 빼기: 개발 절반에서 응답 회피(`unaddressed`)가 많았던 질문 꼴을 시험 쪽에서 버린다. 시험 문항을 보지 않고 꼴 표지
  (`askForm`)로만 고른다. 꼴별 회피 비율은 거짓 전제 범주에서만 재므로 거짓 전제 문항에만 적용한다 — 꼴 칸이 없는 다른 범주
  문항은 기본 꼴로 읽히지만 그 비율을 잰 적이 없어 빼지 않는다.
- 축소: 관문 범주는 꼴 빼기가 한 번 걸려도 하한 밑으로 떨어지지 않게 여유를 두고 심는다. 여유가 그대로 시험에 남으면 본 측정
  원가가 그만큼 늘어나므로, 시드 파일의 `shrinkSeed` 로 시험 문항을 작품을 넘는 합계 하한(`totals`)에 여유를 더한 목표
  (`shrink_target`)까지 줄인다. 같은 작품·같은
  층에서 두 개씩 빼 층의 홀짝을 바꾸지 않고(꼴마다 반씩 나눈 층이 짝으로 줄어든다), 남은 수가 가장 많은 층부터 뺀다(같으면 시드로
  섞은 순서). 한 문항이 둘 이상의 합계에 들면 어느 합계도 목표 밑으로 내려가지 않을 때만 뺀다. 목표와 차이가 홀수면 목표보다 하나
  많이 남는다. 꼴 빼기 뒤 이미 하한 밑인 합계는 줄이지 않고 미달로 알린다(대본을 더 쓸지 관찰 범주로 돌릴지는 사람이 정한다).

둘 다 시드 파일의 sha256 이 실행자가 준 값과 같고, 분할 매니페스트가 그 시드 파일로 나뉜 것일 때만 돈다. 목록 파일 꼴:

    {"drop": ["<id>", ...], "forms": ["<꼴>", ...], "shrinkSeed": 정수 | null, "seedFileSha256": "<sha>"}

시험 보기는 `drop` 칸만 읽는다(`holdout.load_view`). 목록 파일의 sha256 은 봉인 문서 머리에 적는다(`seal`)."""

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from memory_eval import bundle_split, holdout
from memory_eval.b1.plants_tool import ASK_FORMS, DEFAULT_ASK_FORM
from memory_eval.seal import TEST_DROP_HEADER

SEAL_HEADER_KEY = TEST_DROP_HEADER
# 축소 대상 — 안전 관문이 세는 범주만 줄인다. 다른 범주의 합계 하한은 확인만 한다.
GATE_CATEGORIES = frozenset({"secret", "false_premise"})
# 꼴 빼기를 적용하는 범주 — 꼴별 회피 비율을 잰 범주.
FORM_DROP_CATEGORIES = frozenset({"false_premise"})
# 축소 목표 = 하한 × (1 + 이 비율), 올림. 하한까지 딱 줄이면 본 측정에서 응답 하나가 측정 불능이 되거나 빠지기만 해도 표본이
# 하한 밑이라 측정이 멈춘다 — 한두 건을 견딜 여유를 남긴다. 정수 셈으로 올린다(1.1 의 부동소수 곱은 10 × 1.1 을 11 보다 크게 본다).
SHRINK_MARGIN_PERCENT = 10
SHRINK_SEED_KEY = "shrinkSeed"


def _test_items(
    config: dict[str, Any], config_path: Path, split_root: Path, seed_sha: str
) -> dict[str, dict[str, Any]]:
    """작품마다 시험 id → 심기 표 항목(범주·층·꼴만 쓴다)."""
    out: dict[str, dict[str, Any]] = {}
    for work, spec in config["works"].items():
        manifest = json.loads((split_root / work / holdout.MANIFEST_FILE).read_text(encoding="utf-8"))
        if manifest.get("seedFileSha256") != seed_sha:
            raise SystemExit(f"{work} 분할이 분할 때와 다른 시드 파일로 나뉘었다(시드 파일이 분할 뒤 바뀌었다)")
        plants_path = config_path.parent / spec["plants"]
        if holdout.sha256_file(plants_path) != manifest["plantsSha256"]:
            raise SystemExit(f"{work} 심기 표가 분할 때와 다르다")
        raw = json.loads(plants_path.read_text(encoding="utf-8"))
        by_id = {str(e["id"]): e for e in list(raw.get("plants", [])) + list(raw.get("abstains", []))}
        test_ids = json.loads((split_root / work / holdout.TEST_IDS_FILE).read_text(encoding="utf-8"))
        out[work] = {str(i): by_id[str(i)] for i in test_ids}
    return out


def _rule_members(rule: dict[str, Any], tests: dict[str, dict[str, Any]], dropped: set[str]) -> list[tuple[str, str]]:
    return [
        (work, item)
        for work in rule["works"]
        for item, entry in tests[work].items()
        if item not in dropped and entry["category"] in rule["categories"]
    ]


def _totals(config: dict[str, Any], tests: dict[str, dict[str, Any]], dropped: set[str]) -> list[dict[str, Any]]:
    out = []
    for rule in config.get("totals", []):
        n = len(_rule_members(rule, tests, dropped))
        out.append({"name": rule["name"], "test": n, "min": int(rule["min"]), "ok": n >= int(rule["min"])})
    return out


def shrink_target(floor: int) -> int:
    return -(-floor * (100 + SHRINK_MARGIN_PERCENT) // 100)


def _floor(rule: dict[str, Any]) -> int:
    """축소가 지키는 합계 바닥 — 줄이는 관문 범주 합계는 여유를 더한 목표, 그 밖의 합계는 하한."""
    floor = int(rule["min"])
    return shrink_target(floor) if set(rule["categories"]) <= GATE_CATEGORIES else floor


def _shrink(config: dict[str, Any], tests: dict[str, dict[str, Any]], dropped: set[str], seed: int) -> list[str]:
    rng = random.Random(seed)
    rules = [r for r in config.get("totals", []) if set(r["categories"]) <= GATE_CATEGORIES]
    cut: list[str] = []
    for rule in rules:
        groups: dict[tuple[str, str], list[str]] = {}
        for work, item in _rule_members(rule, tests, dropped):
            groups.setdefault((work, bundle_split.stratum_of(tests[work][item])), []).append(item)
        order = sorted(groups)
        rng.shuffle(order)
        while True:
            fits = [
                key
                for key in order
                if len(groups[key]) >= 2
                and all(
                    len(_rule_members(other, tests, dropped)) - 2 >= _floor(other)
                    for other in config.get("totals", [])
                    if key[0] in other["works"] and tests[key[0]][groups[key][0]]["category"] in other["categories"]
                )
            ]
            if not fits:
                break
            key = max(fits, key=lambda k: len(groups[k]))
            pair = rng.sample(sorted(groups[key]), 2)
            for item in pair:
                groups[key].remove(item)
                dropped.add(item)
                cut.append(item)
    return cut


def build_drop(config_path: Path, split_root: Path, *, seed_sha: str, forms: list[str], shrink: bool) -> dict[str, Any]:
    """빼기 목록과 이유별 개수·뺀 뒤 합계. 파일은 쓰지 않는다."""
    bundle_split.require_seed_sha(config_path, seed_sha)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    unknown = sorted(set(forms) - ASK_FORMS)
    if unknown:
        raise SystemExit(f"모르는 질문 꼴: {unknown}")
    if shrink and SHRINK_SEED_KEY not in config:
        raise SystemExit(f"시드 파일에 {SHRINK_SEED_KEY} 가 없다 — 축소 시드를 결과 전에 시드 파일에 고정해야 줄인다")
    tests = _test_items(config, config_path, split_root, seed_sha)
    form_drop = sorted(
        item
        for entries in tests.values()
        for item, entry in entries.items()
        if entry["category"] in FORM_DROP_CATEGORIES and entry.get("askForm", DEFAULT_ASK_FORM) in set(forms)
    )
    category = {item: str(entry["category"]) for entries in tests.values() for item, entry in entries.items()}
    dropped = set(form_drop)
    shrink_seed = int(config[SHRINK_SEED_KEY]) if shrink else None
    shrunk = _shrink(config, tests, dropped, shrink_seed) if shrink_seed is not None else []
    return {
        "drop": sorted(dropped),
        "byReason": {"form": len(form_drop), "shrink": len(shrunk)},
        "byCategory": {
            "form": dict(sorted(Counter(category[i] for i in form_drop).items())),
            "shrink": dict(sorted(Counter(category[i] for i in shrunk).items())),
        },
        "forms": sorted(forms),
        "shrinkSeed": shrink_seed,
        "seedFileSha256": seed_sha,
        "totals": _totals(config, tests, dropped),
    }


def write_drop(path: Path, result: dict[str, Any]) -> str:
    """목록 파일을 쓰고 그 sha256 을 돌려준다(봉인 문서 머리에 적을 값)."""
    body = {key: result[key] for key in (holdout.DROP_KEY, "forms", "shrinkSeed", "seedFileSha256")}
    data = (json.dumps(body, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()
