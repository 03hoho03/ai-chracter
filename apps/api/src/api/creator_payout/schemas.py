import uuid
from datetime import date, datetime
from typing import Literal

from api.core.schema import CamelModel
from api.db.models.creator_payout import (
    BankCode,
    CreatorPayoutApplicationStatus,
    CreatorPayoutConfirmationKind,
    CreatorPayoutStatus,
)


class ApplyCreatorPayoutRequest(CamelModel):
    # 정산 신청 화면의 개인정보 수집·이용 동의. 동의하지 않은 신청은 만들지 않는다.
    agreed: Literal[True]


class ApplyCreatorPayoutResponse(CamelModel):
    status: Literal["pending"]


class CreatorPayoutApplicationView(CamelModel):
    """가장 최근 신청. `decisionReason` 은 거절·승인 취소 사유로 신청자에게 보이는 글이다. `decidedAt` 은 승인·거절한
    시각이고, 승인 취소된 신청의 취소 시각은 `revokedAt` 이다."""

    status: CreatorPayoutApplicationStatus
    applied_at: datetime
    decided_at: datetime | None
    decision_reason: str
    revoked_at: datetime | None


class CreatorPayoutEligibilityView(CamelModel):
    """신청 자격. 신청과 같은 판정 함수의 값이라 화면이 미리 보여 주는 자격과 신청의 거절이 갈리지 않는다."""

    identity_verified: bool
    adult: bool
    has_published_work: bool
    suspended: bool


class CreatorPayoutInfoView(CamelModel):
    """등록한 지급 정보의 표시값. 주민등록번호는 싣지 않는다. `maskedName` 은 실명의 첫·끝 글자만 남긴 값이고, 암호화 키를
    잃어 복호화할 수 없으면 null 이다(은행·계좌 끝 4자리는 평문이라 그대로 보인다) — 그때는 지급 정보를 다시 입력받는다."""

    masked_name: str | None
    bank_code: BankCode
    account_last4: str


class CreatorPayoutInProgressView(CamelModel):
    amount_krw: int
    requested_at: datetime


class CreatorPayoutResponse(CamelModel):
    application: CreatorPayoutApplicationView | None
    eligibility: CreatorPayoutEligibilityView
    # 승인된 적이 있는가(승인 중이거나 승인 취소됨). 승인 취소 뒤에도 확정된 적립은 남아 지급을 신청할 수 있어서, 최근
    # 신청이 다시 대기 중이어도 참이다.
    ever_approved: bool
    # 적립 잔액(원) = 확정 행 금액의 합 − 처리 중·지급된 지급 금액. 저장하지 않고 매번 더한다(반려된 지급은 빼지 않아
    # 저절로 돌아온다). 지급 뒤 확정 뒤 결제 취소 조정이 들어오면 음수일 수 있고, 음수는 다음 적립과 상계된다.
    balance_krw: int
    # 적립 비율(만분율, 500 = 5%). 서버 설정값이라 웹이 사본을 두지 않고 이 값으로 비율을 말한다.
    rate_bps: int
    # 지급을 신청할 수 있는 최소 잔액(원). 탈퇴하려는 회원은 이보다 적어도 탈퇴 화면에서 신청할 수 있다.
    minimum_payout_krw: int
    # 지급 정보 입력·지급 신청을 지금 받는가. 거짓이면(지급 정보 암호화 키가 없음) 두 요청이 503 이라 화면이 지급 버튼을
    # 숨긴다. 신청·적립·확정·조회는 이 값과 무관하게 돈다.
    payout_available: bool
    # 지금 쓰는 지급 정보. 등록한 적이 없으면 null.
    payout_info: CreatorPayoutInfoView | None
    # 처리 중인 지급 신청. 있으면 새 신청도, 지급 정보 변경도 할 수 없다.
    in_progress_payout: CreatorPayoutInProgressView | None


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


class PutPayoutInfoRequest(CamelModel):
    """지급 정보. 형식은 라우터가 확인하고 `CREATOR_PAYOUT_INFO_INVALID` 로 답한다 — 스키마 검증 오류는 입력값을 응답에
    되돌려 싣기 때문이다. 실명은 앞뒤 공백을 빼고 1~40자, 주민등록번호는 숫자 13자리(하이픈 없이), 계좌번호는 숫자
    6~20자리(하이픈 없이), 은행은 코드 목록 안. `agreed` 는 지급 정보 수집·이용과 국외이전 동의다."""

    legal_name: str
    rrn: str
    bank_code: str
    account_number: str
    agreed: Literal[True]


class RequestPayoutRequest(CamelModel):
    # 탈퇴 화면에서 최소 지급액 미만 잔액을 신청하는가. 잔액이 최소액 이상이면 무시하고 일반 신청으로 남긴다.
    for_withdrawal: bool = False


class RequestPayoutResponse(CamelModel):
    """신청한 금액(확정 잔액 전액)과 떼는 원천징수, 실지급액."""

    amount_krw: int
    income_tax_krw: int
    local_tax_krw: int
    net_amount_krw: int


class CreatorPayoutPayoutView(CamelModel):
    """지급 신청 하나. `transferredOn` 은 이체한 날(KST), `returnReason` 은 반려 사유다."""

    id: uuid.UUID
    status: CreatorPayoutStatus
    amount_krw: int
    income_tax_krw: int
    local_tax_krw: int
    net_amount_krw: int
    requested_at: datetime
    transferred_on: date | None
    return_reason: str


class CreatorPayoutPayoutsResponse(CamelModel):
    items: list[CreatorPayoutPayoutView]
