"""결제·본인인증이 켜져 있는지의 판정. 설정값(`core/config.py`)이 비면 기동을 막지 않고 그 기능만 끈다.

설정은 호출 때마다 `settings` 에서 다시 읽는다 — 테스트가 `monkeypatch.setattr(settings, …)` 로 값을 정하므로
(로컬 `.env` 에는 실제 포트원 키가 있다) 값을 모듈 상수로 묶어 두면 그 덮어쓰기가 통하지 않는다.
"""

from api.core.config import settings


def identity_configured() -> bool:
    """본인인증을 시작하고 결과를 저장할 수 있는가: 상점 id·본인인증 채널키·API 비밀·CI HMAC 키가 모두 있다."""
    return all(
        (
            settings.portone_store_id,
            settings.portone_identity_channel_key,
            settings.portone_api_secret,
            settings.identity_ci_hmac_key,
        )
    )


def payments_active() -> bool:
    """결제를 받을 수 있는가: 결제 스위치 ∧ 상점 id·결제 채널키·API 비밀·웹훅 비밀 ∧ 본인인증 설정.

    본인인증 설정까지 요구하는 이유: 결제는 만 19세 확인 때문에 늘 본인인증을 거친다. 인증 설정이 비었는데 결제만
    켜지면 구매 화면은 보이는데 아무도 인증할 수 없어 아무도 결제하지 못한다.
    """
    return (
        settings.payments_enabled
        and all(
            (
                settings.portone_store_id,
                settings.portone_payment_channel_key,
                settings.portone_api_secret,
                settings.portone_webhook_secret,
            )
        )
        and identity_configured()
    )


def identity_gate_active() -> bool:
    """미인증 회원의 무료 대화·미션을 막는 게이트가 켜져 있는가. 인증할 수 없는 환경에서 게이트만 켜지면 아무도
    풀 수 없으므로 본인인증 설정이 함께 있어야 한다."""
    return settings.identity_gate_enabled and identity_configured()
