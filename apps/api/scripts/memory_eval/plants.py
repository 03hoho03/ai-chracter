"""심기 표(`plants.json`) 읽기와 그 표에서 파생하는 것 — 체크포인트별 프로브·오프라인 문항, 분할 다시 계산.

확정 값(분할·체크포인트 배정·질문·맥락 턴 문장·정답 키)은 언제나 파일에서 읽는다. 이 모듈은 규칙을 다시 정하지 않는다 —
`recompute_split` 은 파일의 분할이 사전 등록한 층 규칙과 같은지 대조하는 용도이고, 하네스의 집계는 파일의 `split` 만 쓴다."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_eval.metrics import stratified_split

# 짝 비교의 대상 범주(화자 귀속은 판정자 지표로 따로 본다).
TARGET_CATEGORIES = ("물건", "장소", "시점", "약속")


@dataclass(frozen=True)
class PlantSet:
    raw: dict[str, Any]
    plants: list[dict[str, Any]]
    abstains: list[dict[str, Any]]
    # 이 보기에서 일부러 뺀 문항 id(봉인 확인 없이 연 개발 보기의 시험 문항). 찾으면 없는 문항이 아니라 거부로 알린다.
    hidden: frozenset[str] = field(default_factory=frozenset)

    def item(self, item_id: str) -> dict[str, Any]:
        for entry in self.plants + self.abstains:
            if entry["id"] == item_id:
                return entry
        if item_id in self.hidden:
            raise SystemExit(f"시험 문항 {item_id} 은 봉인 확인을 지난 시험 모드에서만 연다")
        raise KeyError(item_id)

    def all_items(self) -> list[dict[str, Any]]:
        return self.plants + self.abstains


@dataclass(frozen=True)
class Probe:
    """Opus 프로브 하나. `turns` 는 보낼 사용자 문장 순서다 — 대명사 문항은 맥락 턴 문장이 먼저, 질문이 나중."""

    item_id: str
    checkpoint: int
    turns: list[str]
    kind: str  # plant · abstain
    split: str

    @property
    def two_turn(self) -> bool:
        return len(self.turns) == 2


def load_plants(path: Path) -> PlantSet:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return PlantSet(raw=raw, plants=list(raw["plants"]), abstains=list(raw.get("abstains", [])))


def checkpoints(plant_set: PlantSet) -> list[int]:
    return [int(t) for t in plant_set.raw.get("checkpoints", [50, 100, 300])]


def plant_turns(plant: dict[str, Any]) -> list[int]:
    turns = plant.get("plantTurns") or [plant["plantTurn"]]
    return [int(t) for t in turns]


def _probe_turns(entry: dict[str, Any]) -> list[str]:
    context = entry.get("contextTurn")
    if entry.get("questionForm") == "anaphora" and context:
        return [str(context["userLine"]), str(entry["question"])]
    return [str(entry["question"])]


def opus_probes(plant_set: PlantSet, checkpoint: int) -> list[Probe]:
    """그 체크포인트의 Opus 프로브, 심은 항목 다음 기권 순(파일 순서)."""
    probes: list[Probe] = []
    for kind, entries in (("plant", plant_set.plants), ("abstain", plant_set.abstains)):
        for entry in entries:
            if checkpoint in entry["probeCheckpoints"].get("opus", []):
                probes.append(
                    Probe(
                        item_id=entry["id"],
                        checkpoint=checkpoint,
                        turns=_probe_turns(entry),
                        kind=kind,
                        split=str(entry.get("split", "")),
                    )
                )
    return probes


def offline_entries(plant_set: PlantSet, checkpoint: int) -> list[dict[str, Any]]:
    return [e for e in plant_set.all_items() if checkpoint in e["probeCheckpoints"].get("offline", [])]


def _stratum(entry: dict[str, Any], rule: str) -> tuple[Any, ...]:
    category = str(entry.get("category", ""))
    if category == "기권":
        return ("기권",)
    if rule == "category":
        return (category,)
    if rule == "role":
        # 대상 범주는 한 묶음으로 두고 (Opus 짝 비교 대상인가, 직접 형식 합격선 후보인가)로 나눈다. 나머지 범주는 각각 한 층.
        if category not in TARGET_CATEGORIES:
            return (category,)
        paired = bool(entry["probeCheckpoints"].get("opus"))
        passline = entry.get("questionForm") == "direct" and not (entry.get("limitProbe") or {}).get("designedToFail")
        return ("target", paired, passline)
    raise ValueError(f"모르는 층 규칙: {rule}")


def recompute_split(plant_set: PlantSet, *, rule: str, seed: int) -> dict[str, str]:
    strata: dict[tuple[Any, ...], list[str]] = {}
    for entry in plant_set.all_items():
        strata.setdefault(_stratum(entry, rule), []).append(str(entry["id"]))
    return stratified_split(strata, seed)


def split_agreement(plant_set: PlantSet, *, rule: str) -> dict[str, Any]:
    """파일의 분할과 규칙으로 다시 계산한 분할을 대조한다."""
    seed = int(plant_set.raw["seed"])
    again = recompute_split(plant_set, rule=rule, seed=seed)
    differ = sorted(i for i, half in again.items() if half != plant_set.item(i).get("split"))
    test = sorted(e["id"] for e in plant_set.all_items() if e.get("split") == "test")
    return {"rule": rule, "seed": seed, "agrees": not differ, "differ": differ, "fileTest": test}
