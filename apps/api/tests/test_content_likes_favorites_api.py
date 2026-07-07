import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    CharacterVersionDetail,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Favorite,
    Genre,
    Like,
    ModerationStatus,
    StoryPromptTemplate,
    StoryVersionDetail,
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


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_asset(db_session: AsyncSession, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_published_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    content_type: ContentType = ContentType.CHARACTER,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
    like_count: int = 0,
    name: str,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=moderation_status,
        like_count=like_count,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(timezone.utc),
        detail_description="설명",
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, creator_user_id)
    if content_type == ContentType.CHARACTER:
        db_session.add(
            CharacterVersionDetail(
                content_version_id=version.id,
                name=name,
                one_liner="한줄소개",
                thumbnail_asset_id=thumbnail.id,
                intro="인트로",
                example_dialogues=[],
                character_prompt="프롬프트",
            )
        )
    else:
        db_session.add(
            StoryVersionDetail(
                content_version_id=version.id,
                name=name,
                one_liner="한줄소개",
                thumbnail_asset_id=thumbnail.id,
                prompt_template=StoryPromptTemplate.BASIC,
            )
        )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _count_likes(db_session: AsyncSession, user_id: uuid.UUID, content_id: uuid.UUID) -> int:
    result = await db_session.execute(
        sa.select(sa.func.count()).select_from(Like).where(
            Like.user_id == user_id, Like.content_id == content_id
        )
    )
    return result.scalar_one()


async def _count_favorites(db_session: AsyncSession, user_id: uuid.UUID, content_id: uuid.UUID) -> int:
    result = await db_session.execute(
        sa.select(sa.func.count()).select_from(Favorite).where(
            Favorite.user_id == user_id, Favorite.content_id == content_id
        )
    )
    return result.scalar_one()


async def test_like_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(f"/contents/{uuid.uuid4()}/like")
    assert resp.status_code == 401


async def test_like_unknown_content_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(f"/contents/{uuid.uuid4()}/like")
    assert resp.status_code == 404


async def test_like_then_unlike_updates_count_and_is_idempotent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="캐릭터"
    )
    await db_session.commit()

    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/like")
    assert resp.status_code == 204
    # Repeat like is a no-op, not a second row / double increment.
    resp = await db_client.post(f"/contents/{content.id}/like")
    assert resp.status_code == 204

    await db_session.refresh(content)
    assert content.like_count == 1
    assert await _count_likes(db_session, user.id, content.id) == 1

    resp = await db_client.delete(f"/contents/{content.id}/like")
    assert resp.status_code == 204
    # Repeat unlike is a no-op.
    resp = await db_client.delete(f"/contents/{content.id}/like")
    assert resp.status_code == 204

    await db_session.refresh(content)
    assert content.like_count == 0
    assert await _count_likes(db_session, user.id, content.id) == 0


async def test_favorite_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(f"/contents/{uuid.uuid4()}/favorite")
    assert resp.status_code == 401


async def test_favorite_unknown_content_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.delete(f"/contents/{uuid.uuid4()}/favorite")
    assert resp.status_code == 404


async def test_favorite_then_unfavorite_is_idempotent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="캐릭터"
    )
    await db_session.commit()

    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/favorite")
    assert resp.status_code == 204
    resp = await db_client.post(f"/contents/{content.id}/favorite")
    assert resp.status_code == 204
    assert await _count_favorites(db_session, user.id, content.id) == 1

    resp = await db_client.delete(f"/contents/{content.id}/favorite")
    assert resp.status_code == 204
    resp = await db_client.delete(f"/contents/{content.id}/favorite")
    assert resp.status_code == 204
    assert await _count_favorites(db_session, user.id, content.id) == 0


async def test_list_favorites_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/me/favorites")
    assert resp.status_code == 401


async def test_list_favorites_returns_favorited_contents_most_recently_favorited_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Favorite rows are inserted directly (rather than via two live POSTs) with distinct
    # created_at values: db_client's whole test runs inside one outer Postgres transaction
    # (see conftest.py's db_session fixture), and `now()` resolves to that transaction's
    # start time for every statement in it, so two live POSTs here would tie on created_at.
    user = _make_user()
    creator = _make_user()
    db_session.add_all([user, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    now = datetime.now(timezone.utc)

    character = await _make_published_content(
        db_session,
        creator_user_id=creator.id,
        genre_id=genre.id,
        content_type=ContentType.CHARACTER,
        name="즐겨찾기 캐릭터",
    )
    story = await _make_published_content(
        db_session,
        creator_user_id=creator.id,
        genre_id=genre.id,
        content_type=ContentType.STORY,
        name="즐겨찾기 스토리",
    )
    await _make_published_content(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="즐겨찾기 안 함"
    )
    db_session.add_all(
        [
            Favorite(user_id=user.id, content_id=character.id, created_at=now - timedelta(minutes=1)),
            Favorite(user_id=user.id, content_id=story.id, created_at=now),
        ]
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/favorites")
    assert resp.status_code == 200
    body = resp.json()
    names = [item["name"] for item in body["items"]]
    assert names == ["즐겨찾기 스토리", "즐겨찾기 캐릭터"]
    assert "즐겨찾기 안 함" not in names
    assert body["nextCursor"] is None
    assert body["items"][0]["type"] == "story"
    assert body["items"][0]["creatorUserId"] == str(creator.id)


async def test_list_favorites_excludes_deleted_moderation_status(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    creator = _make_user()
    db_session.add_all([user, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)

    deleted_content = await _make_published_content(
        db_session,
        creator_user_id=creator.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.DELETED,
        name="삭제됨",
    )
    restricted_content = await _make_published_content(
        db_session,
        creator_user_id=creator.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.RESTRICTED,
        name="이용제한",
    )
    db_session.add_all(
        [
            Favorite(user_id=user.id, content_id=deleted_content.id),
            Favorite(user_id=user.id, content_id=restricted_content.id),
        ]
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/favorites")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    # Restricted content is still a live bookmark; only the fully-hidden "deleted" one drops out.
    assert names == ["이용제한"]


async def test_list_favorites_cursor_pagination_covers_all_items_without_duplicates(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.content.router.FAVORITES_PAGE_SIZE", 2)

    user = _make_user()
    creator = _make_user()
    db_session.add_all([user, creator])
    await db_session.flush()
    genre = await _get_genre(db_session)
    now = datetime.now(timezone.utc)

    expected_names = [f"즐겨찾기-{i}" for i in range(5)]
    contents = []
    for name in expected_names:
        content = await _make_published_content(
            db_session, creator_user_id=creator.id, genre_id=genre.id, name=name
        )
        contents.append(content)
    await db_session.flush()

    for i, content in enumerate(contents):
        db_session.add(
            Favorite(user_id=user.id, content_id=content.id, created_at=now - timedelta(minutes=i))
        )
    await db_session.commit()

    await _login_as(db_client, user.id)

    collected: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str] = {}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await db_client.get("/me/favorites", params=params)
        assert resp.status_code == 200
        body = resp.json()
        collected.extend(item["name"] for item in body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert collected == expected_names
