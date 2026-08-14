import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail


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


async def test_generated_images_requires_login(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()

    resp = await api_client.get("/me/generated-images")
    assert resp.status_code == 401


async def test_generated_images_empty_when_none_generated(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me/generated-images")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_generated_images_lists_own_ready_generated_assets_newest_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.commit()
    await _login_as(db_client, owner.id)

    now = datetime.now(timezone.utc)
    older_id = uuid.uuid4()
    newer_id = uuid.uuid4()
    db_session.add_all(
        [
            Asset(
                id=older_id,
                owner_user_id=owner.id,
                storage_key=f"assets/generated/{older_id}.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
                created_at=now - timedelta(minutes=5),
            ),
            Asset(
                id=newer_id,
                owner_user_id=owner.id,
                storage_key=f"assets/generated/{newer_id}.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
                created_at=now,
            ),
            # excluded: not GENERATED
            Asset(
                id=uuid.uuid4(),
                owner_user_id=owner.id,
                storage_key="assets/original/other.png",
                kind=AssetKind.ORIGINAL,
                status=AssetStatus.READY,
            ),
            # excluded: still pending
            Asset(
                id=uuid.uuid4(),
                owner_user_id=owner.id,
                storage_key="assets/generated/pending.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.PENDING,
            ),
            # excluded: another user's generated asset
            Asset(
                id=uuid.uuid4(),
                owner_user_id=other.id,
                storage_key="assets/generated/other-user.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
            ),
        ]
    )
    await db_session.commit()

    resp = await db_client.get("/me/generated-images")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["assetId"] for item in body] == [str(newer_id), str(older_id)]
    for item in body:
        assert item["imageUrl"].startswith("http")
        assert "createdAt" in item


async def _make_generated_asset(db_session: AsyncSession, owner_user_id: uuid.UUID) -> Asset:
    asset_id = uuid.uuid4()
    asset = Asset(
        id=asset_id,
        owner_user_id=owner_user_id,
        storage_key=f"assets/generated/{asset_id}.png",
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_character_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    name: str = "캐릭터",
    thumbnail_asset_id: uuid.UUID | None = None,
    published: bool = True,
) -> tuple[Content, ContentVersion]:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    version = ContentVersion(
        content_id=content.id,
        version_number=1 if published else None,
        published_at=datetime.now(timezone.utc) if published else None,
        detail_description="",
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner="",
            thumbnail_asset_id=thumbnail_asset_id,
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    )
    await db_session.flush()
    return content, version


async def _make_story_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    name: str = "스토리",
    thumbnail_asset_id: uuid.UUID | None = None,
) -> tuple[Content, ContentVersion]:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
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
        detail_description="",
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner="",
            thumbnail_asset_id=thumbnail_asset_id,
            prompt_template=StoryPromptTemplate.BASIC,
        )
    )
    await db_session.flush()
    return content, version


async def _get_usages(client: httpx.AsyncClient, asset_id: uuid.UUID) -> list[dict[str, object]]:
    resp = await client.get("/me/generated-images")
    assert resp.status_code == 200
    item = next(i for i in resp.json() if i["assetId"] == str(asset_id))
    usages = item["usages"]
    assert isinstance(usages, list)
    return usages


async def test_generated_image_unused_has_empty_usages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == []


async def test_generated_image_used_as_character_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, _ = await _make_character_content(
        db_session, creator_user_id=user.id, name="캐릭터A", thumbnail_asset_id=asset.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == [
        {
            "contentId": str(content.id),
            "contentType": "character",
            "contentTitle": "캐릭터A",
            "field": "thumbnail",
        }
    ]


async def test_generated_image_used_as_story_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, _ = await _make_story_content(
        db_session, creator_user_id=user.id, name="스토리A", thumbnail_asset_id=asset.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == [
        {
            "contentId": str(content.id),
            "contentType": "story",
            "contentTitle": "스토리A",
            "field": "thumbnail",
        }
    ]


async def test_generated_image_used_as_situational_image_original(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, version = await _make_character_content(
        db_session, creator_user_id=user.id, name="캐릭터B"
    )
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=version.id,
            image_asset_id=asset.id,
            trigger_condition="조건",
            order=0,
        )
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == [
        {
            "contentId": str(content.id),
            "contentType": "character",
            "contentTitle": "캐릭터B",
            "field": "situationalImage",
        }
    ]


async def test_generated_image_used_as_situational_image_blurred(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, version = await _make_character_content(
        db_session, creator_user_id=user.id, name="캐릭터C"
    )
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=version.id,
            blurred_asset_id=asset.id,
            trigger_condition="조건",
            order=0,
        )
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == [
        {
            "contentId": str(content.id),
            "contentType": "character",
            "contentTitle": "캐릭터C",
            "field": "situationalImage",
        }
    ]


async def test_generated_image_used_by_two_contents_has_two_usages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    character, _ = await _make_character_content(
        db_session, creator_user_id=user.id, name="캐릭터D", thumbnail_asset_id=asset.id
    )
    story, _ = await _make_story_content(
        db_session, creator_user_id=user.id, name="스토리D", thumbnail_asset_id=asset.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    usages = await _get_usages(db_client, asset.id)
    assert sorted(usages, key=lambda u: str(u["contentId"])) == sorted(
        [
            {
                "contentId": str(character.id),
                "contentType": "character",
                "contentTitle": "캐릭터D",
                "field": "thumbnail",
            },
            {
                "contentId": str(story.id),
                "contentType": "story",
                "contentTitle": "스토리D",
                "field": "thumbnail",
            },
        ],
        key=lambda u: str(u["contentId"]),
    )


async def test_generated_image_referenced_only_by_draft_version_counts_as_used(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, _ = await _make_character_content(
        db_session, creator_user_id=user.id, name="초안캐릭터", thumbnail_asset_id=asset.id, published=False
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == [
        {
            "contentId": str(content.id),
            "contentType": "character",
            "contentTitle": "초안캐릭터",
            "field": "thumbnail",
        }
    ]


async def test_generated_image_same_content_same_field_multiple_versions_merged(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, published_version = await _make_character_content(
        db_session, creator_user_id=user.id, name="구버전이름", thumbnail_asset_id=asset.id
    )
    # 같은 콘텐츠의 더 최신(draft) 버전이 같은 asset을 같은 field로 참조 — 하나로 합쳐진다.
    draft_version = ContentVersion(
        content_id=content.id,
        detail_description="",
        created_at=published_version.created_at + timedelta(minutes=5),
    )
    db_session.add(draft_version)
    await db_session.flush()
    db_session.add(
        CharacterVersionDetail(
            content_version_id=draft_version.id,
            name="신버전이름",
            one_liner="",
            thumbnail_asset_id=asset.id,
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == [
        {
            "contentId": str(content.id),
            "contentType": "character",
            "contentTitle": "신버전이름",
            "field": "thumbnail",
        }
    ]
