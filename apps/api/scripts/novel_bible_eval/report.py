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
from novel_bible_eval.run import BIBLE_TABLES, ChapterOutcome
from novel_bible_eval.spec import EvalSet

RECALL_FLOOR = {"facts": 0.70}
_CLOSED = "immutable_attribute_mismatch"
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


def _repeated(ratios: Sequence[Ratio]) -> dict[str, Any]:
    return {"repeats": [_entry(ratio) for ratio in ratios], "mean": _mean(ratios), "pass": None}


def synthetic_report(
    eval_set: EvalSet, outcomes: Sequence[ChapterOutcome], attempts: Sequence[tuple[str, str | None]], *,
    adapter: str, halted: str | None = None, calls: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """`calls` 는 해석기를 지난 호출 기록 원소 전부(`Meter.calls`)다 — 실제 모델·구현과 단계별 원가를 거기서 센다. 작업 행에
    남지 않는 판정 호출도 들어 있다. `cost` 는 작업 행에 남은 추출 호출만 센 원가다."""
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
        out["precision.facts"] = _repeated(precision)
    relation = metrics.relation_accuracy(eval_set, outcomes)
    if relation is not None:
        out["relation_accuracy"] = _repeated(relation)
    for origin, ratios in metrics.adaptation_recall(eval_set, outcomes).items():
        out[f"adaptation_recall.{origin}"] = _repeated(ratios)
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
            "by_rule": _entries(blocking.by_rule, error_rate=True),
            "by_group": _entries(blocking.by_group, error_rate=True),
            "by_subkind": _entries(blocking.by_subkind, error_rate=True),
            "recall_by_rule": _entries(blocking.recall_by_rule),
            "closed": {
                "false_positive_by_category": _entries(blocking.closed.false_positive_by_category, error_rate=True),
                "false_positive_by_item": _entries(blocking.closed.false_positive_by_item, error_rate=True),
                "recall_by_category": _entries(blocking.closed.recall_by_category),
                "recall_by_item": _entries(blocking.closed.recall_by_item),
            },
            "attempted": blocking.totals,
            "excluded": blocking.excluded,
            "undeterminable": blocking.undeterminable,
            "probe_rows_left": {
                table: sum(outcome.rows_left.get(table, 0) for outcome in outcomes) for table in BIBLE_TABLES
            },
        },
        "models": metrics.models(calls),
        "cost": metrics.cost(outcomes),
        "cost_by_stage": metrics.stage_costs(calls),
    }


def _entries(ratios: Mapping[str, Ratio], *, error_rate: bool = False) -> dict[str, dict[str, Any]]:
    return {name: _entry(ratio, error_rate=error_rate) for name, ratio in ratios.items()}


# 뺀 뒤 열 머리 — 뺄 항목을 이 세트의 오탐으로 고르고 같은 세트로 다시 쟀으므로, 다른 원고에서보다 좋게 나온다.
AFTER_HEADER = "뺀 뒤 — 같은 세트로 고르고 다시 잰 값이라 낙관 쪽으로 기운다"


def removal_report(
    eval_set: EvalSet, before: Sequence[ChapterOutcome], after: Sequence[ChapterOutcome], *, removed: Sequence[str]
) -> dict[str, Any]:
    """열거형 사전 항목(`enum:범주/정규 값`)을 뺀 뒤의 차단 지표를 빼기 전과 나란히 둔다 — 차단 오탐률·차단 재현율·닫힌 값 불변
    속성 모순 규칙의 값, 그 규칙의 갈래별 값, 뺀 항목별 값. 뺀 뒤 값을 어떻게 얻었는지(추출을 다시 부름, 기록한 출력을 재생함)는
    여기서 정하지 않는다 — 그 결과 묶음(`after`)을 받는다. 뺀 항목을 기대한 충돌 탐침은 뺀 뒤에도 분모에 남아, 막지 못하게 된
    값이 재현율에 그대로 드러난다."""
    sides = [metrics.blocking(eval_set, outcomes) for outcomes in (before, after)]
    rows: list[dict[str, Any]] = []

    def row(name: str, pick: Any, *, error_rate: bool) -> None:
        picked = [pick(summary) for summary in sides]
        rows.append({
            "name": name,
            "before": _entry(picked[0] or Ratio(0, 0), error_rate=error_rate),
            "after": _entry(picked[1] or Ratio(0, 0), error_rate=error_rate),
        })

    row("block_false_positive", lambda summary: summary.false_positive, error_rate=True)
    row("block_recall", lambda summary: summary.recall, error_rate=False)
    row(f"block_false_positive.{_CLOSED}", lambda summary: summary.by_rule[_CLOSED], error_rate=True)
    row(f"block_recall.{_CLOSED}", lambda summary: summary.recall_by_rule[_CLOSED], error_rate=False)
    categories = sorted({c for side in sides for c in (*side.closed.false_positive_by_category,
                                                        *side.closed.recall_by_category)})
    for category in categories:
        row(f"block_false_positive.{category}", lambda s, c=category: s.closed.false_positive_by_category.get(c),
            error_rate=True)
        row(f"block_recall.{category}", lambda s, c=category: s.closed.recall_by_category.get(c), error_rate=False)
    for item in removed:
        row(f"block_false_positive.{item}", lambda s, i=item: s.closed.false_positive_by_item.get(i), error_rate=True)
        row(f"block_recall.{item}", lambda s, i=item: s.closed.recall_by_item.get(i), error_rate=False)
    return {"removed": list(removed), "rows": rows}


def removal_markdown(table: dict[str, Any]) -> str:
    lines = [
        "# 열거형 사전 항목을 뺀 전·후", "", "뺀 항목: " + ", ".join(table["removed"]), "",
        f"| 지표 | 빼기 전 | {AFTER_HEADER} |", "|---|---|---|",
    ]
    lines += [f"| {row['name']} | {_short(row['before'])} | {_short(row['after'])} |" for row in table["rows"]]
    return "\n".join([*lines, ""])


def _short(entry: dict[str, Any]) -> str:
    """관측치 (k/n) 와 구간 — 오류율은 단측 상한, 그 밖은 Wilson."""
    value = "-" if entry["value"] is None else f"{entry['value']:.3f}"
    bounds = f"상한 {entry['upper']:.3f}" if "upper" in entry else "Wilson [{:.3f}, {:.3f}]".format(*entry["wilson"])
    return f"{value} ({entry['k']}/{entry['n']}) · {bounds}"


# 합성 원고를 Claude 계열이 썼다 — 비교표에 함께 적는 한계.
_WRITER_NOTE = (
    "합성 원고는 Claude 계열 모델이 썼다 — Claude 어댑터의 재현율이 부풀 수 있어, 어댑터 간 순위는 사람 라벨 세트를 우선한다."
)


def compare_markdown(reports: Mapping[str, dict[str, Any]]) -> str:
    """어댑터별 보고서를 한 표로 — 지표마다 어댑터 열에 관측치(k/n)와 합격선 대조, 반복이 있는 지표는 평균과 그 판정. 끝에
    실제로 부른 모델·구현과 원가 행을 둔다."""
    names = list(reports)
    metric_names = list(dict.fromkeys(name for report in reports.values() for name in report["metrics"]))
    lines = [
        "# 정본 기억 측정 — 어댑터 비교", "", _WRITER_NOTE, "",
        "| 지표 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names),
    ]
    for metric in metric_names:
        cells = [_compare_cell(reports[name]["metrics"].get(metric)) for name in names]
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    used = [
        ", ".join(f"{row['stage']} {row['backend']}/{row['model']}" for row in reports[name].get("models", [])) or "-"
        for name in names
    ]
    lines.append("| 실제 모델 | " + " | ".join(used) + " |")
    spent = [
        f"{sum(stage['usd'] for stage in reports[name].get('cost_by_stage', {}).values()):.4f}" for name in names
    ]
    lines.append("| 원가(USD, 판정 포함) | " + " | ".join(spent) + " |")
    halted = [reports[name].get("halted") or "-" for name in names]
    lines.append("| 실행 멈춤 | " + " | ".join(halted) + " |")
    return "\n".join([*lines, ""])


def _compare_cell(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "-"
    verdict = _verdict_cell(entry)
    tail = "" if verdict == "-" else f" {verdict}"
    if "repeats" in entry:
        mean = "-" if entry["mean"] is None else f"{entry['mean']:.3f}"
        return f"평균 {mean}{tail}"
    value = "-" if entry["value"] is None else f"{entry['value']:.3f}"
    return f"{value} ({entry['k']}/{entry['n']}){tail}"


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
    """반복이 있는 지표는 반복별 행 뒤에 판정 근거인 평균 행을 두고, 합격 칸은 평균 행에만 채운다. 그 뒤에 차단 세부(규칙별 오탐은
    전체 오탐과 같은 분모, 충돌 규칙별 재현율, 비충돌 세부 종류별 오탐, 닫힌 값 갈래·사전 항목별)를 표로 두고 나머지는 JSON 이다."""
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
    blocking = report["blocking"]
    closed = blocking["closed"]
    details = {
        "규칙별 오탐": blocking["by_rule"], "충돌 규칙별 재현율": blocking["recall_by_rule"],
        "비충돌 세부 종류별 오탐": blocking["by_subkind"],
        "닫힌 값 갈래별 오탐": closed["false_positive_by_category"], "사전 항목별 오탐": closed["false_positive_by_item"],
        "닫힌 값 갈래별 재현율": closed["recall_by_category"], "사전 항목별 재현율": closed["recall_by_item"],
    }
    lines += ["", "| 차단 세부 | 이름 | 관측 | k/n | 구간 |", "|---|---|---|---|---|"]
    lines += [f"| {title} | {name} | {_cell(entry)} |" for title, rows in details.items() for name, entry in rows.items()]
    rest = {k: v for k, v in report.items() if k != "metrics"}
    rest["blocking"] = {k: v for k, v in blocking.items() if k not in ("by_rule", "recall_by_rule", "by_subkind", "closed")}
    lines += ["", "```json", json.dumps(rest, ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], outcomes: Sequence[ChapterOutcome], run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")  # cite-ok: 문서가 아니라 하네스의 출력 파일 이름
    (run_dir / "outcomes.json").write_text(
        json.dumps([outcome.model_dump(mode="json") for outcome in outcomes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
