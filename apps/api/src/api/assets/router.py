import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.schemas import AssetCompleteResponse, PresignedUploadRequest, PresignedUploadResponse
from api.core.s3 import build_object_key, generate_presigned_put_url, object_exists
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/assets", tags=["assets"])


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
