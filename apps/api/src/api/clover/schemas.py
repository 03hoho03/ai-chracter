import uuid
from datetime import datetime
from typing import Literal

from api.clover.products import ProductKey
from api.core.schema import CamelModel
from api.llm.chat_models import ChatModelId
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


class CloverModelPricingItem(CamelModel):
    """글쓰기 모델 하나의 사용 단가. 모델 레지스트리(`llm/chat_models.py`)에서 채팅에서 고를 수 있는 모델만 레지스트리
    순서대로 실린다 — 이 목록은 채팅 모델 안내다. 채팅에서 고를 수 없는 모델(Sonnet)은 소설 상위 모델로 쓰이는데, 소설
    상위 모델은 별도 허용 명단에 든 계정만 써서 일반 회원은 살 수 없으므로 그 화 단가를 이 안내에 따로 싣지 않는다."""

    id: ChatModelId
    name: str
    # 새 대화방이 고르는 기본 모델인가.
    is_default: bool
    # 화면이 베타 표시를 붙이는가. 레지스트리의 고정 속성이라 기능 스위치가 꺼져 있어도 켜져 있어도 같은 값이다 — 스위치
    # 상태를 내보내면 비로그인 방문자에게 기능이 켜졌는지가 드러난다(소설 라우트가 꺼짐·미허용을 한 가지 거부로 내는 것과
    # 같은 이유).
    beta: bool
    # 이 모델로 쓰는 채팅 턴 하나와 소설 화 하나의 클로버. 소설 화 단가는 모델별 목록이 채팅 모델 안내가 된 뒤에도 이 칸을
    # 가드 없이 읽는 옛 화면을 위해 남긴다 — 그래서 Opus 행의 소설 화 단가는 응답에 계속 보인다. 기본 모델 값은 응답
    # 최상위 `novel_episode_cost` 에도 있다.
    chat_turn_cost: int
    novel_episode_cost: int


class CloverPricingResponse(CamelModel):
    """공개 가격 안내. 구매 전 안내에 없는 사용처 가격은 숨은 가격으로 읽히므로 일반 회원이 쓸 수 있는 모든 사용처(채팅에서
    고를 수 있는 상위 모델 포함)의 단가와, 허용된 계정만 쓰는 소설(기본 모델 화·AI 수정)의 단가를 싣고 소설은 그
    사실(`novel_restricted`)을 함께 싣는다. 소설 상위 모델의 화 단가는 따로 싣지 않는다 — 소설 허용에 더해 별도 명단에 든
    계정만 쓰고 일반 회원은 살 수 없는 선택지라서다. 다만 모델 행의 `novel_episode_cost` 칸이 옛 화면 호환용으로 남아 있어
    Opus 행의 소설 화 단가는 계속 보인다."""

    products: list[CloverProductItem]
    # 기본 모델로 쓰는 채팅 턴 하나와 이미지 한 장의 클로버. 채팅 턴은 `models` 의 기본 모델 값과 같다 — 모델별 목록이
    # 생기기 전에 배포된 화면이 이 칸을 읽으므로 남겨 둔다.
    chat_turn_cost: int
    image_cost: int
    models: list[CloverModelPricingItem]
    # 기본 모델로 쓰는 소설 화 하나의 클로버. `models` 의 기본 모델 값과 같다 — `models` 가 채팅에서 고를 수 있는 모델만
    # 싣게 되어 소설 단가 안내는 이 칸을 읽는다.
    novel_episode_cost: int
    # AI 문단 수정 한 번의 클로버. 모델과 무관하다(언제나 기본 모델로 고친다).
    novel_ai_edit_cost: int
    # 소설(화 생성·AI 수정)이 허용된 계정 전용인가.
    novel_restricted: bool
    # 하루에 클로버 없이 쓸 수 있는 대화 턴 수. 로그인한 화면은 `GET /me` 의 같은 값을 읽지만 공개 안내는 그 응답을
    # 못 읽는다.
    daily_free_chat_turns: int
    # 노벨 화 하나의 소장 가격과, 소설마다 앞에서부터 무료로 읽는 화 수. 노벨이 꺼져 있어도 싣는다(가격표는 정책 안내다).
    novel_read_cost: int
    novel_free_chapter_count: int
    # 노벨이 모두에게 열려 있는가. 로그인하지 않은 방문자에게도 노벨 탭을 보이려면(누르면 로그인 유도) 인증 없는 응답에 이
    # 값이 있어야 한다 — `GET /me` 는 로그인한 사람만 읽는다. 꺼져 있으면 화면이 탭과 노벨 화면을 숨긴다. 누가 보는지 모르는
    # 응답이라 미리보기 명단이 있는 동안은 거짓이다 — 명단 회원에게는 `GET /me` 의 같은 이름 값이 탭을 연다.
    novel_public_enabled: bool
    # 지금 결제를 받는가. 거짓이면 구매 화면이 "준비 중"을 보인다.
    payments_enabled: bool
    # 구매 화면이 고를 수 있는 결제수단(`payments/methods.py` 가 유일한 목록).
    pay_methods: list[CloverPayMethodItem]
    # 미인증 회원 게이트(무료 대화·미션을 본인인증한 회원에게만)가 켜져 있는가. 로그인하지 않은 방문자도 읽는 정책
    # 문장이 이 값으로 갈린다 — 꺼진 동안 "본인인증을 마친 회원은"이라고 쓰면 거짓이다. `GET /me` 와 같은 판정 함수다.
    identity_gate_enabled: bool
