"""노벨 구매와 게시자 삭제가 실제로 겹칠 때(독립 커넥션).

같은 커넥션의 테스트로는 두 요청이 순서대로 돌아 경쟁이 드러나지 않는다. 그래서 상대 트랜잭션이 잠금을 쥔 채 커밋하지
않은 상태에서 라우트 함수를 띄우고, 그 라우트가 정말 막혀 있는 것(`_assert_blocked`)을 먼저 확인한 뒤 상대를 놓는다. 막힘
확인이 없으면 둘을 순서대로 돌려도 같은 최종 상태가 나와 아무것도 증명하지 못한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import User
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendAllocation, CloverSpendRefund, CloverSpendUsage
from api.db.models.content import Content
from api.db.models.moderation import Notification
from api.db.models.novel import Novel, NovelPublication, NovelPurchase
from api.novel_public.purchases import NovelChapterPurchaseResponse, purchase_chapter
from api.novelize import router as novelize_router
from api.novelize.deletion import delete_novels
from factories import PublicNovel, _assert_blocked, _make_public_novel, _make_user_with_clover_lot

_MARKER_DOMAIN = "novel-purchase-races.test"


@pytest_asyncio.fixture
async def independent_factory(db_engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """커밋되는 독립 커넥션 세션 팩토리. 여기서 쓴 행은 롤백되지 않으므로 표지 도메인 회원과 그 소설·원작·클로버 기록을
    끝에서 직접 지운다(FK 를 가리키는 쪽부터)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(user_ids)))).all()
            await cleanup.execute(
                delete(NovelPurchase).where(
                    or_(NovelPurchase.buyer_user_id.in_(user_ids), NovelPurchase.publisher_user_id.in_(user_ids))
                )
            )
            await cleanup.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
            ledger_ids = select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
            allocation_ids = select(CloverSpendAllocation.id).where(CloverSpendAllocation.spend_ledger_id.in_(ledger_ids))
            await cleanup.execute(delete(CloverSpendRefund).where(CloverSpendRefund.allocation_id.in_(allocation_ids)))
            await cleanup.execute(delete(CloverSpendAllocation).where(CloverSpendAllocation.spend_ledger_id.in_(ledger_ids)))
            await cleanup.execute(delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(ledger_ids)))
            await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
            await delete_novels(cleanup, novel_ids)
            await cleanup.execute(delete(Content).where(Content.creator_user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def _member(factory: async_sessionmaker[AsyncSession], balance: int = 100) -> uuid.UUID:
    async with factory() as s:
        user = await _make_user_with_clover_lot(s, email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}", clover_balance=balance)
        await s.commit()
    return user.id


async def _publish(factory: async_sessionmaker[AsyncSession], publisher_id: uuid.UUID) -> PublicNovel:
    """6화짜리 공개 소설(6화가 유료). 원작자에게도 표지 도메인을 달아 정리가 찾게 한다 — 소설이 지워지면 소설에서 원작을
    거슬러 찾을 수 없다."""
    async with factory() as s:
        novel = await _make_public_novel(s, publisher_id, batches=(6,))
        creator_id = select(Content.creator_user_id).where(Content.id == novel.content_id).scalar_subquery()
        await s.execute(update(User).where(User.id == creator_id).values(email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}"))
        await s.commit()
    return novel


async def _buy(
    db: AsyncSession, novel: PublicNovel, buyer_id: uuid.UUID
) -> NovelChapterPurchaseResponse:
    return await purchase_chapter(
        db, buyer_id=buyer_id, novel_id=novel.novel_id, chapter_id=novel.chapter_ids[5], expected_price=30
    )


async def _bought_and_committed(factory: async_sessionmaker[AsyncSession], novel: PublicNovel, buyer_id: uuid.UUID) -> None:
    async with factory() as s:
        assert (await _buy(s, novel, buyer_id)).charged == 30
        await s.commit()


async def _balance(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> int:
    async with factory() as s:
        balance = await s.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


async def test_the_same_buyer_buying_one_chapter_twice_at_once_pays_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """같은 사람의 구매 둘이 겹치면 뒤의 것은 구매자 행에서 기다렸다가 앞의 구매를 보고 차감 없이 소장 응답이다."""
    novel = await _publish(independent_factory, await _member(independent_factory))
    buyer = await _member(independent_factory)
    first = independent_factory()
    try:
        assert (await _buy(first, novel, buyer)).charged == 30

        async def second_purchase() -> NovelChapterPurchaseResponse:
            async with independent_factory() as s:
                response = await _buy(s, novel, buyer)
                await s.commit()
                return response

        second = asyncio.create_task(second_purchase())
        await _assert_blocked(second)
        await first.commit()
        result = await asyncio.wait_for(second, 10)
    finally:
        await first.close()

    assert result.charged == 0
    assert await _balance(independent_factory, buyer) == 70
