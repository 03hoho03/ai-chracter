import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.image_processing import (
    BLURRED_CONTENT_TYPE,
    THUMBNAIL_CONTENT_TYPE,
    generate_blurred_image,
    generate_thumbnail,
)
from api.assets.schemas import (
    UPLOAD_SIZE_LIMIT_BYTES,
    AssetCompleteResponse,
    AssetPurpose,
    GeneratedImageItem,
    GeneratedImageUsage,
    GeneratedImageUsageField,
    PresignedUploadRequest,
    PresignedUploadResponse,
    RegisterSituationalImageRequest,
    SituationalImageResponse,
)
from api.core.s3 import (
    build_object_key,
    build_thumbnail_key,
    delete_object,
    download_object,
    generate_presigned_get_url,
    generate_presigned_put_url,
    get_object_size,
    upload_object,
)
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import Content, ContentType, ContentVersion
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import StoryVersionDetail
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


def _upload_size_limit(storage_key: str) -> int | None:
    """Presigned-upload keys are `assets/{purpose}/{uuid}{ext}` (build_object_key);
    the Asset table has no purpose column, so the purpose is recovered from the key
    path. Keys outside the user-upload purposes (e.g. `assets/generated/...`) have
    no limit — the size check is a bypass safety net for presigned uploads only.
    """
    try:
        purpose = AssetPurpose(storage_key.split("/")[1])
    except ValueError:
        return None
    return UPLOAD_SIZE_LIMIT_BYTES[purpose]


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

    actual_bytes = await run_in_threadpool(get_object_size, asset.storage_key)
    if actual_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded object not found in storage yet",
        )

    max_bytes = _upload_size_limit(asset.storage_key)
    if max_bytes is not None and actual_bytes > max_bytes:
        # The FE resizes before upload, so oversize means the client bypassed it.
        # Delete S3 first so a failure leaves the row for a retry (delete_generated_image's
        # ordering), then drop the Asset row — never READY with an oversized original.
        await run_in_threadpool(delete_object, asset.storage_key)
        await db.delete(asset)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"maxBytes": max_bytes, "actualBytes": actual_bytes},
        )

    # Invariant: a READY image asset always has a `{key}_thumb.webp` variant, so
    # list endpoints can derive the key without an existence check. A failed
    # variant therefore fails the whole asset — never READY with only the original.
    original_bytes = await run_in_threadpool(download_object, asset.storage_key)
    try:
        thumbnail_bytes = await run_in_threadpool(generate_thumbnail, original_bytes)
    except (OSError, ValueError) as exc:
        # Pillow can't decode the upload — deterministic failure, so clean up
        # like the oversize path instead of leaving an unretryable PENDING row.
        await run_in_threadpool(delete_object, asset.storage_key)
        await db.delete(asset)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded object is not a decodable image",
        ) from exc
    await run_in_threadpool(
        upload_object,
        build_thumbnail_key(asset.storage_key),
        thumbnail_bytes,
        THUMBNAIL_CONTENT_TYPE,
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
    # The BLURRED asset goes READY below, so it needs its `_thumb.webp` variant too
    # (same invariant as complete_asset_upload — the original's thumbnail already
    # exists from that step). A failure here propagates before the commit, so the
    # registration fails as a whole and no READY asset is left without a thumbnail.
    blurred_thumbnail_bytes = await run_in_threadpool(generate_thumbnail, blurred_bytes)
    await run_in_threadpool(
        upload_object,
        build_thumbnail_key(blurred_storage_key),
        blurred_thumbnail_bytes,
        THUMBNAIL_CONTENT_TYPE,
    )

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


async def collect_asset_usages(
    db: AsyncSession, asset_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[GeneratedImageUsage]]:
    """어느 콘텐츠가 이 asset들을 참조 중인지 역조회한다 (US-001, tasks/prd-image-library.md).

    assets.id를 참조하는 4개 컬럼(character/story thumbnail_asset_id,
    situational_images.image/blurred_asset_id)을 컬럼별 일괄 select로 훑는다 —
    이미지마다 개별 조회하지 않는다(N+1 금지). 초안/발행 버전을 구분하지 않고 둘 다
    '사용 중'으로 보며, 같은 (content_id, field) 참조는 하나로 합친다(제목은 최신
    버전의 detail name이 남는다). US-002의 삭제 사전 판정도 이 함수를 재사용한다.
    """
    if not asset_ids:
        return {}

    merged: dict[uuid.UUID, dict[tuple[uuid.UUID, str], GeneratedImageUsage]] = {}

    def _add(
        asset_id: uuid.UUID,
        content_id: uuid.UUID,
        content_type: ContentType,
        content_title: str,
        field: GeneratedImageUsageField,
    ) -> None:
        merged.setdefault(asset_id, {})[(content_id, field)] = GeneratedImageUsage(
            content_id=content_id,
            content_type=content_type,
            content_title=content_title,
            field=field,
        )

    detail_models: tuple[type[CharacterVersionDetail] | type[StoryVersionDetail], ...] = (
        CharacterVersionDetail,
        StoryVersionDetail,
    )
    for detail_model in detail_models:
        thumbnail_rows = await db.execute(
            select(detail_model.thumbnail_asset_id, Content.id, Content.type, detail_model.name)
            .join(ContentVersion, ContentVersion.id == detail_model.content_version_id)
            .join(Content, Content.id == ContentVersion.content_id)
            .where(detail_model.thumbnail_asset_id.in_(asset_ids))
            .order_by(ContentVersion.created_at)
        )
        for thumbnail_asset_id, content_id, content_type, name in thumbnail_rows:
            _add(thumbnail_asset_id, content_id, content_type, name, "thumbnail")

    # 상황별 이미지는 캐릭터 전용이라 제목은 소속 버전의 character_version_details.name이다.
    requested_ids = set(asset_ids)
    situational_rows = await db.execute(
        select(
            SituationalImage.image_asset_id,
            SituationalImage.blurred_asset_id,
            Content.id,
            Content.type,
            CharacterVersionDetail.name,
        )
        .join(ContentVersion, ContentVersion.id == SituationalImage.content_version_id)
        .join(
            CharacterVersionDetail,
            CharacterVersionDetail.content_version_id == SituationalImage.content_version_id,
        )
        .join(Content, Content.id == ContentVersion.content_id)
        .where(
            or_(
                SituationalImage.image_asset_id.in_(asset_ids),
                SituationalImage.blurred_asset_id.in_(asset_ids),
            )
        )
        .order_by(ContentVersion.created_at)
    )
    for image_asset_id, blurred_asset_id, content_id, content_type, name in situational_rows:
        for referenced_id in (image_asset_id, blurred_asset_id):
            if referenced_id in requested_ids:
                _add(referenced_id, content_id, content_type, name, "situationalImage")

    return {asset_id: list(entries.values()) for asset_id, entries in merged.items()}


@me_router.get("/generated-images")
async def list_generated_images(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[GeneratedImageItem]:
    """techspec-backend-media.md §3: "생성한 이미지에서 선택" 갤러리 조회."""
    assets = list(
        await db.scalars(
            select(Asset)
            .where(
                Asset.owner_user_id == current_user_id,
                Asset.kind == AssetKind.GENERATED,
                Asset.status == AssetStatus.READY,
            )
            .order_by(Asset.created_at.desc())
        )
    )
    usages_by_asset = await collect_asset_usages(db, [asset.id for asset in assets])

    items: list[GeneratedImageItem] = []
    for asset in assets:
        image_url = await run_in_threadpool(generate_presigned_get_url, asset.storage_key)
        items.append(
            GeneratedImageItem(
                asset_id=asset.id,
                image_url=image_url,
                created_at=asset.created_at,
                usages=usages_by_asset.get(asset.id, []),
            )
        )
    return items


@me_router.delete("/generated-images/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated_image(
    asset_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """US-002 (tasks/prd-image-library.md): 생성 이미지 삭제.

    존재하지 않음/타인 소유/GENERATED 아님을 전부 404 하나로 답한다 — 남의 asset
    존재 여부를 노출하지 않기 위함. 사용 중이면 409에 사용처 목록을 담아
    발행·초안 참조가 깨지는 삭제를 구조적으로 막는다.
    """
    asset = await db.get(Asset, asset_id)
    if (
        asset is None
        or asset.owner_user_id != current_user_id
        or asset.kind != AssetKind.GENERATED
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    usages = (await collect_asset_usages(db, [asset_id])).get(asset_id, [])
    if usages:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "usages": [usage.model_dump(mode="json", by_alias=True) for usage in usages]
            },
        )

    # S3를 먼저 지운다 — 실패하면 DB 행이 남아 재시도가 가능하다(고아 레코드 대신
    # 고아 파일을 피한다).
    await run_in_threadpool(delete_object, asset.storage_key)
    await db.delete(asset)
    await db.commit()
