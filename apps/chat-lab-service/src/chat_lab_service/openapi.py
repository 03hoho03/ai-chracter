"""서비스 HTTP 스키마 직렬화 — 환경·DB·공개키 없이 돈다.

자리 표시 설정은 검증 없이 만들어 환경 변수를 읽지 않는다. 엔진은 만들기만 하고 접속하지 않으며, 공개키 클라이언트도 받지 않는다.
스키마에 설정값이 들어가지 않으므로 어느 기계에서 떨궈도 바이트가 같다.
"""

import json
from pathlib import Path

from pydantic import SecretStr

from chat_lab_service.app import create_app
from chat_lab_service.settings import Settings


def _placeholder_settings() -> Settings:
    return Settings.model_construct(
        database_url=SecretStr("postgresql+asyncpg://placeholder@127.0.0.1:5432/placeholder"),
        access_issuer="https://placeholder.cloudflareaccess.com",
        access_aud="placeholder",
        read_emails=frozenset({"placeholder@example.com"}),
        upload_client_ids=frozenset({"placeholder.access"}),
        web_dir=Path("/nonexistent"),
    )


def openapi_text() -> str:
    spec = create_app(_placeholder_settings()).openapi()
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
