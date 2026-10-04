"""발행 쓰기 구간의 작품 행 잠금 — 독립 커넥션이 있어야만 검증된다.

발행은 심사를 기다리는 동안 트랜잭션을 쥐지 않으므로, 같은 초안의 발행 둘이 쓰기 구간에 거의 같이 들어올 수 있다.
쓰기 구간은 작품 행을 `FOR UPDATE` 로 잠근 뒤 초안이 아직 초안인지 다시 읽는다. 잠금이 없으면 둘 다 "아직 초안"을 읽고
둘 다 발행해 발행본 번호를 덮어쓰고 초안을 둘 만든다. `db_session` 하나 위에서는 두 세션이 같은 트랜잭션이라 잠금이
서로를 막지 않으므로, 여기서는 엔진에서 커넥션을 따로 받아 진짜로 다투게 한다.

🔴 여기서 쓴 행은 롤백되지 않는다 — 픽스처가 직접 지운다. 그 픽스처가 만든 작품만 지운다.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.content.router import _lock_draft_for_publish
from api.db.models import Content, ContentType, ContentVersion, ContentVisibility, ModerationStatus, User
from factories import _assert_blocked, _make_user


@dataclass(frozen=True)
class _CommittedDraft:
    factory: async_sessionmaker[AsyncSession]
    content_id: uuid.UUID
    version_id: uuid.UUID


@pytest_asyncio.fixture
async def committed_draft(db_engine: AsyncEngine) -> AsyncGenerator[_CommittedDraft, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        user = _make_user()
        db.add(user)
        await db.flush()
        content = Content(
            creator_user_id=user.id,
            type=ContentType.CHARACTER,
            hashtags=[],
            visibility=ContentVisibility.PRIVATE,
            moderation_status=ModerationStatus.NORMAL,
        )
        db.add(content)
        await db.flush()
        version = ContentVersion(content_id=content.id, detail_description="")
        db.add(version)
        await db.commit()
    try:
        yield _CommittedDraft(factory, content.id, version.id)
    finally:
        async with factory() as db:
            await db.execute(sa.delete(ContentVersion).where(ContentVersion.content_id == content.id))
            await db.execute(sa.delete(Content).where(Content.id == content.id))
            await db.execute(sa.delete(User).where(User.id == user.id))
            await db.commit()


async def test_publish_lock_makes_a_second_publish_wait_and_then_refuse(committed_draft: _CommittedDraft) -> None:
    """판정 기준(결과를 보기 전에 적었다): 첫 발행이 쓰기 구간에 있는 동안 두 번째 발행의 쓰기 구간은 잠금에서 멈춰
    있어야 하고(`_assert_blocked`), 첫 발행이 초안을 발행본으로 커밋한 뒤에는 409 `PUBLISH_CONFLICT` 로 끝나야 한다.
    멈추지 않거나 409 가 아니면 실패다."""
    factory = committed_draft.factory
    async with factory() as first, factory() as second:
        _, version = await _lock_draft_for_publish(first, committed_draft.content_id, committed_draft.version_id)

        waiting = asyncio.create_task(
            _lock_draft_for_publish(second, committed_draft.content_id, committed_draft.version_id)
        )
        await _assert_blocked(waiting)

        version.version_number = 1
        version.published_at = datetime.now(UTC)
        await first.commit()

        with pytest.raises(HTTPException) as refused:
            await waiting
        await second.commit()

    detail: object = refused.value.detail
    assert refused.value.status_code == 409
    assert detail == {"code": "PUBLISH_CONFLICT"}
