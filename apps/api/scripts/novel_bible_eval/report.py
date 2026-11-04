"""보고서 — 지표마다 관측치·k/n·구간·합격선 대조를 JSON 과 마크다운으로 쓴다. 측정 실행 폴더에만 두고 커밋하지 않는다.

합격선(관측치로 판정): 핵심 사실 정밀도 ≥ 0.90, 사실 재현율 ≥ 0.70(반복 평균), 인물 지식 방향 오류 ≤ 3%(반복 평균), 차단 오탐
0건, 판정 모델과 사람의 κ ≥ 0.6. 합격 여부와 무관하게 운영에서 켜지 않는다. 정본 불완전으로 뺀 탐침이 많으면(충돌·비충돌 어느
쪽이든 25% 초과) 탐침이 드는 지표를 판정하지 않는다(`pass` 가 null)."""

import json
from collections.abc import Sequence
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
        out[f"recall.{slot}"] = {
            "repeats": [_entry(ratio) for ratio in ratios], "mean": mean,
            "pass": None if floor is None or mean is None else mean >= floor,
        }
    direction = metrics.direction_error(eval_set, outcomes)
    if direction is not None:
        mean = _mean(direction)
        out["direction_error"] = {
            "repeats": [_entry(ratio, error_rate=True) for ratio in direction], "mean": mean,
            "pass": None if mean is None else mean <= DIRECTION_CEILING,
        }
    blocking = metrics.blocking(eval_set, outcomes)
    judged = not blocking.undeterminable
    out["block_false_positive"] = {
        **_entry(blocking.false_positive, error_rate=True),
        "by_chapter": _entry(blocking.false_positive_by_chapter, error_rate=True),
        "pass": blocking.false_positive.k == 0 if judged else None,
    }
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
            "probes": blocking.totals,
            "excluded": blocking.excluded,
            "failed": blocking.failed,
            "undeterminable": blocking.undeterminable,
            "probe_rows_left": sum(outcome.rows_left for outcome in outcomes),
        },
        "cost": metrics.cost(outcomes),
    }


def label_report(labeled: Sequence[LabeledClaim]) -> dict[str, Any]:
    """어댑터별 사람 라벨 지표. κ 는 판정 모델 라벨이 생기면 `metrics.cohen_kappa` 로 같은 주장 단위에서 센다."""
    adapters = sorted({adapter for row in labeled for adapter in row.claim.adapters})
    out: dict[str, Any] = {}
    for adapter in adapters:
        core = metrics.label_precision(labeled, adapter, core_only=True)
        out[adapter] = {
            "precision": _entry(metrics.label_precision(labeled, adapter)),
            "core_fact_precision": {
                **_entry(core), "pass": None if core.value is None else core.value >= CORE_PRECISION_FLOOR
            },
            "direction_error": _entry(metrics.label_direction_error(labeled, adapter), error_rate=True),
        }
    return {"claims": len(labeled), "adapters": out}


def _cell(entry: dict[str, Any]) -> str:
    value = "-" if entry["value"] is None else f"{entry['value']:.3f}"
    bounds = f"상한 {entry['upper']:.3f}" if "upper" in entry else "Wilson [{:.3f}, {:.3f}]".format(*entry["wilson"])
    if "bootstrap" in entry:
        bounds += " · 부트스트랩 [{:.3f}, {:.3f}]".format(*entry["bootstrap"])
    return f"{value} | {entry['k']}/{entry['n']} | {bounds}"


def to_markdown(report: dict[str, Any]) -> str:
    lines = [f"# 정본 기억 측정 — {report['adapter']}", ""]
    if report.get("halted"):
        lines += [f"원장 멈춤: {report['halted']}", ""]
    lines += ["| 지표 | 관측 | k/n | 구간 | 합격 |", "|---|---|---|---|---|"]
    for name, entry in report["metrics"].items():
        rows = [(f"{name} (반복 {i})", row) for i, row in enumerate(entry["repeats"], 1)] if "repeats" in entry \
            else [(name, entry)]
        for label, row in rows:
            verdict = entry.get("pass")
            lines.append(f"| {label} | {_cell(row)} | {'-' if verdict is None else ('합격' if verdict else '미달')} |")
    lines += ["", "```json", json.dumps({k: v for k, v in report.items() if k != "metrics"}, ensure_ascii=False,
                                       indent=2), "```", ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], outcomes: Sequence[ChapterOutcome], run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")
    (run_dir / "outcomes.json").write_text(
        json.dumps([outcome.model_dump(mode="json") for outcome in outcomes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
