import json
import secrets
from typing import TypedDict
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Google OAuth token exchange failed"
            )
        access_token = token_resp.json()["access_token"]

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Google OAuth userinfo fetch failed"
            )
        data = userinfo_resp.json()
        return GoogleProfile(sub=data["sub"], email=data["email"])


async def get_google_profile(code: str) -> GoogleProfile:
    """FastAPI dependency wrapper so tests can override the network call
    (see `api/db/session.get_db_session`'s override for the established pattern)."""
    return await exchange_code_for_profile(code)


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
