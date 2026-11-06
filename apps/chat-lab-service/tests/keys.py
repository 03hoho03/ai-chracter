"""시험 서명 키·토큰·공개키 주소 흉내.

Cloudflare 에는 한 번도 닿지 않는다. 토큰은 여기서 만든 RSA 키로 서명하고, 공개키는 같은 프로세스의 스레드
HTTP 서버가 낸다. 앱은 그 주소를 가리키는 `PyJWKClient` 를 받아 운영과 같은 urllib 경로로 공개키를 받는다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "https://chat-lab-test.cloudflareaccess.com"
AUD = "3f" * 32
TOKEN_HEADER = "cf-access-jwt-assertion"

READER_EMAIL = "reader@example.com"
# 설정에는 대소문자를 섞어 적는다 — 허용 목록 비교가 대소문자를 무시하는지 보려는 것이다.
SECOND_READER_EMAIL = "second.reader@example.com"
OUTSIDER_EMAIL = "stranger@example.com"
UPLOADER_ID = "uploader-client.access"
SECOND_UPLOADER_ID = "second-uploader.access"
OUTSIDE_UPLOADER_ID = "outside-client.access"

READ_EMAILS_SETTING = "reader@example.com,Second.Reader@Example.com"
UPLOAD_CLIENT_IDS_SETTING = f"{UPLOADER_ID},{SECOND_UPLOADER_ID}"


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    def public_jwk(self) -> dict[str, Any]:
        jwk = RSAAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        return {**jwk, "kid": self.kid, "alg": "RS256", "use": "sig"}

    def public_pem(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )


def _new_key(kid: str) -> SigningKey:
    return SigningKey(kid=kid, private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048))


CURRENT_KEY = _new_key("synthetic-current-kid")
ROTATED_KEY = _new_key("synthetic-rotated-kid")


class _Omit:
    """클레임을 아예 빼라는 표지 — `None` 은 값으로 싣는다."""


OMIT = _Omit()


def _now() -> int:
    # PyJWT 는 exp·nbf·iat 를 실제 벽시계(`datetime.now`)로 보므로 클레임도 실제 시각으로 만든다.
    return int(time.time())


def _apply(claims: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = {**claims, **overrides}
    return {name: value for name, value in merged.items() if not isinstance(value, _Omit)}


def human_claims(email: Any = READER_EMAIL, **overrides: Any) -> dict[str, Any]:
    """사람 로그인 토큰 꼴: `email`·`nbf` 가 있고 `aud` 는 배열이다."""
    now = _now()
    claims: dict[str, Any] = {
        "aud": [AUD],
        "email": email,
        "exp": now + 600,
        "iat": now,
        "nbf": now,
        "iss": ISSUER,
        "type": "app",
        "identity_nonce": "synthetic-nonce",
        "sub": "00000000-0000-4000-8000-0000000000aa",
        "country": "KR",
    }
    return _apply(claims, overrides)


def service_claims(common_name: Any = UPLOADER_ID, **overrides: Any) -> dict[str, Any]:
    """서비스 토큰 꼴: `sub` 가 빈 문자열이고 `email`·`nbf` 가 없으며 `common_name` 이 Client ID 다."""
    now = _now()
    claims: dict[str, Any] = {
        "aud": [AUD],
        "common_name": common_name,
        "exp": now + 600,
        "iat": now,
        "iss": ISSUER,
        "type": "app",
        "identity_nonce": "",
        "sub": "",
    }
    return _apply(claims, overrides)


def sign(claims: dict[str, Any], key: SigningKey = CURRENT_KEY, *, kid: str | None = None) -> str:
    """RS256 으로 서명한다. `kid` 를 주면 머리의 kid 만 그 값으로 바꾼다(서명 키는 `key`)."""
    return jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": kid or key.kid})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signing_input(header: dict[str, Any], claims: dict[str, Any]) -> bytes:
    head = _b64(json.dumps(header, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{head}.{body}".encode("ascii")


def forge_rs256(header: dict[str, Any], claims: dict[str, Any], key: SigningKey = CURRENT_KEY) -> str:
    """머리를 라이브러리 검사 없이 그대로 싣고 RS256 으로 서명한다(kid 가 문자열이 아닌 토큰 등)."""
    signing_input = _signing_input(header, claims)
    signature = key.private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode('ascii')}.{_b64(signature)}"


def alg_none_token(claims: dict[str, Any], kid: str = CURRENT_KEY.kid) -> str:
    signing_input = _signing_input({"alg": "none", "typ": "JWT", "kid": kid}, claims)
    return f"{signing_input.decode('ascii')}."


def hs256_with_public_key_token(claims: dict[str, Any], key: SigningKey = CURRENT_KEY) -> str:
    """공개키 PEM 을 HMAC 비밀로 쓴 토큰 — 알고리즘 혼동 공격 꼴."""
    signing_input = _signing_input({"alg": "HS256", "typ": "JWT", "kid": key.kid}, claims)
    signature = hmac.new(key.public_pem(), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64(signature)}"


def human_token(email: Any = READER_EMAIL, key: SigningKey = CURRENT_KEY, **overrides: Any) -> str:
    return sign(human_claims(email, **overrides), key)


def service_token(common_name: Any = UPLOADER_ID, key: SigningKey = CURRENT_KEY, **overrides: Any) -> str:
    return sign(service_claims(common_name, **overrides), key)


def neither_token() -> str:
    """유효한 서명이지만 email 도 common_name 도 없는 토큰."""
    return sign(human_claims(OMIT))


def both_token() -> str:
    """유효한 서명에 email 과 common_name 을 함께 실은 토큰 — Cloudflare 는 만들지 않는 꼴."""
    return sign(human_claims(READER_EMAIL, common_name=UPLOADER_ID))


def bad_signature_token() -> str:
    """머리 kid 는 공개된 키인데 다른 키로 서명한 토큰."""
    return sign(human_claims(READER_EMAIL), ROTATED_KEY, kid=CURRENT_KEY.kid)


def auth(token: str) -> dict[str, str]:
    return {TOKEN_HEADER: token}


JwksMode = Literal["ok", "status500", "disconnect", "garbage", "array"]


@dataclass
class JwksServer:
    """127.0.0.1 임의 포트에서 JWKS 를 내는 스레드 HTTP 서버.

    내보낼 키 묶음(`keys`)·실패 모드(`mode`)·받기 횟수(`fetch_count`)를 테스트가 쥔다.
    """

    keys: list[SigningKey] = field(default_factory=lambda: [CURRENT_KEY])
    mode: JwksMode = "ok"
    fetch_count: int = 0
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    PATH = "/cdn-cgi/access/certs"

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}{self.PATH}"

    def reset(self) -> None:
        with self._lock:
            self.keys = [CURRENT_KEY]
            self.mode = "ok"
            self.fetch_count = 0

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != JwksServer.PATH:
                    self.send_error(404)
                    return
                with owner._lock:
                    owner.fetch_count += 1
                    mode = owner.mode
                    payload = {"keys": [key.public_jwk() for key in owner.keys]}
                if mode == "status500":
                    self.send_error(500)
                elif mode == "disconnect":
                    # 머리는 200 KiB 를 약속하고 몇 바이트만 보낸 뒤 연결을 닫는다 — 받는 쪽은 응답 중간에 끊긴다.
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(200 * 1024))
                    self.end_headers()
                    self.wfile.write(b'{"keys": [')
                    self.wfile.flush()
                    self.close_connection = True
                elif mode == "garbage":
                    self._send(b"<html>this is not json</html>", "text/html")
                elif mode == "array":
                    self._send(b"[]", "application/json")
                else:
                    self._send(json.dumps(payload).encode(), "application/json")

            def _send(self, body: bytes, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, name="jwks-mock", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
