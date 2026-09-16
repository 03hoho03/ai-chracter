"""`ops/purge_image_requests.py` — image-monitoring-goal-prompt.md IM-7a: 이미지가 남지 않은
생성 요청(`status IN ('blocked', 'failed')`)을 `created_at`으로부터 90일 뒤 파기한다.

`test_ops_backup_withdrawn_emails.py`(같은 `run_sh` 경계 모킹 패턴)를 그대로 베꼈다. Postgres가
실제로 필터링하는지는 이 스위트가 검증하지 않는다 — `run_sh`를 모킹해 (1) cutoff 계산·SQL 구성
(2) `RETURNING` 출력 줄 수 세기 (3) 실패 시 예외 전파·Discord 알림 배선만 확인한다.
"""

import subprocess
from datetime import UTC, datetime, timedelta

import pytest

import ops.purge_image_requests as purge_image_requests


def test_generates_delete_sql_scoped_to_blocked_and_failed_with_correct_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """깨지는 시나리오: cutoff가 `now + 90일`로 뒤집히거나 비교 연산자가 `>`로 뒤집히면 아직
    보관기간이 남은 행까지 지우는 SQL이 나간다. 생성된 SQL 문자열에서 cutoff·비교 방향·대상
    테이블을 직접 확인한다."""
    now = datetime(2026, 9, 16, 6, 0, 0, tzinfo=UTC)
    expected_cutoff = now - purge_image_requests.BLOCKED_OR_FAILED_REQUEST_RETENTION

    captured: dict[str, str] = {}

    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"id-a\nid-b\n", stderr=b""
        )

    monkeypatch.setattr(purge_image_requests, "run_sh", _fake_run_sh)

    removed = purge_image_requests.purge_expired_image_requests("postgresql://unused", now=now)

    assert removed == 2
    assert "DELETE FROM image_generation_requests" in captured["script"]
    assert expected_cutoff.isoformat() in captured["script"]
    assert "created_at <" in captured["script"]


def test_status_filter_excludes_succeeded_and_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: status 필터가 `IN ('blocked', 'failed')`에서 벗어나(예: 조건이 통째로
    빠지거나 `!=` 로 반전되어) `succeeded`·`pending` 행까지 SQL 대상에 걸리면, 이미지가 남아
    있는(IM-7이 별도로 정한) 요청이나 아직 진행 중인 요청까지 지우는 SQL이 나간다."""
    captured: dict[str, str] = {}

    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(purge_image_requests, "run_sh", _fake_run_sh)

    purge_image_requests.purge_expired_image_requests(
        "postgresql://unused", now=datetime.now(UTC)
    )

    # `shell_quote`가 SQL 안의 작은따옴표를 `'\''`로 이스케이프해 원문 그대로는 안 남는다 —
    # 대신 구성요소별로 확인한다.
    assert "status IN (" in captured["script"]
    assert "blocked" in captured["script"]
    assert "failed" in captured["script"]
    assert "succeeded" not in captured["script"]
    assert "pending" not in captured["script"]


def test_retention_is_exactly_90_days_91_old_deleted_89_old_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """깨지는 시나리오: 90일 상수가 89일이나 91일로 오프바이원 나면 이 테스트가 깨진다.

    ⚠️ cutoff를 `purge_image_requests.BLOCKED_OR_FAILED_REQUEST_RETENTION`에서 다시 계산하면
    상수 자체가 틀려도 자기 자신과만 비교해 항상 통과하는 항진명제가 된다 — 그래서 여기서는
    90을 테스트 안에 직접 못박고, 실제로 생성된 SQL에 그 cutoff가 들어 있는지 대조한다. 실제
    DB 필터링은 이 스위트가 검증하지 않으므로(모킹 경계, `run_sh`가 진짜 psql을 부르지 않음)
    그 cutoff 기준으로 91일 전 행은 `created_at < cutoff`(삭제 대상), 89일 전 행은 그 반대
    (보존 대상)임을 datetime 비교로 함께 확인한다."""
    now = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)
    hardcoded_90_day_cutoff = now - timedelta(days=90)  # 모듈 상수를 참조하지 않는다

    captured: dict[str, str] = {}

    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(purge_image_requests, "run_sh", _fake_run_sh)

    purge_image_requests.purge_expired_image_requests("postgresql://unused", now=now)

    assert hardcoded_90_day_cutoff.isoformat() in captured["script"]
    assert now - timedelta(days=91) < hardcoded_90_day_cutoff  # 91일 전 → 삭제 대상
    assert now - timedelta(days=89) >= hardcoded_90_day_cutoff  # 89일 전 → 보존 대상


def test_missing_dash_q_would_overcount_by_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: `-Atq`에서 `-q`가 빠지면(`-At`로 되돌아가면) `RETURNING`이 있는 DML 뒤
    `psql`이 결과 행과 별개로 커맨드 태그(`DELETE 0`)를 한 줄 더 찍어 0건을 지웠을 때도 1건으로
    센다(`backup_db.py`의 프로덕션 실측 회귀와 동일). 여기서는 생성된 스크립트에 `-Atq`가 실제로
    쓰였는지를 직접 못박는다 — mock의 빈 stdout만으로는 `-q` 누락을 잡지 못한다."""
    captured: dict[str, str] = {}

    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        # 실제 `psql -Atq -c "... RETURNING ...;"` 출력(0행): `-q`가 커맨드 태그까지 억제해
        # 완전히 빈 stdout이다.
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(purge_image_requests, "run_sh", _fake_run_sh)

    removed = purge_image_requests.purge_expired_image_requests(
        "postgresql://unused", now=datetime.now(UTC)
    )

    assert removed == 0
    assert " -Atq " in captured["script"]


def test_raises_when_psql_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: `run_sh`가 실패(nonzero exit)했는데 예외로 전파하지 않으면, 파기가
    실제로는 안 됐는데도 크론이 성공으로 남아 실패 알림도 나가지 않는다."""

    def _fake_run_sh(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr="psql: 연결 실패".encode()
        )

    monkeypatch.setattr(purge_image_requests, "run_sh", _fake_run_sh)

    with pytest.raises(RuntimeError, match="연결 실패"):
        purge_image_requests.purge_expired_image_requests(
            "postgresql://unused", now=datetime.now(UTC)
        )


def test_on_failure_notifies_discord_and_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: 실패 시 `notify()` 배선이 빠지면, 매일 도는 파기 크론이 조용히 죽어도
    아무도 모른다 — 프로덕션 백업 크론이 실제로 이 사고를 낸 적이 있다(backup_db.py 상단 경고)."""
    sent: list[str] = []

    def _fake_notify(message: str) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(purge_image_requests, "notify", _fake_notify)

    exit_code = purge_image_requests._on_failure(RuntimeError("psql: 연결 실패"))

    assert exit_code == 1
    assert len(sent) == 1
    assert "연결 실패" in sent[0]


def test_main_propagates_exception_without_notifying(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: `main()`이 실패를 삼키면(예: 넓은 `except`로 감싸면) `__main__`의
    `_on_failure` 알림 배선까지 도달하지 못해 실패가 완전히 조용해진다. `main()` 자신은 예외를
    삼키지 않고 그대로 올려야 한다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["purge_image_requests.py"])

    with pytest.raises(KeyError):
        purge_image_requests.main()
