"""채팅 모델별 일일 원가 비율 리포트(`api.clover.chat_cost_ratio`).

순수 집계(턴 기록 행 → 모델·날짜별 요약 → 경보 판정·출력 줄)를 주로 치고, DB 를 거치는 것은 단위 전환 컷과 읽기 전용
트랜잭션 확인뿐이다. 원가는 단가표에 시험용 모델 한 줄(입력·출력 모두 100만 토큰당 1달러)을 끼워 손으로 셀 수 있게 한다 —
실제 단가표 값이 바뀌어도 이 테스트가 흔들리지 않는다. 기대 비율과 원 환산은 상수가 아니라 이 파일의 숫자(1,400원·0.690원)로
계산한다 — 상수를 바꾸면 빨강이어야 하기 때문이다.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover import chat_cost_ratio as report
from api.core.rate_limit import KST
from api.db.models.clover import CloverUnitEvent
from api.llm import pricing
from api.llm.pricing import ModelPrice
from factories import _make_bare_chat_room, _make_chat_turn

_PRICED = "test-priced-model"
_DAY = date(2026, 10, 28)


@pytest.fixture(autouse=True)
def _test_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력·출력 100만 토큰당 1달러, 캐시 읽기 0.1달러. 출력 10만 토큰 = 0.1달러."""
    monkeypatch.setitem(pricing.MODEL_PRICES, _PRICED, ModelPrice(1.0, 0.1, 1.0))


def _call(call_site: str = "chat_generate", model: str = _PRICED, **tokens: int | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "callSite": call_site,
        "model": model,
        "promptTokens": 0,
        "cachedTokens": 0,
        "cacheWriteTokens": 0,
        "outputTokens": 0,
        "thoughtsTokens": None,
    }
    record.update(tokens)
    return record


def _at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=KST)


def _row(
    day: date = _DAY,
    *,
    chat_model: str = "opus",
    kind: str = "send",
    charge_source: str = "clover",
    clovers: int = 200,
    calls: list[dict[str, Any]] | None = None,
) -> report.TurnRow:
    return report.TurnRow(
        created_at=_at(day),
        chat_model=chat_model,
        kind=kind,
        charge_source=charge_source,
        clover_amount=clovers,
        llm_calls=[_call(outputTokens=100_000)] if calls is None else calls,
    )


def _paid_day(
    day: date, turns: int, *, clovers: int, output_tokens: int = 100_000, chat_model: str = "opus"
) -> list[report.TurnRow]:
    return [
        _row(day, chat_model=chat_model, clovers=clovers, calls=[_call(outputTokens=output_tokens)])
        for _ in range(turns)
    ]


def _over(day: date, turns: int = 10) -> list[report.TurnRow]:
    """턴당 0.1달러(140원) · 200클로버(최악 138원) → 비율 약 101.4%."""
    return _paid_day(day, turns, clovers=200)


def _under(day: date, turns: int = 10) -> list[report.TurnRow]:
    """턴당 0.1달러(140원) · 300클로버(최악 207원) → 비율 약 67.6%."""
    return _paid_day(day, turns, clovers=300)


def _last_line(rows: list[report.TurnRow], *, dry_run: bool = False, ignore_previous: bool = False) -> str:
    return report.build_output(rows, _DAY, dry_run=dry_run, ignore_previous=ignore_previous)[-1]


def _alerts(rows: list[report.TurnRow], *, ignore_previous: bool = False) -> report.Alerts:
    return report.decide_alerts(report.summarize(rows), _DAY, ignore_previous=ignore_previous)


# ── 상수 ──────────────────────────────────────────────────────────────────────
def test_ratio_uses_the_worst_case_0_690_krw_per_clover_and_crosses_100_percent() -> None:
    """유료 10턴, 원가 1달러(1,400원), 차감 2,000클로버 → 1400 ÷ (2000 × 0.690) ≈ 101.4% 로 경보. 0.828 이면 84.5% 라 경보가
    사라진다 — 그 상수가 말없이 바뀌면 여기서 빨강이어야 한다."""
    days = report.summarize(_over(_DAY))
    opus = days[_DAY]["opus"]

    assert opus.clovers == 2_000
    assert opus.ratio == pytest.approx(1400 / (2000 * 0.690))
    assert [model for model, _ in _alerts(_over(_DAY)).over] == ["opus"]


def test_cost_is_converted_at_1400_krw_per_dollar() -> None:
    opus = report.summarize(_over(_DAY))[_DAY]["opus"]

    assert opus.paid_usd == pytest.approx(1.0)
    assert opus.paid_krw == pytest.approx(1400.0)


# ── 표본 문턱 ─────────────────────────────────────────────────────────────────
def test_nine_paid_turns_over_100_percent_do_not_alert_but_ten_do() -> None:
    assert _alerts(_over(_DAY, turns=9)).over == []
    assert [model for model, _ in _alerts(_over(_DAY, turns=10)).over] == ["opus"]


# ── 100% 경계 ─────────────────────────────────────────────────────────────────
def test_a_day_at_exactly_100_percent_does_not_alert() -> None:
    """경보는 100% 를 넘을 때만이다. 턴당 출력 34,500토큰(0.0345달러) · 70클로버 × 10턴 → 원가 0.345 × 1400 = 483원,
    분모 700 × 0.690 = 483원으로 정확히 100%."""
    rows = _paid_day(_DAY, 10, clovers=70, output_tokens=34_500)
    opus = report.summarize(rows)[_DAY]["opus"]

    assert opus.paid_krw == pytest.approx(0.345 * 1400)
    assert opus.clovers * 0.690 == pytest.approx(483)
    assert opus.ratio == 1.0
    assert report.verdict(opus) == "ok"
    assert _alerts(rows).over == []


# ── 재경보 억제 ───────────────────────────────────────────────────────────────
def test_a_second_day_over_in_a_row_does_not_alert_again() -> None:
    rows = _over(_DAY - timedelta(days=1)) + _over(_DAY)

    assert _alerts(rows).over == []


def test_over_after_a_day_at_or_under_100_percent_alerts_again() -> None:
    rows = _over(_DAY - timedelta(days=2)) + _under(_DAY - timedelta(days=1)) + _over(_DAY)

    assert [model for model, _ in _alerts(rows).over] == ["opus"]


def test_a_day_short_of_samples_keeps_the_previous_state() -> None:
    """초과 → 9턴짜리 초과 → 초과 는 연속이다 — 표본 부족일은 판정을 바꾸지 않는다."""
    rows = _over(_DAY - timedelta(days=2)) + _over(_DAY - timedelta(days=1), turns=9) + _over(_DAY)

    assert _alerts(rows).over == []


def test_no_decidable_day_within_fourteen_days_counts_as_no_previous_over() -> None:
    rows = _over(_DAY - timedelta(days=15)) + _over(_DAY)

    assert [model for model, _ in _alerts(rows).over] == ["opus"]


def test_ignore_previous_alerts_on_an_over_streak_that_was_never_reported() -> None:
    """크론을 켜기 전부터 초과가 이어지던 모델은 첫 실행에서 연속으로 억제된다 — 설치 직후 한 번 돌리는 플래그가 그 첫
    경보를 낸다."""
    rows = _over(_DAY - timedelta(days=1)) + _over(_DAY)

    assert _alerts(rows).over == []
    assert [model for model, _ in _alerts(rows, ignore_previous=True).over] == ["opus"]


# ── 무료·예외 턴 ──────────────────────────────────────────────────────────────
def test_free_and_skipped_turns_count_only_toward_the_total_cost() -> None:
    expensive = [_call(outputTokens=10_000_000)]
    rows = [
        *_over(_DAY),
        _row(charge_source="free", clovers=0, calls=expensive),
        _row(charge_source="skipped", clovers=0, calls=expensive),
    ]

    opus = report.summarize(rows)[_DAY]["opus"]

    assert opus.paid_turns == 10
    assert opus.ratio == pytest.approx(1400 / (2000 * 0.690))
    assert opus.total_usd == pytest.approx(1.0 + 10.0 + 10.0)
    assert opus.other_turns == {"free": 1, "skipped": 1}


# ── 단가 없는 모델 ────────────────────────────────────────────────────────────
def test_unpriced_calls_make_the_day_undecidable_instead_of_counting_as_zero() -> None:
    rows = _under(_DAY)
    rows[0] = _row(clovers=300, calls=[_call(outputTokens=100_000), _call("chat_stat_judgment", "no-price-model")])

    opus = report.summarize(rows)[_DAY]["opus"]
    lines = report.build_output(rows, _DAY, dry_run=False, ignore_previous=False)

    assert report.verdict(opus) is None
    assert dict(opus.paid_unpriced) == {"no-price-model": 1}
    assert any("unpriced 1" in line for line in lines)


def test_unpriced_calls_do_not_hide_a_day_whose_priced_calls_alone_cross_100_percent() -> None:
    rows = _over(_DAY)
    rows[0] = _row(clovers=200, calls=[_call(outputTokens=100_000), _call("chat_stat_judgment", "no-price-model")])

    line = _last_line(rows)

    assert line.startswith("채팅 원가 경보:")
    assert "opus" in line
    assert "no-price-model 1건" in line


def test_unpriced_model_id_is_reported_only_on_the_first_day_it_appears() -> None:
    """비율 경보가 없는 날(표본 부족)에도 새 id 는 알린다. 전날에도 있던 id 는 다시 알리지 않는다."""
    unpriced_turn = [_call(outputTokens=1), _call("chat_stat_judgment", "no-price-model")]
    first_day = [_row(clovers=300, calls=unpriced_turn)]

    assert _alerts(first_day).new_unpriced == {"no-price-model": 1}
    assert "no-price-model 1건" in _last_line(first_day)

    second_day = [_row(_DAY - timedelta(days=1), clovers=300, calls=unpriced_turn), *first_day]

    assert _alerts(second_day).new_unpriced == {}
    assert not _last_line(second_day).startswith("채팅 원가 경보:")


def test_unpriced_model_id_seen_on_any_earlier_loaded_day_is_not_new_even_if_absent_the_day_before() -> None:
    """이틀에 한 번 쓰는 모델이 이틀마다 다시 알리지 않게, 전날만이 아니라 읽어 온 이전 날 전부와 비교한다."""
    unpriced_turn = [_call(outputTokens=1), _call("chat_stat_judgment", "no-price-model")]
    rows = [
        _row(_DAY - timedelta(days=2), clovers=300, calls=unpriced_turn),
        _row(_DAY - timedelta(days=1), clovers=300),
        _row(clovers=300, calls=unpriced_turn),
    ]

    assert _alerts(rows).new_unpriced == {}
    assert not _last_line(rows).startswith("채팅 원가 경보:")


def test_unpriced_calls_in_free_turns_do_not_drive_the_alerts() -> None:
    rows = [_row(charge_source="free", clovers=0, calls=[_call("chat_generate", "no-price-model")])]

    assert _alerts(rows).new_unpriced == {}


# ── 원가 범위 ─────────────────────────────────────────────────────────────────
def test_judgment_and_query_embedding_calls_count_and_are_split_from_generation() -> None:
    query_embedding = {
        "callSite": "chat_memory_query_embedding",
        "model": _PRICED,
        "dims": 1024,
        "promptTokens": 300_000,
        "latencyMs": 120,
        "outcome": "ok",
    }
    calls = [
        query_embedding,
        _call(promptTokens=1_000_000, cachedTokens=1_000_000),
        _call("chat_stat_judgment", promptTokens=200_000),
        _call("chat_ending_judgment", promptTokens=100_000),
    ]
    rows = [_row(calls=calls), _row(calls=[_call(promptTokens=1_000_000)])]

    opus = report.summarize(rows)[_DAY]["opus"]

    # 생성: 캐시 읽기 1M × 0.1 + 입력 1M × 1.0. 그 밖: 임베딩 0.3M + 판정 0.2M + 0.1M, 모두 × 1.0.
    assert opus.paid_generate_usd == pytest.approx(0.1 + 1.0)
    assert opus.paid_other_usd == pytest.approx(0.3 + 0.2 + 0.1)
    assert opus.paid_usd == pytest.approx(1.7)
    # 캐시 미적중은 생성 칸만 센다 — 판정·임베딩 칸은 캐시 칸이 0 이어도 세지 않는다.
    assert (opus.generate_calls, opus.generate_miss_calls) == (2, 1)
    assert opus.generate_prompt_tokens == 2_000_000
    assert opus.generate_cached_tokens == 1_000_000


# ── 출력 ──────────────────────────────────────────────────────────────────────
def test_alert_is_the_last_line_and_dry_run_hides_it_from_the_wrappers_prefix_match() -> None:
    rows = _over(_DAY)

    assert _last_line(rows).startswith("채팅 원가 경보:")
    assert "자동 조치 없음" in _last_line(rows)
    dry = _last_line(rows, dry_run=True)
    assert not dry.startswith("채팅 원가 경보:")
    assert dry.startswith("[dry-run] 채팅 원가 경보:")


def test_alerts_for_several_models_share_one_line() -> None:
    rows = _over(_DAY) + _paid_day(_DAY, 10, clovers=200, chat_model="sonnet")

    line = _last_line(rows)

    assert line.startswith("채팅 원가 경보:")
    assert "opus" in line
    assert "sonnet" in line


def test_a_quiet_day_does_not_end_with_the_alert_prefix() -> None:
    assert not _last_line(_under(_DAY)).startswith("채팅 원가 경보:")
    assert not _last_line([]).startswith("채팅 원가 경보:")


def test_main_exits_1_when_the_unit_state_is_not_converted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _refuse(day: date) -> list[report.TurnRow]:
        raise report.UnitStateError("단위 전환 기록이 전환이 아니다")

    monkeypatch.setattr(report, "_load", _refuse)

    assert report.main(["--date", "2026-10-28"]) == 1


# ── DB ────────────────────────────────────────────────────────────────────────
async def _unit_events(db_session: AsyncSession, *events: tuple[str, datetime]) -> None:
    """표를 비우고 주어진 기록만 남긴다. 롤백되는 연결이라 테스트가 끝나면 원래대로 돌아간다."""
    await db_session.execute(delete(CloverUnitEvent))
    db_session.add_all(
        CloverUnitEvent(
            action=action, lock_started_at=at - timedelta(seconds=1), occurred_at=at, money_rows=0, written_by="test"
        )
        for action, at in events
    )
    await db_session.flush()


async def test_turns_before_the_unit_conversion_are_left_out_and_the_boundary_is_kept(
    db_session: AsyncSession,
) -> None:
    room = await _make_bare_chat_room(db_session)
    converted_at = _at(_DAY, hour=9)
    await _unit_events(db_session, ("convert", converted_at))
    db_session.add_all(
        [
            # 전환 전 3원 단위 차감 — 비율에 들어가면 분모가 세 배로 부푼다.
            _make_chat_turn(
                room.id,
                chat_model="opus",
                charge_source="clover",
                clover_amount=70,
                created_at=converted_at - timedelta(seconds=1),
            ),
            _make_chat_turn(
                room.id, chat_model="opus", charge_source="clover", clover_amount=200, created_at=converted_at
            ),
            _make_chat_turn(
                room.id,
                chat_model="opus",
                charge_source="clover",
                clover_amount=200,
                created_at=converted_at + timedelta(hours=1),
            ),
        ]
    )
    await db_session.flush()

    rows = await report.load_rows(db_session, _DAY)
    opus = report.summarize(rows)[_DAY]["opus"]

    assert sorted(row.clover_amount for row in rows) == [200, 200]
    assert (opus.paid_turns, opus.clovers) == (2, 400)


async def test_rows_are_read_from_fourteen_days_before_through_the_end_of_the_kst_day(
    db_session: AsyncSession,
) -> None:
    room = await _make_bare_chat_room(db_session)
    await _unit_events(db_session, ("convert", datetime(2026, 9, 1, tzinfo=UTC)))
    first_kept = datetime.combine(_DAY - timedelta(days=14), datetime.min.time(), tzinfo=KST)
    next_day = datetime.combine(_DAY + timedelta(days=1), datetime.min.time(), tzinfo=KST)
    stamps = {
        1: first_kept - timedelta(seconds=1),
        2: first_kept,
        3: next_day - timedelta(seconds=1),
        4: next_day,
    }
    db_session.add_all(
        _make_chat_turn(room.id, charge_source="clover", clover_amount=amount, created_at=at)
        for amount, at in stamps.items()
    )
    await db_session.flush()

    rows = await report.load_rows(db_session, _DAY)

    assert sorted(row.clover_amount for row in rows) == [2, 3]


@pytest.mark.parametrize("events", [pytest.param(("revert",), id="reverted"), pytest.param((), id="never")])
async def test_unit_state_other_than_converted_refuses_to_report(
    db_session: AsyncSession, events: tuple[str, ...]
) -> None:
    converted_at = _at(_DAY - timedelta(days=3))
    history = [("convert", converted_at)] if events else []
    history += [(action, converted_at + timedelta(days=1)) for action in events]
    await _unit_events(db_session, *history)

    with pytest.raises(report.UnitStateError):
        await report.load_rows(db_session, _DAY)


async def test_report_reads_inside_a_read_only_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _fake_load(session: AsyncSession, day: date) -> list[report.TurnRow]:
        seen.append((await session.execute(text("SHOW transaction_read_only"))).scalar_one())
        return []

    monkeypatch.setattr(report, "load_rows", _fake_load)

    await report.read_rows(_DAY)

    assert seen == ["on"]
