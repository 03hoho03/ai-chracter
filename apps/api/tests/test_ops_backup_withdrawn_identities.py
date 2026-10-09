"""탈퇴한 인증 회원의 CI 해시(`withdrawn_identities`)를 1년 뒤 파기하는 백업 크론 단계.

`backup_db.py` 는 시스템 python3 로 돌아 SQLAlchemy 를 쓸 수 없어 컨테이너 안 `psql` 을 부른다. 여기서는 그 경계(`run_sh`)를
가짜로 바꿔 cutoff·SQL 구성·`RETURNING` 줄 세기·실패 전파와, 백업이 실패하면 파기도 하지 않는 순서를 본다 — 이메일 해시
파기 테스트(`test_ops_backup_withdrawn_emails.py`)와 같은 모양이다. Postgres 가 실제로 거르는지는 이 스위트가 보지 않는다.
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import ops.backup_db as backup_db
from api.core.constants import WITHDRAWN_IDENTITY_RETENTION_PERIOD


def test_retention_matches_api_constant() -> None:
    """크론은 `api` 를 import 할 수 없어 1년을 복제해 쓴다. 미션 재수령 차단이 풀리는 시점과 행이 파기되는 시점이
    갈라지지 않게 원본과 같은지 본다."""
    assert backup_db.WITHDRAWN_EMAIL_BLOCK_PERIOD == WITHDRAWN_IDENTITY_RETENTION_PERIOD


def _capture_run_sh(
    monkeypatch: pytest.MonkeyPatch, *, stdout: bytes, returncode: int = 0, stderr: bytes = b""
) -> dict[str, str]:
    captured: dict[str, str] = {}

    def _fake_run_sh(script: str, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(backup_db, "run_sh", _fake_run_sh)
    return captured


def test_deletes_only_rows_past_the_retention_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """cutoff 가 `now - 1년` 이고 비교가 `<` 여야 한다 — 뒤집히면 보관 중인 행까지 지운다."""
    now = datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC)
    captured = _capture_run_sh(monkeypatch, stdout=b"hmac-a\nhmac-b\n")

    removed = backup_db.delete_expired_withdrawn_identities("postgresql://unused", now=now)

    assert removed == 2
    script = captured["script"]
    assert "DELETE FROM withdrawn_identities" in script
    assert "withdrawn_at <" in script
    assert (now - WITHDRAWN_IDENTITY_RETENTION_PERIOD).isoformat() in script
    assert "RETURNING ci_hmac" in script
    # `-q` 가 빠지면 psql 이 커맨드 태그(`DELETE n`)를 한 줄 더 찍어 0건도 1건으로 센다.
    assert " -Atq " in script


def test_counts_zero_when_nothing_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_run_sh(monkeypatch, stdout=b"")

    assert backup_db.delete_expired_withdrawn_identities("postgresql://unused", now=datetime.now(UTC)) == 0


def test_raises_when_psql_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_run_sh(monkeypatch, stdout=b"", returncode=1, stderr="psql: 연결 실패".encode())

    with pytest.raises(RuntimeError, match="연결 실패"):
        backup_db.delete_expired_withdrawn_identities("postgresql://unused", now=datetime.now(UTC))


def test_main_does_not_purge_when_backup_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """백업이 실패한 날의 상태가 지워지면 안 된다 — 덤프 예외가 파기 호출에 닿기 전에 전파돼야 한다."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/unused")
    monkeypatch.setattr(
        backup_db, "dump", lambda url, target: (_ for _ in ()).throw(RuntimeError("pg_dump 실패"))
    )
    purged = False

    def _spy_delete(url: str, *, now: datetime) -> int:
        nonlocal purged
        purged = True
        return 0

    monkeypatch.setattr(backup_db, "delete_expired_withdrawn_identities", _spy_delete)
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--out-dir", str(tmp_path)])

    with pytest.raises(RuntimeError, match="pg_dump 실패"):
        backup_db.main()

    assert purged is False


def test_main_purges_identities_after_a_successful_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """위 거절의 짝 — 백업이 성공하면 이메일 해시와 같은 자리에서 CI 해시도 파기한다."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/unused")
    monkeypatch.setenv("S3_BUCKET_NAME", "bucket-test")
    monkeypatch.delenv("HEALTHCHECKS_BACKUP_PING_URL", raising=False)
    monkeypatch.setattr(backup_db, "dump", lambda url, target: target.write_bytes(b"dump"))
    monkeypatch.setattr(backup_db, "upload", lambda *args, **kwargs: None)
    monkeypatch.setattr(backup_db, "prune", lambda *args, **kwargs: [])
    monkeypatch.setattr(backup_db, "check_r2_capacity", lambda *args, **kwargs: None)
    monkeypatch.setattr(backup_db, "delete_expired_withdrawn_emails", lambda url, *, now: 0)
    calls: list[str] = []

    def _spy_delete(url: str, *, now: datetime) -> int:
        calls.append(url)
        return 1

    monkeypatch.setattr(backup_db, "delete_expired_withdrawn_identities", _spy_delete)
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--out-dir", str(tmp_path)])

    assert backup_db.main() == 0
    assert len(calls) == 1
