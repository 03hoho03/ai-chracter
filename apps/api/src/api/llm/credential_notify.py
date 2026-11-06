"""Claude 자격 목록 변경을 디스코드 채널(`LLM_CREDENTIAL_DISCORD_WEBHOOK_URL`, 결제 채널과 다른 웹훅)에 알린다.

쏘고 잊는다 — 태스크 참조를 쥔 채 띄워 부르는 쪽(어드민 응답, `BackgroundTasks` 가 닿지 않는 LLM 호출 경로)이 알림을
기다리지 않게 하고, 끝나면 참조를 놓는다(`novelize/runner.py` 의 `_spawn` 과 같은 꼴). 알림은 변경을 바꾸지 않는다:
실패는 삼키고 클래스 이름만 남긴다(오류 문장이 웹훅 주소 — 곧 그 채널에 쓸 권한 — 를 실을 수 있다). 웹훅이 비면 보내지 않고
경고 한 줄만 남긴다.

문구에는 공급자·라벨·지문·변경 요지만 싣는다 — 키·끝 4자리·조직 id 는 싣지 않는다. 라벨은 운영자가 쓴 글이라 멘션 문법이
섞여도 울리지 않게 멘션 해석을 끈다.

호출 경로가 상태를 보고 보내는 알림(후보 없음·키를 읽을 수 없음·추정 잔액 임계)은 같은 상태가 이어지는 동안 호출마다 나므로
Redis 표지(`SET NX EX`)로 한 번만 보낸다(`spawn_credential_notification_once`). 소진 알림은 DB 의 조건부 UPDATE 가 한 번만
바꾸므로 표지가 필요 없다.
"""

import asyncio
import logging
from collections.abc import Callable

from collections.abc import Coroutine
from typing import Any

import httpx

from api.core.config import settings
from api.core.redis import redis_client

logger = logging.getLogger(__name__)

# 백그라운드에서 도는 호출이라 아무도 기다리지 않지만, 오래 매달리면 그만큼 연결이 묶인다.
_TIMEOUT_SECONDS = 5.0
# 중복 억제 표지를 세우는 Redis 왕복의 상한. 공용 Redis 클라이언트에 소켓 시간 초과가 없어 따로 건다(사용량 기록과 같은 값).
_DEDUPE_TIMEOUT_SECONDS = 0.1
_pending: set[asyncio.Task[None]] = set()


def _spawn(coroutine: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coroutine)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


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
    _spawn(send_credential_notification(message))


def get_credential_notifier() -> Callable[[str], None]:
    """어드민 라우트가 커밋 뒤에 부르는 알림 함수. 테스트는 이 의존성을 갈아 끼워 문구만 모은다."""
    return spawn_credential_notification


async def send_credential_notification_once(dedupe_key: str, message: str, *, ttl_seconds: int) -> None:
    """같은 표지로는 수명 안에 한 번만 보낸다(Redis `SET NX EX` 가 표지를 처음 세운 쪽만). 표지를 확인하지 못하면(Redis 오류·
    상한 초과) 보내지 않고 경고만 — 확인 없이 보내면 실패한 호출마다 알림이 간다. 절대 raise 하지 않는다."""
    try:
        async with asyncio.timeout(_DEDUPE_TIMEOUT_SECONDS):
            first = await redis_client.set(dedupe_key, "1", nx=True, ex=ttl_seconds)
    except Exception as exc:
        logger.warning("llm credential notification skipped: dedupe check failed (%s)", type(exc).__name__)
        return
    if first:
        await send_credential_notification(message)


def spawn_credential_notification_once(dedupe_key: str, message: str, *, ttl_seconds: int) -> None:
    """위를 참조를 쥔 태스크로 쏘고 잊는다 — 부르는 쪽(LLM 호출 경로)은 Redis 도 기다리지 않는다. 웹훅이 비면 표지도 세우지
    않는다(웹훅을 채운 뒤의 첫 알림이 앞서 세운 표지에 막히지 않게)."""
    if not settings.llm_credential_discord_webhook_url:
        logger.warning("llm credential notification skipped: webhook not configured")
        return
    _spawn(send_credential_notification_once(dedupe_key, message, ttl_seconds=ttl_seconds))
