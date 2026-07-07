import uuid
from datetime import date, datetime, timezone

import httpx
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
    Genre,
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
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
    name: str,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=visibility,
        moderation_status=moderation_status,
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


async def _make_draft_only_content(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id, version_number=None, published_at=None, detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, creator_user_id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="초안",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()
    return content


async def test_list_user_contents_excludes_never_published_drafts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _make_draft_only_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "character"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_user_contents_returns_published_content_for_stranger(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="공개 캐릭터"
    )
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "character"})
    assert resp.status_code == 200
    [item] = resp.json()
    assert item["id"] == str(content.id)
    assert item["name"] == "공개 캐릭터"
    assert item["type"] == "character"
    assert item["visibility"] == "public"
    assert item["moderationStatus"] == "normal"
    assert item["viewCount"] == 0
    assert "thumbnailAssetId" in item
    assert item["thumbnailUrl"] is not None


async def test_list_user_contents_hides_link_and_private_from_stranger(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.LINK,
        name="링크공개",
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PRIVATE,
        name="비공개",
    )
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "character"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_user_contents_hides_restricted_and_deleted_from_stranger(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.RESTRICTED,
        name="이용제한",
    )
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "character"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_user_contents_ignores_visibility_param_for_stranger(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PRIVATE,
        name="비공개",
    )
    await db_session.commit()

    resp = await db_client.get(
        f"/users/{user.id}/contents", params={"type": "character", "visibility": "private"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_user_contents_owner_default_all_includes_restricted_but_not_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PRIVATE,
        name="비공개",
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.RESTRICTED,
        name="이용제한",
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.DELETED,
        name="삭제됨",
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "character"})
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert names == {"비공개", "이용제한"}


async def test_list_user_contents_owner_specific_visibility_excludes_restricted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.RESTRICTED,
        name="공개-이용제한",
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PUBLIC,
        name="공개-정상",
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(
        f"/users/{user.id}/contents", params={"type": "character", "visibility": "public"}
    )
    assert resp.status_code == 200
    [item] = resp.json()
    assert item["name"] == "공개-정상"


async def test_list_user_contents_filters_by_type(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="캐릭터"
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        content_type=ContentType.STORY,
        name="스토리",
    )
    await db_session.commit()

    resp = await db_client.get(f"/users/{user.id}/contents", params={"type": "story"})
    assert resp.status_code == 200
    [item] = resp.json()
    assert item["name"] == "스토리"
    assert item["type"] == "story"
