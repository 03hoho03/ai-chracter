"""결제·환불 완료를 디스코드 채널에 알린다. 라우트가 `Depends(get_payment_notifier)` 로 받아 `BackgroundTasks` 로 응답
뒤에 보낸다.

알림은 결제를 바꾸지 않는다 — 실패는 삼키고 `logger.warning` 만 남긴다(알림 실패가 결제·환불 응답을 실패로 만들면
안 된다). 문구에는 상품·금액·상태만 싣는다. 회원 id·주문 id 는 조각도 넣지 않는다 — 외부 채널로 개인을 다시 알아볼
단서를 보내지 않으려는 것이다.
"""

import logging
from collections.abc import Awaitable, Callable

import httpx

from api.core.config import settings

logger = logging.getLogger(__name__)

PaymentNotifier = Callable[[str], Awaitable[None]]

# 응답 뒤 백그라운드에서 도는 호출이라 사용자는 기다리지 않지만, 오래 매달리면 그만큼 워커가 묶인다.
_TIMEOUT_SECONDS = 5.0


async def send_payment_notification(message: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.payment_discord_webhook_url, json={"content": message})
            response.raise_for_status()
    # 알림은 어떤 이유로 실패해도 결제 흐름 밖의 일이다(주소 형식 오류처럼 httpx.HTTPError 가 아닌 것도 포함).
    except Exception as exc:
        logger.warning("payment notification failed: %s", type(exc).__name__)


async def _skip_payment_notification(message: str) -> None:
    return None


def get_payment_notifier() -> PaymentNotifier:
    """알림 주소가 비면 아무것도 보내지 않는 함수를 준다(로컬·CI)."""
    if settings.payment_discord_webhook_url:
        return send_payment_notification
    return _skip_payment_notification
