"""어드민 기능 스위치 변경을 운영 알림 디스코드 채널(`DISCORD_WEBHOOK_URL`, VM 크론 알림과 같은 채널)에 알린다.

쏘고 잊는다 — 태스크 참조를 쥔 채 띄워 어드민 응답이 알림을 기다리지 않게 하고, 끝나면 참조를 놓는다(`llm/credential_notify.py`
와 같은 꼴). 알림은 저장을 바꾸지 않는다: 실패는 삼키고 클래스 이름만 남긴다(오류 문장이 웹훅 주소 — 곧 그 채널에 쓸 권한 — 를
실을 수 있다). 웹훅이 비면 보내지 않고 경고 한 줄만 남긴다.

문구는 스위치 이름·실효 전→후·사유만 싣고 운영자 계정은 싣지 않는다(누가 바꿨는지는 어드민 이력에 있다). 사유는 운영자가 쓴
글이라 멘션 문법이 섞여도 울리지 않게 멘션 해석을 끈다. User-Agent 는 디스코드 HTTP API 꼴로 싣는다 — 디스코드 앞단이 기본
User-Agent(호스트 알림 스크립트의 urllib)를 막아 운영 알림이 하나도 나가지 않은 적이 있다(`scripts/ops/notify.py`).
"""

import asyncio
import logging
from collections.abc import Callable

import httpx

from api.core.config import settings

logger = logging.getLogger(__name__)

# 백그라운드에서 도는 호출이라 아무도 기다리지 않지만, 오래 매달리면 그만큼 연결이 묶인다.
_TIMEOUT_SECONDS = 5.0
_DISCORD_USER_AGENT = "DiscordBot (https://api.ddona.site, 1.0)"
_pending: set[asyncio.Task[None]] = set()


async def send_feature_switch_notification(message: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.discord_webhook_url,
                json={"content": message, "allowed_mentions": {"parse": []}},
                headers={"User-Agent": _DISCORD_USER_AGENT},
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("feature switch notification failed: %s", type(exc).__name__)


def spawn_feature_switch_notification(message: str) -> None:
    """참조를 쥔 채 쏘고 잊는다."""
    if not settings.discord_webhook_url:
        logger.warning("feature switch notification skipped: webhook not configured")
        return
    task = asyncio.create_task(send_feature_switch_notification(message))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def get_feature_switch_notifier() -> Callable[[str], None]:
    """어드민 라우트가 커밋 뒤에 부르는 알림 함수. 테스트는 이 의존성을 갈아 끼워 문구만 모은다."""
    return spawn_feature_switch_notification
