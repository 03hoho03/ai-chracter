"""이 회원이 지금 크리에이터 정산을 신청·승인받을 수 있는가 — 신청, `GET /me/creator-payout`, 어드민 신청 목록과 승인 때의
재확인이 모두 이 판정을 쓴다.

판정이 여러 벌이면 화면이 보여 주는 자격과 신청·승인의 거절이 갈린다. 정산 스위치는 여기서 보지 않는다(스위치는 회원과
무관하고, 어드민 승인은 스위치와 무관하게 열려 있다).

나이는 본인인증으로 덮어쓴 생년월일을 결제와 같은 기준(UTC 날짜)으로 잰다. 인증 전이면 생년월일을 믿을 수 없어 성인으로
치지 않는다.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.age import is_under_creator_payout_minimum_age
from api.db.models.auth import User
from api.db.models.content import Content

# 막는 이유. 순서가 우선순위다 — 탈퇴·정지가 먼저이고, 인증 전에는 생년월일을 믿을 수 없어 나이보다 인증이 먼저다.
CreatorPayoutBlockReason = Literal["withdrawn", "suspended", "identity_required", "age_restricted", "no_published_work"]


@dataclass(frozen=True)
class CreatorPayoutEligibility:
    withdrawn: bool
    suspended: bool
    identity_verified: bool
    adult: bool
    published_count: int

    @property
    def block_reason(self) -> CreatorPayoutBlockReason | None:
        """신청·승인할 수 없으면 그 이유, 할 수 있으면 `None`."""
        if self.withdrawn:
            return "withdrawn"
        if self.suspended:
            return "suspended"
        if not self.identity_verified:
            return "identity_required"
        if not self.adult:
            return "age_restricted"
        if self.published_count == 0:
            return "no_published_work"
        return None


def creator_payout_eligibility(user: User, published_count: int) -> CreatorPayoutEligibility:
    verified = user.identity_verified_at is not None
    return CreatorPayoutEligibility(
        withdrawn=user.deleted_at is not None,
        suspended=user.suspended_at is not None,
        identity_verified=verified,
        # 인증자는 생년월일을 갖지만, 없으면 성인이 아닌 것으로 둔다.
        adult=verified
        and user.birth_date is not None
        and not is_under_creator_payout_minimum_age(user.birth_date, datetime.now(UTC).date()),
        published_count=published_count,
    )


async def published_content_counts(db: AsyncSession, user_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, int]:
    """회원별 발행 작품 수(발행본이 있는 자기 작품). 목록이 없는 회원은 결과에 없다(0)."""
    if not user_ids:
        return {}
    rows = await db.execute(
        select(Content.creator_user_id, func.count(Content.id))
        .where(Content.creator_user_id.in_(user_ids), Content.current_published_version_id.is_not(None))
        .group_by(Content.creator_user_id)
    )
    return {creator_id: published for creator_id, published in rows.tuples()}


async def load_creator_payout_eligibility(db: AsyncSession, user: User) -> CreatorPayoutEligibility:
    counts = await published_content_counts(db, [user.id])
    return creator_payout_eligibility(user, counts.get(user.id, 0))
