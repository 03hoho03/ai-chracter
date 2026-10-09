from datetime import datetime
from typing import Literal

from api.core.schema import CamelModel
from api.db.models.creator_payout import CreatorPayoutApplicationStatus


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
