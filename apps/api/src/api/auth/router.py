import json
import logging
import secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import kakao_oauth
from api.auth.age import is_under_minimum_age
from api.comments.access import lock_active_user
from api.auth.emails import send_password_reset_email, send_verification_code_email
from api.auth.google_oauth import (
    GoogleProfileFetcher,
    build_authorization_url,
    consume_oauth_state,
    delete_pending_google_signup,
    get_google_profile_fetcher,
    get_pending_google_signup,
    store_oauth_state,
    store_pending_google_signup,
)
from api.auth.kakao_oauth import (
    KakaoProfileFetcher,
    KakaoUnlinker,
    get_kakao_profile_fetcher,
    get_kakao_unlinker,
    unlink_after_withdrawal,
)
from api.auth.oauth_common import (
    OAuthExchangeError,
    OAuthProvider,
    clear_oauth_cookie,
    finish_social_login,
    oauth_callback_redirect,
    oauth_login_error_redirect,
    pending_signup_cookie_name,
    resolve_oauth_state,
    safe_redirect_path,
    set_oauth_cookie,
    signup_method,
    state_cookie_name,
)
from api.auth.password_reset import delete_reset_token, get_reset_token, store_reset_token
from api.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestRequest,
    ResendVerificationCodeRequest,
    SignupRequest,
    SignupResponse,
    SocialOnboardingRequest,
    SocialOnboardingResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from api.auth.withdrawal import delete_storage_object_now, delete_storage_objects_later, erase_account
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
from api.core.security import hash_password, hash_withdrawn_email, verify_password
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User, WithdrawnEmail
from api.db.session import get_db_session
from api.legal.dependencies import _latest_published_legal_version, _reconsent_required
from api.session.cookies import clear_session_cookie, get_session_id_from_request, set_session_cookie
from api.session.dependencies import get_current_user_id
from api.session.store import create_session, delete_session, revoke_user_sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


async def _reregistration_blocked(db: AsyncSession, email: str, now: datetime) -> bool:
    withdrawn = await db.scalar(
        select(WithdrawnEmail).where(WithdrawnEmail.email_hmac == hash_withdrawn_email(email))
    )
    return withdrawn is not None and now - withdrawn.withdrawn_at < WITHDRAWN_EMAIL_BLOCK_PERIOD


def _is_abandoned_email_signup(user: User) -> bool:
    """이메일 인증을 마치지 않은 비밀번호 가입 행인가. 이 행은 로그인할 수 없어(로그인이 미인증을
    막는다) 실사용 계정이 아니라 방치된 기록이므로, 같은 이메일의 새 가입(이메일 가입 재시도,
    카카오 가입)이 대체할 수 있다. 인증 완료·소셜 연동·정지 중 하나라도 있으면 실사용 중이거나
    보호할 계정이다."""
    return (
        user.email_verified_at is None
        and user.google_sub is None
        and user.kakao_id is None
        and user.suspended_at is None
        and user.deleted_at is None
    )


def _onboarding_conflict(code: str) -> HTTPException:
    # 경합·이메일 중복과 재가입 차단이 같은 409 라 프런트가 안내를 가를 수 있게 원인을 `code` 로 담는다.
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code})


async def _apply_onboarding_consent(
    db: AsyncSession, user: User, payload: SocialOnboardingRequest, now: datetime
) -> None:
    """소셜 온보딩이 받은 프로필과 약관 3종 동의를 행에 적는다. 동의 버전은 지금 게시된 최신본이다.

    버전 조회가 자동 flush 를 일으키지 않게 막는다. 카카오 온보딩은 기존 행을 대체할 때 회원번호를
    이 함수 호출 전에 대입하는데, 여기서 flush 되면 그 UPDATE 가 UNIQUE 충돌을 409 로 바꾸는
    `_flush_social_signup` 의 savepoint 밖에서 나가 500 이 된다. 쓰기는 그 함수에서만 나가야 한다."""
    with db.no_autoflush:
        privacy_version = await _latest_published_legal_version(db, "privacy")
        terms_version = await _latest_published_legal_version(db, "terms")
    user.nickname = payload.nickname
    user.birth_date = payload.birth_date
    user.terms_agreed_at = now
    user.privacy_agreed_at = now
    user.transfer_agreed_at = now
    user.terms_version = terms_version
    user.privacy_version = privacy_version
    # 국외이전 동의는 처리방침 버전에 묶인다.
    user.transfer_version = privacy_version


async def _flush_social_signup(db: AsyncSession, user: User) -> None:
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        # 조회와 이 쓰기 사이의 경합에서 진 요청 — 콜백 뒤 온보딩 전에 같은 이메일로 다른 가입이
        # 먼저 커밋됐거나, 같은 가입 대기를 두 탭에서 동시에 제출했다(users.email 또는 provider
        # 식별자 UNIQUE). 어느 쪽이든 "이미 가입됨"이다. signup 과 같은 이유로 db.rollback()은
        # 쓰지 않는다 — begin_nested()가 SAVEPOINT까지만 되감는다.
        raise _onboarding_conflict("EMAIL_ALREADY_REGISTERED") from None


async def _start_onboarded_session(
    response: Response, user: User, *, provider: OAuthProvider
) -> SocialOnboardingResponse:
    session_id = await create_session(user.id)
    # 주입받은 `response` 에 걸고 모델을 반환하므로 FastAPI 가 두 쿠키를 응답에 합친다.
    set_session_cookie(response, session_id)
    clear_oauth_cookie(response, pending_signup_cookie_name(provider))
    return SocialOnboardingResponse(email=user.email)


def _auth_too_many_requests(retry_after: int, *, code: str) -> HTTPException:
    # rate_limit_gate.py의 _too_many_requests를 재사용하지
    # 않는다 — 그 함수는 user_id를 필수로 받아 로그에 찍는데, 이 파일의 세 엔드포인트는 인증 전이라
    # user_id가 없고 키가 email/IP다. 이메일은 PII라 로그에 싣지 않는다(`user_id`까지가 한계다).
    # Retry-After 헤더는 여기도 주지 않는다 — 채팅 429와 같은 이유(CORS가 노출하지 않는
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
    # 카운터는 DB 조회보다 먼저, 무조건 올린다. IP·이메일 둘 다 매
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

    # 행을 잠그고 읽는다 — 카카오 온보딩이 같은 미인증 행을 카카오 계정으로 대체하는 중이면 그
    # 커밋을 기다렸다가 바뀐 상태(인증됨)로 다시 판정한다. 잠그지 않으면 판정 뒤 덮어쓰기가 막
    # 대체된 카카오 계정에 비밀번호를 얹을 수 있다.
    existing = await db.scalar(
        select(User)
        .where(User.email == payload.email)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)

    # 탈퇴 시 users.email이 자리표시자로 바뀌므로
    # 위 existing 조회는 탈퇴 행을 더 이상 찾지 못한다 — 재가입 차단은 이 HMAC 조회로 옮긴다.
    if await _reregistration_blocked(db, payload.email, now):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if existing is not None:
        # 인증 완료 또는 구글 연동이 있으면 "방치된 미인증 가입"이
        # 아니라 실사용 중인 계정이므로 409로 막는다(google_callback이 email_verified_at을
        # 보지 않고 세션을 발급해 미인증인 채 실사용 중인 계정이 있을 수 있다 —
        # tests/test_auth_google_api.py:196-224). 정지도 마찬가지로 보호 대상이다. 카카오 계정은
        # 온보딩이 인증 시각을 함께 적어 인증 조건에 먼저 걸리지만, 인증 시각이 비어 있는 예전
        # 데이터가 있어도 덮어쓰지 않도록 식별자로도 막는다.
        if not _is_abandoned_email_signup(existing):
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
        # 국외이전 동의는 처리방침 버전에 묶인다.
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
            # 국외이전 동의는 처리방침 버전에 묶인다.
            transfer_version=privacy_version,
        )
        try:
            async with db.begin_nested():
                db.add(user)
                await db.flush()
        except IntegrityError:
            # select와 이 insert 사이의 경합에서 진 요청.
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
    # 계정 존재 여부를 새지 않도록 "유저 없음"도 오답 코드와 완전히
    # 같은 400을 낸다. 응답뿐 아니라 **Redis 왕복 횟수까지 같아야** 타이밍으로도 안 샌다 —
    # 그래서 user 존재 여부와 무관하게 get_verification_code/increment_verification_attempts를
    # 항상 실행한 뒤 한 조건문에서 같이 판정한다.
    user = await db.scalar(select(User).where(User.email == payload.email))
    stored = await get_verification_code(payload.email)
    if user is None or stored is None or stored["code"] != payload.code:
        # 오답마다 증가, 상한에 닿으면 코드를 삭제해 무효화한다.
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
    # 시간당 상한을 60초 쿨다운보다 먼저 검사한다 — 카운터 증분이
    # 핸들러 최상단, DB 조회보다 앞에 있어야 하므로 자연스럽게 이 순서가 된다. 둘 다 429지만
    # retryAfterSeconds가 다르다: 상한을 넘긴 사용자는 (대개 더 긴) 창 잔여 시간을 보고,
    # 그 아래에서는 기존 60초 쿨다운이 그대로 동작한다.
    retry_after = await rate_limit.check_rate_limit(
        "resend_verification_code_email", payload.email, rate_limit.RESEND_VERIFICATION_EMAIL_LIMIT
    )
    if retry_after > 0:
        raise _auth_too_many_requests(retry_after, code="AUTH_LIMIT")

    # 쿨다운 검사를 유저 조회보다 먼저 한다. 코드는 아래에서
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
    state = await store_oauth_state(safe_redirect_path(redirect))
    response = RedirectResponse(build_authorization_url(state), status_code=status.HTTP_302_FOUND)
    # 같은 state 를 로그인을 시작한 브라우저에도 심는다 — 콜백이 대조한다(resolve_oauth_state).
    set_oauth_cookie(
        response,
        state_cookie_name("google"),
        state,
        max_age=settings.google_oauth_state_ttl_seconds,
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    fetch_profile: GoogleProfileFetcher = Depends(get_google_profile_fetcher),
    db: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    # 어떤 결과든 JSON 400·422 대신 로그인 화면으로 302 한다 — 브라우저가 최상위 이동으로 여는
    # 주소라 날것의 오류 본문이 뜨면 사용자가 빠져나갈 수 없다. 그래서 쿼리 파라미터를 모두
    # optional 로 받고 판정은 본문에서 한다.
    #
    # state 대조를 취소 판정보다 먼저 한다. 취소 응답에도 state 가 실려 오므로, 먼저 대조하면 이
    # 브라우저가 시작한 흐름의 취소만 "취소"로 안내되고 그때 1회용 state 가 소비되고 쿠키도
    # 지워져 흐름이 깨끗이 끝난다. 취소를 먼저 보면 Redis state 와 쿠키가 TTL 까지 남는다.
    # 토큰 교환(네트워크)은 둘 다 통과한 뒤에만 부른다.
    redirect_target = await resolve_oauth_state(
        request, state, provider="google", consume=consume_oauth_state
    )
    if redirect_target is None:
        return oauth_login_error_redirect("google_state", provider="google")
    if error is not None or code is None:
        return oauth_login_error_redirect("google_cancelled", provider="google")
    try:
        profile = await fetch_profile(code)
    except OAuthExchangeError as exc:
        # 리다이렉트 응답은 Sentry 가 자동으로 잡지 않으므로(5xx 만 잡는다) 명시적으로 올린다.
        logger.warning("google oauth exchange failed: %s", exc)
        capture_dependency_failure(exc, dependency="google_oauth")
        return oauth_login_error_redirect("google_failed", provider="google")

    user = await db.scalar(select(User).where(User.google_sub == profile["sub"]))
    if user is None:
        # Same email already registered via the password flow: link this Google
        # account to it instead of failing on the users.email unique constraint.
        # 행을 잠그고 읽는다 — 카카오 온보딩이 같은 미인증 행을 카카오 계정으로 대체하는 중이면 그
        # 커밋을 기다렸다가 바뀐 상태로 다시 판정한다. 잠그지 않으면 대체 전의 행을 보고 구글을
        # 붙여 한 행이 카카오와 구글을 함께 갖게 된다.
        user = await db.scalar(
            select(User)
            .where(User.email == profile["email"])
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        # 카카오 계정에는 구글을 자동으로 붙이지 않는다 — 카카오 로그인이 구글 계정에 붙지 않는
        # 것과 대칭이다. 이메일 재활용으로 남의 계정에 들어가는 경로를 새로 열지 않는다.
        if user is not None and user.kakao_id is not None:
            return oauth_callback_redirect(
                f"{settings.frontend_base_url}/login?error=google_email_taken&method=kakao",
                provider="google",
            )
        if user is not None and user.google_sub is None:
            user.google_sub = profile["sub"]
            await db.commit()

    if user is None:
        token = await store_pending_google_signup(profile)
        # 토큰을 URL 쿼리가 아니라 HttpOnly 쿠키로 내린다 — URL 은 히스토리·리퍼러·로그로 새고,
        # 쿠키면 새더라도 이 브라우저 밖에서는 온보딩을 끝낼 수 없다.
        response = oauth_callback_redirect(
            f"{settings.frontend_base_url}/onboarding/google", provider="google"
        )
        set_oauth_cookie(
            response,
            pending_signup_cookie_name("google"),
            token,
            max_age=settings.google_pending_signup_ttl_seconds,
        )
        return response

    return await finish_social_login(user, redirect_target, provider="google")


@router.post("/onboarding/google")
async def onboarding_google(
    payload: SocialOnboardingRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> SocialOnboardingResponse:
    # 쿠키가 없을 때와 만료됐을 때를 같은 400 으로 낸다 — 프런트가 이미 이 응답을 "만료"로 다룬다.
    token = request.cookies.get(pending_signup_cookie_name("google"))
    pending = await get_pending_google_signup(token) if token is not None else None
    if token is None or pending is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    now = datetime.now(UTC)
    user = await db.scalar(select(User).where(User.google_sub == pending["sub"]))
    if user is None:
        # 탈퇴 시 google_sub도 파기되므로
        # 재가입 시도는 위 google_sub 매치가 아니라 항상 이 신규 유저 생성 분기를 타게 된다.
        if await _reregistration_blocked(db, pending["email"], now):
            raise _onboarding_conflict("REREGISTRATION_BLOCKED")
        user = User(email=pending["email"], google_sub=pending["sub"], email_verified_at=now)
        await _apply_onboarding_consent(db, user, payload, now)
        await _flush_social_signup(db, user)
    else:
        # 대입·커밋·pending 토큰 삭제 **전**에 막는다 — 뒤에서 막으면 403인데도
        # 닉네임·생년월일이 덮어써진 채 커밋되고, 토큰이 지워져 재시도가 400으로 바뀐다.
        # 신규 유저 분기는 방금 만든 행이라 suspended_at이 정의상 None이다.
        if user.suspended_at is not None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
        user.nickname = payload.nickname
        user.birth_date = payload.birth_date
    await db.commit()
    await delete_pending_google_signup(token)
    return await _start_onboarded_session(response, user, provider="google")


@router.get("/kakao")
async def kakao_login(redirect: str = "/") -> RedirectResponse:
    # 키가 없는 환경(로컬·CI)에서 카카오로 보내면 카카오 오류 화면이라는 막다른 곳에 닿는다.
    if not kakao_oauth.kakao_login_configured():
        return oauth_login_error_redirect("kakao_failed", provider="kakao")
    state = await kakao_oauth.store_oauth_state(safe_redirect_path(redirect))
    response = RedirectResponse(
        kakao_oauth.build_authorization_url(state), status_code=status.HTTP_302_FOUND
    )
    # 같은 state 를 로그인을 시작한 브라우저에도 심는다 — 콜백이 대조한다(resolve_oauth_state).
    set_oauth_cookie(
        response,
        state_cookie_name("kakao"),
        state,
        max_age=settings.kakao_oauth_state_ttl_seconds,
    )
    return response


@router.get("/kakao/callback")
async def kakao_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    fetch_profile: KakaoProfileFetcher = Depends(get_kakao_profile_fetcher),
    db: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    # 판정 순서와 그 이유는 google_callback 과 같다(state → 취소 → 교환 → 회원 판정, 어떤 결과든
    # 로그인 화면으로 302).
    redirect_target = await resolve_oauth_state(
        request, state, provider="kakao", consume=kakao_oauth.consume_oauth_state
    )
    if redirect_target is None:
        return oauth_login_error_redirect("kakao_state", provider="kakao")
    if error is not None or code is None:
        return oauth_login_error_redirect("kakao_cancelled", provider="kakao")
    try:
        profile = await fetch_profile(code)
    except OAuthExchangeError as exc:
        logger.warning("kakao oauth exchange failed: %s", exc)
        capture_dependency_failure(exc, dependency="kakao_oauth")
        return oauth_login_error_redirect("kakao_failed", provider="kakao")

    user = await db.scalar(select(User).where(User.kakao_id == profile["kakao_id"]))
    if user is not None:
        # 기존 회원은 이메일 상태와 무관하게 들인다. 계정 키는 회원번호이고 이메일은 가입 시점의
        # 충돌 판정과 인증 기록에만 쓰였다 — 가입 뒤 카카오계정 이메일이 무효가 되거나 이메일 제공
        # 동의를 철회했다고 로그인을 막으면 고칠 길 없이 계정에 못 들어온다.
        return await finish_social_login(user, redirect_target, provider="kakao")

    email = profile["email"]
    if email is None:
        # 신규 가입만 인증된 이메일을 요구한다. 이메일 충돌 판정과 `email_verified_at` 기록이 "이
        # 이메일은 이 사람의 것"이라는 전제 위에 서 있어서, 미인증 이메일을 받으면 남의 이메일로
        # 가입하거나 남의 계정과 충돌 판정이 날 수 있다. 장애가 아니라 사용자가 고칠 수 있는
        # 상태(이메일 제공 미동의·미인증)라 따로 안내하고 Sentry 에는 올리지 않는다.
        return oauth_login_error_redirect("kakao_email_required", provider="kakao")

    # 같은 이메일의 계정이 있어도 카카오를 자동으로 붙이지 않는다(구글과 다르다) — 미인증 이메일·
    # 이메일 재활용으로 남의 계정에 들어가는 경로를 없앤다. 원래 가입 수단을 알려 그쪽으로
    # 로그인하게 한다. 예외는 방치된 미인증 이메일 가입이다: 로그인할 수 없는 기록이라 막을 이유가
    # 없고, 카카오가 인증한 이메일이므로 온보딩이 그 행을 이 사람의 카카오 계정으로 대체한다.
    same_email = await db.scalar(select(User).where(User.email == email))
    if same_email is not None and not _is_abandoned_email_signup(same_email):
        return oauth_callback_redirect(
            f"{settings.frontend_base_url}/login?error=kakao_email_taken"
            f"&method={signup_method(same_email)}",
            provider="kakao",
        )

    token = await kakao_oauth.store_pending_kakao_signup(
        kakao_oauth.KakaoPendingSignup(kakao_id=profile["kakao_id"], email=email)
    )
    # 토큰을 URL 이 아니라 HttpOnly 쿠키로 내리는 이유는 google_callback 과 같다.
    response = oauth_callback_redirect(
        f"{settings.frontend_base_url}/onboarding/kakao", provider="kakao"
    )
    set_oauth_cookie(
        response,
        pending_signup_cookie_name("kakao"),
        token,
        max_age=settings.kakao_pending_signup_ttl_seconds,
    )
    return response


@router.post("/onboarding/kakao")
async def onboarding_kakao(
    payload: SocialOnboardingRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> SocialOnboardingResponse:
    token = request.cookies.get(pending_signup_cookie_name("kakao"))
    pending = await kakao_oauth.get_pending_kakao_signup(token) if token is not None else None
    if token is None or pending is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    now = datetime.now(UTC)
    replaced_email_signup = False
    user = await db.scalar(select(User).where(User.kakao_id == pending["kakao_id"]))
    if user is None:
        # 탈퇴 시 kakao_id 도 파기되므로 재가입 시도는 항상 이 분기를 탄다.
        if await _reregistration_blocked(db, pending["email"], now):
            raise _onboarding_conflict("REREGISTRATION_BLOCKED")
        # 같은 이메일 행을 잠그고 다시 판정한다 — 콜백 뒤에 그 이메일 가입이 인증을 마쳤거나
        # 다른 가입이 생겼을 수 있고, 잠가야 이메일 가입의 덮어쓰기(signup)와 엇갈리지 않는다.
        same_email = await db.scalar(
            select(User)
            .where(User.email == pending["email"])
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if same_email is None:
            user = User(email=pending["email"], kakao_id=pending["kakao_id"], email_verified_at=now)
        elif _is_abandoned_email_signup(same_email):
            # 방치된 미인증 이메일 가입을 이 카카오 계정으로 대체한다. 행을 지우고 새로 만들지 않고
            # 그 행을 재사용한다 — users.id 를 가리키는 FK 가 여럿이라(운영자 조치 기록 등) 삭제는
            # 그 참조가 하나라도 있으면 실패하고, signup 의 덮어쓰기도 같은 이유로 행을 재사용한다.
            # 비밀번호는 지운다: 남이 이 이메일로 미인증 가입을 해 둔 경우 그 비밀번호로 이 계정에
            # 들어올 수 없어야 한다.
            user = same_email
            user.password_hash = None
            user.kakao_id = pending["kakao_id"]
            user.email_verified_at = now
            replaced_email_signup = True
        else:
            raise _onboarding_conflict("EMAIL_ALREADY_REGISTERED")
        await _apply_onboarding_consent(db, user, payload, now)
        await _flush_social_signup(db, user)
    else:
        # 구글 온보딩과 같다 — 대입·커밋·가입 대기 삭제 전에 막아야 403 인데도 프로필이 덮어써지거나
        # 재시도가 400 으로 바뀌지 않는다.
        if user.suspended_at is not None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
        user.nickname = payload.nickname
        user.birth_date = payload.birth_date
    await db.commit()
    if replaced_email_signup:
        # 대체된 이메일 가입에 발급했던 인증 코드를 지운다. 남아 있어도 이미 인증된 행이라 결과는
        # 같지만, 지워진 가입의 흔적을 남기지 않는다.
        await delete_verification_code(pending["email"])
        await clear_verification_attempts(pending["email"])
    await kakao_oauth.delete_pending_kakao_signup(token)
    return await _start_onboarded_session(response, user, provider="kakao")


def _kakao_webhook_user_id(request: Request, body: bytes) -> str | None:
    """연결 해제 웹훅의 회원번호를 꺼낸다. 카카오 문서는 POST 본문 형식을 명시하지 않아(예시는
    form-urlencoded) form 을 먼저 보고, JSON 본문과 쿼리스트링(GET)도 받는다. 요청 본문 파서
    (python-multipart)가 의존성에 없어 직접 파싱한다."""
    text = body.decode("utf-8", errors="replace")
    form_values = parse_qs(text).get("user_id")
    if form_values:
        return form_values[0]
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("user_id") is not None:
        return str(data["user_id"])
    return request.query_params.get("user_id")


async def _handle_kakao_unlink_webhook(
    request: Request, background_tasks: BackgroundTasks, db: AsyncSession
) -> Response:
    """사용자가 카카오 쪽에서 앱 연결을 끊거나 카카오계정을 지우면 카카오가 보내는 알림이다. 우리
    탈퇴와 같은 파기(1년 재가입 차단 기록 포함)를 한다 — 연결 끊기만으로 재가입 차단을 피할 수
    있으면 탈퇴 차단의 우회로가 된다. 카카오계정 삭제도 이 알림으로 오므로 정지 회원도 파기한다.

    카카오는 3초 안에 200 을 요구하고 이 알림은 재전송이 없다. 그래서 받은 자리에서 커밋까지
    끝내고, 호출 수에 상한이 없는 오브젝트 스토리지 삭제만 키를 모아 응답 뒤로 미룬다. 회원이
    없거나 이미 탈퇴했어도 200 이다(카카오 요구 규격).
    """
    expected = f"KakaoAK {settings.kakao_admin_key}".encode()
    authorization = request.headers.get("authorization")
    # 키가 비어 있으면 무엇이든 거절한다 — 빈 키와 `KakaoAK ` 헤더가 일치해 누구나 회원을 파기할
    # 수 있게 되는 것을 막는다. 비교는 바이트로 한다(비ASCII 헤더 값에 TypeError 가 나지 않게).
    if (
        not settings.kakao_admin_key
        or authorization is None
        or not secrets.compare_digest(authorization.encode(), expected)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    kakao_id = _kakao_webhook_user_id(request, await request.body())
    if kakao_id is None:
        return Response(status_code=status.HTTP_200_OK)
    # 같은 알림이 겹쳐 와도 두 번째는 첫 커밋을 기다린 뒤 회원번호가 지워진 행을 다시 평가해
    # 0행이 된다 — 잠금과 커밋 뒤 NULL 이 멱등을 만든다.
    user = await db.scalar(
        select(User)
        .where(User.kakao_id == kakao_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if user is None or user.deleted_at is not None:
        return Response(status_code=status.HTTP_200_OK)

    storage_keys: list[str] = []

    async def collect_storage_key(storage_key: str) -> None:
        storage_keys.append(storage_key)

    user_id = user.id
    await erase_account(db, user, delete_storage_object=collect_storage_key)
    # 카카오 쪽 연결은 이미 끊겼으므로 연결 끊기 API 는 부르지 않는다.
    # 세션 폐기가 실패해도 500 을 내지 않는다 — 파기는 이미 커밋됐고 카카오는 재전송하지 않으므로
    # 500 은 아래 오브젝트 스토리지 삭제 예약만 빠뜨린다. 남은 세션은 `get_current_user_id` 의
    # 탈퇴 행 조회가 401 로 막는다.
    try:
        await revoke_user_sessions(user_id)
    except Exception as exc:
        logger.warning("kakao unlink webhook: session revoke failed for user %s: %r", user_id, exc)
        capture_dependency_failure(exc, dependency="redis")
    if storage_keys:
        background_tasks.add_task(delete_storage_objects_later, storage_keys)
    return Response(status_code=status.HTTP_200_OK)


# 카카오 콘솔이 GET·POST 중 하나를 고르게 해 둘 다 받는다. 서버 간 호출이라 스키마에서 뺀다 — 한
# 라우트에 두 메서드를 묶으면 operationId 가 실행마다 흔들려 openapi 드리프트 검사가 깨진다.
@router.get("/kakao/unlink", include_in_schema=False)
async def kakao_unlink_webhook_get(
    request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db_session)
) -> Response:
    return await _handle_kakao_unlink_webhook(request, background_tasks, db)


@router.post("/kakao/unlink", include_in_schema=False)
async def kakao_unlink_webhook_post(
    request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db_session)
) -> Response:
    return await _handle_kakao_unlink_webhook(request, background_tasks, db)


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

    # 위 조건문이 deleted_at is not None인 계정을 이미 배제했다 — birth_date는 탈퇴 파기
    # 시에만 None이 된다.
    assert user.birth_date is not None
    # 만 14세 미만 신규 가입은 서버가 거부하므로 이 분기는 시행일
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
        # 있다(정지를 "요청 차단"으로 설계한 것과 짝을 이루는 판단 — 세션이
        # 살아있는 채 막히는 것과 로그인 시도가 막히는 것이 같은 메시지를 줘야 일관적이다).
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    session_id = await create_session(user.id)
    set_session_cookie(response, session_id)
    return None


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    session_id = get_session_id_from_request(request)
    if session_id is not None:
        # 역인덱스(`user_sessions:{user_id}`)의 멤버는 남겨 둔다 — 키 없는 멤버는 폐기 때 DEL이
        # 헛돌 뿐이고 만료 score가 지나면 다음 로그인에서 정리된다.
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
    # 카운터를 계정 존재 여부와 무관하게, DB 조회보다 먼저 올린다 —
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
    # 비밀번호가 없는 소셜 전용 계정에는 보내지 않는다 — 재설정 링크가 그 계정에 비밀번호를 새로
    # 만들어, 의도하지 않은 두 번째 로그인 수단이 생긴다. 응답은 미등록 이메일과 같은 204 다.
    if user is not None and user.password_hash is not None:
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
    # 탈퇴 전에 발급된 토큰이 탈퇴 때 파기한 `password_hash`를 되살리지 못하게 한다
    # 탈퇴 계정은 이메일이 자리표시자라 새 토큰은 못 받는다.
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    # 비밀번호가 없는 소셜 전용 계정에 비밀번호가 생기는 경로를 재설정 요청 단계와 함께 여기서도
    # 닫는다 — 요청 단계의 검사가 배포되기 전에 발급된 토큰이 아직 살아 있을 수 있다.
    if user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    # 재설정은 계정이 털렸을 때 쓰는 경로라 현재 세션 개념 없이 전부 폐기한다.
    # 토큰 삭제보다 먼저 한다 — 폐기가 실패해 500이 나도 토큰이 남아 있어야 같은 링크로 재시도하면
    # 폐기까지 끝난다(토큰을 먼저 지우면 옛 세션이 남은 채 재시도 수단이 사라진다).
    await revoke_user_sessions(user.id)
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

    # 위 조건문이 deleted_at is not None인 계정을 이미 배제했다 — nickname은 탈퇴 파기
    # 시에만 None이 된다.
    assert user.nickname is not None
    method = signup_method(user)
    return MeResponse(
        id=user.id,
        email=user.email,
        nickname=user.nickname,
        bio=user.bio,
        profile_image_asset_id=user.profile_image_asset_id,
        terms_reconsent_required=_reconsent_required(user.terms_version, required_terms_version),
        privacy_reconsent_required=_reconsent_required(user.privacy_version, required_privacy_version),
        has_password=user.password_hash is not None,
        social_provider=None if method == "email" else method,
    )


@me_router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # 소셜 전용 계정은 "현재 비밀번호가 틀렸다"가 아니라 비밀번호가 없다는 사실을 따로 알린다 —
    # 같은 400 문자열이면 프런트가 존재하지 않는 비밀번호를 다시 입력하라고 안내하게 된다.
    if user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "PASSWORD_NOT_SET"}
        )
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )

    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    # 다른 기기 세션만 폐기한다 — 바꾼 사람은 지금 이 세션이다.
    await revoke_user_sessions(user_id, except_session_id=get_session_id_from_request(request))
    return None


@me_router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    kakao_unlinker: KakaoUnlinker = Depends(get_kakao_unlinker),
) -> None:
    user = await lock_active_user(db, user_id)
    # 파기가 회원번호를 지우므로 연결 끊기에 쓸 값을 먼저 잡아 둔다.
    kakao_id = user.kakao_id
    await erase_account(db, user, delete_storage_object=delete_storage_object_now)

    # 역인덱스 배포 전에 만든 세션은 인덱스에 없어 아래 폐기가 못 지운다 — 현재 세션만은 쿠키로
    # 직접 지운다. 폐기보다 **먼저** 부르는 건 역인덱스 도입 전 순서 그대로다: 폐기의 Redis 호출이 중간에
    # 실패해도 현재 세션은 이미 지워져 있다. 두 호출은 서로 독립이다.
    session_id = get_session_id_from_request(request)
    if session_id is not None:
        await delete_session(session_id)
    # 현재 세션을 포함해 전부 폐기한다. 실패해 500이 나도
    # 탈퇴는 이미 커밋됐고, 남은 세션은 `get_current_user_id`의 `users` 조회가 401로 막는다.
    await revoke_user_sessions(user_id)
    clear_session_cookie(response)
    # 카카오와의 앱 연결은 커밋 뒤 백그라운드로 끊는다 — 실패해도 탈퇴는 이미 끝났다
    # (unlink_after_withdrawal 이 이유와 함께 실패를 기록한다).
    if kakao_id is not None:
        background_tasks.add_task(unlink_after_withdrawal, kakao_unlinker, kakao_id, user_id)
    return None
