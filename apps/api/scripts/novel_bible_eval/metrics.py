"""지표 식과 구간.

합격은 관측치로 정하고 구간을 함께 적는다. 오류율(방향 오류·차단 오탐·스키마 실패)은 단측 95% Clopper–Pearson 상한, 그 밖의
비율은 Wilson 양측 95% 구간과 화 단위 군집 부트스트랩(화를 다시 뽑기, 2,000회, 시드 고정) 구간이다. 같은 화의 항목끼리 오류가
몰리므로 항목을 독립으로 보는 Wilson 만으로는 구간이 좁게 나온다. 0건 지표는 부트스트랩이 한 점으로 무너지므로 상한만 쓴다.

합성 세트 지표는 결과에 그 슬롯의 작업이 있을 때만 낸다 — 등록부에 아직 없는 슬롯은 지표가 없고, 슬롯이 들어오면 같은 세트로
지표가 생긴다."""

import math
import random
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from api.llm.pricing import call_cost

from novel_bible_eval.labels import LabeledClaim
from novel_bible_eval.match import (
    Aliases,
    Extracted,
    direction_counts,
    extracted,
    matched_events,
    matched_facts,
    matched_knowledge,
)
from novel_bible_eval.run import ChapterOutcome
from novel_bible_eval.spec import ChapterSpec, EvalSet

_Z95 = 1.959963984540054
_SYNTHETIC_SLOTS = ("events", "facts", "knowledge")
# 한 어댑터에서 판정에 쓰지 못한 확정이 이 비율을 넘으면 차단 지표를 판정하지 않는다 — 기본 화는 실패한 확정, 충돌·비충돌
# 탐침은 실패한 것과 정본 불완전으로 뺀 것을 합쳐 각각 본다.
EXCLUDED_LIMIT = 0.25
# 검사가 판정을 낸 끝 상태. 실패와 끝나지 않은 상태(작업 중·밀려남)는 검사에 닿지 못했으므로 막히지 않은 확정으로 세지 않고
# 실패율에 넣는다.
_JUDGED = ("committed", "blocked")


@dataclass(frozen=True)
class Ratio:
    """k / n. `clusters` 는 화마다의 (k, n) — 부트스트랩이 화를 다시 뽑는다."""

    k: int
    n: int
    clusters: tuple[tuple[int, int], ...] = ()

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None


def _ratio(clusters: Sequence[tuple[int, int]]) -> Ratio:
    return Ratio(sum(k for k, _ in clusters), sum(n for _, n in clusters), tuple(clusters))


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denominator = 1 + _Z95**2 / n
    center = (p + _Z95**2 / (2 * n)) / denominator
    half = _Z95 * math.sqrt(p * (1 - p) / n + _Z95**2 / (4 * n * n)) / denominator
    return (max(0.0, center - half), min(1.0, center + half))


def _binomial_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def upper_bound(k: int, n: int, alpha: float = 0.05) -> float:
    """단측 (1 − alpha) Clopper–Pearson 상한 — P(X ≤ k | n, p) = alpha 인 p. 0건이면 1 − alpha^(1/n)."""
    if n == 0 or k >= n:
        return 1.0
    if k == 0:
        return float(1 - alpha ** (1 / n))
    low, high = k / n, 1.0
    for _ in range(100):
        middle = (low + high) / 2
        if _binomial_cdf(k, n, middle) > alpha:
            low = middle
        else:
            high = middle
    return high


def cluster_bootstrap(
    clusters: Sequence[tuple[int, int]], *, rounds: int = 2_000, seed: int = 0
) -> tuple[float, float]:
    """화를 복원 추출로 다시 뽑아 합친 비율의 2.5·97.5 백분위."""
    rng = random.Random(seed)
    ratios: list[float] = []
    for _ in range(rounds):
        sample = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        total = sum(n for _, n in sample)
        if total:
            ratios.append(sum(k for k, _ in sample) / total)
    ratios.sort()
    last = len(ratios) - 1
    return (ratios[math.floor(0.025 * last)], ratios[math.ceil(0.975 * last)])


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float:
    count = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / count
    left, right = Counter(first), Counter(second)
    chance = sum(left[c] * right[c] for c in left.keys() | right.keys()) / count**2
    return 1.0 if chance == 1 else (observed - chance) / (1 - chance)


# ── 합성 세트 ─────────────────────────────────────────────────────────


def _ran_slots(outcomes: Sequence[ChapterOutcome]) -> list[str]:
    ran = {job.slot for outcome in outcomes for job in outcome.jobs}
    return [slot for slot in _SYNTHETIC_SLOTS if slot in ran]


def _base_by_repeat(outcomes: Sequence[ChapterOutcome]) -> dict[int, dict[tuple[str, int], ChapterOutcome]]:
    found: dict[int, dict[tuple[str, int], ChapterOutcome]] = {}
    for outcome in outcomes:
        if outcome.probe is None:
            found.setdefault(outcome.repeat, {})[outcome.novel, outcome.ordinal] = outcome
    return dict(sorted(found.items()))


def _hits(slot: str, chapter: ChapterSpec, found: Extracted | None, aliases: Aliases) -> tuple[int, int]:
    """(맞춘 수, 심은 수). 결과가 없는 화는 하나도 맞추지 못한 것이다."""
    if slot == "events":
        return (matched_events(chapter.events, found.events) if found else 0), len(chapter.events)
    if slot == "facts":
        return (matched_facts(chapter.facts, found.facts, aliases) if found else 0), len(chapter.facts)
    return (matched_knowledge(chapter.knowledge, found.knowledge, aliases) if found else 0), len(chapter.knowledge)


def recall(eval_set: EvalSet, outcomes: Sequence[ChapterOutcome]) -> dict[str, list[Ratio]]:
    """슬롯마다 반복별 재현율 = 맞춘 심은 항목 / 기본 세트에 심은 항목. 결과가 없는 화(확정 전에 멈췄거나 실패)의 정답도 분모에
    든다."""
    result: dict[str, list[Ratio]] = {}
    for slot in _ran_slots(outcomes):
        per_repeat = []
        for by_chapter in _base_by_repeat(outcomes).values():
            clusters = []
            for novel in eval_set.novels:
                for ordinal, chapter in enumerate(novel.chapters, start=1):
                    outcome = by_chapter.get((novel.key, ordinal))
                    found = extracted(outcome) if outcome is not None else None
                    clusters.append(_hits(slot, chapter, found, novel.aliases))
            per_repeat.append(_ratio(clusters))
        result[slot] = per_repeat
    return result


def fact_precision(eval_set: EvalSet, outcomes: Sequence[ChapterOutcome]) -> list[Ratio] | None:
    """반복별 사실 정밀도(합성) = 정답에 대응한 제안 사실 / 기본 화의 제안 사실. 제안 하나가 원자 명제 하나이고, 정답 하나에는
    제안 하나만 대응하므로 같은 명제를 두 번 내면 하나는 틀린 것으로 센다. 결과가 없는 화는 제안이 없어 분모에 아무것도 더하지
    않는다. 사실 작업이 없으면 None."""
    if "facts" not in _ran_slots(outcomes):
        return None
    per_repeat = []
    for by_chapter in _base_by_repeat(outcomes).values():
        clusters = []
        for novel in eval_set.novels:
            for ordinal, chapter in enumerate(novel.chapters, start=1):
                outcome = by_chapter.get((novel.key, ordinal))
                if outcome is not None:
                    found = extracted(outcome).facts
                    clusters.append((matched_facts(chapter.facts, found, novel.aliases), len(found)))
        per_repeat.append(_ratio(clusters))
    return per_repeat


def direction_error(eval_set: EvalSet, outcomes: Sequence[ChapterOutcome]) -> list[Ratio] | None:
    """반복별 인물 지식 방향 오류율(합성). 지식 작업이 없으면 None."""
    if "knowledge" not in _ran_slots(outcomes):
        return None
    per_repeat = []
    for by_chapter in _base_by_repeat(outcomes).values():
        clusters = []
        for novel in eval_set.novels:
            for ordinal, chapter in enumerate(novel.chapters, start=1):
                outcome = by_chapter.get((novel.key, ordinal))
                if outcome is not None:
                    denominator, errors = direction_counts(
                        chapter.knowledge, extracted(outcome).knowledge, novel.aliases
                    )
                    clusters.append((errors, denominator))
        per_repeat.append(_ratio(clusters))
    return per_repeat


@dataclass(frozen=True)
class BlockingSummary:
    false_positive: Ratio  # 확정 단위
    false_positive_by_chapter: Ratio  # 기본 화는 반복을 한 화로 묶은 단위(어느 반복에서든 막히면 막힌 화), 탐침은 하나씩
    by_rule: dict[str, int]
    by_group: dict[str, Ratio]
    recall: Ratio
    warning_recall: Ratio
    excluded: dict[str, int]
    failed: dict[str, Ratio]  # 확정 실패율 — 기본 화(`base`)·탐침 종류마다 검사에 닿지 못한 확정 / 시도한 확정
    undeterminable: bool
    totals: dict[str, int] = field(default_factory=dict)  # 시도한 확정 수, `failed` 와 같은 갈래


def blocking(eval_set: EvalSet, outcomes: Sequence[ChapterOutcome]) -> BlockingSummary:
    """차단 오탐률 = (차단된 기본 확정 + 차단된 비충돌 탐침) / (기본 확정 + 비충돌 탐침). 막히지 않은 확정은 `committed` 만
    센다. 실패했거나 끝 상태에 닿지 않은 확정은 검사에 닿지 못했으므로 오탐 분모에서 빼고 갈래마다 실패율로 센다. 탐침은 기대는
    기본 화(`depends_on`)가 첫 반복에서 하나라도 정본에 없으면 정본 불완전으로 오탐·차단 재현율·경고 재현율 어디에도 넣지
    않는다 — 짝이 없으면 충돌 탐침은 막힐 수 없고 비충돌 탐침은 막히지 않을 수밖에 없어 넣으면 재현율은 내려가고 오탐은 0 쪽으로
    기운다. 실패한 확정을 빼기만 하면 오탐 분모가 조용히 줄어 실패가 몰린 실행이 오탐 0 으로 읽히므로, 기본 화의 실패나 충돌·비충돌
    탐침의 실패 + 정본 불완전이 25% 를 넘으면 판정 불가로 표시한다."""
    probes = {probe.key: probe for novel in eval_set.novels for probe in novel.probes}
    canon = {(o.novel, o.ordinal) for o in outcomes if o.probe is None and o.repeat == 1 and o.status == "committed"}
    population: list[ChapterOutcome] = []
    base_units: dict[tuple[str, int], bool] = {}
    probe_units: list[bool] = []
    groups: dict[str, list[tuple[int, int]]] = {}
    conflict: list[tuple[int, int]] = []
    warning: list[tuple[int, int]] = []
    excluded: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    failed: Counter[str] = Counter()
    for outcome in outcomes:
        branch = "base" if outcome.probe is None else probes[outcome.probe].kind
        totals[branch] += 1
        if outcome.status not in _JUDGED:
            failed[branch] += 1
            continue
        blocked = outcome.status == "blocked"
        if outcome.probe is None:
            population.append(outcome)
            key = (outcome.novel, outcome.ordinal)
            base_units[key] = base_units.get(key, False) or blocked
            continue
        probe = probes[outcome.probe]
        if not all((outcome.novel, ordinal) in canon for ordinal in probe.depends_on):
            excluded[probe.kind] += 1
        elif probe.kind == "non_conflict":
            population.append(outcome)
            probe_units.append(blocked)
            groups.setdefault(probe.group, []).append((int(blocked), 1))
        elif probe.kind == "conflict":
            conflict.append((int(blocked and probe.expected_rule in outcome.block_rules), 1))
        else:
            warning.append((int(probe.expected_rule in outcome.warning_rules), 1))
    rules: Counter[str] = Counter()
    for outcome in population:
        if outcome.status == "blocked":
            rules.update(set(outcome.block_rules))
    over = any(
        totals[kind] and (failed[kind] + excluded[kind]) / totals[kind] > EXCLUDED_LIMIT
        for kind in ("base", "conflict", "non_conflict")
    )
    return BlockingSummary(
        false_positive=_ratio([(int(o.status == "blocked"), 1) for o in population]),
        false_positive_by_chapter=_ratio([(int(blocked), 1) for blocked in (*base_units.values(), *probe_units)]),
        by_rule=dict(rules),
        by_group={group: _ratio(rows) for group, rows in sorted(groups.items())},
        recall=_ratio(conflict),
        warning_recall=_ratio(warning),
        excluded=dict(excluded),
        failed={branch: Ratio(failed[branch], count) for branch, count in sorted(totals.items())},
        undeterminable=over,
        totals=dict(totals),
    )


def quote_rate(outcomes: Sequence[ChapterOutcome]) -> Ratio:
    """근거 인용 실재율 = 검증을 통과해 남은 항목 / (남은 항목 + 인용 때문에 버린 항목). 회상 관계는 그 사건의 인용을 빌려 쓰므로
    세지 않는다. 다른 사유로 버린 항목(문단 번호가 틀림 따위)은 인용을 보기 전에 버려 분모에 넣지 않는다."""
    clusters = []
    for outcome in outcomes:
        kept = dropped = 0
        for job in outcome.jobs:
            if job.proposal is None:
                continue
            kept += sum(1 for item in job.proposal["items"] if item["table"] != "event_relation")
            dropped += sum(count for reason, count in job.proposal["dropped"].items() if reason.startswith("quote"))
        clusters.append((kept, kept + dropped))
    return _ratio(clusters)


def schema_failure_rate(attempts: Sequence[tuple[str, str | None]]) -> Ratio:
    return Ratio(sum(code == "schema_invalid" for _, code in attempts), len(attempts))


def cost(outcomes: Sequence[ChapterOutcome]) -> dict[str, Any]:
    """작업 호출 기록의 원가(앱 단가표)와 지연. 단가표에 없는 모델의 호출은 원가에서 빠지고 `unpriced` 로 센다."""
    calls = [call for outcome in outcomes for job in outcome.jobs for call in job.calls]
    priced = [call_cost(call).usd for call in calls]
    durations = sorted(int(call["durationMs"]) for call in calls if isinstance(call.get("durationMs"), int))
    return {
        "calls": len(calls),
        "usd": sum(usd for usd in priced if usd is not None),
        "unpriced": sum(usd is None for usd in priced),
        "median_ms": statistics.median(durations) if durations else None,
        "p90_ms": durations[math.ceil(0.9 * len(durations)) - 1] if durations else None,
    }


# ── 사람 라벨 ─────────────────────────────────────────────────────────


def _supported(labeled: LabeledClaim, adapter: str) -> bool:
    quotes = labeled.claim.adapters[adapter]
    return bool(quotes) and all(labeled.label.quotes[index] == "supported" for index in quotes)


def label_precision(labeled: Sequence[LabeledClaim], adapter: str, *, core_only: bool = False) -> Ratio:
    """그 어댑터가 낸 주장 중 라벨이 `맞음` 이고 그 어댑터가 붙인 인용이 모두 `받침` 인 것 / 판단 불가가 아닌 것. `core_only`
    는 차단 규칙이 읽는 사실 주장으로 좁히되, 속성이 핵심인지는 그 어댑터 자신의 불변 표시로 정한다 — 다른 어댑터가 같은 속성을
    불변으로 냈다고 이 어댑터의 주장이 핵심 사실 정밀도에 들지 않는다."""
    clusters: dict[int, list[int]] = {}
    for row in labeled:
        if adapter not in row.claim.adapters or row.label.verdict == "unknown":
            continue
        if core_only and not row.claim.core[adapter]:
            continue
        cell = clusters.setdefault(row.claim.chapter, [0, 0])
        cell[0] += row.label.verdict == "correct" and _supported(row, adapter)
        cell[1] += 1
    return _ratio([(k, n) for k, n in clusters.values()])


def label_direction_error(labeled: Sequence[LabeledClaim], adapter: str) -> Ratio:
    """그 어댑터의 지식 주장 중 방향 틀림 / (맞음 + 방향 틀림)."""
    rows = [
        row.label.verdict == "direction"
        for row in labeled
        if row.claim.slot == "knowledge" and adapter in row.claim.adapters
        and row.label.verdict in ("correct", "direction")
    ]
    return Ratio(sum(rows), len(rows))
