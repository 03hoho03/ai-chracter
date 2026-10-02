"""리플레이 JSONL → 판정별 일치율·정확도·실패·토큰·원가·지연과 통과 여부.

일치 단위: 스탯은 "입력 × 스탯"의 방향(+/−/0, 카운터 스탯 제외), 그림은 고른 후보(없으면 None), 엔딩은 발동 여부, 발행
심사는 통과 여부.

통과 기준(판정 종류 × 후보 설정):
- 스탯·그림·엔딩 — 후보와 현행의 일치율이 현행 자기 반복 일치율보다 `margin_pp` 넘게 낮지 않고, 구조화 실패가 0.
  스탯은 전체 단위와 "변화 기대 단위"(설계 정답이 0 이 아닌 단위) 두 열 모두에 같은 폭을 건다.
- 발행 심사 — 설계 정답과 다른 판정이 한 번도 없고, 구조화 실패와 호출 실패가 0.

두 일치율은 같은 추정 방식으로 잰다 — 현행 자기 반복은 현행 회차끼리의 모든 쌍, 후보는 후보 회차 × 현행 회차의
모든 쌍에서 단위별로 같은 값을 낸 비율이다. 후보를 현행 다수결과 비교하면 다수결이 회차 잡음을 걸러 준 값과 견주게 돼
후보 쪽이 유리해지므로 기준에는 쓰지 않고 참고로만 낸다(`majority_agreement`).

구조화 실패는 응답이 스키마로 해석되지 않은 호출과, 해석은 됐지만 서버가 버리는 값(후보 밖 그림 id, 없는 스탯 id)을 낸
호출의 합이다. 쿼터·네트워크 실패(`api`·`rate_limit`)는 모델 품질이 아니라 따로 센다.
"""

import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from itertools import combinations, product
from pathlib import Path
from typing import Any

from api.llm.pricing import estimate_cost_usd

KIND_ORDER = ("stat", "image", "ending", "publish")


@dataclass(frozen=True)
class Row:
    kind: str
    config: str
    calls: int
    ok: int
    structural_failures: int
    other_failures: int
    cross_agreement: float | None
    majority_agreement: float | None
    nontrivial_cross_agreement: float | None
    accuracy: float | None
    label_mismatches: int
    mean_input_tokens: float | None
    mean_cached_tokens: float | None
    mean_thoughts_tokens: float | None
    mean_output_tokens: float | None
    mean_cost_usd: float | None
    latency_p50_ms: float | None
    latency_p90_ms: float | None
    passes: bool | None


@dataclass(frozen=True)
class Report:
    baseline: str
    margin_pp: float
    self_agreement: dict[str, float | None]
    rows: dict[tuple[str, str], Row]


def load_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _units(record: dict[str, Any]) -> dict[str, Hashable]:
    derived = record["derived"]
    kind = record["kind"]
    if kind == "stat":
        return {f"{record['input_id']}:{name}": value for name, value in derived["directions"].items()}
    if kind == "image":
        return {record["input_id"]: derived["matched"]}
    if kind == "ending":
        return {record["input_id"]: derived["triggered"]}
    return {record["input_id"]: derived["passed"]}


def _expected_units(record: dict[str, Any]) -> dict[str, Hashable]:
    expected = record["expected"]
    if record["kind"] == "stat":
        return {f"{record['input_id']}:{name}": value for name, value in expected.items()}
    return {record["input_id"]: expected}


def _by_rep(records: Iterable[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Hashable]]:
    # 회차는 실행마다 0 부터 센다 — 실행을 나눠 돌린 파일을 합쳐도 회차가 서로 덮어쓰지 않게 실행 id 와 묶는다.
    reps: dict[tuple[str, int], dict[str, Hashable]] = defaultdict(dict)
    for record in records:
        if record["ok"]:
            reps[(record.get("run_id", ""), record["rep"])].update(_units(record))
    return reps


def _pair_rate(
    pairs: Iterable[tuple[dict[str, Hashable], dict[str, Hashable]]], only: set[str] | None = None
) -> float | None:
    same = total = 0
    for left, right in pairs:
        for unit in left.keys() & right.keys():
            if only is not None and unit not in only:
                continue
            total += 1
            same += left[unit] == right[unit]
    return same / total if total else None


def _majority(reps: dict[tuple[str, int], dict[str, Hashable]]) -> dict[str, Hashable]:
    votes: dict[str, Counter[Hashable]] = defaultdict(Counter)
    for units in reps.values():
        for unit, value in units.items():
            votes[unit][value] += 1
    majority: dict[str, Hashable] = {}
    for unit, counter in votes.items():
        value, count = counter.most_common(1)[0]
        if count * 2 > sum(counter.values()):
            majority[unit] = value
    return majority


def _structural(record: dict[str, Any]) -> bool:
    if not record["ok"]:
        return bool(record["error_type"] == "parse")
    derived = record["derived"]
    return bool(derived.get("out_of_candidates") or derived.get("unknown_stat_ids"))


def _input_tokens(tokens: dict[str, Any]) -> int | None:
    # 이미지가 실린 호출은 SDK 가 입력 토큰을 비워 보내기도 한다 — 그때는 전체에서 출력·사고를 빼 입력으로 본다.
    if tokens.get("prompt") is not None:
        return int(tokens["prompt"])
    if tokens.get("total") is not None:
        return int(tokens["total"]) - int(tokens.get("candidates") or 0) - int(tokens.get("thoughts") or 0)
    return None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _within(candidate: float | None, reference: float | None, margin_pp: float) -> bool:
    if candidate is None or reference is None:
        return False
    return candidate * 100 >= reference * 100 - margin_pp


def analyze(records: list[dict[str, Any]], *, baseline: str, margin_pp: float) -> Report:
    records = [r for r in records if r.get("kind") in KIND_ORDER]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["kind"], record["config"])].append(record)

    # 스탯에서 정답이 0 이 아닌 단위 — 장면에 없는 인물의 0 이 대부분이라 전체 일치율만 보면 변화 판정의 차이가 묽어진다.
    nontrivial_units = {
        unit
        for record in records
        if record["kind"] == "stat"
        for unit, value in _expected_units(record).items()
        if value != "0"
    }
    self_agreement: dict[str, float | None] = {}
    self_nontrivial: float | None = None
    baseline_reps: dict[str, dict[tuple[str, int], dict[str, Hashable]]] = {}
    for kind in KIND_ORDER:
        reps = _by_rep(grouped.get((kind, baseline), []))
        baseline_reps[kind] = reps
        self_agreement[kind] = _pair_rate((reps[a], reps[b]) for a, b in combinations(sorted(reps), 2))
        if kind == "stat":
            self_nontrivial = _pair_rate(
                ((reps[a], reps[b]) for a, b in combinations(sorted(reps), 2)), nontrivial_units
            )

    rows: dict[tuple[str, str], Row] = {}
    for (kind, config), group in grouped.items():
        reps = _by_rep(group)
        base = baseline_reps[kind]
        is_baseline = config == baseline
        nontrivial = nontrivial_units if kind == "stat" else None
        if is_baseline:
            cross = self_agreement[kind]
            nontrivial_cross = _pair_rate(((base[a], base[b]) for a, b in combinations(sorted(base), 2)), nontrivial)
        else:
            cross = _pair_rate((reps[c], base[b]) for c, b in product(sorted(reps), sorted(base)))
            nontrivial_cross = _pair_rate(
                ((reps[c], base[b]) for c, b in product(sorted(reps), sorted(base))), nontrivial
            )
        majority = _majority(base)
        majority_agreement = _pair_rate((units, majority) for units in reps.values())

        correct = judged = mismatches = 0
        for record in group:
            if not record["ok"]:
                continue
            got = _units(record)
            for unit, want in _expected_units(record).items():
                if unit in got:
                    judged += 1
                    correct += got[unit] == want
                    mismatches += kind == "publish" and got[unit] != want

        structural = sum(_structural(r) for r in group)
        other = sum(1 for r in group if not r["ok"] and r["error_type"] != "parse")
        token_rows = [r["tokens"] for r in group if r.get("tokens")]
        inputs = [t for t in (_input_tokens(tokens) for tokens in token_rows) if t is not None]
        costs = [
            cost
            for r in group
            if r.get("tokens") and (input_tokens := _input_tokens(r["tokens"])) is not None
            for cost in [
                estimate_cost_usd(
                    r["model"],
                    input_tokens=input_tokens,
                    cached_tokens=int(r["tokens"].get("cached") or 0),
                    output_tokens=int(r["tokens"].get("candidates") or 0),
                    thoughts_tokens=int(r["tokens"].get("thoughts") or 0),
                )
            ]
            if cost is not None
        ]
        latencies = [float(r["latency_ms"]) for r in group if r["ok"]]

        passes: bool | None
        if is_baseline:
            passes = None
        elif kind == "publish":
            # 호출이 실패해 판정이 없는 건 불일치 0 이 아니라 기준 미충족이다 — 운영 발행은 심사 실패를 거부로 막는다.
            passes = structural == 0 and mismatches == 0 and other == 0 and judged > 0
        elif cross is None or self_agreement[kind] is None:
            passes = None
        else:
            passes = structural == 0 and _within(cross, self_agreement[kind], margin_pp)
            if kind == "stat":
                passes = passes and _within(nontrivial_cross, self_nontrivial, margin_pp)

        rows[(kind, config)] = Row(
            kind=kind,
            config=config,
            calls=len(group),
            ok=sum(r["ok"] for r in group),
            structural_failures=structural,
            other_failures=other,
            cross_agreement=cross,
            majority_agreement=majority_agreement,
            nontrivial_cross_agreement=nontrivial_cross,
            accuracy=correct / judged if judged else None,
            label_mismatches=mismatches,
            mean_input_tokens=_mean([float(v) for v in inputs]),
            mean_cached_tokens=_mean([float(t.get("cached") or 0) for t in token_rows]),
            mean_thoughts_tokens=_mean([float(t.get("thoughts") or 0) for t in token_rows]),
            mean_output_tokens=_mean([float(t.get("candidates") or 0) for t in token_rows]),
            mean_cost_usd=_mean(costs),
            latency_p50_ms=_percentile(latencies, 0.5),
            latency_p90_ms=_percentile(latencies, 0.9),
            passes=passes,
        )
    return Report(baseline=baseline, margin_pp=margin_pp, self_agreement=self_agreement, rows=rows)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 0) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def format_report(report: Report) -> str:
    ordered = sorted(
        report.rows.values(),
        key=lambda row: (KIND_ORDER.index(row.kind), row.config != report.baseline, row.config),
    )
    verdict = {None: "—", True: "통과", False: "불합격"}
    lines = [
        f"기준 설정: {report.baseline} · 허용 폭: {report.margin_pp:g}%p",
        "",
        "## 판정 품질",
        "",
        "| 판정 | 설정 | 호출 | 현행 자기 일치 | 후보×현행 일치 | (참고) 현행 다수결 대비 | 변화 기대 단위 일치 | 설계 정답 정확도 "
        "| 구조화 실패 | 기타 실패 | 발행 라벨 불일치 | 기준 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in ordered:
        lines.append(
            f"| {row.kind} | {row.config} | {row.calls} | {_pct(report.self_agreement[row.kind])} | "
            f"{_pct(row.cross_agreement)} | {_pct(row.majority_agreement)} | {_pct(row.nontrivial_cross_agreement)} | "
            f"{_pct(row.accuracy)} | {row.structural_failures} | {row.other_failures} | "
            f"{row.label_mismatches if row.kind == 'publish' else '—'} | {verdict[row.passes]} |"
        )
    lines += [
        "",
        "## 토큰 · 원가 · 지연 (호출당 평균)",
        "",
        "| 판정 | 설정 | 입력 | 캐시 | 사고 | 출력 | 원가(USD) | 지연 p50(ms) | 지연 p90(ms) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in ordered:
        lines.append(
            f"| {row.kind} | {row.config} | {_num(row.mean_input_tokens)} | {_num(row.mean_cached_tokens)} | "
            f"{_num(row.mean_thoughts_tokens)} | {_num(row.mean_output_tokens)} | {_num(row.mean_cost_usd, 6)} | "
            f"{_num(row.latency_p50_ms)} | {_num(row.latency_p90_ms)} |"
        )
    return "\n".join(lines)
