"""잠긴 그림 대신 보여 줄 블러본 자산 만들기 — 캐릭터 상황별 이미지 등록과 스토리 발행이 함께 쓴다."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.image_processing import (
    BLURRED_CONTENT_TYPE,
    THUMBNAIL_CONTENT_TYPE,
    generate_blurred_image,
    generate_variants,
    read_image_size,
)
from api.core.s3 import build_object_key, download_object, upload_object
from api.db.models.media import Asset, AssetKind, AssetStatus


@dataclass(frozen=True)
class BlurredUpload:
    """저장소에 올린 블러본 — 자산 행으로 만들기 전의 값."""

    asset_id: uuid.UUID
    storage_key: str
    width: int
    height: int


async def upload_blurred_copy(source_storage_key: str) -> BlurredUpload:
    """원본을 내려받아 블러본 PNG 와 그 변형(`_thumb.webp`·`_display.webp`)을 올린다. 세션을 건드리지 않아 여러 장을 동시에 돌릴 수
    있다 — 자산 행은 `blurred_asset_row` 로 따로 만든다."""
    original_bytes = await run_in_threadpool(download_object, source_storage_key)
    blurred_bytes = await run_in_threadpool(generate_blurred_image, original_bytes)

    blurred_asset_id = uuid.uuid4()
    blurred_storage_key = build_object_key("situational-image-blurred", blurred_asset_id, BLURRED_CONTENT_TYPE)
    await run_in_threadpool(upload_object, blurred_storage_key, blurred_bytes, BLURRED_CONTENT_TYPE)
    # READY 자산은 늘 변형 전부를 함께 가진다(응답이 존재 확인 없이 키를 만든다). 여기서 실패하면 행을
    # 만들기 전에 예외가 나가 변형 없는 READY 자산이 남지 않는다.
    blurred_variants = await run_in_threadpool(generate_variants, blurred_storage_key, blurred_bytes)
    # 원본 행의 크기를 베끼지 않고 블러 바이트에서 잰다 — 원본이 크기를 채우기 전 자산이면 그 값이 비어 있다.
    blurred_width, blurred_height = await run_in_threadpool(read_image_size, blurred_bytes)
    for variant_key, variant_bytes in blurred_variants:
        await run_in_threadpool(upload_object, variant_key, variant_bytes, THUMBNAIL_CONTENT_TYPE)
    return BlurredUpload(
        asset_id=blurred_asset_id, storage_key=blurred_storage_key, width=blurred_width, height=blurred_height
    )


def blurred_asset_row(upload: BlurredUpload, *, owner_user_id: uuid.UUID) -> Asset:
    return Asset(
        id=upload.asset_id,
        owner_user_id=owner_user_id,
        storage_key=upload.storage_key,
        kind=AssetKind.BLURRED,
        status=AssetStatus.READY,
        width=upload.width,
        height=upload.height,
    )


async def create_blurred_asset(db: AsyncSession, *, source_storage_key: str, owner_user_id: uuid.UUID) -> Asset:
    """블러본을 올리고(`upload_blurred_copy`) READY 블러 자산 행을 세션에 더한다(flush·commit 은 호출자 몫 — 이
    행을 가리키는 행보다 먼저 flush 해야 FK 가 맞는다).

    S3 에 올린 뒤 호출자의 트랜잭션이 실패하면 두 객체는 가리키는 행 없이 남는다."""
    asset = blurred_asset_row(await upload_blurred_copy(source_storage_key), owner_user_id=owner_user_id)
    db.add(asset)
    return asset
