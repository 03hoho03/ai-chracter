"""Access JWT 검사: 서명·클레임·공개키 받기·신원 분류·허용 목록.

401 본문은 하나(`unauthenticated`)이고 세부 이유는 접근 기록에만 남으므로, 거부마다 마지막 기록 행의 `reason` 을 함께 본다.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from jwt import PyJWKClient

from bundles import make_bundle, upload_bundle
from harness import Db, FakeMonotonic, Lab, OpenLab, assert_error
from keys import (
    CURRENT_KEY,
    ISSUER,
    OMIT,
    OUTSIDE_UPLOADER_ID,
    OUTSIDER_EMAIL,
    READER_EMAIL,
    ROTATED_KEY,
    SECOND_READER_EMAIL,
    TOKEN_HEADER,
    UPLOADER_ID,
    alg_none_token,
    auth,
    bad_signature_token,
    both_token,
    forge_rs256,
    hs256_with_public_key_token,
    human_claims,
    human_token,
    neither_token,
    service_claims,
    service_token,
    sign,
)

MALFORMED_TOKENS: dict[str, Callable[[], str]] = {
    "no-dots": lambda: "not-a-jwt",
    "bad-segments": lambda: "a.b.c",
    "bad-signature-encoding": lambda: human_token() + "!",
    "no-kid": lambda: forge_rs256({"alg": "RS256", "typ": "JWT"}, human_claims()),
    "kid-not-string": lambda: forge_rs256({"alg": "RS256", "typ": "JWT", "kid": 7}, human_claims()),
}


def _now() -> int:
    return int(time.time())


async def _list_with(lab: Lab, token: str) -> httpx.Response:
    return await lab.client.get("/api/runs", headers=auth(token))


async def _assert_rejected(lab: Lab, db: Db, token: str, reason: str) -> None:
    response = await _list_with(lab, token)
    assert_error(response, 401, "unauthenticated")
    row = await db.last_access_row()
    assert (row["status"], row["reason"], row["identity_kind"]) == (401, reason, "none")


async def test_valid_human_token_reads_list(lab: Lab, db: Db) -> None:
    response = await _list_with(lab, human_token())
    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert response.headers["cache-control"] == "no-store"
    row = await db.last_access_row()
    assert (row["identity_kind"], row["identity"], row["reason"]) == ("human", READER_EMAIL, None)


@pytest.mark.parametrize("email", ["READER@EXAMPLE.COM", SECOND_READER_EMAIL])
async def test_read_email_match_ignores_case(lab: Lab, email: str) -> None:
    # 설정은 `reader@example.com,Second.Reader@Example.com` 이다 — 토큰과 설정 어느 쪽 대소문자가 달라도 같은 사람이다.
    response = await _list_with(lab, human_token(email))
    assert response.status_code == 200


async def test_wrong_audience_is_401(lab: Lab, db: Db) -> None:
    await _assert_rejected(lab, db, human_token(aud=["0" * 64]), "badAudience")


@pytest.mark.parametrize(
    "issuer", ["https://other-team.cloudflareaccess.com", f"{ISSUER}/"], ids=["other-team", "trailing-slash"]
)
async def test_wrong_issuer_is_401(lab: Lab, db: Db, issuer: str) -> None:
    await _assert_rejected(lab, db, human_token(iss=issuer), "badIssuer")


async def test_signature_from_other_key_is_401(lab: Lab, db: Db) -> None:
    await _assert_rejected(lab, db, bad_signature_token(), "badSignature")


async def test_expired_token_is_401(lab: Lab, db: Db) -> None:
    now = _now()
    await _assert_rejected(lab, db, human_token(exp=now - 60, iat=now - 660, nbf=now - 660), "expired")


async def test_future_nbf_is_401(lab: Lab, db: Db) -> None:
    await _assert_rejected(lab, db, human_token(nbf=_now() + 60), "notYetValid")


async def test_future_iat_is_401(lab: Lab, db: Db) -> None:
    await _assert_rejected(lab, db, human_token(iat=_now() + 60), "notYetValid")


async def test_small_clock_skew_within_leeway_is_accepted(lab: Lab) -> None:
    # VM 과 Cloudflare 시계의 몇 초 차이로 방금 받은 토큰이 떨어지지 않게 10초 여유를 둔다.
    now = _now()
    response = await _list_with(lab, human_token(exp=now - 3, nbf=now + 3, iat=now + 3))
    assert response.status_code == 200


@pytest.mark.parametrize("claim", ["exp", "iss", "aud"])
async def test_missing_required_claim_is_401(lab: Lab, db: Db, claim: str) -> None:
    await _assert_rejected(lab, db, sign(human_claims(**{claim: OMIT})), "missingClaim")


async def test_missing_header_is_401(lab: Lab, db: Db) -> None:
    response = await lab.client.get("/api/runs")
    assert_error(response, 401, "unauthenticated")
    assert (await db.last_access_row())["reason"] == "noToken"


async def test_cookie_only_is_401(lab: Lab, db: Db) -> None:
    # 브라우저 쿠키는 읽지 않는다 — Access 가 원점으로 넘기는 머리만 믿는다.
    response = await lab.client.get("/api/runs", headers={"Cookie": f"CF_Authorization={human_token()}"})
    assert_error(response, 401, "unauthenticated")
    assert (await db.last_access_row())["reason"] == "noToken"


async def test_duplicate_token_headers_are_401(lab: Lab, db: Db) -> None:
    token = human_token()
    response = await lab.client.get("/api/runs", headers=[(TOKEN_HEADER, token), (TOKEN_HEADER, token)])
    assert_error(response, 401, "unauthenticated")
    assert (await db.last_access_row())["reason"] == "malformedToken"


@pytest.mark.parametrize("shape", sorted(MALFORMED_TOKENS))
async def test_malformed_token_is_401(lab: Lab, db: Db, shape: str) -> None:
    await _assert_rejected(lab, db, MALFORMED_TOKENS[shape](), "malformedToken")


# 알고리즘은 공개키를 받기 전에 거른다. kid 가 공개된 키면 받은 뒤 서명 검사에서 걸러도 응답·이유가 같지만, 그러면 위조
# 토큰마다 공개키 받기가 일어난다. 그래서 거부와 함께 받기 횟수 0 을 본다.


async def test_alg_none_is_401(lab: Lab, db: Db) -> None:
    await _assert_rejected(lab, db, alg_none_token(human_claims()), "badAlgorithm")
    assert lab.jwks.fetch_count == 0


async def test_hs256_signed_with_public_key_is_401(lab: Lab, db: Db) -> None:
    await _assert_rejected(lab, db, hs256_with_public_key_token(human_claims()), "badAlgorithm")
    assert lab.jwks.fetch_count == 0


async def test_other_rsa_algorithm_is_401(lab: Lab, db: Db) -> None:
    token = jwt.encode(human_claims(), CURRENT_KEY.private_key, algorithm="RS512", headers={"kid": CURRENT_KEY.kid})
    await _assert_rejected(lab, db, token, "badAlgorithm")
    assert lab.jwks.fetch_count == 0


async def test_alg_none_with_unknown_kid_is_401_without_fetching_keys(lab: Lab, db: Db) -> None:
    # 모르는 kid 를 단 서명 없는 토큰도 알고리즘에서 끝난다 — 모르는 kid 로 보고 공개키를 다시 받지 않는다.
    await _assert_rejected(lab, db, alg_none_token(human_claims(), kid="never-published-kid"), "badAlgorithm")
    assert lab.jwks.fetch_count == 0


async def test_unknown_kid_within_cooldown_is_401_without_refetch(
    lab: Lab, db: Db, fake_monotonic: FakeMonotonic
) -> None:
    assert (await _list_with(lab, human_token())).status_code == 200
    assert lab.jwks.fetch_count == 1
    # 키가 이미 회전돼 공개키 주소에 있어도, 마지막 성공 받기 30초 안에는 다시 받지 않는다.
    lab.jwks.keys = [CURRENT_KEY, ROTATED_KEY]
    fake_monotonic.advance(29)
    await _assert_rejected(lab, db, human_token(key=ROTATED_KEY), "unknownKey")
    assert lab.jwks.fetch_count == 1


async def test_unknown_kid_after_cooldown_refetches_once_and_accepts_rotated_key(
    lab: Lab, fake_monotonic: FakeMonotonic
) -> None:
    assert (await _list_with(lab, human_token())).status_code == 200
    lab.jwks.keys = [CURRENT_KEY, ROTATED_KEY]
    fake_monotonic.advance(31)
    response = await _list_with(lab, human_token(key=ROTATED_KEY))
    assert response.status_code == 200
    assert lab.jwks.fetch_count == 2
    # 다시 받은 묶음이 캐시에 남아 다음 요청은 받지 않는다.
    assert (await _list_with(lab, human_token(key=ROTATED_KEY))).status_code == 200
    assert lab.jwks.fetch_count == 2


async def test_unknown_kid_after_cooldown_still_missing_is_401(lab: Lab, db: Db, fake_monotonic: FakeMonotonic) -> None:
    assert (await _list_with(lab, human_token())).status_code == 200
    fake_monotonic.advance(31)
    await _assert_rejected(lab, db, human_token(key=ROTATED_KEY), "unknownKey")
    assert lab.jwks.fetch_count == 2
    # 방금 받았으므로 다시 쿨다운 안이다 — 같은 모르는 kid 가 또 와도 받지 않는다.
    await _assert_rejected(lab, db, human_token(key=ROTATED_KEY), "unknownKey")
    assert lab.jwks.fetch_count == 2


async def test_removed_key_stops_being_trusted_after_cache_lifespan(
    lab: Lab, db: Db, fake_monotonic: FakeMonotonic
) -> None:
    assert (await _list_with(lab, human_token())).status_code == 200
    lab.jwks.keys = [ROTATED_KEY]
    fake_monotonic.advance(299)
    assert (await _list_with(lab, human_token())).status_code == 200
    fake_monotonic.advance(2)
    await _assert_rejected(lab, db, human_token(), "unknownKey")
    assert lab.jwks.fetch_count == 2


async def test_failed_refetch_keeps_cached_keys(lab: Lab, db: Db, fake_monotonic: FakeMonotonic) -> None:
    assert (await _list_with(lab, human_token())).status_code == 200
    lab.jwks.mode = "status500"
    fake_monotonic.advance(31)
    response = await _list_with(lab, human_token(key=ROTATED_KEY))
    assert_error(response, 503, "keysUnavailable")
    assert (await db.last_access_row())["reason"] == "keysUnavailable"
    # 받기가 실패해도 이미 받은 키는 버리지 않는다.
    assert (await _list_with(lab, human_token())).status_code == 200
    assert lab.jwks.fetch_count == 2


async def test_default_client_uses_thirty_second_cooldown_and_certs_url(
    open_lab: OpenLab, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[PyJWKClient] = []
    original_init = PyJWKClient.__init__

    def recording_init(self: PyJWKClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(PyJWKClient, "__init__", recording_init)
    async with open_lab(keys_client="default") as lab:
        assert (await lab.client.get("/api/health")).status_code == 200
        assert lab.jwks.fetch_count == 0

    assert len(created) == 1
    client = created[0]
    assert client.uri == f"{ISSUER}/cdn-cgi/access/certs"
    assert client.cooldown_duration == 30
    assert client.jwk_set_cache is not None
    assert client.jwk_set_cache.lifespan == 300
    assert client.timeout == 10
    assert client.headers.get("User-Agent") == "ddona-chat-lab-service"
    # kid→키 캐시를 켜면 회수된 키를 수명 없이 계속 믿는다 — 켜지 않았으면 인스턴스에 덮어쓴 메서드가 없다.
    assert "get_signing_key" not in vars(client)


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/cdn-cgi/access/certs"


@pytest.mark.parametrize("mode", ["status500", "disconnect", "refused"])
async def test_key_endpoint_down_is_503(open_lab: OpenLab, db: Db, mode: str) -> None:
    keys_client: Any = PyJWKClient(_closed_port_url(), timeout=5) if mode == "refused" else "mock"
    async with open_lab(keys_client=keys_client) as lab:
        if mode == "status500":
            lab.jwks.mode = "status500"
        elif mode == "disconnect":
            lab.jwks.mode = "disconnect"
        response = await _list_with(lab, human_token())
    assert_error(response, 503, "keysUnavailable")
    assert (await db.last_access_row())["reason"] == "keysUnavailable"


async def test_key_endpoint_garbage_is_503(lab: Lab, db: Db) -> None:
    lab.jwks.mode = "garbage"
    response = await _list_with(lab, human_token())
    assert_error(response, 503, "keysUnavailable")
    assert (await db.last_access_row())["reason"] == "keysUnavailable"


async def test_key_endpoint_json_array_lets_nothing_through(lab: Lab) -> None:
    lab.jwks.mode = "array"
    response = await _list_with(lab, human_token())
    assert response.status_code in (401, 503)


async def test_service_token_without_email_and_nbf_uploads(lab: Lab, db: Db) -> None:
    claims = service_claims()
    assert "email" not in claims and "nbf" not in claims and claims["sub"] == ""
    response, _, _ = await upload_bundle(lab.client, make_bundle("run-service"), token=sign(claims))
    assert response.status_code == 201, response.text
    row = await db.last_access_row()
    assert (row["identity_kind"], row["identity"]) == ("service", UPLOADER_ID)


async def test_unregistered_common_name_is_404(lab: Lab, db: Db) -> None:
    response, _, _ = await upload_bundle(
        lab.client, make_bundle("run-outside"), token=service_token(OUTSIDE_UPLOADER_ID)
    )
    assert_error(response, 404, "notFound")
    row = await db.last_access_row()
    assert (row["identity_kind"], row["reason"]) == ("service", "notAllowed")
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 0


async def test_unregistered_email_is_404(lab: Lab, db: Db) -> None:
    response = await _list_with(lab, human_token(OUTSIDER_EMAIL))
    assert_error(response, 404, "notFound")
    row = await db.last_access_row()
    assert (row["identity_kind"], row["identity"], row["reason"]) == ("human", OUTSIDER_EMAIL, "notAllowed")


async def test_token_without_email_or_common_name_is_404(lab: Lab, db: Db) -> None:
    response = await _list_with(lab, neither_token())
    assert_error(response, 404, "notFound")
    row = await db.last_access_row()
    assert (row["identity_kind"], row["identity"], row["reason"]) == ("unknown", None, "notAllowed")


async def test_token_with_both_email_and_common_name_is_404(lab: Lab, db: Db) -> None:
    # 읽기 목록의 이메일과 올리기 목록의 Client ID 를 함께 실어도 어느 쪽으로도 해석하지 않는다.
    listed = await lab.client.get("/api/runs", headers=auth(both_token()))
    uploaded, _, _ = await upload_bundle(lab.client, make_bundle("run-both"), token=both_token())
    for response in (listed, uploaded):
        assert_error(response, 404, "notFound")
    rows = await db.access_rows()
    assert [(row["identity_kind"], row["identity"], row["reason"]) for row in rows] == [
        ("unknown", None, "notAllowed"),
        ("unknown", None, "notAllowed"),
    ]
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 0


@pytest.mark.parametrize("email", ["", 42, None], ids=["empty", "number", "null"])
async def test_email_that_is_not_a_nonempty_string_is_not_a_person(lab: Lab, db: Db, email: Any) -> None:
    response = await _list_with(lab, human_token(email))
    assert_error(response, 404, "notFound")
    assert (await db.last_access_row())["identity_kind"] == "unknown"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("token", [None, "not-a-jwt", "valid"])
async def test_health_ignores_token(lab: Lab, db: Db, method: str, token: str | None) -> None:
    headers = {} if token is None else auth(human_token() if token == "valid" else token)
    response = await lab.client.request(method, "/api/health", headers=headers)
    assert response.status_code == 200
    if method == "GET":
        assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    # 상태 확인은 토큰을 보지 않으므로 공개키도 받지 않는다.
    assert lab.jwks.fetch_count == 0
    row = await db.last_access_row()
    assert (row["identity_kind"], row["identity"], row["route"]) == ("none", None, "/api/health")


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/health/"), ("POST", "/api/health"), ("GET", "/health")])
async def test_health_exception_is_exact(lab: Lab, method: str, path: str) -> None:
    response = await lab.client.request(method, path)
    assert_error(response, 401, "unauthenticated")


async def test_allowed_human_cannot_upload(lab: Lab, db: Db) -> None:
    # 허용된 사람이어도 올리기는 서비스 토큰만 — 다른 신원은 404 이고 판은 생기지 않는다.
    response, _, _ = await upload_bundle(lab.client, make_bundle("run-human"), token=human_token(READER_EMAIL))
    assert_error(response, 404, "notFound")
    assert (await db.last_access_row())["reason"] == "wrongIdentity"
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 0
