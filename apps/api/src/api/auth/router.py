import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.router import collect_asset_usages
from api.auth.age import is_under_minimum_age
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
    VERIFICATION_ATTEMPTS_LIMIT,
    clear_verification_attempts,
    delete_verification_code,
    generate_code,
    get_verification_code,
    increment_verification_attempts,
    seconds_until_resend_allowed,
    store_verification_code,
)
from api.core import rate_limit
from api.core.config import settings
from api.core.constants import WITHDRAWN_EMAIL_BLOCK_PERIOD
from api.core.email import EmailSender, get_email_sender
from api.core.s3 import build_thumbnail_key, delete_object
from api.core.security import hash_password, hash_withdrawn_email, verify_password
from api.db.models.auth import User, WithdrawnEmail
from api.db.models.chat import ChatMessage, ChatRoom, ChatRoomStat
from api.db.models.content import Content, ContentVisibility
from api.db.models.inquiry import Inquiry
from api.db.models.media import Asset, AssetKind, ImageGenerationRequest
from api.db.session import get_db_session
from api.legal.dependencies import _latest_published_legal_version, _reconsent_required
from api.session.cookies import clear_session_cookie, get_session_id_from_request, set_session_cookie
from api.session.dependencies import get_current_user_id
from api.session.store import create_session, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


async def _reregistration_blocked(db: AsyncSession, email: str, now: datetime) -> bool:
    withdrawn = await db.scalar(
        select(WithdrawnEmail).where(WithdrawnEmail.email_hmac == hash_withdrawn_email(email))
    )
    return withdrawn is not None and now - withdrawn.withdrawn_at < WITHDRAWN_EMAIL_BLOCK_PERIOD


def _auth_too_many_requests(retry_after: int, *, code: str) -> HTTPException:
    # error-delivery-goal-prompt.md ED-12: rate_limit_gate.py의 _too_many_requests를 재사용하지
    # 않는다 — 그 함수는 user_id를 필수로 받아 로그에 찍는데, 이 파일의 세 엔드포인트는 인증 전이라
    # user_id가 없고 키가 email/IP다. 이메일을 로그에 싣는 것은 RL-12가 금지한다.
    # ED-14: Retry-After 헤더는 여기도 주지 않는다 — RL-11과 같은 이유(CORS가 노출하지 않는
    # 헤더라 크로스오리진에서 못 읽는다). auth도 ddona.site→api.ddona.site로 크로스오리진이라
    # 같은 판단이 적용된다.
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": code, "retryAfterSeconds": retry_after, "window": "auth"},
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    email_sender: EmailSender = Depends(get_email_sender),
) -> SignupResponse:
    # email-goal-prompt.md E-6: 카운터는 DB 조회보다 먼저, 무조건 올린다. IP·이메일 둘 다 매
    # 요청마다 증가해야(성공/실패와 무관하게) 한쪽이 이미 상한을 넘겨도 다른 쪽 카운트가 누락되지 않는다.
    client_ip = request.client.host if request.client else "unknown"
    ip_retry_after = await rate_limit.check_rate_limit(
        "signup_ip", client_ip, rate_limit.SIGNUP_IP_LIMIT
    )
    email_retry_after = await rate_limit.check_rate_limit(
        "signup_email", payload.email, rate_limit.SIGNUP_EMAIL_LIMIT
    )
    retry_after = ip_retry_after or email_retry_after
    if retry_after > 0:
        raise _auth_too_many_requests(retry_after, code="AUTH_LIMIT")

    existing = await db.scalar(select(User).where(User.email == payload.email))
    now = datetime.now(UTC)

    # legal-revision-goal-prompt.md LR-7: 탈퇴 시 users.email이 자리표시자로 바뀌므로(LR-6)
    # 위 existing 조회는 탈퇴 행을 더 이상 찾지 못한다 — 재가입 차단은 이 HMAC 조회로 옮긴다.
    if await _reregistration_blocked(db, payload.email, now):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if existing is not None:
        # email-goal-prompt.md E-5: 인증 완료 또는 구글 연동이 있으면 "방치된 미인증 가입"이
        # 아니라 실사용 중인 계정이므로 409로 막는다(google_callback이 email_verified_at을
        # 보지 않고 세션을 발급해 미인증인 채 실사용 중인 계정이 있을 수 있다 —
        # tests/test_auth_google_api.py:196-224). 정지도 마찬가지로 보호 대상이다.
        if (
            existing.email_verified_at is not None
            or existing.google_sub is not None
            or existing.suspended_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )

        # 순수하게 방치된 비밀번호 가입 — 기존 row를 덮어쓴다. id/created_at/google_sub 등은
        # 보존해야 하므로 새 User(...)로 교체하지 않고 기존 인스턴스의 속성만 바꾼다.
        existing.password_hash = hash_password(payload.password)
        existing.nickname = payload.nickname
        existing.birth_date = payload.birth_date
        existing.terms_agreed_at = now
        existing.privacy_agreed_at = now
        existing.transfer_agreed_at = now
        existing.terms_version = await _latest_published_legal_version(db, "terms")
        privacy_version = await _latest_published_legal_version(db, "privacy")
        existing.privacy_version = privacy_version
        # legal-revision-goal-prompt.md LR-3: 국외이전 동의는 처리방침 버전에 묶인다.
        existing.transfer_version = privacy_version
        await db.commit()
    else:
        privacy_version = await _latest_published_legal_version(db, "privacy")
        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            nickname=payload.nickname,
            birth_date=payload.birth_date,
            terms_agreed_at=now,
            privacy_agreed_at=now,
            transfer_agreed_at=now,
            terms_version=await _latest_published_legal_version(db, "terms"),
            privacy_version=privacy_version,
            # legal-revision-goal-prompt.md LR-3: 국외이전 동의는 처리방침 버전에 묶인다.
            transfer_version=privacy_version,
        )
        try:
            async with db.begin_nested():
                db.add(user)
                await db.flush()
        except IntegrityError:
            # email-goal-prompt.md E-11: select와 이 insert 사이의 경합에서 진 요청.
            # admin/legal.py의 SAVEPOINT 패턴과 같은 이유로 db.rollback()은 쓰지 않는다 —
            # begin_nested()의 컨텍스트 매니저가 SAVEPOINT까지만 되감아 세션을 정리한다.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            ) from None
        await db.commit()

    code = generate_code()
    await store_verification_code(payload.email, code, now)
    background_tasks.add_task(send_verification_code_email, email_sender, payload.email, code)

    return SignupResponse(email=payload.email)


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db_session)
) -> VerifyEmailResponse:
    # email-goal-prompt.md E-12: 계정 존재 여부를 새지 않도록 "유저 없음"도 오답 코드와 완전히
    # 같은 400을 낸다. 응답뿐 아니라 **Redis 왕복 횟수까지 같아야** 타이밍으로도 안 샌다 —
    # 그래서 user 존재 여부와 무관하게 get_verification_code/increment_verification_attempts를
    # 항상 실행한 뒤 한 조건문에서 같이 판정한다.
    user = await db.scalar(select(User).where(User.email == payload.email))
    stored = await get_verification_code(payload.email)
    if user is None or stored is None or stored["code"] != payload.code:
        # email-goal-prompt.md E-7: 오답마다 증가, 상한에 닿으면 코드를 삭제해 무효화한다.
        # 별도 잠금 상태는 만들지 않는다 — 재전송이 곧 복구다.
        attempts = await increment_verification_attempts(payload.email)
        if attempts >= VERIFICATION_ATTEMPTS_LIMIT:
            await delete_verification_code(payload.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code"
        )

    user.email_verified_at = datetime.now(UTC)
    await db.commit()
    await delete_verification_code(payload.email)
    await clear_verification_attempts(payload.email)

    return VerifyEmailResponse()


@router.post("/resend-verification-code", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification_code(
    payload: ResendVerificationCodeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    email_sender: EmailSender = Depends(get_email_sender),
) -> None:
    # email-goal-prompt.md E-6: 시간당 상한을 60초 쿨다운보다 먼저 검사한다 — 카운터 증분이
    # 핸들러 최상단, DB 조회보다 앞에 있어야 하므로 자연스럽게 이 순서가 된다. 둘 다 429지만
    # retryAfterSeconds가 다르다: 상한을 넘긴 사용자는 (대개 더 긴) 창 잔여 시간을 보고,
    # 그 아래에서는 기존 60초 쿨다운이 그대로 동작한다.
    retry_after = await rate_limit.check_rate_limit(
        "resend_verification_code_email", payload.email, rate_limit.RESEND_VERIFICATION_EMAIL_LIMIT
    )
    if retry_after > 0:
        raise _auth_too_many_requests(retry_after, code="AUTH_LIMIT")

    # email-goal-prompt.md E-12a: 쿨다운 검사를 유저 조회보다 먼저 한다. 코드는 아래에서
    # 등록 여부와 무관하게 항상 저장되므로, 유저 조회를 먼저 하면 미등록 이메일은 쿨다운
    # 429를 낼 코드가 없어 등록 이메일과 다른 응답이 나온다(존재 여부 누설).
    now = datetime.now(UTC)
    stored = await get_verification_code(payload.email)
    if stored is not None:
        sent_at = datetime.fromisoformat(stored["sent_at"])
        retry_after = seconds_until_resend_allowed(
            sent_at, now, settings.email_verification_resend_cooldown_seconds
        )
        if retry_after > 0:
            raise _auth_too_many_requests(retry_after, code="AUTH_COOLDOWN")

    user = await db.scalar(select(User).where(User.email == payload.email))

    code = generate_code()
    await store_verification_code(payload.email, code, now)
    if user is not None:
        background_tasks.add_task(send_verification_code_email, email_sender, payload.email, code)
    return None


@router.get("/google")
async def google_login(redirect: str = "/") -> RedirectResponse:
    state = await store_oauth_state(redirect)
    return RedirectResponse(build_authorization_url(state), status_code=status.HTTP_302_FOUND)


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

    if user is None:
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

    # legal-revision-goal-prompt.md LR-30(2026-09-15 정정판): login()과 같은 게이트를 여기에도
    # 둔다 — google_sub 직접 매치와 이메일 매칭으로 google_sub를 붙이는 두 분기가 모두 여기로
    # 수렴하므로 한 곳만 막으면 둘 다 막힌다. 위 조건문이 deleted_at is not None인 계정을
    # 이미 배제했다 — birth_date는 탈퇴(S5 파기) 시에만 None이 된다. 집계에서 0건 확인되면
    # 이 블록을 걷어낼 것(login()의 동일 게이트와 짝).
    assert user.birth_date is not None
    if is_under_minimum_age(user.birth_date, datetime.now(UTC).date()):
        return RedirectResponse(
            f"{settings.frontend_base_url}/login?error=account_age_restricted",
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
        # legal-revision-goal-prompt.md LR-7·LR-18: 탈퇴 시 google_sub도 파기되므로(LR-18)
        # 재가입 시도는 위 google_sub 매치가 아니라 항상 이 신규 유저 생성 분기를 타게 된다.
        if await _reregistration_blocked(db, pending["email"], now):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )
        privacy_version = await _latest_published_legal_version(db, "privacy")
        user = User(
            email=pending["email"],
            google_sub=pending["sub"],
            nickname=payload.nickname,
            birth_date=payload.birth_date,
            terms_agreed_at=now,
            privacy_agreed_at=now,
            transfer_agreed_at=now,
            email_verified_at=now,
            terms_version=await _latest_published_legal_version(db, "terms"),
            privacy_version=privacy_version,
            # legal-revision-goal-prompt.md LR-3: 국외이전 동의는 처리방침 버전에 묶인다.
            transfer_version=privacy_version,
        )
        db.add(user)
    else:
        user.nickname = payload.nickname
        user.birth_date = payload.birth_date
    await db.commit()
    await delete_pending_google_signup(payload.token)

    if user.suspended_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    session_id = await create_session({"user_id": str(user.id)})
    set_session_cookie(response, session_id)
    return OnboardingGoogleResponse(email=user.email)


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

    # 위 조건문이 deleted_at is not None인 계정을 이미 배제했다 — birth_date는 탈퇴(S5 파기)
    # 시에만 None이 된다.
    assert user.birth_date is not None
    # legal-revision-goal-prompt.md LR-30: LR-9가 신규 가입을 막으므로 이 분기는 시행일
    # 이전에 가입한 기존 미성년 계정만 겨냥한다. 법정대리인 동의 여부와 무관하게 연령만
    # 본다 — 프로덕션 집계를 받지 못해 안전한 쪽(로그인 차단)을 택했다. 집계가 0건으로
    # 확인되면 이 블록을 걷어낼 것.
    if is_under_minimum_age(user.birth_date, datetime.now(UTC).date()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Minimum age not met"
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
    payload: PasswordResetRequestRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    email_sender: EmailSender = Depends(get_email_sender),
) -> None:
    # email-goal-prompt.md E-6: 카운터를 계정 존재 여부와 무관하게, DB 조회보다 먼저 올린다 —
    # 안 그러면 등록된 이메일에서만 429가 나서 아래의 204 고정 응답이 지키려는 은닉이 429로 깨진다.
    client_ip = request.client.host if request.client else "unknown"
    ip_retry_after = await rate_limit.check_rate_limit(
        "password_reset_ip", client_ip, rate_limit.PASSWORD_RESET_IP_LIMIT
    )
    email_retry_after = await rate_limit.check_rate_limit(
        "password_reset_email", payload.email, rate_limit.PASSWORD_RESET_EMAIL_LIMIT
    )
    retry_after = ip_retry_after or email_retry_after
    if retry_after > 0:
        raise _auth_too_many_requests(retry_after, code="AUTH_LIMIT")

    # Same 204 response whether or not the email is registered, so the caller
    # can't use this endpoint to probe which emails have an account.
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is not None:
        token = await store_reset_token(user.id)
        reset_link = f"{settings.frontend_base_url}/reset-password?token={token}"
        background_tasks.add_task(send_password_reset_email, email_sender, payload.email, reset_link)
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

    # 위 조건문이 deleted_at is not None인 계정을 이미 배제했다 — nickname은 탈퇴(S5 파기)
    # 시에만 None이 된다.
    assert user.nickname is not None
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

    now = datetime.now(UTC)
    original_email = user.email

    # legal-revision-goal-prompt.md LR-19: 프로필 이미지 R2 오브젝트를 지운다 —
    # core/s3.py의 delete_object·assets/router.py의 호출 선례(:116,133,382)를 따른다.
    if user.profile_image_asset_id is not None:
        asset = await db.get(Asset, user.profile_image_asset_id)
        if asset is not None:
            await run_in_threadpool(delete_object, asset.storage_key)
            # assets/router.py:124의 불변식 — READY 이미지 asset은 항상
            # `{key}_thumb.webp` 변형을 갖는다. 프로필 이미지도 그 공용 업로드
            # 경로(assets/router.py의 complete_asset_upload)를 타므로 원본만
            # 지우면 썸네일이 R2에 고아로 남는다.
            await run_in_threadpool(delete_object, build_thumbnail_key(asset.storage_key))

    user.deleted_at = now
    # legal-revision-goal-prompt.md LR-6: users.email이 unique=True, nullable=False라
    # NULL을 못 쓴다 — 복원 불가능한 자리표시자로 유일성을 유지한다.
    user.email = f"withdrawn:{user_id}"
    user.password_hash = None
    user.nickname = None
    user.bio = None
    user.birth_date = None
    # legal-revision-goal-prompt.md LR-18: 파기하지 않으면 구글 가입자는 google_sub 직접
    # 매치(google_callback)에 영구히 걸려, 이메일 가입자와 달리 1년이 지나도 재가입이 안 열린다.
    user.google_sub = None
    user.profile_image_asset_id = None

    # legal-revision-goal-prompt.md LR-7·LR-8: 평문 이메일 대신 키 있는 HMAC 한 행을 남긴다.
    # 같은 이메일이 만료 후 재사용됐다가 다시 탈퇴할 수 있어 PK 충돌이면 갱신한다.
    email_hmac = hash_withdrawn_email(original_email)
    withdrawn_row = await db.scalar(
        select(WithdrawnEmail).where(WithdrawnEmail.email_hmac == email_hmac)
    )
    if withdrawn_row is not None:
        withdrawn_row.withdrawn_at = now
    else:
        db.add(WithdrawnEmail(email_hmac=email_hmac, withdrawn_at=now))

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

    # T-4 적대적 리뷰: `profile_image_asset_id = None` 대입(위 574줄)이 DB에 반영된
    # 뒤라야 아래 `DELETE FROM assets`가 FK 위반을 내지 않는다. autoflush에 기대지 않는다.
    await db.flush()

    # image-monitoring-goal-prompt.md IM-7: 탈퇴한 유저의 GENERATED asset과 요청 행을
    # "이미지와 같은 수명"으로 파기한다. profile_image_asset_id는 위에서 이미 None으로
    # 끊었으므로(LR-19 블록) 여기서 지워도 프로필 FK가 안전하다.
    generated_assets = (
        await db.scalars(
            select(Asset).where(Asset.owner_user_id == user_id, Asset.kind == AssetKind.GENERATED)
        )
    ).all()
    if generated_assets:
        asset_ids = [asset.id for asset in generated_assets]
        usages_by_asset = await collect_asset_usages(db, asset_ids)
        # collect_asset_usages는 캐릭터/스토리 썸네일과 상황별 이미지만 본다 —
        # 문의 첨부(inquiries.attachment_asset_id)는 보지 않는다. 문의는 소유자만
        # 검사하고 kind를 안 보며(inquiry/router.py) 탈퇴해도 삭제되지 않으므로,
        # 제외하지 않으면 FK 위반으로 탈퇴 전체가 500으로 죽는다.
        inquiry_asset_ids = set(
            (
                await db.scalars(
                    select(Inquiry.attachment_asset_id).where(
                        Inquiry.attachment_asset_id.in_(asset_ids)
                    )
                )
            ).all()
        )

        deletable_assets = [
            asset
            for asset in generated_assets
            if not usages_by_asset.get(asset.id) and asset.id not in inquiry_asset_ids
        ]
        deletable_ids = {asset.id for asset in deletable_assets}
        for asset in deletable_assets:
            # S3를 먼저 지운다 — 실패하면 DB 행이 남아 재시도가 가능하다
            # (assets/router.py의 delete_generated_image와 같은 이유).
            await run_in_threadpool(delete_object, asset.storage_key)
            await run_in_threadpool(delete_object, build_thumbnail_key(asset.storage_key))
            await db.delete(asset)

        # 요청 행은 asset이 하나도 안 남은 것만 지운다. 남은 asset을 가진 요청 행과,
        # 애초에 asset이 없던 요청 행(차단·실패 — IM-7a의 몫)은 남긴다. 이 유저의
        # GENERATED asset을 전부 조회했으므로(generated_assets), 다른 유저의 asset이
        # 같은 요청 행을 참조할 수 없어(요청 행과 asset은 항상 같은 소유자) 이 목록만으로
        # "남은 asset이 있는가"를 판단할 수 있다.
        surviving_request_ids = {
            asset.request_id
            for asset in generated_assets
            if asset.id not in deletable_ids and asset.request_id is not None
        }
        emptied_request_ids = {
            asset.request_id for asset in deletable_assets if asset.request_id is not None
        } - surviving_request_ids
        if emptied_request_ids:
            # assets.request_id FK 때문에 asset을 먼저 지우고 요청 행을 지워야 한다 —
            # flush로 위 db.delete(asset)들을 먼저 반영한다.
            await db.flush()
            await db.execute(
                delete(ImageGenerationRequest).where(
                    ImageGenerationRequest.id.in_(emptied_request_ids)
                )
            )

    await db.commit()

    session_id = get_session_id_from_request(request)
    if session_id is not None:
        await delete_session(session_id)
    clear_session_cookie(response)
    return None
