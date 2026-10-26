"""원작 상세의 공개 소설 목록 숨김 칸을 더하는 마이그레이션 `296e34a7182f` 의 배포 겹침 안전성.

배포 동안 옛 이미지가 이 스키마 위에서 작품을 만든다. 옛 코드의 INSERT 는 이 칸을 모르므로 서버 기본값이 채워야 하고,
그 값은 "보임"이어야 한다 — 기본값이 빠지면 옛 코드의 작품 생성이 NOT NULL 위반(500)이고, 거짓이면 그 작품의 공개 소설이
원작자가 고르지 않았는데 숨는다. `alembic check` 는 서버 기본값을 비교하지 않아 이 검사가 유일한 신호다."""

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.content import Content
from factories import _make_user


async def test_a_work_inserted_without_the_column_is_visible(db_session: AsyncSession) -> None:
    """칸 이름을 뺀 INSERT(옛 이미지의 작품 생성과 같은 꼴)가 성공하고 "보임"으로 들어간다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content_id = uuid.uuid4()

    await db_session.execute(
        sa.text(
            "INSERT INTO contents (id, creator_user_id, type, hashtags, visibility, moderation_status) "
            "VALUES (:id, :creator, 'CHARACTER', '{}', 'PRIVATE', 'NORMAL')"
        ),
        {"id": content_id, "creator": creator.id},
    )

    visible = await db_session.scalar(sa.select(Content.derived_novels_visible).where(Content.id == content_id))
    assert visible is True
