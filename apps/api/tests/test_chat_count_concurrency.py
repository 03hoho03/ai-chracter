"""대화수 증가의 경쟁 — 롤백되지 않는 독립 커넥션 둘이 있어야만 검증된다.

`db_session`/`db_client` 는 한 커넥션 위의 한 트랜잭션이라 두 요청이 같은 작품 행을 두고 다툴 수 없다. 그 위에서
`asyncio.gather` 로 묶어도 순차 실행이라 아무것도 논증하지 못한다.

경쟁시키는 쪽은 **서로 다른 두 사용자**다. 같은 사용자의 두 요청은 방 생성 경로가 먼저 잡는 회원 행 잠금으로 이미
직렬화되므로, 읽은 값에 1을 더해 쓰는 잘못된 구현으로도 2가 나와 신호가 없다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.chat.chat_count import record_chat_participant
from api.db.models import (
    Content,
    ContentChatParticipant,
    ContentType,
    ContentVisibility,
    ModerationStatus,
    User,
)
from factories import _assert_blocked, _make_user

# teardown 이 지울 대상을 고르는 표지다. 이 파일이 만든 회원과 그 작품만 지운다.
_MARKER_DOMAIN = "chat-count-independent.test"


@pytest_asyncio.fixture
async def independent_session_factory(
    db_engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """엔진에서 직접 만든 세션 팩토리 — 세션마다 풀에서 다른 커넥션을 받고, 쓴 행은 롤백되지 않는다.

    teardown 이 표지 도메인 회원의 기록 행 → 작품 → 회원 순으로 직접 지운다(FK 에 `ON DELETE` 가 없다)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (
            await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))
        ).all()
        if user_ids:
            content_ids = (
                await cleanup.scalars(select(Content.id).where(Content.creator_user_id.in_(user_ids)))
            ).all()
            await cleanup.execute(
                delete(ContentChatParticipant).where(
                    ContentChatParticipant.user_id.in_(user_ids)
                    | ContentChatParticipant.content_id.in_(content_ids)
                )
            )
            await cleanup.execute(delete(Content).where(Content.id.in_(content_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """작가 한 명의 작품 하나와 다른 사용자 둘을 **커밋해서** 만든다. 증가 함수는 작품 행만 보므로 발행본은 없다."""
    async with factory() as session:
        author, first, second = (_make_user(email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}") for _ in range(3))
        session.add_all([author, first, second])
        await session.flush()
        content = Content(
            type=ContentType.CHARACTER,
            creator_user_id=author.id,
            hashtags=[],
            visibility=ContentVisibility.PUBLIC,
            moderation_status=ModerationStatus.NORMAL,
        )
        session.add(content)
        await session.commit()
        return content.id, first.id, second.id


async def test_two_users_starting_at_the_same_time_both_count(
    independent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """두 요청이 각자 작품을 읽은 뒤(값 0) 증가한다. 먼저 쓴 쪽이 커밋할 때까지 다른 쪽은 작품 행 잠금에 막혀
    있어야 하고, 풀린 뒤에는 커밋된 값 위에 더해 2가 돼야 한다.

    빨개지는 조건: 증가를 읽어 둔 값에 1을 더해 쓰는 형태(`content.chat_count = content.chat_count + 1`)로 바꾸면
    두 번째 요청도 0 + 1 을 써서 1이 된다."""
    content_id, first_id, second_id = await _seed(independent_session_factory)

    async with independent_session_factory() as first, independent_session_factory() as second:
        # 라우트가 하듯 작품을 먼저 읽는다 — 두 세션 모두 값 0 을 본다.
        first_content = await first.get(Content, content_id)
        second_content = await second.get(Content, content_id)
        assert first_content is not None and second_content is not None

        await record_chat_participant(first, first_content, first_id)

        async def second_request() -> None:
            await record_chat_participant(second, second_content, second_id)
            await second.commit()

        task = asyncio.create_task(second_request())
        await _assert_blocked(task)
        await first.commit()
        await task

    async with independent_session_factory() as reader:
        assert await reader.scalar(select(Content.chat_count).where(Content.id == content_id)) == 2
