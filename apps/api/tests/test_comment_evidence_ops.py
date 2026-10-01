"""신고 증거 파기의 만료 경계와 복원 성공 판정이 엇갈리지 않아야 한다."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ops import purge_comment_evidence, restore_db


def test_missing_comment_table_in_old_backup_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(purge_comment_evidence, "scalar", lambda sql, *, url: "")
    monkeypatch.setattr(purge_comment_evidence, "run_sh", lambda *args, **kwargs: pytest.fail("old schema UPDATE"))
    assert (
        purge_comment_evidence.purge_expired_comment_evidence(
            "postgresql://unused", now=datetime(2026, 9, 30, tzinfo=UTC)
        )
        == 0
    )


def test_purge_clears_only_expired_evidence_and_keeps_report_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(purge_comment_evidence, "scalar", lambda sql, *, url: "comment_reports")
    captured: list[str] = []

    def run(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured.append(script)
        return subprocess.CompletedProcess([], 0, stdout=b"id1\nid2\n", stderr=b"")

    monkeypatch.setattr(purge_comment_evidence, "run_sh", run)
    now = datetime(2026, 9, 30, tzinfo=UTC)
    assert purge_comment_evidence.purge_expired_comment_evidence("postgresql://unused", now=now) == 2
    assert "UPDATE comment_reports" in captured[0]
    assert "evidence_expires_at <=" in captured[0]
    assert now.isoformat() in captured[0]
    assert "evidence_body = NULL" in captured[0]
    assert "evidence_sticker_id = NULL" in captured[0]
    assert "evidence_mention_user_ids =" in captured[0]
    assert "DELETE" not in captured[0]
    assert " -Atq " in captured[0]


def test_purge_failure_stops_success_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(purge_comment_evidence, "scalar", lambda sql, *, url: "comment_reports")
    monkeypatch.setattr(
        purge_comment_evidence,
        "run_sh",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"denied"),
    )
    with pytest.raises(RuntimeError, match="denied"):
        purge_comment_evidence.purge_expired_comment_evidence("postgresql://unused", now=datetime.now(UTC))


def test_restore_purges_before_returning_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dump = tmp_path / "fixture.dump"
    dump.write_bytes(b"dump")
    order: list[str] = []

    def restore_command(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        order.append("restore")
        return subprocess.CompletedProcess([], 0, stderr=b"")

    monkeypatch.setattr(restore_db, "run_sh", restore_command)

    def purge(url: str, *, now: datetime) -> int:
        order.append("purge")
        assert url == "postgresql://unused"
        return 1

    monkeypatch.setattr(restore_db, "purge_expired_comment_evidence", purge)
    restore_db.restore(dump, "postgresql://unused")
    assert order == ["restore", "purge"]


def test_restore_scrub_failure_is_not_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dump = tmp_path / "fixture.dump"
    dump.write_bytes(b"dump")
    monkeypatch.setattr(restore_db, "run_sh", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stderr=b""))

    def purge(url: str, *, now: datetime) -> int:
        raise RuntimeError("scrub failed")

    monkeypatch.setattr(restore_db, "purge_expired_comment_evidence", purge)
    with pytest.raises(RuntimeError, match="scrub failed"):
        restore_db.restore(dump, "postgresql://unused")
