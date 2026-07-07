import uuid
from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Favorite,
    Genre,
    Like,
    ModerationStatus,
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


async def _get_genre(db_session: AsyncSession, name: str) -> Genre:
    result = await db_session.execute(sa.select(Genre).where(Genre.name == name))
    genre = result.scalar_one()
    return genre


def _make_content(user: User, genre: Genre, **overrides: object) -> Content:
    defaults: dict[str, object] = {
        "type": ContentType.CHARACTER,
        "creator_user_id": user.id,
        "genre_id": genre.id,
        "target": ContentTarget.ALL,
        "hashtags": [],
        "visibility": ContentVisibility.PUBLIC,
        "moderation_status": ModerationStatus.NORMAL,
    }
    defaults.update(overrides)
    return Content(**defaults)


async def test_genres_are_seeded(db_session: AsyncSession) -> None:
    result = await db_session.execute(sa.select(sa.func.count()).select_from(Genre))
    assert result.scalar_one() == 10

    romance = await _get_genre(db_session, "로맨스")
    assert romance.sort_order == 1


async def test_content_requires_existing_genre_and_creator(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session, "판타지")

    content = _make_content(user, genre)
    db_session.add(content)
    await db_session.flush()

    assert content.id is not None
    assert content.view_count == 0
    assert content.like_count == 0
    assert content.chat_count == 0


async def test_content_rejects_unknown_genre(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    content = _make_content(user, Genre(id=uuid.uuid4(), name="unused", sort_order=0))
    db_session.add(content)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_content_version_pins_to_content_and_updates_current_published(
    db_session: AsyncSession,
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session, "SF")

    content = _make_content(user, genre)
    db_session.add(content)
    await db_session.flush()

    draft = ContentVersion(content_id=content.id, detail_description="초안 설명")
    db_session.add(draft)
    await db_session.flush()
    assert draft.published_at is None
    assert draft.version_number is None

    draft.version_number = 1
    draft.published_at = datetime.now(timezone.utc)
    content.current_published_version_id = draft.id
    await db_session.flush()

    refreshed = await db_session.get(Content, content.id)
    assert refreshed is not None
    assert refreshed.current_published_version_id == draft.id


async def test_content_version_rejects_unknown_content(db_session: AsyncSession) -> None:
    version = ContentVersion(content_id=uuid.uuid4(), detail_description="설명")
    db_session.add(version)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def _make_user_and_content(db_session: AsyncSession) -> tuple[User, Content]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session, "일상")

    content = _make_content(user, genre)
    db_session.add(content)
    await db_session.flush()
    return user, content


async def test_favorite_composite_pk_allows_same_content_favorited_by_two_users(
    db_session: AsyncSession,
) -> None:
    _, content = await _make_user_and_content(db_session)
    other_user = _make_user()
    db_session.add(other_user)
    await db_session.flush()

    db_session.add(Favorite(user_id=other_user.id, content_id=content.id))
    another_user = _make_user()
    db_session.add(another_user)
    await db_session.flush()
    db_session.add(Favorite(user_id=another_user.id, content_id=content.id))
    await db_session.flush()


async def test_favorite_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    user, content = await _make_user_and_content(db_session)

    db_session.add(Favorite(user_id=user.id, content_id=content.id))
    await db_session.flush()

    db_session.add(Favorite(user_id=user.id, content_id=content.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_like_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    user, content = await _make_user_and_content(db_session)

    db_session.add(Like(user_id=user.id, content_id=content.id))
    await db_session.flush()

    db_session.add(Like(user_id=user.id, content_id=content.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_like_rejects_unknown_content(db_session: AsyncSession) -> None:
    user, _ = await _make_user_and_content(db_session)

    db_session.add(Like(user_id=user.id, content_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.flush()
