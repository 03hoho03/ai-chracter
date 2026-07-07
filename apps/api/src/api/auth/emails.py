from api.core.email import send_email


def send_verification_code_email(to: str, code: str) -> None:
    send_email(
        to=to,
        subject="[AI 캐릭터 챗] 이메일 인증 코드",
        body=f"인증 코드: {code}\n이 코드는 {to} 계정 인증에 사용됩니다.",
    )
