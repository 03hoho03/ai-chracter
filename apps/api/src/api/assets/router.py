import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.image_processing import BLURRED_CONTENT_TYPE, generate_blurred_image
from api.assets.schemas import (
    AssetCompleteResponse,
    GeneratedImageItem,
    PresignedUploadRequest,
    PresignedUploadResponse,
    RegisterSituationalImageRequest,
    SituationalImageResponse,
)
from api.core.s3 import (
    build_object_key,
    download_object,
    generate_presigned_get_url,
    generate_presigned_put_url,
    object_exists,
    upload_object,
)
from api.db.models.character import SituationalImage
from api.db.models.content import Content, ContentVersion
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/assets", tags=["assets"])
me_router = APIRouter(prefix="/me", tags=["assets"])


@router.post("/presigned-upload", status_code=status.HTTP_201_CREATED)
async def create_presigned_upload(
    payload: PresignedUploadRequest,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PresignedUploadResponse:
    asset_id = uuid.uuid4()
    storage_key = build_object_key(payload.purpose.value, asset_id, payload.content_type)
    upload_url, expires_at = await run_in_threadpool(
        generate_presigned_put_url, storage_key, payload.content_type
    )

    db.add(
        Asset(
            id=asset_id,
            owner_user_id=owner_user_id,
            storage_key=storage_key,
            kind=AssetKind.ORIGINAL,
            status=AssetStatus.PENDING,
        )
    )
    await db.commit()

    return PresignedUploadResponse(upload_url=upload_url, asset_id=asset_id, expires_at=expires_at)


@router.post("/{asset_id}/complete")
async def complete_asset_upload(
    asset_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> AssetCompleteResponse:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.owner_user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the asset owner")

    if not await run_in_threadpool(object_exists, asset.storage_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded object not found in storage yet",
        )

    asset.status = AssetStatus.READY
    await db.commit()

    return AssetCompleteResponse(asset_id=asset.id, status=asset.status)


@router.post("/{asset_id}/register-situational-image")
async def register_situational_image(
    asset_id: uuid.UUID,
    payload: RegisterSituationalImageRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> SituationalImageResponse:
    """techspec-backend-media.md §2. Downloads the original asset, synchronously
    generates a Gaussian-blurred variant (no queue — a single-image blur is
    sub-second), and upserts the situational_images row keyed by entity_id.
    """
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.owner_user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the asset owner")
    if asset.status != AssetStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Asset upload is not complete yet"
        )

    content_version = await db.get(ContentVersion, payload.content_version_id)
    if content_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content version not found")
    content = await db.get(Content, content_version.content_id)
    if content is None or content.creator_user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the content creator")

    original_bytes = await run_in_threadpool(download_object, asset.storage_key)
    blurred_bytes = await run_in_threadpool(generate_blurred_image, original_bytes)

    blurred_asset_id = uuid.uuid4()
    blurred_storage_key = build_object_key(
        "situational-image-blurred", blurred_asset_id, BLURRED_CONTENT_TYPE
    )
    await run_in_threadpool(upload_object, blurred_storage_key, blurred_bytes, BLURRED_CONTENT_TYPE)

    db.add(
        Asset(
            id=blurred_asset_id,
            owner_user_id=current_user_id,
            storage_key=blurred_storage_key,
            kind=AssetKind.BLURRED,
            status=AssetStatus.READY,
        )
    )

    situational_image = await db.scalar(
        select(SituationalImage).where(
            SituationalImage.content_version_id == payload.content_version_id,
            SituationalImage.entity_id == payload.entity_id,
        )
    )
    if situational_image is None:
        situational_image = SituationalImage(
            entity_id=payload.entity_id, content_version_id=payload.content_version_id
        )
        db.add(situational_image)

    situational_image.image_asset_id = asset_id
    situational_image.blurred_asset_id = blurred_asset_id
    situational_image.trigger_condition = payload.trigger_condition
    situational_image.order = payload.order

    await db.commit()

    return SituationalImageResponse(
        entity_id=payload.entity_id,
        image_asset_id=asset_id,
        blurred_asset_id=blurred_asset_id,
        trigger_condition=payload.trigger_condition,
        order=payload.order,
    )


@me_router.get("/generated-images")
async def list_generated_images(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[GeneratedImageItem]:
    """techspec-backend-media.md §3: "생성한 이미지에서 선택" 갤러리 조회."""
    assets = await db.scalars(
        select(Asset)
        .where(
            Asset.owner_user_id == current_user_id,
            Asset.kind == AssetKind.GENERATED,
            Asset.status == AssetStatus.READY,
        )
        .order_by(Asset.created_at.desc())
    )

    items: list[GeneratedImageItem] = []
    for asset in assets:
        image_url = await run_in_threadpool(generate_presigned_get_url, asset.storage_key)
        items.append(
            GeneratedImageItem(asset_id=asset.id, image_url=image_url, created_at=asset.created_at)
        )
    return items
