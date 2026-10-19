"""유료 호출 원장과 예산 견적.

원장(`ledger.jsonl`)은 호출마다 한 줄: 승인 묶음·단계·call_site·모델·토큰(입력 전체·캐시 읽기·캐시 쓰기·출력·사고)·단가표
원가·누적(원장 전체와 그 묶음). 승인은 묶음(한 번의 측정 승인)마다 받으므로 멈춤 판정은 그 묶음의 누적만 본다 — 앞 묶음의 지출이
이번 묶음의 멈춤 선을 먼저 채우지 않게. 다음 호출 견적을 더해 묶음 상한이나 멈춤 선을 넘을 것 같으면 그 호출 전에 멈춘다
(`BudgetExceededError` → CLI 종료 코드 20). 상한·멈춤 선은 승인 값이라 런마다 실행 인자로 받는다(기본값이 있으면 상한만 올린
실행이 옛 멈춤 선에서 조용히 먼저 멈춘다).

단가는 앱 단가표가 먼저이고, 앱 단가표에 아직 없는 모델(Haiku 5.5 — 단가 줄은 직결 구조화 호출을 고치는 변경에서 들어온다 —
과 임베딩 오프라인 비교의 Voyage·Gemini 임베딩 모델)만 여기의 보충표에서 읽는다. 보충표에도 없으면 원가를 모르는 유료 호출이므로 거부한다. 입력 토큰은 캐시 읽기·쓰기를 포함한
전체다(앱 단가 계산과 같은 뜻)."""

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api.llm.pricing import MODEL_PRICES, ModelPrice

from memory_eval.plants import PlantSet, checkpoints, opus_probes

# 앱 단가표에 아직 없는 모델. Haiku 5.5: 입력 0.10 · 캐시 읽기 0.01 · 출력 0.50 · 5분 캐시 쓰기 0.125 (프롬프트 100K 토큰 이하 단가).
SUPPLEMENTARY_PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(0.10, 0.01, 0.50, cache_write_usd_per_million=0.125),
    # 임베딩은 입력 토큰만 값이 있다(100만 토큰당 정가, 무료 몫은 원장 원가에서 빼지 않는다).
    "voyage-4-lite": ModelPrice(0.02, 0.02, 0.0),
    "voyage-4": ModelPrice(0.06, 0.06, 0.0),
    "voyage-4-large": ModelPrice(0.12, 0.12, 0.0),
    "gemini-embedding-2": ModelPrice(0.20, 0.20, 0.0),
}

EXIT_BUDGET = 20


class BudgetExceededError(Exception):
    pass


def price_for(model: str) -> ModelPrice:
    price = MODEL_PRICES.get(model) or SUPPLEMENTARY_PRICES.get(model)
    if price is None:
        raise KeyError(f"단가를 모르는 모델: {model}")
    return price


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    cached_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
    thoughts_tokens: int,
) -> float:
    price = price_for(model)
    uncached = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    return (
        uncached * price.input_usd_per_million
        + cached_tokens * price.cached_input_usd_per_million
        + cache_write_tokens * price.cache_write_usd_per_million
        + (output_tokens + thoughts_tokens) * price.output_usd_per_million
    ) / 1_000_000


# 원장 요약에서 단계 칸이 없는 줄(하네스 전에 손으로 남긴 줄)을 묶는 이름.
NO_STAGE = "(단계 없음)"


def row_cost(row: Mapping[str, Any]) -> float:
    """원장 한 줄의 원가. 하네스가 쓰는 줄은 `costUsd`, 하네스 전에 손으로 남긴 줄은 `cost_usd` 다 — 둘 다 상한 계산에 든다."""
    if "costUsd" in row:
        return float(row["costUsd"])
    if "cost_usd" in row:
        return float(row["cost_usd"])
    raise KeyError(f"원가 칸이 없는 원장 줄: {sorted(row)}")


class Ledger:
    def __init__(
        self, path: Path, *, cap_usd: float = math.inf, halt_usd: float | None = None, bundle: str | None = None
    ) -> None:
        self.path = path
        # 묶음 상한(넘지 않는다)과 멈춤 선(닿으면 멈추고 묻는다, 없으면 상한만 본다). 멈춤 선을 상한보다 높게 주어도 상한이 이긴다.
        self.cap_usd = cap_usd
        self.halt_usd = halt_usd
        # 승인 묶음. 없으면 원장 전체를 한 묶음으로 본다(유료 실행은 CLI 가 묶음을 요구한다).
        self.bundle = bundle

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def total_usd(self) -> float:
        return sum(row_cost(r) for r in self.rows())

    def bundle_usd(self) -> float:
        """이 묶음의 누적. 묶음 칸이 없는 옛 줄은 어느 묶음에도 들지 않는다."""
        if self.bundle is None:
            return self.total_usd()
        return sum(row_cost(r) for r in self.rows() if r.get("bundle") == self.bundle)

    def append(
        self,
        *,
        stage: str,
        call_site: str,
        model: str,
        input_tokens: int,
        cached_tokens: int,
        cache_write_tokens: int,
        output_tokens: int,
        thoughts_tokens: int,
        note: str = "",
    ) -> dict[str, Any]:
        cost = cost_usd(
            model,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
        )
        row = {
            "at": datetime.now(UTC).isoformat(),
            "bundle": self.bundle,
            "stage": stage,
            "callSite": call_site,
            "model": model,
            "inputTokens": input_tokens,
            "cachedTokens": cached_tokens,
            "cacheWriteTokens": cache_write_tokens,
            "outputTokens": output_tokens,
            "thoughtsTokens": thoughts_tokens,
            "costUsd": cost,
            "cumulativeUsd": self.total_usd() + cost,
            "bundleCumulativeUsd": self.bundle_usd() + cost,
            "note": note,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def check_headroom(self, next_estimate_usd: float) -> None:
        total = self.bundle_usd()
        limit = self.cap_usd if self.halt_usd is None else min(self.cap_usd, self.halt_usd)
        if total + next_estimate_usd > limit:
            name = "상한" if limit == self.cap_usd else "멈춤 선"
            where = f"묶음 {self.bundle} " if self.bundle is not None else ""
            raise BudgetExceededError(
                f"{where}누적 ${total:.4f} + 다음 견적 ${next_estimate_usd:.4f} 가 {name} ${limit:.2f} 를 넘는다"
                " — 멈추고 묻는다"
            )


def opus_turns_per_arm(plant_set: PlantSet) -> int:
    return sum(len(p.turns) for cp in checkpoints(plant_set) for p in opus_probes(plant_set, cp))


def budget_estimate(
    plant_set: PlantSet,
    *,
    arms: int,
    opus_turn_usd: float,
    server_judgment_turn_usd: float,
    extras: Mapping[str, float],
    cap_usd: float,
) -> dict[str, Any]:
    """사전 등록 견적식: Opus = 턴 수 × 턴당 상한, 서버측 판정 = 턴 수 × 턴당 판정 원가, 그 밖은 단계별 고정 견적."""
    per_arm = opus_turns_per_arm(plant_set)
    turns = per_arm * arms
    opus = turns * opus_turn_usd
    judgment = turns * server_judgment_turn_usd
    extra_total = sum(extras.values())
    total = opus + judgment + extra_total
    probes = {cp: len(opus_probes(plant_set, cp)) for cp in checkpoints(plant_set)}
    two_turn = {cp: sum(1 for p in opus_probes(plant_set, cp) if p.two_turn) for cp in checkpoints(plant_set)}
    return {
        "probesPerCheckpoint": probes,
        "twoTurnPerCheckpoint": two_turn,
        "opusTurnsPerArm": per_arm,
        "arms": arms,
        "opusTurns": turns,
        "opusUsd": opus,
        "serverJudgmentUsd": judgment,
        "extras": dict(extras),
        "totalUsd": total,
        "capUsd": cap_usd,
        "headroomUsd": cap_usd - total,
        "breakEvenOpusTurnUsd": (cap_usd - judgment - extra_total) / turns if turns else math.inf,
    }


def opus_turn_cost_from_usage(usage: Mapping[str, Any]) -> float:
    """턴 기록(`chat_turns.llm_calls`) 한 건의 원가. 칸 이름은 `CallUsage.as_record` 와 같다."""
    return cost_usd(
        str(usage["model"]),
        input_tokens=int(usage.get("promptTokens") or 0),
        cached_tokens=int(usage.get("cachedTokens") or 0),
        cache_write_tokens=int(usage.get("cacheWriteTokens") or 0),
        output_tokens=int(usage.get("outputTokens") or 0),
        thoughts_tokens=int(usage.get("thoughtsTokens") or 0),
    )
