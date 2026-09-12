from collections.abc import Awaitable, Callable

import httpx

from api.core.config import settings

# email-goal-prompt.md E-10 / apps/api/CLAUDE.md: 외부 HTTP 호출은 Depends로 감싸 테스트에서
# app.dependency_overrides로 갈아끼운다 — 라우터는 이 타입을 Depends(get_email_sender)로 받는다.
EmailSender = Callable[[str, str, str], Awaitable[None]]


class EmailSendError(Exception):
    """Raised when the configured email provider fails to send a message."""


async def send_email_console(to: str, subject: str, body: str) -> None:
    """email-goal-prompt.md E-3 기본값 — 실제 발송 없이 콘솔에 찍는다(로컬 개발/pytest)."""
    print(f"EMAIL to={to} subject={subject!r} body={body!r}")


async def send_email_resend(to: str, subject: str, body: str) -> None:
    """email-goal-prompt.md E-1: Resend HTTP API. llm/cloudflare_image.py:84-94와 같은 형태 —
    httpx.AsyncClient → raise_for_status() → HTTPStatusError(좁음)/HTTPError(넓음) 순으로
    잡아 전용 예외로 정규화한다.

    타임아웃 10초: 이미지 생성(60초, 무거운 추론)과 달리 몇 KB짜리 JSON 왕복이라 오래 걸릴
    이유가 없다 — 응답 이후 백그라운드에서 도는 호출(E-2)이 오래 매달리면 그만큼 이벤트 루프
    워커가 묶이므로 짧게 잡는다.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.email_from, "to": [to], "subject": subject, "text": body},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise EmailSendError(
            f"Resend email send failed: {exc.response.status_code} {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise EmailSendError(f"Resend email send call failed: {exc}") from exc


def get_email_sender() -> EmailSender:
    """FastAPI dependency: settings.email_provider로 분기한다(E-3). 프로바이더가 2개뿐이라
    함수 안 if 하나로 충분하다 — 레지스트리/추상 베이스 클래스는 세우지 않는다."""
    if settings.email_provider == "resend":
        return send_email_resend
    return send_email_console
