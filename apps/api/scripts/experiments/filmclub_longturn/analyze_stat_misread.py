"""스탯 판정 형식 갈래(현행·A·L·L+A) 리플레이 결과를, 결과를 보기 전에 정해 둔 기준 그대로 판정한다.

입력은 `judgment_replay.py` 오프라인 모드가 쓴 jsonl(`kind=call` 줄)과 그 호출을 만든 입력 JSON 이다. 같은 입력의 현행 갈래와
수정 갈래를 비교해 두 가지를 본다.

- 오독 감소(오독 검출 군 E): 한 호감의 새 값을 자기 현재값이 아니라 같은 종류 다른 스탯의 현재값 근처로 내는 출력이
  줄었는가.
- 정상 판정 불변(대조 군 N 중심): 방향·폭·요청률·규칙 위반·형식 이상이 현행과 비슷한가.

갈래 이름은 도구의 `statFormat` 값 그대로다 — `current`(현행), `A`(스탯 줄에서 현재값·범위를 이름 바로 뒤로), `L`(지시문
끝 한 문장), `B`(A 와 L 을 함께). 정의·임계값은 아래 상수와 함수가 전부이고, 바꾸면 사전에 고정한 기준과 달라진다.

    uv run --env-file .env python scripts/experiments/filmclub_longturn/analyze_stat_misread.py \\
        --inputs-dir <run>/inputs --replay <run>/replay/<inputId>.jsonl [...] --reps 5 --out <run>/s3-analysis.md
    # inputId 가 없는 옛 형식 jsonl 은 파일마다 입력을 지정한다:
    ... --replay old.jsonl --assign old.jsonl=<run>/inputs/anchor-....json --reps 10
"""

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from api.llm.pricing import estimate_cost_usd

ARMS = ("current", "A", "L", "B")
ARM_LABEL = {"current": "현행", "A": "A", "L": "L", "B": "L+A(B)"}
TREATMENTS = ("L", "A", "B")
# 오독 검출 군. 닻(형식 비교 때 쓴 두 턴)도 같은 성격의 입력이라 E 로 다룬다 — 이번 런의 판정 입력에는 들지 않는다.
E_GROUPS = frozenset({"E1", "E2", "anchor"})
N_GROUPS = frozenset({"N1", "N2"})

# 자기 현재값에서 이만큼 이상 떨어진 요청만 오독 후보다. 측정 방의 정상 상승 최대가 +7 이라 그보다 큰 첫 정수.
MISREAD_MIN_DISTANCE = 8.0
FISHER_ALPHA = 0.05
# 현행 E 군 오독이 이보다 적으면 감소 검정이 정보를 주지 못한다(현행 6/60 에서 수정 갈래 1건이면 이미 p≈0.057).
G1_MIN_INFORMATIVE = 6
G2A_MAX_CHANGED_SHARE = 0.10
G2B_MAX_MEAN_ABS_PCT_DIFF = 1.0
G2B_CELL_MEDIAN_PCT_DIFF = 2.5
G2B_MAX_CELL_SHARE = 0.10
G2C_MAX_REQUEST_RATE_DIFF_PCT = 15.0
G2D_MAX_EXCESS = 2
G2E_MAX_EXCESS = 1
# 한 턴 변화가 범위의 이 비율을 넘으면 규칙 위반 — 범위가 너무 작아 1 의 변화도 이 비율을 넘는 스탯은 빼고.
G2D_RANGE_SHARE = 0.15
PARSE_FAILURE_MARK = "could not be parsed"


# ── 입력 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stat:
    stat_id: str
    name: str
    min_value: float
    max_value: float
    per_turn_delta: float | None
    change_direction: str | None
    max_change_per_turn: float | None

    @property
    def is_counter(self) -> bool:
        """시스템이 매 턴 굴리는 값 — 판정 대상이 아니고 판정 프롬프트가 넣지 말라고 적는다."""
        return self.per_turn_delta is not None

    @property
    def span(self) -> float:
        return self.max_value - self.min_value

    def kind_key(self) -> tuple[float, float, str | None, float | None]:
        """같은 범위·같은 종류: 범위 양 끝과 판정 제약(방향·턴당 최대 폭)이 모두 같은 판정 스탯."""
        return (self.min_value, self.max_value, self.change_direction or "both", self.max_change_per_turn)


@dataclass(frozen=True)
class InputSpec:
    input_id: str
    group: str
    stats: tuple[Stat, ...]
    start: dict[str, float]

    @property
    def is_e(self) -> bool:
        return self.group in E_GROUPS

    def stat(self, stat_id: str) -> Stat | None:
        return next((s for s in self.stats if s.stat_id == stat_id), None)

    def judged(self) -> list[Stat]:
        return [s for s in self.stats if not s.is_counter]

    def peers(self, stat: Stat) -> list[Stat]:
        if stat.is_counter:
            return []
        return [o for o in self.judged() if o.stat_id != stat.stat_id and o.kind_key() == stat.kind_key()]


def input_from_json(data: dict[str, Any]) -> InputSpec:
    group = data["group"]
    if group not in E_GROUPS | N_GROUPS:
        raise ValueError(f"{data['inputId']}: 모르는 군 {group}")
    stats = tuple(
        Stat(
            stat_id=str(row["entity_id"]),
            name=row["name"],
            min_value=float(row["min_value"]),
            max_value=float(row["max_value"]),
            per_turn_delta=row["per_turn_delta"],
            change_direction=row["change_direction"],
            max_change_per_turn=row["max_change_per_turn"],
        )
        for row in data["statDefs"]
    )
    start = {str(k): float(v) for k, v in data["statStart"].items()}
    if set(start) != {s.stat_id for s in stats}:
        raise ValueError(f"{data['inputId']}: 시작값이 스탯 정의와 맞지 않는다")
    spec = InputSpec(input_id=data["inputId"], group=group, stats=stats, start=start)
    if spec.is_e and not any(len(spec.peers(s)) >= 2 for s in spec.judged()):
        # E 군은 같은 범위·같은 종류 판정 스탯이 셋 이상인 배치다 — 아니면 오독 정의가 이 입력에서 뜻이 없다.
        raise ValueError(f"{spec.input_id}: E 군인데 같은 종류 판정 스탯이 셋 이상인 묶음이 없다")
    return spec


@dataclass(frozen=True)
class Call:
    input_id: str
    arm: str
    rep: int
    output: dict[str, Any] | None
    error: str | None
    tokens: dict[str, Any] | None = None
    latency_ms: float | None = None
    model: str | None = None

    def raw_changes(self) -> list[tuple[str, float]]:
        if self.output is None:
            return []
        return [(str(c["stat_id"]), float(c["new_value"])) for c in self.output.get("stat_changes", [])]

    def last_values(self) -> dict[str, float]:
        """같은 스탯이 여러 번 나오면 서버처럼 마지막 항목 하나."""
        return dict(self.raw_changes())


def load_calls(path: Path, assigned: InputSpec | None = None) -> list[Call]:
    calls: list[Call] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") != "call":
            continue
        if row.get("judgment", "stat") != "stat":
            raise ValueError(f"{path}: 스탯 판정이 아닌 호출 줄이 있다")
        input_id = row.get("inputId")
        if assigned is not None:
            if input_id is not None and input_id != assigned.input_id:
                raise ValueError(f"{path}: 줄의 inputId {input_id} 가 지정한 입력 {assigned.input_id} 와 다르다")
            if row.get("group") is not None and row["group"] != assigned.group:
                raise ValueError(f"{path}: 줄의 군이 지정한 입력과 다르다")
            input_id = assigned.input_id
        if input_id is None:
            raise ValueError(f"{path}: inputId 가 없는 줄 — --assign 으로 입력을 지정한다")
        arm = row["statFormat"]
        if arm not in ARMS:
            raise ValueError(f"{path}: 모르는 갈래 {arm}")
        calls.append(
            Call(
                input_id=input_id,
                arm=arm,
                rep=int(row["rep"]),
                output=row.get("output"),
                error=row.get("error"),
                tokens=row.get("tokens"),
                latency_ms=row.get("latencyMs"),
                model=row.get("sentModel"),
            )
        )
    return calls


# ── 호출 하나의 분류 ────────────────────────────────────────────────────────


def requests(call: Call, spec: InputSpec) -> dict[str, float]:
    """요청 = 출력에 그 스탯이 있고 값이 시작값과 다름. 아는 판정 스탯만(모르는 id·카운터는 형식 이상으로 따로 센다)."""
    out: dict[str, float] = {}
    for stat_id, value in call.last_values().items():
        stat = spec.stat(stat_id)
        if stat is None or stat.is_counter:
            continue
        if value != spec.start[stat_id]:
            out[stat_id] = value
    return out


def delta(call: Call, spec: InputSpec, stat: Stat) -> float:
    """자기 기준 Δ = 요청값 − 자기 시작값, 요청이 없으면 0."""
    value = requests(call, spec).get(stat.stat_id)
    return 0.0 if value is None else value - spec.start[stat.stat_id]


def delta_pct(call: Call, spec: InputSpec, stat: Stat) -> float:
    return 100.0 * delta(call, spec, stat) / stat.span


def misread_stats(call: Call, spec: InputSpec) -> set[str]:
    """E 군만: 요청값 r 이 자기 시작값 v_s 에서 8 이상 떨어져 있고, 같은 종류 다른 스탯 o 중 하나의 시작값에 더 가깝다."""
    if not spec.is_e:
        return set()
    found: set[str] = set()
    for stat_id, r in requests(call, spec).items():
        stat = spec.stat(stat_id)
        assert stat is not None
        own = abs(r - spec.start[stat_id])
        if own < MISREAD_MIN_DISTANCE:
            continue
        if any(abs(r - spec.start[o.stat_id]) < own for o in spec.peers(stat)):
            found.add(stat_id)
    return found


def is_misread_call(call: Call, spec: InputSpec) -> bool:
    return bool(misread_stats(call, spec))


def rule_violations(call: Call, spec: InputSpec, stat: Stat) -> list[str]:
    """서버가 자르기 전 원 출력이 스탯 꼬리 규칙(방향·턴당 최대 폭)이나 범위 15% 를 넘었는가."""
    value = requests(call, spec).get(stat.stat_id)
    if value is None:
        return []
    change = value - spec.start[stat.stat_id]
    found: list[str] = []
    if (stat.change_direction == "increase" and change < 0) or (stat.change_direction == "decrease" and change > 0):
        found.append("direction")
    step = stat.max_change_per_turn
    if step is not None and step > 0 and abs(change) > step:
        found.append("maxChange")
    if 1 <= G2D_RANGE_SHARE * stat.span and abs(change) > G2D_RANGE_SHARE * stat.span:
        found.append("over15")
    return found


def format_anomalies(call: Call, spec: InputSpec) -> list[str]:
    """호출 하나의 형식 이상: 오류(파싱 실패는 따로), 모르는 statId, 카운터 스탯을 출력에 넣음(값과 무관)."""
    if call.error is not None:
        return ["parseFailure" if PARSE_FAILURE_MARK in call.error else "error"]
    found: list[str] = []
    for stat_id, _ in call.raw_changes():
        stat = spec.stat(stat_id)
        if stat is None:
            found.append("unknownStatId")
        elif stat.is_counter:
            found.append("counterRequested")
    return sorted(set(found))


def sign(value: float) -> str:
    return "+" if value > 0 else "-" if value < 0 else "0"


def modal_set(values: Iterable[str]) -> frozenset[str]:
    counts = Counter(values)
    if not counts:
        return frozenset()
    top = max(counts.values())
    return frozenset(k for k, v in counts.items() if v == top)


def fisher_one_sided_less(x_hits: int, x_n: int, c_hits: int, c_n: int) -> float:
    """2×2 표에서 갈래 X 의 오독이 현행보다 적다는 단측 Fisher 정확 검정 p — 여백 고정 초기하분포의 P(K ≤ x_hits)."""
    total, hits = x_n + c_n, x_hits + c_hits
    denom = math.comb(total, x_n)
    return sum(math.comb(hits, k) * math.comb(total - hits, x_n - k) for k in range(0, x_hits + 1)) / denom


# ── 집계 ────────────────────────────────────────────────────────────────────


@dataclass
class Data:
    specs: dict[str, InputSpec]
    calls: list[Call]
    by_key: dict[tuple[str, str], list[Call]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        grouped: dict[tuple[str, str], list[Call]] = defaultdict(list)
        for call in self.calls:
            if call.input_id not in self.specs:
                raise ValueError(f"입력 JSON 이 없는 inputId: {call.input_id}")
            grouped[(call.input_id, call.arm)].append(call)
        self.by_key = dict(grouped)

    def input_ids(self) -> list[str]:
        return sorted({c.input_id for c in self.calls})

    def arms(self) -> list[str]:
        present = {c.arm for c in self.calls}
        return [a for a in ARMS if a in present]

    def get(self, input_id: str, arm: str) -> list[Call]:
        return self.by_key.get((input_id, arm), [])


def check_counts(data: Data, reps: int) -> None:
    """입력 × 갈래마다 호출 줄이 정확히 reps 개여야 한다 — 재시도 줄이 섞이거나 빠진 채 판정하지 않는다."""
    bad = [
        f"{i}/{a}={len(data.get(i, a))}" for i in data.input_ids() for a in data.arms() if len(data.get(i, a)) != reps
    ]
    if "current" not in data.arms():
        raise ValueError("현행 갈래 호출이 없다")
    silent = sorted(set(data.specs) - set(data.input_ids()))
    if silent:
        raise ValueError(f"호출 줄이 하나도 없는 입력: {', '.join(silent)}")
    if bad:
        raise ValueError(f"입력 × 갈래 호출 수가 {reps} 가 아니다: {', '.join(bad)}")


def g1(data: Data, arm: str) -> dict[str, Any]:
    e_ids = [i for i in data.input_ids() if data.specs[i].is_e]
    per_group: dict[str, dict[str, int]] = {}
    for input_id in e_ids:
        group = data.specs[input_id].group
        slot = per_group.setdefault(group, {"x": 0, "c": 0, "xn": 0, "cn": 0})
        for name, key, nkey in ((arm, "x", "xn"), ("current", "c", "cn")):
            calls = data.get(input_id, name)
            slot[key] += sum(is_misread_call(c, data.specs[input_id]) for c in calls)
            slot[nkey] += len(calls)
    x = sum(g["x"] for g in per_group.values())
    c = sum(g["c"] for g in per_group.values())
    xn = sum(g["xn"] for g in per_group.values())
    cn = sum(g["cn"] for g in per_group.values())
    p = fisher_one_sided_less(x, xn, c, cn) if xn and cn else None
    per_source_ok = all(g["x"] <= g["c"] for g in per_group.values())
    informative = c >= G1_MIN_INFORMATIVE
    if not e_ids:
        status = "해당 없음"
        ok = None
    elif informative:
        ok = x < c and p is not None and p < FISHER_ALPHA and per_source_ok
        status = "통과" if ok else "실패"
    else:
        ok = x <= c and per_source_ok
        status = "비정보적(X≤현행 충족)" if ok else "비정보적(X≤현행 위반)"
    return {
        "x": x,
        "xn": xn,
        "current": c,
        "currentN": cn,
        "p": p,
        "perGroup": per_group,
        "perSourceOk": per_source_ok,
        "informative": informative,
        "ok": ok,
        "status": status,
    }


def _cells(data: Data, include_e: bool) -> list[tuple[str, Stat]]:
    return [
        (i, s)
        for i in data.input_ids()
        if (include_e and data.specs[i].is_e) or data.specs[i].group in N_GROUPS
        for s in data.specs[i].judged()
    ]


def _valid(calls: list[Call]) -> list[Call]:
    return [c for c in calls if c.error is None]


def _cell_values(data: Data, input_id: str, stat: Stat, arm: str, drop_misread: bool) -> list[float]:
    spec = data.specs[input_id]
    return [
        delta_pct(c, spec, stat)
        for c in _valid(data.get(input_id, arm))
        if not (drop_misread and stat.stat_id in misread_stats(c, spec))
    ]


def g2abc(data: Data, arm: str, *, include_e: bool = False, drop_misread: bool = True) -> dict[str, Any]:
    """G2a 방향·G2b 폭·G2c 요청률. 판정은 N 군 칸만(include_e=False). include_e 는 관찰용 what-if."""
    cells = _cells(data, include_e)
    if not cells:
        return {"cells": 0, "ok": None, "status": "판정 불가(N 군 칸 0)"}
    changed: list[str] = []
    median_moved: list[str] = []
    x_abs: list[float] = []
    c_abs: list[float] = []
    x_req = c_req = x_inst = c_inst = 0
    for input_id, stat in cells:
        xv = _cell_values(data, input_id, stat, arm, drop_misread)
        cv = _cell_values(data, input_id, stat, "current", drop_misread)
        label = f"{input_id}/{stat.name}"
        # 유효 호출이 없는 칸은 비교할 수 없으니 바뀐 칸으로 센다(오류는 G2e 에서도 따로 잡힌다).
        if not xv or not cv or not (modal_set(map(sign, xv)) & modal_set(map(sign, cv))):
            changed.append(label)
        if not xv or not cv or abs(statistics.median(xv) - statistics.median(cv)) > G2B_CELL_MEDIAN_PCT_DIFF:
            median_moved.append(label)
        x_abs += [abs(v) for v in xv]
        c_abs += [abs(v) for v in cv]
        x_req += sum(v != 0 for v in xv)
        c_req += sum(v != 0 for v in cv)
        x_inst += len(xv)
        c_inst += len(cv)
    n = len(cells)
    mean_x = statistics.fmean(x_abs) if x_abs else 0.0
    mean_c = statistics.fmean(c_abs) if c_abs else 0.0
    rate_x = 100.0 * x_req / x_inst if x_inst else 0.0
    rate_c = 100.0 * c_req / c_inst if c_inst else 0.0
    a_ok = len(changed) <= G2A_MAX_CHANGED_SHARE * n
    b_ok = abs(mean_x - mean_c) <= G2B_MAX_MEAN_ABS_PCT_DIFF and len(median_moved) <= G2B_MAX_CELL_SHARE * n
    c_ok = abs(rate_x - rate_c) <= G2C_MAX_REQUEST_RATE_DIFF_PCT
    return {
        "cells": n,
        "allowedCells": math.floor(G2A_MAX_CHANGED_SHARE * n + 1e-9),
        "g2a": {"changed": changed, "ok": a_ok},
        "g2b": {
            "meanAbsPctX": mean_x,
            "meanAbsPctCurrent": mean_c,
            "medianMoved": median_moved,
            "ok": b_ok,
        },
        "g2c": {"rateX": rate_x, "rateCurrent": rate_c, "ok": c_ok},
        "ok": a_ok and b_ok and c_ok,
        "status": "통과" if a_ok and b_ok and c_ok else "실패",
    }


def violation_count(data: Data, arm: str) -> tuple[int, Counter[str]]:
    """G2d: N 군 판정 스탯 출력 + E 군의 오독 아닌 판정 스탯 출력에서, 위반이 하나라도 있는 (호출, 스탯) 수."""
    count = 0
    kinds: Counter[str] = Counter()
    for input_id in data.input_ids():
        spec = data.specs[input_id]
        for call in _valid(data.get(input_id, arm)):
            misread = misread_stats(call, spec)
            for stat in spec.judged():
                if stat.stat_id in misread:
                    continue
                found = rule_violations(call, spec, stat)
                if found:
                    count += 1
                    kinds.update(found)
    return count, kinds


def anomaly_count(data: Data, arm: str) -> tuple[int, Counter[str]]:
    """G2e: 형식 이상이 하나라도 있는 호출 수(E·N 전 호출)."""
    count = 0
    kinds: Counter[str] = Counter()
    for input_id in data.input_ids():
        spec = data.specs[input_id]
        for call in data.get(input_id, arm):
            found = format_anomalies(call, spec)
            if found:
                count += 1
                kinds.update(found)
    return count, kinds


def verdict(data: Data, arm: str) -> dict[str, Any]:
    r1 = g1(data, arm)
    r2 = g2abc(data, arm)
    d_x, d_kinds = violation_count(data, arm)
    d_c, _ = violation_count(data, "current")
    e_x, e_kinds = anomaly_count(data, arm)
    e_c, _ = anomaly_count(data, "current")
    d_ok = d_x <= d_c + G2D_MAX_EXCESS
    e_ok = e_x <= e_c + G2E_MAX_EXCESS
    if r1["ok"] is None or r2["ok"] is None:
        final = "판정 불가"
    elif not (r1["ok"] and r2["ok"] and d_ok and e_ok):
        final = "실패"
    elif not r1["informative"]:
        final = "비정보적 — 사용자 판단"
    else:
        final = "통과"
    return {
        "arm": arm,
        "g1": r1,
        "g2abc": r2,
        "g2d": {"x": d_x, "current": d_c, "kinds": dict(d_kinds), "ok": d_ok},
        "g2e": {"x": e_x, "current": e_c, "kinds": dict(e_kinds), "ok": e_ok},
        "final": final,
    }


# ── 관찰 ────────────────────────────────────────────────────────────────────


def _fmt_num(value: float) -> str:
    return f"{value:g}"


def request_distribution(data: Data, input_id: str, stat: Stat, arm: str) -> str:
    """원 출력의 값 분포(마지막 항목). 시작값과 같은 값은 '=' 로, 출력에 없으면 '없음'."""
    spec = data.specs[input_id]
    counts: Counter[str] = Counter()
    for call in data.get(input_id, arm):
        if call.error is not None:
            counts["오류"] += 1
            continue
        value = call.last_values().get(stat.stat_id)
        if value is None:
            counts["없음"] += 1
        elif value == spec.start[stat.stat_id]:
            counts["="] += 1
        else:
            counts[_fmt_num(value)] += 1
    return " · ".join(f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def usage_summary(data: Data, arm: str) -> dict[str, Any]:
    calls = [c for c in data.calls if c.arm == arm]
    prompt = [c.tokens["prompt"] for c in calls if c.tokens and c.tokens.get("prompt") is not None]
    out = [c.tokens["candidates"] for c in calls if c.tokens and c.tokens.get("candidates") is not None]
    cached = Counter(repr(c.tokens.get("cached")) if c.tokens else "토큰 없음" for c in calls)
    cost = 0.0
    for c in calls:
        if not c.tokens or c.model is None or c.tokens.get("prompt") is None:
            continue
        usd = estimate_cost_usd(
            c.model,
            input_tokens=c.tokens["prompt"] or 0,
            cached_tokens=c.tokens.get("cached") or 0,
            output_tokens=c.tokens.get("candidates") or 0,
            thoughts_tokens=c.tokens.get("thoughts") or 0,
        )
        cost += usd or 0.0
    latency = [c.latency_ms for c in calls if c.latency_ms is not None]
    items = Counter(len(c.raw_changes()) for c in calls if c.error is None)
    return {
        "calls": len(calls),
        "promptTokensMean": statistics.fmean(prompt) if prompt else None,
        "outputTokensMean": statistics.fmean(out) if out else None,
        "cached": dict(cached),
        "usd": cost,
        "latencyMedianMs": statistics.median(latency) if latency else None,
        "outputItems": dict(sorted(items.items())),
    }


# ── 출력 ────────────────────────────────────────────────────────────────────


def _ok(value: bool | None) -> str:
    return "—" if value is None else ("O" if value else "**X**")


def _p(value: float | None) -> str:
    return "—" if value is None else f"{value:.3g}"


def render(data: Data, results: dict[str, dict[str, Any]], whatif: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = ["# 스탯 판정 형식 갈래 판정", ""]
    lines.append(f"입력 {len(data.input_ids())}개, 호출 줄 {len(data.calls)}개, 갈래 {', '.join(data.arms())}.")
    lines += ["", "## 판정", "", "| 갈래 | G1 | G2a–c | G2d | G2e | 판정 |", "|---|---|---|---|---|---|"]
    for arm, r in results.items():
        lines.append(
            f"| {ARM_LABEL[arm]} | {r['g1']['status']} | {r['g2abc']['status']} | {_ok(r['g2d']['ok'])} | "
            f"{_ok(r['g2e']['ok'])} | **{r['final']}** |"
        )
    gate_l = results.get("L", {}).get("final")
    gate_b = results.get("B", {}).get("final")
    lines += ["", f"- L 게시 조건(L 통과): {gate_l}", f"- A 병합 조건(L+A 통과): {gate_b}"]

    lines += ["", "## G1 오독 감소(E 군)", "", "| 갈래 | 오독 호출 | 현행 | Fisher 단측 p | 원천별 X≤현행 | 상태 |"]
    lines.append("|---|---|---|---|---|---|")
    for arm, r in results.items():
        g = r["g1"]
        groups = ", ".join(f"{k} {v['x']}/{v['xn']} vs {v['c']}/{v['cn']}" for k, v in sorted(g["perGroup"].items()))
        lines.append(
            f"| {ARM_LABEL[arm]} | {g['x']}/{g['xn']} | {g['current']}/{g['currentN']} | {_p(g['p'])} | "
            f"{_ok(g['perSourceOk'])} ({groups}) | {g['status']} |"
        )

    lines += ["", "## G2 정상 판정 불변", ""]
    lines.append(
        "| 갈래 | 칸 | G2a 방향 바뀐 칸(허용) | G2b 평균 |Δ%| X/현행 | G2b 중앙 이동 칸 | G2c 요청률 X/현행 | G2d 위반 X/현행 | G2e 이상 X/현행 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for arm, r in results.items():
        a = r["g2abc"]
        if a["cells"] == 0:
            abc = "— | — | — | —"
        else:
            abc = (
                f"{len(a['g2a']['changed'])} ({a['allowedCells']}) {_ok(a['g2a']['ok'])} | "
                f"{a['g2b']['meanAbsPctX']:.2f}/{a['g2b']['meanAbsPctCurrent']:.2f} | "
                f"{len(a['g2b']['medianMoved'])} {_ok(a['g2b']['ok'])} | "
                f"{a['g2c']['rateX']:.1f}%/{a['g2c']['rateCurrent']:.1f}% {_ok(a['g2c']['ok'])}"
            )
        lines.append(
            f"| {ARM_LABEL[arm]} | {a['cells']} | {abc} | {r['g2d']['x']}/{r['g2d']['current']} {r['g2d']['kinds'] or ''} "
            f"{_ok(r['g2d']['ok'])} | {r['g2e']['x']}/{r['g2e']['current']} {r['g2e']['kinds'] or ''} {_ok(r['g2e']['ok'])} |"
        )
    for arm, r in results.items():
        a = r["g2abc"]
        if a["cells"] and (a["g2a"]["changed"] or a["g2b"]["medianMoved"]):
            lines.append(
                f"- {ARM_LABEL[arm]}: 방향 바뀐 칸 {a['g2a']['changed']}, 중앙 이동 칸 {a['g2b']['medianMoved']}"
            )

    if whatif:
        lines += ["", "### 관찰(판정 밖): E 군 칸까지 G2a–c 에 넣으면", ""]
        lines.append("| 갈래 | 경우 | 칸 | 방향 바뀐 칸 | 중앙 이동 칸 | 평균 |Δ%| X/현행 | 요청률 X/현행 |")
        lines.append("|---|---|---|---|---|---|---|")
        for key, r in whatif.items():
            arm, case = key.split("|")
            if r["cells"] == 0:
                continue
            lines.append(
                f"| {ARM_LABEL[arm]} | {case} | {r['cells']} | {len(r['g2a']['changed'])} {r['g2a']['changed']} | "
                f"{len(r['g2b']['medianMoved'])} | {r['g2b']['meanAbsPctX']:.2f}/{r['g2b']['meanAbsPctCurrent']:.2f} | "
                f"{r['g2c']['rateX']:.1f}%/{r['g2c']['rateCurrent']:.1f}% |"
            )

    lines += ["", "## 입력별 요청값 분포(원 출력, 마지막 항목)", ""]
    for input_id in data.input_ids():
        spec = data.specs[input_id]
        mis = {a: sum(is_misread_call(c, spec) for c in data.get(input_id, a)) for a in data.arms()}
        mis_text = ", ".join(f"{ARM_LABEL[a]} {v}" for a, v in mis.items()) if spec.is_e else "N 군(오독 정의 없음)"
        lines += [f"### {input_id} ({spec.group}) — 오독 호출: {mis_text}", ""]
        lines.append("| 스탯 | 시작값 | " + " | ".join(ARM_LABEL[a] for a in data.arms()) + " |")
        lines.append("|---|---|" + "---|" * len(data.arms()))
        for stat in spec.stats:
            tag = " (카운터)" if stat.is_counter else ""
            cells = " | ".join(request_distribution(data, input_id, stat, a) for a in data.arms())
            lines.append(f"| {stat.name}{tag} | {_fmt_num(spec.start[stat.stat_id])} | {cells} |")
        lines.append("")

    lines += [
        "## 토큰·원가·지연(관찰)",
        "",
        "| 갈래 | 호출 | 입력 토큰 평균 | 출력 토큰 평균 | cached | 원가 $ | 지연 중앙 ms | 출력 항목 수 |",
    ]
    lines.append("|---|---|---|---|---|---|---|---|")
    total = 0.0
    for arm in data.arms():
        u = usage_summary(data, arm)
        total += u["usd"]
        pt = "—" if u["promptTokensMean"] is None else f"{u['promptTokensMean']:.1f}"
        ot = "—" if u["outputTokensMean"] is None else f"{u['outputTokensMean']:.1f}"
        lat = "—" if u["latencyMedianMs"] is None else f"{u['latencyMedianMs']:.0f}"
        lines.append(
            f"| {ARM_LABEL[arm]} | {u['calls']} | {pt} | {ot} | {u['cached']} | {u['usd']:.6f} | {lat} | {u['outputItems']} |"
        )
    lines += ["", f"원가 합계 ${total:.6f}.", ""]
    return "\n".join(lines)


def analyze(data: Data) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    results = {arm: verdict(data, arm) for arm in TREATMENTS if arm in data.arms()}
    whatif: dict[str, dict[str, Any]] = {}
    for arm in results:
        whatif[f"{arm}|E 포함·오독 출력 뺌"] = g2abc(data, arm, include_e=True, drop_misread=True)
        whatif[f"{arm}|E 포함·오독 출력 그대로"] = g2abc(data, arm, include_e=True, drop_misread=False)
    return results, whatif


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inputs-dir", help="입력 JSON 디렉터리(*.json 전부, 하위 디렉터리 제외)")
    parser.add_argument("--input-json", action="append", default=[], help="입력 JSON(여럿)")
    parser.add_argument("--replay", action="append", required=True, help="리플레이 jsonl(여럿)")
    parser.add_argument("--assign", action="append", default=[], help="<jsonl>=<입력 JSON> — inputId 없는 옛 줄용")
    parser.add_argument("--reps", type=int, required=True, help="입력 × 갈래마다 있어야 하는 호출 수")
    parser.add_argument("--out", help="마크다운 결과 파일(없으면 표준 출력)")
    parser.add_argument("--json", help="판정 결과 JSON 파일")
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.input_json]
    if args.inputs_dir:
        paths += sorted(p for p in Path(args.inputs_dir).glob("*.json") if p.name[:2] in ("E1", "E2", "N1", "N2"))
    specs: dict[str, InputSpec] = {}
    by_path: dict[Path, InputSpec] = {}
    for path in paths:
        spec = input_from_json(json.loads(path.read_text(encoding="utf-8")))
        specs[spec.input_id] = spec
        by_path[path.resolve()] = spec
    assigned: dict[Path, InputSpec] = {}
    for item in args.assign:
        jsonl, input_json = item.split("=", 1)
        spec = input_from_json(json.loads(Path(input_json).read_text(encoding="utf-8")))
        specs[spec.input_id] = spec
        assigned[Path(jsonl).resolve()] = spec
    calls: list[Call] = []
    for replay in args.replay:
        calls += load_calls(Path(replay), assigned.get(Path(replay).resolve()))
    data = Data(specs=specs, calls=calls)
    check_counts(data, args.reps)
    results, whatif = analyze(data)
    text = render(data, results, whatif)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.json:
        Path(args.json).write_text(json.dumps({"results": results, "whatif": whatif}, ensure_ascii=False, indent=1))
    for arm, r in results.items():
        print(f"{ARM_LABEL[arm]}: {r['final']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
