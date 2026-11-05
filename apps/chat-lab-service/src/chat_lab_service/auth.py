"""Cloudflare Access JWT 검사와 신원 분류.

Access 가 원점으로 넘기는 머리(`Cf-Access-Jwt-Assertion`)만 믿는다 — 브라우저 쿠키(`CF_Authorization`)는 읽지 않는다. 거부는
401(누구인지 모름)·404(허용 밖·다른 신원)뿐이다. 금지(Forbidden) 응답은 "있지만 못 본다"를 알려 주므로 쓰지 않는다.
"""

import http.client
from collections.abc import Iterable
from typing import Any

import anyio.to_thread
import jwt
from fastapi import Request
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKSetError,
)
from starlette.types import ASGIApp, Receive, Scope, Send

from chat_lab_service.access_log import IdentityKind, record_of
from chat_lab_service.boundary import is_api_path
from chat_lab_service.errors import NOT_FOUND_DETAIL, ServiceHTTPError, error_response
from chat_lab_service.schemas import AccessReason

TOKEN_HEADER = b"cf-access-jwt-assertion"
HEALTH_PATH = "/api/health"
ALGORITHM = "RS256"
# VM 과 Cloudflare 시계의 몇 초 차이로 방금 받은 토큰이 "아직 유효 전"으로 떨어지지 않게. 대가는 만료가 그만큼 늦는 것이다.
LEEWAY_SECONDS = 10
REQUIRED_CLAIMS = ["exp", "iss", "aud"]
_KEYS_UNAVAILABLE = "Access 공개키를 받지 못했다"

_DECODE_REASONS: list[tuple[type[InvalidTokenError], AccessReason]] = [
    (ExpiredSignatureError, "expired"),
    (ImmatureSignatureError, "notYetValid"),
    (InvalidAudienceError, "badAudience"),
    (InvalidIssuerError, "badIssuer"),
    (MissingRequiredClaimError, "missingClaim"),
    (InvalidSignatureError, "badSignature"),
    (InvalidAlgorithmError, "badAlgorithm"),
]


def default_jwks_client(issuer: str) -> PyJWKClient:
    return PyJWKClient(
        f"{issuer}/cdn-cgi/access/certs",
        cache_jwk_set=True,
        # 키 묶음을 5분만 믿는다 — Cloudflare 가 키를 빼면 그 키로 서명한 토큰을 5분 안에 더는 받지 않는다.
        lifespan=300,
        # 받는 동안 클라이언트 잠금을 쥐어 다른 요청의 토큰 검사가 모두 줄을 선다. 공개키 주소가 멈췄을 때 그 줄을 라이브러리
        # 기본(30초)보다 일찍 503 으로 끊는다.
        timeout=10,
        # 파이썬 기본 User-Agent 는 Cloudflare 앞 다른 서비스에서 막힌 적이 있다. 공개키 주소도 Cloudflare 다.
        headers={"User-Agent": "ddona-chat-lab-service"},
        # 모르는 kid 로 다시 받는 쿨다운은 라이브러리 기본(30초) 그대로. kid→키 캐시(`cache_keys`)는 켜지 않는다 — 켜면 수명
        # 없이 회수된 키를 계속 믿는다.
    )


class _RejectedError(Exception):
    def __init__(self, status: int, reason: AccessReason, detail: str = "") -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.detail = detail


def _classify(claims: dict[str, Any]) -> tuple[IdentityKind, str | None]:
    """사람 토큰은 email 만, 서비스 토큰은 common_name(Client ID)만 싣는다. 둘 다 있거나 둘 다 없으면 어느 쪽으로도 해석하지
    않는다 — Cloudflare 는 그런 토큰을 만들지 않는다."""
    email = claims.get("email")
    common_name = claims.get("common_name")
    if "common_name" not in claims and isinstance(email, str) and email:
        return "human", email
    if "email" not in claims and isinstance(common_name, str) and common_name:
        return "service", common_name
    return "unknown", None


class AuthMiddleware:
    """라우팅 앞에서 토큰을 보고 신원을 접근 기록에 채운다. 허용 밖이면 경로와 무관하게 바로 404 — 경로가 있는지도 드러내지
    않는다."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        jwks_client: PyJWKClient,
        issuer: str,
        audience: str,
        read_emails: Iterable[str],
        upload_client_ids: Iterable[str],
    ) -> None:
        self.app = app
        self.jwks_client = jwks_client
        self.issuer = issuer
        self.audience = audience
        self.read_emails = frozenset(read_emails)
        self.upload_client_ids = frozenset(upload_client_ids)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope["path"] == HEALTH_PATH and scope["method"] in ("GET", "HEAD")):
            await self.app(scope, receive, send)
            return
        record = record_of(scope)
        try:
            claims = await self._verified_claims(scope)
            record.identity_kind, record.identity = _classify(claims)
            if not self._allowed(record.identity_kind, record.identity):
                raise _RejectedError(404, "notAllowed")
            # 정적 웹은 사람만 본다.
            if not is_api_path(scope["path"]) and record.identity_kind != "human":
                raise _RejectedError(404, "wrongIdentity")
        except _RejectedError as rejected:
            record.reason = rejected.reason
            await error_response(rejected.status, rejected.reason, rejected.detail)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _allowed(self, kind: IdentityKind, identity: str | None) -> bool:
        if identity is None:
            return False
        if kind == "human":
            return identity.casefold() in self.read_emails
        return kind == "service" and identity in self.upload_client_ids

    async def _verified_claims(self, scope: Scope) -> dict[str, Any]:
        tokens = [value for name, value in scope["headers"] if name == TOKEN_HEADER]
        if not tokens:
            raise _RejectedError(401, "noToken")
        if len(tokens) > 1:
            raise _RejectedError(401, "malformedToken")
        token = tokens[0].decode("latin-1")
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError:
            raise _RejectedError(401, "malformedToken") from None
        # 알고리즘은 공개키를 받기 전에 거른다 — `none`·HS256(공개키를 HMAC 비밀로 쓰는 혼동 공격) 등.
        if header.get("alg") != ALGORITHM:
            raise _RejectedError(401, "badAlgorithm")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise _RejectedError(401, "malformedToken")
        try:
            # 공개키 받기는 동기 urllib 이라 이벤트 루프를 막지 않게 스레드에서 돈다(클라이언트 안에 잠금이 있다).
            signing_key = await anyio.to_thread.run_sync(self.jwks_client.get_signing_key, kid)
        except PyJWKClientConnectionError:
            raise _RejectedError(503, "keysUnavailable", _KEYS_UNAVAILABLE) from None
        except (PyJWKClientError, PyJWKSetError):
            raise _RejectedError(401, "unknownKey") from None
        except (ValueError, http.client.HTTPException):
            # JSON 이 아닌 응답은 라이브러리가 감싸지 않은 `json` 오류로 올린다. 2.14 판은 응답 중간에 끊긴 것도 감싸지 않는다.
            raise _RejectedError(503, "keysUnavailable", _KEYS_UNAVAILABLE) from None
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=[ALGORITHM],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": REQUIRED_CLAIMS},
                leeway=LEEWAY_SECONDS,
            )
        except InvalidTokenError as error:
            reason: AccessReason = next(
                (reason for kind, reason in _DECODE_REASONS if isinstance(error, kind)), "malformedToken"
            )
            raise _RejectedError(401, reason) from None
        return claims


async def require_human(request: Request) -> str:
    """허용된 사람의 email. 다른 신원이면 경로 인자 검증보다 먼저 404 — 라우트 의존성은 경로 인자보다 먼저 풀린다."""
    record = record_of(request.scope)
    if record.identity_kind != "human" or record.identity is None:
        raise ServiceHTTPError(404, "wrongIdentity", NOT_FOUND_DETAIL)
    return record.identity


async def require_uploader(request: Request) -> str:
    """허용된 올리기 서비스 토큰의 Client ID."""
    record = record_of(request.scope)
    if record.identity_kind != "service" or record.identity is None:
        raise ServiceHTTPError(404, "wrongIdentity", NOT_FOUND_DETAIL)
    return record.identity
