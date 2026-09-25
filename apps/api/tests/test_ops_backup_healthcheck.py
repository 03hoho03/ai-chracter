"""`backup_db.py` 의 healthchecks.io check-in.

세 지점 — `main()` 진입부(start) / 성공 직전(성공) / `__main__` 의 실패 처리(실패) — 를
검증한다. 놓치기 쉬운 두 가지를 특히 고정한다:

1. **`--no-upload` 는 크론이 안 쓰는 로컬 전용 경로라 성공 ping을 보내면 안 된다** — 보내면
   실제로는 R2에 아무것도 안 올라갔는데 healthchecks.io에는 "오늘 백업 성공"으로 찍힌다.
2. **ping 자체의 실패가 백업을 죽이면 안 된다** — `ops.notify.ping`이 이미 예외를 삼키므로
   (`test_ops_notify.py`), 여기서는 그 계약을 신뢰하고 "언제 어떤 URL로 호출되는가"만 본다.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

import ops.backup_db as backup_db


def _recording_ping(calls: list[str]) -> Callable[[str], bool]:
    """`ping(url)`을 흉내내며 호출된 URL을 `calls`에 기록한다."""

    def _fake(url: str) -> bool:
        calls.append(url)
        return True

    return _fake


def _stub_successful_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    """dump/upload/prune/R2 용량/파기를 전부 성공으로 스텁해 ping 배선만 남긴다."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(backup_db, "dump", lambda url, target: target.write_bytes(b"dump"))
    monkeypatch.setattr(backup_db, "upload", lambda local, bucket, key: None)
    monkeypatch.setattr(backup_db, "prune", lambda bucket, prefix, keep: [])
    monkeypatch.setattr(backup_db, "check_r2_capacity", lambda bucket: None)
    monkeypatch.setattr(backup_db, "delete_expired_withdrawn_emails", lambda url, *, now: 0)


def test_healthcheck_skips_ping_when_url_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCHECKS_BACKUP_PING_URL", raising=False)
    called: list[str] = []
    monkeypatch.setattr(backup_db, "ping", _recording_ping(called))

    backup_db._healthcheck("/start")

    assert called == []


def test_healthcheck_appends_suffix_to_configured_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHCHECKS_BACKUP_PING_URL", "https://hc-ping.com/abc123")
    called: list[str] = []
    monkeypatch.setattr(backup_db, "ping", _recording_ping(called))

    backup_db._healthcheck("/fail")

    assert called == ["https://hc-ping.com/abc123/fail"]


def test_main_pings_start_then_success_on_full_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HEALTHCHECKS_BACKUP_PING_URL", "https://hc-ping.com/abc123")
    _stub_successful_backup(monkeypatch)
    called: list[str] = []
    monkeypatch.setattr(backup_db, "ping", _recording_ping(called))
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--out-dir", str(tmp_path)])

    assert backup_db.main() == 0

    assert called == [
        "https://hc-ping.com/abc123/start",
        "https://hc-ping.com/abc123",
    ]


def test_main_with_no_upload_pings_start_but_not_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """크론은 `--no-upload`를 쓰지 않는다 — 이 경로에 성공 ping을 넣으면 실제 업로드 없이도
    healthchecks.io에 성공으로 찍혀, 크론이 조용히 죽어도 아무도 모르게 되는 것과 같은 위험이
    이 플래그를 쓰는 수동 실행에서도 재현된다."""
    monkeypatch.setenv("HEALTHCHECKS_BACKUP_PING_URL", "https://hc-ping.com/abc123")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setattr(backup_db, "dump", lambda url, target: target.write_bytes(b"dump"))
    called: list[str] = []
    monkeypatch.setattr(backup_db, "ping", _recording_ping(called))
    monkeypatch.setattr(
        "sys.argv", ["backup_db.py", "--out-dir", str(tmp_path), "--no-upload", "--keep-local"]
    )

    assert backup_db.main() == 0

    assert called == ["https://hc-ping.com/abc123/start"]


def test_on_failure_prints_message_and_pings_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HEALTHCHECKS_BACKUP_PING_URL", "https://hc-ping.com/abc123")
    called: list[str] = []
    monkeypatch.setattr(backup_db, "ping", _recording_ping(called))

    exit_code = backup_db._on_failure(RuntimeError("pg_dump 실패"))

    assert exit_code == 1
    assert called == ["https://hc-ping.com/abc123/fail"]
    assert "pg_dump 실패" in capsys.readouterr().err


def test_on_failure_without_configured_url_does_not_call_ping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HEALTHCHECKS_BACKUP_PING_URL", raising=False)
    called: list[str] = []
    monkeypatch.setattr(backup_db, "ping", _recording_ping(called))

    exit_code = backup_db._on_failure(KeyError("DATABASE_URL"))

    assert exit_code == 1
    assert called == []
