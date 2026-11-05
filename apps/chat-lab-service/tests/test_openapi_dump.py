"""서비스 HTTP 스키마 떨구기 — 환경과 무관한 같은 바이트, 커밋본과의 일치, 웹 codegen 이 읽을 모양."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import pytest

from chat_lab_service.openapi import openapi_text
from harness import SERVICE_OPENAPI, SV_ROOT, Lab
from keys import auth, human_token

RESPONSE_REASONS = {
    "unauthenticated",
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
    "keysUnavailable",
    "dbUnavailable",
    "internal",
}


def test_openapi_text_is_stable_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = openapi_text()
    # 설정값이 스키마에 새거나 떨구기가 환경·DB·공개키에 기대면 아래 값들 때문에 바이트가 달라지거나 실패한다.
    marker = "EnvMk3Openapi"
    monkeypatch.setenv("LAB_DATABASE_URL", f"postgresql+asyncpg://lab:{marker}@127.0.0.1:1/{marker}")
    monkeypatch.setenv("LAB_ACCESS_ISSUER", f"https://{marker}.cloudflareaccess.com")
    monkeypatch.setenv("LAB_ACCESS_AUD", marker)
    monkeypatch.setenv("LAB_READ_EMAILS", f"{marker}@example.com")
    monkeypatch.setenv("LAB_UPLOAD_CLIENT_IDS", f"{marker}.access")
    monkeypatch.setenv("LAB_WEB_DIR", f"/nonexistent/{marker}")
    with_environment = openapi_text()
    assert with_environment == baseline
    assert marker not in with_environment
    assert baseline.endswith("\n")
    assert baseline == json.dumps(json.loads(baseline), indent=2, ensure_ascii=False) + "\n"

    # 다른 프로세스·빈 환경(CI 러너와 같은 조건)에서도 같은 바이트다.
    program = (
        "import sys\n"
        "from chat_lab_service.openapi import openapi_text\n"
        "sys.stdout.buffer.write(openapi_text().encode('utf-8'))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=SV_ROOT,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")[-2000:]
    assert completed.stdout.decode("utf-8") == baseline


def test_committed_service_openapi_matches() -> None:
    # CI 의 드리프트 검사와 같은 대조를 로컬에서도 — 라우트·응답 모델을 고쳤으면 스키마를 다시 떨궈 함께 커밋한다.
    assert SERVICE_OPENAPI.is_file(), "apps/chat-lab/service-openapi.json 이 없다 — scripts/dump_openapi.py 로 떨군다"
    assert SERVICE_OPENAPI.read_text(encoding="utf-8") == openapi_text(), (
        "커밋한 service-openapi.json 이 코드와 다르다 — apps/chat-lab-service 에서 "
        "`uv run python scripts/dump_openapi.py` 로 다시 떨군다"
    )


def _spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads(openapi_text())
    return spec


def _resolve(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].removeprefix("#/components/schemas/")]
    return schema


def test_openapi_lists_service_routes() -> None:
    paths = _spec()["paths"]
    assert {path: sorted(methods) for path, methods in paths.items()} == {
        "/api/health": ["get", "head"],
        "/api/runs": ["get"],
        "/api/runs/{runId}": ["delete"],
        "/api/runs/{runId}/versions": ["get", "post"],
        "/api/runs/{runId}/versions/{sha256}/bundle": ["get", "head"],
    }


def test_openapi_describes_upload_bundle_and_error_shapes() -> None:
    spec = _spec()
    paths = spec["paths"]
    upload_body = paths["/api/runs/{runId}/versions"]["post"]["requestBody"]["content"]
    assert set(upload_body) == {"application/gzip"}
    assert upload_body["application/gzip"]["schema"].get("format") == "binary"
    bundle_ok = paths["/api/runs/{runId}/versions/{sha256}/bundle"]["get"]["responses"]["200"]["content"]
    assert "application/json" in bundle_ok

    error = _resolve(spec, {"$ref": "#/components/schemas/ServiceError"})
    assert set(error["required"]) == {"detail", "reason"}
    reason = _resolve(spec, error["properties"]["reason"])
    assert set(reason["enum"]) == RESPONSE_REASONS
    # 웹이 오류 본문을 이 모델로 읽도록 거부 응답마다 ServiceError 를 적는다(요청 검증 422 는 프레임워크 모델과 함께).
    for path, methods in paths.items():
        for method, operation in methods.items():
            for status, response in operation["responses"].items():
                if status.startswith(("4", "5")) and status != "422":
                    schema = response["content"]["application/json"]["schema"]
                    assert schema == {"$ref": "#/components/schemas/ServiceError"}, (path, method, status)


async def test_docs_and_schema_routes_are_not_served(lab: Lab) -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        response = await lab.client.get(path, headers=auth(human_token()))
        assert response.status_code == 404, path
