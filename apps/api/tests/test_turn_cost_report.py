"""`scripts/turn_cost_report.py` — 턴 기록(`chat_turns.llm_calls`)의 호출 칸으로 턴당 원가 분포를 내는 읽기 전용 스크립트."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import turn_cost_report as script
from api.llm.pricing import MODEL_PRICES, CallCost, call_cost, estimate_cost_usd
from factories import _make_bare_chat_room, _make_chat_turn


def _generation(call_site: str, model: str, **tokens: int | None) -> dict[str, Any]:
    """공급자 구현이 남기는 생성·판정 칸 모양(`CallUsage.as_record`)."""
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


def _query_embedding(*, tokens: int | None, latency_ms: int, outcome: str) -> dict[str, Any]:
    """임베딩 회상이 켜진 턴의 맨 앞 칸 모양 — 캐시·출력 칸이 없고 차원·지연·결과 칸이 있다."""
    return {
        "callSite": "chat_memory_query_embedding",
        "model": "voyage-4-large",
        "dims": 1024,
        "promptTokens": tokens,
        "latencyMs": latency_ms,
        "outcome": outcome,
    }


def test_generation_call_costs_what_the_price_table_says() -> None:
    call = _generation(
        "chat_generate",
        "claude-opus-5-5",
        promptTokens=10_000,
        cachedTokens=6_000,
        cacheWriteTokens=1_000,
        outputTokens=500,
    )

    cost = call_cost(call)

    expected = estimate_cost_usd(
        "claude-opus-5-5",
        input_tokens=10_000,
        cached_tokens=6_000,
        cache_write_tokens=1_000,
        output_tokens=500,
        thoughts_tokens=0,
    )
    assert cost == CallCost("chat_generate", "claude-opus-5-5", expected, missing_tokens=False)


def test_query_embedding_call_without_cache_or_output_fields_costs_its_input_tokens() -> None:
    cost = call_cost(_query_embedding(tokens=300, latency_ms=120, outcome="ok"))

    assert cost.usd == pytest.approx(300 * MODEL_PRICES["voyage-4-large"].input_usd_per_million / 1_000_000)
    assert cost.missing_tokens is False
    assert cost.call_site == "chat_memory_query_embedding"


def test_call_without_reported_input_tokens_is_flagged_and_priced_on_what_was_reported() -> None:
    """시간 초과로 끊은 질의 임베딩·이미지가 실린 판정은 입력 토큰이 없다 — 0 원으로 숨기지 않고 표시한다."""
    timeout = call_cost(_query_embedding(tokens=None, latency_ms=250, outcome="timeout"))
    image = call_cost(_generation("chat_situational_image", "claude-haiku-5-5", promptTokens=None, outputTokens=40))

    assert timeout == CallCost("chat_memory_query_embedding", "voyage-4-large", 0.0, missing_tokens=True)
    assert image.missing_tokens is True
    assert image.usd == pytest.approx(40 * MODEL_PRICES["claude-haiku-5-5"].output_usd_per_million / 1_000_000)


def test_model_missing_from_price_table_has_no_cost() -> None:
    cost = call_cost(_generation("chat_generate", "unknown-model", promptTokens=1_000, outputTokens=100))

    assert cost.usd is None


def _usd(model: str, *, prompt: int = 0, output: int = 0) -> float:
    value = estimate_cost_usd(model, input_tokens=prompt, cached_tokens=0, output_tokens=output, thoughts_tokens=0)
    assert value is not None
    return value


def test_summary_groups_calls_by_site_and_model_and_distributes_turn_totals() -> None:
    turns = [
        [
            _query_embedding(tokens=100, latency_ms=100, outcome="ok"),
            _generation("chat_generate", "claude-opus-5-5", promptTokens=1_000, outputTokens=100),
            _generation("chat_stat_judgment", "claude-haiku-5-5", promptTokens=500, outputTokens=10),
        ],
        [
            _query_embedding(tokens=None, latency_ms=250, outcome="timeout"),
            _generation("chat_generate", "claude-opus-5-5", promptTokens=3_000, outputTokens=300),
        ],
        [_generation("chat_generate", "unknown-model", promptTokens=1, outputTokens=1)],
        [],
    ]

    summary = script.summarize(turns)

    sites = {(s.call_site, s.model): s for s in summary.sites}
    opus = sites[("chat_generate", "claude-opus-5-5")]
    assert opus.calls == 2
    assert opus.total_usd == pytest.approx(
        _usd("claude-opus-5-5", prompt=1_000, output=100) + _usd("claude-opus-5-5", prompt=3_000, output=300)
    )
    assert opus.max_usd == pytest.approx(_usd("claude-opus-5-5", prompt=3_000, output=300))
    embedding = sites[("chat_memory_query_embedding", "voyage-4-large")]
    assert (embedding.calls, embedding.missing_tokens) == (2, 1)
    unknown = sites[("chat_generate", "unknown-model")]
    assert (unknown.calls, unknown.unpriced, unknown.total_usd) == (1, 1, 0.0)

    first = (
        _usd("voyage-4-large", prompt=100)
        + _usd("claude-opus-5-5", prompt=1_000, output=100)
        + _usd("claude-haiku-5-5", prompt=500, output=10)
    )
    second = _usd("claude-opus-5-5", prompt=3_000, output=300)
    # 단가 없는 호출이 있는 턴은 합계가 낮게 보이므로 분포에서 빼고 따로 센다. 호출이 없는 턴은 0 원 턴이다.
    assert summary.turns == 4
    assert summary.unpriced_turns == 1
    assert sorted(summary.turn_usd) == pytest.approx(sorted([first, second, 0.0]))
    assert summary.query_outcomes == {"ok": 1, "timeout": 1}
    assert summary.query_latency_ms == [100, 250]


def test_summary_collects_both_first_token_latencies_only_from_calls_that_carry_them() -> None:
    """첫 글자 지연 둘은 생성 칸에만 있다. 글 없이 끝난 생성은 키가 없어 분포에 들지 않고, 질의 임베딩의 `latencyMs` 와
    섞지 않는다. 턴 시작부터 잰 값과 스트림 시작부터 잰 값은 각자 한 줄이다."""
    turns = [
        [
            _query_embedding(tokens=100, latency_ms=100, outcome="ok"),
            _generation(
                "chat_generate",
                "claude-opus-5-5",
                promptTokens=1_000,
                outputTokens=100,
                firstTokenMs=1_200,
                streamFirstTokenMs=900,
            ),
            _generation("chat_stat_judgment", "claude-haiku-5-5", promptTokens=500, outputTokens=10),
        ],
        [_generation("chat_generate", "claude-opus-5-5", promptTokens=1_000, outputTokens=0)],
        [
            _generation(
                "chat_generate",
                "claude-opus-5-5",
                promptTokens=1_000,
                outputTokens=100,
                firstTokenMs=1_600,
                streamFirstTokenMs=1_500,
            )
        ],
    ]

    summary = script.summarize(turns)

    assert sorted(summary.first_token_ms) == [1_200, 1_600]
    assert sorted(summary.stream_first_token_ms) == [900, 1_500]
    assert summary.query_latency_ms == [100]
    lines = script.format_report(summary).splitlines()
    assert "first token ms (turn start) n 2 p50 1200.0 p90 1600.0 max 1600" in lines
    assert "first token ms (stream start) n 2 p50 900.0 p90 1500.0 max 1500" in lines


def test_format_report_has_no_first_token_line_when_no_call_carries_it() -> None:
    summary = script.summarize([[_generation("chat_generate", "claude-opus-5-5", promptTokens=1, outputTokens=1)]])

    assert "first token" not in script.format_report(summary)


def test_percentile_is_nearest_rank() -> None:
    values = [float(v) for v in range(1, 11)]

    assert script.percentile(values, 0.5) == 5.0
    assert script.percentile(values, 0.9) == 9.0
    assert script.percentile(values, 1.0) == 10.0
    assert script.percentile([7.0], 0.5) == 7.0
    assert script.percentile([], 0.5) is None


async def test_read_llm_calls_keeps_turns_inside_the_kst_window_and_chat_model(db_session: AsyncSession) -> None:
    room = await _make_bare_chat_room(db_session)
    marker = _generation("chat_generate", "claude-opus-5-5", promptTokens=1)
    # KST 10-15 은 UTC 10-14 15:00 ~ 10-15 15:00 이다.
    inside = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    last_inside = datetime(2026, 10, 15, 14, 59, tzinfo=UTC)
    before = datetime(2026, 10, 14, 14, 59, tzinfo=UTC)
    after = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    db_session.add_all(
        [
            _make_chat_turn(room.id, chat_model="opus", created_at=inside, llm_calls=[marker | {"promptTokens": 1}]),
            _make_chat_turn(
                room.id, chat_model="opus", created_at=last_inside, llm_calls=[marker | {"promptTokens": 2}]
            ),
            _make_chat_turn(room.id, chat_model="gemini", created_at=inside, llm_calls=[marker | {"promptTokens": 3}]),
            _make_chat_turn(room.id, chat_model="opus", created_at=before, llm_calls=[marker | {"promptTokens": 4}]),
            _make_chat_turn(room.id, chat_model="opus", created_at=after, llm_calls=[marker | {"promptTokens": 5}]),
        ]
    )
    await db_session.flush()

    every_model = await script.read_llm_calls(db_session, date(2026, 10, 15), date(2026, 10, 15), chat_model=None)
    opus_only = await script.read_llm_calls(db_session, date(2026, 10, 15), date(2026, 10, 15), chat_model="opus")

    assert sorted(t[0]["promptTokens"] for t in every_model) == [1, 2, 3]
    assert sorted(t[0]["promptTokens"] for t in opus_only) == [1, 2]


async def test_report_reads_inside_a_read_only_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _fake_read(session: AsyncSession, start: date, end: date, *, chat_model: str | None) -> list[Any]:
        seen.append((await session.execute(text("SHOW transaction_read_only"))).scalar_one())
        return []

    monkeypatch.setattr(script, "read_llm_calls", _fake_read)

    await script.load_turns(date(2026, 10, 15), date(2026, 10, 15), chat_model=None)

    assert seen == ["on"]


def test_format_report_prints_every_site_and_the_turn_distribution() -> None:
    summary = script.summarize(
        [
            [
                _query_embedding(tokens=100, latency_ms=100, outcome="ok"),
                _generation("chat_generate", "claude-opus-5-5", promptTokens=1_000, outputTokens=100),
            ]
        ]
    )

    report = script.format_report(summary)

    assert "chat_memory_query_embedding" in report
    assert "chat_generate" in report
    assert "turns 1" in report
    assert "ok=1" in report
