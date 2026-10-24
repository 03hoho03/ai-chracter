"""수동 백업(`--manual`)과 매일 크론 백업이 R2 보관 칸을 나눠 쓰지 않는지 고정한다.

보관은 프리픽스별 갯수 기준이다. 수동 백업이 `daily/` 에 올라가면 뜰 때마다 가장 오래된 일단위 사본이
하나씩 지워진다 — 마이그레이션 병합마다 손으로 백업을 뜨면 하루 다섯 번으로 닷새치 일단위 사본이 사라진다.
그래서 두 경로가 **어디에 올리고 어디를 정리하는지**와, 수동 경로가 크론의 healthchecks.io 체크를 건드리지
않는지를 본다. 업로드·정리·덤프는 전부 스텁이라 R2·DB 에 닿지 않는다.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

import ops.backup_db as backup_db

SUNDAY = datetime(2026, 10, 25, 18, 0, tzinfo=UTC)


def _recording_ping(calls: list[str]) -> Callable[[str], bool]:
    def _fake(url: str) -> bool:
        calls.append(url)
        return True

    return _fake


class _SundayDatetime(datetime):
    """주단위 사본이 붙는 일요일로 시각을 고정한다 — 수동 경로가 `weekly/` 에도 새지 않는지 보려면 필요하다."""

    @classmethod
    def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
        return SUNDAY


def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *extra_args: str
) -> tuple[list[str], list[tuple[str, int]], list[str]]:
    """스텁 위에서 `main()` 을 돌리고 (올린 키, 정리한 (프리픽스, 보관 수), 보낸 ping) 을 돌려준다."""
    uploaded: list[str] = []
    pruned: list[tuple[str, int]] = []
    pinged: list[str] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("HEALTHCHECKS_BACKUP_PING_URL", "https://hc-ping.com/abc123")
    monkeypatch.delenv("BACKUP_PREFIX", raising=False)
    monkeypatch.setattr(backup_db, "datetime", _SundayDatetime)
    monkeypatch.setattr(backup_db, "dump", lambda url, target: target.write_bytes(b"dump"))
    monkeypatch.setattr(backup_db, "upload", lambda local, bucket, key: uploaded.append(key))

    def _prune(bucket: str, prefix: str, keep: int) -> list[str]:
        pruned.append((prefix, keep))
        return []

    monkeypatch.setattr(backup_db, "prune", _prune)
    monkeypatch.setattr(backup_db, "check_r2_capacity", lambda bucket: None)
    monkeypatch.setattr(backup_db, "delete_expired_withdrawn_emails", lambda url, *, now: 0)
    monkeypatch.setattr(backup_db, "delete_expired_withdrawn_identities", lambda url, *, now: 0)
    monkeypatch.setattr(backup_db, "ping", _recording_ping(pinged))
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--out-dir", str(tmp_path), *extra_args])

    assert backup_db.main() == 0
    return uploaded, pruned, pinged


def test_manual_backup_uploads_and_prunes_only_manual_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    uploaded, pruned, _ = _run(monkeypatch, tmp_path, "--manual")

    assert uploaded == ["backup/manual/20261025T180000Z.dump"]
    assert pruned == [("backup/manual/", backup_db.MANUAL_KEEP)]


def test_manual_backup_sends_no_healthcheck_ping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """healthchecks.io 체크는 매일 크론이 돌았는지를 본다. 손으로 뜬 백업이 start·성공을 찍으면 크론이
    빠진 날을 가리고, 실패를 찍으면 크론이 멀쩡한데 경보가 울린다."""
    _, _, pinged = _run(monkeypatch, tmp_path, "--manual")

    assert pinged == []


def test_manual_backup_failure_sends_no_fail_ping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """실패 ping 은 `main()` 밖 `_on_failure` 가 보낸다 — 수동 실행이 거기까지 꺼 두는지 본다."""
    monkeypatch.setenv("HEALTHCHECKS_BACKUP_PING_URL", "https://hc-ping.com/abc123")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

    def _failing_dump(url: str, target: Path) -> None:
        raise RuntimeError("pg_dump 실패")

    monkeypatch.setattr(backup_db, "dump", _failing_dump)
    pinged: list[str] = []
    monkeypatch.setattr(backup_db, "ping", _recording_ping(pinged))
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--out-dir", str(tmp_path), "--manual"])

    with pytest.raises(RuntimeError) as caught:
        backup_db.main()
    assert backup_db._on_failure(caught.value) == 1

    assert pinged == []


def test_cron_backup_keeps_daily_and_weekly_and_never_touches_manual(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    uploaded, pruned, pinged = _run(monkeypatch, tmp_path)

    assert uploaded == [
        "backup/daily/20261025T180000Z.dump",
        "backup/weekly/20261025T180000Z.dump",
    ]
    assert pruned == [
        ("backup/daily/", backup_db.DAILY_KEEP),
        ("backup/weekly/", backup_db.WEEKLY_KEEP),
    ]
    assert pinged == ["https://hc-ping.com/abc123/start", "https://hc-ping.com/abc123"]


def test_backup_sh_forwards_arguments_to_backup_db() -> None:
    """`backup.sh` 가 인자를 넘기지 않으면 `backup.sh --manual` 이 아무 오류 없이 일단위 백업이 되어
    일단위 보관 칸을 다시 먹는다. VM 에서만 돌 수 있는 스크립트라 실행 대신 `exec` 줄을 읽는다."""
    script = Path(__file__).resolve().parents[3] / "ops" / "backup.sh"
    exec_lines = [line for line in script.read_text().splitlines() if line.startswith("exec ")]

    assert len(exec_lines) == 1
    assert "-m ops.backup_db" in exec_lines[0]
    assert exec_lines[0].rstrip().endswith('"$@"')
