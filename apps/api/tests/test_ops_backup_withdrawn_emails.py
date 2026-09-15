"""legal-revision-goal-prompt.md LR-32: 처리방침 제4조 2항·약관 제14조 4항이 약속한 "1년
보관 후 파기"를 실제로 수행하는 코드가 저장소에 없었다(LR-23이 "조회 시 무시"만으로 충분하다고
판단한 근거가 틀렸다 — VM 크론이 매일 `backup_db.py`를 돈다). 이 파일은 그 삭제 로직과, 백업이
실패하면 삭제도 일어나지 않는다는 순서 보장을 검증한다.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops.backup_db as backup_db
from api.db.models.auth import WithdrawnEmail


def _make_withdrawn_email(*, withdrawn_at: datetime) -> WithdrawnEmail:
    return WithdrawnEmail(email_hmac="hmac-" + uuid.uuid4().hex, withdrawn_at=withdrawn_at)


async def test_deletes_withdrawn_email_past_block_period(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    row = _make_withdrawn_email(withdrawn_at=now - timedelta(days=366))
    db_session.add(row)
    await db_session.flush()

    removed = await backup_db.delete_expired_withdrawn_emails(db_session, now=now)

    assert removed == 1
    assert await db_session.get(WithdrawnEmail, row.email_hmac) is None


async def test_keeps_withdrawn_email_within_block_period(db_session: AsyncSession) -> None:
    """만료 조건을 "전부 삭제"로 잘못 구현해도 위 테스트는 통과한다 — 이 테스트가 그 항진명제를 막는다."""
    now = datetime.now(UTC)
    row = _make_withdrawn_email(withdrawn_at=now - timedelta(days=364))
    db_session.add(row)
    await db_session.flush()

    removed = await backup_db.delete_expired_withdrawn_emails(db_session, now=now)

    assert removed == 0
    assert await db_session.get(WithdrawnEmail, row.email_hmac) is not None


def test_main_does_not_purge_when_backup_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`dump()`가 실패하면(pg_dump 에러) 그 예외가 곧장 전파되어, 뒤에 있는 만료 삭제 호출까지
    아예 도달하지 못해야 한다 — 백업이 실패한 날의 상태가 지워지면 안 되기 때문이다."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/unused")
    monkeypatch.setattr(
        backup_db,
        "dump",
        lambda url, target: (_ for _ in ()).throw(RuntimeError("pg_dump 실패")),
    )

    purged = False

    async def _spy_purge() -> int:
        nonlocal purged
        purged = True
        return 0

    monkeypatch.setattr(backup_db, "_purge_expired_withdrawn_emails", _spy_purge)
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--out-dir", str(tmp_path)])

    with pytest.raises(RuntimeError, match="pg_dump 실패"):
        backup_db.main()

    assert purged is False
