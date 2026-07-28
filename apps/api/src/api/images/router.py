import asyncio
import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.core.s3 import build_object_key, generate_presigned_get_url, upload_object
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.session import get_db_session, get_session_factory
from api.images.jobs import ImageGenerationJobStatus, create_job, enqueue_generation, get_job, update_job
from api.images.models import IMAGE_MODELS, IMAGE_MODELS_BY_ID, AspectRatio, ImageModelId
from api.images.schemas import (
    GenerateImageRequest,
    GenerateImageResponse,
    ImageJobImageItem,
    ImageJobStatusResponse,
    ImageModelItem,
)
from api.llm.client import LLMClientError
from api.llm.dependencies import get_image_client
from api.llm.image import ImageClient, ImageStylePreset
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/images", tags=["images"])


async def _generate_and_store_one(
    image_client: ImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
    owner_user_id: uuid.UUID,
    prompt: str,
    style: ImageStylePreset,
    aspect_ratio: AspectRatio,
) -> bool:
    try:
        data, mime_type = await image_client.generate_image(prompt, style, aspect_ratio)
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
    except LLMClientError:
        return False
    except Exception as exc:  # noqa: BLE001
        # 생성/업로드/저장 중 예기치 못한 오류가 백그라운드 태스크를 조용히 죽여 잡이 running에
        # 영원히 멈추는 것을 방지한다(uvicorn이 root logger 핸들러를 안 붙여서 print로 남긴다).
        print(f"[imggen] job={job_id} unexpected generation error: {type(exc).__name__}: {exc}", flush=True)
        return False


async def _run_generation(
    job_id: str,
    owner_user_id: uuid.UUID,
    image_client: ImageClient,
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


@router.get("/models")
async def list_image_models(
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[ImageModelItem]:
    """생성에 쓸 수 있는 모델 + 각 모델이 지원하는 종횡비. FE가 모델 선택 시 미지원
    종횡비를 비활성화하는 데 쓴다."""
    return [
        ImageModelItem(
            id=spec.id,
            name=spec.name,
            supported_aspect_ratios=list(spec.supported_aspect_ratios),
        )
        for spec in IMAGE_MODELS
    ]


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_images(
    payload: GenerateImageRequest,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    image_client_factory: Callable[[ImageModelId], ImageClient] = Depends(get_image_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> GenerateImageResponse:
    spec = IMAGE_MODELS_BY_ID[payload.model]
    if payload.aspect_ratio not in spec.supported_aspect_ratios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{spec.name}' does not support aspect ratio '{payload.aspect_ratio}'",
        )
    image_client = image_client_factory(payload.model)
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


@router.get("/jobs/{job_id}")
async def get_image_job(
    job_id: str,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ImageJobStatusResponse:
    job = await get_job(job_id, owner_user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    images: list[ImageJobImageItem] = []
    for asset_id in job.asset_ids:
        asset = await db.get(Asset, asset_id)
        if asset is None:
            continue
        image_url = await run_in_threadpool(generate_presigned_get_url, asset.storage_key)
        images.append(ImageJobImageItem(asset_id=asset_id, image_url=image_url))

    return ImageJobStatusResponse(
        status=job.status,
        requested_count=job.requested_count,
        completed_count=job.completed_count,
        images=images,
        error=job.error,
    )
