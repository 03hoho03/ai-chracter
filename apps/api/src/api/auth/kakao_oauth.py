"""카카오 로그인의 provider 고유 부분 — 인가 URL·토큰 교환·사용자 정보 파싱·연결 끊기 호출과
Redis 의 state·가입 대기 키. 구글(`google_oauth.py`)과 모양이 같지만 키 접두와 TTL 설정이 달라
파라미터화하지 않고 모듈을 나눈다. 브라우저 쿠키·콜백 리다이렉트·세션 발급은
`oauth_common.py` 한 벌을 함께 쓴다.

PKCE 는 쓰지 않는다. 카카오는 `code_challenge` 를 받아 주지만, 그 뒤 틀린 `code_verifier` 로
토큰을 교환해도 토큰을 발급해 검증하지 않는 것을 실측했다(2026-10-01) — 보내도 보호가 생기지
않고 코드만 늘어난다. 인가 코드 탈취 방어는 필수인 클라이언트 시크릿과 브라우저에 묶인 state
쿠키가 맡는다.
"""

import json
import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from typing import TypedDict
from urllib.parse import urlencode

import httpx

from api.auth.oauth_common import OAuthExchangeError
from api.core.config import settings
from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure

logger = logging.getLogger(__name__)

KAKAO_AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USER_ME_URL = "https://kapi.kakao.com/v2/user/me"
KAKAO_UNLINK_URL = "https://kapi.kakao.com/v1/user/unlink"

# 이메일 발송(`core/email.py`)과 같은 이유로 짧게 잡는다 — 몇 KB 짜리 JSON 왕복이라 오래 걸릴
# 이유가 없고, 콜백은 사용자가 화면 앞에서 기다리는 요청이다.
_HTTP_TIMEOUT_SECONDS = 10.0


class KakaoProfile(TypedDict):
    """`/v2/user/me` 에서 읽은 값. `email` 은 카카오가 인증된 유효한 이메일을 줄 때만 있고 그 밖에는
    `None` 이다(미동의·미보유·미인증·무효). 이메일이 꼭 필요한지는 콜백이 회원 판정 뒤에 정한다."""

    kakao_id: str
    email: str | None


class KakaoPendingSignup(TypedDict):
    """온보딩을 기다리는 신규 가입. 가입에는 인증된 이메일이 필수라 `email` 이 늘 있다."""

    kakao_id: str
    email: str


def kakao_login_configured() -> bool:
    """REST API 키와 클라이언트 시크릿이 둘 다 있어야 카카오 로그인이 끝까지 간다(시크릿은 토큰
    교환에 필수다)."""
    return bool(settings.kakao_rest_api_key) and bool(settings.kakao_client_secret)


def callback_redirect_uri() -> str:
    return f"{settings.api_base_url}/auth/kakao/callback"


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.kakao_rest_api_key,
        "redirect_uri": callback_redirect_uri(),
        "response_type": "code",
        "scope": "account_email",
        "state": state,
    }
    return f"{KAKAO_AUTH_URL}?{urlencode(params)}"


def parse_user_me(data: object) -> KakaoProfile:
    """`/v2/user/me` 응답 본문을 프로필로 바꾼다. 회원번호(`id`)가 없거나 본문 모양이 다르면
    `KeyError`·`TypeError` 를 그대로 던진다(호출자가 교환 실패로 바꾼다). 이메일을 쓸 수 없으면
    `email` 을 `None` 으로 돌려준다 — 여기서 던지면 회원번호로 찾을 기존 회원까지 막힌다.

    회원번호는 카카오가 정수로 주지만 연결 해제 웹훅은 같은 값을 문자열로 보내므로 문자열로
    바꿔 저장·비교를 한 표현으로 맞춘다."""
    if not isinstance(data, dict):
        raise TypeError("user/me body is not an object")
    kakao_id = str(data["id"])
    account = data.get("kakao_account")
    if not isinstance(account, dict):
        return KakaoProfile(kakao_id=kakao_id, email=None)
    email = account.get("email")
    if (
        not isinstance(email, str)
        or not email
        or account.get("is_email_valid") is not True
        or account.get("is_email_verified") is not True
    ):
        return KakaoProfile(kakao_id=kakao_id, email=None)
    return KakaoProfile(kakao_id=kakao_id, email=email)


async def exchange_code_for_profile(code: str) -> KakaoProfile:
    """실패는 전부 `OAuthExchangeError` 로 바꿔 던진다(구글 모듈과 같은 이유 — 콜백이 그것만
    잡아 로그인 화면으로 되돌린다). 이메일을 쓸 수 없는 것은 실패가 아니다(`parse_user_me`)."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            token_resp = await client.post(
                KAKAO_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.kakao_rest_api_key,
                    "client_secret": settings.kakao_client_secret,
                    "redirect_uri": callback_redirect_uri(),
                    "code": code,
                },
            )
            if token_resp.status_code != 200:
                raise OAuthExchangeError(f"token exchange returned {token_resp.status_code}")
            access_token = token_resp.json()["access_token"]

            me_resp = await client.get(
                KAKAO_USER_ME_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            if me_resp.status_code != 200:
                raise OAuthExchangeError(f"user/me returned {me_resp.status_code}")
            return parse_user_me(me_resp.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # 구글 모듈과 같다 — 예외 이름만 남긴다(메시지에 응답 본문이 섞일 수 있다).
        raise OAuthExchangeError(type(exc).__name__) from exc


KakaoProfileFetcher = Callable[[str], Awaitable[KakaoProfile]]


def get_kakao_profile_fetcher() -> KakaoProfileFetcher:
    """토큰 교환 호출을 Depends 로 주입해 테스트가 네트워크 없이 갈아끼우게 한다. 호출 함수를
    주입하는 이유는 구글(`get_google_profile_fetcher`)과 같다 — 콜백이 state 대조와 취소 판정을
    끝낸 뒤에 부르고 그 실패를 직접 잡아야 한다."""
    return exchange_code_for_profile


def _state_key(state: str) -> str:
    return f"kakao_oauth_state:{state}"


async def store_oauth_state(redirect_target: str) -> str:
    state = secrets.token_urlsafe(16)
    await redis_client.set(_state_key(state), redirect_target, ex=settings.kakao_oauth_state_ttl_seconds)
    return state


async def consume_oauth_state(state: str) -> str | None:
    key = _state_key(state)
    redirect_target = await redis_client.get(key)
    if redirect_target is None:
        return None
    await redis_client.delete(key)
    return str(redirect_target)


def _pending_signup_key(token: str) -> str:
    return f"kakao_pending_signup:{token}"


async def store_pending_kakao_signup(signup: KakaoPendingSignup) -> str:
    token = secrets.token_urlsafe(24)
    await redis_client.set(
        _pending_signup_key(token),
        json.dumps({"kakao_id": signup["kakao_id"], "email": signup["email"]}),
        ex=settings.kakao_pending_signup_ttl_seconds,
    )
    return token


async def get_pending_kakao_signup(token: str) -> KakaoPendingSignup | None:
    raw = await redis_client.get(_pending_signup_key(token))
    if raw is None:
        return None
    data: KakaoPendingSignup = json.loads(raw)
    return data


async def delete_pending_kakao_signup(token: str) -> None:
    await redis_client.delete(_pending_signup_key(token))


class KakaoUnlinkError(Exception):
    """연결 끊기 API 호출 실패. 메시지에는 상태코드·예외 이름만 담는다."""


async def unlink_kakao_user(kakao_id: str) -> None:
    """우리 쪽 탈퇴 뒤 카카오와 앱의 연결을 끊는다. 어드민 키로 인증하므로 사용자 토큰이 필요
    없다. 서비스가 이 API 로 끊으면 카카오는 연결 해제 웹훅을 보내지 않는다."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                KAKAO_UNLINK_URL,
                headers={"Authorization": f"KakaoAK {settings.kakao_admin_key}"},
                data={"target_id_type": "user_id", "target_id": kakao_id},
            )
    except httpx.HTTPError as exc:
        raise KakaoUnlinkError(type(exc).__name__) from exc
    if resp.status_code != 200:
        raise KakaoUnlinkError(f"unlink returned {resp.status_code}")


async def _skip_kakao_unlink(kakao_id: str) -> None:
    logger.warning("kakao unlink skipped: KAKAO_ADMIN_KEY is not set")


KakaoUnlinker = Callable[[str], Awaitable[None]]


def get_kakao_unlinker() -> KakaoUnlinker:
    """연결 끊기 호출을 Depends 로 주입한다(`core/email.py` 의 `get_email_sender` 와 같은 모양).
    어드민 키가 없는 환경(로컬·CI)에서는 호출하지 않고 경고만 남긴다."""
    if settings.kakao_admin_key:
        return unlink_kakao_user
    return _skip_kakao_unlink


async def unlink_after_withdrawal(
    unlinker: KakaoUnlinker, kakao_id: str, user_id: uuid.UUID
) -> None:
    """탈퇴 커밋 뒤 백그라운드에서 부른다. 실패해도 탈퇴는 이미 끝난 것으로 둔다 — 탈퇴를 외부
    API 에 인질로 잡지 않는다. 연결이 남더라도 우리 쪽 `kakao_id` 는 이미 지워져, 같은 카카오
    계정으로 다시 들어오면 신규 가입 온보딩을 타고 1년 재가입 차단에 걸린다. 로그에는 카카오
    회원번호(개인 식별자) 대신 우리 회원 id 를 남긴다."""
    try:
        await unlinker(kakao_id)
    except KakaoUnlinkError as exc:
        logger.warning("kakao unlink failed for user %s: %s", user_id, exc)
        capture_dependency_failure(exc, dependency="kakao_oauth")
