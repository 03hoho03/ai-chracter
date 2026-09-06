import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select, update
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
    ChangePasswordRequest,
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
from api.db.models.chat import ChatMessage, ChatRoom, ChatRoomStat
from api.db.models.content import Content, ContentVisibility
from api.db.models.legal import LegalDocument
from api.db.session import get_db_session
from api.session.cookies import clear_session_cookie, get_session_id_from_request, set_session_cookie
from api.session.dependencies import get_current_user_id
from api.session.store import create_session, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


async def _latest_published_legal_version(
    db: AsyncSession, kind: str, *, requires_reconsent: bool | None = None
) -> str | None:
    """kind별 최신 게시본의 version. `requires_reconsent`를 주면 그 값으로 게시된 것만
    보고(`GET /me` 재동의 판정용), 안 주면 전체 게시본 중 최신(가입 시점 기록용)."""
    filters = [LegalDocument.kind == kind, LegalDocument.status == "published"]
    if requires_reconsent is not None:
        filters.append(LegalDocument.requires_reconsent.is_(requires_reconsent))
    document = await db.scalar(
        select(LegalDocument).where(*filters).order_by(LegalDocument.published_at.desc()).limit(1)
    )
    return document.version if document is not None else None


def _reconsent_required(current_version: str | None, required_version: str | None) -> bool:
    """`required_version`이 없으면(=`requires_reconsent=true`로 게시된 문서가 아직
    없으면) 재동의가 필요할 수 없다. 있으면 유저가 그 버전 이상으로 동의했는지 본다.

    **`version`이 zero-padded ISO 날짜 문자열이라 문자열 비교가 시간순과 일치한다는
    전제 위에 이 판정 전체가 서 있다** — 다른 포맷의 버전을 쓰면 이 비교가 깨진다.
    그 전제는 서버가 강제한다: `AdminLegalPublishRequest.version`(`api/admin/schemas.py`)의
    `pattern=r"^\d{4}-\d{2}-\d{2}$"`가 이 포맷이 아닌 버전의 게시 자체를 422로 막는다.
    """
    if required_version is None:
        return False
    return current_version is None or current_version < required_version


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
        terms_version=await _latest_published_legal_version(db, "terms"),
        privacy_version=await _latest_published_legal_version(db, "privacy"),
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

    if user.suspended_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

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
        # state는 1회용이라(consume_oauth_state 가 읽는 즉시 삭제) 위조뿐 아니라 정상 사용자도
        # 여기 도달한다 — 온보딩 화면에서 뒤로가기 후 계정 재선택, 콜백 URL 새로고침, TTL 만료.
        # 이때 400 JSON을 그대로 내면 브라우저에 날것의 본문이 렌더링되어 빠져나갈 수 없으므로,
        # 로그인 화면으로 되돌려 재시도할 수 있게 한다(state 1회성 자체는 그대로 유지).
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            detail="Invalid or expired state",
            headers={"Location": f"{settings.frontend_base_url}/login?error=google_state"},
        )
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

    # 탈퇴(deleted_at)한 계정은 비밀번호 로그인(US-024)부터 막혀 있었지만 구글 로그인은
    # 이 확인이 없던 기존 갭이었다 — 정지 확인을 넣는 김에 같이 메운다. 비밀번호 로그인과
    # 달리 탈퇴 여부를 숨기지 않는다: 여긴 실제 자격증명(비밀번호) 추측 공격 표면이 없다
    # (호출자가 이미 그 구글 계정을 실제로 소유하고 있어야 여기 도달한다).
    if user.deleted_at is not None or user.suspended_at is not None:
        error_code = "account_deleted" if user.deleted_at is not None else "account_suspended"
        return RedirectResponse(
            f"{settings.frontend_base_url}/login?error={error_code}",
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
            terms_version=await _latest_published_legal_version(db, "terms"),
            privacy_version=await _latest_published_legal_version(db, "privacy"),
        )
        db.add(user)
    else:
        user.nickname = payload.nickname
        user.birth_date = payload.birth_date
    await db.commit()
    await delete_pending_google_signup(payload.token)

    if is_guardian_consent_required(user.birth_date, now.date()):
        return OnboardingGoogleResponse(is_minor_guardian_required=True, email=user.email)

    if user.suspended_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    session_id = await create_session({"user_id": str(user.id)})
    set_session_cookie(response, session_id)
    return OnboardingGoogleResponse(is_minor_guardian_required=False, email=user.email)


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
        or user.deleted_at is not None
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

    if user.suspended_at is not None:
        # deleted_at과 달리 숨기지 않는다 — 탈퇴는 "이메일 또는 비밀번호가 올바르지 않음"에
        # 묻어 탈퇴 사실 자체를 노출하지 않지만, 정지는 사용자가 알아야 이의를 제기할 수
        # 있다(techspec §2가 정지를 "요청 차단"으로 설계한 것과 짝을 이루는 판단 — 세션이
        # 살아있는 채 막히는 것과 로그인 시도가 막히는 것이 같은 메시지를 줘야 일관적이다).
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

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

    required_terms_version = await _latest_published_legal_version(db, "terms", requires_reconsent=True)
    required_privacy_version = await _latest_published_legal_version(
        db, "privacy", requires_reconsent=True
    )

    return MeResponse(
        id=user.id,
        email=user.email,
        nickname=user.nickname,
        bio=user.bio,
        profile_image_asset_id=user.profile_image_asset_id,
        terms_reconsent_required=_reconsent_required(user.terms_version, required_terms_version),
        privacy_reconsent_required=_reconsent_required(user.privacy_version, required_privacy_version),
    )


@me_router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if user.password_hash is None or not verify_password(
        payload.current_password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )

    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    return None


@me_router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw(
    request: Request,
    response: Response,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user.deleted_at = datetime.now(UTC)

    await db.execute(
        update(Content)
        .where(Content.creator_user_id == user_id)
        .values(visibility=ContentVisibility.PRIVATE)
    )

    room_ids = (await db.scalars(select(ChatRoom.id).where(ChatRoom.user_id == user_id))).all()
    if room_ids:
        await db.execute(delete(ChatRoomStat).where(ChatRoomStat.chat_room_id.in_(room_ids)))
        await db.execute(delete(ChatMessage).where(ChatMessage.chat_room_id.in_(room_ids)))
        await db.execute(delete(ChatRoom).where(ChatRoom.id.in_(room_ids)))

    await db.commit()

    session_id = get_session_id_from_request(request)
    if session_id is not None:
        await delete_session(session_id)
    clear_session_cookie(response)
    return None
