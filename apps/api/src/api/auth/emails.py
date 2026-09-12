import logging

from api.core.email import EmailSendError, EmailSender

# email-goal-prompt.md E-2: 발송은 BackgroundTasks로 응답 이후 실행되므로 실패해도 가입/재전송/
# 비밀번호 재설정 응답에는 영향이 없다 — 대신 로그에 남긴다. uvicorn은 root logger에 핸들러를
# 안 붙여 info/debug는 조용히 사라지지만 logging.lastResort가 WARNING 이상은 stderr로 내보낸다
# (chat/router.py:100-102 선례).
logger = logging.getLogger(__name__)


async def send_verification_code_email(sender: EmailSender, to: str, code: str) -> None:
    await _send(
        sender,
        to,
        subject="[AI 캐릭터 챗] 이메일 인증 코드",
        body=f"인증 코드: {code}\n이 코드는 {to} 계정 인증에 사용됩니다.",
    )


async def send_password_reset_email(sender: EmailSender, to: str, reset_link: str) -> None:
    await _send(
        sender,
        to,
        subject="[AI 캐릭터 챗] 비밀번호 재설정",
        body=f"비밀번호를 재설정하려면 아래 링크를 클릭하세요:\n{reset_link}\n이 링크는 1시간 동안 유효합니다.",
    )


async def _send(sender: EmailSender, to: str, subject: str, body: str) -> None:
    try:
        await sender(to, subject, body)
    except EmailSendError as exc:
        logger.warning("email send failed to=%s subject=%r: %s", to, subject, exc)
