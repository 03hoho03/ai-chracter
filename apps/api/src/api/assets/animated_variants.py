"""움직이는 대표 이미지의 움직이는 변형을 업로드 완료 응답 뒤에 만든다.

업로드 완료는 크롭한 첫 프레임으로 정지 변형만 만들고 바로 답한다 — 모든 프레임을 크롭·인코딩하는 일은 GIF 하나에
수 초가 걸려(로컬 측정 0.5~1.8초, 운영 VM 은 더 느리다) 업로드한 사람을 그만큼 기다리게 하고 워커를 잡는다. 그래서
`BackgroundTasks` 로 넘기고, 다 올린 뒤에만 `animated_variants_ready` 를 켠다. 그 전·실패 시에는 카드·상세가 정지 변형을
받는다(업로드 자체는 이미 끝났다). 프로세스가 그 사이 내려가면(배포) 이 자산은 정지 변형으로 남는다.
"""

import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.assets.image_processing import (
    THUMBNAIL_CONTENT_TYPE,
    ImageCrop,
    generate_animated_variants,
    run_image_work,
)
from api.core.s3 import delete_object, upload_object
from api.db.models.media import Asset, AssetStatus

logger = logging.getLogger(__name__)


async def build_animated_variants(
    session_factory: async_sessionmaker[AsyncSession],
    asset_id: uuid.UUID,
    storage_key: str,
    original_bytes: bytes,
    crop: ImageCrop | None,
) -> None:
    """움직이는 변형을 만들어 올리고 자산을 준비됨으로 표시한다. 실패는 경고 로그만 남기고 삼킨다 — 응답은 이미 나갔고,
    정지 변형이 그대로 쓰인다. 올리는 사이 자산이 지워졌으면(READY 가 아니면) 올린 변형을 치운다 — 지우는 쪽은 이 키들을
    이미 지운 뒤라 남겨 두면 지운 그림의 사본이 저장소에 남는다."""
    try:
        variants = await run_image_work(generate_animated_variants, storage_key, original_bytes, crop)
        for key, data in variants:
            await run_in_threadpool(upload_object, key, data, THUMBNAIL_CONTENT_TYPE)
    except (BotoCoreError, ClientError, OSError, ValueError) as exc:
        logger.warning("animated variants failed for asset %s: %s", asset_id, exc)
        return
    if not variants:
        return

    async with session_factory() as session:
        marked = await session.scalar(
            update(Asset)
            .where(Asset.id == asset_id, Asset.status == AssetStatus.READY)
            .values(animated_variants_ready=True)
            .returning(Asset.id)
        )
        await session.commit()
    if marked is None:
        for key, _ in variants:
            await run_in_threadpool(delete_object, key)
