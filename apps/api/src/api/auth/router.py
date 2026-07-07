from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.age import is_guardian_consent_required
from api.auth.emails import send_verification_code_email
from api.auth.schemas import (
    GuardianConsentRequest,
    ResendVerificationCodeRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from api.auth.verification import (
    delete_verification_code,
    generate_code,
    get_verification_code,
    seconds_until_resend_allowed,
    store_verification_code,
)
from api.core.config import settings
from api.core.security import hash_password
from api.db.models.auth import GuardianConsent, User
from api.db.session import get_db_session
from api.session.cookies import set_session_cookie
from api.session.store import create_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest, db: AsyncSession = Depends(get_db_session)
) -> SignupResponse:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    now = datetime.now(UTC)
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname,
        birth_date=payload.birth_date,
        terms_agreed_at=now,
        privacy_agreed_at=now,
    )
    db.add(user)
    await db.commit()

    code = generate_code()
    await store_verification_code(payload.email, code, now)
    send_verification_code_email(payload.email, code)

    return SignupResponse(email=payload.email)


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db_session)
) -> VerifyEmailResponse:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    stored = await get_verification_code(payload.email)
    if stored is None or stored["code"] != payload.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code"
        )

    user.email_verified_at = datetime.now(UTC)
    await db.commit()
    await delete_verification_code(payload.email)

    return VerifyEmailResponse(
        is_minor_guardian_required=is_guardian_consent_required(user.birth_date, datetime.now(UTC).date())
    )


@router.post("/resend-verification-code", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification_code(
    payload: ResendVerificationCodeRequest, db: AsyncSession = Depends(get_db_session)
) -> None:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    now = datetime.now(UTC)
    stored = await get_verification_code(payload.email)
    if stored is not None:
        sent_at = datetime.fromisoformat(stored["sent_at"])
        retry_after = seconds_until_resend_allowed(
            sent_at, now, settings.email_verification_resend_cooldown_seconds
        )
        if retry_after > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"retryAfterSeconds": retry_after},
            )

    code = generate_code()
    await store_verification_code(payload.email, code, now)
    send_verification_code_email(payload.email, code)
    return None


@router.post("/guardian-consent", status_code=status.HTTP_204_NO_CONTENT)
async def guardian_consent(
    payload: GuardianConsentRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email verification required"
        )

    if not is_guardian_consent_required(user.birth_date, datetime.now(UTC).date()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Guardian consent is not required for this account",
        )

    consent = GuardianConsent(
        user_id=user.id,
        guardian_name=payload.guardian_name,
        guardian_contact=payload.guardian_contact,
        consent_agreed_at=datetime.now(UTC),
        ip_address=request.client.host if request.client else None,
    )
    db.add(consent)
    await db.commit()

    session_id = await create_session({"user_id": str(user.id)})
    set_session_cookie(response, session_id)
    return None
