from api.core.email import send_email


def send_verification_code_email(to: str, code: str) -> None:
    send_email(
        to=to,
        subject="[AI 캐릭터 챗] 이메일 인증 코드",
        body=f"인증 코드: {code}\n이 코드는 {to} 계정 인증에 사용됩니다.",
    )


def send_password_reset_email(to: str, reset_link: str) -> None:
    send_email(
        to=to,
        subject="[AI 캐릭터 챗] 비밀번호 재설정",
        body=f"비밀번호를 재설정하려면 아래 링크를 클릭하세요:\n{reset_link}\n이 링크는 1시간 동안 유효합니다.",
    )
