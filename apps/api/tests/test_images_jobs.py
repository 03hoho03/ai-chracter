import asyncio
import uuid

from api.core.config import settings
from api.core.redis import redis_client
from api.images.jobs import (
    ImageGenerationJobStatus,
    create_job,
    enqueue_generation,
    get_job,
    update_job,
)


async def test_create_job_returns_queued_status_with_requested_count() -> None:
    owner_user_id = uuid.uuid4()

    job = await create_job(owner_user_id, requested_count=3)

    assert job.owner_user_id == owner_user_id
    assert job.status == ImageGenerationJobStatus.QUEUED
    assert job.requested_count == 3
    assert job.completed_count == 0
    assert job.asset_ids == []
    assert job.error is None


async def test_create_job_sets_ttl_of_one_hour() -> None:
    job = await create_job(uuid.uuid4(), requested_count=1)

    ttl = await redis_client.ttl(f"imggen:job:{job.job_id}")
    assert 0 < ttl <= settings.image_generation_job_ttl_seconds


async def test_get_job_round_trips_by_owner() -> None:
    owner_user_id = uuid.uuid4()
    job = await create_job(owner_user_id, requested_count=2)

    fetched = await get_job(job.job_id, owner_user_id)

    assert fetched is not None
    assert fetched.job_id == job.job_id


async def test_get_job_returns_none_for_wrong_owner() -> None:
    job = await create_job(uuid.uuid4(), requested_count=1)

    fetched = await get_job(job.job_id, uuid.uuid4())

    assert fetched is None


async def test_get_job_returns_none_for_nonexistent_job() -> None:
    fetched = await get_job(uuid.uuid4().hex, uuid.uuid4())

    assert fetched is None


async def test_update_job_increments_progress_and_appends_asset_id() -> None:
    owner_user_id = uuid.uuid4()
    job = await create_job(owner_user_id, requested_count=2)
    asset_id = uuid.uuid4()

    await update_job(job.job_id, status=ImageGenerationJobStatus.RUNNING)
    await update_job(job.job_id, completed_increment=1, asset_id=asset_id)

    fetched = await get_job(job.job_id, owner_user_id)
    assert fetched is not None
    assert fetched.status == ImageGenerationJobStatus.RUNNING
    assert fetched.completed_count == 1
    assert fetched.asset_ids == [asset_id]


async def test_update_job_sets_failed_status_and_error() -> None:
    owner_user_id = uuid.uuid4()
    job = await create_job(owner_user_id, requested_count=1)

    await update_job(job.job_id, status=ImageGenerationJobStatus.FAILED, error="quota exceeded")

    fetched = await get_job(job.job_id, owner_user_id)
    assert fetched is not None
    assert fetched.status == ImageGenerationJobStatus.FAILED
    assert fetched.error == "quota exceeded"


async def test_update_job_on_nonexistent_job_is_a_noop() -> None:
    await update_job(uuid.uuid4().hex, status=ImageGenerationJobStatus.FAILED)


async def test_enqueue_generation_runs_handler_as_background_task() -> None:
    calls: list[str] = []
    done = asyncio.Event()

    async def handler(value: str) -> None:
        calls.append(value)
        done.set()

    await enqueue_generation(handler, "hello")
    await asyncio.wait_for(done.wait(), timeout=1)

    assert calls == ["hello"]
