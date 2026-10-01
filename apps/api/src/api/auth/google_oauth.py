import json
import secrets
from collections.abc import Awaitable, Callable
from typing import TypedDict
from urllib.parse import urlencode

import httpx

from api.auth.oauth_common import OAuthExchangeError
from api.core.config import settings
from api.core.redis import redis_client

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleProfile(TypedDict):
    sub: str
    email: str


def callback_redirect_uri() -> str:
    return f"{settings.api_base_url}/auth/google/callback"


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": callback_redirect_uri(),
        "response_type": "code",
        "scope": "openid email",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_profile(code: str) -> GoogleProfile:
    """실패는 전부 `OAuthExchangeError` 로 바꿔 던진다 — 비정상 상태코드뿐 아니라 네트워크
    오류·타임아웃(`httpx.HTTPError`)과 응답 형식 오류(JSON 아님·키 누락)도 콜백이 잡을 수 있어야
    브라우저에 500 화면이 뜨지 않는다."""
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": callback_redirect_uri(),
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                raise OAuthExchangeError(f"token exchange returned {token_resp.status_code}")
            access_token = token_resp.json()["access_token"]

            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            if userinfo_resp.status_code != 200:
                raise OAuthExchangeError(f"userinfo returned {userinfo_resp.status_code}")
            data = userinfo_resp.json()
            return GoogleProfile(sub=data["sub"], email=data["email"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # ValueError 는 JSON 이 아닌 본문, KeyError·TypeError 는 기대한 키가 없거나 모양이 다른
        # 본문이다. 예외 이름만 남긴다 — 메시지에 응답 본문이 섞일 수 있다.
        raise OAuthExchangeError(type(exc).__name__) from exc


GoogleProfileFetcher = Callable[[str], Awaitable[GoogleProfile]]


def get_google_profile_fetcher() -> GoogleProfileFetcher:
    """토큰 교환 호출을 Depends 로 주입해 테스트가 네트워크 없이 갈아끼우게 한다
    (`core/email.py` 의 `get_email_sender` 와 같은 모양). 프로필 자체가 아니라 호출 함수를 주입하는
    이유는 콜백이 state 대조와 취소 판정을 끝낸 **뒤에** 교환을 부르고 그 실패를 직접 잡아
    로그인 화면으로 되돌려야 하기 때문이다 — 프로필을 의존성으로 받으면 그 실패가 라우트 본문
    밖에서 터진다."""
    return exchange_code_for_profile


def _state_key(state: str) -> str:
    return f"google_oauth_state:{state}"


async def store_oauth_state(redirect_target: str) -> str:
    state = secrets.token_urlsafe(16)
    await redis_client.set(_state_key(state), redirect_target, ex=settings.google_oauth_state_ttl_seconds)
    return state


async def consume_oauth_state(state: str) -> str | None:
    key = _state_key(state)
    redirect_target = await redis_client.get(key)
    if redirect_target is None:
        return None
    await redis_client.delete(key)
    return str(redirect_target)


class PendingGoogleSignup(TypedDict):
    sub: str
    email: str


def _pending_signup_key(token: str) -> str:
    return f"google_pending_signup:{token}"


async def store_pending_google_signup(profile: GoogleProfile) -> str:
    token = secrets.token_urlsafe(24)
    payload: PendingGoogleSignup = {"sub": profile["sub"], "email": profile["email"]}
    await redis_client.set(
        _pending_signup_key(token), json.dumps(payload), ex=settings.google_pending_signup_ttl_seconds
    )
    return token


async def get_pending_google_signup(token: str) -> PendingGoogleSignup | None:
    raw = await redis_client.get(_pending_signup_key(token))
    if raw is None:
        return None
    data: PendingGoogleSignup = json.loads(raw)
    return data


async def delete_pending_google_signup(token: str) -> None:
    await redis_client.delete(_pending_signup_key(token))
