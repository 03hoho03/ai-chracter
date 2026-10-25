"""그림이 남지 않은 생성 요청 행 지우기의 요청 행 잠금 — 독립 커넥션이 있어야만 검증된다.

한 요청에서 나온 두 그림을 두 트랜잭션이 동시에 지우면, 잠금이 없을 때 각자 "상대 그림이 아직 있다"(상대의 삭제가 커밋 전이라
보이지 않는다)를 읽고 둘 다 요청 행을 남긴다 — 그림은 다 사라졌는데 프롬프트 원문이 남는다. 요청 행을 먼저 잠그면 뒤에 온
쪽이 앞쪽 커밋을 기다렸다가 새로 보고 지운다. `db_session` 하나 위에서는 두 세션이 같은 트랜잭션이라 잠금이 서로를 막지
않으므로, 여기서는 엔진에서 커넥션을 따로 받아 진짜로 다투게 한다.

🔴 여기서 쓴 행은 롤백되지 않는다 — 픽스처가 직접 지운다. 그 픽스처가 만든 행만 지운다.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.assets.router import delete_emptied_generation_requests
from api.db.models import User
from api.db.models.media import Asset, AssetKind, AssetStatus, ImageGenerationRequest
from api.images import router as images_router
from factories import _assert_blocked, _make_user


@dataclass(frozen=True)
class _CommittedPair:
    factory: async_sessionmaker[AsyncSession]
    request_id: uuid.UUID
    asset_ids: tuple[uuid.UUID, uuid.UUID]


@pytest_asyncio.fixture
async def committed_pair(db_engine: AsyncEngine) -> AsyncGenerator[_CommittedPair, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        user = _make_user()
        db.add(user)
        await db.flush()
        request = ImageGenerationRequest(
            owner_user_id=user.id,
            prompt="a cat",
            style="soft_portrait",
            aspect_ratio="1:1",
            model="v1",
            requested_count=2,
            status="succeeded",
            completed_count=2,
        )
        db.add(request)
        await db.flush()
        asset_ids = (uuid.uuid4(), uuid.uuid4())
        db.add_all(
            Asset(
                id=asset_id,
                owner_user_id=user.id,
                storage_key=f"assets/generated/{asset_id}.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
                request_id=request.id,
            )
            for asset_id in asset_ids
        )
        await db.commit()
    try:
        yield _CommittedPair(factory, request.id, asset_ids)
    finally:
        async with factory() as db:
            await db.execute(sa.delete(Asset).where(Asset.id.in_(asset_ids)))
            await db.execute(sa.delete(ImageGenerationRequest).where(ImageGenerationRequest.id == request.id))
            await db.execute(sa.delete(User).where(User.id == user.id))
            await db.commit()


async def _delete_asset_and_emptied_request(db: AsyncSession, asset_id: uuid.UUID, request_id: uuid.UUID) -> None:
    await db.execute(sa.delete(Asset).where(Asset.id == asset_id))
    await delete_emptied_generation_requests(db, {request_id})


async def test_concurrent_deletes_of_both_images_of_a_request_leave_no_request_row(
    committed_pair: _CommittedPair,
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 첫 트랜잭션이 한 그림을 지우고 요청 행을 본 채 커밋하지 않은 동안, 다른 그림을
    지우는 두 번째 트랜잭션의 요청 행 정리는 잠금에서 멈춰 있어야 하고(`_assert_blocked`), 첫 트랜잭션이 커밋한 뒤에는
    요청 행이 지워져 있어야 한다. 멈추지 않거나 행이 남으면 실패다."""
    factory = committed_pair.factory
    first_asset, second_asset = committed_pair.asset_ids
    async with factory() as first, factory() as second:
        await _delete_asset_and_emptied_request(first, first_asset, committed_pair.request_id)

        waiting = asyncio.create_task(
            _delete_asset_and_emptied_request(second, second_asset, committed_pair.request_id)
        )
        await _assert_blocked(waiting)

        await first.commit()
        await waiting
        await second.commit()

    async with factory() as db:
        remaining = await db.scalar(
            sa.select(ImageGenerationRequest.id).where(ImageGenerationRequest.id == committed_pair.request_id)
        )
    assert remaining is None


@dataclass(frozen=True)
class _CommittedPendingImage:
    factory: async_sessionmaker[AsyncSession]
    request_id: uuid.UUID
    asset_id: uuid.UUID


@pytest_asyncio.fixture
async def committed_pending_image(db_engine: AsyncEngine) -> AsyncGenerator[_CommittedPendingImage, None]:
    """아직 생성 중(`pending`)인 한 장짜리 요청과, 그 요청에서 이미 커밋된 그림 한 장."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        user = _make_user()
        db.add(user)
        await db.flush()
        request = ImageGenerationRequest(
            owner_user_id=user.id,
            prompt="a cat",
            style="soft_portrait",
            aspect_ratio="1:1",
            model="v1",
            requested_count=1,
            status="pending",
        )
        db.add(request)
        await db.flush()
        asset_id = uuid.uuid4()
        db.add(
            Asset(
                id=asset_id,
                owner_user_id=user.id,
                storage_key=f"assets/generated/{asset_id}.png",
                kind=AssetKind.GENERATED,
                status=AssetStatus.READY,
                request_id=request.id,
            )
        )
        await db.commit()
    try:
        yield _CommittedPendingImage(factory, request.id, asset_id)
    finally:
        async with factory() as db:
            await db.execute(sa.delete(Asset).where(Asset.id == asset_id))
            await db.execute(sa.delete(ImageGenerationRequest).where(ImageGenerationRequest.id == request.id))
            await db.execute(sa.delete(User).where(User.id == user.id))
            await db.commit()


async def _finish_as_succeeded(factory: async_sessionmaker[AsyncSession], request_id: uuid.UUID) -> None:
    await images_router._record_request_outcome(
        factory,
        request_id,
        status="succeeded",
        completed_count=1,
        blocked_count=0,
        input_error_count=0,
        blocked_reason=None,
        input_error=None,
        error=None,
    )


async def _request_row_exists(factory: async_sessionmaker[AsyncSession], request_id: uuid.UUID) -> bool:
    async with factory() as db:
        found = await db.scalar(sa.select(ImageGenerationRequest.id).where(ImageGenerationRequest.id == request_id))
    return found is not None


async def test_finishing_waits_for_a_gallery_delete_holding_the_request_row_then_removes_the_emptied_row(
    committed_pending_image: _CommittedPendingImage,
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 갤러리 삭제가 생성 중인 요청의 마지막 그림을 지우고 요청 행을 잠근 채 커밋하지
    않은 동안, 생성 종료 기록은 잠금에서 멈춰 있어야 하고(`_assert_blocked`), 갤러리 삭제가 커밋한 뒤 끝난 종료 기록은
    그림이 남지 않은 요청 행을 지워야 한다. 갤러리 쪽은 그때 행이 `pending` 이라 남기므로, 종료 쪽이 지우지 않으면 행이
    남는다."""
    factory = committed_pending_image.factory
    request_id = committed_pending_image.request_id
    async with factory() as gallery:
        await _delete_asset_and_emptied_request(gallery, committed_pending_image.asset_id, request_id)

        finishing = asyncio.create_task(_finish_as_succeeded(factory, request_id))
        await _assert_blocked(finishing)

        await gallery.commit()
        await finishing

    assert not await _request_row_exists(factory, request_id)


async def test_finishing_does_not_wait_on_an_uncommitted_image_delete_and_the_gallery_then_removes_the_row(
    committed_pending_image: _CommittedPendingImage,
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 갤러리 삭제가 그림 행만 지우고 아직 요청 행을 보지 않은 채 커밋하지 않았으면,
    생성 종료 기록은 그림 행 잠금에 막히지 않고 끝나며(그림이 아직 보이므로) 요청 행을 남긴다. 그 뒤 갤러리 삭제가 요청
    행을 보면 이미 `succeeded` 라 지운다. 종료 기록이 멈추거나, 마지막에 행이 남으면 실패다."""
    factory = committed_pending_image.factory
    request_id = committed_pending_image.request_id
    async with factory() as gallery:
        await gallery.execute(sa.delete(Asset).where(Asset.id == committed_pending_image.asset_id))

        await asyncio.wait_for(_finish_as_succeeded(factory, request_id), timeout=5)
        assert await _request_row_exists(factory, request_id)

        await delete_emptied_generation_requests(gallery, {request_id})
        await gallery.commit()

    assert not await _request_row_exists(factory, request_id)
