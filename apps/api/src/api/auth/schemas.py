import uuid
from datetime import UTC, date, datetime

from pydantic import EmailStr, Field, field_validator

from api.auth.age import is_under_minimum_age
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


class OnboardingGoogleRequest(CamelModel):
    token: str
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


class OnboardingGoogleResponse(CamelModel):
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
