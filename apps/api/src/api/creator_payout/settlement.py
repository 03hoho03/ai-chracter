"""크리에이터 정산 계산과 확정. 승인 때의 소급과 매달의 확정이 모두 `confirm_window` 하나를 부른다 — 계산식이 두 벌이면
같은 사용이 경로에 따라 다른 금액이 된다.

크리에이터 c 의 적립 = (적립 구간 안에 일어난 c 귀속 유료 배분 − 적립 구간 안에 일어난 그 배분들의 환급) × 단가 × 비율.

- 정산 대상 사용처는 채팅·소설만이다(미리보기 제외, 앞으로 생길 다른 사용 종류도 여기에 넣기 전까지는 빠진다). 환급도
  사용처를 거쳐 같은 종류로 거른다 — 배분·로트로만 모으면 다른 종류 사용의 환급이 채팅·소설 정산에서 빠진다.
- 자기 작품에서 쓴 것과, 사용 시점에 소유자가 이미 탈퇴한 작품에서 쓴 것은 세지 않는다.
- 유료 로트(`purchase_paid`)의 배분만 센다. 한 차감이 무료·보너스·유료 로트에 걸칠 수 있어 배분 단위로 센다.
- 차감은 차감 시각, 환급은 환급 시각이 속한 구간에서 센다. 환급은 그 차감이 적립 구간 안이었을 때만 뺀다(더한 적이 없는
  차감의 환급을 빼지 않는다).
- 단가(부가세 포함)는 결제 행의 `amount_krw / paid_amount`, 적립은 공급가(÷ 1.1)의 `rate_bps / 10000` 이다. 유료 1클로버의
  적립 = `amount_krw × rate_bps / (paid_amount × 11000)`.
- 결제별 상한: 한 결제에서 정산 대상이 될 수 있는 유료 수는 `(amount_krw − cancelled_amount_krw) × paid_amount /
  amount_krw` 를 넘지 않는다. 그 결제의 유료 로트에서 나간 순사용 전체가 이를 넘으면 모든 크리에이터의 몫에 같은 계수
  (상한 ÷ 순사용)를 곱한다 — 확정 순서와 무관하게 크리에이터마다 독립으로 정해진다.
- 확정 뒤 결제 취소: 그 달 끝까지 성공한 취소가 있고 지금 계수가 1 보다 작은 결제는, 이 크리에이터가 그 결제로 이미 확정한
  몫을 지금 계수로 다시 맞춘 차이(음수만)를 이번 달에 더한다. 앞선 조정도 확정 금액에 들어 있어 같은 몫을 두 번 빼지
  않고, 취소가 없는 달에도 계수가 내려가면(환급된 클로버를 다시 씀) 다시 맞춘다.
- 원 미만: 줄(작품 × 결제) 값을 반올림 전 그대로 더하고, 그 합계를 소수 6자리로 맞춘 뒤 한 번 0 쪽으로 버린다(음수 달도
  0 쪽, 남은 음수는 잔액에서 빠져 다음 적립과 상계된다). 맞추는 것은 정수인 참값(유료 22 = 3원)이 나눗셈 오차나 앞선 줄
  저장값의 반올림 오차로 2.999… 가 되어 한 원을 잃는 것을 막기 위해서다.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.clover import CloverSpendUsageKind
from api.db.models.creator_payout import CreatorPayoutConfirmation, CreatorPayoutConfirmationLine

# 정산에 넣는 사용처 종류. 새 종류(공개 소설 열람 등)는 분배 규칙을 정하기 전까지 여기 넣지 않는다 — 넣지 않으면 그 사용과
# 그 환급이 함께 빠진다.
SETTLED_USAGE_KINDS: tuple[CloverSpendUsageKind, ...] = ("chat", "novel")

_EXACT_PLACES = Decimal("1e-10")
# 버리기 직전 합계를 맞추는 자리. 결제 단가가 정수 원이면 계수 1인 몫은 1/11000원 단위라 정수가 아닌 참값은 정수에서
# 1/11000(≈ 9.1e-5) 이상 떨어져 있고, 줄 저장값의 반올림이 남기는 오차는 줄당 5e-11 이라, 그 사이인 1e-6 에 맞추면 오차는
# 지우고 정당한 원 미만은 건드리지 않는다(계수가 1 보다 작은 몫만 참값이 정수 아래 5e-7 안쪽일 때 1원 위로 갈린다).
_TRUNCATE_PLACES = Decimal("1e-6")

# 확정 뒤 결제 취소 조정의 대상 결제: `:me`(확정하는 달의 다음 월초) 전에 성공한 취소가 있고 지금 계수가 1 보다 작은 결제.
# 계수 비교는 나눗셈 없이 양변에 `amount_krw` 를 곱해 정수로 한다. `:me` 가 NULL(소급)이면 비교가 NULL 이라 비어 있다.
CAPPED_PAYMENTS_SQL = """
  SELECT pay.id AS payment_id
    FROM payments pay
    JOIN clover_lots lot ON lot.payment_id = pay.id AND lot.kind = 'purchase_paid'
    JOIN clover_spend_allocations a ON a.lot_id = lot.id
   WHERE pay.id IN (SELECT pc.payment_id FROM payment_cancellations pc
                     WHERE pc.status = 'succeeded' AND pc.completed_at < CAST(:me AS timestamptz))
   GROUP BY pay.id
  HAVING (pay.amount_krw - pay.cancelled_amount_krw)::bigint * pay.paid_amount
         < SUM(a.amount - a.refunded_amount) * pay.amount_krw
"""

# 크리에이터 하나 × 확정 행 하나. 결과 한 줄 = 내역 줄 하나(작품 × 결제). 차감·환급과 취소 조정이 한 문장이라 같은
# 스냅숏의 계수를 쓴다 — 둘로 나누면 그 사이에 커밋된 취소가 이 달 몫과 조정에 서로 다른 계수를 준다.
_SETTLEMENT_SQL = text(
    f"""
WITH win AS (
  SELECT * FROM unnest(CAST(:ws_list AS timestamptz[]), CAST(:we_list AS timestamptz[])) AS w(ws, we)
),
eligible AS (
  SELECT u.spend_ledger_id, u.content_id, u.created_at AS spent_at
    FROM clover_spend_usages u
    JOIN users owner ON owner.id = u.content_owner_user_id
   WHERE u.content_owner_user_id = :creator_id
     AND u.usage_kind = ANY(CAST(:usage_kinds AS text[]))
     AND NOT u.is_self_play
     AND (owner.deleted_at IS NULL OR owner.deleted_at > u.created_at)
     AND EXISTS (SELECT 1 FROM creator_payout_applications ap
                  WHERE ap.user_id = :creator_id
                    AND ap.accrual_start_at IS NOT NULL
                    AND u.created_at >= ap.accrual_start_at
                    AND (ap.revoked_at IS NULL OR u.created_at < ap.revoked_at))
),
paid AS (
  SELECT e.content_id, e.spent_at, a.id AS allocation_id, a.amount, lot.payment_id
    FROM eligible e
    JOIN clover_spend_allocations a ON a.spend_ledger_id = e.spend_ledger_id
    JOIN clover_lots lot ON lot.id = a.lot_id AND lot.kind = 'purchase_paid'
),
movement AS (
  SELECT p.content_id, p.payment_id, p.amount AS units, p.amount AS gross, 0 AS refunded
    FROM paid p
   WHERE EXISTS (SELECT 1 FROM win WHERE p.spent_at >= win.ws AND p.spent_at < win.we)
  UNION ALL
  SELECT p.content_id, p.payment_id, -r.amount, 0, r.amount
    FROM paid p JOIN clover_spend_refunds r ON r.allocation_id = p.allocation_id
   WHERE EXISTS (SELECT 1 FROM win WHERE r.created_at >= win.ws AND r.created_at < win.we)
),
per_payment AS (
  SELECT content_id, payment_id, SUM(units) AS units, SUM(gross) AS gross, SUM(refunded) AS refunded
    FROM movement GROUP BY content_id, payment_id
),
capped AS ({CAPPED_PAYMENTS_SQL}),
prior AS (
  SELECT l.content_id, l.payment_id,
         SUM(l.net_units::numeric(38,20) * c.rate_bps) AS units_bps,
         SUM(l.exact_krw)                              AS confirmed_krw
    FROM creator_payout_confirmation_lines l
    JOIN creator_payout_confirmations c ON c.id = l.confirmation_id
   WHERE c.user_id = :creator_id
     AND l.payment_id IN (SELECT payment_id FROM capped)
   GROUP BY l.content_id, l.payment_id
),
keys AS (
  SELECT content_id, payment_id FROM per_payment
  UNION
  SELECT content_id, payment_id FROM prior
),
factor AS (
  SELECT pay.id AS payment_id, pay.amount_krw, pay.paid_amount,
         COALESCE(LEAST(1::numeric,
           ((pay.amount_krw - pay.cancelled_amount_krw)::numeric * pay.paid_amount / pay.amount_krw)
           / NULLIF(s.spent, 0)), 1) AS f
    FROM payments pay
    JOIN (SELECT lot.payment_id, SUM(a.amount - a.refunded_amount) AS spent
            FROM clover_lots lot JOIN clover_spend_allocations a ON a.lot_id = lot.id
           WHERE lot.kind = 'purchase_paid'
             AND lot.payment_id IN (SELECT payment_id FROM keys)
           GROUP BY lot.payment_id) s ON s.payment_id = pay.id
)
SELECT k.content_id, k.payment_id,
       COALESCE(pp.units, 0)    AS net_units,
       COALESCE(pp.gross, 0)    AS gross_units,
       COALESCE(pp.refunded, 0) AS refunded_units,
       COALESCE(pp.units, 0)::numeric(38,20) * f.amount_krw * CAST(:rate_bps AS integer) * f.f
           / (f.paid_amount * 11000) AS own_krw,
       COALESCE(LEAST(0::numeric,
           pr.units_bps * f.amount_krw * f.f / (f.paid_amount * 11000) - pr.confirmed_krw), 0) AS cancel_adjust_krw
  FROM keys k
  LEFT JOIN per_payment pp USING (content_id, payment_id)
  LEFT JOIN prior pr USING (content_id, payment_id)
  JOIN factor f USING (payment_id)
 ORDER BY k.content_id, k.payment_id
"""
)


def _exact(value: Decimal) -> Decimal:
    return value.quantize(_EXACT_PLACES, rounding=ROUND_HALF_UP)


async def confirm_window(
    db: AsyncSession,
    *,
    creator_id: uuid.UUID,
    kind: Literal["retro", "monthly"],
    period_month: date | None,
    windows: Sequence[tuple[datetime, datetime]],
    cancel_adjust_month: tuple[datetime, datetime] | None,
) -> CreatorPayoutConfirmation | None:
    """크리에이터 한 명의 확정 행 하나와 그 내역 줄(작품 × 결제)을 넣는다. **커밋하지 않는다.**

    `windows` 는 이 행이 세는 적립 구간 목록(각 [시작, 끝) 반열린, 시작 순, 길이 0 인 구간은 호출자가 뺀다)이다. 소급은
    하나, 월 확정은 그 달에 걸친 승인 구간 수만큼(같은 달 승인 취소 → 재승인이면 둘), 결제 취소 조정만 있는 달은 빈
    목록이다. 구간이 겹쳐도 한 번만 센다. 구간마다 따로 부르지 않는다 — 같은 달 월 확정 행은 하나뿐이다(부분 유니크).

    `cancel_adjust_month` 는 월 확정이면 그 달 [월초, 다음 월초)이고 그 끝이 확정 뒤 결제 취소 조정의 기준 시각이다.
    소급이면 `None` 이라 조정이 없다(그 크리에이터의 첫 확정이라 앞선 몫이 없다).

    구간이 없고 조정 합도 0 이면 행을 넣지 않고 `None` 이다(조정만 있을 수 있는 크리에이터마다 매달 0원 행이 쌓이지
    않게). 구간이 있으면 0원이어도 넣는다 — 그 달·소급을 했다는 표식이 재실행 멱등의 근거다.

    같은 크리에이터의 확정은 순서대로 해야 한다 — 앞선 확정의 내역 줄을 잠금 없이 읽으므로 두 확정이 동시에 돌면 같은
    결제 몫을 두 번 줄일 수 있다. 호출 쪽이 크리에이터 `users` 행을 잠근 트랜잭션 안에서 부른다.

    확정 행의 `exact_krw` 는 반올림 전 줄 값을 모두 더한 뒤 10자리로 맞춘 값이고, `amount_krw` 는 그 합을 6자리로 맞춰
    버린 것이다. 줄에 저장하는 값은 줄마다 10자리로 맞춘 값이라 그 합은 행의 `exact_krw` 와 줄 수 × 5e-11 안에서 다를 수
    있고, 다음 달 결제 취소 조정은 그 저장값을 기준으로 빼므로 같은 크기의 오차가 조정 줄로 넘어온다. 10자리에서 바로
    버리면 그 오차가 쌓여 정수인 참값(2.4545… + 2.4545… + 1.0909… = 정확히 6원)이 5.9999999999 가 되어 한 원을 잃는다.
    """
    if windows:
        window_start, window_end = windows[0][0], max(end for _, end in windows)
    elif cancel_adjust_month is not None:
        window_start, window_end = cancel_adjust_month
    else:
        raise ValueError("적립 구간도 결제 취소 조정 달도 없는 확정은 셀 것이 없다")

    rate_bps = settings.creator_payout_rate_bps
    rows = (
        await db.execute(
            _SETTLEMENT_SQL,
            {
                "creator_id": creator_id,
                "ws_list": [start for start, _ in windows],
                "we_list": [end for _, end in windows],
                "me": None if cancel_adjust_month is None else cancel_adjust_month[1],
                "rate_bps": rate_bps,
                "usage_kinds": list(SETTLED_USAGE_KINDS),
            },
        )
    ).all()

    confirmation_id = uuid.uuid4()
    lines: list[CreatorPayoutConfirmationLine] = []
    gross_units = refunded_units = 0
    raw_total = Decimal(0)
    for row in rows:
        gross_units += int(row.gross_units)
        refunded_units += int(row.refunded_units)
        raw_total += row.own_krw + row.cancel_adjust_krw
        cancel_adjust = _exact(row.cancel_adjust_krw)
        exact = _exact(row.own_krw + row.cancel_adjust_krw)
        if row.net_units == 0 and exact == 0:
            continue
        lines.append(
            CreatorPayoutConfirmationLine(
                confirmation_id=confirmation_id,
                content_id=row.content_id,
                payment_id=row.payment_id,
                net_units=int(row.net_units),
                cancel_adjust_krw=cancel_adjust,
                exact_krw=exact,
            )
        )

    exact_total = _exact(raw_total)
    if not windows and exact_total == 0:
        return None

    confirmation = CreatorPayoutConfirmation(
        id=confirmation_id,
        user_id=creator_id,
        kind=kind,
        period_month=period_month,
        window_start=window_start,
        window_end=window_end,
        gross_units=gross_units,
        refunded_units=refunded_units,
        rate_bps=rate_bps,
        exact_krw=exact_total,
        # `int()` 는 0 쪽으로 버린다 — 음수 달도 절댓값의 원 미만을 버린다.
        amount_krw=int(raw_total.quantize(_TRUNCATE_PLACES, rounding=ROUND_HALF_UP)),
    )
    db.add(confirmation)
    # 줄이 확정 행을 FK 로 가리킨다. 이 저장소는 `relationship()` 을 쓰지 않아 단위작업의 INSERT 정렬에 기대지 않는다.
    await db.flush()
    if lines:
        db.add_all(lines)
        await db.flush()
    return confirmation
