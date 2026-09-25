"""`ops.notify` — Discord 웹훅 + healthchecks.io ping 공통 유틸.

**알림이 안 갔다고 호출부(백업·리소스 감시)가 죽으면 안 된다** — 그래서 이 모듈의 두 함수는
절대 예외를 던지지 않는다. 이 계약이 깨지면 알림 인프라의 사소한 오류(웹훅 URL 오타, 네트워크
일시 장애)가 백업 실패로 둔갑한다. 여기서는 그 계약 자체를 고정한다.

`urllib.request.urlopen`을 직접 패치한다(`ops.notify`가 아니라) — `notify.py`도 같은 전역
`urllib.request` 모듈 객체를 참조하므로 효과는 같고, mypy strict의 `no-implicit-reexport`가
막는 `notify_module.urllib` 같은 재수출 경로를 통하지 않아도 된다.
"""

import urllib.error
import urllib.request

import pytest

from ops import notify as notify_module


def test_notify_posts_json_content_to_configured_webhook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")

    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 204

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def _fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["data"] = request.data
        captured["content_type"] = request.get_header("Content-type")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    assert notify_module.notify("백업 실패") is True
    assert captured["url"] == "https://discord.com/api/webhooks/1/abc"
    assert captured["method"] == "POST"
    assert captured["data"] == b'{"content": "\\ubc31\\uc5c5 \\uc2e4\\ud328"}'
    assert captured["content_type"] == "application/json"


def test_notify_skips_network_call_and_returns_true_when_webhook_url_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """알림 설정이 없는 것과 알림 실패는 다르다 — 전자는 정상 상태다."""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    def _fail_if_called(request: urllib.request.Request, timeout: float) -> None:
        raise AssertionError("웹훅 URL이 없으면 네트워크를 타면 안 된다")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_if_called)

    assert notify_module.notify("아무 메시지") is True


def test_notify_swallows_network_errors_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")

    def _raise_url_error(request: urllib.request.Request, timeout: float) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_url_error)

    assert notify_module.notify("백업 실패") is False


def test_ping_sends_get_request_to_given_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 200

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def _fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["data"] = request.data
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    assert notify_module.ping("https://hc-ping.com/abc123/start") is True
    assert captured["url"] == "https://hc-ping.com/abc123/start"
    assert captured["data"] is None  # GET — Discord POST 와 달리 본문이 없다


def test_ping_swallows_network_errors_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_url_error(request: urllib.request.Request, timeout: float) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_url_error)

    assert notify_module.ping("https://hc-ping.com/abc123/fail") is False


def test_notify_swallows_malformed_webhook_url_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """스킴 없는 URL은 `urllib.request.Request()` 생성 시점에 `ValueError`를 던진다 — `urlopen`보다
    먼저다. 그래서 여기서는 `urlopen`을 패치하지 않는다: 패치해 버리면 실제로는 그 전에 죽는 걸
    가려서 이 테스트가 통과해 버린다."""
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "hc-ping.com/abc123")

    assert notify_module.notify("백업 실패") is False


def test_ping_swallows_malformed_url_without_raising() -> None:
    assert notify_module.ping("hc-ping.com/abc123") is False


def test_ping_swallows_url_with_control_characters_without_raising() -> None:
    """제어 문자가 섞인 URL은 스킴이 있어도 `urlopen` 내부에서 `http.client.InvalidURL`을 던진다
    (`ValueError`/`URLError`/`OSError` 어느 것도 아니다) — 웹훅 URL을 env var 에 옮겨 적다가
    줄바꿈이 섞여도 이 경로를 탄다."""
    assert notify_module.ping("https://hc-ping.com/abc123\n/start") is False
