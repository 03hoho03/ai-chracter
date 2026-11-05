"""Claude 자격 목록 변경을 디스코드 채널(`LLM_CREDENTIAL_DISCORD_WEBHOOK_URL`, 결제 채널과 다른 웹훅)에 알린다.

쏘고 잊는다 — 태스크 참조를 쥔 채 띄워 부르는 쪽(어드민 응답, 나중에는 `BackgroundTasks` 가 닿지 않는 LLM 호출 경로)이
알림을 기다리지 않게 하고, 끝나면 참조를 놓는다(`novelize/runner.py` 의 `_spawn` 과 같은 꼴). 알림은 변경을 바꾸지 않는다:
실패는 삼키고 클래스 이름만 남긴다(오류 문장이 웹훅 주소 — 곧 그 채널에 쓸 권한 — 를 실을 수 있다). 웹훅이 비면 보내지 않고
경고 한 줄만 남긴다.

문구에는 공급자·라벨·지문·변경 요지만 싣는다 — 키·끝 4자리·조직 id 는 싣지 않는다. 라벨은 운영자가 쓴 글이라 멘션 문법이
섞여도 울리지 않게 멘션 해석을 끈다.
"""

import asyncio
import logging
from collections.abc import Callable

import httpx

from api.core.config import settings

logger = logging.getLogger(__name__)

# 백그라운드에서 도는 호출이라 아무도 기다리지 않지만, 오래 매달리면 그만큼 연결이 묶인다.
_TIMEOUT_SECONDS = 5.0
_pending: set[asyncio.Task[None]] = set()


async def send_credential_notification(message: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.llm_credential_discord_webhook_url,
                json={"content": message, "allowed_mentions": {"parse": []}},
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("llm credential notification failed: %s", type(exc).__name__)


def spawn_credential_notification(message: str) -> None:
    """참조를 쥔 채 쏘고 잊는다."""
    if not settings.llm_credential_discord_webhook_url:
        logger.warning("llm credential notification skipped: webhook not configured")
        return
    task = asyncio.create_task(send_credential_notification(message))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def get_credential_notifier() -> Callable[[str], None]:
    """어드민 라우트가 커밋 뒤에 부르는 알림 함수. 테스트는 이 의존성을 갈아 끼워 문구만 모은다."""
    return spawn_credential_notification
