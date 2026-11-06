"""접근 기록: 요청마다 한 행, 거부 이유, 원문 묶음 내줌 표지, 남기지 않는 값, 기록 실패, 90일 정리."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from jwt import PyJWK, PyJWKClient

from bundles import (
    UPLOAD_HEADER,
    TrackedBody,
    gz,
    header_value,
    make_bundle,
    post_upload,
    provenance,
    sha256_hex,
    to_json,
    upload_bundle,
    upload_header,
)
from chat_lab_service.access_log import purge_old_access_log
from harness import CLOCK_START, COMPRESSED_LIMIT, MIB, Db, Lab, OpenLab, assert_error, assert_security_headers
from keys import (
    OMIT,
    OUTSIDER_EMAIL,
    READER_EMAIL,
    ROTATED_KEY,
    UPLOADER_ID,
    alg_none_token,
    auth,
    bad_signature_token,
    human_claims,
    human_token,
    neither_token,
    service_token,
)

RUN = "run-logged"
UPLOAD_ROUTE = "/api/runs/{runId}/versions"
BUNDLE_ROUTE = "/api/runs/{runId}/versions/{sha256}/bundle"

# 접근 기록의 `reason` 이 가질 수 있는 값 전부.
ALL_LOGGED_REASONS = {
    "noToken",
    "malformedToken",
    "badAlgorithm",
    "unknownKey",
    "badSignature",
    "badAudience",
    "badIssuer",
    "expired",
    "notYetValid",
    "missingClaim",
    "keysUnavailable",
    "notAllowed",
    "wrongIdentity",
    "notFound",
    "tooLarge",
    "notGzip",
    "notJsonObject",
    "noUploadHeader",
    "badUploadHeader",
    "provenanceFailed",
    "noContractVersion",
    "unsupportedContract",
    "legacyFormat",
    "badBundle",
    "runIdMismatch",
    "badDeleteBody",
    "dbUnavailable",
    "internal",
}
# 이 파일의 표 밖에서 덮는 이유: DB 오류는 판 테스트의 표 이름 바꾸기로, 처리되지 않은 예외는 아래 500 테스트로.
REASONS_COVERED_ELSEWHERE = {"dbUnavailable", "internal"}


def _list(token: str) -> Callable[[Lab], Awaitable[httpx.Response]]:
    return lambda lab: lab.client.get("/api/runs", headers=auth(token))


def _upload_json(data: bytes, **kwargs: Any) -> Callable[[Lab], Awaitable[httpx.Response]]:
    return lambda lab: post_upload(lab.client, RUN, gz(data), **kwargs)


def _bundle_with(**overrides: Any) -> bytes:
    bundle = make_bundle(RUN)
    bundle.update(overrides)
    return to_json(bundle)


async def _keys_down(lab: Lab) -> httpx.Response:
    lab.jwks.mode = "status500"
    return await lab.client.get("/api/runs", headers=auth(human_token()))


async def _declared_too_large(lab: Lab) -> httpx.Response:
    body = TrackedBody(b"\x1f\x8b", chunk_size=MIB, chunk_count=9)
    return await post_upload(lab.client, RUN, body, extra_headers={"Content-Length": str(COMPRESSED_LIMIT + 1)})


async def _delete_with_wrong_body(lab: Lab) -> httpx.Response:
    await upload_bundle(lab.client, make_bundle(RUN))
    return await lab.client.request(
        "DELETE", f"/api/runs/{RUN}", json={"runId": "other-run"}, headers=auth(human_token())
    )


REASON_CASES: dict[str, tuple[Callable[[Lab], Awaitable[httpx.Response]], int, str]] = {
    "noToken": (lambda lab: lab.client.get("/api/runs"), 401, "none"),
    "malformedToken": (_list("not-a-jwt"), 401, "none"),
    "badAlgorithm": (lambda lab: _list(alg_none_token(human_claims()))(lab), 401, "none"),
    "unknownKey": (lambda lab: _list(human_token(key=ROTATED_KEY))(lab), 401, "none"),
    "badSignature": (lambda lab: _list(bad_signature_token())(lab), 401, "none"),
    "badAudience": (lambda lab: _list(human_token(aud=["0" * 64]))(lab), 401, "none"),
    "badIssuer": (lambda lab: _list(human_token(iss="https://other.cloudflareaccess.com"))(lab), 401, "none"),
    "expired": (lambda lab: _list(human_token(exp=human_claims()["iat"] - 60))(lab), 401, "none"),
    "notYetValid": (lambda lab: _list(human_token(nbf=human_claims()["iat"] + 60))(lab), 401, "none"),
    "missingClaim": (lambda lab: _list(human_token(exp=OMIT))(lab), 401, "none"),
    "keysUnavailable": (_keys_down, 503, "none"),
    "notAllowed": (lambda lab: _list(human_token(OUTSIDER_EMAIL))(lab), 404, "human"),
    "wrongIdentity": (lambda lab: _list(service_token())(lab), 404, "service"),
    "notFound": (
        lambda lab: lab.client.get("/api/runs/never-uploaded/versions", headers=auth(human_token())),
        404,
        "human",
    ),
    "tooLarge": (_declared_too_large, 413, "service"),
    "notGzip": (lambda lab: post_upload(lab.client, RUN, to_json(make_bundle(RUN))), 422, "service"),
    "notJsonObject": (_upload_json(b"[1, 2]"), 422, "service"),
    "noUploadHeader": (_upload_json(to_json(make_bundle(RUN)), send_header=False), 422, "service"),
    "badUploadHeader": (_upload_json(to_json(make_bundle(RUN)), header="not json"), 422, "service"),
    "provenanceFailed": (
        _upload_json(to_json(make_bundle(RUN)), header=upload_header(prov=provenance(passed=False))),
        422,
        "service",
    ),
    "noContractVersion": (
        _upload_json(to_json({k: v for k, v in make_bundle(RUN).items() if k != "contractVersion"})),
        422,
        "service",
    ),
    "unsupportedContract": (_upload_json(_bundle_with(contractVersion=0)), 422, "service"),
    "legacyFormat": (_upload_json(to_json(make_bundle(RUN, fmt="legacy"))), 422, "service"),
    "badBundle": (_upload_json(_bundle_with(raw="yes")), 422, "service"),
    "runIdMismatch": (_upload_json(to_json(make_bundle("another-run"))), 422, "service"),
    "badDeleteBody": (_delete_with_wrong_body, 422, "human"),
}


def test_reason_cases_cover_every_logged_reason() -> None:
    assert set(REASON_CASES) | REASONS_COVERED_ELSEWHERE == ALL_LOGGED_REASONS


@pytest.mark.parametrize("reason", sorted(REASON_CASES))
async def test_rejected_request_rows_carry_reason(lab: Lab, db: Db, reason: str) -> None:
    send, status, identity_kind = REASON_CASES[reason]
    response = await send(lab)
    assert response.status_code == status, response.text
    row = await db.last_access_row()
    assert (row["status"], row["reason"], row["identity_kind"]) == (status, reason, identity_kind)


async def test_every_request_writes_one_row(lab: Lab, db: Db) -> None:
    human = auth(human_token())
    responses = [
        await lab.client.get("/api/health"),
        await lab.client.head("/api/health"),
        await lab.client.get("/api/runs"),
        await lab.client.get("/api/runs", headers=auth(human_token(OUTSIDER_EMAIL))),
        await lab.client.put("/api/runs", headers=human),
        await _declared_too_large(lab),
        await post_upload(lab.client, RUN, gz(to_json(make_bundle(RUN))), send_header=False),
        await post_upload(lab.client, RUN, gz(to_json(make_bundle(RUN)))),
        await lab.client.get("/api/runs", headers=human),
        await lab.client.get("/", headers=human),
        await lab.client.get("/assets/app.js", headers=human),
        await lab.client.get("/no-such-file.txt", headers=human),
        await lab.client.get(
            f"/api/runs/{RUN}/versions/{sha256_hex(to_json(make_bundle(RUN)))}/bundle",
            headers={**human, "Accept-Encoding": "gzip"},
        ),
        await lab.client.request("DELETE", f"/api/runs/{RUN}", json={"runId": RUN}, headers=human),
    ]
    statuses = [response.status_code for response in responses]
    assert {200, 201, 401, 404, 405, 413, 422} <= set(statuses), statuses
    rows = await db.access_rows()
    assert [row["status"] for row in rows] == statuses
    assert [row["method"] for row in rows] == [response.request.method for response in responses]
    assert all(row["at"] == lab.clock.now for row in rows)


async def test_method_not_allowed_records_route_template(lab: Lab, db: Db) -> None:
    response = await lab.client.put("/api/runs", headers=auth(human_token()))
    assert response.status_code == 405
    assert_security_headers(response)
    row = await db.last_access_row()
    assert (row["route"], row["status"], row["identity_kind"]) == ("/api/runs", 405, "human")


@pytest.mark.parametrize(
    ("method", "path", "route", "run_id"),
    [
        ("GET", "/api/runs", "/api/runs", None),
        ("GET", "/api/runs/run-abc/versions", UPLOAD_ROUTE, "run-abc"),
        ("POST", "/api/runs/run-abc/versions", UPLOAD_ROUTE, "run-abc"),
        ("GET", f"/api/runs/run-abc/versions/{'c' * 64}/bundle", BUNDLE_ROUTE, "run-abc"),
        ("DELETE", "/api/runs/run-abc", "/api/runs/{runId}", "run-abc"),
        ("GET", "/api/runs/bad.id/versions", UPLOAD_ROUTE, None),
        ("GET", "/", "/{static}", None),
        ("GET", "/assets/app.js", "/{static}", None),
        ("GET", "/api/no-such-route", "unmatched", None),
    ],
)
async def test_route_template_recorded_for_unauthenticated_request(
    lab: Lab, db: Db, method: str, path: str, route: str, run_id: str | None
) -> None:
    # 인증 401 로 라우터까지 가지 않은 요청에도 경로 틀과 runId 가 남는다. 경로 원문은 남기지 않는다.
    response = await lab.client.request(method, path)
    assert response.status_code == 401
    row = await db.last_access_row()
    assert (row["route"], row["run_id"], row["reason"], row["identity_kind"]) == (route, run_id, "noToken", "none")


async def _download_rows(lab: Lab, db: Db, *, raw: bool) -> list[dict[str, Any]]:
    """묶음을 gzip·푼 꼴로 한 번씩 꺼내고 목록도 한 번 읽은 뒤 그 세 행을 돌려준다."""
    response, data, _ = await upload_bundle(lab.client, make_bundle(RUN, raw=raw))
    sha = response.json()["sha256"]
    assert sha == sha256_hex(data)
    human = auth(human_token())
    for encoding in ("gzip", "identity"):
        served = await lab.client.get(
            f"/api/runs/{RUN}/versions/{sha}/bundle", headers={**human, "Accept-Encoding": encoding}
        )
        assert served.status_code == 200
    assert (await lab.client.get("/api/runs", headers=human)).status_code == 200
    rows = (await db.access_rows())[-3:]
    for row in rows[:2]:
        assert (row["route"], row["run_id"], row["sha256"]) == (BUNDLE_ROUTE, RUN, sha)
    return rows


async def test_raw_bundle_download_is_marked(lab: Lab, db: Db) -> None:
    rows = await _download_rows(lab, db, raw=True)
    assert [row["raw_served"] for row in rows] == [True, True, False]


async def test_redacted_bundle_download_is_not_marked(lab: Lab, db: Db) -> None:
    rows = await _download_rows(lab, db, raw=False)
    assert [row["raw_served"] for row in rows] == [False, False, False]


async def test_upload_and_delete_rows_carry_identity_and_sha(lab: Lab, db: Db) -> None:
    response, data, _ = await upload_bundle(lab.client, make_bundle(RUN))
    assert response.status_code == 201
    upload_row = await db.last_access_row()
    assert (upload_row["identity_kind"], upload_row["identity"], upload_row["run_id"], upload_row["sha256"]) == (
        "service",
        UPLOADER_ID,
        RUN,
        sha256_hex(data),
    )
    deleted = await lab.client.request(
        "DELETE", f"/api/runs/{RUN}", json={"runId": RUN}, headers=auth(human_token(READER_EMAIL))
    )
    assert deleted.status_code == 200
    delete_row = await db.last_access_row()
    assert (delete_row["identity_kind"], delete_row["identity"], delete_row["run_id"], delete_row["status"]) == (
        "human",
        READER_EMAIL,
        RUN,
        200,
    )


async def test_unknown_identity_is_recorded_without_identity_value(lab: Lab, db: Db) -> None:
    await lab.client.get("/api/runs", headers=auth(neither_token()))
    row = await db.last_access_row()
    assert (row["identity_kind"], row["identity"]) == ("unknown", None)


@pytest.mark.parametrize(
    ("header", "expected"),
    [("203.0.113.7", "203.0.113.7"), ("2001:db8::1", "2001:db8::1"), ("not-an-ip", None), (None, None)],
    ids=["ipv4", "ipv6", "garbage", "absent"],
)
async def test_client_ip_kept_only_when_parsable(lab: Lab, db: Db, header: str | None, expected: str | None) -> None:
    headers = {} if header is None else {"CF-Connecting-IP": header}
    await lab.client.get("/api/health", headers=headers)
    assert (await db.last_access_row())["client_ip"] == expected


async def test_rows_hold_no_token_or_header_values(lab: Lab, db: Db) -> None:
    marker = "HdrMk7Q2zTrace"
    human = human_token()
    service = service_token()
    noisy = {
        "Cookie": f"CF_Authorization={human}; other={marker}",
        "CF-Access-Client-Id": f"{marker}-id",
        "CF-Access-Client-Secret": f"{marker}-secret",
        "User-Agent": f"{marker}-agent",
        "Referer": f"https://{marker}.example/",
        "X-Forwarded-For": f"{marker}",
        "Authorization": f"Bearer {marker}",
        "CF-Connecting-IP": f"{marker}",
    }
    await lab.client.get("/api/runs", headers={**noisy, **auth(human)})
    await lab.client.get(f"/api/runs?q={marker}", headers=auth(human))
    await lab.client.get(f"/api/{marker}", headers=auth(human))
    await lab.client.get(f"/{marker}.html", headers=auth(human))
    await lab.client.get("/api/runs", headers={"Cookie": f"CF_Authorization={human}"})
    await lab.client.get("/api/runs", headers=auth(f"{marker}.not.token"))
    await lab.client.get(f"/api/runs/{RUN}/versions/{marker}/bundle", headers=auth(human))
    header = upload_header(note=marker, prov={**provenance(), "extra": marker})
    await post_upload(lab.client, RUN, gz(to_json(make_bundle(RUN))), token=service, header=header, extra_headers=noisy)
    await lab.client.post(
        f"/api/runs/{RUN}/versions",
        content=gz(to_json(make_bundle(RUN))),
        headers={UPLOAD_HEADER: header_value(header), "Cookie": f"x={marker}"},
    )

    rows = await db.access_rows()
    assert len(rows) == 9
    forbidden = [marker, human, service, human.split(".")[2], service.split(".")[2]]
    leaks = [
        (row["id"], column, needle)
        for row in rows
        for column, value in row.items()
        if isinstance(value, str)
        for needle in forbidden
        if needle in value
    ]
    assert leaks == []
    stored = await db.fetch(
        "SELECT run_item::text AS run_item, provenance::text AS provenance, uploaded_by, source_commit "
        "FROM bundle_versions"
    )
    assert all(marker not in str(value) for row in stored for value in row.values())


async def test_log_write_failure_keeps_response(
    lab: Lab, db: Db, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    # 기록은 응답을 다 보낸 뒤 쓴다 — 기록이 실패해도 이미 나간 응답은 그대로이고, 오류 출력에는 예외 이름만 남는다.
    constraint = "lab_block_access_writes"
    await db.execute(f"ALTER TABLE access_log ADD CONSTRAINT {constraint} CHECK (false) NOT VALID")
    try:
        health = await lab.client.get("/api/health")
        listed = await lab.client.get("/api/runs", headers=auth(human_token()))
    finally:
        await db.execute(f"ALTER TABLE access_log DROP CONSTRAINT {constraint}")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert listed.status_code == 200
    assert listed.json() == {"items": []}
    captured = capfd.readouterr()
    output = caplog.text + captured.out + captured.err
    assert "접근 기록을 쓰지 못했다" in output
    assert constraint not in output
    assert await db.scalar("SELECT count(*) FROM access_log") == 0


class _ExplodingKeys(PyJWKClient):
    def get_signing_key(self, kid: str) -> PyJWK:
        raise RuntimeError("UnhandledMk5Detail")


async def test_unhandled_error_is_500_with_headers_and_row(
    open_lab: OpenLab, db: Db, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    exploding = _ExplodingKeys("http://127.0.0.1:9/cdn-cgi/access/certs")
    async with open_lab(keys_client=exploding) as lab:
        response = await lab.client.get("/api/runs", headers=auth(human_token()))
    assert_error(response, 500, "internal")
    row = await db.last_access_row()
    assert (row["status"], row["reason"], row["route"]) == (500, "internal", "/api/runs")
    captured = capfd.readouterr()
    output = caplog.text + captured.out + captured.err
    assert "RuntimeError" in output
    assert "UnhandledMk5Detail" not in output
    assert "UnhandledMk5Detail" not in response.text


async def test_purge_removes_rows_older_than_ninety_days(db: Db) -> None:
    now = CLOCK_START
    for days in (0, 89, 90, 91, 400):
        await db.insert_access_row(now - timedelta(days=days))
    deleted = await purge_old_access_log(db.engine, now)
    assert deleted == 2
    remaining = sorted(row["at"] for row in await db.access_rows())
    assert remaining == [now - timedelta(days=90), now - timedelta(days=89), now]


async def _wait_until_gone(db: Db, at: Any) -> None:
    # 정리는 lifespan 이 띄운 작업에서 돈다 — 그 작업이 첫 정리를 마칠 때까지 기다린다(시간 판정에 쓰지 않는다).
    for _ in range(250):
        if await db.scalar("SELECT count(*) FROM access_log WHERE at = :at", at=at) == 0:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("기동한 뒤 90일 지난 기록이 지워지지 않았다")


async def test_startup_runs_purge_once(open_lab: OpenLab, db: Db) -> None:
    old = CLOCK_START - timedelta(days=91)
    recent = CLOCK_START - timedelta(days=89)
    await db.insert_access_row(old)
    await db.insert_access_row(recent)
    async with open_lab() as lab:
        await _wait_until_gone(db, old)
        rows = await db.fetch("SELECT at FROM access_log WHERE at < :now", now=CLOCK_START)
        assert [row["at"] for row in rows] == [recent]
        # 다음 정리는 하루 뒤다 — 요청이 와도 지우지 않는다.
        older = CLOCK_START - timedelta(days=200)
        await db.insert_access_row(older)
        assert (await lab.client.get("/api/health")).status_code == 200
        assert await db.scalar("SELECT count(*) FROM access_log WHERE at = :at", at=older) == 1
