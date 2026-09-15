"""R2 용량 임계 알림(monitoring-techspec.md MT-12).

새 스크립트·새 크론·새 Cloudflare 토큰 없이 기존 `aws()` 헬퍼로 `aws s3 ls --recursive
--summarize`를 한 번 더 불러 총 바이트를 읽는다. `prune()`이 이미 밟아 둔 함정(빈 프리픽스에서
`exit 1` + 빈 stderr)을 여기서도 같은 방식으로 피해야 한다 — 이 테스트가 그 회귀를 잡는다.
"""

import subprocess
from collections.abc import Callable

import pytest

import ops.backup_db as backup_db


def _recording_notify(calls: list[str]) -> Callable[[str], bool]:
    """`notify(message)`를 흉내내며 호출된 메시지를 `calls`에 기록한다."""

    def _fake(message: str) -> bool:
        calls.append(message)
        return True

    return _fake


_SUMMARY_OUTPUT = (
    "2026-09-01 03:00:01     311296 assets/profile/9f3c.png\n"
    "2026-09-14 03:00:02   1048576 backup/daily/20260914T030002Z.dump\n"
    "\n"
    "Total Objects: 2\n"
    "   Total Size: 1359872\n"
)


def test_parse_s3_summary_reads_total_size_bytes() -> None:
    assert backup_db.parse_s3_summary(_SUMMARY_OUTPUT) == 1359872


def test_parse_s3_summary_does_not_confuse_total_objects_with_total_size() -> None:
    """`Total Objects:`도 `Total`로 시작한다 — 접두어 매칭이 느슨하면 객체 개수를 바이트로
    오인해 임계값과 전혀 다른 스케일로 비교하게 된다."""
    text = "Total Objects: 999999999\n   Total Size: 100\n"
    assert backup_db.parse_s3_summary(text) == 100


def test_parse_s3_summary_raises_when_summary_line_missing() -> None:
    with pytest.raises(ValueError, match="Total Size"):
        backup_db.parse_s3_summary("2026-09-01 03:00:01     311296 assets/profile/9f3c.png\n")


def test_check_r2_capacity_notifies_when_over_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R2_CAPACITY_THRESHOLD_BYTES", raising=False)  # 기본값(10GB) 사용

    def _fake_aws(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert args[:3] == ["s3", "ls", "s3://test-bucket/"]
        assert "--recursive" in args
        assert "--summarize" in args
        summary = "Total Objects: 1\n   Total Size: 11000000000\n"  # 11GB > 기본 10GB
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=summary.encode(), stderr=b"")

    monkeypatch.setattr(backup_db, "aws", _fake_aws)
    sent: list[str] = []
    monkeypatch.setattr(backup_db, "notify", _recording_notify(sent))

    backup_db.check_r2_capacity("test-bucket")

    assert len(sent) == 1
    assert "GB" in sent[0]


def test_check_r2_capacity_does_not_notify_when_under_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R2_CAPACITY_THRESHOLD_BYTES", raising=False)

    def _fake_aws(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        summary = "Total Objects: 1\n   Total Size: 100\n"  # 100바이트 << 10GB
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=summary.encode(), stderr=b"")

    monkeypatch.setattr(backup_db, "aws", _fake_aws)
    sent: list[str] = []
    monkeypatch.setattr(backup_db, "notify", _recording_notify(sent))

    backup_db.check_r2_capacity("test-bucket")

    assert sent == []


def test_check_r2_capacity_treats_empty_bucket_as_zero_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """`prune()`이 이미 겪은 함정과 같다 — 객체가 하나도 없으면 `aws s3 ls`가 exit 1을 내는데,
    그때는 stderr도 비어 있다. 이걸 진짜 오류로 취급하면 막 만든 빈 버킷에서 매번 알림이 뜬다."""

    def _fake_aws(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(backup_db, "aws", _fake_aws)
    sent: list[str] = []
    monkeypatch.setattr(backup_db, "notify", _recording_notify(sent))

    backup_db.check_r2_capacity("test-bucket")  # 예외 없이 조용히 끝나야 한다

    assert sent == []


def test_check_r2_capacity_raises_on_real_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_aws(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"AccessDenied"
        )

    monkeypatch.setattr(backup_db, "aws", _fake_aws)

    with pytest.raises(RuntimeError, match="AccessDenied"):
        backup_db.check_r2_capacity("test-bucket")


def test_check_r2_capacity_threshold_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본값(10GB)로는 안 울릴 작은 용량도, 임계값을 낮추면 울려야 한다 — env var가 실제로
    읽히는지 확인한다(항상 기본값만 검증하면 이 배선이 죽어도 위 테스트들은 계속 통과한다)."""
    monkeypatch.setenv("R2_CAPACITY_THRESHOLD_BYTES", "1000")

    def _fake_aws(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        summary = "Total Objects: 1\n   Total Size: 2000\n"
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=summary.encode(), stderr=b"")

    monkeypatch.setattr(backup_db, "aws", _fake_aws)
    sent: list[str] = []
    monkeypatch.setattr(backup_db, "notify", _recording_notify(sent))

    backup_db.check_r2_capacity("test-bucket")

    assert len(sent) == 1


def test_malformed_threshold_env_var_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """오타난 설정값이 `backup_db.py`의 좁은 `except (RuntimeError, KeyError)` 밖(ValueError)으로
    새 나가면 `__main__` 가드가 못 잡아 실패 ping도 안 나간다 — RuntimeError로 갈아 끼워야 한다."""
    monkeypatch.setenv("R2_CAPACITY_THRESHOLD_BYTES", "not-a-number")

    def _fake_aws(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        summary = "Total Objects: 1\n   Total Size: 100\n"
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=summary.encode(), stderr=b"")

    monkeypatch.setattr(backup_db, "aws", _fake_aws)

    with pytest.raises(RuntimeError, match="R2_CAPACITY_THRESHOLD_BYTES"):
        backup_db.check_r2_capacity("test-bucket")
