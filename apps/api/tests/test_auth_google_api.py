import uuid
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.google_oauth import (
    GoogleProfile,
    _state_key,
    get_google_profile,
    get_pending_google_signup,
    safe_redirect_path,
    store_pending_google_signup,
)
from api.core.config import settings
from api.core.redis import redis_client
from api.core.security import hash_password
from api.db.models.auth import User
from api.main import app
from factories import _make_user


def _fake_profile(sub: str, email: str) -> GoogleProfile:
    return GoogleProfile(sub=sub, email=email)


def _override_google_profile(sub: str, email: str) -> None:
    app.dependency_overrides[get_google_profile] = lambda: _fake_profile(sub, email)


def _clear_google_profile_override() -> None:
    del app.dependency_overrides[get_google_profile]


async def test_google_login_redirects_to_google_auth_url(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/auth/google", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "redirect_uri=" in location
    assert "state=" in location


async def test_google_callback_rejects_unknown_state(db_client: httpx.AsyncClient) -> None:
    """소비된/위조된 state는 날것의 400이 아니라 로그인 화면으로 되돌린다 — 온보딩에서
    뒤로가기 후 계정 재선택처럼 정상 사용자도 도달하는 경로라, 브라우저에 JSON 본문이
    렌더링되는 막다른 페이지가 되면 안 된다."""
    _override_google_profile("google-sub-unknown-state", "unknown-state@example.com")
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": "not-a-real-state"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"
    finally:
        _clear_google_profile_override()


async def _start_google_login(db_client: httpx.AsyncClient, redirect: str = "/") -> str:
    start = await db_client.get("/auth/google", params={"redirect": redirect}, follow_redirects=False)
    location = start.headers["location"]
    state = httpx.URL(location).params["state"]
    return state


async def test_google_callback_new_user_redirects_to_onboarding_without_session(
    db_client: httpx.AsyncClient,
) -> None:
    state = await _start_google_login(db_client)
    _override_google_profile(f"google-sub-{uuid.uuid4()}", f"new-{uuid.uuid4()}@example.com")
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(f"{settings.frontend_base_url}/onboarding/google?token=")
        assert settings.session_cookie_name not in resp.cookies
    finally:
        _clear_google_profile_override()


async def _onboard_new_google_user(
    db_client: httpx.AsyncClient, birth_date: str, **overrides: object
) -> dict[str, object]:
    sub = f"google-sub-{uuid.uuid4()}"
    email = f"new-{uuid.uuid4()}@example.com"
    state = await _start_google_login(db_client)
    _override_google_profile(sub, email)
    try:
        callback = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()
    token = httpx.URL(callback.headers["location"]).params["token"]

    payload: dict[str, object] = {
        "token": token,
        "nickname": "구글유저",
        "birthDate": birth_date,
        "termsAgreed": True,
        "privacyAgreed": True,
        "transferAgreed": True,
    }
    payload.update(overrides)
    return {"payload": payload, "sub": sub, "email": email}


async def test_onboarding_google_adult_creates_user_and_issues_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")

    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 200
    assert resp.json() == {"email": ctx["email"]}
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == ctx["email"]))
    assert user is not None
    assert user.google_sub == ctx["sub"]
    assert user.nickname == "구글유저"
    assert user.email_verified_at is not None

    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)


async def test_onboarding_google_rejects_under_minimum_age(db_client: httpx.AsyncClient) -> None:
    """legal-revision-goal-prompt.md LR-9: 이메일 가입과 마찬가지로 구글 온보딩도 만 14세
    미만을 거부한다 — 두 경로가 비대칭으로 새지 않는지가 이 런의 반복된 위험이다."""
    minor_birth_date = date.today().replace(year=date.today().year - 13).isoformat()
    ctx = await _onboard_new_google_user(db_client, minor_birth_date)

    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 422


async def test_onboarding_google_rejects_missing_terms_agreement(db_client: httpx.AsyncClient) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01", termsAgreed=False)
    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 422


async def test_onboarding_google_rejects_missing_transfer_agreement(db_client: httpx.AsyncClient) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01", transferAgreed=False)
    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 422


async def test_onboarding_google_rejects_transfer_agreement_field_omitted(
    db_client: httpx.AsyncClient,
) -> None:
    """legal-revision-goal-prompt.md LR-1: SignupRequest와 마찬가지로 transferAgreed는
    OnboardingGoogleRequest에서도 필수 필드다 — 두 클래스의 validator는 복붙본이라
    한쪽만 고치면 이 경로에서만 422가 안 걸리는 비대칭이 생길 수 있다."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    payload = ctx["payload"]
    assert isinstance(payload, dict)
    del payload["transferAgreed"]
    resp = await db_client.post("/auth/onboarding/google", json=payload)
    assert resp.status_code == 422


async def test_onboarding_google_rejects_invalid_token(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/onboarding/google",
        json={
            "token": "not-a-real-token",
            "nickname": "구글유저",
            "birthDate": "2000-01-01",
            "termsAgreed": True,
            "privacyAgreed": True,
            "transferAgreed": True,
        },
    )
    assert resp.status_code == 400


async def test_google_callback_existing_adult_user_issues_session_and_redirects(
    db_client: httpx.AsyncClient,
) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200
    db_client.cookies.clear()

    state = await _start_google_login(db_client, redirect="/mypage")
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/mypage"
    assert settings.session_cookie_name in resp.cookies


async def test_google_callback_links_existing_password_account_by_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    signup_payload = {
        "email": f"linked-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "패스워드유저",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
        "transferAgreed": True,
    }
    signup_resp = await db_client.post("/auth/signup", json=signup_payload)
    assert signup_resp.status_code == 201

    state = await _start_google_login(db_client)
    google_sub = f"google-sub-{uuid.uuid4()}"
    _override_google_profile(google_sub, str(signup_payload["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == signup_payload["email"]))
    assert user is not None
    assert user.google_sub == google_sub


async def test_google_callback_redirects_suspended_existing_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지 확인을 넣는 김에 메운 기존 갭(deleted_at 미확인)과 짝을 이루는 경로 —
    구글 로그인은 리다이렉트 응답이라 HTTPException이 아니라 `?error=`로 로그인
    화면에 되돌린다."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200
    db_client.cookies.clear()

    user = await db_session.scalar(select(User).where(User.email == ctx["email"]))
    assert user is not None
    user.suspended_at = datetime.now(UTC)
    await db_session.flush()

    state = await _start_google_login(db_client)
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=account_suspended"
    assert settings.session_cookie_name not in resp.cookies


async def test_onboarding_google_suspended_existing_user_is_rejected_without_side_effects(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """backlog-sweep BS-8(J-1): 정지 검사가 `db.commit()`·pending 토큰 삭제보다 **앞**에 있어야
    한다. 이 403은 `google_sub` 매치 기존 유저 분기에서만 난다(신규 유저는 `suspended_at`이
    정의상 `None`) — 콜백은 정지 유저를 리다이렉트해 토큰을 주지 않으므로 토큰을 직접 만든다.
    이 분기에 실제로 닿는 드문 경로는 둘이다(완료 뒤 재제출은 토큰이 지워져 400이라 아니다):
    (a) 같은 토큰을 **동시에** 두 번 제출해 한쪽이 먼저 커밋한 뒤 관리자가 정지한 경우,
    (b) pending 토큰을 받은 뒤 같은 이메일로 비밀번호 가입 → 두 번째 구글 콜백이 그 행에
    `google_sub`를 연결 → 관리자 정지 → 옛 토큰 제출.
    403만 보면 순서가 틀려도 초록이다 — 닉네임 원복·토큰 잔존·재시도 403이 신호다."""
    sub = f"google-sub-{uuid.uuid4()}"
    user = _make_user(
        google_sub=sub,
        nickname="원래",
        birth_date=date(1999, 5, 5),
        suspended_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    token = await store_pending_google_signup(GoogleProfile(sub=sub, email=user.email))
    payload = {
        "token": token,
        "nickname": "바뀜",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
        "transferAgreed": True,
    }

    resp = await db_client.post("/auth/onboarding/google", json=payload)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Account suspended"
    assert settings.session_cookie_name not in resp.cookies
    await db_session.refresh(user)
    assert user.nickname == "원래"
    assert user.birth_date == date(1999, 5, 5)
    assert await get_pending_google_signup(token) is not None

    retry = await db_client.post("/auth/onboarding/google", json=payload)
    assert retry.status_code == 403


async def test_google_callback_rejects_existing_minor_account_matched_by_google_sub(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """legal-revision-goal-prompt.md LR-30 정정판: S2 적대적 리뷰가 찾은 구멍 — 연령 게이트가
    `login()`에만 있고 `google_callback`엔 없었다. LR-9가 신규 가입을 막아 더 이상
    `/auth/signup`으로는 만들 수 없는 기존 미성년 계정을, 시행일 이전 가입분을 흉내 내
    DB에 직접 만들어 재현한다. google_sub 직접 매치 분기가 세션 없이 되돌리는지 본다."""
    sub = f"google-sub-{uuid.uuid4()}"
    user = _make_user(
        google_sub=sub, birth_date=date.today().replace(year=date.today().year - 13)
    )
    db_session.add(user)
    await db_session.flush()

    state = await _start_google_login(db_client)
    _override_google_profile(sub, user.email)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert (
        resp.headers["location"]
        == f"{settings.frontend_base_url}/login?error=account_age_restricted"
    )
    assert settings.session_cookie_name not in resp.cookies


async def test_google_callback_rejects_existing_minor_account_linked_by_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이메일 매칭으로 기존 (비밀번호) 계정에 google_sub를 붙이는 분기도 같은 게이트를
    타는지 본다 — 정정판이 지적한 바로 그 분기다. google_sub 직접 매치 분기만 막고 이
    분기를 빠뜨리면 링크된 기존 미성년 계정이 구글 로그인으로 그대로 들어온다."""
    user = _make_user(
        birth_date=date.today().replace(year=date.today().year - 13),
        password_hash=hash_password("password123"),
    )
    db_session.add(user)
    await db_session.flush()

    state = await _start_google_login(db_client)
    google_sub = f"google-sub-{uuid.uuid4()}"
    _override_google_profile(google_sub, user.email)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert (
        resp.headers["location"]
        == f"{settings.frontend_base_url}/login?error=account_age_restricted"
    )
    assert settings.session_cookie_name not in resp.cookies


async def test_onboarding_google_blocks_reregistration_within_one_year_of_withdrawal(
    db_client: httpx.AsyncClient,
) -> None:
    """legal-revision-goal-prompt.md LR-7·LR-18: 탈퇴 시 google_sub도 파기되므로(LR-18)
    google_sub 직접 매치가 아니라 onboarding_google의 신규 유저 생성 분기를 타게 되고,
    거기서 withdrawn_emails의 HMAC 조회가 막는다. 이 런에서 반복된 비대칭 위험(이메일
    경로만 막고 구글 경로가 새는 것)을 가장 직접적으로 확인하는 테스트다."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200

    withdraw_resp = await db_client.delete("/me")
    assert withdraw_resp.status_code == 204

    state = await _start_google_login(db_client)
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        callback = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    # google_sub가 파기됐으므로 "기존 계정을 찾음"이 아니라 "신규 가입"으로 취급돼
    # 온보딩으로 되돌아간다 — google_sub가 안 지워졌다면 여긴 /login?error=account_deleted였을 것.
    assert callback.status_code == 302
    assert callback.headers["location"].startswith(
        f"{settings.frontend_base_url}/onboarding/google?token="
    )
    token = httpx.URL(callback.headers["location"]).params["token"]

    resp = await db_client.post(
        "/auth/onboarding/google",
        json={
            "token": token,
            "nickname": "구글유저",
            "birthDate": "2000-01-01",
            "termsAgreed": True,
            "privacyAgreed": True,
            "transferAgreed": True,
        },
    )
    assert resp.status_code == 409


# backlog-l-goal-prompt.md BL-1: redirect 는 콜백에서 frontend_base_url 뒤에 그대로 이어 붙으므로
# "https://ddona.site" + "@evil.com" 처럼 호스트를 바꾸는 값이 들어오면 로그인 직후 외부로 튄다.
_UNSAFE_REDIRECTS = [
    "@evil.com",
    ".evil.com",
    "//evil.com",
    "/\\evil.com",
    "/foo\\bar",
    "https://evil.com",
    "javascript:alert(1)",
    "",
    "/\t/evil.com",
    "/\n/evil.com",
    "/\x00x",
    "/\x7fx",
]
_SAFE_REDIRECTS = ["/", "/content/1?x=1", "/my#tab"]


@pytest.mark.parametrize("value", _UNSAFE_REDIRECTS)
def test_safe_redirect_path_falls_back_to_root(value: str) -> None:
    assert safe_redirect_path(value) == "/"


@pytest.mark.parametrize("value", _SAFE_REDIRECTS)
def test_safe_redirect_path_keeps_same_origin_path(value: str) -> None:
    assert safe_redirect_path(value) == value


async def test_google_login_stores_sanitized_redirect(db_client: httpx.AsyncClient) -> None:
    """저장 전에 걸러지는지 — 콜백 쪽 재검증만 있어도 아래 엔드포인트 테스트는 통과하므로 따로 본다."""
    state = await _start_google_login(db_client, redirect="@evil.com")
    assert await redis_client.get(_state_key(state)) == "/"


async def test_google_callback_unsafe_redirect_lands_on_frontend_root(
    db_client: httpx.AsyncClient,
) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200
    db_client.cookies.clear()

    state = await _start_google_login(db_client, redirect="@evil.com")
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/"


async def test_google_callback_revalidates_redirect_stored_before_fix(
    db_client: httpx.AsyncClient,
) -> None:
    """배포 전에 Redis 에 들어간 state(검증 없이 저장된 악성 값)도 콜백에서 막는다."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200
    db_client.cookies.clear()

    state = f"pre-fix-{uuid.uuid4()}"
    await redis_client.set(_state_key(state), "@evil.com", ex=60)
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/"
