"""소설의 연재권 잠금. 소설이 처음 독자에게 보인 순간(첫 공개, 운영자 승인이 있으면 승인) 한 번 찍히고 풀리지 않는다.
잠금 기록은 정책 스위치(`novel_public_policy_v2_enabled`)와 무관하게 쓴다 — 꺼진 동안 공개된 소설도 그때 잠겨야 나중에
켰을 때 승인 대기 없이 이어 공개한다. 잠금이 효력을 갖는 것(원작자가 소설화 허락을 거둬도 다음 화를 이어 공개, 첫 공개의
운영자 승인 면제)은 스위치가 켜졌을 때뿐이다.

잠금은 한 번만 찍는다 — `serial_locked_at IS NULL` 조건을 걸어 먼저 찍힌 시각·출처·허락 사본·원작 버전·약관 판을 덮지
않는다(집필권 잠금과 같은 꼴)."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.content import Content
from api.db.models.novel import Novel


def lock_in_effect(novel: Novel) -> bool:
    """이 소설의 연재권 잠금이 지금 효력이 있는가 — 스위치가 켜졌고 잠겨 있다. 원작 판정이 허락을 건너뛸지 이것으로 정한다."""
    return settings.novel_public_policy_v2_enabled and novel.serial_locked_at is not None


def needs_review(novel: Novel) -> bool:
    """이 소설을 독자에게 처음 내보내려면 운영자 승인이 필요한가 — 스위치가 켜졌고 아직 잠기지 않았다. 잠금이 곧 "독자에게
    한 번이라도 보였다"의 기록이라 따로 첫 공개 표식을 두지 않는다."""
    return settings.novel_public_policy_v2_enabled and novel.serial_locked_at is None


async def lock_serial(db: AsyncSession, novel_id: uuid.UUID, *, terms_version: str | None) -> None:
    """공개 쓰기·승인 트랜잭션 안에서 아직 잠기지 않은 소설을 잠근다. 허락 사본과 원작 버전은 그 순간 원작 행의 값(원작
    행이 없으면 NULL)이고, 원작 버전은 공개 판정이 보는 지금 게시본이다. 약관 판은 그 순간 시행 중인 판이다(게시본이 없으면
    NULL)."""
    await db.execute(
        update(Novel)
        .where(Novel.id == novel_id, Novel.serial_locked_at.is_(None))
        .values(
            serial_locked_at=func.now(),
            serial_lock_permission=select(Content.novel_permission)
            .where(Content.id == Novel.content_id)
            .scalar_subquery(),
            serial_lock_content_version_id=select(Content.current_published_version_id)
            .where(Content.id == Novel.content_id)
            .scalar_subquery(),
            serial_lock_terms_version=terms_version,
            serial_lock_source="first_publish",
        )
    )
