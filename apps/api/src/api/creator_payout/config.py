"""크리에이터 정산이 켜져 있는지의 판정. 설정이 모자라면 기동을 막지 않고 이 기능만 끈다(결제 `payments/config.py` 와 같은
관례). 설정은 호출 때마다 `settings` 에서 다시 읽는다 — 테스트가 `monkeypatch.setattr(settings, …)` 로 값을 정한다.
"""

from api.core.config import settings
from api.core.field_crypto import FieldDecryptError, FieldKeyring
from api.payments.config import identity_configured


def creator_payout_active() -> bool:
    """크리에이터가 정산을 신청·조회하고 적립이 확정되는가: 정산 스위치 ∧ 본인인증 설정.

    본인인증 설정까지 요구하는 이유: 신청 자격이 본인인증과 그 생년월일의 만 19세라, 인증 설정이 비었는데 정산만 켜지면
    화면은 보이는데 아무도 신청할 수 없다. 지급 정보 암호화 키는 보지 않는다 — 신청·적립·확정·조회는 키 없이 맞게 돌고,
    키가 필요한 것은 지급 정보를 저장·읽는 일뿐이다(`creator_payout_transfer_active`). 어드민의 신청·지급 처리는 이
    판정을 보지 않는다 — 끄기 전에 들어온 신청과 지급을 마무리해야 한다.
    """
    return settings.creator_payout_enabled and identity_configured()


def creator_payout_transfer_active() -> bool:
    """지급 정보 입력과 지급 신청을 받을 수 있는가: 정산이 켜져 있고 지급 정보 암호화 키가 있다."""
    return creator_payout_active() and bool(settings.creator_payout_encryption_keys)


def payout_keyring() -> FieldKeyring:
    """지급 정보 암호화 키 목록. 형식은 기동 때 설정 검증이 이미 확인했다. 키가 비어 있으면 `FieldDecryptError` —
    어드민 경로와 작가 조회는 키 없이도 들어올 수 있고, 그때 지급 정보는 읽을 수 없는 것과 같다."""
    if not settings.creator_payout_encryption_keys:
        raise FieldDecryptError
    return FieldKeyring.parse(settings.creator_payout_encryption_keys)
