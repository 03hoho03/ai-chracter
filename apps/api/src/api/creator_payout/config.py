"""크리에이터 정산이 켜져 있는지의 판정. 설정이 모자라면 기동을 막지 않고 이 기능만 끈다(결제 `payments/config.py` 와 같은
관례). 설정은 호출 때마다 `settings` 에서 다시 읽는다 — 테스트가 `monkeypatch.setattr(settings, …)` 로 값을 정한다.
"""

from api.core.config import settings
from api.payments.config import identity_configured


def creator_payout_active() -> bool:
    """크리에이터가 정산을 신청·조회할 수 있는가: 정산 스위치 ∧ 본인인증 설정.

    본인인증 설정까지 요구하는 이유: 신청 자격이 본인인증과 그 생년월일의 만 19세라, 인증 설정이 비었는데 정산만 켜지면
    화면은 보이는데 아무도 신청할 수 없다. 어드민의 신청 처리는 이 판정을 보지 않는다 — 끄기 전에 들어온 신청을
    마무리해야 한다.
    """
    return settings.creator_payout_enabled and identity_configured()
