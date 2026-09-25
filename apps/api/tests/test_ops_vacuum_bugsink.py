"""`ops/vacuum_bugsink.py` — Bugsink 오류 이벤트를 `MAX_EVENT_AGE_DAYS`보다 오래된 것부터
지운다.

`docker exec` 호출은 `subprocess.run` 스텁으로 대체한다 — 실제 컨테이너 없이 성공/실패(컨테이너
미기동 포함) 두 경로와, 실패 시 Discord 알림 배선만 검증한다.
"""

import subprocess

import pytest

import ops.vacuum_bugsink as vacuum_bugsink


def test_run_vacuum_calls_docker_exec_on_the_fixed_container_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert cmd == [
            "docker",
            "exec",
            vacuum_bugsink.CONTAINER_NAME,
            "bugsink-manage",
            "vacuum",
            "--old-events",
        ]
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="Vacuum complete.\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert vacuum_bugsink.run_vacuum() == "Vacuum complete.\n"


def test_run_vacuum_raises_runtime_error_when_container_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr=f"Error response from daemon: container {vacuum_bugsink.CONTAINER_NAME} is not running",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="is not running"):
        vacuum_bugsink.run_vacuum()


def test_main_prints_output_and_returns_zero_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vacuum_bugsink, "run_vacuum", lambda: "Vacuum complete.\n")
    monkeypatch.setattr("sys.argv", ["vacuum_bugsink.py"])

    assert vacuum_bugsink.main() == 0


def test_on_failure_notifies_and_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def _fake_notify(message: str) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(vacuum_bugsink, "notify", _fake_notify)

    exit_code = vacuum_bugsink._on_failure(RuntimeError("container not running"))

    assert exit_code == 1
    assert len(sent) == 1
    assert "container not running" in sent[0]
