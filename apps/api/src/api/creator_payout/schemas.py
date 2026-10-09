import uuid
from datetime import date, datetime
from typing import Literal

from api.core.schema import CamelModel
from api.db.models.creator_payout import CreatorPayoutApplicationStatus, CreatorPayoutConfirmationKind


class ApplyCreatorPayoutRequest(CamelModel):
    # 정산 신청 화면의 개인정보 수집·이용 동의. 동의하지 않은 신청은 만들지 않는다.
    agreed: Literal[True]


class ApplyCreatorPayoutResponse(CamelModel):
    status: Literal["pending"]


class CreatorPayoutApplicationView(CamelModel):
    """가장 최근 신청. 거절 사유(`decisionReason`)는 신청자에게 보이는 글이다."""

    status: CreatorPayoutApplicationStatus
    applied_at: datetime
    decided_at: datetime | None
    decision_reason: str


class CreatorPayoutEligibilityView(CamelModel):
    """신청 자격. 신청과 같은 판정 함수의 값이라 화면이 미리 보여 주는 자격과 신청의 거절이 갈리지 않는다."""

    identity_verified: bool
    adult: bool
    has_published_work: bool
    suspended: bool


class CreatorPayoutResponse(CamelModel):
    application: CreatorPayoutApplicationView | None
    eligibility: CreatorPayoutEligibilityView
    # 승인된 적이 있는가(승인 중이거나 승인 취소됨). 승인 취소 뒤에도 확정된 적립은 남아 지급을 신청할 수 있어서, 최근
    # 신청이 다시 대기 중이어도 참이다.
    ever_approved: bool
    # 적립 잔액(원) = 확정 행 금액의 합. 저장하지 않고 매번 더한다. 확정 뒤 결제 취소 조정이 크면 음수일 수 있고, 음수는
    # 다음 적립과 상계된다.
    balance_krw: int


class CreatorPayoutStatementLineView(CamelModel):
    """확정 하나의 작품별 내역(결제별 내역을 작품으로 합친 값). 원 단위는 원 미만을 0 쪽으로 버린 표시값이라 줄의 합이
    확정 금액과 다를 수 있다 — 합계는 확정의 `amountKrw` 를 쓴다."""

    content_id: uuid.UUID
    # 작품의 가장 최근 발행본 이름. 발행된 적이 없으면 빈 문자열이다.
    content_title: str
    # 그 확정의 적립 구간 안 순사용(유료 클로버, 환급이 크면 음수).
    net_units: int
    # 확정 뒤 결제 취소로 앞선 몫을 줄인 금액(0 이하).
    cancel_adjust_krw: int
    amount_krw: int


class CreatorPayoutStatementView(CamelModel):
    """확정 하나. `retro` 는 첫 승인 때의 소급, `monthly` 는 그 달(`periodMonth`, KST 1일) 확정이다."""

    kind: CreatorPayoutConfirmationKind
    period_month: date | None
    window_start: datetime
    window_end: datetime
    gross_units: int
    refunded_units: int
    amount_krw: int
    lines: list[CreatorPayoutStatementLineView]


class CreatorPayoutStatementsResponse(CamelModel):
    items: list[CreatorPayoutStatementView]
    next_cursor: str | None
