"""`ops/check_resources.py` — VM `free`/`df` 임계 감시 + healthchecks.io dead man's switch.

파싱·판정은 `free`/`df` **출력 문자열**을 받는 순수 함수라 실제 VM 없이 검증한다. `main()`은
그 순수 함수와 subprocess 호출부·알림·ping 배선만 잇는다는 걸 스텁으로 확인한다.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import ops.check_resources as check_resources


def _recording(calls: list[str]) -> Callable[[str], bool]:
    """`notify(message)`/`ping(url)`을 흉내내며 호출 인자를 `calls`에 기록한다."""

    def _fake(value: str) -> bool:
        calls.append(value)
        return True

    return _fake


def _argv(tmp_path: Path) -> list[str]:
    """`--state-file`·`--worker-state-file` 은 필수 인자다 — 테스트가 운영 경로(`/var/lib/ddona/...`)를 읽거나 쓰지 않게
    매번 임시 경로를 준다. 워커 기대 상태 파일은 만들지 않으면 없음(= 꺼짐)이라 워커는 감시하지 않는다."""
    return [
        "check_resources.py",
        "--state-file",
        str(tmp_path / "resource-check.state"),
        "--worker-state-file",
        str(tmp_path / "novelize_worker"),
    ]


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


def test_main_notifies_once_per_breached_resource(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MEMORY_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.delenv("DISK_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.delenv("HEALTHCHECKS_RESOURCE_PING_URL", raising=False)

    def _fake_read(cmd: list[str]) -> str:
        return _FREE_UNDER_PRESSURE if cmd[0] == "free" else _DF_FULL

    monkeypatch.setattr(check_resources, "_read", _fake_read)
    sent: list[str] = []
    monkeypatch.setattr(check_resources, "notify", _recording(sent))
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    assert check_resources.main() == 0
    assert len(sent) == 2  # 메모리 1건 + 디스크 1건


def test_main_does_not_notify_when_resources_are_healthy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake_read(cmd: list[str]) -> str:
        return _FREE_HEALTHY if cmd[0] == "free" else _DF_HEALTHY

    monkeypatch.setattr(check_resources, "_read", _fake_read)
    sent: list[str] = []
    monkeypatch.setattr(check_resources, "notify", _recording(sent))
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    assert check_resources.main() == 0
    assert sent == []


def test_main_pings_dead_mans_switch_even_when_resources_are_healthy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    assert check_resources.main() == 0
    assert pinged == ["https://hc-ping.com/resource-check"]


def test_main_skips_ping_when_url_not_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HEALTHCHECKS_RESOURCE_PING_URL", raising=False)

    def _fake_read(cmd: list[str]) -> str:
        return _FREE_HEALTHY if cmd[0] == "free" else _DF_HEALTHY

    monkeypatch.setattr(check_resources, "_read", _fake_read)
    monkeypatch.setattr(check_resources, "notify", lambda message: True)
    pinged: list[str] = []
    monkeypatch.setattr(check_resources, "ping", _recording(pinged))
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    assert check_resources.main() == 0
    assert pinged == []


def test_read_raises_runtime_error_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="free: 명령 없음")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="명령 없음"):
        check_resources._read(["free", "-m"])


# ── 상태 전환 알림 ────────────────────────────────────────────────────────────
# 5분마다 도는 크론이 같은 경고를 매번 보내면 채널이 같은 줄로 덮여 정작 새 경고가 묻힌다.
# 그래서 항목(메모리·디스크)별로 마지막 상태를 파일에 남기고, 상태가 바뀔 때만 보낸다.

_NOW = 1_759_550_000.0
_DAY = 24 * 60 * 60


def _healthy_state() -> dict[str, check_resources.ItemState]:
    return {
        "memory": {"alerting": False, "last_notified_at": None},
        "disk": {"alerting": False, "last_notified_at": None},
        "novelize_worker": {"alerting": False, "last_notified_at": None},
    }


def test_decide_notifies_once_when_resource_crosses_threshold() -> None:
    to_send, next_state = check_resources.decide(
        _healthy_state(), {"memory": "메모리 사용률 95.0% (임계값 90%)", "disk": None}, now=_NOW
    )

    assert list(to_send) == ["memory"]
    assert "메모리 사용률 95.0%" in to_send["memory"]
    assert next_state["memory"] == {"alerting": True, "last_notified_at": _NOW}
    assert next_state["disk"] == {"alerting": False, "last_notified_at": None}


def test_decide_stays_silent_while_alert_persists_within_a_day() -> None:
    """같은 경고가 이어지는 동안 5분마다 다시 보내면 채널이 같은 줄로 덮인다 — 하루 안에는 보내지 않는다.
    값이 더 나빠져도(95%→97%) 다시 보내지 않는다 — 상태(경고 중)가 바뀌지 않았기 때문이다."""
    previous = _healthy_state()
    previous["disk"] = {"alerting": True, "last_notified_at": _NOW - (_DAY - 1)}

    to_send, next_state = check_resources.decide(
        previous, {"memory": None, "disk": "디스크(/) 사용률 97.0% (임계값 85%)"}, now=_NOW
    )

    assert to_send == {}
    assert next_state["disk"] == {"alerting": True, "last_notified_at": _NOW - (_DAY - 1)}


def test_decide_renotifies_once_a_day_while_alert_persists() -> None:
    """첫 알림이 묻혔을 때를 대비해 경고가 이어지면 24시간마다 한 번 다시 보낸다."""
    previous = _healthy_state()
    previous["disk"] = {"alerting": True, "last_notified_at": _NOW - _DAY}

    to_send, next_state = check_resources.decide(
        previous, {"memory": None, "disk": "디스크(/) 사용률 97.0% (임계값 85%)"}, now=_NOW
    )

    assert list(to_send) == ["disk"]
    assert "디스크(/) 사용률 97.0%" in to_send["disk"]
    assert "지속" in to_send["disk"]
    assert next_state["disk"] == {"alerting": True, "last_notified_at": _NOW}


def test_decide_sends_one_recovery_notice_then_stays_silent() -> None:
    previous = _healthy_state()
    previous["memory"] = {"alerting": True, "last_notified_at": _NOW - 600}

    to_send, next_state = check_resources.decide(previous, {"memory": None, "disk": None}, now=_NOW)

    assert list(to_send) == ["memory"]
    assert "복구" in to_send["memory"]
    assert next_state["memory"]["alerting"] is False

    to_send_again, _ = check_resources.decide(next_state, {"memory": None, "disk": None}, now=_NOW + 300)
    assert to_send_again == {}


def test_load_state_treats_missing_file_as_healthy(tmp_path: Path) -> None:
    """못 읽으면 "정상, 알린 적 없음" 으로 본다 — 경고 중이면 다음 실행이 한 번 더 보낸다(놓치는 것보다 중복이 낫다)."""
    assert check_resources.load_state(tmp_path / "없음.state") == _healthy_state()


@pytest.mark.parametrize(
    "content",
    [
        "{깨진 json",
        "[]",
        '{"memory": "alerting", "disk": {"alerting": "yes", "last_notified_at": null}}',
        '{"memory": {"alerting": true, "last_notified_at": "어제"}}',
    ],
)
def test_load_state_treats_corrupt_entries_as_healthy(tmp_path: Path, content: str) -> None:
    path = tmp_path / "resource-check.state"
    path.write_text(content)

    assert check_resources.load_state(path) == _healthy_state()


def test_load_state_keeps_valid_entry_when_another_entry_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "resource-check.state"
    path.write_text(json.dumps({"memory": {"alerting": True, "last_notified_at": _NOW}, "disk": 3}))

    state = check_resources.load_state(path)

    assert state["memory"] == {"alerting": True, "last_notified_at": _NOW}
    assert state["disk"] == {"alerting": False, "last_notified_at": None}


def _breached_disk_read(cmd: list[str]) -> str:
    return _FREE_HEALTHY if cmd[0] == "free" else _DF_FULL


def test_main_does_not_repeat_alert_on_next_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """크론이 5분 뒤 같은 상태로 다시 돌면 아무것도 보내지 않는다 — 상태가 파일로 실행을 건너간다."""
    monkeypatch.delenv("DISK_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.setattr(check_resources, "_read", _breached_disk_read)
    sent: list[str] = []
    monkeypatch.setattr(check_resources, "notify", _recording(sent))
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    assert check_resources.main() == 0
    assert check_resources.main() == 0

    assert len(sent) == 1
    assert "디스크" in sent[0]


def test_main_notifies_again_when_state_file_is_corrupt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "resource-check.state").write_text("{깨진")
    monkeypatch.delenv("DISK_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.setattr(check_resources, "_read", _breached_disk_read)
    sent: list[str] = []
    monkeypatch.setattr(check_resources, "notify", _recording(sent))
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    assert check_resources.main() == 0

    assert len(sent) == 1
    saved = json.loads((tmp_path / "resource-check.state").read_text())
    assert saved["disk"]["alerting"] is True


def test_main_retries_alert_when_notify_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """보내기에 실패한 경고를 "보냈다" 로 기록하면 다음 24시간 동안 아무도 모른다 — 다음 실행이 다시 보낸다."""
    monkeypatch.delenv("DISK_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.setattr(check_resources, "_read", _breached_disk_read)
    attempts: list[str] = []

    def _failing_notify(message: str) -> bool:
        attempts.append(message)
        return False

    monkeypatch.setattr(check_resources, "notify", _failing_notify)
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    assert check_resources.main() == 0
    assert check_resources.main() == 0

    assert len(attempts) == 2


def test_main_still_pings_when_state_file_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """상태를 못 남겨도 감시 자체는 살아 있어야 한다 — stderr 에 남기고 ping 까지 간다.
    그 대가는 매 실행 알림(상태 파일 도입 전 동작)이라 안전한 쪽이다."""
    monkeypatch.setenv("HEALTHCHECKS_RESOURCE_PING_URL", "https://hc-ping.com/resource-check")
    monkeypatch.delenv("DISK_ALERT_THRESHOLD_PERCENT", raising=False)
    monkeypatch.setattr(check_resources, "_read", _breached_disk_read)
    monkeypatch.setattr(check_resources, "notify", lambda message: True)
    pinged: list[str] = []
    monkeypatch.setattr(check_resources, "ping", _recording(pinged))
    unwritable = tmp_path / "없는-디렉터리" / "resource-check.state"
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_resources.py",
            "--state-file",
            str(unwritable),
            "--worker-state-file",
            str(tmp_path / "novelize_worker"),
        ],
    )

    assert check_resources.main() == 0

    assert pinged == ["https://hc-ping.com/resource-check"]
    assert "상태 파일" in capsys.readouterr().err


# ── 소설화 워커 ──────────────────────────────────────────────────────────────
# 워커를 감시할지는 교체 스크립트가 남기는 기대 상태 파일(`on`/`off`)로 정한다 — 크론은 `.env` 를 읽지 않는다. 판정은
# 두 워커 색 중 healthy 가 하나라도 있는지다. docker 를 못 읽어도 메모리·디스크·ping 은 계속 간다.


def _docker_read(health: dict[str, str], *, fail: bool = False) -> Callable[[list[str]], str]:
    """`free`·`df` 는 정상 출력을, `docker ps` 는 `health`(서비스 → 헬스 상태, 없으면 컨테이너 없음)대로 id 를,
    `docker inspect` 는 그 id 의 헬스 상태를 돌려준다. `fail` 이면 docker 호출이 실패한다."""

    def _fake(cmd: list[str]) -> str:
        if cmd[0] == "free":
            return _FREE_HEALTHY
        if cmd[0] == "df":
            return _DF_HEALTHY
        assert cmd[0] == "docker", cmd
        if fail:
            raise RuntimeError("docker ps 실패:\nCannot connect to the Docker daemon")
        if cmd[1] == "ps":
            service = next(arg.split("=")[-1] for arg in cmd if "com.docker.compose.service=" in arg)
            return f"id-{service}\n" if service in health else ""
        assert cmd[1] == "inspect", cmd
        return health[cmd[-1].removeprefix("id-")] + "\n"

    return _fake


def _run_worker_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, read: Callable[[list[str]], str], *, expected: str | None
) -> tuple[list[str], list[str]]:
    """기대 상태 파일을 `expected` 로 두고(None 이면 만들지 않는다) main 을 한 번 돌려 보낸 알림과 ping 을 돌려준다."""
    if expected is not None:
        (tmp_path / "novelize_worker").write_text(expected)
    monkeypatch.setenv("HEALTHCHECKS_RESOURCE_PING_URL", "https://hc-ping.com/resource-check")
    monkeypatch.setattr(check_resources, "_read", read)
    sent: list[str] = []
    pinged: list[str] = []
    monkeypatch.setattr(check_resources, "notify", _recording(sent))
    monkeypatch.setattr(check_resources, "ping", _recording(pinged))
    monkeypatch.setattr("sys.argv", _argv(tmp_path))
    assert check_resources.main() == 0
    return sent, pinged


@pytest.mark.parametrize("expected", [None, "off\n", "깨진 값"])
def test_worker_is_not_watched_when_not_expected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, expected: str | None
) -> None:
    """스위치가 꺼져 있으면(파일 없음·off·알 수 없는 값) 워커가 없는 것이 정상이다 — docker 를 부르지도 않는다."""

    def _no_docker(cmd: list[str]) -> str:
        assert cmd[0] != "docker", cmd
        return _FREE_HEALTHY if cmd[0] == "free" else _DF_HEALTHY

    sent, _ = _run_worker_check(monkeypatch, tmp_path, _no_docker, expected=expected)
    assert sent == []


def test_worker_one_healthy_color_is_enough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """교체 중에는 옛 워커(비우는 중)와 새 워커가 같이 있고, 평소에는 한 색만 있다 — healthy 가 하나면 정상이다."""
    read = _docker_read({"worker_blue": "unhealthy", "worker_green": "healthy"})
    sent, _ = _run_worker_check(monkeypatch, tmp_path, read, expected="on\n")
    assert sent == []


def test_worker_missing_while_expected_alerts_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """켜져 있는데 healthy 워커가 없으면 새 작업이 60초 뒤 환불로 끝난다 — 알리고, 다음 실행은 같은 경고를 반복하지 않는다."""
    read = _docker_read({"worker_blue": "unhealthy"})
    sent, pinged = _run_worker_check(monkeypatch, tmp_path, read, expected="on\n")
    assert len(sent) == 1
    assert "소설화 워커" in sent[0]
    assert "blue=unhealthy" in sent[0] and "green=없음" in sent[0]
    assert pinged == ["https://hc-ping.com/resource-check"]

    sent_again, _ = _run_worker_check(monkeypatch, tmp_path, read, expected="on\n")
    assert sent_again == []


def test_worker_recovery_notice_names_the_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """복구 문구는 항목마다 맞아야 한다 — 워커는 "임계값" 이 없다."""
    _run_worker_check(monkeypatch, tmp_path, _docker_read({}), expected="on\n")
    sent, _ = _run_worker_check(monkeypatch, tmp_path, _docker_read({"worker_blue": "healthy"}), expected="on\n")
    assert len(sent) == 1
    assert "소설화 워커" in sent[0]
    assert "임계값" not in sent[0]


def test_worker_docker_failure_warns_only_that_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """docker 데몬을 못 읽는 것은 워커 항목의 경고일 뿐이다 — 메모리·디스크 판정과 ping 은 계속 간다. 여기서 죽으면
    healthchecks.io 가 "VM 이 죽었다" 로 본다."""

    def _read(cmd: list[str]) -> str:
        if cmd[0] == "free":
            return _FREE_UNDER_PRESSURE
        return _docker_read({}, fail=True)(cmd)

    sent, pinged = _run_worker_check(monkeypatch, tmp_path, _read, expected="on\n")
    assert len(sent) == 2
    assert any("메모리" in message for message in sent)
    assert any("소설화 워커 상태를 읽지 못했다" in message for message in sent)
    assert pinged == ["https://hc-ping.com/resource-check"]


def test_worker_docker_binary_missing_is_a_worker_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """docker 실행 파일이 없을 때 `subprocess.run` 은 `FileNotFoundError` 를 던진다 — 그것도 워커 항목 경고다."""

    def _read(cmd: list[str]) -> str:
        if cmd[0] == "docker":
            raise FileNotFoundError("docker")
        return _FREE_HEALTHY if cmd[0] == "free" else _DF_HEALTHY

    sent, pinged = _run_worker_check(monkeypatch, tmp_path, _read, expected="on\n")
    assert len(sent) == 1
    assert "소설화 워커 상태를 읽지 못했다" in sent[0]
    assert pinged == ["https://hc-ping.com/resource-check"]


@pytest.mark.parametrize(
    "health",
    [
        {"worker_blue": "starting"},
        {"worker_blue": "unhealthy", "worker_green": "starting"},
    ],
)
def test_worker_starting_is_not_an_alert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, health: dict[str, str]
) -> None:
    """교체가 새 워커를 띄운 직후 그 워커는 헬스체크 유예 동안 `starting` 이다 — 크론이 그 순간과 겹쳐도 경고가 아니다.
    `starting` 이 이어지지 않는 것은 docker 가 보장한다(유예가 끝나고 실패가 이어지면 unhealthy 로 바뀐다)."""
    sent, _ = _run_worker_check(monkeypatch, tmp_path, _docker_read(health), expected="on\n")
    assert sent == []


def test_worker_alerts_once_when_starting_worker_disappears(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """starting 은 조용히 지나가고, 그 뒤 워커가 사라지면 그때 한 번 알린다 — 상태가 바뀔 때만 알린다는 규약은 그대로다."""
    sent, _ = _run_worker_check(monkeypatch, tmp_path, _docker_read({"worker_blue": "starting"}), expected="on\n")
    assert sent == []

    sent, _ = _run_worker_check(monkeypatch, tmp_path, _docker_read({}), expected="on\n")
    assert len(sent) == 1
    assert "blue=없음" in sent[0] and "green=없음" in sent[0]

    sent, _ = _run_worker_check(monkeypatch, tmp_path, _docker_read({}), expected="on\n")
    assert sent == []
