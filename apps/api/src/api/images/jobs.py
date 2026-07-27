import asyncio
import enum
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import BaseModel, Field
from redis.exceptions import WatchError

from api.core.config import settings
from api.core.redis import redis_client


class ImageGenerationJobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ImageGenerationJob(BaseModel):
    """Redis에 그대로 직렬화되는 생성 잡 레코드 (tasks/prd-image-generation.md §3/US-003)."""

    job_id: str
    owner_user_id: uuid.UUID
    status: ImageGenerationJobStatus
    requested_count: int
    completed_count: int = 0
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    error: str | None = None


def _job_key(job_id: str) -> str:
    return f"imggen:job:{job_id}"


async def _save_job(job: ImageGenerationJob) -> None:
    await redis_client.set(
        _job_key(job.job_id), job.model_dump_json(), ex=settings.image_generation_job_ttl_seconds
    )


async def create_job(owner_user_id: uuid.UUID, requested_count: int) -> ImageGenerationJob:
    job = ImageGenerationJob(
        job_id=uuid.uuid4().hex,
        owner_user_id=owner_user_id,
        status=ImageGenerationJobStatus.QUEUED,
        requested_count=requested_count,
    )
    await _save_job(job)
    return job


async def get_job(job_id: str, owner_user_id: uuid.UUID) -> ImageGenerationJob | None:
    """Returns None if the job doesn't exist, has expired, or isn't owned by
    `owner_user_id` — callers (US-005) surface all three cases as 404."""
    raw = await redis_client.get(_job_key(job_id))
    if raw is None:
        return None
    job = ImageGenerationJob.model_validate_json(raw)
    if job.owner_user_id != owner_user_id:
        return None
    return job


async def update_job(
    job_id: str,
    *,
    status: ImageGenerationJobStatus | None = None,
    completed_increment: int = 0,
    asset_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    """Progress-update helper: bumps `completed_count`, appends a succeeded
    `asset_id`, and/or sets `status`/`error` (e.g. queued->running, or the final
    succeeded/failed transition once generation finishes).

    Uses Redis WATCH/MULTI/EXEC (optimistic locking, retried on conflict)
    instead of a plain GET-then-SET: US-004's `asyncio.gather`'d generation
    calls each call this concurrently for the same job, and a bare
    GET-then-SET loses updates under that concurrency (confirmed empirically —
    `completed_count`/`asset_ids` under-counted with 2 concurrent callers)."""
    key = _job_key(job_id)
    async with redis_client.pipeline() as pipe:
        while True:
            try:
                await pipe.watch(key)
                raw = await pipe.get(key)
                if raw is None:
                    await pipe.unwatch()  # type: ignore[no-untyped-call]
                    return
                job = ImageGenerationJob.model_validate_json(raw)
                if status is not None:
                    job.status = status
                if completed_increment:
                    job.completed_count += completed_increment
                if asset_id is not None:
                    job.asset_ids.append(asset_id)
                if error is not None:
                    job.error = error
                pipe.multi()  # type: ignore[no-untyped-call]
                pipe.set(key, job.model_dump_json(), ex=settings.image_generation_job_ttl_seconds)
                await pipe.execute()
                return
            except WatchError:
                continue


_background_tasks: set[asyncio.Task[None]] = set()


async def enqueue_generation(handler: Callable[..., Coroutine[Any, Any, None]], *args: Any) -> None:
    """생성 잡 실행 인터페이스 (tasks/prd-image-generation.md §8).

    인프로세스 asyncio 구현: `handler(*args)`를 백그라운드 태스크로 즉시 실행하고
    반환한다. 호출부(US-004의 POST /images/generate)는 이 함수만 호출하면 되므로,
    내구성이 필요해지면 이 함수 본문만 arq `enqueue_job` 호출로 교체하면 된다(호출
    시그니처는 유지).
    """
    task: asyncio.Task[None] = asyncio.create_task(handler(*args))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
