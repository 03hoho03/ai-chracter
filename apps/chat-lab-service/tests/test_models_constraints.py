"""마이그레이션이 만든 표의 CHECK·NOT NULL·UNIQUE 제약.

`alembic check` 는 CHECK 제약을 비교하지 않으므로 모델과 마이그레이션이 어긋나도 CI 가 모른다. 여기서는 앱을 거치지 않고
SQL 로 직접 넣어 DB 가 실제로 거부하는지 본다. 거부 사례마다 받아지는 행에서 칸 하나만 바꾼다.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from bundles import COMMIT_A, COMMIT_SHA256
from harness import CLOCK_START, Db

SHA = "ab" * 32

INSERT_BUNDLE = """
INSERT INTO bundle_versions (
    run_id, sha256, body, compressed_size, uncompressed_size, contract_version, raw, run_item,
    source_commit, source_dirty, provenance, uploaded_by, uploaded_at, deleted_by, deleted_at
) VALUES (
    :run_id, :sha256, :body, :compressed_size, :uncompressed_size, :contract_version, :raw,
    CAST(:run_item AS jsonb), :source_commit, :source_dirty, CAST(:provenance AS jsonb), :uploaded_by,
    :uploaded_at, :deleted_by, :deleted_at
)
"""

INSERT_ACCESS = """
INSERT INTO access_log (at, identity_kind, identity, method, route, run_id, sha256, status, reason, client_ip)
VALUES (:at, :identity_kind, :identity, :method, :route, :run_id, :sha256, :status, :reason, :client_ip)
"""


def bundle_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": "run-constraints",
        "sha256": SHA,
        "body": b"\x1f\x8b synthetic",
        "compressed_size": 10,
        "uncompressed_size": 20,
        "contract_version": 1,
        "raw": False,
        "run_item": json.dumps({"runId": "run-constraints"}),
        "source_commit": COMMIT_A,
        "source_dirty": False,
        "provenance": json.dumps({"passed": True}),
        "uploaded_by": "uploader-client.access",
        "uploaded_at": CLOCK_START,
        "deleted_by": None,
        "deleted_at": None,
    }
    row.update(overrides)
    return row


def access_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "at": CLOCK_START,
        "identity_kind": "human",
        "identity": "reader@example.com",
        "method": "GET",
        "route": "/api/runs",
        "run_id": None,
        "sha256": None,
        "status": 200,
        "reason": None,
        "client_ip": None,
    }
    row.update(overrides)
    return row


# 지운 판: 본문이 비고 지운 이·때가 짝으로 남는다. 아래 거부 사례는 두 CHECK 가운데 하나만 어기도록 골랐다.
DELETED = {"body": None, "deleted_by": "reader@example.com", "deleted_at": CLOCK_START + timedelta(days=1)}


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"run_id": "r"},
        {"run_id": "r" * 1024},
        {"source_commit": COMMIT_SHA256},
        DELETED,
    ],
    ids=["baseline", "one-char-run", "longest-run", "sha256-commit", "deleted"],
)
async def test_valid_bundle_rows_are_accepted(db: Db, overrides: dict[str, Any]) -> None:
    await db.execute(INSERT_BUNDLE, **bundle_row(**overrides))
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_id": ""},
        {"run_id": "r" * 1025},
        {"sha256": SHA.upper()},
        {"sha256": SHA[:-1]},
        {"sha256": "g" * 64},
        {"compressed_size": 0},
        {"uncompressed_size": 0},
        {"source_commit": COMMIT_A[:-1]},
        {"source_commit": COMMIT_A + "0"},
        {"source_commit": "z" * 40},
        {"body": None, "deleted_at": CLOCK_START},
        {"deleted_by": "reader@example.com"},
        {"body": None},
        {**DELETED, "body": b"\x1f\x8b still here"},
        {"run_id": None},
        {"raw": None},
        {"run_item": None},
        {"provenance": None},
        {"uploaded_by": None},
        {"uploaded_at": None},
        {"contract_version": None},
    ],
    ids=[
        "empty-run",
        "run-too-long",
        "sha-uppercase",
        "sha-short",
        "sha-not-hex",
        "compressed-zero",
        "uncompressed-zero",
        "commit-39",
        "commit-41",
        "commit-not-hex",
        "deleted-at-without-by",
        "deleted-by-without-at",
        "body-cleared-but-live",
        "body-kept-after-delete",
        "run-null",
        "raw-null",
        "run-item-null",
        "provenance-null",
        "uploaded-by-null",
        "uploaded-at-null",
        "contract-null",
    ],
)
async def test_invalid_bundle_rows_are_rejected(db: Db, overrides: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        await db.execute(INSERT_BUNDLE, **bundle_row(**overrides))


async def test_same_run_and_sha_is_unique(db: Db) -> None:
    await db.execute(INSERT_BUNDLE, **bundle_row())
    with pytest.raises(IntegrityError):
        await db.execute(INSERT_BUNDLE, **bundle_row(source_commit=COMMIT_SHA256))
    # 같은 내용이 다른 런에 있는 것은 다른 판이다.
    await db.execute(INSERT_BUNDLE, **bundle_row(run_id="run-elsewhere"))
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 2


@pytest.mark.parametrize("kind", ["none", "human", "service", "unknown"])
async def test_access_log_accepts_known_identity_kinds(db: Db, kind: str) -> None:
    await db.execute(INSERT_ACCESS, **access_row(identity_kind=kind))
    assert await db.scalar("SELECT raw_served FROM access_log") is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"identity_kind": "admin"},
        {"identity_kind": None},
        {"at": None},
        {"method": None},
        {"route": None},
        {"status": None},
    ],
    ids=["unknown-kind", "kind-null", "at-null", "method-null", "route-null", "status-null"],
)
async def test_invalid_access_rows_are_rejected(db: Db, overrides: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        await db.execute(INSERT_ACCESS, **access_row(**overrides))
