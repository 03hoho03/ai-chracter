"""이 회원이 지금 클로버를 살 수 있는가 — 주문 생성과 `GET /me` 가 같은 판정을 쓴다.

판정이 두 벌이면 허브가 보여 주는 구매 가능 여부와 주문의 거절이 갈린다. 결제 스위치는 여기서 보지 않는다(스위치는
회원과 무관해 가격 응답의 `paymentsEnabled` 가 따로 싣는다).

본인인증은 미인증 회원 게이트가 아니라 나이를 확인하는 유일한 수단이라, 게이트 스위치·레이트리밋 면제와 무관하게 늘
건다. 나이는 인증으로 덮어쓴 생년월일을 로그인의 연령 확인과 같은 기준(UTC 날짜)으로 잰다.
"""

from datetime import UTC, datetime
from typing import Literal

from api.auth.age import is_under_payment_minimum_age
from api.db.models.auth import User

PurchaseBlockReason = Literal["identity_required", "age_restricted"]


def purchase_block_reason(user: User) -> PurchaseBlockReason | None:
    """살 수 없으면 그 이유, 살 수 있으면 `None`. 인증 전이면 생년월일을 믿을 수 없어 나이보다 인증이 먼저다."""
    if user.identity_verified_at is None:
        return "identity_required"
    # 인증자는 생년월일을 갖지만, 없으면 assert 대신 나이 거절로 둔다.
    if user.birth_date is None or is_under_payment_minimum_age(user.birth_date, datetime.now(UTC).date()):
        return "age_restricted"
    return None
