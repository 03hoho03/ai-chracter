"""Claude 자격 목록 항목의 추정 사용액 — 호출 원가를 마이크로달러 정수로 그 항목·충전액 기준의 Redis 해시에 쌓고 읽는다.

원가 규칙은 어드민 사용량 화면과 같은 함수(`usage_store.call_cost_usd`)라 여기서는 쌓는 규칙(기준·단가 없음·실패 흡수)을 본다.
기대 금액은 단가표 값으로 손으로 계산해 적는다 — 같은 함수로 기대값을 만들면 늘 같다."""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from api.core.redis import redis_client
from api.llm import credential_usage
from api.llm.claude_messages import to_usage
from api.llm.credential_usage import CredentialSpend, SpendTarget, read_credential_spend, record_credential_spend
from factories import _capture_credential_alerts, _settle_credential_tasks

_BASIS = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
_LATER_BASIS = datetime(2026, 11, 4, 9, 30, 15, 123456, tzinfo=UTC)
_UNPRICED = "claude-unknown-model-0"


def _target(credit_since: datetime | None = _BASIS, **fields: Any) -> SpendTarget:
    values: dict[str, Any] = {
        "id": uuid.UUID("00000000-0000-4000-8000-0000000000a1"),
        "label": "운영 계정",
        "fingerprint": "0a1b2c3d",
        "credit_micro_usd": None if credit_since is None else 50_000_000,
        "credit_since": credit_since,
        "alert_pct": 20,
    }
    values.update(fields)
    return SpendTarget(**values)


async def _spend(target: SpendTarget) -> CredentialSpend | None:
    return (await read_credential_spend([target]))[target.id]


async def test_spend_adds_the_token_cost_in_micro_dollars() -> None:
    """Opus: 입력 700 + 캐시 읽기 200 + 캐시 쓰기 100, 출력 70(사고 20 포함) → 정가 입력 700×4 + 캐시 읽기 200×0.2 + 캐시 쓰기
    100×5 + 출력 70×20 = 4740 마이크로달러. 해시는 쓸 때마다 보존 기간을 다시 건다."""
    target = _target()

    await record_credential_spend(
        target, "claude-opus-5-5", to_usage(700, cache_read=200, cache_write=100, output_tokens=70, thinking_tokens=20)
    )
    await record_credential_spend(target, "claude-opus-5-5", to_usage(700, 200, 100, 70, 20))

    assert await _spend(target) == CredentialSpend(spent_micro_usd=9480, calls=2, unpriced_calls=0, unpriced_model=None)
    (key,) = await redis_client.keys("llm_credential:usage:*")
    assert await redis_client.ttl(key) > 399 * 24 * 60 * 60


async def test_unpriced_model_counts_calls_without_adding_spend() -> None:
    """단가표에 없는 모델의 호출은 금액을 더하지 않고 따로 센다 — 화면이 "단가 없음: 그 id n회"로 보인다."""
    target = _target()

    await record_credential_spend(target, _UNPRICED, to_usage(1000, 0, 0, 200))
    assert await _spend(target) == CredentialSpend(
        spent_micro_usd=0, calls=1, unpriced_calls=1, unpriced_model=_UNPRICED
    )

    await record_credential_spend(target, "claude-haiku-5-5", to_usage(1000, 0, 0, 200))
    assert await _spend(target) == CredentialSpend(
        spent_micro_usd=200, calls=2, unpriced_calls=1, unpriced_model=_UNPRICED
    )


async def test_spend_restarts_when_the_credit_basis_changes() -> None:
    """충전액 기준 시각이 바뀌면(충전액 변경·기준 다시 잡기) 새 기준의 누적은 0 부터다. 옛 기준의 누적은 그대로 남아 있다."""
    before = _target()
    after = _target(credit_since=_LATER_BASIS)

    await record_credential_spend(before, "claude-haiku-5-5", to_usage(1000, 0, 0, 200))

    assert await _spend(after) == CredentialSpend(spent_micro_usd=0, calls=0, unpriced_calls=0, unpriced_model=None)
    await record_credential_spend(after, "claude-haiku-5-5", to_usage(1000, 0, 0, 200))
    assert await _spend(after) == CredentialSpend(spent_micro_usd=200, calls=1, unpriced_calls=0, unpriced_model=None)
    assert await _spend(before) == CredentialSpend(spent_micro_usd=200, calls=1, unpriced_calls=0, unpriced_model=None)


async def test_nothing_is_recorded_without_a_credit_basis() -> None:
    """충전액이 없으면 쌓지 않고 읽어도 값이 없다 — 충전액을 넣었다 지웠다 할 때 옛 누적이 되살아나지 않게."""
    target = _target(credit_since=None)

    await record_credential_spend(target, "claude-opus-5-5", to_usage(700, 200, 100, 70, 20))

    assert await redis_client.keys("llm_credential:usage:*") == []
    assert await _spend(target) is None


class _BrokenPipeline:
    def __init__(self, hang: bool) -> None:
        self.hang = hang

    async def __aenter__(self) -> "_BrokenPipeline":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: self

    async def execute(self) -> list[Any]:
        if self.hang:
            await asyncio.sleep(5)
        raise RedisConnectionError("redis is down")


class _BrokenRedis:
    def __init__(self, hang: bool) -> None:
        self.hang = hang

    def pipeline(self, transaction: bool = True) -> _BrokenPipeline:
        return _BrokenPipeline(self.hang)


@pytest.mark.parametrize("hang", [pytest.param(False, id="error"), pytest.param(True, id="timeout")])
async def test_spend_recording_failure_is_swallowed_within_the_time_cap(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, hang: bool
) -> None:
    """생성 스트림 안에서 불리므로 Redis 가 실패하거나 답하지 않아도 예외 없이 상한 안에 돌아온다(그 한 건만 빠진다)."""
    monkeypatch.setattr(credential_usage, "redis_client", _BrokenRedis(hang))

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="api.llm.credential_usage"):
        await record_credential_spend(_target(), "claude-opus-5-5", to_usage(700, 200, 100, 70, 20))

    assert time.monotonic() - started < 1.0
    assert any(record.name == "api.llm.credential_usage" for record in caplog.records)


async def test_unreadable_spend_store_reads_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """읽기도 실패를 삼킨다 — 기준이 있는 항목까지 모두 "모름"(None)이고 어드민 조회는 그대로 뜬다."""
    monkeypatch.setattr(credential_usage, "redis_client", _BrokenRedis(False))
    with_basis = _target()
    without_basis = _target(credit_since=None, id=uuid.UUID("00000000-0000-4000-8000-0000000000a2"))

    assert await read_credential_spend([with_basis, without_basis]) == {with_basis.id: None, without_basis.id: None}


# ── 추정 잔액 임계 알림 ──────────────────────────────────────────────────────────────────
# Haiku 5.5 출력 400만 토큰 = 400만 × 0.50 달러/백만 = 2 달러(입력 없음).
_TWO_DOLLARS = to_usage(0, 0, 0, 4_000_000)


def _below(spent: str, credit: str, remaining: int, alert: int) -> str:
    return (
        "[Claude 자격] 추정 잔액이 임계 아래 — anthropic · 운영 계정 · 지문 0a1b2c3d · "
        f"추정 사용 {spent} / 충전 {credit} 달러 · 남은 {remaining}%(임계 {alert}%) · 콘솔 잔액을 확인하고 충전액을 그 값으로 "
        "고치거나(같으면 기준 다시 잡기) 충전한다"
    )


async def _spend_twice_over(target: SpendTarget, times: int) -> None:
    for _ in range(times):
        await record_credential_spend(target, "claude-haiku-5-5", _TWO_DOLLARS)
    await _settle_credential_tasks()


async def test_threshold_alert_fires_once_on_the_first_crossing(monkeypatch: pytest.MonkeyPatch) -> None:
    """충전 10 달러·임계 50%: 2·4 달러는 위, 6 달러에서 처음 아래로 내려가 한 번 알리고, 더 내려가도(추정 초과 포함) 다시 알리지
    않는다."""
    alerts = _capture_credential_alerts(monkeypatch)
    target = _target(credit_micro_usd=10_000_000, alert_pct=50)

    await _spend_twice_over(target, 2)
    assert alerts == []
    await _spend_twice_over(target, 1)
    assert alerts == [_below("6.00", "10.00", 40, 50)]
    await _spend_twice_over(target, 3)
    assert alerts == [_below("6.00", "10.00", 40, 50)]


async def test_threshold_alert_rearms_when_the_credit_or_percent_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """이미 아래인 채 임계만 바꿔도 다음 호출에서 한 번 더 알린다. 충전액 기준을 다시 잡으면 새 기준의 누적이 0 부터라 다시 내려갈
    때 알린다."""
    alerts = _capture_credential_alerts(monkeypatch)
    target = _target(credit_micro_usd=10_000_000, alert_pct=50)
    await _spend_twice_over(target, 3)

    await _spend_twice_over(_target(credit_micro_usd=10_000_000, alert_pct=30), 1)
    rebased = _target(credit_since=_LATER_BASIS, credit_micro_usd=10_000_000, alert_pct=50)
    await _spend_twice_over(rebased, 2)
    assert len(alerts) == 2
    await _spend_twice_over(rebased, 1)

    assert alerts == [
        _below("6.00", "10.00", 40, 50),
        _below("8.00", "10.00", 20, 30),
        _below("6.00", "10.00", 40, 50),
    ]
