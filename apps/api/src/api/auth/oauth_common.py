"""소셜 로그인(OAuth) 흐름에서 provider 와 무관하게 같은 조각.

provider 별 모듈(`google_oauth.py` 등)은 인가 URL·토큰 교환·Redis 키처럼 provider 마다 다른 것만
갖고, 브라우저 바인딩 쿠키·콜백 리다이렉트·기존 회원의 세션 발급은 여기 한 벌만 둔다 — 한쪽만
고쳐 두 로그인 경로가 어긋나는 일이 반복된 위험이라 사본을 두지 않는다. 라우터가 아닌 모듈에
두는 이유는 여러 라우터가 import 해도 순환이 생기지 않게 하려는 것이다.
"""

import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import Request, Response, status
from fastapi.responses import RedirectResponse

from api.auth.age import is_under_minimum_age
from api.core.config import settings
from api.db.models.auth import User
from api.session.cookies import set_session_cookie
from api.session.store import create_session

OAuthProvider = Literal["google", "kakao"]

# state·pending 쿠키는 Path 를 `/` 로 둔다. 브라우저가 보는 API 경로가 환경마다 다르기
# 때문이다 — 운영·로컬은 `/auth/...` 이지만 dev(tailscale)는 프록시가 `/api` 접두를 벗겨 넘겨서
# 브라우저 경로가 `/api/auth/...` 다. `/auth/...` 로 좁히면 dev 콜백에 쿠키가 안 실리고,
# `API_BASE_URL` 의 경로를 접두로 붙이면 `.env` 를 싣고 도는 로컬 pytest(요청 경로
# `http://testserver/auth/...`)에서 안 실린다. 모든 환경에서 실리는 값은 `/` 하나뿐이다. Path 는
# 보안 경계가 아니라(같은 호스트의 다른 경로는 어차피 읽을 수 있다) 넓혀서 잃는 것이 없고,
# provider·용도별로 이름을 갈라 같은 Path 에서도 서로 덮어쓰지 않는다.
_OAUTH_COOKIE_PATH = "/"


class OAuthExchangeError(Exception):
    """인가 코드를 프로필로 바꾸는 외부 호출이 실패했다. 비정상 상태코드·네트워크 오류·응답
    형식 오류를 전부 이 하나로 바꿔 던진다 — 콜백이 이것만 잡아 로그인 화면으로 되돌리므로,
    다른 예외가 새면 브라우저에 500 화면이 뜬다. 메시지에는 상태코드·예외 이름만 담는다
    (토큰·이메일을 싣지 않는다)."""


def safe_redirect_path(value: str) -> str:
    """로그인 후 돌아갈 경로를 같은 오리진 경로로 제한한다.

    콜백은 `frontend_base_url` 뒤에 이 값을 그대로 이어 붙이므로 "@evil.com"(userinfo)·
    ".evil.com"(서브도메인)처럼 호스트를 바꾸는 값이 들어오면 로그인 직후 외부로 튄다.
    어긋나면 거부하지 않고 "/"로 대체한다 — 로그인 자체는 정상 흐름이다.

    이 이어 붙이기에서 실제로 호스트를 바꾸는 것은 "/"로 시작하지 않는 값뿐이다
    ("https://ddona.site" + "//evil.com"은 호스트가 그대로다). 아래 나머지 조건은 같은 값이
    상대 URL로 해석되는 순간(프런트가 이 경로로 이동하거나 이어 붙이기 방식이 바뀌면)
    외부로 튀는 형태를 미리 막는 것이다 — 상대 URL로는 "//evil.com"·"/\\evil.com"
    (브라우저는 "\\"를 "/"로 읽는다)·"/<탭>/evil.com"(파싱 전에 탭·개행을 지운다)이
    모두 evil.com 으로 간다.

    - "\\"는 두 번째 글자만이 아니라 위치와 무관하게 거부한다: 앱 라우트(apps/web/src/routes)
      어디에도 역슬래시가 없어 잃는 정상 경로가 없고, 규칙이 더 단순하다.
    - 제어문자(0x00-0x1f, 0x7f)는 위 탭·개행 제거 외에 Location 헤더에 실리는 값이라 거부한다.
    """
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return "/"
    return value


def state_cookie_name(provider: OAuthProvider) -> str:
    return f"oauth_state_{provider}"


def pending_signup_cookie_name(provider: OAuthProvider) -> str:
    return f"oauth_pending_{provider}"


def set_oauth_cookie(response: Response, name: str, value: str, *, max_age: int) -> None:
    """SameSite 는 세션 쿠키 설정을 따르지 않고 Lax 로 고정한다. state 쿠키는 인가 서버에서
    돌아오는 최상위 GET 이동에 실려야 하는데 Lax 면 충분하고, Strict 면 그 cross-site 이동에서
    빠진다. Secure 는 HTTPS 여부가 환경마다 다르므로 세션 쿠키와 같은 설정을 따른다."""
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        path=_OAUTH_COOKIE_PATH,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


def clear_oauth_cookie(response: Response, name: str) -> None:
    # 브라우저는 설정할 때와 같은 Path 로 지워야 실제로 지운다.
    response.delete_cookie(
        key=name,
        path=_OAUTH_COOKIE_PATH,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


async def resolve_oauth_state(
    request: Request,
    state: str | None,
    *,
    provider: OAuthProvider,
    consume: Callable[[str], Awaitable[str | None]],
) -> str | None:
    """콜백의 state 가 이 브라우저가 시작한 흐름의 것인지 확인하고, 맞으면 Redis 에서 1회
    소비해 돌아갈 경로를 꺼낸다. 아니면 None.

    state 가 Redis 에만 있으면 공격자가 자기 인가 흐름의 콜백 URL 을 피해자에게 열게 해
    피해자를 공격자 계정으로 로그인시킬 수 있다(로그인 CSRF). 그래서 로그인 시작 때 같은 값을
    쿠키로 심고 여기서 대조한다. 대조를 consume 보다 먼저 한다 — 불일치일 때 남는 Redis 값은
    공격자 자신의 것이라 지울 이유가 없고, 같은 브라우저의 다른 탭이 시작한 흐름이라면 쿠키가
    뒤 탭 값으로 덮여 앞 탭은 어차피 이 검사에서 떨어진다(재시도로 복구된다).

    None 인 경우는 위조뿐 아니라 정상 사용자도 닿는다 — state 는 1회용이라 온보딩 화면에서
    뒤로가기 후 계정 재선택, 콜백 URL 새로고침, TTL 만료가 모두 여기로 온다. 호출자는 날것의
    오류 본문 대신 로그인 화면으로 되돌려 재시도할 수 있게 한다.
    """
    cookie = request.cookies.get(state_cookie_name(provider))
    if state is None or cookie is None or not secrets.compare_digest(state, cookie):
        return None
    redirect_target = await consume(state)
    if redirect_target is None:
        return None
    # 저장 전(로그인 시작)에도 거르지만, 그 검증이 배포되기 전에 Redis 에 들어간 state 까지
    # 막기 위해 꺼낼 때 한 번 더 거른다.
    return safe_redirect_path(redirect_target)


def oauth_callback_redirect(url: str, *, provider: OAuthProvider) -> RedirectResponse:
    """콜백이 내는 모든 리다이렉트. 결과와 무관하게 콜백 도달로 이 로그인 흐름은 끝나므로 state
    쿠키를 지운다. 라우트가 응답 객체를 직접 반환하면 주입받은 `Response` 에 건 쿠키는 버려지기
    때문에 쿠키는 반드시 반환하는 이 객체에 건다."""
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    clear_oauth_cookie(response, state_cookie_name(provider))
    return response


def oauth_login_error_redirect(error_code: str, *, provider: OAuthProvider) -> RedirectResponse:
    return oauth_callback_redirect(
        f"{settings.frontend_base_url}/login?error={error_code}", provider=provider
    )


async def finish_social_login(
    user: User, redirect_target: str, *, provider: OAuthProvider
) -> RedirectResponse:
    """콜백이 기존 회원을 찾았을 때의 공통 마무리 — 탈퇴·정지·연령을 거르고 세션을 발급한다.
    DB 를 다시 읽지 않는다(호출자가 찾은 `user` 와 Redis 만 쓴다)."""
    # 탈퇴(deleted_at)한 계정도 막는다. 비밀번호 로그인과 달리 탈퇴 여부를 숨기지 않는다: 여긴
    # 실제 자격증명(비밀번호) 추측 공격 표면이 없다(호출자가 이미 그 소셜 계정을 실제로 소유하고
    # 있어야 여기 도달한다). 탈퇴하면 이메일이 자리표시자가 되고 provider 식별자도 파기되므로
    # 탈퇴 행이 여기 올 일은 사실상 없지만 예전 데이터를 위해 검사는 유지한다.
    if user.deleted_at is not None or user.suspended_at is not None:
        error_code = "account_deleted" if user.deleted_at is not None else "account_suspended"
        return oauth_login_error_redirect(error_code, provider=provider)

    # login()과 같은 연령 게이트를 여기에도 둔다 — provider 식별자 직접 매치와 이메일 매칭으로
    # 식별자를 붙이는 분기가 모두 여기로 수렴하므로 한 곳만 막으면 둘 다 막힌다. 위 조건문이
    # deleted_at is not None인 계정을 이미 배제했다 — birth_date는 탈퇴 파기 시에만 None이 된다.
    # 집계에서 0건 확인되면 이 블록을 걷어낼 것(login()의 동일 게이트와 짝).
    assert user.birth_date is not None
    if is_under_minimum_age(user.birth_date, datetime.now(UTC).date()):
        return oauth_login_error_redirect("account_age_restricted", provider=provider)

    session_id = await create_session(user.id)
    response = oauth_callback_redirect(
        f"{settings.frontend_base_url}{redirect_target}", provider=provider
    )
    set_session_cookie(response, session_id)
    return response
