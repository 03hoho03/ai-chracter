"""작품의 마지막 편집 시각 칸을 더하는 마이그레이션 `35bbef005344` 의 백필 검증.

마이그레이션 자체는 다시 돌리지 않는다. 세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했으므로 백필
문장을 테스트마다 롤백되는 `db_session` 커넥션에서 그대로 실행한다. 작품·버전은 생성자로 직접 넣고 시각을 명시한다."""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.content import Content, ContentType, ContentVersion, ContentVisibility, ModerationStatus
from factories import _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("35bbef005344")

_CREATED = datetime(2026, 3, 1, tzinfo=UTC)
_FIRST_PUBLISH = datetime(2026, 4, 1, tzinfo=UTC)
_LAST_PUBLISH = datetime(2026, 5, 1, tzinfo=UTC)


async def _content(db_session: AsyncSession, creator_user_id: uuid.UUID) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
        created_at=_CREATED,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def test_backfill_uses_the_latest_publish_time_or_else_the_creation_time(db_session: AsyncSession) -> None:
    """발행 이력이 있으면 가장 늦은 발행 시각, 없으면 생성 시각이 들어간다. 발행 뒤 딸린 초안 버전(발행 시각 없음)은
    값에 끼지 않는다.

    빨개지는 조건: `max` 대신 `min` 을 쓰면 첫 작품이 첫 발행 시각, `GREATEST` 가 NULL 을 무시하지 않는 꼴(예: 발행
    시각을 그대로 대입)이면 둘째 작품이 NULL 위반으로 실패한다. 작품마다 묶지 않으면 두 작품이 같은 값을 받는다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    published = await _content(db_session, creator.id)
    never_published = await _content(db_session, creator.id)
    db_session.add_all(
        [
            ContentVersion(
                content_id=published.id, version_number=1, published_at=_FIRST_PUBLISH, detail_description="합성 1"
            ),
            ContentVersion(
                content_id=published.id, version_number=2, published_at=_LAST_PUBLISH, detail_description="합성 2"
            ),
            ContentVersion(content_id=published.id, detail_description="합성 초안"),
            ContentVersion(content_id=never_published.id, detail_description="합성 초안"),
        ]
    )
    await db_session.flush()

    await db_session.execute(sa.text(_M.BACKFILL_EDITED_AT_SQL))

    rows = await db_session.execute(
        sa.select(Content.id, Content.edited_at).where(Content.id.in_([published.id, never_published.id]))
    )
    assert dict(rows.tuples().all()) == {published.id: _LAST_PUBLISH, never_published.id: _CREATED}
