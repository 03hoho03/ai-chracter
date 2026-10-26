"""사실 주입 재측정 — 지금 운영 상태의 갈래와, 같은 상태에 사실 주입만 더 켠 갈래 두 갈래를 견준다.

갈래: 기준은 장면 회상·요약 비밀 표기·지식 범위 필터·임베딩 쓰기·임베딩 회상을 켜고 사실 주입만 끈 갈래, 비교는 거기에 사실
주입을 켠 갈래다. 둘 다 묶음 1 갈래 표(`arm_env.BUNDLE1_ARMS`)에 이미 있는 이름을 쓴다 — 새 이름을 만들면 env 표·템플릿 계열·
"실제로 돌았나" 문턱(`ran_gate`)을 따로 이어야 하고, 이으면서 한 곳을 빠뜨리면 그 갈래가 단언 없이 집계된다. 두 갈래의 env 는
사실 주입 스위치 한 줄만 다르다(테스트가 본다). 질의 임베딩 시간 상한은 프로브 인자(`--memory-embed-recall-timeout-ms`)로 두
갈래에 같은 값을 준다.

효과: 관계·정정·거짓 전제 문항의 판정자 성공을 기준 → 사실 주입 갈래로 견준다. 셈은 묶음 판정의 효과 함수(정확 단측 검정·Holm·
최소 차·표본 하한, `verdict_v4.effect_family`)와 통과 최소 불일치 표(`verdict_v4.power_table`)를 이 갈래 쌍의 표로 부른다. 효과가
하나라 Holm 가족 크기는 1 이다.

판정 유효성은 묶음 판정과 같은 장치를 쓴다(`verdict`). 판정 불능은 사실 주입 갈래면 실패, 기준 갈래면 성공으로 세므로, 불능이
한쪽에 몰리면 실제 차이 없이 기준 갈래가 나아 보인다 — 그래서 스토리 레인 표에서 한 갈래의 불능 수가 상한(행의 3%, 최소 1)을
넘으면 효과를 무효(`halt`)로 낸다. 판정자 대조군 기록이 없거나 관문 미달(사용자가 받아들인 결정 없이)이면 전체 상태가 `halt`·
`fail` 이다. 판정 줄 중복과 같은 대본을 두 번 넘긴 입력은 거부한다. 프로브 행에 질의 임베딩 시간 상한이 기록돼 있으면 두
갈래의 값이 하나여야 한다 — 다르면 사실 주입 말고 상한도 달랐던 비교라 거부한다.

관찰 칸(판정 아님, 값만 낸다 — 판정·권고에 넣지 않는다). 입력은 `filter-recompute` 출력 행의 `recordedRows`(그 질문 턴 기록에
실린 사실 행의 아는 사람·말한 쪽·글)다.
- 비밀이 공개 사실로 실림: 사실 주입 갈래의 비밀 문항 프로브 가운데, 실린 행 중 아는 사람이 정해지지 않은(`known_by` NULL) 행이
  그 비밀 내용을 담은 것(`wording_metrics.holds_secret_content` 규칙)이 있는 프로브 수. 지식 범위 필터는 아는 사람이 없는 행을 늘
  남기므로, 추출이 비밀을 공개 사실로 적었으면 필터가 막지 못한 채 실린다.
- 사용자 주장 행 실림: 사실 주입 갈래 프로브의 실린 행 가운데 말한 쪽이 사용자(`asserted_by = user`)인 행 수.
- 템플릿에 없는 실린 행 수: 턴 기록의 id 가 템플릿 행에 없다 — 기록과 템플릿이 어긋난 것이라 따로 센다."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from api.chat.memory_facts import normalize_part

from memory_eval import verdict_v4 as v4
from memory_eval.plants import PlantSet
from memory_eval.wording_metrics import holds_secret_content

CURRENT_ARM = "b1-B1E"  # cite-ok: 하네스 갈래 이름 문자열이다(결정 번호 아님)
FACTS_ARM = "b1-B2"  # cite-ok: 하네스 갈래 이름 문자열이다(결정 번호 아님)
EFFECT = "factsInject"
EFFECTS: dict[str, v4.EffectSpec] = {
    EFFECT: (CURRENT_ARM, FACTS_ARM, ("relation", "correction", v4.PREMISE_CATEGORY), "judged"),
}
# 관찰로만 내는 효과는 없다 — 하나뿐인 효과가 판정 대상이다.
OBSERVED: tuple[str, ...] = ()
USER_ASSERTED = "user"


def effects(
    groups: Sequence[Sequence[dict[str, Any]]],
    score_rows: Sequence[Mapping[str, Any]],
    judge_rows: Sequence[Mapping[str, Any]],
    *,
    floors: Mapping[str, int] | None = None,
    invalid_arms: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    return v4.effect_family(
        groups, score_rows, judge_rows, invalid_arms=invalid_arms, floors=floors, effects=EFFECTS, observed_effects=OBSERVED
    )


def effect_floors(seeds: Mapping[str, Any]) -> dict[str, int]:
    return v4.effect_floors(seeds, effects=EFFECTS)


def power_table(sizes: Mapping[str, int], *, max_c: int) -> dict[str, Any]:
    return v4.power_table(sizes, max_c=max_c, effects=EFFECTS, observed_effects=OBSERVED)


def observations(
    items: Iterable[Mapping[str, Any]], recompute_rows: Iterable[Mapping[str, Any]], *, arm: str = FACTS_ARM
) -> dict[str, int]:
    """`items` 는 심기 표 문항(비밀 범주만 본다), `recompute_rows` 는 `filter-recompute` 출력 행. 갈래 `arm` 의 행만 센다."""
    secrets = {str(e["id"]): e for e in items if e.get("category") == v4.SECRET_CATEGORY}
    out = dict.fromkeys(
        ("probes", "secretProbes", "secretLoadedAsPublicFact", "userClaimRowsLoaded", "recordedRowsNotInTemplate"), 0
    )
    for row in recompute_rows:
        if str(row.get("arm")) != arm:
            continue
        out["probes"] += 1
        recorded = list(row.get("recordedRows") or ())
        loaded = [r for r in recorded if r.get("found")]
        out["recordedRowsNotInTemplate"] += len(recorded) - len(loaded)
        out["userClaimRowsLoaded"] += sum(1 for r in loaded if r.get("assertedBy") == USER_ASSERTED)
        item = secrets.get(str(row.get("item")))
        if item is None:
            continue
        out["secretProbes"] += 1
        users = frozenset(normalize_part(str(n)) for n in row.get("userNames") or ())
        if any(r.get("knownBy") is None and holds_secret_content(r.get("text"), item, users) for r in loaded):
            out["secretLoadedAsPublicFact"] += 1
    return out


def require_same_embed_timeout(
    probe_rows: Iterable[Mapping[str, Any]], arms: Sequence[str] = (CURRENT_ARM, FACTS_ARM)
) -> dict[str, list[str]]:
    """갈래별로 프로브 행에 기록된 질의 임베딩 시간 상한 값(기록 없는 행은 건너뛴다). 두 갈래를 통틀어 값이 둘 이상이면 거부한다."""
    seen: dict[str, set[str]] = {arm: set() for arm in arms}
    for row in probe_rows:
        arm = str(row.get("arm"))
        value = row.get("embedRecallTimeoutMs")
        if arm in seen and value is not None:
            seen[arm].add(str(value))
    if len(set().union(*seen.values())) > 1:
        raise SystemExit(f"두 갈래의 질의 임베딩 시간 상한이 다르다 — 사실 주입 말고도 다른 비교다: {seen}")
    return {arm: sorted(values) for arm, values in seen.items()}


def verdict(
    story_sets: Sequence[PlantSet],
    character_sets: Sequence[PlantSet],
    score_rows: Sequence[Mapping[str, Any]],
    judge_rows: Sequence[Mapping[str, Any]],
    *,
    control_rows: Sequence[dict[str, Any]] | None,
    controls_override: Mapping[str, Any] | None = None,
    floors: Mapping[str, int] | None = None,
    split: str = "test",
) -> dict[str, Any]:
    """효과(판정 불능 상한으로 무효 처리)·대조군·전체 상태. 효과는 스토리 레인 문항으로 센다(묶음 판정과 같다)."""
    v4.require_unique_judge_rows(judge_rows)
    v4.require_distinct_scripts({"story": story_sets, "character": character_sets})
    story = [[e for e in s.all_items() if e.get("split") == split] for s in story_sets]
    if not any(story):
        raise SystemExit(f"스토리 레인에 {split} 절반 문항이 없다")
    rates = v4.unable_rates({"story": story}, judge_rows)
    invalid = frozenset(arm for arm, r in rates["story"].items() if r["exceeded"])
    out = effects(story, score_rows, judge_rows, floors=floors, invalid_arms=invalid)
    controls = v4.controls_table(control_rows, controls_override)
    # 검출력 부족으로 보류한 효과는 통과도 실패도 아니라 전체 상태에서 빠진다(묶음 판정과 같다).
    parts = [controls] if out[EFFECT]["status"] == v4.UNDERPOWERED else [out[EFFECT], controls]
    statuses = [str(part["status"]) for part in parts]
    if invalid or "halt" in statuses:
        status = "halt"
    else:
        status = "pass" if all(s == "pass" for s in statuses) else "fail"
    return {"split": split, "arms": [CURRENT_ARM, FACTS_ARM], "effects": out, "unableCeiling": rates,
            "invalid": sorted(invalid), "controls": controls, "status": status}  # fmt: skip
