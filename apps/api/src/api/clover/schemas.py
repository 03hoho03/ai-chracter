import uuid
from datetime import datetime
from typing import Literal

from api.core.schema import CamelModel

# 원장 조회 쿼리 파라미터와 응답 `category` 필드가
# 같은 타입을 공유한다.
CloverLedgerCategory = Literal["use", "earn", "expire"]


class CloverExpiringSoon(CamelModel):
    """가장 임박한 만료 묶음 — 같은 시각 만료 로트는 합산."""

    amount: int
    expires_at: datetime


class CloverBalanceResponse(CamelModel):
    """Python은 snake_case, JSON은 camelCase다."""

    balance: int
    # 오늘(KST) 이미 확인했는가 — false면 FE가 소진 시 확인 모달을 띄운다.
    spend_confirmed_today: bool
    # 오늘(KST) 출석을 아직 안 받았는가 — true면 FE가 attendance를 POST한다.
    attendance_claimable: bool
    # `expires_at > now()`인 로트만 본다(이미 만료됐지만
    # 배치가 아직 못 지운 로트는 제외). 이건 표시 전용 필터라 "차감·잔액 판정 경로에는
    # 만료 필터를 걸지 않는다"는 원칙과 충돌하지 않는다 — 표시와 판정은 다른 경로다. **만료까지 3일
    # 이내인지는 BE가 판정한다**(`clover/router.py`의 `EXPIRING_SOON_THRESHOLD`) — 값(3일)과
    # 판정 주체(채우는 쪽) 둘 다 설계에서 정해진 것이다.
    expiring_soon: CloverExpiringSoon | None


class CloverAttendanceResponse(CamelModel):
    # 오늘 이미 받았으면 false다. **에러가 아니다** — 멱등을 서버가 보장하므로
    # FE가 여러 번 불러도 200이고, `useEffect` 경합도 안전하다.
    granted: bool
    balance: int


class CloverMissionItem(CamelModel):
    """`achieved`·`claimed`는 매 조회마다 EXISTS로 다시
    계산한다 — 저장된 상태가 아니다."""

    key: str
    reward: int
    achieved: bool
    # 원장에 이 미션의 멱등키가 이미 있는가 — true면 FE가 "청구완료"로 표시한다.
    claimed: bool


class CloverMissionsResponse(CamelModel):
    missions: list[CloverMissionItem]


class CloverMissionClaimResponse(CamelModel):
    # 이미 청구했으면 false다 — 출석(`CloverAttendanceResponse.granted`)과 같은 규칙,
    # **에러가 아니다**.
    granted: bool
    balance: int


class CloverLedgerItem(CamelModel):
    """`category`는 BE의 `kind`→범주 맵
    (`clover/router.py`의 `CLOVER_KIND_CATEGORY`)을 그대로 실어 보낸 것이다 — FE가 같은 맵을
    다시 두지 않는다."""

    id: uuid.UUID
    amount: int
    balance_after: int
    # `db/models/clover.py`의 `kind`와 같은 이유로 `Literal`이 아니라 `str`이다 — `AdminCloverLedgerItem`
    # 선례(`admin/schemas.py`)와 같다.
    kind: str
    category: CloverLedgerCategory
    created_at: datetime


class CloverLedgerListResponse(CamelModel):
    """`DraftListResponse`(`content/schemas.py`)와 같은 커서 페이지네이션 봉투."""

    items: list[CloverLedgerItem]
    next_cursor: str | None
