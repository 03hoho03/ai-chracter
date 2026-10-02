import uuid
from datetime import UTC, date, datetime

from pydantic import EmailStr, Field, field_validator

from api.auth.age import is_under_minimum_age
from api.auth.oauth_common import OAuthProvider
from api.core.schema import CamelModel


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
