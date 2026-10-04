import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.google_oauth import (
    GoogleProfile,
    GoogleProfileFetcher,
    PendingGoogleSignup,
    _pending_signup_key,
    _state_key,
    exchange_code_for_profile,
    get_google_profile_fetcher,
    get_pending_google_signup,
    store_pending_google_signup,
)
from api.auth.oauth_common import OAuthExchangeError, safe_redirect_path
from api.core.config import settings
from api.core.redis import redis_client
from api.core.security import hash_password
from api.db.models.auth import User
from api.db.session import engine
from api.main import app
from factories import _login_as, _make_user, _patch_httpx, _wait_until_lock_wait

_STATE_COOKIE = "oauth_state_google"
_PENDING_COOKIE = "oauth_pending_google"


def _fake_profile(sub: str, email: str | None) -> GoogleProfile:
    return GoogleProfile(sub=sub, email=email)


def _override_profile_fetcher(fetch: GoogleProfileFetcher) -> None:
    app.dependency_overrides[get_google_profile_fetcher] = lambda: fetch


def _override_google_profile(sub: str, email: str | None) -> None:
    async def fetch(code: str) -> GoogleProfile:
        return _fake_profile(sub, email)

    _override_profile_fetcher(fetch)


def _clear_google_profile_override() -> None:
    del app.dependency_overrides[get_google_profile_fetcher]


def _set_cookie_headers(resp: httpx.Response, name: str) -> list[str]:
    return [h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{name}=")]


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


async def test_google_login_binds_state_to_browser_with_cookie(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """state 를 Redis 에만 두면 공격자가 자기 인가 흐름의 콜백 URL 을 피해자 브라우저에서 열게 해
    피해자를 공격자 계정으로 로그인시킬 수 있다. 시작한 브라우저에 같은 값을 쿠키로 심는지,
    그리고 dev 의 `/api` 접두 프록시에서도 실리도록 Path 가 `/` 인지 본다."""
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    resp = await db_client.get("/auth/google", follow_redirects=False)
    state = httpx.URL(resp.headers["location"]).params["state"]

    [header] = _set_cookie_headers(resp, _STATE_COOKIE)
    assert header.startswith(f"{_STATE_COOKIE}={state};")
    attrs = {part.strip().lower() for part in header.split(";")[1:]}
    assert {"httponly", "path=/", "samesite=lax", "secure"} <= attrs
    assert f"max-age={settings.google_oauth_state_ttl_seconds}" in attrs


async def test_google_callback_rejects_state_without_browser_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    """로그인 CSRF 의 모양 그대로다 — Redis 에는 살아 있는(공격자가 시작한) state 지만 콜백을 연
    브라우저에는 그 쿠키가 없다. 쿠키 대조 없이 Redis 만 보면 여기서 세션이 나간다."""
    state = await _start_google_login(db_client)
    db_client.cookies.clear()
    _override_google_profile(f"google-sub-{uuid.uuid4()}", f"csrf-{uuid.uuid4()}@example.com")
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"
    assert settings.session_cookie_name not in resp.cookies
    assert not _set_cookie_headers(resp, _PENDING_COOKIE)


async def test_google_callback_rejects_state_that_does_not_match_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    """같은 브라우저에서 로그인을 두 번 시작하면 쿠키는 뒤의 state 로 덮인다. 앞의 state 로 돌아온
    콜백은 불일치로 거절되고, 대조가 consume 보다 먼저라 앞의 state 는 Redis 에 그대로 남는다."""
    first_state = await _start_google_login(db_client)
    await _start_google_login(db_client)
    _override_google_profile(f"google-sub-{uuid.uuid4()}", f"two-tabs-{uuid.uuid4()}@example.com")
    try:
        resp = await db_client.get(
            "/auth/google/callback",
            params={"state": first_state, "code": "c"},
            follow_redirects=False,
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"
    assert await redis_client.get(_state_key(first_state)) is not None


async def test_google_callback_rejects_non_ascii_state_against_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    """state 는 공격자가 고를 수 있는 쿼리 값이다. 비ASCII 문자열을 str 그대로 상수 시간 비교에
    넘기면 TypeError 로 500 이 나므로, 쿠키가 있는 상태에서도 로그인 화면으로 돌아오는지 본다."""
    await _start_google_login(db_client)
    _override_profile_fetcher(_fail_if_called)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": "\u00e9", "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"


async def test_google_callback_rejects_expired_state_even_with_matching_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    """쿠키 대조는 Redis 의 1회성·TTL 을 대신하지 않는다 — 쿠키가 맞아도 Redis 에서 사라진
    state(만료, 이미 소비)는 거절한다."""
    state = await _start_google_login(db_client)
    await redis_client.delete(_state_key(state))
    _override_profile_fetcher(_fail_if_called)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"


async def _fail_if_called(code: str) -> GoogleProfile:
    raise AssertionError("취소된 콜백이 토큰 교환을 호출했다")


async def test_google_callback_cancelled_by_user_returns_to_login(
    db_client: httpx.AsyncClient,
) -> None:
    """구글 동의 화면에서 취소하면 `code` 없이 `error=access_denied` 와 state 만 돌아온다.
    전에는 `code` 필수 파라미터 검증의 422 JSON 이 브라우저에 그대로 떴다."""
    state = await _start_google_login(db_client)
    _override_profile_fetcher(_fail_if_called)
    try:
        resp = await db_client.get(
            "/auth/google/callback",
            params={"error": "access_denied", "state": state},
            follow_redirects=False,
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_cancelled"
    # 취소도 이 흐름의 끝이라 1회용 state 를 소비하고 브라우저 쿠키를 지운다.
    assert await redis_client.get(_state_key(state)) is None
    [cleared] = _set_cookie_headers(resp, _STATE_COOKIE)
    assert "max-age=0" in cleared.lower()


async def test_google_callback_without_code_or_error_is_treated_as_cancelled(
    db_client: httpx.AsyncClient,
) -> None:
    state = await _start_google_login(db_client)
    _override_profile_fetcher(_fail_if_called)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_cancelled"


async def test_google_callback_cancel_with_unbound_state_reports_state_error(
    db_client: httpx.AsyncClient,
) -> None:
    """state 를 취소 판정보다 먼저 본다 — 이 브라우저가 시작하지 않은 흐름의 콜백은 취소든
    아니든 같은 state 오류로 끝난다."""
    state = await _start_google_login(db_client)
    db_client.cookies.clear()
    resp = await db_client.get(
        "/auth/google/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"


async def test_google_callback_without_state_returns_to_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(
        "/auth/google/callback", params={"code": "c"}, follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_state"


async def test_google_callback_exchange_failure_returns_to_login(
    db_client: httpx.AsyncClient,
) -> None:
    """토큰 교환·userinfo 실패는 전에 400 JSON(비정상 응답)이나 500(네트워크 오류·키 누락)으로
    브라우저에 그대로 떴다."""

    async def failing(code: str) -> GoogleProfile:
        raise OAuthExchangeError("token exchange returned 400")

    state = await _start_google_login(db_client)
    _override_profile_fetcher(failing)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=google_failed"
    assert settings.session_cookie_name not in resp.cookies
    [cleared] = _set_cookie_headers(resp, _STATE_COOKIE)
    assert "max-age=0" in cleared.lower()


def _token_ok_then(userinfo: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "at"})
        return userinfo

    return handler


def _raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda request: httpx.Response(400, json={}), id="token-non-200"),
        pytest.param(lambda request: httpx.Response(200, json={}), id="token-missing-key"),
        pytest.param(lambda request: httpx.Response(200, text="<html>"), id="token-not-json"),
        pytest.param(_token_ok_then(httpx.Response(500)), id="userinfo-non-200"),
        pytest.param(
            _token_ok_then(httpx.Response(200, json={"email": "a@example.com"})),
            id="userinfo-missing-sub",
        ),
        pytest.param(_raise_connect_error, id="network-error"),
    ],
)
async def test_exchange_code_for_profile_normalizes_failures(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """콜백은 `OAuthExchangeError` 하나만 잡아 로그인 화면으로 되돌린다. 다른 예외가 새면
    500 막다른 화면이 된다."""
    _patch_httpx(monkeypatch, handler, module="api.auth.google_oauth")
    with pytest.raises(OAuthExchangeError):
        await exchange_code_for_profile("code")


async def test_exchange_code_for_profile_returns_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _token_ok_then(
        httpx.Response(200, json={"sub": "s-1", "email": "a@example.com", "email_verified": True})
    )
    _patch_httpx(monkeypatch, handler, module="api.auth.google_oauth")
    assert await exchange_code_for_profile("code") == {"sub": "s-1", "email": "a@example.com"}


@pytest.mark.parametrize(
    "userinfo",
    [
        pytest.param({"sub": "s-1", "email": "a@example.com", "email_verified": False}, id="false"),
        pytest.param({"sub": "s-1", "email": "a@example.com"}, id="verified-missing"),
        pytest.param(
            {"sub": "s-1", "email": "a@example.com", "email_verified": "true"}, id="verified-string"
        ),
        pytest.param({"sub": "s-1", "email_verified": True}, id="email-missing"),
    ],
)
async def test_exchange_code_for_profile_drops_unverified_email(
    monkeypatch: pytest.MonkeyPatch, userinfo: dict[str, object]
) -> None:
    """구글이 인증했다고 확언하지 않은 이메일은 없는 것으로 다룬다 — 그 주소로 기존 계정을 찾아
    붙이면 남의 이메일을 주장한 구글 계정이 그 계정에 들어간다. 교환 실패가 아니다(sub 로 찾을
    기존 회원은 그대로 들어와야 한다)."""
    _patch_httpx(monkeypatch, _token_ok_then(httpx.Response(200, json=userinfo)), module="api.auth.google_oauth")
    assert await exchange_code_for_profile("code") == {"sub": "s-1", "email": None}


async def test_google_callback_new_user_redirects_to_onboarding_without_session(
    db_client: httpx.AsyncClient,
) -> None:
    state = await _start_google_login(db_client)
    _override_google_profile(f"google-sub-{uuid.uuid4()}", f"new-{uuid.uuid4()}@example.com")
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
        assert resp.status_code == 302
        # 토큰이 URL·히스토리·리퍼러로 새지 않게 URL 이 아니라 쿠키로 내린다.
        assert resp.headers["location"] == f"{settings.frontend_base_url}/onboarding/google"
        assert settings.session_cookie_name not in resp.cookies
        [pending] = _set_cookie_headers(resp, _PENDING_COOKIE)
        attrs = {part.strip().lower() for part in pending.split(";")[1:]}
        assert {"httponly", "path=/", "samesite=lax"} <= attrs
        assert f"max-age={settings.google_pending_signup_ttl_seconds}" in attrs
        assert await get_pending_google_signup(resp.cookies[_PENDING_COOKIE]) is not None
        [cleared] = _set_cookie_headers(resp, _STATE_COOKIE)
        assert "max-age=0" in cleared.lower()
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
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()
    assert callback.headers["location"] == f"{settings.frontend_base_url}/onboarding/google"

    payload: dict[str, object] = {
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

    token = db_client.cookies[_PENDING_COOKIE]
    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 200
    assert resp.json() == {"email": ctx["email"]}
    assert settings.session_cookie_name in resp.cookies
    [cleared] = _set_cookie_headers(resp, _PENDING_COOKIE)
    assert "max-age=0" in cleared.lower()
    assert await get_pending_google_signup(token) is None

    user = await db_session.scalar(select(User).where(User.email == ctx["email"]))
    assert user is not None
    assert user.google_sub == ctx["sub"]
    assert user.nickname == "구글유저"
    assert user.email_verified_at is not None

    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)


async def test_onboarding_google_rejects_under_minimum_age(db_client: httpx.AsyncClient) -> None:
    """이메일 가입과 마찬가지로 구글 온보딩도 만 14세
    미만을 거부한다 — 두 경로가 비대칭으로 새는 것이 반복된 위험이다."""
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
    """SignupRequest와 마찬가지로 transferAgreed는
    OnboardingGoogleRequest에서도 필수 필드다 — 두 클래스의 validator는 복붙본이라
    한쪽만 고치면 이 경로에서만 422가 안 걸리는 비대칭이 생길 수 있다."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    payload = ctx["payload"]
    assert isinstance(payload, dict)
    del payload["transferAgreed"]
    resp = await db_client.post("/auth/onboarding/google", json=payload)
    assert resp.status_code == 422


_ONBOARDING_FORM = {
    "nickname": "구글유저",
    "birthDate": "2000-01-01",
    "termsAgreed": True,
    "privacyAgreed": True,
    "transferAgreed": True,
}


async def test_onboarding_google_without_pending_cookie_ignores_token_in_body(
    db_client: httpx.AsyncClient,
) -> None:
    """URL·히스토리로 샌 토큰을 다른 브라우저가 들고 와도 가입을 끝낼 수 없어야 한다 — 쿠키만
    본다. 본문의 옛 `token` 필드는 무시된다(구 프런트가 보내도 422 가 아니다)."""
    token = await store_pending_google_signup(
        PendingGoogleSignup(
            sub=f"google-sub-{uuid.uuid4()}", email=f"leak-{uuid.uuid4()}@example.com"
        )
    )
    resp = await db_client.post("/auth/onboarding/google", json={**_ONBOARDING_FORM, "token": token})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid or expired token"}
    assert await get_pending_google_signup(token) is not None


async def test_onboarding_google_rejects_expired_pending_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    await redis_client.delete(_pending_signup_key(db_client.cookies[_PENDING_COOKIE]))

    resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid or expired token"}


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
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
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
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == signup_payload["email"]))
    assert user is not None
    assert user.google_sub == google_sub


async def test_google_callback_unverified_email_does_not_link_existing_password_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(password_hash=await hash_password("password123"))
    db_session.add(user)
    await db_session.flush()

    state = await _start_google_login(db_client)
    # 프로필의 email 이 None 이면 교환 단계에서 미인증 이메일을 버린 것이다 — 원래 주소가 이
    # 계정과 같았더라도 콜백은 그 주소를 알 수 없어야 한다.
    _override_google_profile(f"google-sub-{uuid.uuid4()}", None)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == (
        f"{settings.frontend_base_url}/login?error=google_email_required"
    )
    assert settings.session_cookie_name not in resp.cookies
    assert not _set_cookie_headers(resp, _PENDING_COOKIE)
    await db_session.refresh(user)
    assert user.google_sub is None


async def test_google_callback_without_verified_email_still_logs_in_existing_member_by_sub(
    db_client: httpx.AsyncClient,
) -> None:
    """이메일 인증 상태는 신규 가입·연결에만 쓴다. 이미 sub 로 묶인 회원을 이메일 상태로 막으면
    고칠 길 없이 계정에 못 들어온다(카카오 콜백과 같은 판단)."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200
    db_client.cookies.clear()

    state = await _start_google_login(db_client, redirect="/mypage")
    _override_google_profile(str(ctx["sub"]), None)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/mypage"
    assert settings.session_cookie_name in resp.cookies


async def test_google_callback_rejects_same_email_already_linked_to_another_google_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 주소를 주장하는 다른 구글 계정(이메일 재발급 등)이 기존 구글 회원의 세션을 받으면
    안 된다. 원래 구글 계정으로 로그인하라고 안내한다."""
    original_sub = f"google-sub-{uuid.uuid4()}"
    user = _make_user(google_sub=original_sub)
    db_session.add(user)
    await db_session.flush()

    state = await _start_google_login(db_client)
    _override_google_profile(f"google-sub-{uuid.uuid4()}", user.email)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == (
        f"{settings.frontend_base_url}/login?error=google_email_taken&method=google"
    )
    assert settings.session_cookie_name not in resp.cookies
    assert not _set_cookie_headers(resp, _PENDING_COOKIE)
    await db_session.refresh(user)
    assert user.google_sub == original_sub


@pytest_asyncio.fixture
async def committed_user_ids() -> AsyncIterator[list[uuid.UUID]]:
    """테스트 트랜잭션 밖에서 커밋한 users 행을 지운다. 콜백이 그 행을 잠근 채 테스트 트랜잭션이
    끝날 때까지 쥐고 있으므로, 테스트 본문에서 지우면 그 잠금을 기다리다 멈춘다. 그래서 테스트
    인자에서 `db_client` 보다 앞에 둬 그 트랜잭션이 되감긴 뒤에 정리되게 한다."""
    ids: list[uuid.UUID] = []
    yield ids
    async with engine.begin() as conn:
        await conn.execute(delete(User).where(User.id.in_(ids)))


async def test_google_callback_racing_link_of_the_same_google_account_logs_in(
    committed_user_ids: list[uuid.UUID], db_client: httpx.AsyncClient
) -> None:
    """같은 구글 계정의 콜백 두 개가 동시에 같은 비밀번호 계정에 연결을 시도한다. 먼저 커밋한 쪽이
    붙인 sub 는 자기 것이라 "다른 구글 계정"으로 거부하면 안 된다. 별개 커넥션이 sub 를 미커밋으로
    붙여 행을 잠그고, 콜백이 sub 조회를 놓친 뒤 이메일 행 잠금을 기다리는 것을 관측한 다음 커밋해
    진짜 경합을 만든다."""
    sub = f"google-sub-{uuid.uuid4()}"
    email = f"race-{uuid.uuid4()}@example.com"
    user_id = uuid.uuid4()
    committed_user_ids.append(user_id)
    async with engine.connect() as interloper:
        await interloper.execute(
            insert(User).values(
                id=user_id,
                email=email,
                password_hash=await hash_password("password123"),
                nickname="경합",
                birth_date=date(2000, 1, 1),
                terms_agreed_at=datetime.now(UTC),
                privacy_agreed_at=datetime.now(UTC),
                email_verified_at=datetime.now(UTC),
            )
        )
        await interloper.commit()
        await interloper.execute(update(User).where(User.id == user_id).values(google_sub=sub))
        interloper_pid = await interloper.scalar(text("SELECT pg_backend_pid()"))

        state = await _start_google_login(db_client)
        _override_google_profile(sub, email)
        try:
            task = asyncio.create_task(
                db_client.get(
                    "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
                )
            )
            try:
                # 콜백 커넥션이 이 커넥션의 트랜잭션 종료를 기다리는 상태(미승인 transactionid
                # 잠금)를 pg_locks 로 직접 관측한다.
                async with asyncio.timeout(5.0):
                    while True:
                        waiting = await interloper.scalar(
                            text(
                                "SELECT count(*) FROM pg_locks"
                                " WHERE locktype = 'transactionid' AND NOT granted AND pid <> :pid"
                            ),
                            {"pid": interloper_pid},
                        )
                        if waiting:
                            break
                        await asyncio.sleep(0.01)
                await interloper.commit()
            finally:
                # 관측에 실패해도 잠금을 풀어 콜백이 끝나게 한다.
                await interloper.rollback()
                resp = await task
        finally:
            _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/"
    assert settings.session_cookie_name in resp.cookies


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
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/login?error=account_suspended"
    assert settings.session_cookie_name not in resp.cookies


async def test_onboarding_google_suspended_existing_user_is_rejected_without_side_effects(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지 검사가 `db.commit()`·pending 토큰 삭제보다 **앞**에 있어야
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
    token = await store_pending_google_signup(PendingGoogleSignup(sub=sub, email=user.email))
    db_client.cookies.set(_PENDING_COOKIE, token)
    payload = {
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
    """리뷰가 찾은 구멍 — 연령 게이트가
    `login()`에만 있고 `google_callback`엔 없었다. 만 14세 미만 가입 거부로 더 이상
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
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
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
        password_hash=await hash_password("password123"),
    )
    db_session.add(user)
    await db_session.flush()

    state = await _start_google_login(db_client)
    google_sub = f"google-sub-{uuid.uuid4()}"
    _override_google_profile(google_sub, user.email)
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
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
    """탈퇴 시 google_sub도 파기되므로
    google_sub 직접 매치가 아니라 onboarding_google의 신규 유저 생성 분기를 타게 되고,
    거기서 withdrawn_emails의 HMAC 조회가 막는다. 반복된 비대칭 위험(이메일
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
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    # google_sub가 파기됐으므로 "기존 계정을 찾음"이 아니라 "신규 가입"으로 취급돼
    # 온보딩으로 되돌아간다 — google_sub가 안 지워졌다면 여긴 /login?error=account_deleted였을 것.
    assert callback.status_code == 302
    assert callback.headers["location"] == f"{settings.frontend_base_url}/onboarding/google"

    resp = await db_client.post("/auth/onboarding/google", json=_ONBOARDING_FORM)
    assert resp.status_code == 409
    # 이메일 중복과 같은 409 라 프런트가 안내 문구를 가를 수 있게 원인을 담는다.
    assert resp.json() == {"detail": {"code": "REREGISTRATION_BLOCKED"}}


async def test_onboarding_google_concurrent_duplicate_email_returns_409_with_code(
    db_client: httpx.AsyncClient,
) -> None:
    """콜백에서 pending 을 받은 뒤 온보딩을 끝내기 전에 같은 이메일로 다른 가입이 먼저 커밋되면
    users.email UNIQUE 의 IntegrityError 를 맞는다. 전에는 이것이 500 이었다. 진짜 경합을
    재현한다 — 별개 커넥션이 같은 이메일을 미커밋으로 넣어 두고, 온보딩 INSERT 가 그 잠금을
    기다리기 시작한 것을 관측한 뒤 커밋한다."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    email = str(ctx["email"])

    async with engine.connect() as interloper:
        await interloper.execute(
            insert(User).values(
                id=uuid.uuid4(),
                email=email,
                nickname="선점",
                birth_date=date(2000, 1, 1),
                terms_agreed_at=datetime.now(UTC),
                privacy_agreed_at=datetime.now(UTC),
            )
        )
        task = asyncio.create_task(db_client.post("/auth/onboarding/google", json=ctx["payload"]))
        try:
            await _wait_until_lock_wait(interloper, seconds=5.0)
            await interloper.commit()
            resp = await task

            assert resp.status_code == 409
            assert resp.json() == {"detail": {"code": "EMAIL_ALREADY_REGISTERED"}}
            assert settings.session_cookie_name not in resp.cookies
        finally:
            await interloper.execute(delete(User).where(User.email == email))
            await interloper.commit()


async def test_me_reports_google_only_account_without_password(
    db_client: httpx.AsyncClient,
) -> None:
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200

    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json()["hasPassword"] is False
    assert me.json()["socialProvider"] == "google"


async def test_me_reports_password_account_linked_to_google_as_both(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """한 계정이 비밀번호와 구글을 함께 가질 수 있어(이메일 자동 연동) 두 필드가 따로 있다."""
    user = _make_user(password_hash=await hash_password("password123"), google_sub=f"g-{uuid.uuid4()}")
    db_session.add(user)
    await db_session.flush()

    await _login_as(db_client, user.id)
    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json()["hasPassword"] is True
    assert me.json()["socialProvider"] == "google"


async def test_change_password_on_google_only_account_returns_password_not_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소셜 전용 계정은 "현재 비밀번호가 틀렸다"가 아니라 비밀번호가 없다는 사실을 따로 알려야
    프런트가 엉뚱한 안내를 하지 않는다."""
    ctx = await _onboard_new_google_user(db_client, "2000-01-01")
    onboard_resp = await db_client.post("/auth/onboarding/google", json=ctx["payload"])
    assert onboard_resp.status_code == 200

    resp = await db_client.patch(
        "/me/password", json={"currentPassword": "anything1", "newPassword": "newpassword456"}
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": {"code": "PASSWORD_NOT_SET"}}
    user = await db_session.scalar(select(User).where(User.email == ctx["email"]))
    assert user is not None
    assert user.password_hash is None


# redirect 는 콜백에서 frontend_base_url 뒤에 그대로 이어 붙으므로
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
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
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

    # 브라우저 쿠키 대조는 통과시키고(같은 값을 쿠키로 심는다) Redis 에서 꺼낸 값의 재검증만 본다.
    state = f"pre-fix-{uuid.uuid4()}"
    await redis_client.set(_state_key(state), "@evil.com", ex=60)
    db_client.cookies.set(_STATE_COOKIE, state)
    _override_google_profile(str(ctx["sub"]), str(ctx["email"]))
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_google_profile_override()

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/"
