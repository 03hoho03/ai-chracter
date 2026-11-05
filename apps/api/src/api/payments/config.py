"""결제·본인인증이 켜져 있는지의 판정. 설정값(`core/config.py`)이 비면 기동을 막지 않고 그 기능만 끈다.

설정은 호출 때마다 `settings` 에서 다시 읽는다 — 테스트가 `monkeypatch.setattr(settings, …)` 로 값을 정하므로
(로컬 `.env` 에는 실제 포트원 키가 있다) 값을 모듈 상수로 묶어 두면 그 덮어쓰기가 통하지 않는다.

키 검사(`missing_*_settings`)는 스위치와 떼어 부를 수 있다 — 어드민 기능 스위치 현황판은 스위치의 실효 값을 DB 에서 따로
계산하므로, 이 요청에 고정된 스위치 값이 섞이는 `payments_active()` 대신 키 쪽만 받아 비어 있는 키 이름을 보인다.
"""

from api.core.config import settings
from api.core.feature_switches import switch_on

# 본인인증을 시작하고 결과를 저장하는 데 필요한 설정 칸.
_IDENTITY_SETTINGS = ("portone_store_id", "portone_identity_channel_key", "portone_api_secret", "identity_ci_hmac_key")
# 결제를 받는 데 필요한 설정 칸(본인인증 설정은 따로 더한다).
_PAYMENT_SETTINGS = ("portone_store_id", "portone_payment_channel_key", "portone_api_secret", "portone_webhook_secret")


def _missing(names: tuple[str, ...]) -> list[str]:
    """비어 있는 칸의 env 키 이름(칸 이름의 대문자). 값은 싣지 않는다."""
    return [name.upper() for name in names if not getattr(settings, name)]


def missing_identity_settings() -> list[str]:
    """본인인증에 필요한 설정 중 비어 있는 것의 env 키 이름."""
    return _missing(_IDENTITY_SETTINGS)


def missing_payment_settings() -> list[str]:
    """결제에 필요한 설정 중 비어 있는 것의 env 키 이름 — 결제 키 넷과, 겹치지 않는 본인인증 설정까지."""
    return _missing(tuple(dict.fromkeys(_PAYMENT_SETTINGS + _IDENTITY_SETTINGS)))


def identity_configured() -> bool:
    """본인인증을 시작하고 결과를 저장할 수 있는가: 상점 id·본인인증 채널키·API 비밀·CI HMAC 키가 모두 있다."""
    return not missing_identity_settings()


def payments_active() -> bool:
    """결제를 받을 수 있는가: 결제 스위치 ∧ 상점 id·결제 채널키·API 비밀·웹훅 비밀 ∧ 본인인증 설정.

    본인인증 설정까지 요구하는 이유: 결제는 만 19세 확인 때문에 늘 본인인증을 거친다. 인증 설정이 비었는데 결제만
    켜지면 구매 화면은 보이는데 아무도 인증할 수 없어 아무도 결제하지 못한다.
    """
    return switch_on("payments_enabled") and not missing_payment_settings()


def identity_gate_active() -> bool:
    """미인증 회원의 미션 보상을 막는 게이트가 켜져 있는가. 인증할 수 없는 환경에서 게이트만 켜지면 아무도
    풀 수 없으므로 본인인증 설정이 함께 있어야 한다."""
    return switch_on("identity_gate_enabled") and identity_configured()
