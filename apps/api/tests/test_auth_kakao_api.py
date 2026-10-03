import asyncio
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime

import boto3
import httpx
import pytest
from botocore.exceptions import ClientError
import sqlalchemy as sa
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.google_oauth import GoogleProfile, get_google_profile_fetcher
from api.auth.kakao_oauth import (
    KAKAO_AUTH_URL,
    KakaoPendingSignup,
    KakaoProfile,
    KakaoProfileFetcher,
    KakaoUnlinkError,
    _pending_signup_key,
    _state_key,
    exchange_code_for_profile,
    get_kakao_profile_fetcher,
    get_kakao_unlinker,
    get_pending_kakao_signup,
    store_pending_kakao_signup,
    unlink_kakao_user,
)
from api.auth import router as auth_router
from api.auth.oauth_common import OAuthExchangeError
from api.auth.verification import get_verification_code, store_verification_code
from api.auth.withdrawal import delete_storage_objects_later
from api.core.config import settings
from api.core.redis import redis_client
from api.core.s3 import build_variant_keys
from api.core.security import hash_password, hash_withdrawn_email
from api.db.models.auth import User, WithdrawnEmail
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.session import engine
from api.legal.dependencies import _latest_published_legal_version
from api.main import app
from api.session.store import create_session, get_session
from factories import _login_as, _make_user, _patch_httpx, _wait_until_lock_wait

_STATE_COOKIE = "oauth_state_kakao"
_PENDING_COOKIE = "oauth_pending_kakao"
_ADMIN_KEY = "test-kakao-admin-key"
_ONBOARDING_FORM = {
    "nickname": "카카오유저",
    "birthDate": "2000-01-01",
    "termsAgreed": True,
    "privacyAgreed": True,
    "transferAgreed": True,
}


@pytest.fixture(autouse=True)
def _kakao_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬 `.env` 에는 실제 카카오 키가 있고 CI 에는 없다. 키 유무로 갈리는 분기를 환경이 아니라
    테스트가 정하도록 매번 명시한다(키가 없는 경우를 보는 테스트는 다시 덮어쓴다)."""
    monkeypatch.setattr(settings, "kakao_rest_api_key", "test-rest-api-key")
    monkeypatch.setattr(settings, "kakao_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "kakao_admin_key", _ADMIN_KEY)


@pytest.fixture(autouse=True)
def _recorded_unlinks() -> Iterator[list[str]]:
    """실제 카카오 연결 끊기 API 를 부르지 않게 늘 기록용으로 갈아끼운다."""
    calls: list[str] = []

    async def record(kakao_id: str) -> None:
        calls.append(kakao_id)

    app.dependency_overrides[get_kakao_unlinker] = lambda: record
    yield calls
    app.dependency_overrides.pop(get_kakao_unlinker, None)


def _override_fetcher(fetch: KakaoProfileFetcher) -> None:
    app.dependency_overrides[get_kakao_profile_fetcher] = lambda: fetch


def _override_kakao_profile(kakao_id: str, email: str) -> None:
    async def fetch(code: str) -> KakaoProfile:
        return KakaoProfile(kakao_id=kakao_id, email=email)

    _override_fetcher(fetch)


def _clear_fetcher_override() -> None:
    app.dependency_overrides.pop(get_kakao_profile_fetcher, None)


async def _fail_if_called(code: str) -> KakaoProfile:
    raise AssertionError("토큰 교환이 호출되면 안 되는 경로다")


def _set_cookie_headers(resp: httpx.Response, name: str) -> list[str]:
    return [h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{name}=")]


def _login_error(code: str) -> str:
    return f"{settings.frontend_base_url}/login?error={code}"


async def _start_kakao_login(db_client: httpx.AsyncClient, redirect: str = "/") -> str:
    start = await db_client.get("/auth/kakao", params={"redirect": redirect}, follow_redirects=False)
    return httpx.URL(start.headers["location"]).params["state"]


async def _kakao_callback(
    db_client: httpx.AsyncClient, kakao_id: str, email: str, *, redirect: str = "/"
) -> httpx.Response:
    state = await _start_kakao_login(db_client, redirect)
    _override_kakao_profile(kakao_id, email)
    try:
        return await db_client.get(
            "/auth/kakao/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_fetcher_override()


def _new_identity() -> tuple[str, str]:
    return str(uuid.uuid4().int % 10**12), f"kakao-{uuid.uuid4()}@example.com"


def _kakao_api(
    user_me: httpx.Response, *, token: httpx.Response | None = None, seen: list[httpx.Request] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.host == "kauth.kakao.com":
            return token if token is not None else httpx.Response(200, json={"access_token": "at"})
        return user_me

    return handler


def _user_me(**account: object) -> httpx.Response:
    base: dict[str, object] = {
        "has_email": True,
        "email_needs_agreement": False,
        "is_email_valid": True,
        "is_email_verified": True,
        "email": "kakao@example.com",
    }
    base.update(account)
    return httpx.Response(
        200, json={"id": 1234567890, "connected_at": "2026-10-01T00:00:00Z", "kakao_account": base}
    )


def _unusable_email_user_me_cases() -> list[object]:
    """카카오가 인증된 이메일을 주지 않는 `/v2/user/me` 응답들. 회원번호는 모두 1234567890 이다.
    응답 객체를 테스트마다 새로 만들도록 함수로 둔다."""
    return [
        pytest.param(_user_me(has_email=False, email=None), id="no-email"),
        pytest.param(
            httpx.Response(200, json={"id": 1234567890, "kakao_account": {"has_email": False}}),
            id="email-field-absent",
        ),
        pytest.param(httpx.Response(200, json={"id": 1234567890}), id="no-kakao-account"),
        pytest.param(_user_me(is_email_verified=False), id="unverified"),
        pytest.param(_user_me(is_email_valid=False), id="invalid"),
    ]


# --- 로그인 시작 ---


@pytest.mark.parametrize(
    "missing", [pytest.param("kakao_rest_api_key", id="rest-key"), pytest.param("kakao_client_secret", id="secret")]
)
async def test_kakao_login_without_keys_returns_to_login(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """키가 없는 환경에서 카카오로 보내면 카카오 오류 화면이라는 막다른 곳에 닿는다."""
    monkeypatch.setattr(settings, missing, "")
    resp = await db_client.get("/auth/kakao", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == _login_error("kakao_failed")
    assert not [h for h in _set_cookie_headers(resp, _STATE_COOKIE) if "max-age=0" not in h.lower()]


async def test_kakao_login_redirects_to_kakao_and_binds_state_cookie(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    resp = await db_client.get("/auth/kakao", params={"redirect": "@evil.com"}, follow_redirects=False)
    assert resp.status_code == 302
    location = httpx.URL(resp.headers["location"])
    assert str(location).startswith(f"{KAKAO_AUTH_URL}?")
    params = location.params
    assert params["client_id"] == "test-rest-api-key"
    assert params["redirect_uri"] == f"{settings.api_base_url}/auth/kakao/callback"
    assert params["response_type"] == "code"
    assert params["scope"] == "account_email"
    assert "code_challenge" not in params
    state = params["state"]
    # 돌아갈 경로는 저장 전에 같은 오리진 경로로 걸러진다.
    assert await redis_client.get(_state_key(state)) == "/"

    [header] = _set_cookie_headers(resp, _STATE_COOKIE)
    assert header.startswith(f"{_STATE_COOKIE}={state};")
    attrs = {part.strip().lower() for part in header.split(";")[1:]}
    assert {"httponly", "path=/", "samesite=lax", "secure"} <= attrs
    assert f"max-age={settings.kakao_oauth_state_ttl_seconds}" in attrs


# --- 콜백: state·취소·교환 실패·이메일 ---


async def test_kakao_callback_rejects_state_without_browser_cookie(db_client: httpx.AsyncClient) -> None:
    state = await _start_kakao_login(db_client)
    db_client.cookies.clear()
    _override_fetcher(_fail_if_called)
    try:
        resp = await db_client.get(
            "/auth/kakao/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_fetcher_override()
    assert resp.status_code == 302
    assert resp.headers["location"] == _login_error("kakao_state")
    assert settings.session_cookie_name not in resp.cookies


async def test_kakao_callback_rejects_state_that_does_not_match_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    first = await _start_kakao_login(db_client)
    await _start_kakao_login(db_client)
    _override_fetcher(_fail_if_called)
    try:
        resp = await db_client.get(
            "/auth/kakao/callback", params={"state": first, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_fetcher_override()
    assert resp.headers["location"] == _login_error("kakao_state")
    assert await redis_client.get(_state_key(first)) is not None


async def test_kakao_callback_rejects_google_state_cookie(db_client: httpx.AsyncClient) -> None:
    """provider 마다 쿠키가 따로라 구글 로그인으로 시작한 state 로는 카카오 콜백을 통과하지 못한다."""
    start = await db_client.get("/auth/google", follow_redirects=False)
    google_state = httpx.URL(start.headers["location"]).params["state"]
    resp = await db_client.get(
        "/auth/kakao/callback", params={"state": google_state, "code": "c"}, follow_redirects=False
    )
    assert resp.headers["location"] == _login_error("kakao_state")


async def test_kakao_callback_cancelled_consumes_state_and_clears_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    state = await _start_kakao_login(db_client)
    _override_fetcher(_fail_if_called)
    try:
        resp = await db_client.get(
            "/auth/kakao/callback",
            params={"state": state, "error": "access_denied"},
            follow_redirects=False,
        )
        no_code = await db_client.get(
            "/auth/kakao/callback",
            params={"state": await _start_kakao_login(db_client)},
            follow_redirects=False,
        )
    finally:
        _clear_fetcher_override()
    assert resp.status_code == 302
    assert resp.headers["location"] == _login_error("kakao_cancelled")
    assert await redis_client.get(_state_key(state)) is None
    [cleared] = _set_cookie_headers(resp, _STATE_COOKIE)
    assert "max-age=0" in cleared.lower()
    assert no_code.headers["location"] == _login_error("kakao_cancelled")


async def test_kakao_callback_exchange_failure_returns_to_login(db_client: httpx.AsyncClient) -> None:
    async def failing(code: str) -> KakaoProfile:
        raise OAuthExchangeError("token exchange returned 401")

    state = await _start_kakao_login(db_client)
    _override_fetcher(failing)
    try:
        resp = await db_client.get(
            "/auth/kakao/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        _clear_fetcher_override()
    assert resp.headers["location"] == _login_error("kakao_failed")
    assert settings.session_cookie_name not in resp.cookies
    [cleared] = _set_cookie_headers(resp, _STATE_COOKIE)
    assert "max-age=0" in cleared.lower()


async def _kakao_callback_via_api(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, user_me: httpx.Response
) -> httpx.Response:
    """프로필 교환을 갈아끼우지 않고 카카오 API 응답만 흉내 내 콜백을 끝까지 탄다."""
    state = await _start_kakao_login(db_client)
    _patch_httpx(monkeypatch, _kakao_api(user_me), module="api.auth.kakao_oauth")
    return await db_client.get(
        "/auth/kakao/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )


@pytest.mark.parametrize("user_me", _unusable_email_user_me_cases())
async def test_kakao_callback_new_member_without_verified_email_asks_for_email(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, user_me: httpx.Response
) -> None:
    resp = await _kakao_callback_via_api(db_client, monkeypatch, user_me)
    assert resp.headers["location"] == _login_error("kakao_email_required")
    assert settings.session_cookie_name not in resp.cookies
    assert not _set_cookie_headers(resp, _PENDING_COOKIE)


# --- 콜백: 기존 회원 ---


@pytest.mark.parametrize("user_me", _unusable_email_user_me_cases())
async def test_kakao_callback_existing_member_logs_in_without_verified_email(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    user_me: httpx.Response,
) -> None:
    """가입 뒤 카카오계정 이메일이 무효가 되거나 이메일 제공 동의를 철회해도 회원번호로 찾은 기존
    회원은 로그인된다 — 이메일 조건은 가입할 때만 따진다."""
    db_session.add(
        _make_user(
            kakao_id="1234567890",
            email=f"kakao-{uuid.uuid4()}@example.com",
            email_verified_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    resp = await _kakao_callback_via_api(db_client, monkeypatch, user_me)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/"
    assert settings.session_cookie_name in resp.cookies
    assert not _set_cookie_headers(resp, _PENDING_COOKIE)


async def test_kakao_callback_existing_member_issues_session_and_redirects(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email, email_verified_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()

    # 카카오에서 이메일을 바꿨어도 회원번호로 찾는다.
    resp = await _kakao_callback(db_client, kakao_id, f"changed-{email}", redirect="/mypage")
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/mypage"
    assert settings.session_cookie_name in resp.cookies
    assert not _set_cookie_headers(resp, _PENDING_COOKIE)


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        pytest.param({"suspended_at": datetime.now(UTC)}, "account_suspended", id="suspended"),
        pytest.param(
            {"deleted_at": datetime.now(UTC), "birth_date": None, "nickname": None},
            "account_deleted",
            id="deleted",
        ),
        pytest.param(
            {"birth_date": date.today().replace(year=date.today().year - 13)},
            "account_age_restricted",
            id="minor",
        ),
    ],
)
async def test_kakao_callback_rejects_blocked_existing_member(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    overrides: dict[str, object],
    error_code: str,
) -> None:
    kakao_id, email = _new_identity()
    db_session.add(_make_user(kakao_id=kakao_id, email=email, **overrides))
    await db_session.flush()

    resp = await _kakao_callback(db_client, kakao_id, email)
    assert resp.headers["location"] == _login_error(error_code)
    assert settings.session_cookie_name not in resp.cookies


# --- 콜백: 같은 이메일의 다른 계정 ---


@pytest.mark.parametrize(
    ("overrides", "method"),
    [
        pytest.param(
            {"password_hash": "x", "email_verified_at": datetime.now(UTC)}, "email", id="verified-email"
        ),
        pytest.param({"google_sub": "g"}, "google", id="google"),
        pytest.param({"google_sub": "g", "password_hash": "x"}, "google", id="google-with-password"),
        pytest.param({"kakao_id": "other-kakao"}, "kakao", id="other-kakao-account"),
        pytest.param(
            {"password_hash": "x", "suspended_at": datetime.now(UTC)}, "email", id="suspended-unverified"
        ),
    ],
)
async def test_kakao_callback_refuses_email_taken_by_other_account(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    overrides: dict[str, object],
    method: str,
) -> None:
    """같은 이메일의 계정에 카카오를 자동으로 붙이지 않는다 — 이메일 재활용·미인증 이메일로 남의
    계정에 들어가는 경로를 없앤다. 원래 가입 수단을 안내할 수 있게 method 를 싣는다."""
    kakao_id, email = _new_identity()
    if "google_sub" in overrides:
        overrides = {**overrides, "google_sub": f"google-sub-{uuid.uuid4()}"}
    if "kakao_id" in overrides:
        overrides = {**overrides, "kakao_id": f"other-{uuid.uuid4()}"}
    user = _make_user(email=email, **overrides)
    db_session.add(user)
    await db_session.flush()
    before_kakao_id = user.kakao_id

    resp = await _kakao_callback(db_client, kakao_id, email)
    assert resp.status_code == 302
    assert resp.headers["location"] == (
        f"{settings.frontend_base_url}/login?error=kakao_email_taken&method={method}"
    )
    assert settings.session_cookie_name not in resp.cookies
    assert not _set_cookie_headers(resp, _PENDING_COOKIE)
    await db_session.refresh(user)
    assert user.kakao_id == before_kakao_id


# --- 신규 가입 ---


async def test_kakao_callback_new_member_redirects_to_onboarding_with_pending_cookie(
    db_client: httpx.AsyncClient,
) -> None:
    kakao_id, email = _new_identity()
    resp = await _kakao_callback(db_client, kakao_id, email)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.frontend_base_url}/onboarding/kakao"
    assert settings.session_cookie_name not in resp.cookies
    [pending] = _set_cookie_headers(resp, _PENDING_COOKIE)
    attrs = {part.strip().lower() for part in pending.split(";")[1:]}
    assert {"httponly", "path=/", "samesite=lax"} <= attrs
    assert f"max-age={settings.kakao_pending_signup_ttl_seconds}" in attrs
    assert await get_pending_kakao_signup(resp.cookies[_PENDING_COOKIE]) == {
        "kakao_id": kakao_id,
        "email": email,
    }
    [cleared] = _set_cookie_headers(resp, _STATE_COOKIE)
    assert "max-age=0" in cleared.lower()


async def test_onboarding_kakao_creates_verified_member_and_issues_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    kakao_id, email = _new_identity()
    await _kakao_callback(db_client, kakao_id, email)
    token = db_client.cookies[_PENDING_COOKIE]

    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 200
    assert resp.json() == {"email": email}
    assert settings.session_cookie_name in resp.cookies
    [cleared] = _set_cookie_headers(resp, _PENDING_COOKIE)
    assert "max-age=0" in cleared.lower()
    assert await get_pending_kakao_signup(token) is None

    user = await db_session.scalar(select(User).where(User.kakao_id == kakao_id))
    assert user is not None
    assert user.email == email
    assert user.password_hash is None
    assert user.google_sub is None
    assert user.email_verified_at is not None
    assert user.nickname == "카카오유저"
    assert user.birth_date == date(2000, 1, 1)
    privacy_version = await _latest_published_legal_version(db_session, "privacy")
    assert user.terms_version == await _latest_published_legal_version(db_session, "terms")
    assert user.privacy_version == privacy_version
    assert user.transfer_version == privacy_version
    assert user.transfer_agreed_at is not None

    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)
    assert me.json()["hasPassword"] is False
    assert me.json()["socialProvider"] == "kakao"


async def test_onboarding_kakao_without_pending_cookie_returns_400(db_client: httpx.AsyncClient) -> None:
    kakao_id, email = _new_identity()
    token = await store_pending_kakao_signup(KakaoPendingSignup(kakao_id=kakao_id, email=email))
    resp = await db_client.post("/auth/onboarding/kakao", json={**_ONBOARDING_FORM, "token": token})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid or expired token"}
    assert await get_pending_kakao_signup(token) is not None


async def test_onboarding_kakao_rejects_expired_pending_cookie(db_client: httpx.AsyncClient) -> None:
    kakao_id, email = _new_identity()
    await _kakao_callback(db_client, kakao_id, email)
    await redis_client.delete(_pending_signup_key(db_client.cookies[_PENDING_COOKIE]))
    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 400


async def test_onboarding_kakao_rejects_under_minimum_age(db_client: httpx.AsyncClient) -> None:
    kakao_id, email = _new_identity()
    await _kakao_callback(db_client, kakao_id, email)
    minor = date.today().replace(year=date.today().year - 13).isoformat()
    resp = await db_client.post("/auth/onboarding/kakao", json={**_ONBOARDING_FORM, "birthDate": minor})
    assert resp.status_code == 422


async def test_onboarding_kakao_existing_member_resubmit_updates_profile(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 가입 대기를 두 탭에서 낸 경우처럼 회원번호의 행이 이미 있으면 새로 만들지 않는다."""
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email, nickname="원래")
    db_session.add(user)
    await db_session.flush()
    db_client.cookies.set(
        _PENDING_COOKIE, await store_pending_kakao_signup(KakaoPendingSignup(kakao_id=kakao_id, email=email))
    )

    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.nickname == "카카오유저"


async def test_onboarding_kakao_suspended_existing_member_is_rejected_without_side_effects(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email, nickname="원래", suspended_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    token = await store_pending_kakao_signup(KakaoPendingSignup(kakao_id=kakao_id, email=email))
    db_client.cookies.set(_PENDING_COOKIE, token)

    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 403
    assert settings.session_cookie_name not in resp.cookies
    await db_session.refresh(user)
    assert user.nickname == "원래"
    assert await get_pending_kakao_signup(token) is not None


# --- 미인증 이메일 가입 행 대체 ---


async def _unverified_email_signup(db_client: httpx.AsyncClient, email: str) -> None:
    resp = await db_client.post(
        "/auth/signup",
        json={**_ONBOARDING_FORM, "email": email, "password": "password123", "nickname": "미인증"},
    )
    assert resp.status_code == 201


async def test_kakao_replaces_unverified_email_signup_with_same_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이메일 가입을 마치지 않은(인증 전) 행은 로그인할 수 없는 기록이라 카카오 가입을 막지 않는다.
    카카오가 인증한 이메일이므로 그 행을 이 사람의 카카오 계정으로 대체하고, 앞서 걸린 비밀번호는
    지운다 — 남이 그 이메일로 미인증 가입을 해 둔 경우 그 비밀번호로 들어올 수 없어야 한다."""
    kakao_id, email = _new_identity()
    await _unverified_email_signup(db_client, email)
    original = await db_session.scalar(select(User).where(User.email == email))
    assert original is not None
    original_id = original.id
    assert await get_verification_code(email) is not None

    callback = await _kakao_callback(db_client, kakao_id, email)
    assert callback.headers["location"] == f"{settings.frontend_base_url}/onboarding/kakao"

    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 200
    assert settings.session_cookie_name in resp.cookies

    db_session.expire_all()
    users = (await db_session.scalars(select(User).where(User.email == email))).all()
    assert [u.id for u in users] == [original_id]
    [user] = users
    assert user.kakao_id == kakao_id
    assert user.password_hash is None
    assert user.email_verified_at is not None
    assert user.nickname == "카카오유저"
    # 대체된 이메일 가입의 인증 코드로 나중에 그 행을 건드리지 못하게 지운다.
    assert await get_verification_code(email) is None

    login = await db_client.post("/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 401


async def test_onboarding_kakao_refuses_replacement_when_row_was_verified_meanwhile(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """콜백 뒤 온보딩 전에 그 이메일 가입이 인증을 마치면 더는 방치된 기록이 아니다."""
    kakao_id, email = _new_identity()
    await _unverified_email_signup(db_client, email)
    await _kakao_callback(db_client, kakao_id, email)
    token = db_client.cookies[_PENDING_COOKIE]

    row = await db_session.scalar(select(User).where(User.email == email))
    assert row is not None
    row.email_verified_at = datetime.now(UTC)
    await db_session.flush()

    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 409
    assert resp.json() == {"detail": {"code": "EMAIL_ALREADY_REGISTERED"}}
    assert settings.session_cookie_name not in resp.cookies
    await db_session.refresh(row)
    assert row.kakao_id is None
    assert row.password_hash is not None
    assert row.nickname == "미인증"
    assert await get_pending_kakao_signup(token) is not None


async def test_onboarding_kakao_refuses_email_taken_after_callback(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    kakao_id, email = _new_identity()
    await _kakao_callback(db_client, kakao_id, email)
    db_session.add(_make_user(email=email, google_sub=f"google-sub-{uuid.uuid4()}"))
    await db_session.flush()

    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 409
    assert resp.json() == {"detail": {"code": "EMAIL_ALREADY_REGISTERED"}}


async def test_onboarding_kakao_concurrent_same_kakao_account_returns_409(
    db_client: httpx.AsyncClient,
) -> None:
    """같은 카카오 계정의 가입이 다른 커넥션에서 먼저 커밋되면 회원번호 UNIQUE 에 걸린다 — 500 이
    아니라 409 여야 한다. 별개 커넥션이 같은 회원번호를 미커밋으로 넣고, 온보딩 INSERT 가 그 잠금을
    기다리는 것을 관측한 뒤 커밋해 진짜 경합을 만든다."""
    kakao_id, email = _new_identity()
    await _kakao_callback(db_client, kakao_id, email)

    async with engine.connect() as interloper:
        await interloper.execute(
            insert(User).values(
                id=uuid.uuid4(),
                email=f"other-{email}",
                kakao_id=kakao_id,
                nickname="선점",
                birth_date=date(2000, 1, 1),
                terms_agreed_at=datetime.now(UTC),
                privacy_agreed_at=datetime.now(UTC),
            )
        )
        task = asyncio.create_task(db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM))
        try:
            await _wait_until_lock_wait(interloper, seconds=5.0)
            await interloper.commit()
            resp = await task

            assert resp.status_code == 409
            assert resp.json() == {"detail": {"code": "EMAIL_ALREADY_REGISTERED"}}
            assert settings.session_cookie_name not in resp.cookies
        finally:
            await interloper.execute(delete(User).where(User.kakao_id == kakao_id))
            await interloper.commit()


async def test_onboarding_kakao_replacement_concurrent_same_kakao_account_returns_409(
    db_client: httpx.AsyncClient,
) -> None:
    """미인증 행을 대체하는 경로도 회원번호 UNIQUE 충돌을 409 로 내야 한다. 대체는 기존 행의 UPDATE
    라, 회원번호를 대입한 뒤 동의 버전 조회가 자동 flush 를 일으키면 그 UPDATE 가 충돌을 409 로
    바꾸는 savepoint 밖에서 나가 500 이 된다. 별개 커넥션이 같은 회원번호를 미커밋으로 넣어 두고,
    대체 UPDATE 가 그 잠금을 기다리는 것을 관측한 뒤 커밋해 진짜 경합을 만든다."""
    kakao_id, email = _new_identity()
    await _unverified_email_signup(db_client, email)
    await _kakao_callback(db_client, kakao_id, email)

    async with engine.connect() as interloper:
        await interloper.execute(
            insert(User).values(
                id=uuid.uuid4(),
                email=f"other-{email}",
                kakao_id=kakao_id,
                nickname="선점",
                birth_date=date(2000, 1, 1),
                terms_agreed_at=datetime.now(UTC),
                privacy_agreed_at=datetime.now(UTC),
            )
        )
        task = asyncio.create_task(db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM))
        try:
            await _wait_until_lock_wait(interloper, seconds=5.0)
            await interloper.commit()
            resp = await task

            assert resp.status_code == 409
            assert resp.json() == {"detail": {"code": "EMAIL_ALREADY_REGISTERED"}}
            assert settings.session_cookie_name not in resp.cookies
        finally:
            await interloper.execute(delete(User).where(User.kakao_id == kakao_id))
            await interloper.commit()


async def test_onboarding_kakao_blocks_reregistration_after_withdrawal(
    db_client: httpx.AsyncClient, _recorded_unlinks: list[str]
) -> None:
    kakao_id, email = _new_identity()
    await _kakao_callback(db_client, kakao_id, email)
    assert (await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)).status_code == 200

    assert (await db_client.delete("/me")).status_code == 204

    # 탈퇴로 회원번호가 지워져 기존 회원이 아니라 신규 가입으로 돌아온다(지워지지 않았다면
    # account_deleted 로 영구히 막힌다).
    callback = await _kakao_callback(db_client, kakao_id, email)
    assert callback.headers["location"] == f"{settings.frontend_base_url}/onboarding/kakao"
    resp = await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)
    assert resp.status_code == 409
    assert resp.json() == {"detail": {"code": "REREGISTRATION_BLOCKED"}}


# --- 다른 가입 경로의 대칭 ---


async def test_google_callback_refuses_email_of_kakao_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email, email_verified_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()

    async def fetch(code: str) -> GoogleProfile:
        return GoogleProfile(sub=f"google-sub-{uuid.uuid4()}", email=email)

    start = await db_client.get("/auth/google", follow_redirects=False)
    state = httpx.URL(start.headers["location"]).params["state"]
    app.dependency_overrides[get_google_profile_fetcher] = lambda: fetch
    try:
        resp = await db_client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
    finally:
        del app.dependency_overrides[get_google_profile_fetcher]

    assert resp.status_code == 302
    assert resp.headers["location"] == (
        f"{settings.frontend_base_url}/login?error=google_email_taken&method=kakao"
    )
    assert settings.session_cookie_name not in resp.cookies
    await db_session.refresh(user)
    assert user.google_sub is None


async def test_google_callback_waits_for_concurrent_kakao_replacement_and_refuses(
    api_client: httpx.AsyncClient,
) -> None:
    """구글 콜백이 이메일로 찾은 행에 구글을 붙이는 사이 카카오 온보딩이 같은 미인증 행을 카카오
    계정으로 대체하면, 잠그지 않은 콜백은 대체 전의 행을 보고 구글을 붙여 한 행이 두 provider 를
    갖게 된다. 콜백은 그 행을 잠가 대체의 커밋을 기다린 뒤 바뀐 행으로 다시 판정해야 한다.

    양쪽 커넥션이 같은 행을 봐야 하므로 이 테스트는 롤백되는 테스트 트랜잭션이 아니라 실제로 커밋되는
    앱 세션(`api_client`)을 쓰고, 만든 행은 끝에 지운다. 별개 커넥션이 카카오 대체를 흉내 내 그 행을
    미커밋으로 고쳐 두고, 콜백이 그 잠금에 막힌 것을 관측한 뒤 커밋한다."""
    kakao_id, email = _new_identity()
    user_id = uuid.uuid4()
    async with engine.connect() as setup:
        await setup.execute(
            insert(User).values(
                id=user_id,
                email=email,
                password_hash=hash_password("password123"),
                nickname="미인증",
                birth_date=date(2000, 1, 1),
                terms_agreed_at=datetime.now(UTC),
                privacy_agreed_at=datetime.now(UTC),
            )
        )
        await setup.commit()

    api_client.cookies.clear()
    async with engine.connect() as interloper:
        try:
            start = await api_client.get("/auth/google", follow_redirects=False)
            state = httpx.URL(start.headers["location"]).params["state"]

            interloper_pid = await interloper.scalar(sa.text("SELECT pg_backend_pid()"))
            await interloper.execute(
                update(User)
                .where(User.id == user_id)
                .values(kakao_id=kakao_id, email_verified_at=datetime.now(UTC), password_hash=None)
            )

            async def fetch(code: str) -> GoogleProfile:
                return GoogleProfile(sub=f"google-sub-{uuid.uuid4()}", email=email)

            app.dependency_overrides[get_google_profile_fetcher] = lambda: fetch
            task = asyncio.create_task(
                api_client.get(
                    "/auth/google/callback",
                    params={"state": state, "code": "c"},
                    follow_redirects=False,
                )
            )
            # 콜백이 이 커넥션의 행 잠금에 막혀 기다리기 시작한 것을 관측한다. 공용 헬퍼
            # `_wait_until_lock_wait` 는 INSERT 대기(users 테이블 쓰기 잠금을 쥔 채 대기)만 보므로
            # 쓰기 잠금 없이 행 잠금을 기다리는 SELECT 대기는 잡지 못한다.
            async with asyncio.timeout(5.0):
                while True:
                    blocked = await interloper.scalar(
                        sa.text(
                            "SELECT count(*) FROM pg_locks"
                            " WHERE NOT granted AND :pid = ANY(pg_blocking_pids(pid))"
                        ),
                        {"pid": interloper_pid},
                    )
                    if blocked:
                        break
                    await asyncio.sleep(0.01)
            await interloper.commit()
            resp = await task

            assert resp.status_code == 302
            assert resp.headers["location"] == (
                f"{settings.frontend_base_url}/login?error=google_email_taken&method=kakao"
            )
            assert settings.session_cookie_name not in resp.cookies
            row = (await interloper.execute(select(User).where(User.id == user_id))).one()
            assert row.kakao_id == kakao_id
            assert row.google_sub is None
        finally:
            app.dependency_overrides.pop(get_google_profile_fetcher, None)
            api_client.cookies.clear()
            await interloper.rollback()
            await interloper.execute(delete(User).where(User.id == user_id))
            await interloper.commit()


async def test_signup_refuses_email_of_kakao_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """인증 시각이 비어 있는 예전 데이터라도 카카오 계정이면 이메일 가입이 덮어쓰지 않는다."""
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email)
    db_session.add(user)
    await db_session.flush()

    resp = await db_client.post(
        "/auth/signup", json={**_ONBOARDING_FORM, "email": email, "password": "password123"}
    )
    assert resp.status_code == 409
    await db_session.refresh(user)
    assert user.password_hash is None


async def test_me_reports_kakao_provider(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user(kakao_id=f"k-{uuid.uuid4()}", email_verified_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    me = await db_client.get("/me")
    assert me.json()["socialProvider"] == "kakao"
    assert me.json()["hasPassword"] is False


# --- 탈퇴와 연결 끊기 ---


async def test_withdraw_erases_kakao_id_and_unlinks_after_commit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, _recorded_unlinks: list[str]
) -> None:
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email)
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.delete("/me")
    assert resp.status_code == 204
    assert _recorded_unlinks == [kakao_id]
    await db_session.refresh(user)
    assert user.kakao_id is None
    assert user.deleted_at is not None


async def test_withdraw_of_non_kakao_member_does_not_unlink(
    db_client: httpx.AsyncClient, db_session: AsyncSession, _recorded_unlinks: list[str]
) -> None:
    user = _make_user(google_sub=f"google-sub-{uuid.uuid4()}")
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    assert (await db_client.delete("/me")).status_code == 204
    assert _recorded_unlinks == []


async def test_withdraw_succeeds_when_kakao_unlink_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴를 외부 API 에 인질로 잡지 않는다 — 연결 끊기가 실패해도 우리 쪽 파기는 끝난 것이다."""

    async def failing(kakao_id: str) -> None:
        raise KakaoUnlinkError("unlink returned 500")

    app.dependency_overrides[get_kakao_unlinker] = lambda: failing
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email)
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.delete("/me")
    assert resp.status_code == 204
    await db_session.refresh(user)
    assert user.kakao_id is None
    assert user.deleted_at is not None


async def test_get_kakao_unlinker_skips_without_admin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "kakao_admin_key", "")
    unlinker = get_kakao_unlinker()
    assert unlinker is not unlink_kakao_user
    await unlinker("123")  # 키가 없으면 호출하지 않고 경고만 남긴다(예외 없음).

    monkeypatch.setattr(settings, "kakao_admin_key", _ADMIN_KEY)
    assert get_kakao_unlinker() is unlink_kakao_user


async def test_unlink_kakao_user_sends_admin_key_and_target(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": 123})

    _patch_httpx(monkeypatch, handler, module="api.auth.kakao_oauth")
    await unlink_kakao_user("123")
    [request] = seen
    assert str(request.url) == "https://kapi.kakao.com/v1/user/unlink"
    assert request.headers["authorization"] == f"KakaoAK {_ADMIN_KEY}"
    assert httpx.QueryParams(request.content.decode()) == httpx.QueryParams(
        {"target_id_type": "user_id", "target_id": "123"}
    )


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda request: httpx.Response(401, json={}), id="non-200"),
        pytest.param(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("boom", request=request)),
            id="network-error",
        ),
    ],
)
async def test_unlink_kakao_user_normalizes_failures(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    _patch_httpx(monkeypatch, handler, module="api.auth.kakao_oauth")
    with pytest.raises(KakaoUnlinkError):
        await unlink_kakao_user("123")


# --- 토큰 교환·사용자 정보 파싱 ---


async def test_exchange_code_for_profile_returns_string_id_and_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []
    _patch_httpx(monkeypatch, _kakao_api(_user_me(), seen=seen), module="api.auth.kakao_oauth")

    assert await exchange_code_for_profile("the-code") == {
        "kakao_id": "1234567890",
        "email": "kakao@example.com",
    }
    token_request, me_request = seen
    assert str(token_request.url) == "https://kauth.kakao.com/oauth/token"
    form = httpx.QueryParams(token_request.content.decode())
    assert dict(form) == {
        "grant_type": "authorization_code",
        "client_id": "test-rest-api-key",
        "client_secret": "test-client-secret",
        "redirect_uri": f"{settings.api_base_url}/auth/kakao/callback",
        "code": "the-code",
    }
    assert str(me_request.url) == "https://kapi.kakao.com/v2/user/me"
    assert me_request.headers["authorization"] == "Bearer at"


@pytest.mark.parametrize("user_me", _unusable_email_user_me_cases())
async def test_exchange_code_for_profile_drops_unusable_email(
    monkeypatch: pytest.MonkeyPatch, user_me: httpx.Response
) -> None:
    _patch_httpx(monkeypatch, _kakao_api(user_me), module="api.auth.kakao_oauth")
    assert await exchange_code_for_profile("code") == {"kakao_id": "1234567890", "email": None}


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(_kakao_api(_user_me(), token=httpx.Response(400, json={})), id="token-4xx"),
        pytest.param(_kakao_api(_user_me(), token=httpx.Response(200, json={})), id="token-missing-key"),
        pytest.param(_kakao_api(httpx.Response(500)), id="user-me-5xx"),
        pytest.param(_kakao_api(httpx.Response(200, text="<html>")), id="user-me-not-json"),
        pytest.param(
            _kakao_api(httpx.Response(200, json={"kakao_account": {}})), id="user-me-missing-id"
        ),
        pytest.param(_kakao_api(httpx.Response(200, json=[1])), id="user-me-not-object"),
    ],
)
async def test_exchange_code_for_profile_normalizes_failures(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    _patch_httpx(monkeypatch, handler, module="api.auth.kakao_oauth")
    with pytest.raises(OAuthExchangeError):
        await exchange_code_for_profile("code")


# --- 연결 해제 웹훅 ---


def _webhook_headers(key: str = _ADMIN_KEY) -> dict[str, str]:
    return {"Authorization": f"KakaoAK {key}"}


async def _kakao_member(db_session: AsyncSession, **overrides: object) -> User:
    kakao_id, email = _new_identity()
    user = _make_user(kakao_id=kakao_id, email=email, **overrides)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(httpx.Headers(), id="no-header"),
        pytest.param(httpx.Headers(_webhook_headers("wrong-key")), id="wrong-key"),
        pytest.param(httpx.Headers({"Authorization": f"Bearer {_ADMIN_KEY}"}), id="wrong-scheme"),
        # 헤더 값은 비ASCII 바이트로도 올 수 있다 — 문자열 그대로 비교하면 TypeError 로 500 이 된다.
        pytest.param(httpx.Headers({b"Authorization": "KakaoAK é".encode("latin-1")}), id="non-ascii"),
    ],
)
async def test_kakao_unlink_webhook_rejects_unauthenticated(
    db_client: httpx.AsyncClient, db_session: AsyncSession, headers: httpx.Headers
) -> None:
    user = await _kakao_member(db_session)
    resp = await db_client.get(
        "/auth/kakao/unlink", params={"user_id": user.kakao_id}, headers=headers
    )
    assert resp.status_code == 401
    await db_session.refresh(user)
    assert user.deleted_at is None


async def test_kakao_unlink_webhook_rejects_everything_without_admin_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """키가 비어 있을 때 `KakaoAK ` 헤더가 빈 키와 일치해 통과하면 누구나 회원을 파기할 수 있다."""
    monkeypatch.setattr(settings, "kakao_admin_key", "")
    user = await _kakao_member(db_session)
    resp = await db_client.get(
        "/auth/kakao/unlink", params={"user_id": user.kakao_id}, headers={"Authorization": "KakaoAK "}
    )
    assert resp.status_code == 401
    await db_session.refresh(user)
    assert user.deleted_at is None


@pytest.mark.parametrize(
    "params", [pytest.param({}, id="no-user-id"), pytest.param({"user_id": "999999999999999"}, id="unknown")]
)
async def test_kakao_unlink_webhook_without_matching_member_is_noop_200(
    db_client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    resp = await db_client.get("/auth/kakao/unlink", params=params, headers=_webhook_headers())
    assert resp.status_code == 200


async def _assert_erased_by_webhook(db_session: AsyncSession, user: User, original_email: str) -> None:
    await db_session.refresh(user)
    assert user.deleted_at is not None
    assert user.kakao_id is None
    assert user.email == f"withdrawn:{user.id}"
    assert user.nickname is None
    withdrawn = await db_session.scalar(
        select(WithdrawnEmail).where(WithdrawnEmail.email_hmac == hash_withdrawn_email(original_email))
    )
    assert withdrawn is not None


async def test_kakao_unlink_webhook_get_erases_member_and_revokes_sessions(
    db_client: httpx.AsyncClient, db_session: AsyncSession, _recorded_unlinks: list[str]
) -> None:
    user = await _kakao_member(db_session)
    original_email = user.email
    session_id = await create_session(user.id)

    resp = await db_client.get(
        "/auth/kakao/unlink",
        params={"app_id": "1", "user_id": user.kakao_id, "referrer_type": "UNLINK_FROM_APPS"},
        headers=_webhook_headers(),
    )
    assert resp.status_code == 200
    await _assert_erased_by_webhook(db_session, user, original_email)
    assert await get_session(session_id) is None
    # 카카오 쪽에서 이미 끊긴 연결이라 다시 끊지 않는다.
    assert _recorded_unlinks == []


async def test_kakao_unlink_webhook_post_form_erases_member_and_deletes_storage_after_commit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """3초 안에 답해야 해서 오브젝트 스토리지 삭제는 키만 모아 커밋 뒤에 한다 — 그래도 결국 지워지는지 본다."""
    user = await _kakao_member(db_session)
    original_email = user.email
    storage_key = f"assets/generated/{uuid.uuid4()}.png"
    db_session.add(
        Asset(
            owner_user_id=user.id,
            storage_key=storage_key,
            kind=AssetKind.GENERATED,
            status=AssetStatus.READY,
        )
    )
    await db_session.flush()
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=b"img")
    for variant_key in build_variant_keys(storage_key):
        s3.put_object(Bucket=settings.s3_bucket_name, Key=variant_key, Body=b"variant")

    resp = await db_client.post(
        "/auth/kakao/unlink",
        content=f"app_id=1&user_id={user.kakao_id}&referrer_type=ACCOUNT_DELETE",
        headers={**_webhook_headers(), "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    await _assert_erased_by_webhook(db_session, user, original_email)
    assert await db_session.scalar(select(Asset).where(Asset.storage_key == storage_key)) is None
    listed = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=storage_key.rsplit(".", 1)[0])
    assert listed["KeyCount"] == 0


async def test_kakao_unlink_webhook_session_revoke_failure_still_returns_200_and_deletes_storage(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """파기는 세션 폐기 전에 이미 커밋됐고 카카오는 이 알림을 재전송하지 않는다. 세션 폐기(Redis)가
    실패해도 500 으로 응답하면 남는 것은 빠진 오브젝트 스토리지 삭제뿐이므로, 실패는 기록만 하고
    삭제 예약까지 마친 뒤 200 이어야 한다."""
    user = await _kakao_member(db_session)
    original_email = user.email
    storage_key = f"assets/generated/{uuid.uuid4()}.png"
    db_session.add(
        Asset(
            owner_user_id=user.id,
            storage_key=storage_key,
            kind=AssetKind.GENERATED,
            status=AssetStatus.READY,
        )
    )
    await db_session.flush()

    async def fail_revoke(user_id: uuid.UUID) -> None:
        raise ConnectionError("redis down")

    scheduled: list[list[str]] = []

    async def record_deletes(storage_keys: list[str]) -> None:
        scheduled.append(storage_keys)

    captured: list[str] = []
    monkeypatch.setattr(auth_router, "revoke_user_sessions", fail_revoke)
    monkeypatch.setattr(auth_router, "delete_storage_objects_later", record_deletes)
    monkeypatch.setattr(
        auth_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append(dependency),
    )

    resp = await db_client.get(
        "/auth/kakao/unlink", params={"user_id": user.kakao_id}, headers=_webhook_headers()
    )
    assert resp.status_code == 200
    await _assert_erased_by_webhook(db_session, user, original_email)
    assert scheduled == [[storage_key, *build_variant_keys(storage_key)]]
    assert captured == ["redis"]


async def test_kakao_unlink_webhook_post_json_body_is_accepted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _kakao_member(db_session)
    original_email = user.email
    resp = await db_client.post(
        "/auth/kakao/unlink", json={"user_id": user.kakao_id}, headers=_webhook_headers()
    )
    assert resp.status_code == 200
    await _assert_erased_by_webhook(db_session, user, original_email)


async def test_kakao_unlink_webhook_erases_suspended_member(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """카카오계정 삭제도 이 웹훅으로 온다. 정지 여부와 무관하게 개인정보를 남길 근거가 없다."""
    user = await _kakao_member(db_session, suspended_at=datetime.now(UTC))
    original_email = user.email
    resp = await db_client.get(
        "/auth/kakao/unlink", params={"user_id": user.kakao_id}, headers=_webhook_headers()
    )
    assert resp.status_code == 200
    await _assert_erased_by_webhook(db_session, user, original_email)


async def test_kakao_unlink_webhook_duplicate_delivery_is_idempotent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """첫 수신이 회원번호를 지우므로 같은 알림이 다시 와도 찾을 행이 없어 아무것도 하지 않는다."""
    user = await _kakao_member(db_session, password_hash=hash_password("password123"))
    kakao_id = user.kakao_id
    first = await db_client.get(
        "/auth/kakao/unlink", params={"user_id": kakao_id}, headers=_webhook_headers()
    )
    assert first.status_code == 200
    await db_session.refresh(user)
    deleted_at = user.deleted_at
    assert deleted_at is not None

    second = await db_client.post(
        "/auth/kakao/unlink", content=f"user_id={kakao_id}", headers=_webhook_headers()
    )
    assert second.status_code == 200
    await db_session.refresh(user)
    assert user.deleted_at == deleted_at


async def test_kakao_unlink_webhook_is_not_in_openapi() -> None:
    assert "/auth/kakao/unlink" not in app.openapi()["paths"]


async def test_email_signup_after_kakao_replacement_returns_409(
    db_client: httpx.AsyncClient,
) -> None:
    """대체 뒤 그 이메일로 다시 이메일 가입을 시도하면 이미 인증된 계정이라 409 다."""
    kakao_id, email = _new_identity()
    await store_verification_code(email, "123456", datetime.now(UTC))
    await _unverified_email_signup(db_client, email)
    await _kakao_callback(db_client, kakao_id, email)
    assert (await db_client.post("/auth/onboarding/kakao", json=_ONBOARDING_FORM)).status_code == 200

    again = await db_client.post(
        "/auth/signup", json={**_ONBOARDING_FORM, "email": email, "password": "password123"}
    )
    assert again.status_code == 409


async def test_delete_storage_objects_later_continues_after_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """응답 뒤라 재시도할 주체가 없다 — 한 키가 실패해도 나머지는 계속 지우고 예외를 밖으로 내지 않는다."""
    attempted: list[str] = []

    async def flaky(storage_key: str) -> None:
        attempted.append(storage_key)
        if storage_key == "first":
            raise ClientError({"Error": {"Code": "500", "Message": "boom"}}, "DeleteObject")

    monkeypatch.setattr("api.auth.withdrawal.delete_storage_object_now", flaky)
    await delete_storage_objects_later(["first", "second"])
    assert attempted == ["first", "second"]
