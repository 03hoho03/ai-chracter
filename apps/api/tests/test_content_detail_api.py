import uuid
from datetime import date, datetime, timezone

import httpx
import pytest
import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.redis import redis_client

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
    StartingSetup,
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
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
    name: str = "이름",
    one_liner: str = "한줄소개",
    detail_description: str = "상세설명",
    hashtags: list[str] | None = None,
    chat_count: int = 0,
    like_count: int = 0,
    version_number: int = 1,
) -> tuple[Content, ContentVersion]:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=hashtags or [],
        visibility=visibility,
        moderation_status=moderation_status,
        chat_count=chat_count,
        like_count=like_count,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=version_number,
        published_at=datetime.now(timezone.utc),
        detail_description=detail_description,
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, creator_user_id)
    if content_type == ContentType.CHARACTER:
        db_session.add(
            CharacterVersionDetail(
                content_version_id=version.id,
                name=name,
                one_liner=one_liner,
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
                one_liner=one_liner,
                thumbnail_asset_id=thumbnail.id,
                prompt_template=StoryPromptTemplate.BASIC,
            )
        )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content, version


async def _add_starting_setup(
    db_session: AsyncSession, *, content_version_id: uuid.UUID, name: str, prologue: str, order: int
) -> StartingSetup:
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content_version_id,
        name=name,
        prologue=prologue,
        order=order,
    )
    db_session.add(setup)
    await db_session.flush()
    return setup


async def test_get_content_detail_returns_meta_metrics_and_version_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(nickname="작가님")
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, version = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        name="공개 캐릭터",
        one_liner="한줄",
        detail_description="상세",
        hashtags=["힐링"],
        chat_count=3,
        like_count=5,
    )
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(content.id)
    assert body["type"] == "character"
    assert body["name"] == "공개 캐릭터"
    assert body["thumbnailUrl"] is not None
    assert body["creatorUserId"] == str(user.id)
    assert body["creatorNickname"] == "작가님"
    assert body["genreId"] == str(genre.id)
    assert body["genreName"] == genre.name
    assert body["hashtags"] == ["힐링"]
    assert body["oneLiner"] == "한줄"
    assert body["detailDescription"] == "상세"
    assert body["chatCount"] == 3
    assert body["likeCount"] == 5
    assert body["isLiked"] is False
    assert body["isFavorited"] is False
    assert body["startingSetups"] is None
    assert body["versionNumber"] == 1
    assert body["isOwner"] is False
    assert body["accessStatus"] == {"kind": "accessible", "visibility": "public"}


async def test_get_content_detail_story_includes_ordered_starting_setups(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, version = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.STORY, name="스토리"
    )
    await _add_starting_setup(
        db_session, content_version_id=version.id, name="두번째", prologue="두번째 프롤로그", order=1
    )
    await _add_starting_setup(
        db_session, content_version_id=version.id, name="기본", prologue="기본 프롤로그", order=0
    )
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    setups = resp.json()["startingSetups"]
    assert [s["name"] for s in setups] == ["기본", "두번째"]
    assert setups[0]["prologue"] == "기본 프롤로그"


async def test_get_content_detail_access_status_reflects_visibility_and_moderation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    private_content, _ = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PRIVATE,
        name="비공개",
    )
    restricted_content, _ = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.RESTRICTED,
        name="이용제한",
    )
    deleted_content, _ = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.DELETED,
        name="삭제됨",
    )
    await db_session.commit()

    private_resp = await db_client.get(f"/contents/{private_content.id}")
    assert private_resp.json()["accessStatus"] == {"kind": "accessible", "visibility": "private"}

    restricted_resp = await db_client.get(f"/contents/{restricted_content.id}")
    assert restricted_resp.json()["accessStatus"] == {"kind": "restricted", "visibility": None}

    deleted_resp = await db_client.get(f"/contents/{deleted_content.id}")
    assert deleted_resp.json()["accessStatus"] == {"kind": "deleted", "visibility": None}


async def test_get_content_detail_is_owner_true_only_for_creator(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(db_session, creator_user_id=owner.id, genre_id=genre.id)
    await db_session.commit()

    anon_resp = await db_client.get(f"/contents/{content.id}")
    assert anon_resp.json()["isOwner"] is False

    await _login_as(db_client, other.id)
    other_resp = await db_client.get(f"/contents/{content.id}")
    assert other_resp.json()["isOwner"] is False

    await _login_as(db_client, owner.id)
    owner_resp = await db_client.get(f"/contents/{content.id}")
    assert owner_resp.json()["isOwner"] is True


async def test_get_content_detail_is_liked_reflects_viewers_own_like(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    liker = _make_user()
    other = _make_user()
    db_session.add_all([owner, liker, other])
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(db_session, creator_user_id=owner.id, genre_id=genre.id)
    db_session.add(Like(user_id=liker.id, content_id=content.id))
    await db_session.commit()

    anon_resp = await db_client.get(f"/contents/{content.id}")
    assert anon_resp.json()["isLiked"] is False

    await _login_as(db_client, other.id)
    other_resp = await db_client.get(f"/contents/{content.id}")
    assert other_resp.json()["isLiked"] is False

    await _login_as(db_client, liker.id)
    liker_resp = await db_client.get(f"/contents/{content.id}")
    assert liker_resp.json()["isLiked"] is True


async def test_get_content_detail_is_favorited_reflects_viewers_own_favorite(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    favoriter = _make_user()
    other = _make_user()
    db_session.add_all([owner, favoriter, other])
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(db_session, creator_user_id=owner.id, genre_id=genre.id)
    db_session.add(Favorite(user_id=favoriter.id, content_id=content.id))
    await db_session.commit()

    anon_resp = await db_client.get(f"/contents/{content.id}")
    assert anon_resp.json()["isFavorited"] is False

    await _login_as(db_client, other.id)
    other_resp = await db_client.get(f"/contents/{content.id}")
    assert other_resp.json()["isFavorited"] is False

    await _login_as(db_client, favoriter.id)
    favoriter_resp = await db_client.get(f"/contents/{content.id}")
    assert favoriter_resp.json()["isFavorited"] is True


async def test_get_content_detail_404_when_not_found_or_never_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    draft_content = Content(
        creator_user_id=user.id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(draft_content)
    await db_session.flush()
    draft_version = ContentVersion(
        content_id=draft_content.id, version_number=None, published_at=None, detail_description="설명"
    )
    db_session.add(draft_version)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, user.id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=draft_version.id,
            name="초안",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.commit()

    missing_resp = await db_client.get(f"/contents/{uuid.uuid4()}")
    assert missing_resp.status_code == 404

    draft_resp = await db_client.get(f"/contents/{draft_content.id}")
    assert draft_resp.status_code == 404


async def test_list_content_versions_returns_only_published_ordered_desc(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, version_number=1
    )
    v2 = ContentVersion(
        content_id=content.id,
        version_number=2,
        published_at=datetime.now(timezone.utc),
        detail_description="설명2",
    )
    db_session.add(v2)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, user.id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=v2.id,
            name="이름v2",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()
    content.current_published_version_id = v2.id

    draft_version = ContentVersion(
        content_id=content.id, version_number=None, published_at=None, detail_description="초안"
    )
    db_session.add(draft_version)
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}/versions")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["versionNumber"] for item in body] == [2, 1]
    assert all("publishedAt" in item for item in body)


async def test_list_content_versions_404_when_content_not_found(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/contents/{uuid.uuid4()}/versions")
    assert resp.status_code == 404


async def _view_count(db_session: AsyncSession, content_id: uuid.UUID) -> int:
    count = await db_session.scalar(sa.select(Content.view_count).where(Content.id == content_id))
    assert count is not None
    return count


async def _make_viewable_content(
    db_session: AsyncSession,
    *,
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
) -> tuple[Content, User]:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _ = await _make_published_content(
        db_session,
        creator_user_id=creator.id,
        genre_id=genre.id,
        visibility=visibility,
        moderation_status=moderation_status,
    )
    await db_session.commit()
    return content, creator


async def test_view_count_increments_on_first_view(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    # ASGITransport awaits the whole app call including background tasks, so the
    # increment must already be visible here.
    assert await _view_count(db_session, content.id) == 1


async def test_view_count_deduped_for_same_viewer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)

    await db_client.get(f"/contents/{content.id}")
    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 1


async def test_view_count_counts_distinct_guests_separately(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)

    await db_client.get(f"/contents/{content.id}")
    db_client.cookies.clear()
    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 2


async def test_view_count_counts_user_and_guest_separately(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)
    viewer = _make_user()
    db_session.add(viewer)
    await db_session.commit()

    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 1

    await _login_as(db_client, viewer.id)
    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 2


async def test_view_count_not_incremented_for_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, creator = await _make_viewable_content(db_session)

    await _login_as(db_client, creator.id)
    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_not_incremented_for_private_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session, visibility=ContentVisibility.PRIVATE)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_not_incremented_for_restricted_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(
        db_session, moderation_status=ModerationStatus.RESTRICTED
    )

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_not_incremented_for_deleted_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session, moderation_status=ModerationStatus.DELETED)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_skipped_when_redis_errors(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    content, _ = await _make_viewable_content(db_session)

    async def _raise_redis_error(*args: object, **kwargs: object) -> None:
        raise RedisError("connection refused")

    monkeypatch.setattr(redis_client, "set", _raise_redis_error)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0
