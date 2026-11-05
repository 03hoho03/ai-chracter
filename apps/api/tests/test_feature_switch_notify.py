"""기능 스위치 변경 알림 — 운영 알림 채널(`DISCORD_WEBHOOK_URL`)로 쏘고 잊는다.

사유는 운영자가 쓴 글이라 멘션 문법이 섞여도 울리지 않게 멘션 해석을 끄고, 디스코드 앞단이 기본 User-Agent 를 막은 적이 있어
디스코드 HTTP API 꼴의 User-Agent 를 싣는다. 실패는 삼키고 클래스 이름만 남긴다."""

import json
import logging

import httpx
import pytest

from api.core.config import settings
from api.core.feature_switch_notify import send_feature_switch_notification
from factories import _patch_httpx

_WEBHOOK = "https://discord.invalid/api/webhooks/0/switch-hook"


@pytest.fixture(autouse=True)
def _webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "discord_webhook_url", _WEBHOOK)


async def test_notification_posts_with_mentions_disabled_and_a_discord_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """사유에 `@everyone` 이 섞여도 채널 전체를 부르지 않는다. 깨지는 시나리오: 운영자가 사유에 쓴 멘션이 운영 채널 전체를
    울리거나, 기본 User-Agent 가 디스코드 앞단에 막혀 알림이 하나도 나가지 않는다."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    _patch_httpx(monkeypatch, handler, module="api.core.feature_switch_notify")

    await send_feature_switch_notification("[기능 스위치] payments_enabled — 꺼짐 → 켜짐\n사유: @everyone")

    (request,) = seen
    assert str(request.url) == _WEBHOOK
    assert request.headers["user-agent"].startswith("DiscordBot (")
    assert json.loads(request.content) == {
        "content": "[기능 스위치] payments_enabled — 꺼짐 → 켜짐\n사유: @everyone",
        "allowed_mentions": {"parse": []},
    }


async def test_notification_failure_is_swallowed_and_logs_only_the_class_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """웹훅이 거절해도 예외를 올리지 않고, 남기는 것은 오류 클래스 이름뿐이다 — 오류 문장이 웹훅 주소(곧 그 채널에 쓸 권한)를
    실을 수 있다. 깨지는 시나리오: 디스코드 400 이 이미 커밋한 저장의 응답을 500 으로 만들거나 로그에 웹훅 주소가 남는다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)

    _patch_httpx(monkeypatch, handler, module="api.core.feature_switch_notify")
    caplog.set_level(logging.WARNING, logger="api.core.feature_switch_notify")

    await send_feature_switch_notification("[기능 스위치] payments_enabled")

    assert [record.getMessage() for record in caplog.records] == ["feature switch notification failed: HTTPStatusError"]
    assert "switch-hook" not in caplog.text
