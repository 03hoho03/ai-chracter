import uuid
from datetime import datetime
from typing import Literal

from api.clover.products import ProductKey
from api.core.schema import CamelModel
from api.payments.methods import PayMethod

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
    # 구매로 받은 클로버(유료+보너스) 중 남은 양. 탈퇴하면 이 몫도 사라지므로 탈퇴 화면이 경고에 쓴다.
    paid_balance: int
    # `expires_at > now()`인 로트만 본다(이미 만료됐지만
    # 배치가 아직 못 지운 로트는 제외). 이건 표시 전용 필터라 "차감·잔액 판정 경로에는
    # 만료 필터를 걸지 않는다"는 원칙과 충돌하지 않는다 — 표시와 판정은 다른 경로다. **만료까지 3일
    # 이내인지는 BE가 판정한다**(`clover/router.py`의 `EXPIRING_SOON_THRESHOLD`) — 값(3일)과
    # 판정 주체(채우는 쪽) 둘 다 설계에서 정해진 것이다.
    expiring_soon: CloverExpiringSoon | None


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
    # 이미 청구했으면 false다. **에러가 아니다** — 멱등을 서버가 보장하므로
    # FE가 여러 번 불러도 200이고, `useEffect` 경합도 안전하다.
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


class CloverProductItem(CamelModel):
    key: ProductKey
    name: str
    # 부가세를 포함한 판매가(원).
    price_krw: int
    paid_amount: int
    bonus_amount: int


class CloverPayMethodItem(CamelModel):
    """포트원 브라우저 SDK 의 `payMethod` 와, 간편결제일 때 `easyPay.easyPayProvider` 값 그대로."""

    pay_method: PayMethod
    easy_pay_provider: str | None


class CloverPricingResponse(CamelModel):
    """공개 가격 안내. 단가는 기본 모델 기준만 싣는다 — 상위 모델은 허용된 계정만 쓰고 소설은 허용 명단 전용이라
    공개 안내에 넣지 않는다."""

    products: list[CloverProductItem]
    # 기본 모델로 쓰는 채팅 턴 하나와 이미지 한 장의 클로버.
    chat_turn_cost: int
    image_cost: int
    # 지금 결제를 받는가. 거짓이면 구매 화면이 "준비 중"을 보인다.
    payments_enabled: bool
    # 구매 화면이 고를 수 있는 결제수단(`payments/methods.py` 가 유일한 목록).
    pay_methods: list[CloverPayMethodItem]
    # 미인증 회원 게이트(무료 대화·미션을 본인인증한 회원에게만)가 켜져 있는가. 로그인하지 않은 방문자도 읽는 정책
    # 문장이 이 값으로 갈린다 — 꺼진 동안 "본인인증을 마친 회원은"이라고 쓰면 거짓이다. `GET /me` 와 같은 판정 함수다.
    identity_gate_enabled: bool
