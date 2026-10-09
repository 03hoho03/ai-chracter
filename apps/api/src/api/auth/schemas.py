import uuid
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from api.auth.age import is_under_minimum_age
from api.auth.oauth_common import OAuthProvider
from api.core.schema import CamelModel
from api.db.models.feature_grant import FeatureName
from api.payments.eligibility import PurchaseBlockReason

# 화면이 진입점을 보이고 숨기는 기능 이름. 계정별 허용 행이 있는 기능(`FeatureName`)에 전역 스위치뿐인 크리에이터 정산을
# 더한다 — `FeatureName` 자체를 넓히면 정산이 계정별 허용 행을 만들 수 있는 값으로 타입 검사를 통과한다.
EnabledFeature = FeatureName | Literal["creator_payout"]


class SignupRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: str = Field(min_length=1)
    birth_date: date
    terms_agreed: bool
    privacy_agreed: bool
    transfer_agreed: bool

    @field_validator("birth_date")
    @classmethod
    def _must_meet_minimum_age(cls, value: date) -> date:
        # 만 14세 미만은 가입을 거부한다.
        if is_under_minimum_age(value, datetime.now(UTC).date()):
            raise ValueError("만 14세 미만은 가입할 수 없습니다.")
        return value

    @field_validator("terms_agreed", "privacy_agreed", "transfer_agreed")
    @classmethod
    def _must_be_agreed(cls, value: bool) -> bool:
        if not value:
            raise ValueError("이용약관 및 개인정보처리방침에 모두 동의해야 합니다.")
        return value


class SignupResponse(CamelModel):
    email: str


class VerifyEmailRequest(CamelModel):
    email: EmailStr
    code: str


class VerifyEmailResponse(CamelModel):
    pass


class ResendVerificationCodeRequest(CamelModel):
    email: EmailStr


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class SocialOnboardingRequest(CamelModel):
    """소셜 가입(구글·카카오) 온보딩이 함께 쓰는 요청 — 생성 타입이 provider 마다 갈리지 않게
    하나로 둔다. 가입 대기 토큰은 본문이 아니라 HttpOnly 쿠키로 받는다: URL·히스토리·리퍼러로
    토큰이 새도 그 쿠키가 없는 다른 브라우저에서는 가입을 끝낼 수 없게 하려는 것이다."""

    nickname: str = Field(min_length=1)
    birth_date: date
    terms_agreed: bool
    privacy_agreed: bool
    transfer_agreed: bool

    @field_validator("birth_date")
    @classmethod
    def _must_meet_minimum_age(cls, value: date) -> date:
        # 만 14세 미만은 가입을 거부한다.
        if is_under_minimum_age(value, datetime.now(UTC).date()):
            raise ValueError("만 14세 미만은 가입할 수 없습니다.")
        return value

    @field_validator("terms_agreed", "privacy_agreed", "transfer_agreed")
    @classmethod
    def _must_be_agreed(cls, value: bool) -> bool:
        if not value:
            raise ValueError("이용약관 및 개인정보처리방침에 모두 동의해야 합니다.")
        return value


class SocialOnboardingResponse(CamelModel):
    email: str


class PasswordResetRequestRequest(CamelModel):
    email: EmailStr


class PasswordResetConfirmRequest(CamelModel):
    token: str
    new_password: str = Field(min_length=8)


class ChangePasswordRequest(CamelModel):
    current_password: str
    new_password: str = Field(min_length=8)


class WithdrawRequest(CamelModel):
    """탈퇴 재인증. 비밀번호가 있는 계정만 값을 요구하고, 그 판정은 서버가 계정을 보고 한다. 필드를
    선택으로 두는 이유: 소셜 계정의 프런트가 값 없이 보낸 `{}` 가 422 로 막히지 않게 한다."""

    current_password: str | None = None


class MeResponse(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str
    bio: str | None
    profile_image_asset_id: uuid.UUID | None
    terms_reconsent_required: bool
    privacy_reconsent_required: bool
    # 한 계정이 비밀번호와 소셜 연동을 함께 가질 수 있어(이메일이 같으면 구글 로그인이 기존
    # 비밀번호 계정에 연동된다) 단일 "가입 방식" 값이 아니라 두 필드로 낸다.
    has_password: bool
    social_provider: OAuthProvider | None
    # 이 계정이 지금 쓸 수 있는 기능. 서버가 라우트 게이트와 같은 판정으로 계산하고 FE 는 이것으로 진입점만
    # 숨긴다(막는 것은 서버 게이트다).
    enabled_features: list[EnabledFeature]
    # 휴대폰 본인인증을 마쳤는가.
    identity_verified: bool
    # 미인증 회원의 무료 대화·미션을 막는 게이트가 켜져 있는가. 라우트 게이트와 같은 판정 함수의 값이다 — 꺼져 있으면
    # 화면이 미인증 회원에게 인증 안내를 띄울 이유가 없다.
    identity_gate_enabled: bool
    # 이 회원이 지금 게이트에 걸리는가 — 스위치·인증 여부·레이트리밋 면제를 라우트 게이트와 같은 함수로 판정한 값이다.
    # 화면이 스위치와 인증 여부로 따로 판정하면 면제 회원의 미션 받기를 잘못 잠근다.
    identity_gated: bool
    # 인증 회원(과 게이트가 꺼진 동안 모든 회원)의 하루 무료 대화 수. 화면 문구가 숫자 사본을 갖지 않게 서버 상수를 싣는다.
    daily_free_chat_turns: int
    # 구매로 받은 클로버의 남은 양(`/me/clover` 의 `paidBalance` 와 같은 함수). 재동의 게이트 밖인 이 응답에 둬야 재동의
    # 모달 안의 탈퇴 확인도 환불 경고를 띄울 수 있다(`/me/clover` 는 재동의 전까지 403 이다).
    paid_clover_balance: int
    # 지금 클로버를 살 수 없는 이유(살 수 있으면 null). 주문 생성과 같은 판정 함수라, 허브가 구매 다이얼로그를 열기 전에
    # 나이 제한을 알린다. 결제 스위치는 여기 없다(가격 응답의 `paymentsEnabled`).
    purchase_block_reason: PurchaseBlockReason | None
