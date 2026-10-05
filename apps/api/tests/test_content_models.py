from datetime import datetime, timezone, UTC

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
from factories import _get_genre, _make_user


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
    draft.published_at = datetime.now(UTC)
    content.current_published_version_id = draft.id
    await db_session.flush()

    refreshed = await db_session.get(Content, content.id)
    assert refreshed is not None
    assert refreshed.current_published_version_id == draft.id


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


# `alembic check` 는 기존 테이블의 복합 PK 구성을 비교하지 않는다(alembic 1.18.5 의
# autogenerate/compare 에 primary_key 비교자가 없다) — favorites 의 복합 PK는 이
# 테스트에서만 검증된다.
async def test_favorite_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    user, content = await _make_user_and_content(db_session)

    db_session.add(Favorite(user_id=user.id, content_id=content.id))
    await db_session.flush()

    db_session.add(Favorite(user_id=user.id, content_id=content.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# `alembic check` 는 기존 테이블의 복합 PK 구성을 비교하지 않는다(alembic 1.18.5 의
# autogenerate/compare 에 primary_key 비교자가 없다) — likes 의 복합 PK는 이
# 테스트에서만 검증된다.
async def test_like_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    user, content = await _make_user_and_content(db_session)

    db_session.add(Like(user_id=user.id, content_id=content.id))
    await db_session.flush()

    db_session.add(Like(user_id=user.id, content_id=content.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_new_content_gets_the_all_ages_rating_without_naming_it(db_session: AsyncSession) -> None:
    """작품을 만드는 코드는 등급을 넘기지 않는다 — DB 기본값이 채운다. 기본값이 빠지면 모든 작품 생성이 NOT NULL
    위반으로 실패한다. `alembic check` 는 `server_default` 를 비교하지 않아 이 테스트가 유일한 신호다."""
    _, content = await _make_user_and_content(db_session)

    rating = await db_session.scalar(sa.select(Content.rating).where(Content.id == content.id))

    assert rating == "all"


async def test_adult_rating_is_rejected_by_the_database(db_session: AsyncSession) -> None:
    """성인 등급은 어떤 경로로도 저장되면 안 된다(CHECK). 파이썬 타입은 코드의 대입만 막고 raw SQL·관리 스크립트는
    DB 만 막는다. `alembic check` 가 CHECK 를 비교하지 않아 이 테스트가 유일한 검증이다."""
    _, content = await _make_user_and_content(db_session)

    with pytest.raises(IntegrityError):
        await db_session.execute(sa.text("UPDATE contents SET rating = 'adult' WHERE id = :id"), {"id": content.id})
