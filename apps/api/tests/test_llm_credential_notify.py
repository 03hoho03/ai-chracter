"""Claude 자격 목록 변경 알림 — 디스코드 웹훅으로 쏘고 잊는다.

알림은 변경을 바꾸지 않는다: 실패는 삼키고 클래스 이름만 남기며, 부르는 쪽은 알림을 기다리지 않는다. 라벨은 운영자가 쓴
글이라 멘션 문법이 섞여도 울리지 않게 멘션 해석을 끈다."""

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from api.core.config import settings
from api.core.redis import redis_client
from api.llm import credential_notify
from api.llm.credential_notify import (
    send_credential_notification,
    send_credential_notification_once,
    spawn_credential_notification,
    spawn_credential_notification_once,
)
from factories import _capture_credential_alerts, _patch_httpx, _settle_credential_tasks

_WEBHOOK = "https://discord.invalid/api/webhooks/0/test-hook"


@pytest.fixture(autouse=True)
def _webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_credential_discord_webhook_url", _WEBHOOK)


async def test_notification_posts_with_mentions_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """`@everyone` 같은 글이 라벨에 섞여도 채널 전체를 부르지 않는다 — 멘션 해석을 끈 본문으로 보낸다."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    _patch_httpx(monkeypatch, handler, module="api.llm.credential_notify")

    await send_credential_notification("[Claude 자격] 켬 — anthropic · @everyone")

    (request,) = seen
    assert str(request.url) == _WEBHOOK
    assert json.loads(request.content) == {
        "content": "[Claude 자격] 켬 — anthropic · @everyone",
        "allowed_mentions": {"parse": []},
    }


async def test_notification_failure_is_swallowed_and_logs_only_the_class_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """웹훅이 실패해도 예외를 올리지 않는다(어드민 변경은 이미 커밋됐다). 남기는 것은 오류 클래스 이름뿐이다 — 오류 문장이
    웹훅 주소(곧 그 채널에 쓸 권한)를 실을 수 있다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    _patch_httpx(monkeypatch, handler, module="api.llm.credential_notify")
    caplog.set_level(logging.WARNING, logger="api.llm.credential_notify")

    await send_credential_notification("[Claude 자격] 끔")

    assert [record.getMessage() for record in caplog.records] == ["llm credential notification failed: ConnectError"]
    assert "test-hook" not in caplog.text


async def test_missing_webhook_skips_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """웹훅이 비면 보내지 않고 경고 한 줄만 남긴다 — 로컬에서 가짜 웹훅 없이 저장을 시험할 수 있게 저장은 막지 않는다."""
    monkeypatch.setattr(settings, "llm_credential_discord_webhook_url", "")
    caplog.set_level(logging.WARNING, logger="api.llm.credential_notify")

    spawn_credential_notification("[Claude 자격] 끔")

    assert credential_notify._pending == set()
    assert [record.getMessage() for record in caplog.records] == [
        "llm credential notification skipped: webhook not configured"
    ]


async def test_spawned_notification_is_kept_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """쏘고 잊되 태스크 참조를 쥔다 — 참조가 없으면 이벤트 루프가 약한 참조만 들고 있어 끝나기 전에 사라질 수 있다. 끝나면
    참조를 놓는다."""
    release = asyncio.Event()
    sent: list[str] = []

    async def slow(message: str) -> None:
        await release.wait()
        sent.append(message)

    monkeypatch.setattr(credential_notify, "send_credential_notification", slow)

    spawn_credential_notification("[Claude 자격] 켬")

    (task,) = credential_notify._pending
    release.set()
    await task
    await asyncio.sleep(0)
    assert sent == ["[Claude 자격] 켬"]
    assert credential_notify._pending == set()


# ── 같은 표지로 한 번만 ─────────────────────────────────────────────────────────────────
async def test_once_notification_is_sent_once_per_key_within_its_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 표지로는 수명 안에 한 번만 보낸다(표지를 처음 세운 쪽만). 표지가 다르면 따로 보낸다. 쏘는 쪽은 기다리지 않는다."""
    sent = _capture_credential_alerts(monkeypatch)

    spawn_credential_notification_once("llm_credential:alert:test:a", "첫 알림", ttl_seconds=600)
    spawn_credential_notification_once("llm_credential:alert:test:a", "같은 표지", ttl_seconds=600)
    await _settle_credential_tasks()
    spawn_credential_notification_once("llm_credential:alert:test:a", "같은 표지 다시", ttl_seconds=600)
    spawn_credential_notification_once("llm_credential:alert:test:b", "다른 표지", ttl_seconds=600)
    await _settle_credential_tasks()

    assert sent == ["첫 알림", "다른 표지"]
    assert 590 < await redis_client.ttl("llm_credential:alert:test:a") <= 600


class _BrokenRedis:
    def __init__(self, hang: bool) -> None:
        self.hang = hang

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        if self.hang:
            await asyncio.sleep(5)
        raise RedisConnectionError("redis is down")


@pytest.mark.parametrize("hang", [pytest.param(False, id="error"), pytest.param(True, id="timeout")])
async def test_once_notification_is_skipped_when_redis_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, hang: bool
) -> None:
    """표지를 확인하지 못하면 보내지 않고 경고만 남긴다 — 확인 없이 보내면 실패한 호출마다 알림이 간다. 답하지 않는 Redis 도 상한
    안에 포기한다."""
    sent = _capture_credential_alerts(monkeypatch)
    monkeypatch.setattr(credential_notify, "redis_client", _BrokenRedis(hang))
    caplog.set_level(logging.WARNING, logger="api.llm.credential_notify")

    async with asyncio.timeout(1):
        await send_credential_notification_once("llm_credential:alert:test:a", "알림", ttl_seconds=600)

    assert sent == []
    reason = "TimeoutError" if hang else "ConnectionError"
    assert [record.getMessage() for record in caplog.records] == [
        f"llm credential notification skipped: dedupe check failed ({reason})"
    ]
