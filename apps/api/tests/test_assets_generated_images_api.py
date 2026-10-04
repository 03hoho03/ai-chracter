import asyncio
import uuid
from datetime import datetime, timedelta, timezone, UTC

import boto3
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.s3 import build_variant_keys, delete_object
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus, ImageGenerationRequest
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail
from factories import (
    _add_media_book_cell,
    _login_as,
    _make_user,
    _noting_open_transactions,
    _open_transaction_probe,
)


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

    now = datetime.now(UTC)
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
    for item, asset_id in zip(body, [newer_id, older_id], strict=True):
        assert item["imageUrl"].startswith("http")
        # 갤러리 그리드는 원본이 아니라 썸네일 변형을 서명한다.
        assert f"assets/generated/{asset_id}_thumb.webp" in item["imageUrl"]
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
        published_at=datetime.now(UTC) if published else None,
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
        published_at=datetime.now(UTC),
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


async def test_delete_unused_generated_image_removes_it_from_list_and_s3(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    await db_session.commit()
    asset_id, storage_key = asset.id, asset.storage_key
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=b"fake-image-bytes")
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{asset_id}")
    assert resp.status_code == 204

    list_resp = await db_client.get("/me/generated-images")
    assert list_resp.status_code == 200
    assert [item["assetId"] for item in list_resp.json()] == []

    listed = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=storage_key)
    assert listed["KeyCount"] == 0


async def test_delete_generated_image_removes_every_variant_from_s3(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """원본만 지우면 썸네일(`_thumb.webp`)과 표시용 변형(`_display.webp`)이 S3에 고아로 남는다 — 둘 다
    사용자가 만든 그림의 사본이다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    await db_session.commit()
    asset_id, storage_key = asset.id, asset.storage_key
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=b"fake-image-bytes")
    for variant_key in build_variant_keys(storage_key):
        s3.put_object(Bucket=settings.s3_bucket_name, Key=variant_key, Body=b"fake-variant")
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{asset_id}")
    assert resp.status_code == 204

    # storage_key 확장자 이전까지가 원본·변형 공통 접두사다(변형 키는 확장자를 `_thumb.webp`·
    # `_display.webp`로 바꿔 붙이므로) — 하나의 조회로 셋 다 사라졌는지 본다.
    common_prefix = storage_key.rsplit(".", 1)[0]
    listed = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=common_prefix)
    assert listed["KeyCount"] == 0


async def test_delete_generated_image_of_other_user_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    asset = await _make_generated_asset(db_session, owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.delete(f"/me/generated-images/{asset.id}")
    assert resp.status_code == 404


async def test_delete_non_generated_asset_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset_id = uuid.uuid4()
    db_session.add(
        Asset(
            id=asset_id,
            owner_user_id=user.id,
            storage_key=f"assets/profile-image/{asset_id}.png",
            kind=AssetKind.ORIGINAL,
            status=AssetStatus.READY,
        )
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{asset_id}")
    assert resp.status_code == 404


async def test_delete_missing_generated_image_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_delete_used_generated_image_is_409_with_usages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, _ = await _make_character_content(
        db_session, creator_user_id=user.id, name="사용중캐릭터", thumbnail_asset_id=asset.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{asset.id}")
    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "usages": [
            {
                "contentId": str(content.id),
                "contentType": "character",
                "contentTitle": "사용중캐릭터",
                "field": "thumbnail",
            }
        ]
    }

    # 삭제되지 않고 목록에 그대로 남아 있다.
    list_resp = await db_client.get("/me/generated-images")
    assert [item["assetId"] for item in list_resp.json()] == [str(asset.id)]


async def test_delete_generated_image_referenced_only_by_draft_is_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, _ = await _make_character_content(
        db_session,
        creator_user_id=user.id,
        name="초안참조",
        thumbnail_asset_id=asset.id,
        published=False,
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{asset.id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["usages"] == [
        {
            "contentId": str(content.id),
            "contentType": "character",
            "contentTitle": "초안참조",
            "field": "thumbnail",
        }
    ]


async def test_delete_generated_image_used_as_reference_clears_the_reference_on_request_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """참조로 쓰였다는 사실은 삭제를 막지 않는다 — 요청 행은 남고 참조 칸만 비워진다. 사용 중
    판정에 참조를 넣으면 한 번 참조로 쓴 이미지는 영영 못 지운다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    request = ImageGenerationRequest(
        owner_user_id=user.id,
        prompt="a cat",
        style="soft_portrait",
        aspect_ratio="1:1",
        model="v1",
        requested_count=1,
        status="blocked",
        blocked_count=1,
        blocked_reason="reference",
        reference_asset_id=asset.id,
    )
    db_session.add(request)
    await db_session.commit()
    asset_id = asset.id
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{asset_id}")

    assert resp.status_code == 204
    assert await db_session.get(Asset, asset_id) is None
    await db_session.refresh(request)
    assert request.reference_asset_id is None


@pytest.mark.parametrize("column", [pytest.param("image", id="image"), pytest.param("blurred", id="blurred")])
async def test_generated_image_used_by_media_book_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession, column: str
) -> None:
    """미디어 북 칸은 이미지와 블러본 두 칸 다 자산을 붙잡는다 — 어느 쪽이든 사용 중이다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    other = await _make_generated_asset(db_session, user.id)
    content, version = await _make_story_content(db_session, creator_user_id=user.id, name="스토리M")
    if column == "image":
        await _add_media_book_cell(db_session, version.id, asset.id, other.id)
    else:
        await _add_media_book_cell(db_session, version.id, other.id, asset.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    assert await _get_usages(db_client, asset.id) == [
        {
            "contentId": str(content.id),
            "contentType": "story",
            "contentTitle": "스토리M",
            "field": "mediaBook",
        }
    ]


async def test_delete_generated_image_conflicts_when_used_by_media_book_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안 칸만 쓰는 생성 이미지도 지우면 초안의 칸 FK 가 깨진다 — 발행본과 같이 409 다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    content, _ = await _make_story_content(db_session, creator_user_id=user.id, name="발행본 제목")
    draft = ContentVersion(content_id=content.id, detail_description="")
    db_session.add(draft)
    await db_session.flush()
    db_session.add(
        StoryVersionDetail(
            content_version_id=draft.id, name="초안 제목", one_liner="", prompt_template=StoryPromptTemplate.BASIC
        )
    )
    await db_session.flush()
    await _add_media_book_cell(db_session, draft.id, asset.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/me/generated-images/{asset.id}")

    assert resp.status_code == 409
    assert resp.json()["detail"]["usages"] == [
        {"contentId": str(content.id), "contentType": "story", "contentTitle": "초안 제목", "field": "mediaBook"}
    ]
    assert await db_session.get(Asset, asset.id) is not None


# ── 생성 이미지 삭제가 저장소 삭제를 기다리는 동안 DB 트랜잭션을 쥐지 않는다 ──────────────────────
#
# 저장소 삭제 셋(원본·변형 둘)을 기다리는 동안 사용처 조회가 연 트랜잭션이 열려 있으면 커넥션 하나를 쥔다. 그래서
# 조회를 커밋으로 닫고 저장소를 지운 뒤, 짧은 트랜잭션에서 사용처를 다시 보고 행을 지운다.


async def test_delete_generated_image_holds_no_transaction_while_deleting_from_storage(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    seen: list[tuple[str, int]] = []
    with _open_transaction_probe() as open_sessions:
        monkeypatch.setattr(
            "api.assets.router.delete_object", _noting_open_transactions(open_sessions, seen, "delete", delete_object)
        )
        resp = await db_client.delete(f"/me/generated-images/{asset.id}")

    assert resp.status_code == 204
    assert seen == [("delete", 0)] * 3
    assert await db_session.get(Asset, asset.id) is None


@pytest.mark.usefixtures("committing_request_session")
async def test_delete_generated_image_is_409_when_it_becomes_used_while_deleting_from_storage(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준: 저장소를 지우는 사이 다른 탭이 그 그림을 대표 이미지로 걸었으면 행을 지우지 않고 사용처와 함께
    409 로 답한다(행을 지우려다 외래 키 오류로 500 이 나면 실패다). 저장소 객체는 이미 지워졌다 — 행이 남아 다시
    지울 수 있다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_generated_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    loop = asyncio.get_running_loop()
    used: list[Content] = []

    async def use_as_thumbnail() -> None:
        content, _ = await _make_character_content(
            db_session, creator_user_id=user.id, name="그사이에건캐릭터", thumbnail_asset_id=asset.id
        )
        await db_session.commit()
        used.append(content)

    def delete_while_another_tab_uses_it(key: str) -> None:
        if not used:
            asyncio.run_coroutine_threadsafe(use_as_thumbnail(), loop).result(10)
        delete_object(key)

    monkeypatch.setattr("api.assets.router.delete_object", delete_while_another_tab_uses_it)
    resp = await db_client.delete(f"/me/generated-images/{asset.id}")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["usages"] == [
        {
            "contentId": str(used[0].id),
            "contentType": "character",
            "contentTitle": "그사이에건캐릭터",
            "field": "thumbnail",
        }
    ]
    assert await db_session.scalar(select(Asset.id).where(Asset.id == asset.id)) == asset.id
