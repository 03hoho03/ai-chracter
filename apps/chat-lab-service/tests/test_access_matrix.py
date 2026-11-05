"""신원 × 경로 접근 표, 경로 검증보다 앞서는 신원 검사, 삭제 본문, 설정 칸, 우회 스위치·403 부재."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from bundles import UPLOAD_HEADER, gz, header_value, make_bundle, sha256_hex, to_json, upload_bundle, upload_header
from chat_lab_service.settings import Settings
from harness import (
    ASSET_JS,
    INDEX_HTML,
    SV_ROOT,
    Lab,
    assert_error,
    assert_request_validation_error,
    assert_security_headers,
    make_settings,
)
from keys import (
    OUTSIDE_UPLOADER_ID,
    OUTSIDER_EMAIL,
    READER_EMAIL,
    UPLOADER_ID,
    auth,
    bad_signature_token,
    both_token,
    human_token,
    neither_token,
    service_token,
)

SEED_RUN = "run-seeded"
UPLOAD_RUN = "run-matrix-upload"

IDENTITIES = [
    "none",
    "invalid",
    "human_allowed",
    "human_outside",
    "service_allowed",
    "service_outside",
    "neither",
    "both",
]
ROUTES = [
    "health",
    "list",
    "versions",
    "bundle",
    "upload",
    "delete",
    "index",
    "asset",
    "missing_static",
    "missing_api",
]
STATIC_ROUTES = {"index", "asset", "missing_static"}

_REJECTED = {route: 404 for route in ROUTES} | {"health": 200}
_UNAUTHENTICATED = {route: 401 for route in ROUTES} | {"health": 200}
EXPECTED: dict[str, dict[str, int]] = {
    "none": _UNAUTHENTICATED,
    "invalid": _UNAUTHENTICATED,
    "human_allowed": {
        "health": 200,
        "list": 200,
        "versions": 200,
        "bundle": 200,
        "upload": 404,
        "delete": 200,
        "index": 200,
        "asset": 200,
        "missing_static": 404,
        "missing_api": 404,
    },
    "human_outside": _REJECTED,
    "service_allowed": _REJECTED | {"upload": 201},
    "service_outside": _REJECTED,
    "neither": _REJECTED,
    "both": _REJECTED,
}


def identity_headers(identity: str) -> dict[str, str]:
    if identity == "none":
        return {}
    tokens = {
        "invalid": bad_signature_token,
        "human_allowed": lambda: human_token(READER_EMAIL),
        "human_outside": lambda: human_token(OUTSIDER_EMAIL),
        "service_allowed": lambda: service_token(UPLOADER_ID),
        "service_outside": lambda: service_token(OUTSIDE_UPLOADER_ID),
        "neither": neither_token,
        "both": both_token,
    }
    return auth(tokens[identity]())


async def seed(lab: Lab) -> str:
    response, data, _ = await upload_bundle(lab.client, make_bundle(SEED_RUN))
    assert response.status_code == 201, response.text
    return sha256_hex(data)


async def call_route(lab: Lab, route: str, headers: dict[str, str], sha: str) -> httpx.Response:
    client = lab.client
    if route == "health":
        return await client.get("/api/health", headers=headers)
    if route == "list":
        return await client.get("/api/runs", headers=headers)
    if route == "versions":
        return await client.get(f"/api/runs/{SEED_RUN}/versions", headers=headers)
    if route == "bundle":
        return await client.get(
            f"/api/runs/{SEED_RUN}/versions/{sha}/bundle", headers={**headers, "Accept-Encoding": "identity"}
        )
    if route == "upload":
        body = gz(to_json(make_bundle(UPLOAD_RUN)))
        upload_headers = {
            **headers,
            "Content-Type": "application/gzip",
            UPLOAD_HEADER: header_value(upload_header()),
        }
        return await client.post(f"/api/runs/{UPLOAD_RUN}/versions", content=body, headers=upload_headers)
    if route == "delete":
        return await client.request("DELETE", f"/api/runs/{SEED_RUN}", json={"runId": SEED_RUN}, headers=headers)
    if route == "index":
        return await client.get("/", headers=headers)
    if route == "asset":
        return await client.get("/assets/app.js", headers=headers)
    if route == "missing_static":
        return await client.get("/no-such-file.txt", headers=headers)
    assert route == "missing_api"
    return await client.get("/api/no-such-route", headers=headers)


def check_cell(identity: str, route: str, response: httpx.Response) -> None:
    expected = EXPECTED[identity][route]
    where = f"{identity} × {route}"
    assert response.status_code != 403, where
    assert response.status_code == expected, (where, response.status_code, response.text[:300])
    assert_security_headers(response)
    if expected == 401:
        assert_error(response, 401, "unauthenticated")
    elif expected == 404:
        assert_error(response, 404, "notFound")
    elif route in STATIC_ROUTES:
        # 해시 없는 index.html 이 옛 판으로 남지 않게 정적 파일은 매번 다시 확인시킨다.
        assert response.headers.get("cache-control") == "no-cache", where
        assert response.content == (INDEX_HTML if route == "index" else ASSET_JS)
    else:
        assert response.headers.get("cache-control") == "no-store", where


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("identity", IDENTITIES)
async def test_identity_route_matrix(lab: Lab, identity: str, route: str) -> None:
    sha = await seed(lab)
    response = await call_route(lab, route, identity_headers(identity), sha)
    check_cell(identity, route, response)


async def sweep(lab: Lab) -> list[tuple[str, str, httpx.Response]]:
    sha = await seed(lab)
    results: list[tuple[str, str, httpx.Response]] = []
    for identity in IDENTITIES:
        for route in ROUTES:
            results.append((identity, route, await call_route(lab, route, identity_headers(identity), sha)))
    return results


async def test_no_response_is_403(lab: Lab) -> None:
    results = await sweep(lab)
    human = auth(human_token())
    extras = [
        await lab.client.put("/api/runs", headers=human),
        await lab.client.request("HEAD", "/assets/app.js", headers=human),
        await lab.client.get("/api/runs/bad.id/versions", headers=human),
        await lab.client.get("/api/runs", headers=auth(service_token())),
        await lab.client.get("/.env", headers=human),
        await lab.client.get("/../../etc/passwd", headers=human),
    ]
    statuses = [response.status_code for _, _, response in results] + [r.status_code for r in extras]
    assert 403 not in statuses


async def test_not_found_bodies_do_not_reveal_existence(lab: Lab) -> None:
    # 허용 밖·다른 신원·진짜 없음 모두 같은 404 본문이어야 경로나 런이 있는지 드러나지 않는다.
    results = await sweep(lab)
    not_found = {response.content for _, _, response in results if response.status_code == 404}
    unauthenticated = {response.content for _, _, response in results if response.status_code == 401}
    assert len(not_found) == 1, not_found
    assert len(unauthenticated) == 1, unauthenticated
    missing_run = await lab.client.get("/api/runs/never-uploaded/versions", headers=auth(human_token()))
    assert missing_run.status_code == 404
    assert missing_run.content in not_found


@pytest.mark.parametrize(
    ("token_kind", "method", "path"),
    [
        ("service", "GET", "/api/runs/bad.id/versions"),
        ("service", "GET", f"/api/runs/{SEED_RUN}/versions/NOT-A-SHA/bundle"),
        ("service", "DELETE", "/api/runs/bad.id"),
        ("human", "POST", "/api/runs/bad.id/versions"),
        ("outsider", "GET", "/api/runs/bad.id/versions"),
        ("outsider", "POST", "/api/runs/bad.id/versions"),
    ],
)
async def test_wrong_identity_beats_path_validation(lab: Lab, token_kind: str, method: str, path: str) -> None:
    token = {
        "service": service_token,
        "human": human_token,
        "outsider": lambda: human_token(OUTSIDER_EMAIL),
    }[token_kind]()
    response = await lab.client.request(method, path, headers=auth(token))
    assert_error(response, 404, "notFound")


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs/bad.id/versions",
        "/api/runs/" + "a" * 1025 + "/versions",
        f"/api/runs/{SEED_RUN}/versions/{'A' * 64}/bundle",
        f"/api/runs/{SEED_RUN}/versions/{'a' * 63}/bundle",
    ],
    ids=["bad-character", "too-long", "uppercase-sha", "short-sha"],
)
async def test_allowed_identity_gets_path_validation_error(lab: Lab, path: str) -> None:
    response = await lab.client.get(path, headers=auth(human_token()))
    assert_request_validation_error(response)


async def _assert_seed_still_listed(lab: Lab) -> None:
    listed = await lab.client.get("/api/runs", headers=auth(human_token()))
    assert [item["runId"] for item in listed.json()["items"]] == [SEED_RUN]


async def test_form_encoded_delete_is_rejected(lab: Lab) -> None:
    await seed(lab)
    response = await lab.client.request(
        "DELETE", f"/api/runs/{SEED_RUN}", data={"runId": SEED_RUN}, headers=auth(human_token())
    )
    assert_error(response, 422, "badDeleteBody")
    await _assert_seed_still_listed(lab)


async def test_delete_body_run_id_must_match_path(lab: Lab) -> None:
    await seed(lab)
    response = await lab.client.request(
        "DELETE", f"/api/runs/{SEED_RUN}", json={"runId": "another-run"}, headers=auth(human_token())
    )
    assert_error(response, 422, "badDeleteBody")
    await _assert_seed_still_listed(lab)


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (None, None),
        (b"not json", "application/json"),
        (b"[]", "application/json"),
        (b"{}", "application/json"),
        (b'{"runId": 7}', "application/json"),
        (f'{{"runId": "{SEED_RUN}"}}'.encode(), "text/plain"),
        # 본문 상한(4KiB) 안에서 파서의 재귀 한도를 넘는 중첩 — 처리 안 된 500 이 아니라 같은 거부다.
        (b"[" * 2000 + b"]" * 2000, "application/json"),
    ],
    ids=["no-body", "not-json", "array", "no-run-id", "run-id-not-string", "json-as-text-plain", "deeply-nested"],
)
async def test_delete_without_valid_body_is_rejected(lab: Lab, content: bytes | None, content_type: str | None) -> None:
    # 교차 사이트 단순 요청(폼·text/plain)으로는 지울 수 없게 JSON 본문과 그 Content-Type 을 함께 요구한다.
    await seed(lab)
    headers = auth(human_token())
    if content_type is not None:
        headers["Content-Type"] = content_type
    response = await lab.client.request("DELETE", f"/api/runs/{SEED_RUN}", content=content, headers=headers)
    assert_error(response, 422, "badDeleteBody")
    await _assert_seed_still_listed(lab)


KNOWN_SETTINGS = {"database_url", "access_issuer", "access_aud", "read_emails", "upload_client_ids", "web_dir"}


def test_settings_fields_are_exactly_known() -> None:
    # 인증을 끄거나 건너뛰는 칸이 생기면(또는 무엇이든 칸이 늘면) 여기서 깨진다.
    assert set(Settings.model_fields) == KNOWN_SETTINGS


def test_settings_read_comma_separated_lists_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # JSON 배열은 따옴표가 들어가 저장소의 env 형식 규칙에 걸리므로 목록은 쉼표 구분으로 받는다.
    monkeypatch.setenv("LAB_DATABASE_URL", "postgresql+asyncpg://lab:secret@127.0.0.1:5432/chat_lab")
    monkeypatch.setenv("LAB_ACCESS_ISSUER", "https://team.cloudflareaccess.com")
    monkeypatch.setenv("LAB_ACCESS_AUD", "ab" * 32)
    monkeypatch.setenv("LAB_READ_EMAILS", "first@example.com,second@example.com")
    monkeypatch.setenv("LAB_UPLOAD_CLIENT_IDS", "one.access,two.access")
    monkeypatch.setenv("LAB_WEB_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    assert "second@example.com" in settings.read_emails
    assert "two.access" in settings.upload_client_ids
    assert "first@example.com,second@example.com" not in settings.read_emails


@pytest.mark.parametrize("field", ["read_emails", "upload_client_ids"])
def test_empty_allow_list_is_rejected(tmp_path: Path, field: str) -> None:
    # 빈 목록으로 뜨면 모두가 404 를 받아 장애처럼 보이므로 기동에서 막는다.
    with pytest.raises(ValidationError):
        make_settings(tmp_path, **{field: ""})


@pytest.mark.parametrize(
    "issuer", ["http://team.cloudflareaccess.com", "https://team.cloudflareaccess.com/", "team.cloudflareaccess.com"]
)
def test_issuer_must_be_https_without_trailing_slash(tmp_path: Path, issuer: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(tmp_path, access_issuer=issuer)


def test_database_url_is_kept_secret(tmp_path: Path) -> None:
    marker = "Mk4q9SettingsSecret"
    settings = make_settings(tmp_path, database_url=f"postgresql+asyncpg://lab:Pw%40{marker}@127.0.0.1:5432/x_test")
    assert marker not in repr(settings)
    assert marker not in str(settings)
    assert marker in settings.database_url.get_secret_value()


def _sources(*, folders: tuple[str, ...], files: tuple[str, ...]) -> list[Path]:
    package = SV_ROOT / "src" / "chat_lab_service"
    assert any(package.glob("*.py")), (
        "서비스 패키지 소스가 없다 — 검사할 대상이 비어 있으면 통과가 아무것도 말하지 않는다"
    )
    found: list[Path] = []
    for folder in folders:
        root = SV_ROOT / folder
        if root.is_dir():
            found += sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    found += [SV_ROOT / name for name in files if (SV_ROOT / name).is_file()]
    return found


def test_source_has_no_403() -> None:
    # 거부는 401(누구인지 모름)·404(허용 밖·없음)뿐이다 — 403 은 "있지만 못 본다"를 알려 준다.
    pattern = re.compile(r"\b403\b|HTTP_403")
    hits = [
        f"{path.relative_to(SV_ROOT)}:{number}"
        for path in _sources(folders=("src", "migrations", "scripts"), files=("Dockerfile", "docker-compose.lab.yml"))
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert hits == []


def test_source_has_no_auth_bypass_switch() -> None:
    pattern = re.compile(r"bypass|skip[_-]?auth|disable[_-]?auth|auth[_-]?disabled|insecure", re.IGNORECASE)
    hits = [
        f"{path.relative_to(SV_ROOT)}:{number}"
        for path in _sources(folders=("src", "migrations", "scripts"), files=("Dockerfile", "docker-compose.lab.yml"))
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert hits == []
