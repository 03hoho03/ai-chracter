import uuid
from datetime import date

from pydantic import EmailStr, Field, field_validator

from api.core.schema import CamelModel


class SignupRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: str = Field(min_length=1)
    birth_date: date
    terms_agreed: bool
    privacy_agreed: bool

    @field_validator("terms_agreed", "privacy_agreed")
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
    is_minor_guardian_required: bool


class ResendVerificationCodeRequest(CamelModel):
    email: EmailStr


class GuardianConsentRequest(CamelModel):
    email: EmailStr
    guardian_name: str = Field(min_length=1)
    guardian_contact: str = Field(min_length=1)
    consent_agreed: bool

    @field_validator("consent_agreed")
    @classmethod
    def _must_be_agreed(cls, value: bool) -> bool:
        if not value:
            raise ValueError("법정대리인 동의가 필요합니다.")
        return value


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class MeResponse(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str
    bio: str | None
    profile_image_asset_id: uuid.UUID | None
