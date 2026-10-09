"""클로버 구매 주문(`payments`)과 그 취소 기록(`payment_cancellations`).

주문·취소 행은 **탈퇴해도 지우지 않는다** — 전자상거래 결제 기록의 법정 보존 기간(5년) 동안 남긴다. `user_id` 는 탈퇴로
가명이 된 사용자 행을 가리킬 뿐 개인정보를 담지 않고, 결제수단 정보는 저장하지 않는다.

종류·상태는 native enum 이 아니라 Text + Literal 이고 DB 쪽 범위는 CHECK 가 막는다(`db/models/novel.py` 와 같은 방식).
🔴 `alembic check` 는 CHECK 와 부분 인덱스의 WHERE 를 비교하지 않는다 — 이 파일의 CHECK·부분 유니크는
`pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증이다. Literal 을 바꾸면 마이그레이션을 손으로 더한다.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal, get_args

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base

# 주문 상태. 전이는 전부 주문 행을 `FOR UPDATE` 로 잠근 채 일어난다(`payments/service.py`).
# - pending: 주문만 만들었다. failed: 포트원이 실패라고 했다(그 뒤 결제 완료가 오면 paid 로 간다 — 포트원 상태가 진실이다).
# - paid: 대조를 통과해 클로버를 지급했다. mismatch: 포트원은 결제 완료인데 주문과 맞지 않아 지급하지 않았다(수동 처리).
# - owner_withdrawn: 결제는 완료됐는데 확정 시점에 주문자가 이미 탈퇴해 지급하지 않았다(운영자가 포트원 콘솔에서 환불하고,
#   그 취소 웹훅이 cancelled 로 맞춘다).
# - cancelled / partially_cancelled: 포트원에서 전액·일부가 취소됐다.
PaymentStatus = Literal[
    "pending", "paid", "failed", "mismatch", "owner_withdrawn", "cancelled", "partially_cancelled"
]
PaymentCancellationSource = Literal["admin", "console"]
PaymentCancellationStatus = Literal["requested", "succeeded", "failed"]


def _sql_in_list(literal: Any) -> str:
    return ", ".join(f"'{value}'" for value in get_args(literal))


class Payment(Base):
    """클로버 구매 주문 하나 = 포트원 결제 하나. 상품의 가격·수량은 주문 시점 값을 복사해 둔다 — 상품 정의가 바뀌어도
    이미 낸 주문의 대조 기준과 지급량이 흔들리지 않게.

    "취소 상태면 `paid_at` 이 있다" 같은 CHECK 는 두지 않는다 — 지급 전에 전액 취소된 건(pending → cancelled)이 정상이라
    거짓 거부가 된다.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 포트원에 넘기는 결제 id. 서버가 발급한다(`clv` + uuid4 hex).
    payment_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_payments_user_id"), nullable=False
    )
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    order_name: Mapped[str] = mapped_column(Text, nullable=False)
    # 부가세 포함 결제 금액(원)과 지급할 유료·보너스 수량 — 주문 시점 상품 정의의 사본.
    amount_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # 주문 시점의 결제 채널키. 결제 대조가 포트원 응답의 채널키를 이 값과 비교한다.
    channel_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(Text, nullable=False)
    # 상태의 사유(대조에서 어긋난 항목 이름 등). 개인정보를 넣지 않는다.
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 유료 조건(청약철회 제한·환불정책)에 동의한 시각과, 그때 게시돼 있던 약관·환불정책 버전.
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terms_version: Mapped[str] = mapped_column(Text, nullable=False)
    refund_policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    # 포트원 거래 id(대사용)와 결제 완료 시각.
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 포트원에서 성공한 취소 금액의 합.
    cancelled_amount_krw: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({_sql_in_list(PaymentStatus)})", name="ck_payments_status"),
        CheckConstraint(
            "amount_krw > 0 AND paid_amount > 0 AND bonus_amount >= 0", name="ck_payments_amounts_positive"
        ),
        CheckConstraint(
            "cancelled_amount_krw >= 0 AND cancelled_amount_krw <= amount_krw", name="ck_payments_cancelled_in_range"
        ),
        Index("ux_payments_payment_id", "payment_id", unique=True),
        Index("ix_payments_user_id_created_at", "user_id", created_at.desc()),
    )


class PaymentCancellation(Base):
    """결제 하나의 취소 시도·결과. 어드민 환불(`admin`)과 포트원 콘솔에서 직접 한 취소(`console`)를 함께 담는다.

    - requested: 클로버는 회수했고 포트원 결과가 성공으로 확정되지 않았다. succeeded: 포트원이 취소 성공을 확인했다.
      failed: 포트원이 확정 거절해 회수분을 되돌렸다.
    - 한 결제에 진행 중(`requested`) 시도는 하나뿐이다(부분 유니크) — 이 행 자체가 환불 시도의 멱등 단위다.
    - `clawback_paid`·`clawback_bonus` 는 이 행 때문에 회수한 유료·보너스 수량이다.
    """

    __tablename__ = "payment_cancellations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payments.id", name="fk_payment_cancellations_payment_id"), nullable=False
    )
    source: Mapped[PaymentCancellationSource] = mapped_column(Text, nullable=False)
    status: Mapped[PaymentCancellationStatus] = mapped_column(Text, nullable=False)
    amount_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    # 어드민 견적의 환불 비율(%).
    ratio_percent: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # 어드민 행만: 환불 신청을 받은 날(KST 날짜).
    request_received_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 회사 귀책이라 비율을 100% 로 둔 환불인가.
    company_fault: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    clawback_paid: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    clawback_bonus: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # 포트원이 돌려준 취소 id(성공·대기 모두).
    portone_cancellation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_payment_cancellations_admin_id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # 어드민 행만: 이 시도의 취소를 포트원에 마지막으로 보내기 시작한 시각. 결제 행 잠금 아래에서 적고, 그 뒤 포트원 호출
    # 상한보다 짧은 동안은 재시도가 다시 보내지 않는다(같은 취소가 동시에 두 번 나가지 않게).
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"source IN ({_sql_in_list(PaymentCancellationSource)})", name="ck_payment_cancellations_source"
        ),
        CheckConstraint(
            f"status IN ({_sql_in_list(PaymentCancellationStatus)})", name="ck_payment_cancellations_status"
        ),
        CheckConstraint("amount_krw > 0", name="ck_payment_cancellations_amount_positive"),
        CheckConstraint("(source = 'admin') = (admin_id IS NOT NULL)", name="ck_payment_cancellations_admin_source"),
        CheckConstraint(
            "(source = 'admin') = (request_received_on IS NOT NULL)", name="ck_payment_cancellations_admin_received_on"
        ),
        CheckConstraint(
            "clawback_paid >= 0 AND clawback_bonus >= 0", name="ck_payment_cancellations_clawback_non_negative"
        ),
        Index(
            "ux_payment_cancellations_payment_id_requested",
            "payment_id",
            unique=True,
            postgresql_where=status == "requested",
        ),
        Index("ux_payment_cancellations_portone_cancellation_id", "portone_cancellation_id", unique=True),
    )
