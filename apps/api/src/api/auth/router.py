import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.age import is_guardian_consent_required
from api.auth.emails import send_password_reset_email, send_verification_code_email
from api.auth.google_oauth import (
    GoogleProfile,
    build_authorization_url,
    consume_oauth_state,
    delete_pending_google_signup,
    get_google_profile,
    get_pending_google_signup,
    store_oauth_state,
    store_pending_google_signup,
)
from api.auth.password_reset import delete_reset_token, get_reset_token, store_reset_token
from api.auth.schemas import (
    GuardianConsentRequest,
    LoginRequest,
    MeResponse,
    OnboardingGoogleRequest,
    OnboardingGoogleResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestRequest,
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
from api.core.security import hash_password, verify_password
from api.db.models.auth import GuardianConsent, User
from api.db.session import get_db_session
from api.session.cookies import clear_session_cookie, get_session_id_from_request, set_session_cookie
from api.session.dependencies import get_current_user_id
from api.session.store import create_session, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


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


@router.get("/google")
async def google_login(redirect: str = "/") -> RedirectResponse:
    state = await store_oauth_state(redirect)
    return RedirectResponse(build_authorization_url(state), status_code=status.HTTP_302_FOUND)


async def _guardian_consent_missing(db: AsyncSession, user: User) -> bool:
    if not is_guardian_consent_required(user.birth_date, datetime.now(UTC).date()):
        return False
    consent = await db.scalar(select(GuardianConsent).where(GuardianConsent.user_id == user.id))
    return consent is None


async def _get_oauth_redirect_target(state: str) -> str:
    """A separate dependency (resolved before `get_google_profile` below, in
    signature order) so a forged/expired `state` is rejected before we spend a
    real network round-trip exchanging `code` with Google."""
    redirect_target = await consume_oauth_state(state)
    if redirect_target is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired state")
    return redirect_target


@router.get("/google/callback")
async def google_callback(
    redirect_target: str = Depends(_get_oauth_redirect_target),
    profile: GoogleProfile = Depends(get_google_profile),
    db: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    user = await db.scalar(select(User).where(User.google_sub == profile["sub"]))
    if user is None:
        # Same email already registered via the password flow: link this Google
        # account to it instead of failing on the users.email unique constraint.
        user = await db.scalar(select(User).where(User.email == profile["email"]))
        if user is not None and user.google_sub is None:
            user.google_sub = profile["sub"]
            await db.commit()

    if user is None or await _guardian_consent_missing(db, user):
        token = await store_pending_google_signup(profile)
        return RedirectResponse(
            f"{settings.frontend_base_url}/onboarding/google?token={token}",
            status_code=status.HTTP_302_FOUND,
        )

    session_id = await create_session({"user_id": str(user.id)})
    response = RedirectResponse(
        f"{settings.frontend_base_url}{redirect_target}", status_code=status.HTTP_302_FOUND
    )
    set_session_cookie(response, session_id)
    return response


@router.post("/onboarding/google")
async def onboarding_google(
    payload: OnboardingGoogleRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> OnboardingGoogleResponse:
    pending = await get_pending_google_signup(payload.token)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    now = datetime.now(UTC)
    user = await db.scalar(select(User).where(User.google_sub == pending["sub"]))
    if user is None:
        user = User(
            email=pending["email"],
            google_sub=pending["sub"],
            nickname=payload.nickname,
            birth_date=payload.birth_date,
            terms_agreed_at=now,
            privacy_agreed_at=now,
            email_verified_at=now,
        )
        db.add(user)
    else:
        user.nickname = payload.nickname
        user.birth_date = payload.birth_date
    await db.commit()
    await delete_pending_google_signup(payload.token)

    if is_guardian_consent_required(user.birth_date, now.date()):
        return OnboardingGoogleResponse(is_minor_guardian_required=True)

    session_id = await create_session({"user_id": str(user.id)})
    set_session_cookie(response, session_id)
    return OnboardingGoogleResponse(is_minor_guardian_required=False)


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if (
        user is None
        or user.password_hash is None
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    if user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Email verification required"
        )

    if is_guardian_consent_required(user.birth_date, datetime.now(UTC).date()):
        consent = await db.scalar(select(GuardianConsent).where(GuardianConsent.user_id == user.id))
        if consent is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Guardian consent required"
            )

    session_id = await create_session({"user_id": str(user.id)})
    set_session_cookie(response, session_id)
    return None


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    session_id = get_session_id_from_request(request)
    if session_id is not None:
        await delete_session(session_id)
    clear_session_cookie(response)
    return None


@router.post("/password-reset/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    payload: PasswordResetRequestRequest, db: AsyncSession = Depends(get_db_session)
) -> None:
    # Same 204 response whether or not the email is registered, so the caller
    # can't use this endpoint to probe which emails have an account.
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is not None:
        token = await store_reset_token(user.id)
        reset_link = f"{settings.frontend_base_url}/reset-password?token={token}"
        send_password_reset_email(payload.email, reset_link)
    return None


@router.get("/password-reset/validate")
async def validate_password_reset_token(token: str) -> None:
    stored = await get_reset_token(token)
    if stored is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    return None


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest, db: AsyncSession = Depends(get_db_session)
) -> None:
    stored = await get_reset_token(payload.token)
    if stored is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    user = await db.get(User, uuid.UUID(stored["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    # Invalidate immediately so the token can't be replayed.
    await delete_reset_token(payload.token)
    return None


@me_router.get("/me")
async def get_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> MeResponse:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    return MeResponse(
        id=user.id,
        email=user.email,
        nickname=user.nickname,
        bio=user.bio,
        profile_image_asset_id=user.profile_image_asset_id,
    )
