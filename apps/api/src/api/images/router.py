import asyncio
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.core.s3 import build_object_key, upload_object
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.session import get_session_factory
from api.images.jobs import ImageGenerationJobStatus, create_job, enqueue_generation, update_job
from api.images.schemas import AspectRatio, GenerateImageRequest, GenerateImageResponse
from api.llm.client import LLMClientError
from api.llm.dependencies import get_image_client
from api.llm.image import GeminiImageClient, ImageStylePreset
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/images", tags=["images"])


async def _generate_and_store_one(
    image_client: GeminiImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
    owner_user_id: uuid.UUID,
    prompt: str,
    style: ImageStylePreset,
    aspect_ratio: AspectRatio,
) -> bool:
    try:
        data, mime_type = await image_client.generate_image(prompt, style, aspect_ratio)
    except LLMClientError:
        return False

    asset_id = uuid.uuid4()
    storage_key = build_object_key("generated", asset_id, mime_type)
    await run_in_threadpool(upload_object, storage_key, data, mime_type)

    async with session_factory() as session:
        session.add(
            Asset(
                id=asset_id,
                owner_user_id=owner_user_id,
                storage_key=storage_key,
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
            )
        )
        await session.commit()

    await update_job(job_id, completed_increment=1, asset_id=asset_id)
    return True


async def _run_generation(
    job_id: str,
    owner_user_id: uuid.UUID,
    image_client: GeminiImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    prompt: str,
    style: ImageStylePreset,
    aspect_ratio: AspectRatio,
    count: int,
) -> None:
    await update_job(job_id, status=ImageGenerationJobStatus.RUNNING)
    results = await asyncio.gather(
        *[
            _generate_and_store_one(
                image_client, session_factory, job_id, owner_user_id, prompt, style, aspect_ratio
            )
            for _ in range(count)
        ]
    )
    if any(results):
        await update_job(job_id, status=ImageGenerationJobStatus.SUCCEEDED)
    else:
        await update_job(job_id, status=ImageGenerationJobStatus.FAILED, error="이미지 생성에 모두 실패했습니다")


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_images(
    payload: GenerateImageRequest,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    image_client: GeminiImageClient = Depends(get_image_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> GenerateImageResponse:
    job = await create_job(owner_user_id, payload.count)
    await enqueue_generation(
        _run_generation,
        job.job_id,
        owner_user_id,
        image_client,
        session_factory,
        payload.prompt,
        payload.style,
        payload.aspect_ratio,
        payload.count,
    )
    return GenerateImageResponse(job_id=job.job_id)
