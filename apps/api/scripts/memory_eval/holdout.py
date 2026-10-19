"""2차 형식 심기 표의 개발/시험 분할과, 하네스가 심기 표를 읽을 때 쓰는 보기.

2차 형식은 항목에 분할 칸이 없다. `split` 명령이 한 번만 계산해 분할 폴더에 쓴다: 층(범주)마다 id 를 문자열 순으로 정렬하고
`random.Random(SPLIT_SEED + 층 이름 해시)` 로 섞어 앞 ceil(n/2) 개를 개발, 나머지를 시험으로 보낸다(층마다 새 난수기라 층 처리
순서가 결과를 바꾸지 않는다). 층마다 같은 시드를 쓰면 크기가 같은 층은 정렬 순 같은 자리가 모두 같은 절반으로 가서, id 번호
순서가 심은 순서를 따라가면 그 쏠림이 층을 넘어 한쪽 절반에 모인다 — 층 이름 해시를 더해 층마다 다른 순열을 쓴다. 쓰는 파일:

- `dev-ids.json`·`test-ids.json`: id 목록만.
- `test-keys.json`: 시험 항목 전체(질문·정답 키·기대 사실 같은 정답 정보를 포함한 항목 그대로).
- `split-manifest.json`: 시드, 심기 표 sha256, `test-keys.json` sha256, 범주별 개수.

이미 분할 파일이 하나라도 있으면 덮어쓰지 않는다 — 분할을 다시 하면 이미 본 개발 결과가 다른 문항 집합 위에 서게 된다.
시험 절반의 주 지표 문항 수가 `TEST_PRIMARY_MIN` 보다 적으면 쓰지 않고 거부한다(짝 비교의 표본이 모자라다).

보기: 개발 보기(기본)는 심기 표에서 개발 id 만 남기고, 시험 id 는 숨김으로 둔다(찾으면 없는 문항이 아니라 거부로 알린다).
시험 절반을 담는 보기는 봉인 확인을 지난 뒤에만 `test-keys.json` 을 열고, 시험 항목은 심기 표가 아니라 그 파일에서 가져온다
(분할 때 기록한 sha256 과 같아야 한다). 어느 보기든 심기 표가 분할 때와 달라졌으면 거부한다.

항목은 1차 하네스 칸으로도 읽히게 옮긴다(`harness_entry`) — 프로브·오프라인 회상·채점·출처 귀속이 같은 코드로 돈다."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from memory_eval.metrics import stratified_split
from memory_eval.plants import PlantSet
from memory_eval.seal import require_seal

SPLIT_SEED = 20261014
SPLIT_DIR = "split"
DEV_IDS_FILE = "dev-ids.json"
TEST_IDS_FILE = "test-ids.json"
TEST_KEYS_FILE = "test-keys.json"
MANIFEST_FILE = "split-manifest.json"
SPLIT_FILES = (DEV_IDS_FILE, TEST_IDS_FILE, TEST_KEYS_FILE, MANIFEST_FILE)
# 시험 절반의 주 지표 문항 수 하한.
TEST_PRIMARY_MIN = 24
ABSTAIN_CATEGORY = "abstain"
# 심기 표는 반증된 사실을 `refuted` 로 적는다. 행·운영 스키마의 표기는 `disproved` 라 하네스 입구인 여기서 한 번만 바꾸고,
# 나머지 코드는 `disproved` 만 쓴다.
_TRUTH_STATUS_ALIASES = {"refuted": "disproved"}
# 체크포인트 직전 30턴은 아직 접히지 않았을 수 있는 원문 창이다(첫 접기 30턴, 그 뒤 10턴씩 접어 원문은 20~30턴 남는다).
# 심은 턴이 모두 이보다 앞이어야 그 체크포인트에서 장면·사실이 접힌 뒤라 오프라인 지표의 대상이 된다.
RAW_WINDOW_TURNS = 30


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_v2(raw: Mapping[str, Any]) -> bool:
    """2차 형식인가 — 묻는 체크포인트가 항목 칸(`ask_checkpoints`)에 있다."""
    return any("ask_checkpoints" in entry for entry in list(raw.get("plants", [])) + list(raw.get("abstains", [])))


def _entries(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(raw.get("plants", [])) + list(raw.get("abstains", []))


def stratum_seed(seed: int, stratum: str) -> int:
    """층의 난수기 시드: 분할 시드 + 층 이름 sha256 앞 8바이트(파이썬 `hash` 는 프로세스마다 달라 쓰지 않는다)."""
    return seed + int.from_bytes(hashlib.sha256(stratum.encode("utf-8")).digest()[:8], "big")


def compute_split(raw: Mapping[str, Any], *, seed: int = SPLIT_SEED) -> dict[str, str]:
    strata: dict[str, list[str]] = {}
    for entry in _entries(raw):
        strata.setdefault(str(entry["category"]), []).append(str(entry["id"]))
    halves: dict[str, str] = {}
    for name, ids in strata.items():
        halves.update(stratified_split({name: ids}, stratum_seed(seed, name)))
    return halves


def split_counts(raw: Mapping[str, Any], halves: Mapping[str, str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for entry in _entries(raw):
        row = counts.setdefault(str(entry["category"]), {"dev": 0, "test": 0})
        row[halves[str(entry["id"])]] += 1
    return dict(sorted(counts.items()))


def count_test_primary(raw: Mapping[str, Any], halves: Mapping[str, str]) -> int:
    return sum(1 for e in _entries(raw) if e.get("primary") is True and halves[str(e["id"])] == "test")


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def write_split(plants_path: Path, out_dir: Path, *, seed: int = SPLIT_SEED) -> dict[str, Any]:
    """분할을 계산해 쓴다. 돌려주는 값은 범주별 개수·시험 주 지표 수·`test-keys.json` sha256 뿐이다 — 항목 내용은 담지
    않는다(표준출력에 찍는 것이 이것뿐이게). 주 지표가 모자라면 아무 파일도 쓰지 않고 `ok=False` 를 돌려준다."""
    existing = [name for name in SPLIT_FILES if (out_dir / name).exists()]
    if existing:
        raise SystemExit(f"분할 파일이 이미 있다(덮어쓰지 않는다): {existing}")
    raw = json.loads(plants_path.read_text(encoding="utf-8"))
    if not is_v2(raw):
        raise SystemExit("분할 명령은 2차 형식 심기 표만 받는다(1차 형식은 항목에 분할이 있다)")
    halves = compute_split(raw, seed=seed)
    counts = split_counts(raw, halves)
    primary = count_test_primary(raw, halves)
    if primary < TEST_PRIMARY_MIN:
        return {"ok": False, "counts": counts, "testPrimary": primary, "testKeysSha256": None}
    order = [str(e["id"]) for e in _entries(raw)]
    test_items = [e for e in _entries(raw) if halves[str(e["id"])] == "test"]
    keys_bytes = _dump({"seed": seed, "items": test_items})
    keys_sha = hashlib.sha256(keys_bytes).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / DEV_IDS_FILE).write_bytes(_dump([i for i in order if halves[i] == "dev"]))
    (out_dir / TEST_IDS_FILE).write_bytes(_dump([i for i in order if halves[i] == "test"]))
    (out_dir / TEST_KEYS_FILE).write_bytes(keys_bytes)
    manifest = {
        "seed": seed,
        "plantsSha256": sha256_file(plants_path),
        "testKeysSha256": keys_sha,
        "counts": counts,
        "testPrimary": primary,
    }
    (out_dir / MANIFEST_FILE).write_bytes(_dump(manifest))
    return {"ok": True, "counts": counts, "testPrimary": primary, "testKeysSha256": keys_sha}


def harness_entry(entry: Mapping[str, Any], half: str, checkpoints: Iterable[int]) -> dict[str, Any]:
    """2차 항목에 1차 하네스가 읽는 칸을 덧붙인다(원래 칸은 그대로 둔다).

    - `split`: 분할 파일의 절반.
    - `plantTurns`·`plantTurn`: 심는 턴 전부와 마지막 턴(장면이 접혔는지는 마지막 심기로 본다).
    - `speaker`: 마지막 심기 사건의 줄·말한 쪽·추출 기대 귀속.
    - `probeCheckpoints`: Opus 는 `ask_checkpoints`, 오프라인은 심기가 모두 접힌 체크포인트(기권은 묻는 체크포인트 그대로).
    - `answerKeys`: 정답 묶음(`answer_key.bundles`, 없으면 빈 목록 — 판정자 문항).
    - `expectedAnswer`: 판정자가 읽는 성공 기준 문장(기권은 질문에 섞인 실제 장면).
    - `expected_fact` 와 그 `superseded` 행의 진실 상태 `refuted` → `disproved`."""
    out = dict(entry)
    if entry.get("expected_fact"):
        out["expected_fact"] = _normalize_fact(entry["expected_fact"])
    out["split"] = half
    turns = sorted(int(t) for t in entry.get("plant_turns") or [])
    if turns:
        out["plantTurns"] = turns
        out["plantTurn"] = turns[-1]
    events = list(entry.get("plants") or [])
    if events:
        last = events[-1]
        out["speaker"] = {"line": last.get("line"), "who": last.get("who"), "assertedBy": last.get("assertedBy")}
    ask = [int(c) for c in entry.get("ask_checkpoints") or []]
    abstain = entry.get("category") == ABSTAIN_CATEGORY
    offline = ask if abstain else [int(cp) for cp in checkpoints if turns and turns[-1] <= int(cp) - RAW_WINDOW_TURNS]
    out["probeCheckpoints"] = {"opus": ask, "offline": offline}
    answer_key = entry.get("answer_key") or {}
    out["answerKeys"] = [list(b) for b in answer_key.get("bundles") or []]
    out["expectedAnswer"] = answer_key.get("fact") if abstain else answer_key.get("correct")
    return out


def _status(value: Any) -> Any:
    return _TRUTH_STATUS_ALIASES.get(value, value) if isinstance(value, str) else value


def _normalize_fact(fact: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(fact)
    if "truth_status" in out:
        out["truth_status"] = _status(out["truth_status"])
    if isinstance(out.get("superseded"), list):
        out["superseded"] = [
            {**row, "truth_status": _status(row.get("truth_status"))} if isinstance(row, Mapping) else row
            for row in out["superseded"]
        ]
    return out


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"분할 파일이 없다 — split 명령을 먼저 돌린다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_view(
    plants_path: Path,
    split_dir: Path,
    splits: set[str],
    *,
    preregistration: Path,
    seal_sha: str | None,
) -> PlantSet:
    unknown = splits - {"dev", "test"}
    if unknown or not splits:
        raise SystemExit(f"절반은 dev·test 중에서 고른다: {sorted(splits)}")
    raw = json.loads(plants_path.read_text(encoding="utf-8"))
    manifest = _read_json(split_dir / MANIFEST_FILE)
    if sha256_file(plants_path) != manifest["plantsSha256"]:
        raise SystemExit("심기 표가 분할 때와 다르다 — 분할을 새로 해야 한다(지금 분할로는 읽지 않는다)")
    dev_ids = {str(i) for i in _read_json(split_dir / DEV_IDS_FILE)}
    test_ids = {str(i) for i in _read_json(split_dir / TEST_IDS_FILE)}
    chosen: dict[str, tuple[Mapping[str, Any], str]] = {}
    if "dev" in splits:
        chosen.update({str(e["id"]): (e, "dev") for e in _entries(raw) if str(e["id"]) in dev_ids})
    if "test" in splits:
        require_seal({"test"}, preregistration, seal_sha=seal_sha)
        keys_path = split_dir / TEST_KEYS_FILE
        if sha256_file(keys_path) != manifest["testKeysSha256"]:
            raise SystemExit("시험 정답 파일이 분할 때 기록한 sha256 과 다르다")
        items = _read_json(keys_path)["items"]
        if {str(e["id"]) for e in items} != test_ids:
            raise SystemExit("시험 정답 파일의 문항이 시험 id 목록과 다르다")
        chosen.update({str(e["id"]): (e, "test") for e in items})
    checkpoints = [int(c) for c in raw.get("checkpoints", [])]
    plants: list[dict[str, Any]] = []
    abstains: list[dict[str, Any]] = []
    for item_id in (str(e["id"]) for e in _entries(raw)):
        if item_id not in chosen:
            continue
        entry, half = chosen[item_id]
        target = abstains if entry.get("category") == ABSTAIN_CATEGORY else plants
        target.append(harness_entry(entry, half, checkpoints))
    head = {k: v for k, v in raw.items() if k not in ("plants", "abstains")}
    head["seed"] = int(manifest["seed"])
    hidden = frozenset() if "test" in splits else frozenset(test_ids)
    return PlantSet(raw=head, plants=plants, abstains=abstains, hidden=hidden)
