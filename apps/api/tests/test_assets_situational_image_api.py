import asyncio
import io
import json
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path

import boto3
import httpx
import pytest
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.assets import blur as blur_module
from api.core.s3 import build_variant_keys, download_object
from api.db.models.character import SituationalImage
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus
from factories import (
    _get_genre,
    _login_as,
    _make_user,
    _noting_open_transactions,
    _open_transaction_probe,
    _put_via_presigned_url,
)


async def _make_draft_version(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    content_type: ContentType = ContentType.CHARACTER,
) -> ContentVersion:
    genre = await _get_genre(db_session)
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
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


async def test_register_situational_image_creates_thumbnails_for_original_and_blur(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """Full upload flow: /complete creates the original's thumbnail and
    register-situational-image creates the blurred variant's thumbnail,
    so both READY assets satisfy the `_thumb.webp` invariant."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    presign_resp = await db_client.post(
        "/assets/presigned-upload",
        json={"contentType": "image/png", "purpose": "situational-image"},
    )
    asset_id = presign_resp.json()["assetId"]
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    _put_via_presigned_url(presign_resp.json()["uploadUrl"], _sample_png_bytes())
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 200

    resp = await db_client.post(
        f"/assets/{asset_id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "문을 열었을 때",
            "order": 0,
        },
    )
    assert resp.status_code == 200
    blurred_asset = await db_session.get(Asset, uuid.UUID(resp.json()["blurredAssetId"]))
    assert blurred_asset is not None

    for storage_key in (asset.storage_key, blurred_asset.storage_key):
        for variant_key in build_variant_keys(storage_key):
            variant_obj = s3.get_object(Bucket=settings.s3_bucket_name, Key=variant_key)
            with Image.open(io.BytesIO(variant_obj["Body"].read())) as variant:
                assert variant.format == "WEBP"


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


async def test_register_situational_image_rejects_published_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """A published version is what readers chat with and what publish moderation already
    approved — writing an image straight into it would skip that review."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    version.published_at = datetime.now(UTC)
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "조건",
            "order": 0,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Content version is not a draft"
    rows = (
        await db_session.scalars(
            sa.select(SituationalImage).where(SituationalImage.content_version_id == version.id)
        )
    ).all()
    assert rows == []


async def test_register_situational_image_rejects_story_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """Situational images belong to characters only; a story draft never reads this table,
    so a row hung off it would be an orphan nobody sees or cleans up."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(
        db_session, creator_user_id=user.id, content_type=ContentType.STORY
    )
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "조건",
            "order": 0,
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Situational images are only for character content"
    rows = (
        await db_session.scalars(
            sa.select(SituationalImage).where(SituationalImage.content_version_id == version.id)
        )
    ).all()
    assert rows == []


async def test_register_situational_image_records_blurred_asset_dimensions(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """블러본은 원본을 줄이지 않고 흐리기만 하므로 원본과 같은 너비·높이다 — 크기를 모르는 원본
    (너비·높이 NULL)이어도 블러본에는 채워진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    asset = await _make_ready_asset(db_session, user.id)
    buffer = io.BytesIO()
    Image.new("RGB", (30, 20), color=(200, 40, 40)).save(buffer, format="PNG")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=buffer.getvalue())
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={"entityId": str(uuid.uuid4()), "contentVersionId": str(version.id), "triggerCondition": "조건", "order": 0},
    )

    assert resp.status_code == 200
    blurred = await db_session.get(Asset, uuid.UUID(resp.json()["blurredAssetId"]))
    assert blurred is not None
    assert (blurred.width, blurred.height) == (30, 20)


async def test_register_situational_image_marks_content_as_having_unpublished_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """초안에 이미지를 등록하는 것도 발행본과 달라지는 변경이다 — 초안 저장(PATCH)처럼 작품에 '발행 안 한 변경'
    표시를 세워야 작가 화면이 발행을 권한다. 플래그는 컬럼 단위 select 로 DB 에서 읽는다(세션 캐시를 보지 않게)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    flag = sa.select(Content.has_unpublished_changes).where(Content.id == version.content_id)
    assert await db_session.scalar(flag) is False
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(version.id),
            "triggerCondition": "문을 열었을 때",
            "order": 0,
        },
    )

    assert resp.status_code == 200
    assert await db_session.scalar(flag) is True


# ── 등록이 블러본을 만드는 동안 DB 트랜잭션을 쥐지 않는다 ──────────────────────────────────────
#
# 등록은 원본 내려받기·블러·블러본과 변형 올리기 셋을 거친다(디코드는 프로세스 전역 한도를 기다릴 수 있다). 그동안
# 확인 조회가 연 트랜잭션이 열려 있으면 커넥션 하나를 쥔다. 그래서 확인을 커밋으로 닫고 블러본을 올린 뒤, 짧은
# 트랜잭션에서 작품 행을 잠그고 아직 초안인지 다시 보고 쓴다.


def _register_body(version: ContentVersion) -> dict[str, object]:
    return {
        "entityId": str(uuid.uuid4()),
        "contentVersionId": str(version.id),
        "triggerCondition": "조건",
        "order": 0,
    }


async def test_register_situational_image_holds_no_transaction_while_making_the_blur(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    seen: list[tuple[str, int]] = []
    with _open_transaction_probe() as open_sessions:
        for attr in ("download_object", "upload_object"):
            monkeypatch.setattr(
                blur_module, attr, _noting_open_transactions(open_sessions, seen, attr, getattr(blur_module, attr))
            )
        resp = await db_client.post(f"/assets/{asset.id}/register-situational-image", json=_register_body(version))

    assert resp.status_code == 200, resp.text
    assert [name for name, _ in seen] == ["download_object", "upload_object", "upload_object", "upload_object"]
    assert [(name, count) for name, count in seen if count != 0] == []


@pytest.mark.usefixtures("committing_request_session")
async def test_register_situational_image_is_refused_when_the_draft_is_published_meanwhile(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준: 블러본을 만드는 사이 그 초안이 발행됐으면(다른 창의 발행) 등록은 409 이고 발행본에 이미지 행이
    생기지 않아야 한다 — 생기면 심사를 거치지 않은 그림이 독자가 대화하는 버전에 들어간다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    loop = asyncio.get_running_loop()

    async def publish_elsewhere() -> None:
        await db_session.execute(
            sa.update(ContentVersion)
            .where(ContentVersion.id == version.id)
            .values(published_at=datetime.now(UTC), version_number=1)
        )
        await db_session.commit()

    def download_while_published_elsewhere(key: str) -> bytes:
        body = download_object(key)
        asyncio.run_coroutine_threadsafe(publish_elsewhere(), loop).result(10)
        return body

    monkeypatch.setattr(blur_module, "download_object", download_while_published_elsewhere)
    resp = await db_client.post(f"/assets/{asset.id}/register-situational-image", json=_register_body(version))

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Content version is not a draft"
    rows = (
        await db_session.scalars(sa.select(SituationalImage).where(SituationalImage.content_version_id == version.id))
    ).all()
    assert rows == []


# 상황 조건 길이 한도는 빌더 화면과 초안 저장이 함께 읽는 한도 표에 있다. 등록 엔드포인트도 조건을 DB 에 쓰므로 같은
# 한도를 지켜야 한다 — 숫자를 여기에 다시 적으면 표와 서버가 어긋나도 알 수 없어 테스트도 표에서 읽는다.
_TRIGGER_MAX_LENGTH: int = json.loads(
    (Path(__file__).parents[1] / "src" / "api" / "content" / "builder_limits.json").read_text(encoding="utf-8")
)["character"]["situationalImageTriggerMaxLength"]


async def test_register_situational_image_rejects_trigger_condition_over_the_builder_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={**_register_body(version), "triggerCondition": "가" * (_TRIGGER_MAX_LENGTH + 1)},
    )

    assert resp.status_code == 422, resp.text
    rows = (
        await db_session.scalars(sa.select(SituationalImage).where(SituationalImage.content_version_id == version.id))
    ).all()
    assert rows == []


async def test_register_situational_image_accepts_trigger_condition_at_the_builder_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_draft_version(db_session, creator_user_id=user.id)
    asset = await _make_ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    trigger = "가" * _TRIGGER_MAX_LENGTH

    resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={**_register_body(version), "triggerCondition": trigger},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["triggerCondition"] == trigger
