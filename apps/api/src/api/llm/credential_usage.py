"""Claude 자격 목록 항목의 추정 사용액 — 목록 경로 호출과 확인 호출의 원가를 그 항목·충전액 기준의 Redis 해시에 쌓고 읽는다.

- **키** `llm_credential:usage:{항목 id}:{기준}`. 기준은 충전액 기준 시각(`credit_since`)의 UTC 마이크로초 정수다(부동소수 없이).
  충전액이 없으면(기준 없음) 쌓지 않는다 — 다른 기준으로 쌓으면 충전액을 넣었다 지울 때 그 키가 충전액이 있던 동안 멈춰 있던
  누적으로 돌아가 뜻이 흐려진다. 충전액을 바꾸거나 같은 값으로 기준만 다시 잡으면 기준 시각이 바뀌어 새 키가 0 부터 센다.
- **필드** `spent_micro_usd`(원가 합, 마이크로달러), `calls`(호출 수), `unpriced_calls`·`unpriced_model`(단가표에 없는 모델의 호출
  수와 그 id — 금액은 더하지 않는다). 기존 사용량 해시(`llm_usage:`)에는 아무것도 더하지 않는다.
- **금액**은 사용량 화면과 같은 원가 함수(`usage_store.call_cost_usd`)를 호출마다 마이크로달러 정수로 반올림한 것이다. 충전액
  칼럼이 마이크로달러 정수라 잔액 임계를 정수끼리 비교하고, 해시가 돌려준 새 합으로 "이번 호출이 임계를 넘겼는가"를 정확히
  가른다. 반올림 오차는 호출마다 0.5 마이크로달러 이하다.
- **보존**은 쓸 때마다 다시 거는 400일이다 — 처음에만 걸면 수개월 쓰는 기준의 누적이 통째로 사라져 잔액이 가득 찬 것처럼 보인다.
- **임계 알림**: 쓰기가 돌려받은 새 합으로 추정 잔액이 충전액의 임계 비율 아래면 한 번 알린다. 표지가 (항목, 기준, 임계)에 묶여
  처음 내려갈 때 한 번이고, 충전액을 바꾸거나 기준을 다시 잡거나 임계를 바꾸면 표지가 달라져 다시 무장된다. 표지 확인은 쏘고 잊는
  태스크 안이라 호출 경로의 Redis 왕복은 쓰기 한 번 그대로다.
- 쓰기·읽기 모두 0.1초 상한 안에서 끝나고 실패를 삼킨다 — 쓰기는 생성 스트림 안에서 불리고, 읽기가 실패하면 어드민 조회는
  사용액 칸만 비운다. 사용자·방 id 는 싣지 않는다.
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure
from api.db.models.llm_credential import LlmCredential
from api.llm.credential_notify import spawn_credential_notification_once
from api.llm.credentials import CREDENTIAL_KEY_PREFIX
from api.llm.usage_store import RECORD_TIMEOUT_SECONDS, call_cost_usd

logger = logging.getLogger(__name__)

SPEND_KEY_PREFIX = f"{CREDENTIAL_KEY_PREFIX}usage:"
SPEND_RETENTION_SECONDS = 400 * 24 * 60 * 60

_MICRO_PER_USD = 1_000_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SpendTarget:
    """사용액을 쌓을 항목과 그 기준 — 런타임은 스냅숏 항목에서, 확인 호출은 DB 행에서 만든다."""

    id: uuid.UUID
    label: str
    fingerprint: str
    credit_micro_usd: int | None
    credit_since: datetime | None
    alert_pct: int

    @classmethod
    def of_row(cls, row: LlmCredential) -> "SpendTarget":
        return cls(
            id=row.id,
            label=row.label,
            fingerprint=row.secret_fingerprint,
            credit_micro_usd=row.credit_micro_usd,
            credit_since=row.credit_since,
            alert_pct=row.alert_pct,
        )


@dataclass(frozen=True)
class CredentialSpend:
    """한 기준의 누적. 기준 이후 호출이 없으면 모두 0 이다."""

    spent_micro_usd: int
    calls: int
    unpriced_calls: int
    unpriced_model: str | None


def credit_basis(credit_since: datetime) -> int:
    """기준 시각의 UTC 마이크로초 정수 — 키와 알림 표지에 같은 값을 쓴다."""
    return (credit_since - _EPOCH) // timedelta(microseconds=1)


def spend_key(target: SpendTarget) -> str | None:
    """그 항목의 지금 기준 키. 충전액이 없으면 None(쌓지 않는다)."""
    if target.credit_micro_usd is None or target.credit_since is None:
        return None
    return f"{SPEND_KEY_PREFIX}{target.id}:{credit_basis(target.credit_since)}"


def below_alert(credit_micro_usd: int, spent_micro_usd: int, alert_pct: int) -> bool:
    """추정 잔액이 충전액의 임계 비율 아래인가(추정 초과로 0 아래인 것도 포함)."""
    return (credit_micro_usd - spent_micro_usd) * 100 < credit_micro_usd * alert_pct


def _alert_below(target: SpendTarget, credit_micro_usd: int, spent_micro_usd: int) -> None:
    assert target.credit_since is not None
    remaining_pct = (credit_micro_usd - spent_micro_usd) * 100 // credit_micro_usd
    spawn_credential_notification_once(
        f"{CREDENTIAL_KEY_PREFIX}alert:threshold:{target.id}:{credit_basis(target.credit_since)}:{target.alert_pct}",
        f"[Claude 자격] 추정 잔액이 임계 아래 — anthropic · {target.label} · 지문 {target.fingerprint} · 추정 사용 "
        f"{spent_micro_usd / _MICRO_PER_USD:.2f} / 충전 {credit_micro_usd / _MICRO_PER_USD:.2f} 달러 · 남은 "
        f"{remaining_pct}%(임계 {target.alert_pct}%) · 콘솔 잔액을 확인하고 충전액을 그 값으로 고치거나(같으면 기준 다시 잡기) "
        "충전한다",
        ttl_seconds=SPEND_RETENTION_SECONDS,
    )


async def record_credential_spend(target: SpendTarget, model: str, usage_metadata: object | None) -> None:
    """호출 한 건의 원가를 그 항목의 지금 기준에 더하고, 그 합이 임계 아래면 알린다(위 머리말). 기준이 없으면 아무것도 하지
    않는다. MULTI/EXEC 한 번 왕복이라 상한에 걸려도 일부만 반영된 호출이 생기지 않는다. **절대 raise 하지 않는다** — 생성
    스트림 안에서 불린다(취소는 그대로 올라간다)."""
    try:
        key = spend_key(target)
        if key is None:
            return
        cost = call_cost_usd(model, usage_metadata)
        async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
            async with redis_client.pipeline(transaction=True) as pipe:
                # 단가가 없어도 금액 필드를 0 만큼 올려 둔다 — 결과의 첫 값이 늘 그 기준의 새 합이다.
                pipe.hincrby(key, "spent_micro_usd", 0 if cost is None else round(cost * _MICRO_PER_USD))
                pipe.hincrby(key, "calls", 1)
                if cost is None:
                    pipe.hincrby(key, "unpriced_calls", 1)
                    pipe.hset(key, "unpriced_model", model)
                pipe.expire(key, SPEND_RETENTION_SECONDS)
                spent = int((await pipe.execute())[0])
        if target.credit_micro_usd is not None and below_alert(target.credit_micro_usd, spent, target.alert_pct):
            _alert_below(target, target.credit_micro_usd, spent)
    except Exception as exc:
        logger.warning("Claude 자격 추정 사용액 기록 실패 — 이 호출 한 건은 사용액에서 빠진다", exc_info=True)
        capture_dependency_failure(exc, dependency="redis")


async def read_credential_spend(targets: Sequence[SpendTarget]) -> dict[uuid.UUID, CredentialSpend | None]:
    """항목마다 지금 기준의 누적. 기준이 없는 항목은 None 이다. 기준이 있는 항목들을 파이프라인 한 번으로 읽고, 읽지 못하면
    (Redis 오류·상한 초과·형식이 다른 값) 모두 None 이다."""
    spends: dict[uuid.UUID, CredentialSpend | None] = {target.id: None for target in targets}
    try:
        keyed = [(target.id, key) for target in targets if (key := spend_key(target)) is not None]
        if not keyed:
            return spends
        async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
            async with redis_client.pipeline(transaction=False) as pipe:
                for _, key in keyed:
                    pipe.hgetall(key)
                hashes: list[dict[str, str]] = await pipe.execute()
        read = {
            credential_id: CredentialSpend(
                spent_micro_usd=int(fields.get("spent_micro_usd", 0)),
                calls=int(fields.get("calls", 0)),
                unpriced_calls=int(fields.get("unpriced_calls", 0)),
                unpriced_model=fields.get("unpriced_model"),
            )
            for (credential_id, _), fields in zip(keyed, hashes, strict=True)
        }
    except Exception as exc:
        logger.warning("Claude 자격 추정 사용액 조회 실패 — 사용액 칸을 비운다", exc_info=True)
        capture_dependency_failure(exc, dependency="redis")
        return spends
    spends.update(read)
    return spends
