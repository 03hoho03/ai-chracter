"""채팅 모델별 일일 원가 비율 리포트 — 읽기 전용, 자동 조치 없음.

    # 운영: 서빙 중인 api 컨테이너 안에서 (ops/chat-cost-ratio.sh 가 매일 KST 00:50 에 어제 하루를 부른다)
    python -m api.clover.chat_cost_ratio [--date YYYY-MM-DD] [--dry-run] [--ignore-previous]

모델(그 턴에 실제로 쓴 와이어 id `chat_turns.chat_model`)마다 KST 하루의 턴 수, LLM 원가(달러·원), 차감 클로버, 원가 비율,
생성 호출의 캐시 미적중률을 찍는다. 원가 비율 = 원가(원) ÷ (차감 클로버 × `WORST_KRW_PER_CLOVER`).

무엇을 세나:
- 출처는 턴 기록(`chat_turns`) 하나다. 행 하나가 저장된 응답 하나이고, 보내기·수정·재생성 행은 각자 자기 차감과 자기 호출을
  가지므로 셋 다 센다. 실패·환급된 턴은 행이 없어 원가와 차감이 함께 빠진다.
- 차감 클로버는 원장이 아니라 행의 `clover_amount` 합이다 — 원장으로 순차감을 내면 지운 방의 차감은 남고 원가는 사라져 분모만
  커진다.
- 비율의 분자·분모는 클로버로 낸 행(`charge_source='clover'`)뿐이다. 무료·예외 행(`free`·`skipped`, 차감 0)은 건수와 "무료
  포함 총원가"로만 찍는다 — 분모 0 인 원가를 비율에 넣으면 운영자 시험 계정이 경보를 울린다. 경보 표본 수도 유료 행 수다.
- 원가는 그 행의 호출 전부다(생성 + 판정 + 회상 질의 임베딩). 클로버 가격이 "생성과 판정 몫 포함"으로 정해졌으므로 생성만 세면
  가격 산정 기준보다 낮게 나와 경보가 늦다. 출력은 생성(`chat_generate`)과 그 밖으로 나눠 찍는다.
- 클로버 단위 전환 기록의 마지막 행이 전환이 아니면 비율을 내지 않고 실패로 끝난다. 전환이면 그 시각 이상의 행만 센다(같은
  시각은 전환 뒤 — 내역의 옛 단위 표시와 같은 경계).
- 빠지는 것: 미리보기 턴(방 행이 없어 턴 기록이 없다), 백그라운드 호출(요약 접기·기억 추출·임베딩 채우기 — 방의 글쓰기 모델로
  귀속할 수 없다), 실패 턴의 부분 생성 원가.
- 🔴 사용량 일 집계(`scripts/llm_usage_report.py`, Redis)와 더하지 않는다 — 일 집계는 턴 기록에 남는 호출도 같은 자리에서
  함께 세므로 더하면 그 몫이 두 번 들어간다. 스탯 변화(`stat_changes`)는 읽지 않는다.

단가와 환율은 `llm/pricing.py` 다(`call_cost`·`KRW_PER_USD`). 단가표에 없는 모델 id 의 호출은 0 원으로 치지 않는다 — 그러면
비율이 조용히 낮아져 경보가 죽는다. 그 호출이 있는 모델-날은 "판정 불가"(`unpriced N`)이고, 단가 있는 호출만 친 비율(하한)이
이미 100% 를 넘으면 초과로 본다.

경보(마지막 줄 `채팅 원가 경보: …` — 보내는 쪽은 래퍼뿐이고 이 모듈은 어떤 경우에도 보내지 않는다):
- 날 D·모델 m 의 비율 경보 ⇔ D 가 판정 가능일 ∧ 비율 > 100% ∧ D 이전 마지막 판정 가능일(D−1 부터 최대 14일, 전환 시각 이전으로는
  가지 않음)의 비율이 100% 이하이거나 그런 날이 없음. 판정 가능일 = 유료 턴 ≥ 10 이고 단가 없는 호출이 없는 날(있어도 하한이
  100% 초과면 판정 가능). 판정 불가일은 상태를 바꾸지 않는다. 상태를 저장하지 않고 실행 때 이전 날을 다시 계산하므로 같은
  `--date` 는 같은 결론이다.
- 단가 없는 모델 id 알림은 비율 경보와 따로, 그 id 가 D−1 의 유료 행에 없었고 D 의 유료 행에 처음 나온 날에만 싣는다.
- `--ignore-previous` 는 이전 날을 보지 않고 D 만으로 판정한다. 크론을 처음 켤 때 이미 이어지던 초과가 "연속"으로 억제돼
  한 번도 알려지지 않는 것을 막으려고, 설치 직후 한 번만 쓴다(크론 줄에는 넣지 않는다).
- `--dry-run` 은 같은 내용을 `[dry-run] ` 을 붙여 찍어 래퍼의 접두 매칭에 걸리지 않게 한다.

종료 코드: 0 정상(경보 유무 무관), 1 단위 전환 상태가 전환이 아님·DB 오류 등 실패(예외 문장은 표준 오류로만 — 래퍼는 고정
문구로 알린다), 2 인자 오류.
"""

import argparse
import asyncio
import sys
import traceback
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover.unit import load_unit_events
from api.core.rate_limit import KST
from api.db.models.chat import ChatTurn
from api.db.session import async_session_factory, engine
from api.llm import pricing

# 판매 1원에서 부가세·PG 수수료·원작자 몫을 뺀 0.828원을 보너스 20% 상품의 1.2 로 나눈 값 — 클로버 하나로 원가에 쓸 수 있는 돈의
# 최악 기준(원). 상품표에서 유도하지 않는다: 경보 기준을 이 고정값으로 정했다.
WORST_KRW_PER_CLOVER = 0.690
ALERT_PREFIX = "채팅 원가 경보:"
DRY_RUN_PREFIX = "[dry-run] "
# 유료 턴이 이보다 적은 날은 판정하지 않는다 — 몇 턴의 캐시 미적중이 비율을 흔든다.
MIN_PAID_TURNS = 10
# 재경보 억제가 이전 판정 가능일을 찾아 거슬러 가는 최대 일수.
LOOKBACK_DAYS = 14
GENERATE_CALL_SITE = "chat_generate"

Verdict = Literal["over", "ok"]


class UnitStateError(RuntimeError):
    """클로버 단위 전환 기록의 마지막 행이 전환이 아니다(되돌림 상태이거나 기록 없음)."""


@dataclass(frozen=True)
class TurnRow:
    created_at: datetime
    chat_model: str
    kind: str
    charge_source: str
    clover_amount: int
    llm_calls: list[dict[str, Any]]


@dataclass
class ModelDay:
    """한 모델의 KST 하루. `paid_*`·`clovers` 는 클로버로 낸 행만, 나머지는 그 모델의 모든 행이다."""

    paid_turns: int = 0
    other_turns: Counter[str] = field(default_factory=Counter)
    kinds: Counter[str] = field(default_factory=Counter)
    paid_generate_usd: float = 0.0
    paid_other_usd: float = 0.0
    clovers: int = 0
    # 단가 있는 호출만의 원가(무료·예외 행 포함).
    total_usd: float = 0.0
    paid_unpriced: Counter[str] = field(default_factory=Counter)
    unpriced_calls: int = 0
    missing_calls: int = 0
    generate_calls: int = 0
    generate_miss_calls: int = 0
    generate_prompt_tokens: int = 0
    generate_cached_tokens: int = 0

    @property
    def paid_usd(self) -> float:
        return self.paid_generate_usd + self.paid_other_usd

    @property
    def paid_krw(self) -> float:
        return self.paid_usd * pricing.KRW_PER_USD

    @property
    def ratio(self) -> float | None:
        """단가 있는 호출만 친 비율. 단가 없는 호출이 있으면 하한이다."""
        if self.clovers <= 0:
            return None
        return self.paid_krw / (self.clovers * WORST_KRW_PER_CLOVER)


Days = dict[date, dict[str, ModelDay]]


@dataclass(frozen=True)
class Alerts:
    over: list[tuple[str, ModelDay]]
    # 이날 처음 나온 단가 없는 모델 id → 유료 행의 호출 수.
    new_unpriced: dict[str, int]


def summarize(rows: Sequence[TurnRow]) -> Days:
    days: Days = {}
    for row in rows:
        day = days.setdefault(row.created_at.astimezone(KST).date(), {})
        summary = day.setdefault(row.chat_model, ModelDay())
        summary.kinds[row.kind] += 1
        paid = row.charge_source == "clover"
        if paid:
            summary.paid_turns += 1
            summary.clovers += row.clover_amount
        else:
            summary.other_turns[row.charge_source] += 1
        for call in row.llm_calls:
            cost = pricing.call_cost(call)
            generate = cost.call_site == GENERATE_CALL_SITE
            summary.missing_calls += cost.missing_tokens
            if generate:
                cached = call.get("cachedTokens")
                cached_tokens = cached if isinstance(cached, int) else 0
                prompt = call.get("promptTokens")
                summary.generate_calls += 1
                summary.generate_miss_calls += cached_tokens == 0
                summary.generate_cached_tokens += cached_tokens
                summary.generate_prompt_tokens += prompt if isinstance(prompt, int) else 0
            if cost.usd is None:
                summary.unpriced_calls += 1
                if paid:
                    summary.paid_unpriced[cost.model] += 1
                continue
            summary.total_usd += cost.usd
            if paid and generate:
                summary.paid_generate_usd += cost.usd
            elif paid:
                summary.paid_other_usd += cost.usd
    return days


def verdict(summary: ModelDay | None) -> Verdict | None:
    """판정 가능일이면 초과·이하, 아니면(표본 부족·차감 없음·단가 없는 호출이 있고 하한이 100% 이하) None."""
    if summary is None or summary.paid_turns < MIN_PAID_TURNS:
        return None
    ratio = summary.ratio
    if ratio is None:
        return None
    if ratio > 1:
        return "over"
    if summary.paid_unpriced:
        return None
    return "ok"


def _previous_verdict(days: Days, model: str, day: date) -> Verdict | None:
    for back in range(1, LOOKBACK_DAYS + 1):
        found = verdict(days.get(day - timedelta(days=back), {}).get(model))
        if found is not None:
            return found
    return None


def decide_alerts(days: Days, day: date, *, ignore_previous: bool) -> Alerts:
    today = days.get(day, {})
    over = [
        (model, summary)
        for model, summary in sorted(today.items())
        if verdict(summary) == "over" and (ignore_previous or _previous_verdict(days, model, day) != "over")
    ]
    unpriced: Counter[str] = Counter()
    for summary in today.values():
        unpriced.update(summary.paid_unpriced)
    seen_before: set[str] = set()
    if not ignore_previous:
        for summary in days.get(day - timedelta(days=1), {}).values():
            seen_before.update(summary.paid_unpriced)
    new_unpriced = {model: count for model, count in sorted(unpriced.items()) if model not in seen_before}
    return Alerts(over=over, new_unpriced=new_unpriced)


def _unpriced_text(counts: Counter[str] | dict[str, int]) -> str:
    return ", ".join(f"{model} {count}건" for model, count in sorted(counts.items()))


def _ratio_text(summary: ModelDay) -> str:
    ratio = summary.ratio
    if ratio is None:
        return "-"
    unpriced = sum(summary.paid_unpriced.values())
    if unpriced and ratio <= 1:
        return f"판정 불가(unpriced {unpriced})"
    text_ = f"{ratio:.1%}"
    if unpriced:
        text_ = f"{text_} 이상(하한, unpriced {unpriced})"
    if summary.paid_turns < MIN_PAID_TURNS:
        text_ = f"{text_} 표본 부족"
    return text_


def _model_line(model: str, s: ModelDay) -> str:
    krw = pricing.KRW_PER_USD
    kinds = " ".join(f"{kind} {count}" for kind, count in sorted(s.kinds.items()))
    miss_tokens = (
        "-" if s.generate_prompt_tokens <= 0 else f"{1 - s.generate_cached_tokens / s.generate_prompt_tokens:.1%}"
    )
    miss_calls = "-" if s.generate_calls == 0 else f"{s.generate_miss_calls / s.generate_calls:.1%}"
    return (
        f"{model}: 유료 {s.paid_turns}턴 · 무료 {s.other_turns['free']} · 예외 {s.other_turns['skipped']} ({kinds})"
        f" | 원가 ${s.paid_usd:.4f} = {s.paid_krw:,.0f}원"
        f" (생성 {s.paid_generate_usd * krw:,.0f} / 그 밖 {s.paid_other_usd * krw:,.0f})"
        f" | 차감 {s.clovers:,}클로버 | 비율 {_ratio_text(s)}"
        f" | 무료 포함 총원가 {s.total_usd * krw:,.0f}원"
        f" | 생성 캐시 미적중 호출 {s.generate_miss_calls}/{s.generate_calls} ({miss_calls}) · 토큰 {miss_tokens}"
        f" | missing {s.missing_calls} · unpriced {s.unpriced_calls}"
    )


def _alert_line(day: date, alerts: Alerts) -> str:
    parts = []
    for model, s in alerts.over:
        part = f"{model} 비율 {s.ratio or 0:.1%} (유료 {s.paid_turns}턴, 원가 {s.paid_krw:,.0f}원, 차감 {s.clovers:,}클로버)"
        if s.paid_unpriced:
            part += f" — 하한, 단가 없는 호출: {_unpriced_text(s.paid_unpriced)}"
        parts.append(part)
    if alerts.new_unpriced:
        parts.append(f"단가 없는 호출 새로 나옴: {_unpriced_text(alerts.new_unpriced)}")
    return f"{ALERT_PREFIX} {day} " + "; ".join(parts) + " — 자동 조치 없음"


def build_output(rows: Sequence[TurnRow], day: date, *, dry_run: bool, ignore_previous: bool) -> list[str]:
    """표준출력 줄. 보낼 경보가 있으면 마지막 줄이 `ALERT_PREFIX` 로 시작한다(`dry_run` 이면 그 앞에 `DRY_RUN_PREFIX`)."""
    days = summarize(rows)
    today = days.get(day, {})
    lines = [
        f"채팅 원가 비율 {day} (KST) — 1달러 {pricing.KRW_PER_USD:,}원, 1클로버 {WORST_KRW_PER_CLOVER}원(보너스 20% 상품 기준),"
        f" 원가는 생성+판정+질의 임베딩, 비율은 클로버로 낸 턴만"
    ]
    lines += [_model_line(model, summary) for model, summary in sorted(today.items())] or ["(그날 턴 기록 없음)"]
    lines.append("미포함: 미리보기 턴·백그라운드(요약 접기·기억 추출·임베딩 채우기)·실패 턴")
    alerts = decide_alerts(days, day, ignore_previous=ignore_previous)
    if alerts.over or alerts.new_unpriced:
        lines.append((DRY_RUN_PREFIX if dry_run else "") + _alert_line(day, alerts))
    else:
        lines.append("경보 없음")
    return lines


async def load_rows(session: AsyncSession, day: date) -> list[TurnRow]:
    """단위 전환 시각과 D−14 0시(KST) 중 늦은 쪽부터 D 다음 날 0시 전까지의 턴 기록 — 반열린 구간 하나로 읽는다."""
    events = await load_unit_events(session)
    if not events or events[-1].action != "convert":
        raise UnitStateError("클로버 단위 전환 기록이 전환이 아니다 — 비율을 내지 않는다")
    start = max(events[-1].occurred_at, datetime.combine(day - timedelta(days=LOOKBACK_DAYS), time.min, tzinfo=KST))
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=KST)
    result = await session.execute(
        select(
            ChatTurn.created_at,
            ChatTurn.chat_model,
            ChatTurn.kind,
            ChatTurn.charge_source,
            ChatTurn.clover_amount,
            ChatTurn.llm_calls,
        ).where(ChatTurn.created_at >= start, ChatTurn.created_at < end)
    )
    return [TurnRow(*row) for row in result.all()]


async def read_rows(day: date) -> list[TurnRow]:
    async with async_session_factory() as session, session.begin():
        # 첫 문장이어야 이 트랜잭션에 걸린다 — 운영 DB 에서 도는 리포트라 실수로라도 쓰지 못하게.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return await load_rows(session, day)


async def _load(day: date) -> list[TurnRow]:
    try:
        return await read_rows(day)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=date.fromisoformat, help="KST 날짜(기본: 어제)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ignore-previous", action="store_true")
    args = parser.parse_args(argv)
    day: date = args.date or datetime.now(KST).date() - timedelta(days=1)
    try:
        rows = asyncio.run(_load(day))
    except UnitStateError as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception:
        # 로그 파일(VM)에만 남는다. 알림은 래퍼가 고정 문구로 보낸다 — 예외 문장에는 SQL 인자가 섞일 수 있다.
        traceback.print_exc()
        return 1
    print("\n".join(build_output(rows, day, dry_run=args.dry_run, ignore_previous=args.ignore_previous)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
