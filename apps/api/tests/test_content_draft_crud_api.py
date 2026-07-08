import io
import uuid
from datetime import date, datetime, timezone

import boto3
import httpx
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus


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


async def _make_empty_character_draft(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(content_id=content.id, detail_description="")
    db_session.add(version)
    await db_session.flush()

    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="",
            one_liner="",
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    )
    await db_session.flush()
    return content


def _draft_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "아리아",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "intro": "안녕하세요",
        "exampleDialogues": [{"id": "d1", "userLine": "안녕", "characterLine": "반가워"}],
        "characterPrompt": "너는 아리아다.",
        "playguide": None,
        "situationalImages": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


async def test_create_content_draft_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/contents", json={"type": "character"})
    assert resp.status_code == 401


async def test_create_content_draft_creates_empty_character_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/contents", json={"type": "character"})
    assert resp.status_code == 201
    content_id = uuid.UUID(resp.json()["contentId"])

    content = await db_session.get(Content, content_id)
    assert content is not None
    assert content.type == ContentType.CHARACTER
    assert content.creator_user_id == user.id
    assert content.genre_id is None
    assert content.target is None
    assert content.hashtags == []
    assert content.visibility == ContentVisibility.PRIVATE
    assert content.moderation_status == ModerationStatus.NORMAL
    assert content.current_published_version_id is None

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content_id)
        )
    ).scalar_one()
    assert version.published_at is None
    assert version.version_number is None
    assert version.detail_description == ""

    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    assert detail.name == ""
    assert detail.one_liner == ""
    assert detail.thumbnail_asset_id is None
    assert detail.intro == ""
    assert detail.example_dialogues == []
    assert detail.character_prompt == ""
    assert detail.playguide is None


async def test_create_content_draft_rejects_story_type(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/contents", json={"type": "story"})
    assert resp.status_code == 422


async def test_get_content_draft_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/contents/{uuid.uuid4()}/draft")
    assert resp.status_code == 401


async def test_get_content_draft_returns_404_for_missing_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.get(f"/contents/{uuid.uuid4()}/draft")
    assert resp.status_code == 404


async def test_get_content_draft_returns_403_for_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.get(f"/contents/{content.id}/draft")
    assert resp.status_code == 403


async def test_get_content_draft_returns_404_for_story_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content = Content(
        creator_user_id=user.id,
        type=ContentType.STORY,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    version = ContentVersion(content_id=content.id, detail_description="")
    db_session.add(version)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.get(f"/contents/{content.id}/draft")
    assert resp.status_code == 404


async def test_get_content_draft_returns_newly_created_empty_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    create_resp = await db_client.post("/contents", json={"type": "character"})
    content_id = create_resp.json()["contentId"]

    resp = await db_client.get(f"/contents/{content_id}/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == content_id
    assert body["type"] == "character"
    assert body["name"] == ""
    assert body["oneLiner"] == ""
    assert body["thumbnailAssetId"] is None
    assert body["intro"] == ""
    assert body["exampleDialogues"] == []
    assert body["characterPrompt"] == ""
    assert body["playguide"] is None
    assert body["situationalImages"] == []
    assert body["description"] == ""
    assert body["genreId"] is None
    assert body["target"] is None
    assert body["hashtags"] == []
    assert body["visibility"] == "private"


async def test_patch_content_draft_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(f"/contents/{uuid.uuid4()}/draft", json=_draft_payload())
    assert resp.status_code == 401


async def test_patch_content_draft_returns_403_for_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.patch(f"/contents/{content.id}/draft", json=_draft_payload())
    assert resp.status_code == 403


async def test_patch_content_draft_updates_fields_without_validation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """AC: PATCH accepts the payload as-is, no min-length/required-ness checks."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(name="", characterPrompt=""),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == ""
    assert body["characterPrompt"] == ""
    assert body["exampleDialogues"] == [
        {"id": "d1", "userLine": "안녕", "characterLine": "반가워"}
    ]

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    assert detail.intro == "안녕하세요"
    assert detail.example_dialogues == [
        {"id": "d1", "userLine": "안녕", "characterLine": "반가워"}
    ]


async def test_patch_content_draft_updates_registration_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """registration-tab fields live on Content/ContentVersion, not character_version_details
    (shared across versions, not per-version snapshot data) — US-083 depends on these being
    settable so a draft can ever pass publish validation."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            description="상세 설명입니다",
            genreId=str(genre.id),
            target="female",
            hashtags=["힐링", "일상"],
            visibility="public",
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "상세 설명입니다"
    assert body["genreId"] == str(genre.id)
    assert body["target"] == "female"
    assert body["hashtags"] == ["힐링", "일상"]
    assert body["visibility"] == "public"

    await db_session.refresh(content)
    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    assert version.detail_description == "상세 설명입니다"
    assert content.genre_id == genre.id
    assert content.target == ContentTarget.FEMALE
    assert content.hashtags == ["힐링", "일상"]
    assert content.visibility == ContentVisibility.PUBLIC


async def test_patch_content_draft_upserts_inserts_updates_deletes_and_reorders_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    keep_id = str(uuid.uuid4())
    drop_id = str(uuid.uuid4())
    first_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            situationalImages=[
                {"id": keep_id, "triggerCondition": "첫 조건"},
                {"id": drop_id, "triggerCondition": "삭제될 조건"},
            ]
        ),
    )
    assert first_resp.status_code == 200
    assert [item["id"] for item in first_resp.json()["situationalImages"]] == [keep_id, drop_id]

    new_id = str(uuid.uuid4())
    second_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            situationalImages=[
                {"id": new_id, "triggerCondition": "새 조건"},
                {"id": keep_id, "triggerCondition": "수정된 조건"},
            ]
        ),
    )
    assert second_resp.status_code == 200
    body = second_resp.json()
    assert [item["id"] for item in body["situationalImages"]] == [new_id, keep_id]
    assert body["situationalImages"][1]["triggerCondition"] == "수정된 조건"

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    rows = (
        (
            await db_session.execute(
                sa.select(SituationalImage)
                .where(SituationalImage.content_version_id == version.id)
                .order_by(SituationalImage.order)
            )
        )
        .scalars()
        .all()
    )
    assert [str(row.entity_id) for row in rows] == [new_id, keep_id]
    assert [row.order for row in rows] == [0, 1]
    assert rows[1].trigger_condition == "수정된 조건"


async def test_patch_content_draft_preserves_image_asset_id_set_by_register_endpoint(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """The image fields are exclusively owned by `/assets/{id}/register-situational-image`
    (US-071) — this endpoint must not null them out when it updates trigger_condition/order
    for an entity_id that already has an image attached."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()

    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color=(200, 40, 40)).save(buffer, format="PNG")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=buffer.getvalue())
    await db_session.commit()
    await _login_as(db_client, user.id)

    entity_id = uuid.uuid4()
    register_resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(entity_id),
            "contentVersionId": str(version.id),
            "triggerCondition": "원래 조건",
            "order": 0,
        },
    )
    assert register_resp.status_code == 200
    blurred_asset_id = register_resp.json()["blurredAssetId"]

    patch_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            situationalImages=[{"id": str(entity_id), "triggerCondition": "수정된 조건"}]
        ),
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["situationalImages"] == [
        {"id": str(entity_id), "imageAssetId": str(asset.id), "triggerCondition": "수정된 조건"}
    ]

    row = await db_session.scalar(
        sa.select(SituationalImage).where(SituationalImage.entity_id == entity_id)
    )
    assert row is not None
    assert row.image_asset_id == asset.id
    assert str(row.blurred_asset_id) == blurred_asset_id
    assert row.trigger_condition == "수정된 조건"
