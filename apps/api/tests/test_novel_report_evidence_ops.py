"""노벨·노벨 댓글 신고 증거 파기 — 만료된 사본만 비우고 신고 처리 기록은 남기는지, 옛 백업과 실패를 어떻게 다루는지."""

import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import NovelComment, NovelCommentReport, NovelReport, ReportReasonCategory, ReportStatus
from factories import _make_novel_tree, _make_user
from ops import purge_novel_report_evidence


def test_missing_table_in_old_backup_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(purge_novel_report_evidence, "scalar", lambda sql, *, url: "")
    monkeypatch.setattr(purge_novel_report_evidence, "run_sh", lambda *args, **kwargs: pytest.fail("old schema UPDATE"))
    assert (
        purge_novel_report_evidence.purge_expired_novel_report_evidence(
            "postgresql://unused", now=datetime(2026, 10, 9, tzinfo=UTC)
        )
        == 0
    )


def test_purge_failure_stops_success_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(purge_novel_report_evidence, "scalar", lambda sql, *, url: "novel_reports")
    monkeypatch.setattr(
        purge_novel_report_evidence,
        "run_sh",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"denied"),
    )
    with pytest.raises(RuntimeError, match="denied"):
        purge_novel_report_evidence.purge_expired_novel_report_evidence("postgresql://unused", now=datetime.now(UTC))


async def test_purge_clears_only_expired_evidence_in_both_tables(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """크론이 psql 로 보낼 SQL 을 그대로 테스트 DB 에 실행해 본다. 만료된 사본만 비우고(파기 시각을 적는다), 만료 전 사본과
    이미 파기한 행은 건드리지 않으며, 신고 사유·상태·대상 칸은 남긴다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    tree = await _make_novel_tree(db_session, user.id)
    comment = NovelComment(novel_id=tree.novel.id, chapter_id=tree.chapter.id, author_user_id=user.id, body="댓글")
    db_session.add(comment)
    await db_session.flush()
    now = datetime.now(UTC)
    earlier = now - timedelta(days=3)

    def novel_report(**overrides: Any) -> NovelReport:
        values: dict[str, Any] = {
            "reporter_user_id": user.id,
            "publisher_user_id": user.id,
            "novel_id": tree.novel.id,
            "reason_category": ReportReasonCategory.SPAM,
            "status": ReportStatus.PENDING,
            "evidence_title": "제목",
            "evidence_synopsis": "소개",
            "evidence_chapter_title": "화 제목",
            "evidence_body": "본문",
            "evidence_expires_at": now + timedelta(days=1),
            **overrides,
        }
        return NovelReport(**values)

    def comment_report(**overrides: Any) -> NovelCommentReport:
        values: dict[str, Any] = {
            "reporter_user_id": user.id,
            "comment_id": None,
            "novel_id": tree.novel.id,
            "comment_author_user_id": user.id,
            "reason_category": ReportReasonCategory.HATE,
            "status": ReportStatus.PENDING,
            "evidence_body": "댓글 사본",
            "evidence_expires_at": now + timedelta(days=1),
            **overrides,
        }
        return NovelCommentReport(**values)

    expired = novel_report(evidence_expires_at=now - timedelta(seconds=1))
    fresh = novel_report()
    already = novel_report(evidence_expires_at=now - timedelta(days=5), evidence_body="남은 값", evidence_purged_at=earlier)
    expired_comment = comment_report(comment_id=comment.id, evidence_expires_at=now)
    fresh_comment = comment_report()
    db_session.add_all([expired, fresh, already, expired_comment, fresh_comment])
    await db_session.commit()

    captured_sql: list[str] = []

    def run(script: str, *, url: str, stdin: object = None, stdout: object = None) -> subprocess.CompletedProcess[bytes]:
        captured_sql.append(script.split(" -c ", 1)[1][1:-1].replace("'\\''", "'"))
        return subprocess.CompletedProcess([], 0, stdout=b"a\nb\n", stderr=b"")

    monkeypatch.setattr(purge_novel_report_evidence, "scalar", lambda sql, *, url: "novel_reports")
    monkeypatch.setattr(purge_novel_report_evidence, "run_sh", run)
    assert purge_novel_report_evidence.purge_expired_novel_report_evidence("postgresql://unused", now=now) == 2
    returned = (await db_session.execute(sa.text(captured_sql[0]))).all()
    await db_session.commit()

    assert sorted(row[0] for row in returned) == sorted([expired.id, expired_comment.id])
    for row in (expired, fresh, already, expired_comment, fresh_comment):
        await db_session.refresh(row)
    assert (expired.evidence_title, expired.evidence_synopsis, expired.evidence_chapter_title, expired.evidence_body) == (
        None,
        None,
        None,
        None,
    )
    assert expired.evidence_purged_at == now
    assert (expired.reason_category, expired.status, expired.novel_id) == (
        ReportReasonCategory.SPAM,
        ReportStatus.PENDING,
        tree.novel.id,
    )
    assert (fresh.evidence_body, fresh.evidence_purged_at) == ("본문", None)
    assert (already.evidence_body, already.evidence_purged_at) == ("남은 값", earlier)
    assert (expired_comment.evidence_body, expired_comment.evidence_purged_at, expired_comment.comment_id) == (
        None,
        now,
        comment.id,
    )
    assert (fresh_comment.evidence_body, fresh_comment.evidence_purged_at) == ("댓글 사본", None)
