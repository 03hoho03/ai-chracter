"""크리에이터 정산 — 정산 신청(`creator_payout_applications`), 확정 행(`creator_payout_confirmations`), 확정 행의 작품 ×
결제별 내역(`creator_payout_confirmation_lines`), 월 확정 배치의 달별 실행 기록(`creator_payout_batch_runs`), 지급 정보
(`creator_payout_profiles`), 지급 신청·기록(`creator_payouts`).

확정·내역·배치 실행 기록·지급 테이블은 탈퇴해도 지우지 않는다 — 확정 행과 내역은 지급·세무의 근거이고, 지급 행은
원천징수와 지급명세서의 근거라 세법상 장부로 보존한다. 지급 정보는 어느 지급도 가리키지 않는 판만 탈퇴 때 지운다. 신청 행은
동의로 받은 기록이라 탈퇴하면 지운다(`auth/withdrawal.py`). 그래서 확정 행·내역은 신청 행을 참조하지 않고, 지급 처리도 신청
행을 읽지 않는다.
상태·종류는 Text + Literal + CHECK 이다(`db/models/payment.py` 와 같은 방식). 🔴 `alembic check` 는 CHECK·부분 인덱스의
WHERE·복합 PK 를 비교하지 않는다 — 이 파일의 제약은 `pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증이다.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.payment import _sql_in_list

# 신청 상태. pending → approved | rejected, approved → revoked. rejected·revoked 는 끝이고 다시 신청하면 새 행이다.
CreatorPayoutApplicationStatus = Literal["pending", "approved", "rejected", "revoked"]
# 확정 종류. retro 는 첫 승인 때 지난 기간을 한 번 세는 행, monthly 는 매달 확정하는 행이다.
CreatorPayoutConfirmationKind = Literal["retro", "monthly"]
# 지급 상태. requested → paid | returned | held, held → paid. paid·returned 는 끝이고, 반려된 금액은 잔액(파생값)으로
# 저절로 돌아온다. held 는 탈퇴한 회원의 건만 간다 — 탈퇴 회원은 다시 신청할 수 없어 반려하면 금액이 갈 곳을 잃으므로,
# 이체할 수 없으면 반려 대신 보류하고 수취 정보를 새로 받아 이체한다. 보류된 금액은 잔액으로 돌아오지 않는다.
CreatorPayoutStatus = Literal["requested", "held", "paid", "returned"]
# 아직 이체하지 않은 지급. 한 사람에 하나이고, 있으면 새 지급 신청과 지급 정보 변경을 받지 않는다.
IN_PROGRESS_PAYOUT_STATUSES: tuple[CreatorPayoutStatus, ...] = ("requested", "held")
# 지급 정보의 은행 코드(금융결제원 3자리 표준 코드). 입력은 이 목록 밖 코드를 받지 않는다. DB CHECK 는 두지 않는다 —
# 은행이 합쳐져 목록이 바뀌어도 이미 지급에 쓰인 판은 남아야 한다(그때 응답 타입도 함께 넓힌다).
BankCode = Literal[
    "002",  # KDB산업은행
    "003",  # IBK기업은행
    "004",  # KB국민은행
    "007",  # 수협은행
    "011",  # NH농협은행
    "012",  # 지역 농·축협
    "020",  # 우리은행
    "023",  # SC제일은행
    "027",  # 한국씨티은행
    "031",  # iM뱅크(대구은행)
    "032",  # 부산은행
    "034",  # 광주은행
    "035",  # 제주은행
    "037",  # 전북은행
    "039",  # 경남은행
    "045",  # 새마을금고
    "048",  # 신협
    "050",  # 저축은행
    "064",  # 산림조합
    "071",  # 우체국
    "081",  # 하나은행
    "088",  # 신한은행
    "089",  # 케이뱅크
    "090",  # 카카오뱅크
    "092",  # 토스뱅크
]

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
    # 거절·승인 취소 사유. 신청자에게 보인다(승인은 쓰지 않는다).
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


class CreatorPayoutProfile(Base):
    """지급 정보 한 판(실명·주민등록번호·은행·계좌). 고치지 않는다 — 회원이 다시 입력하면 새 행을 넣고 이전 행에
    `superseded_at` 을 세운다. 지급 행이 신청 때의 판을 FK 로 가리키므로, 신청 뒤 정보를 바꿔도 처리 중인 지급의 수취인이
    바뀌지 않고 주민등록번호 사본이 지급 건 수만큼 늘지도 않는다.

    회원이 입력 화면에서 동의하고 넣은 판은 동의 시각과 처리방침 버전을 갖는다. 탈퇴한 회원의 처리 중인 지급을 이체하려고
    운영자가 문의로 받은 정보를 넣은 판은 동의 칸 대신 넣은 운영자(`entered_by_admin_id`)를 갖고, 그 지급 행이 새 판을
    가리킨다 — 지급 행이 가리키는 판이 늘 실제로 이체한 수취인이라 지급명세서가 그 판을 읽는다.

    실명·주민등록번호·계좌번호는 `key_id` 의 키로 암호화한 `nonce ‖ 암호문 ‖ tag` 이고, 연관 데이터가 이 행의 id 와 칸
    이름이다(`creator_payout/payout_info.py`) — 그래서 id 를 INSERT 전에 정한다. 키를 바꾼 뒤 다시 암호화하는 것
    (`creator_payout/reencrypt.py`)이 이 행을 고치는 유일한 경로이고 값은 그대로다. 은행 코드와 계좌 끝 4자리는 화면 표시용
    평문이다.
    """

    __tablename__ = "creator_payout_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_creator_payout_profiles_user_id"), nullable=False
    )
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rrn_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    account_number_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    bank_code: Mapped[BankCode] = mapped_column(Text, nullable=False)
    account_last4: Mapped[str] = mapped_column(Text, nullable=False)
    # 지급 정보 입력 화면의 수집·이용(국외이전 포함) 동의 시각과 그때 게시돼 있던 개인정보 처리방침 버전. 운영자가 넣은
    # 판은 둘 다 없다.
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 탈퇴한 회원의 지급을 이체하려고 이 판을 넣은 운영자. 회원이 넣은 판은 없다.
    entered_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_creator_payout_profiles_entered_by_admin_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("key_id <> ''", name="ck_creator_payout_profiles_key_id"),
        CheckConstraint("char_length(account_last4) = 4", name="ck_creator_payout_profiles_account_last4"),
        # 판은 회원이 동의하고 넣었거나 운영자가 넣었거나 둘 중 하나다.
        CheckConstraint(
            "(entered_by_admin_id IS NULL) = (consented_at IS NOT NULL)", name="ck_creator_payout_profiles_source"
        ),
        CheckConstraint(
            "(consented_at IS NULL) = (privacy_version IS NULL)", name="ck_creator_payout_profiles_consent"
        ),
        # 지금 쓰는 판은 한 사람에 하나.
        Index(
            "ux_creator_payout_profiles_user_id_current",
            "user_id",
            unique=True,
            postgresql_where=superseded_at.is_(None),
        ),
    )


class CreatorPayout(Base):
    """지급 신청 하나와 그 처리 기록. 금액은 신청 때의 확정 잔액 전액이고, 원천징수 세율·세액은 신청 때 계산한 값을
    남긴다 — 세율이 나중에 바뀌어도 이 건이 어느 세율로 계산됐는지가 남는다(끝수를 버려 세액만으로는 세율을 되짚기
    어렵다). 실제 이체는 운영자가 은행에서 하고 이 행은 그 기록만 한다.

    적립 잔액은 확정 금액 합에서 `requested`·`held`·`paid` 금액을 뺀 파생값이라, 반려는 상태만 바꾸면 잔액이 돌아온다.
    `for_withdrawal` 은 최소 지급액 미만을 탈퇴 전 예외로 실제로 신청한 건만 참이다.
    """

    __tablename__ = "creator_payouts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_creator_payouts_user_id"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("creator_payout_profiles.id", name="fk_creator_payouts_profile_id"), nullable=False
    )
    status: Mapped[CreatorPayoutStatus] = mapped_column(Text, nullable=False)
    amount_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    for_withdrawal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    income_tax_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    income_tax_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    local_tax_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    net_amount_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 운영자가 적는 실제 이체일(KST 날짜).
    transferred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 보류한 시각. 보류한 건을 이체한 뒤에도 남아 보류를 거쳤다는 것을 보인다.
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_creator_payouts_decided_by_admin_id"), nullable=True
    )
    # 이체 메모. 운영자만 본다.
    admin_memo: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # 반려 사유. 신청자에게 보인다.
    return_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # 보류 사유. 운영자만 본다(보류는 탈퇴한 회원의 건이라 보일 사람이 없다).
    hold_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    __table_args__ = (
        CheckConstraint(f"status IN ({_sql_in_list(CreatorPayoutStatus)})", name="ck_creator_payouts_status"),
        CheckConstraint("amount_krw > 0", name="ck_creator_payouts_amount"),
        CheckConstraint("income_tax_rate_bps > 0", name="ck_creator_payouts_income_tax_rate_bps"),
        CheckConstraint(
            "income_tax_krw >= 0 AND local_tax_krw >= 0", name="ck_creator_payouts_taxes_non_negative"
        ),
        CheckConstraint(
            "net_amount_krw = amount_krw - income_tax_krw - local_tax_krw", name="ck_creator_payouts_net_amount"
        ),
        CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL AND transferred_on IS NOT NULL)", name="ck_creator_payouts_paid"
        ),
        CheckConstraint("(status = 'returned') = (returned_at IS NOT NULL)", name="ck_creator_payouts_returned"),
        # 보류에서 이체로 넘어간 건도 보류 시각을 남기므로 한쪽 방향만 묶는다. 반려된 건은 보류를 거치지 않았다.
        CheckConstraint(
            "(status <> 'held' OR held_at IS NOT NULL) AND (status <> 'returned' OR held_at IS NULL)",
            name="ck_creator_payouts_held",
        ),
        # 처리 중(보류 포함)인 지급은 한 사람에 하나.
        Index(
            "ux_creator_payouts_user_id_in_progress",
            "user_id",
            unique=True,
            postgresql_where=status.in_(IN_PROGRESS_PAYOUT_STATUSES),
        ),
        # 어드민 지급 큐.
        Index("ix_creator_payouts_status_requested_at", "status", "requested_at"),
        # 회원의 지급 내역과 잔액 계산.
        Index("ix_creator_payouts_user_id_requested_at", "user_id", requested_at.desc()),
    )
