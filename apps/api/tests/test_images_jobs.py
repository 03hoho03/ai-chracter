import asyncio
import json
import uuid

from api.core.config import settings
from api.core.redis import redis_client
from api.images.jobs import (
    ImageGenerationJob,
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


async def test_update_job_concurrent_calls_do_not_lose_updates() -> None:
    """`_generate_and_store_one`(LG-6 이후에도 세마포어 밖에 있다)는 `asyncio.gather`로
    같은 잡을 동시에 갱신한다 — WATCH/MULTI/EXEC 낙관적 락을 GET-then-SET으로 바꾸면 이
    동시성에서 갱신이 유실된다(docstring이 이미 실측을 적어뒀다). 오늘 코드가 그 락을 실제로
    쓰는지 고정한다(local-image-gen-goal-prompt.md LG-6 — 업로드/썸네일/Asset 생성은
    세마포어 밖이라 이 동시 갱신 경로는 로컬 전환 후에도 그대로 유효하다)."""
    owner_user_id = uuid.uuid4()
    job = await create_job(owner_user_id, requested_count=5)
    asset_ids = [uuid.uuid4() for _ in range(5)]

    await asyncio.gather(
        *[update_job(job.job_id, completed_increment=1, asset_id=asset_id) for asset_id in asset_ids]
    )

    fetched = await get_job(job.job_id, owner_user_id)
    assert fetched is not None
    assert fetched.completed_count == 5
    assert set(fetched.asset_ids) == set(asset_ids)
    assert len(fetched.asset_ids) == 5


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


def test_image_generation_job_without_blocked_fields_still_validates() -> None:
    """guard-techspec.md GT-4 / guard-progress.md I-1: 잡 TTL이 1시간이라 배포 직후
    최대 1시간 동안 `blocked_count`/`blocked_reason` 필드가 없는 옛 Redis 레코드가
    남아 있다. 기본값이 없으면 `model_validate_json`이 `ValidationError`로 터져 그
    잡의 폴링 엔드포인트(`GET /images/jobs/{id}`)가 500이 된다(I-1 실측 재현) — 이
    테스트가 그 기본값을 고정한다."""
    old_record = json.dumps(
        {
            "job_id": "abc123",
            "owner_user_id": str(uuid.uuid4()),
            "status": "succeeded",
            "requested_count": 1,
            "completed_count": 1,
            "asset_ids": [],
            "error": None,
        }
    )

    job = ImageGenerationJob.model_validate_json(old_record)

    assert job.blocked_count == 0
    assert job.blocked_reason is None


async def test_enqueue_generation_runs_handler_as_background_task() -> None:
    calls: list[str] = []
    done = asyncio.Event()

    async def handler(value: str) -> None:
        calls.append(value)
        done.set()

    await enqueue_generation(handler, "hello")
    await asyncio.wait_for(done.wait(), timeout=1)

    assert calls == ["hello"]
