"""미인증 회원 게이트의 판정 하나. 게이트에 걸리면 일일 무료 대화가 0 이 되고(가진 클로버로는 대화할 수 있다), 출석·미션
보상을 받지 못한다. 이미지·소설·작품 만들기는 막지 않는다.

채팅·출석·미션이 모두 이 함수를 부른다 — 판정이 여러 벌이면 한쪽만 바뀌어, 보이는 버튼이 403 을 받는다. 면제
회원(`rate_limit_exempt`)은 게이트를 건너뛴다. 결제는 이 게이트가 아니다 — 결제의 본인인증은 만 19세 확인 수단이라
스위치·면제와 무관하게 늘 걸린다(`payments/router.py`).
"""

from fastapi import HTTPException, status

from api.db.models.auth import User
from api.payments.config import identity_gate_active

IDENTITY_VERIFICATION_REQUIRED = "IDENTITY_VERIFICATION_REQUIRED"


def is_identity_gated(user: User) -> bool:
    """이 회원이 지금 게이트에 걸리는가. 스위치가 꺼져 있으면 설정만 보고 거짓이다."""
    return identity_gate_active() and not user.rate_limit_exempt and user.identity_verified_at is None


def identity_verification_required() -> HTTPException:
    """게이트의 거절. 429 가 아니라 403 이다 — 기다려서 풀리는 한도가 아니라 인증해야 풀리는 자격이라, 다시 시도할 시각
    (`retryAfterSeconds`)에 참값이 없다."""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": IDENTITY_VERIFICATION_REQUIRED})
