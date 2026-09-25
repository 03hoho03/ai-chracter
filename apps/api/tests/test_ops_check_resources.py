"""`ops/check_resources.py` — VM `free`/`df` 임계 감시 + healthchecks.io dead man's switch.

파싱·판정은 `free`/`df` **출력 문자열**을 받는 순수 함수라 실제 VM 없이 검증한다. `main()`은
그 순수 함수와 subprocess 호출부·알림·ping 배선만 잇는다는 걸 스텁으로 확인한다.
"""

import subprocess
from collections.abc import Callable

import pytest

import ops.check_resources as check_resources


def _recording(calls: list[str]) -> Callable[[str], bool]:
    """`notify(message)`/`ping(url)`을 흉내내며 호출 인자를 `calls`에 기록한다."""

    def _fake(value: str) -> bool:
        calls.append(value)
        return True

    return _fake


_FREE_HEALTHY = """\
               total        used        free      shared  buff/cache   available
Mem:            3919         890         120          12         2909        2909
Swap:              0           0           0
"""

_FREE_UNDER_PRESSURE = """\
               total        used        free      shared  buff/cache   available
Mem:            3919        3800          50          12           69          80
Swap:              0           0           0
"""

_DF_HEALTHY = """\
Filesystem     1K-blocks    Used Available Use% Mounted on
/dev/sda1       30832548 12545678  16000000  45% /
"""

_DF_FULL = """\
Filesystem     1K-blocks    Used Available Use% Mounted on
/dev/sda1       30832548 27832548   1000000  93% /
"""


def test_parse_memory_used_percent_reads_available_column() -> None:
    """`used` 컬럼이 아니라 `available`을 쓴다 — buff/cache 를 실사용으로 착각하면
    거의 항상 90% 넘게 나와 알림이 상시로 운다. 3919 total, 2909 available → 약 25.8% 사용."""
    used_percent = check_resources.parse_memory_used_percent(_FREE_HEALTHY)
    assert used_percent == pytest.approx((3919 - 2909) / 3919 * 100, abs=0.01)


def test_parse_memory_used_percent_raises_when_mem_line_missing() -> None:
    with pytest.raises(ValueError, match="Mem:"):
        check_resources.parse_memory_used_percent("Swap:  0  0  0\n")


def test_parse_disk_used_percent_reads_use_percent_column() -> None:
    assert check_resources.parse_disk_used_percent(_DF_HEALTHY) == 45.0


def test_parse_disk_used_percent_raises_when_mount_missing() -> None:
    with pytest.raises(ValueError, match="/data"):
        check_resources.parse_disk_used_percent(_DF_HEALTHY, mount="/data")


def test_check_memory_returns_none_when_under_threshold() -> None:
    assert check_resources.check_memory(_FREE_HEALTHY, threshold_percent=90) is None


def test_check_memory_returns_message_when_over_threshold() -> None:
    message = check_resources.check_memory(_FREE_UNDER_PRESSURE, threshold_percent=90)
    assert message is not None
    assert "메모리" in message


def test_check_disk_returns_none_when_under_threshold() -> None:
    assert check_resources.check_disk(_DF_HEALTHY, threshold_percent=85) is None


def test_check_disk_returns_message_when_over_threshold() -> None:
    message = check_resources.check_disk(_DF_FULL, threshold_percent=85)
    assert message is not None
    assert "디스크" in message


def test_main_notifies_once_per_breached_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.delenv("DISK_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.delenv("HEALTHCHECKS_RESOURCE_PING_URL", raising=False)

    def _fake_read(cmd: list[str]) -> str:
        return _FREE_UNDER_PRESSURE if cmd[0] == "free" else _DF_FULL

    monkeypatch.setattr(check_resources, "_read", _fake_read)
    sent: list[str] = []
    monkeypatch.setattr(check_resources, "notify", _recording(sent))
    monkeypatch.setattr("sys.argv", ["check_resources.py"])

    assert check_resources.main() == 0
    assert len(sent) == 2  # 메모리 1건 + 디스크 1건


def test_main_does_not_notify_when_resources_are_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_read(cmd: list[str]) -> str:
        return _FREE_HEALTHY if cmd[0] == "free" else _DF_HEALTHY

    monkeypatch.setattr(check_resources, "_read", _fake_read)
    sent: list[str] = []
    monkeypatch.setattr(check_resources, "notify", _recording(sent))
    monkeypatch.setattr("sys.argv", ["check_resources.py"])

    assert check_resources.main() == 0
    assert sent == []


def test_main_pings_dead_mans_switch_even_when_resources_are_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """죽지 않고 살아있다는 사실 자체가 신호다 — 임계 초과가 없을 때도 ping은 빠지면 안 된다.
    ping을 `if alerts:` 안으로 잘못 옮기면 이 테스트가 깨진다."""
    monkeypatch.setenv("HEALTHCHECKS_RESOURCE_PING_URL", "https://hc-ping.com/resource-check")

    def _fake_read(cmd: list[str]) -> str:
        return _FREE_HEALTHY if cmd[0] == "free" else _DF_HEALTHY

    monkeypatch.setattr(check_resources, "_read", _fake_read)
    monkeypatch.setattr(check_resources, "notify", lambda message: True)
    pinged: list[str] = []
    monkeypatch.setattr(check_resources, "ping", _recording(pinged))
    monkeypatch.setattr("sys.argv", ["check_resources.py"])

    assert check_resources.main() == 0
    assert pinged == ["https://hc-ping.com/resource-check"]


def test_main_skips_ping_when_url_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCHECKS_RESOURCE_PING_URL", raising=False)

    def _fake_read(cmd: list[str]) -> str:
        return _FREE_HEALTHY if cmd[0] == "free" else _DF_HEALTHY

    monkeypatch.setattr(check_resources, "_read", _fake_read)
    monkeypatch.setattr(check_resources, "notify", lambda message: True)
    pinged: list[str] = []
    monkeypatch.setattr(check_resources, "ping", _recording(pinged))
    monkeypatch.setattr("sys.argv", ["check_resources.py"])

    assert check_resources.main() == 0
    assert pinged == []


def test_read_raises_runtime_error_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="free: 명령 없음")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="명령 없음"):
        check_resources._read(["free", "-m"])
