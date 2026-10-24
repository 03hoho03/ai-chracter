"""판정 이유 재현성 — 운영 판정기에 판정 이유를 요구하면 스탯 판정이 달라지는지 잰다.

측정 서버 덤프의 스탯 판정 줄을 운영 판정기 조건 그대로(앱의 Haiku 직결 구현·사고 끔·같은 구조화 깊이) 두 판으로 반복해 다시
보낸다 — 운영 응답 스키마 그대로인 판(`plain`)과, 같은 스키마에 이유 글 칸 하나를 더한 판(`reason`). 프롬프트는 두 판이 같은
바이트다. 측정 판정자(더 큰 모델)로 재면 운영 판정기에 대해 아무것도 말하지 못하므로 판정 모델을 바꾸지 않는다. 운영 판정 출력과
턴 기록은 이 도구와 무관하다 — 이유는 이 도구의 결과 파일에만 남는다.

호출·원장·재실행은 판정기 일치율 도구(`judge_agreement`)를 그대로 쓴다: 두 판을 판정 모델 둘처럼 다뤄 줄마다 두 판을 이어
부르고(한 줄 안에서는 한 판의 반복을 모두 부른 뒤 다른 판으로 넘어간다 — 판이 갈마드는 단위는 호출이 아니라 줄이라, 시간에 따른
공급자 쪽 흔들림이 한 판에만 실리지 않는다), 일치의 단위도 같다(프롬프트에 있던 발동 규칙 id 의 집합).

내는 값(표본 묶음 — 기준선·개발 덤프 — 마다, 그리고 합쳐서):
- 판마다 자기 반복 일치율(전체 줄·발동한 줄), 발동 분포(성공 결과 중 규칙이 하나라도 발동한 비율, 결과당 발동 id 수, 최빈 결과가
  빈 집합인 줄의 비율), 구조화 실패.
- 판 사이 일치율(줄마다 두 판 결과를 하나씩 짝지은 모든 쌍 중 같은 쌍의 비율 평균)과, 같은 줄에서 낸 두 자기 반복 일치율의 평균에서
  판 사이 일치율을 뺀 값과 그 표준오차. 이유 칸이 판정을 바꾸지 않으면 두 판 결과는 한 분포에서 나온 것이라 이 차이의 기대값이
  0 이다 — 자기 반복의 흔들림보다 판 사이가 더 갈려야 양수로 커진다.
- 줄마다 두 판의 최빈 결과가 같은 비율, 이유 글 길이와 빈 이유 수.

표본: 기준선 덤프는 전부(또는 정한 수), 개발 덤프는 정한 수를 방마다 고르게 무작위로. 고르기는 씨앗과 줄 id 로만 정해진다."""

import math
import random
import statistics
from collections import Counter
from collections.abc import Container, Mapping, Sequence
from os.path import commonpath
from pathlib import Path
from typing import Any

from pydantic import ConfigDict

from api.chat.prompt_builder import StatRuleJudgmentResult
from api.llm.client import LLMClient

from memory_eval import judge_agreement as ja
from memory_eval.ledger import cost_usd

STAT_CALL_SITE = "chat_stat_judgment"
PLAIN = "plain"
REASON = "reason"
VARIANTS = (PLAIN, REASON)
ALL_GROUP = "all"
BASELINE_GROUP = "baseline"
DEV_GROUP = "dev"
# 견적의 자리값(호출당 출력 토큰). 이유 없는 판은 id 몇 개라 작고, 이유 판은 글이 붙는다 — 실측(`--baseline-sample 1 --reps 1`)
# 뒤 바꾼다.
DEFAULT_PLAIN_OUTPUT_TOKENS = 60
DEFAULT_REASON_OUTPUT_TOKENS = 400


class ReasonedStatRuleJudgmentResult(StatRuleJudgmentResult):
    # 보내는 스키마의 제목·설명을 운영 스키마와 같게 둔다 — 두 판의 차이가 이유 칸 하나여야 그 칸의 효과를 잰다.
    __doc__ = StatRuleJudgmentResult.__doc__
    model_config = ConfigDict(title=StatRuleJudgmentResult.__name__)

    reason: str


def load_stat_lines(paths: Sequence[Path], *, prefix: str | None = None) -> list[ja.JudgmentLine]:
    """덤프에서 스탯 판정 줄만. `prefix` 가 없으면 줄 id 가 일치율 도구와 같은 꼴(`<파일 이름>:<줄 번호>`)이라 그 도구의 대조군
    명세가 그대로 줄을 집는다. 있으면 파일 이름이 서로 같은 덤프 묶음(프로브마다 같은 이름)으로 보고, 파일 부분을 덤프들의 공통
    상위 폴더에서의 상대 경로로 둔다(`<prefix>/<상대 경로>:<줄 번호>`)."""
    if prefix is None:
        return ja.load_lines(paths, call_sites={STAT_CALL_SITE})
    if not paths:
        return []
    root = Path(commonpath([str(path.resolve().parent) for path in paths]))
    return ja.load_lines(
        paths,
        call_sites={STAT_CALL_SITE},
        name=lambda path: f"{prefix}/{path.resolve().relative_to(root).as_posix()}",
    )


def balanced_sample(lines: Sequence[ja.JudgmentLine], n: int, *, seed: int) -> list[ja.JudgmentLine]:
    """방마다 고르게 `n` 줄. 방(방 id 순)마다 줄 id 순으로 늘어놓고 씨앗으로 섞은 뒤, 방을 돌아가며 하나씩 집는다 — 줄이 모자란
    방은 다 쓰고 남는 몫을 나머지 방이 나눈다. 결과는 줄 id 순."""
    if n > len(lines):
        raise SystemExit(f"표본 {n} 줄을 고를 수 없다 — 줄이 {len(lines)} 개뿐이다")
    rng = random.Random(seed)
    by_room: dict[str, list[ja.JudgmentLine]] = {}
    for line in sorted(lines, key=lambda line: line.line_id):
        by_room.setdefault(str(line.room_id), []).append(line)
    queues = []
    for room in sorted(by_room):
        queue = by_room[room]
        rng.shuffle(queue)
        queues.append(queue)
    picked: list[ja.JudgmentLine] = []
    while len(picked) < n:
        for queue in queues:
            if queue and len(picked) < n:
                picked.append(queue.pop())
    return sorted(picked, key=lambda line: line.line_id)


def variant_models(client: LLMClient, model_id: str, overrides: Mapping[str, Any] | None = None) -> list[ja.JudgeModel]:
    """같은 판정기 하나를 두 판으로 — 이유 없는 판은 판정 줄의 스키마(운영 스키마) 그대로, 이유 판은 이유 칸을 더한 스키마로."""
    settings_overrides = dict(overrides or {})
    return [
        ja.JudgeModel(label=PLAIN, model_id=model_id, client=client, overrides=settings_overrides),
        ja.JudgeModel(
            label=REASON,
            model_id=model_id,
            client=client,
            overrides=settings_overrides,
            response_schema=ReasonedStatRuleJudgmentResult,
        ),
    ]


def estimate(
    lines: Sequence[ja.JudgmentLine],
    reps: int,
    *,
    model_id: str,
    tokens_per_char: float,
    plain_output_tokens: int,
    reason_output_tokens: int,
    done: Container[str] = frozenset(),
) -> dict[str, Any]:
    """호출 수 = 줄 수 × 반복 수 × 두 판. 원가 = 판마다 Σ(프롬프트 글자 × 글자당 토큰의 입력 + 출력 자리값) × 반복.
    `done` 은 결과가 이미 남은 호출 키(`<줄 id>|<판>|<반복>`) — 이어 돌리는 실행은 그 호출을 다시 부르지 않으므로 견적에서 뺀다."""
    per_variant: dict[str, Any] = {}
    for label, output_tokens in ((PLAIN, plain_output_tokens), (REASON, reason_output_tokens)):
        pending = [line for line in lines for rep in range(reps) if f"{line.line_id}|{label}|{rep}" not in done]
        usd = sum(
            cost_usd(
                model_id,
                input_tokens=math.ceil(len(line.prompt) * tokens_per_char),
                cached_tokens=0,
                cache_write_tokens=0,
                output_tokens=output_tokens,
                thoughts_tokens=0,
            )
            for line in pending
        )
        per_variant[label] = {"calls": len(pending), "outputTokensPerCall": output_tokens, "usd": usd}
    return {
        "modelId": model_id,
        "calls": sum(v["calls"] for v in per_variant.values()),
        "reps": reps,
        "promptChars": sum(len(line.prompt) for line in lines),
        "tokensPerChar": tokens_per_char,
        "perVariant": per_variant,
        "totalUsd": sum(v["usd"] for v in per_variant.values()),
    }


# ---------------------------------------------------------------- 집계


def _ordered(calls: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """결과 줄을 (줄, 판, 반복) 순으로 — 최빈 결과의 동률을 파일 순서가 아니라 반복 순서로 가르게."""
    return sorted(calls, key=lambda row: (str(row["lineId"]), str(row["model"]), int(row["rep"])))


def _fire_distribution(
    lines: Sequence[ja.JudgmentLine], ok: Mapping[tuple[str, str], Sequence[Any]], label: str
) -> dict[str, Any]:
    results = [result for line in lines for result in ok.get((line.line_id, label), [])]
    return {
        "results": len(results),
        "fireRate": sum(1 for r in results if r) / len(results) if results else None,
        "meanFiredIds": sum(len(r) for r in results) / len(results) if results else None,
    }


def _reasons(lines: Sequence[ja.JudgmentLine], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = {line.line_id for line in lines}
    texts = [
        str(row.get("extra", {}).get("reason", ""))
        for row in ja.latest_calls(rows).values()
        if row["model"] == REASON and row["status"] == "ok" and row["lineId"] in ids
    ]
    return {
        "meanReasonChars": sum(len(t) for t in texts) / len(texts) if texts else None,
        "emptyReasons": sum(1 for t in texts if not t.strip()),
    }


def _between(lines: Sequence[ja.JudgmentLine], ok: Mapping[tuple[str, str], Sequence[Any]]) -> dict[str, Any]:
    """판 사이 비교 — 두 판 모두 성공이 둘 이상인 줄만(한쪽만 빠진 줄이 섞이면 서로 다른 줄에서 낸 값을 견주게 된다)."""
    gaps: list[float] = []
    crosses: list[float] = []
    for line in lines:
        plain, reason = ok.get((line.line_id, PLAIN), []), ok.get((line.line_id, REASON), [])
        if len(plain) < 2 or len(reason) < 2:
            continue
        cross = ja.cross_agreement(plain, reason)
        plain_self, reason_self = ja.self_agreement(plain), ja.self_agreement(reason)
        if cross is None or plain_self is None or reason_self is None:
            continue
        crosses.append(cross)
        gaps.append((plain_self + reason_self) / 2 - cross)
    modal_pairs = [
        (ja._modal(ok[(line.line_id, PLAIN)]), ja._modal(ok[(line.line_id, REASON)]))
        for line in lines
        if ok.get((line.line_id, PLAIN)) and ok.get((line.line_id, REASON))
    ]
    return {
        "lines": len(crosses),
        "crossAgreement": statistics.fmean(crosses) if crosses else None,
        "selfMinusCross": statistics.fmean(gaps) if gaps else None,
        "selfMinusCrossSe": statistics.stdev(gaps) / math.sqrt(len(gaps)) if len(gaps) >= 2 else None,
        "modalLines": len(modal_pairs),
        "modalAgreement": sum(1 for a, b in modal_pairs if a == b) / len(modal_pairs) if modal_pairs else None,
    }


def _group_summary(lines: Sequence[ja.JudgmentLine], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    site = ja.summarize(lines, rows, candidate=REASON, baseline=PLAIN)["callSites"].get(STAT_CALL_SITE)
    ok: dict[tuple[str, str], list[Any]] = {}
    for row in ja.latest_calls(rows).values():
        if row["status"] == "ok":
            ok.setdefault((str(row["lineId"]), str(row["model"])), []).append(row["result"])
    main = [line for line in lines if line.control is None]
    variants: dict[str, Any] = {}
    for label in VARIANTS:
        model = (site or {}).get("models", {}).get(label, {})
        variants[label] = {
            "selfAgreement": model.get("selfAgreement"),
            "selfAgreementLines": model.get("selfAgreementLines", 0),
            "firedSelfAgreement": model.get("firedSelfAgreement"),
            "firedSelfAgreementLines": model.get("firedSelfAgreementLines", 0),
            "emptyModalRate": model.get("modal", {}).get("emptyRate"),
            **_fire_distribution(main, ok, label),
            "ok": model.get("ok", 0),
            "structuredFailures": model.get("structuredFailures", 0),
            "firstAttemptStructuredFailures": model.get("firstAttemptStructuredFailures", 0),
            "callErrors": model.get("callErrors", 0),
        }
    variants[REASON] |= _reasons(main, rows)
    return {
        "lines": len(main),
        "firedLines": (site or {}).get("firedLines", 0),
        "variants": variants,
        "between": _between(main, ok),
    }


def summarize(
    lines: Sequence[ja.JudgmentLine], groups: Mapping[str, str], calls: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """표본 묶음마다와 합친 것의 비교표, 그리고 망친 입력 대조군이 있으면 판마다 반응(일치율 도구의 정의 그대로)."""
    rows = _ordered(calls)
    out: dict[str, Any] = {ALL_GROUP: _group_summary(lines, rows)}
    for name in sorted({groups[line.line_id] for line in lines if line.control is None}):
        out[name] = _group_summary([line for line in lines if groups.get(line.line_id) == name], rows)
    whole = ja.summarize(lines, rows, candidate=REASON, baseline=PLAIN)
    reaction = {label: whole["controlReaction"].get(label) for label in VARIANTS}
    return {"groups": out, "controls": whole["controls"], "controlReaction": reaction}


# ---------------------------------------------------------------- 표


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_tables(report: Mapping[str, Any]) -> str:
    """보고서에 옮길 표(마크다운). 프롬프트·이유 글은 싣지 않는다 — 수와 비율만."""
    groups: Mapping[str, Any] = report["summary"]["groups"]
    out = ["## 판마다 자기 반복과 발동 분포", ""]
    out.append(
        "| 묶음 | 판 | 줄 | 자기 반복 일치율 | 발동 줄 | 발동 줄 자기 반복 | 발동 비율 | 결과당 발동 id | 최빈 빈 집합 줄 비율 "
        "| 구조화 실패(재시도 뒤 / 첫 시도) | 전송 오류 |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, group in groups.items():
        for label in VARIANTS:
            v = group["variants"][label]
            out.append(
                f"| {name} | {label} | {group['lines']} | {_fmt(v['selfAgreement'])} | {group['firedLines']} "
                f"| {_fmt(v['firedSelfAgreement'])} | {_fmt(v['fireRate'])} | {_fmt(v['meanFiredIds'])} "
                f"| {_fmt(v['emptyModalRate'])} | {v['structuredFailures']} / {v['firstAttemptStructuredFailures']} "
                f"| {v['callErrors']} |"
            )
    out += ["", "## 판 사이", ""]
    out.append(
        "| 묶음 | 비교 줄 | 판 사이 일치율 | 자기 반복 평균 − 판 사이 | 표준오차 | 최빈 결과 같은 줄 비율 | 이유 글 평균 길이 "
        "| 빈 이유 |"
    )
    out.append("|---|---|---|---|---|---|---|---|")
    for name, group in groups.items():
        b, r = group["between"], group["variants"][REASON]
        out.append(
            f"| {name} | {b['lines']} | {_fmt(b['crossAgreement'])} | {_fmt(b['selfMinusCross'])} "
            f"| {_fmt(b['selfMinusCrossSe'])} | {_fmt(b['modalAgreement'])} | {_fmt(r['meanReasonChars'])} "
            f"| {r['emptyReasons']} |"
        )
    reaction = report["summary"].get("controlReaction", {})
    if report["summary"].get("controls"):
        out += ["", "## 망친 입력 대조군", "", "| 판 | 잴 수 있는 대조군 | 반응 | 반대 방향 | 반응률 |", "|---|---|---|---|---|"]
        for label in VARIANTS:
            c = reaction.get(label) or {}
            out.append(
                f"| {label} | {c.get('controls', 0)} | {c.get('reacted', 0)} | {c.get('opposite', 0)} "
                f"| {_fmt(c.get('rate'))} |"
            )
    return "\n".join(out) + "\n"


def group_counts(groups: Mapping[str, str], lines: Sequence[ja.JudgmentLine]) -> dict[str, int]:
    counts = Counter(groups[line.line_id] for line in lines if line.control is None)
    return {name: counts[name] for name in (BASELINE_GROUP, DEV_GROUP) if counts[name]}
