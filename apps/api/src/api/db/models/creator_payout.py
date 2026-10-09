"""크리에이터 정산 — 정산 신청(`creator_payout_applications`), 확정 행(`creator_payout_confirmations`), 확정 행의 작품 ×
결제별 내역(`creator_payout_confirmation_lines`), 월 확정 배치의 달별 실행 기록(`creator_payout_batch_runs`).

앞의 세 테이블은 탈퇴해도 지우지 않는다 — 확정 행과 내역은 지급·세무의 근거이고, 신청 행은 적립 구간의 근거다.
상태·종류는 Text + Literal + CHECK 이다(`db/models/payment.py` 와 같은 방식). 🔴 `alembic check` 는 CHECK·부분 인덱스의
WHERE·복합 PK 를 비교하지 않는다 — 이 파일의 제약은 `pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증이다.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.payment import _sql_in_list

# 신청 상태. pending → approved | rejected, approved → revoked. rejected·revoked 는 끝이고 다시 신청하면 새 행이다.
CreatorPayoutApplicationStatus = Literal["pending", "approved", "rejected", "revoked"]
# 확정 종류. retro 는 첫 승인 때 지난 기간을 한 번 세는 행, monthly 는 매달 확정하는 행이다.
CreatorPayoutConfirmationKind = Literal["retro", "monthly"]

# 원 미만을 담는 금액 칸의 정밀도. 소수 10자리는 정산 계산이 원 미만을 반올림해 두는 자리와 같다.
KRW_EXACT = Numeric(30, 10)


class CreatorPayoutApplication(Base):
    """정산 신청 하나. 승인되면 적립 구간이 생긴다.

    `accrual_start_at` 은 "이 차감이 적립 구간 안인가"(환급을 뺄지 판정)에만, `monthly_from_at` 은 월 확정이 세기 시작하는
    시각에만 쓴다. 첫 승인은 `accrual_start_at` 이 소급 일수만큼 앞서고 그 사이는 소급 확정 행 하나가 센다. 둘을 하나로
    두면 첫 승인 달의 월 확정이 소급이 이미 센 구간을 다시 세거나, 소급 기간 차감의 승인 뒤 환급을 빼지 못한다.
    승인 취소는 `revoked_at` 으로 적립 구간의 끝을 닫는다.
    """

    __tablename__ = "creator_payout_applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_creator_payout_applications_user_id"), nullable=False
    )
    status: Mapped[CreatorPayoutApplicationStatus] = mapped_column(Text, nullable=False)
    # 신청 화면의 수집·이용 동의 시각과 그때 게시돼 있던 개인정보 처리방침 버전.
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    privacy_version: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_creator_payout_applications_decided_by_admin_id"), nullable=True
    )
    # 거절 사유는 신청자에게 보인다.
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    accrual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    monthly_from_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_creator_payout_applications_revoked_by_admin_id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_in_list(CreatorPayoutApplicationStatus)})",
            name="ck_creator_payout_applications_status",
        ),
        CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name="ck_creator_payout_applications_decided"),
        CheckConstraint(
            "(status IN ('approved', 'revoked')) = (accrual_start_at IS NOT NULL)",
            name="ck_creator_payout_applications_accrual",
        ),
        CheckConstraint(
            "(status IN ('approved', 'revoked')) = (monthly_from_at IS NOT NULL)"
            " AND accrual_start_at <= monthly_from_at",
            name="ck_creator_payout_applications_monthly_from",
        ),
        CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_creator_payout_applications_revoked"
        ),
        # 살아 있는 신청은 한 사람에 하나.
        Index(
            "ux_creator_payout_applications_user_id_live",
            "user_id",
            unique=True,
            postgresql_where=status.in_(("pending", "approved")),
        ),
        # 어드민 신청 큐.
        Index("ix_creator_payout_applications_status_applied_at", "status", "applied_at"),
    )


class CreatorPayoutConfirmation(Base):
    """크리에이터 한 명의 확정 한 번. 적립 잔액은 이 행들의 `amount_krw` 합에서 지급액을 뺀 파생값이다.

    `exact_krw` 는 원 미만까지 담은 정확값이고 `amount_krw` 는 그 값의 원 미만을 0 쪽으로 버린 적립액이다. 둘 다 음수일 수
    있다(그 달 환급이 사용보다 많거나, 확정 뒤 결제 취소로 앞선 몫을 줄인 달). `window_start`·`window_end` 는 이 행이 센
    적립 구간 목록의 첫 시작과 마지막 끝이고, 구간 없이 결제 취소 조정만 있는 달은 그 달 전체다.

    `exact_krw` 는 반올림 전 내역 값의 합을 소수 10자리로 맞춘 값이라, 줄마다 맞춰 저장한 내역 `exact_krw` 의 합과 줄 수 ×
    5e-11 안에서 다를 수 있다. 둘이 같다는 CHECK 는 두지 않는다(표 사이 조건이기도 하다) — 잔액·지급은 이 행의
    `amount_krw` 만 읽는다.

    같은 사람의 같은 달 월 확정과 두 번째 소급은 부분 유니크가 막는다 — 배치를 다시 돌려도 두 번 확정되지 않는 근거다.
    """

    __tablename__ = "creator_payout_confirmations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_creator_payout_confirmations_user_id"), nullable=False
    )
    kind: Mapped[CreatorPayoutConfirmationKind] = mapped_column(Text, nullable=False)
    # 월 확정만: 그 달 1일(KST).
    period_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 적립 구간 안 차감의 유료 배분 합과, 적립 구간 안 환급 행의 합(양수).
    gross_units: Mapped[int] = mapped_column(Integer, nullable=False)
    refunded_units: Mapped[int] = mapped_column(Integer, nullable=False)
    # 확정 때 쓴 비율(bps). 설정을 바꿔도 이미 확정한 행이 어느 비율로 계산됐는지 남는다.
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    exact_krw: Mapped[Decimal] = mapped_column(KRW_EXACT, nullable=False)
    amount_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"kind IN ({_sql_in_list(CreatorPayoutConfirmationKind)})", name="ck_creator_payout_confirmations_kind"
        ),
        CheckConstraint(
            "(kind = 'monthly') = (period_month IS NOT NULL)", name="ck_creator_payout_confirmations_period_month"
        ),
        CheckConstraint("window_start < window_end", name="ck_creator_payout_confirmations_window"),
        CheckConstraint(
            "gross_units >= 0 AND refunded_units >= 0", name="ck_creator_payout_confirmations_units_non_negative"
        ),
        CheckConstraint("rate_bps BETWEEN 1 AND 10000", name="ck_creator_payout_confirmations_rate_bps"),
        Index(
            "ux_creator_payout_confirmations_monthly",
            "user_id",
            "period_month",
            unique=True,
            postgresql_where=kind == "monthly",
        ),
        Index("ux_creator_payout_confirmations_retro", "user_id", unique=True, postgresql_where=kind == "retro"),
        # 크리에이터 내역 화면.
        Index("ix_creator_payout_confirmations_user_id_window_end", "user_id", window_end.desc()),
    )


class CreatorPayoutConfirmationLine(Base):
    """확정 행 하나의 작품 × 결제별 내역. 결제까지 남기는 것은 확정 뒤 그 결제가 취소됐을 때 "이 크리에이터가 그 결제로
    이미 확정한 순사용·금액"을 다시 읽어 줄일 몫을 정하기 위해서다 — 과거 확정을 다시 계산하면 그때와 계수가 달라
    확정액과 맞지 않는다.

    `net_units` 는 그 확정의 적립 구간 안 순사용(환급이 크면 음수), `cancel_adjust_krw` 는 확정 뒤 결제 취소로 앞선 몫을 줄인
    조정(0 이하), `exact_krw` 는 순사용 몫과 조정의 합이다. 순사용도 금액도 0 인 줄은 넣지 않는다.
    """

    __tablename__ = "creator_payout_confirmation_lines"

    confirmation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("creator_payout_confirmations.id", name="fk_creator_payout_confirmation_lines_confirmation_id"),
        primary_key=True,
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contents.id", name="fk_creator_payout_confirmation_lines_content_id"), primary_key=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payments.id", name="fk_creator_payout_confirmation_lines_payment_id"), primary_key=True
    )
    net_units: Mapped[int] = mapped_column(Integer, nullable=False)
    cancel_adjust_krw: Mapped[Decimal] = mapped_column(KRW_EXACT, nullable=False)
    exact_krw: Mapped[Decimal] = mapped_column(KRW_EXACT, nullable=False)

    __table_args__ = (
        CheckConstraint("cancel_adjust_krw <= 0", name="ck_creator_payout_confirmation_lines_cancel_adjust"),
        # 확정 뒤 결제 취소 조정이 그 결제에서 출발해 앞선 줄을 찾는다. PK 는 확정 행 id 가 앞이라 이 조회에 못 쓴다.
        Index("ix_creator_payout_confirmation_lines_payment_id", "payment_id"),
    )


class CreatorPayoutBatchRun(Base):
    """월 확정 배치가 한 달을 끝냈다는 기록. 이 행이 있는 달은 다시 확정하지 않는다.

    크리에이터별 확정 행과 따로 두는 것은, 감시 수 둘이 크리에이터가 아니라 그 달 전체의 값이고 확정 대상이 0명인 달에도
    "그 달은 끝났다"가 남아야 해서다.

    - `creator_count`·`total_amount_krw`: 그 달 월 확정 행의 수와 `amount_krw` 합.
    - `unattributed_spend_count`: 그 달의 채팅·소설 차감 중 사용처가 없는 것(배포 겹침에 옛 이미지가 남긴 차감 등). 정산에서
      빠졌다는 뜻이고 배치를 멈추지는 않는다.
    - `refund_event_mismatch_count`: 사용처가 있는 유료 배분 중 환급 합(`refunded_amount`)과 환급 행 합이 다른 것. 환급 행
      없이 환급된 몫은 정산에서 빠지지 않고 사용으로 남는다.
    """

    __tablename__ = "creator_payout_batch_runs"

    # 그 달 1일(KST).
    period_month: Mapped[date] = mapped_column(Date, primary_key=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    creator_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount_krw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unattributed_spend_count: Mapped[int] = mapped_column(Integer, nullable=False)
    refund_event_mismatch_count: Mapped[int] = mapped_column(Integer, nullable=False)
