"""legal-revision-goal-prompt.md LR-32: 처리방침 제4조 2항·약관 제14조 4항이 약속한 "1년
보관 후 파기"를 실제로 수행하는 코드가 저장소에 없었다(LR-23이 "조회 시 무시"만으로 충분하다고
판단한 근거가 틀렸다 — VM 크론이 매일 `backup_db.py`를 돈다). 이 파일은 그 삭제 로직과, 백업이
실패하면 삭제도 일어나지 않는다는 순서 보장을 검증한다.

S5-e: `delete_expired_withdrawn_emails`는 더 이상 SQLAlchemy 세션을 받지 않는다 — 프로덕션
크론이 `api` 패키지도 SQLAlchemy도 없는 시스템 python3에서 돌기 때문이다(`ops/backup_db.py`
상단 경고 참고). 이제 `run_sh`(컨테이너 안 `psql`)라는 불투명한 경계를 통해서만 실제 삭제가
일어나므로, 여기서는 그 경계를 모킹해 (1) cutoff 계산·SQL 구성 (2) `RETURNING` 출력 줄 수
세기 (3) 실패 시 예외 전파를 검증한다. Postgres가 실제로 필터링하는지는 이 스위트가 검증하지
않는다 — `run_sh`가 매번 진짜 도커+psql을 부르므로, 이 워크트리의 격리 스택(5434/6381)을
docker 네트워크로 물어야 하는데 그 네트워크 이름은 워크트리마다 다르고 CI 러너 구성과도
달라 이식 가능한 단위 테스트로 못 박을 수 없다(불확실 — 실측 결론).
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import ops.backup_db as backup_db
from api.core.constants import WITHDRAWN_EMAIL_BLOCK_PERIOD


def test_block_period_matches_api_constant() -> None:
    """VM에 `api` 패키지가 없어 `backup_db.py`는 1년 상수를 로컬로 복제한다(파일 상단 경고 참고).
    이 테스트가 그 복제본과 `auth/router.py`가 조회에 쓰는 원본이 갈라지지 않는지 확인한다 —
    안 그러면 "차단이 풀리는 시점"과 "행이 파기되는 시점"이 조용히 어긋난다."""
    assert backup_db.WITHDRAWN_EMAIL_BLOCK_PERIOD == WITHDRAWN_EMAIL_BLOCK_PERIOD


def test_deletes_only_rows_past_the_shared_block_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """cutoff는 `now - WITHDRAWN_EMAIL_BLOCK_PERIOD`여야 한다 — `+`로 뒤집히거나 비교 방향이
    `>`로 뒤집히면 만료되지 않은 행까지 지우는 SQL이 나간다. 이 테스트는 실제로 생성된 SQL
    문자열에서 그 cutoff와 비교 연산자를 확인한다."""
    now = datetime(2026, 9, 15, 18, 0, 0, tzinfo=UTC)
    expected_cutoff = now - WITHDRAWN_EMAIL_BLOCK_PERIOD  # 원본 상수로 독립 계산

    captured: dict[str, str] = {}

    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"hmac-a\nhmac-b\n", stderr=b""
        )

    monkeypatch.setattr(backup_db, "run_sh", _fake_run_sh)

    removed = backup_db.delete_expired_withdrawn_emails("postgresql://unused", now=now)

    assert removed == 2
    assert expected_cutoff.isoformat() in captured["script"]
    assert "withdrawn_at <" in captured["script"]
    assert "DELETE FROM withdrawn_emails" in captured["script"]


def test_counts_zero_when_nothing_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """만료 조건을 "전부 삭제"로 잘못 구현해도 위 테스트는 통과한다 — `RETURNING`이 빈 출력을
    낼 때 0을 세는 이 테스트가 그 항진명제를 막는다."""

    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(backup_db, "run_sh", _fake_run_sh)

    removed = backup_db.delete_expired_withdrawn_emails(
        "postgresql://unused", now=datetime.now(UTC)
    )

    assert removed == 0


def test_raises_when_psql_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr="psql: 연결 실패".encode()
        )

    monkeypatch.setattr(backup_db, "run_sh", _fake_run_sh)

    with pytest.raises(RuntimeError, match="연결 실패"):
        backup_db.delete_expired_withdrawn_emails("postgresql://unused", now=datetime.now(UTC))


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

    def _spy_delete(url: str, *, now: datetime) -> int:
        nonlocal purged
        purged = True
        return 0

    monkeypatch.setattr(backup_db, "delete_expired_withdrawn_emails", _spy_delete)
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--out-dir", str(tmp_path)])

    with pytest.raises(RuntimeError, match="pg_dump 실패"):
        backup_db.main()

    assert purged is False
