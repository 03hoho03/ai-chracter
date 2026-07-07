import uuid
from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    CharacterImageExposure,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    StoryEndingUnlock,
    User,
)


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(timezone.utc),
        "privacy_agreed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _make_published_version(db_session: AsyncSession, user: User) -> ContentVersion:
    genre_result = await db_session.execute(sa.select(Genre).limit(1))
    genre = genre_result.scalar_one()

    content = Content(
        type=ContentType.STORY,
        creator_user_id=user.id,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(timezone.utc),
        detail_description="발행된 버전",
    )
    db_session.add(version)
    await db_session.flush()

    return version


async def _make_chat_room(db_session: AsyncSession, **overrides: object) -> ChatRoom:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_published_version(db_session, user)

    defaults: dict[str, object] = {
        "user_id": user.id,
        "content_id": version.content_id,
        "content_version_id": version.id,
    }
    defaults.update(overrides)
    room = ChatRoom(**defaults)
    db_session.add(room)
    await db_session.flush()
    return room


async def test_chat_room_pins_to_content_version_with_defaults(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)

    assert room.turn_count == 0
    assert room.ending_reached is False
    assert room.version_auto_upgraded is False
    assert room.ending_entity_id is None
    assert room.name is None


async def test_chat_room_rejects_unknown_content_version(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_published_version(db_session, user)

    room = ChatRoom(user_id=user.id, content_id=version.content_id, content_version_id=uuid.uuid4())
    db_session.add(room)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_chat_message_attaches_to_chat_room(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)

    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="안녕하세요")
    db_session.add(message)
    await db_session.flush()

    assert message.role == ChatMessageRole.USER


async def test_chat_message_rejects_unknown_chat_room(db_session: AsyncSession) -> None:
    message = ChatMessage(chat_room_id=uuid.uuid4(), role=ChatMessageRole.ASSISTANT, content="안녕하세요")
    db_session.add(message)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_chat_room_stat_composite_pk_allows_multiple_stats_per_room(
    db_session: AsyncSession,
) -> None:
    room = await _make_chat_room(db_session)

    stat_a = ChatRoomStat(chat_room_id=room.id, stat_entity_id=uuid.uuid4(), current_value=50)
    stat_b = ChatRoomStat(chat_room_id=room.id, stat_entity_id=uuid.uuid4(), current_value=10)
    db_session.add_all([stat_a, stat_b])
    await db_session.flush()

    assert stat_a.chat_room_id == stat_b.chat_room_id
    assert stat_a.stat_entity_id != stat_b.stat_entity_id


async def test_chat_room_stat_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)
    stat_entity_id = uuid.uuid4()

    db_session.add(ChatRoomStat(chat_room_id=room.id, stat_entity_id=stat_entity_id, current_value=50))
    await db_session.flush()

    db_session.add(ChatRoomStat(chat_room_id=room.id, stat_entity_id=stat_entity_id, current_value=60))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_story_ending_unlock_accumulates_per_user_and_starting_setup(
    db_session: AsyncSession,
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    unlock = StoryEndingUnlock(
        user_id=user.id,
        starting_setup_entity_id=uuid.uuid4(),
        ending_entity_id=uuid.uuid4(),
    )
    db_session.add(unlock)
    await db_session.flush()

    assert unlock.first_reached_at is not None


async def test_story_ending_unlock_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    starting_setup_entity_id = uuid.uuid4()
    ending_entity_id = uuid.uuid4()

    db_session.add(
        StoryEndingUnlock(
            user_id=user.id,
            starting_setup_entity_id=starting_setup_entity_id,
            ending_entity_id=ending_entity_id,
        )
    )
    await db_session.flush()

    db_session.add(
        StoryEndingUnlock(
            user_id=user.id,
            starting_setup_entity_id=starting_setup_entity_id,
            ending_entity_id=ending_entity_id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_character_image_exposure_accumulates_per_user_and_content(
    db_session: AsyncSession,
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_published_version(db_session, user)

    exposure = CharacterImageExposure(
        user_id=user.id,
        content_id=version.content_id,
        image_entity_id=uuid.uuid4(),
    )
    db_session.add(exposure)
    await db_session.flush()

    assert exposure.first_exposed_at is not None


async def test_character_image_exposure_rejects_unknown_content(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    exposure = CharacterImageExposure(
        user_id=user.id,
        content_id=uuid.uuid4(),
        image_entity_id=uuid.uuid4(),
    )
    db_session.add(exposure)

    with pytest.raises(IntegrityError):
        await db_session.flush()
