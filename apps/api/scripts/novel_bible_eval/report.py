"""보고서 — 지표마다 관측치·k/n·구간·합격선 대조를 JSON 과 마크다운으로 쓴다. 측정 실행 폴더에만 두고 커밋하지 않는다.

합격선(관측치로 판정): 핵심 사실 정밀도 ≥ 0.90, 사실 재현율 ≥ 0.70(반복 평균), 인물 지식 방향 오류 ≤ 3%(반복 평균), 차단 오탐
0건, 판정 모델과 사람의 κ ≥ 0.6. 합격 여부와 무관하게 운영에서 켜지 않는다. 합성 세트의 사실 정밀도(`precision.facts`)는 합격선
없이 싣는다 — 합격선이 있는 정밀도는 사람 라벨의 핵심 사실 정밀도다.

판정 불가(`pass` 가 null, `undetermined` 에 까닭)는 셋이다.
- 분모가 0 이다 — 어느 합격 지표든 관측치가 없다.
- 실행이 멈췄다(원장 멈춤이나 끊김) — 합성 세트의 합격 지표 모두. 설계한 표본(반복 수·탐침 수)이 다 돌지 않은 실행이다. 사람
  라벨은 추출이 멈췄거나 끊긴 어댑터의 핵심 사실 정밀도 — 앞 화 일부만 담긴 추출이다.
- 판정에 쓰지 못한 확정이 25% 를 넘는다(기본 화의 실패, 충돌·비충돌 탐침의 실패 + 정본 불완전) — 차단 지표. 그중 합격선이
  있는 것은 차단 오탐이고, 합격선이 없는 차단·경고 재현율은 `blocking.undeterminable` 로 적는다. 재현율은 실패한 화의 정답도
  분모에 두어 실패가 놓침으로 들고, 방향 오류는 실패한 화에서 짝이 생기지 않아 분자·분모가 함께 빠지므로 이 검사를 두지 않는다.
  확정 실패율은 갈래마다 차단 오탐 바로 뒤에 지표로 싣는다.

차단 오탐은 예외다 — 합격선이 0건이라, 관측된 오탐이 하나라도 있으면 표본을 더 돌려도 합격으로 뒤집히지 않는다. 그래서 오탐이
1건 이상이면 멈췄거나 판정에 쓰지 못한 확정이 25% 를 넘어도 미달로 확정한다. 오탐이 0건일 때만 위 까닭으로 판정 불가가 된다."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from novel_bible_eval import metrics
from novel_bible_eval.labels import LabeledClaim
from novel_bible_eval.metrics import Ratio
from novel_bible_eval.run import ChapterOutcome
from novel_bible_eval.spec import EvalSet

RECALL_FLOOR = {"facts": 0.70}
DIRECTION_CEILING = 0.03
CORE_PRECISION_FLOOR = 0.90
KAPPA_FLOOR = 0.6


def _entry(ratio: Ratio, *, error_rate: bool = False) -> dict[str, Any]:
    """오류율은 단측 상한, 그 밖은 Wilson 구간. 부트스트랩은 화 묶음이 있고 관측이 0·1 이 아닐 때만(한 점으로 무너진다)."""
    entry: dict[str, Any] = {"k": ratio.k, "n": ratio.n, "value": ratio.value}
    if error_rate:
        entry["upper"] = metrics.upper_bound(ratio.k, ratio.n)
    else:
        entry["wilson"] = list(metrics.wilson(ratio.k, ratio.n))
    if ratio.clusters and 0 < ratio.k < ratio.n:
        entry["bootstrap"] = list(metrics.cluster_bootstrap(ratio.clusters))
    return entry


def _verdict(entry: dict[str, Any], observed: bool | None, *, halted: str | None, unusable: bool = False) -> dict[str, Any]:
    """합격 칸을 채운다. 판정할 수 없으면 `pass` 를 null 로 두고 그 까닭을 `undetermined` 에 적는다."""
    reason = (
        "멈춘 실행" if halted else "분모 0" if observed is None else "실패·정본 불완전 25% 초과" if unusable else None
    )
    return {**entry, "pass": None if reason else observed, **({"undetermined": reason} if reason else {})}


def _mean(ratios: Sequence[Ratio]) -> float | None:
    values = [ratio.value for ratio in ratios if ratio.value is not None]
    return sum(values) / len(values) if values else None


def synthetic_report(
    eval_set: EvalSet, outcomes: Sequence[ChapterOutcome], attempts: Sequence[tuple[str, str | None]], *,
    adapter: str, halted: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for slot, ratios in metrics.recall(eval_set, outcomes).items():
        mean = _mean(ratios)
        floor = RECALL_FLOOR.get(slot)
        entry = {"repeats": [_entry(ratio) for ratio in ratios], "mean": mean, "pass": None}
        out[f"recall.{slot}"] = entry if floor is None else _verdict(
            entry, None if mean is None else mean >= floor, halted=halted
        )
    precision = metrics.fact_precision(eval_set, outcomes)
    if precision is not None:
        out["precision.facts"] = {"repeats": [_entry(ratio) for ratio in precision], "mean": _mean(precision),
                                  "pass": None}
    direction = metrics.direction_error(eval_set, outcomes)
    if direction is not None:
        mean = _mean(direction)
        out["direction_error"] = _verdict(
            {"repeats": [_entry(ratio, error_rate=True) for ratio in direction], "mean": mean},
            None if mean is None else mean <= DIRECTION_CEILING, halted=halted,
        )
    blocking = metrics.blocking(eval_set, outcomes)
    false_positive = blocking.false_positive
    fp_entry = {
        **_entry(false_positive, error_rate=True),
        "by_chapter": _entry(blocking.false_positive_by_chapter, error_rate=True),
    }
    # 합격선이 0건이라 관측된 오탐은 표본이 덜 돌았어도 미달을 정한다 — 멈춤·실패 초과로 판정을 미루지 않는다.
    out["block_false_positive"] = {**fp_entry, "pass": False} if false_positive.k else _verdict(
        fp_entry, True if false_positive.n else None, halted=halted, unusable=blocking.undeterminable,
    )
    for branch, ratio in blocking.failed.items():
        out[f"commit_failure.{branch}"] = _entry(ratio, error_rate=True)
    out["block_recall"] = _entry(blocking.recall)
    out["warning_recall"] = _entry(blocking.warning_recall)
    out["quote_rate"] = _entry(metrics.quote_rate(outcomes))
    out["schema_failure_rate"] = _entry(metrics.schema_failure_rate(attempts), error_rate=True)
    return {
        "adapter": adapter,
        "halted": halted,
        "slots": sorted({job.slot for outcome in outcomes for job in outcome.jobs}),
        "metrics": out,
        "blocking": {
            "by_rule": blocking.by_rule,
            "by_group": {group: _entry(ratio, error_rate=True) for group, ratio in blocking.by_group.items()},
            "attempted": blocking.totals,
            "excluded": blocking.excluded,
            "undeterminable": blocking.undeterminable,
            "probe_rows_left": sum(outcome.rows_left for outcome in outcomes),
        },
        "cost": metrics.cost(outcomes),
    }


def label_report(labeled: Sequence[LabeledClaim], halted: Mapping[str, str | None]) -> dict[str, Any]:
    """어댑터별 사람 라벨 지표. `halted` 는 어댑터마다 그 추출의 멈춤·끊김 까닭(라벨 열쇠에 실린 것) — 멈춘 어댑터의 판정은
    판정 불가로 두고 까닭을 그 어댑터 칸에 싣는다. 주장이 하나도 없는 어댑터도 열쇠에 있으면 싣는다(멈춘 추출이 보고서에서
    사라지지 않게). κ 는 판정 모델 라벨이 생기면 `metrics.cohen_kappa` 로 같은 주장 단위에서 센다."""
    adapters = sorted(set(halted) | {adapter for row in labeled for adapter in row.claim.adapters})
    out: dict[str, Any] = {}
    for adapter in adapters:
        core = metrics.label_precision(labeled, adapter, core_only=True)
        reason = halted.get(adapter)
        out[adapter] = {
            "halted": reason,
            "precision": _entry(metrics.label_precision(labeled, adapter)),
            "core_fact_precision": _verdict(
                _entry(core), None if core.value is None else core.value >= CORE_PRECISION_FLOOR, halted=reason
            ),
            "direction_error": _entry(metrics.label_direction_error(labeled, adapter), error_rate=True),
        }
    return {"claims": len(labeled), "adapters": out}


def _cell(entry: dict[str, Any]) -> str:
    value = "-" if entry["value"] is None else f"{entry['value']:.3f}"
    bounds = f"상한 {entry['upper']:.3f}" if "upper" in entry else "Wilson [{:.3f}, {:.3f}]".format(*entry["wilson"])
    if "bootstrap" in entry:
        bounds += " · 부트스트랩 [{:.3f}, {:.3f}]".format(*entry["bootstrap"])
    return f"{value} | {entry['k']}/{entry['n']} | {bounds}"


def _verdict_cell(entry: dict[str, Any]) -> str:
    verdict = entry.get("pass")
    if verdict is None:
        return f"판정 불가 — {entry['undetermined']}" if "undetermined" in entry else "-"
    return "합격" if verdict else "미달"


def to_markdown(report: dict[str, Any]) -> str:
    """반복이 있는 지표는 반복별 행 뒤에 판정 근거인 평균 행을 두고, 합격 칸은 평균 행에만 채운다."""
    lines = [f"# 정본 기억 측정 — {report['adapter']}", ""]
    if report.get("halted"):
        lines += [f"실행 멈춤: {report['halted']}", ""]
    lines += ["| 지표 | 관측 | k/n | 구간 | 합격 |", "|---|---|---|---|---|"]
    for name, entry in report["metrics"].items():
        if "repeats" not in entry:
            lines.append(f"| {name} | {_cell(entry)} | {_verdict_cell(entry)} |")
            continue
        lines += [f"| {name} (반복 {i}) | {_cell(row)} | - |" for i, row in enumerate(entry["repeats"], 1)]
        mean = "-" if entry["mean"] is None else f"{entry['mean']:.3f}"
        lines.append(f"| {name} (평균) | {mean} | - | - | {_verdict_cell(entry)} |")
    lines += ["", "```json", json.dumps({k: v for k, v in report.items() if k != "metrics"}, ensure_ascii=False,
                                       indent=2), "```", ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], outcomes: Sequence[ChapterOutcome], run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")  # cite-ok: 문서가 아니라 하네스의 출력 파일 이름
    (run_dir / "outcomes.json").write_text(
        json.dumps([outcome.model_dump(mode="json") for outcome in outcomes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
