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
from api.db.models.character import SituationalImage
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


async def _make_draft_version(db_session: AsyncSession, *, creator_user_id: uuid.UUID) -> ContentVersion:
    genre = await _get_genre(db_session)
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(content_id=content.id, detail_description="설명")
    db_session.add(version)
    await db_session.flush()
    return version


def _sample_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color=(200, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _make_ready_asset(db_session: AsyncSession, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()

    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=_sample_png_bytes())
    return asset


async def test_register_situational_image_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        f"/assets/{uuid.uuid4()}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(uuid.uuid4()),
            "triggerCondition": "문을 열었을 때",
            "order": 0,
        },
    )
    assert resp.status_code == 401


async def test_register_situational_image_generates_blur_and_upserts_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    entity_id = uuid.uuid4()
    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(entity_id),
            "contentVersionId": str(version.id),
            "triggerCondition": "문을 열었을 때",
            "order": 0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entityId"] == str(entity_id)
    assert body["imageAssetId"] == str(asset.id)
    assert body["triggerCondition"] == "문을 열었을 때"
    assert body["order"] == 0
    assert set(body.keys()) == {"entityId", "imageAssetId", "blurredAssetId", "triggerCondition", "order"}

    blurred_asset_id = uuid.UUID(body["blurredAssetId"])
    blurred_asset = await db_session.get(Asset, blurred_asset_id)
    assert blurred_asset is not None
    assert blurred_asset.owner_user_id == user.id
    assert blurred_asset.kind == AssetKind.BLURRED
    assert blurred_asset.status == AssetStatus.READY

    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    blurred_object = s3.get_object(Bucket=settings.s3_bucket_name, Key=blurred_asset.storage_key)
    blurred_bytes = blurred_object["Body"].read()
    assert blurred_bytes != _sample_png_bytes()
    assert Image.open(io.BytesIO(blurred_bytes)).size == (16, 16)

    situational_image = await db_session.scalar(
        sa.select(SituationalImage).where(SituationalImage.entity_id == entity_id)
    )
    assert situational_image is not None
    assert situational_image.content_version_id == version.id
    assert situational_image.image_asset_id == asset.id
    assert situational_image.blurred_asset_id == blurred_asset_id
    assert situational_image.trigger_condition == "문을 열었을 때"
    assert situational_image.order == 0


async def test_register_situational_image_upserts_by_entity_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    first_asset = await _make_ready_asset(db_session, user.id)
    second_asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    entity_id = uuid.uuid4()
    first_resp = await db_client.post(
        f"/assets/{first_asset.id}/register-situational-image",
        json={
            "entityId": str(entity_id),
            "contentVersionId": str(version.id),
            "triggerCondition": "처음 조건",
            "order": 0,
        },
    )
    assert first_resp.status_code == 200

    second_resp = await db_client.post(
        f"/assets/{second_asset.id}/register-situational-image",
        json={
            "entityId": str(entity_id),
            "contentVersionId": str(version.id),
            "triggerCondition": "수정된 조건",
            "order": 2,
        },
    )
    assert second_resp.status_code == 200
    assert second_resp.json()["imageAssetId"] == str(second_asset.id)

    rows = (
        (await db_session.execute(sa.select(SituationalImage).where(SituationalImage.entity_id == entity_id)))
        .scalars()
        .all()
    )
    [row] = rows
    assert row.image_asset_id == second_asset.id
    assert row.trigger_condition == "수정된 조건"
    assert row.order == 2


async def test_register_situational_image_rejects_non_owner_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=other.id)
    asset = await _make_ready_asset(db_session, owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "조건",
            "order": 0,
        },
    )
    assert resp.status_code == 403


async def test_register_situational_image_rejects_asset_not_ready(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    pending_asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.PENDING,
    )
    db_session.add(pending_asset)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{pending_asset.id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "조건",
            "order": 0,
        },
    )
    assert resp.status_code == 409


async def test_register_situational_image_rejects_unknown_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{uuid.uuid4()}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "조건",
            "order": 0,
        },
    )
    assert resp.status_code == 404


async def test_register_situational_image_rejects_unknown_content_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(uuid.uuid4()),
            "triggerCondition": "조건",
            "order": 0,
        },
    )
    assert resp.status_code == 404


async def test_register_situational_image_rejects_non_creator_content_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    creator = _make_user()
    other = _make_user()
    db_session.add_all([creator, other])
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=creator.id)
    asset = await _make_ready_asset(db_session, other.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "조건",
            "order": 0,
        },
    )
    assert resp.status_code == 403
