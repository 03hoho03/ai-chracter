"""노벨 구매와 게시자 삭제, 좋아요가 실제로 겹칠 때(독립 커넥션).

같은 커넥션의 테스트로는 두 요청이 순서대로 돌아 경쟁이 드러나지 않는다. 그래서 상대 트랜잭션이 잠금을 쥔 채 커밋하지
않은 상태에서 라우트 함수를 띄우고, 그 라우트가 정말 막혀 있는 것(`_assert_blocked`)을 먼저 확인한 뒤 상대를 놓는다. 막힘
확인이 없으면 둘을 순서대로 돌려도 같은 최종 상태가 나와 아무것도 증명하지 못한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import User
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendAllocation, CloverSpendRefund, CloverSpendUsage
from api.db.models.content import Content
from api.db.models.moderation import Notification
from api.db.models.novel import Novel, NovelLike, NovelPublication, NovelPurchase
from api.novel_public.purchases import NovelChapterPurchaseResponse, purchase_chapter
from api.novel_public.reading import like_webnovel
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


def _delete_in_own_session(factory: async_sessionmaker[AsyncSession], novel_id: uuid.UUID) -> "asyncio.Task[object]":
    """소설 삭제 라우트를 자기 세션으로 띄운다. 거절(`HTTPException`)은 결과로 돌려주고 성공은 None 이다 — 교착 오류 같은
    500 감은 그대로 터져 테스트를 실패시킨다."""

    async def run() -> object:
        async with factory() as s:
            novel = await s.get_one(Novel, novel_id)
            try:
                await novelize_router.delete_novel(novel=novel, db=s)
            except HTTPException as exc:
                return exc
            return None

    return asyncio.create_task(run())


async def _balance(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> int:
    async with factory() as s:
        balance = await s.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


@dataclass(frozen=True)
class _CrossBuyers:
    first: PublicNovel
    second: PublicNovel


async def _publishers_who_bought_each_other(factory: async_sessionmaker[AsyncSession]) -> _CrossBuyers:
    first = await _publish(factory, await _member(factory))
    second = await _publish(factory, await _member(factory))
    await _bought_and_committed(factory, second, first.publisher_id)
    await _bought_and_committed(factory, first, second.publisher_id)
    return _CrossBuyers(first, second)


async def test_two_publishers_who_bought_each_others_chapter_can_delete_at_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """서로의 6화를 산 두 게시자가 동시에 소설을 지운다. 게시자 행을 먼저 쥐고 구매자(상대) 행을 나중에 잡으면, 둘이 각자
    자기 행을 쥔 채 상대를 기다려 교착한다. 두 공개 행을 붙든 트랜잭션으로 두 삭제를 같은 지점에 세워 그 겹침을 만든다 —
    관련 회원을 id 순으로 먼저 잡으면 한쪽이 다른 쪽 뒤에 줄을 설 뿐 둘 다 끝나고, 둘 다 환급받는다."""
    pair = await _publishers_who_bought_each_other(independent_factory)
    holder = independent_factory()
    try:
        await holder.execute(
            select(NovelPublication.novel_id)
            .where(NovelPublication.novel_id.in_([pair.first.novel_id, pair.second.novel_id]))
            .with_for_update(read=True)
        )
        first = _delete_in_own_session(independent_factory, pair.first.novel_id)
        second = _delete_in_own_session(independent_factory, pair.second.novel_id)
        await _assert_blocked(first)
        await _assert_blocked(second)
        await holder.rollback()
        results = await asyncio.wait_for(asyncio.gather(first, second), 10)
    finally:
        await holder.close()

    assert list(results) == [None, None]
    assert await _balance(independent_factory, pair.first.publisher_id) == 100
    assert await _balance(independent_factory, pair.second.publisher_id) == 100


async def test_a_delete_that_waited_for_a_new_purchase_refuses_and_the_retry_refunds_it(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """삭제가 구매자를 고른 뒤 아직 커밋되지 않은 구매가 게시자 행을 쥐고 있다. 삭제는 그 구매를 기다렸다가 잠그지 않은 새
    구매자를 보고 409 로 아무것도 지우지 않는다(환급 없이 지우면 그 구매가 버려진다). 다시 지우면 새 구매자까지 환급한다."""
    novel = await _publish(independent_factory, await _member(independent_factory))
    buyer = await _member(independent_factory)
    purchase = independent_factory()
    try:
        await _buy(purchase, novel, buyer)
        deleting = _delete_in_own_session(independent_factory, novel.novel_id)
        await _assert_blocked(deleting)
        await purchase.commit()
        refused = await asyncio.wait_for(deleting, 10)
    finally:
        await purchase.close()

    assert isinstance(refused, HTTPException)
    detail: object = refused.detail  # 실제로는 dict 를 싣는다(선언은 str)
    assert (refused.status_code, detail) == (409, {"code": "NOVEL_DELETE_CONFLICT"})
    assert await _balance(independent_factory, buyer) == 70
    assert await _delete_in_own_session(independent_factory, novel.novel_id) is None
    assert await _balance(independent_factory, buyer) == 100


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


async def test_the_same_member_liking_twice_at_once_counts_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """같은 사람의 좋아요 둘이 겹친다. 공개 행을 붙든 트랜잭션이 앞의 좋아요를 "행은 넣었고 수는 아직" 자리에 세워 두면, 뒤의
    좋아요는 그 넣은 행의 커밋을 기다린다(둘 다 막힘을 먼저 확인). 놓으면 뒤의 것은 충돌로 아무것도 넣지 않아 수를 올리지
    않는다 — 행 수와 좋아요 수가 함께 1 이다."""
    novel = await _publish(independent_factory, await _member(independent_factory))
    member = await _member(independent_factory)

    def like_in_own_session() -> "asyncio.Task[None]":
        async def run() -> None:
            async with independent_factory() as s:
                await like_webnovel(novel_id=novel.novel_id, user_id=member, db=s)

        return asyncio.create_task(run())

    holder = independent_factory()
    try:
        await holder.execute(
            select(NovelPublication.novel_id).where(NovelPublication.novel_id == novel.novel_id).with_for_update()
        )
        first = like_in_own_session()
        await _assert_blocked(first)
        second = like_in_own_session()
        await _assert_blocked(second)
        await holder.rollback()
        await asyncio.wait_for(asyncio.gather(first, second), 10)
    finally:
        await holder.close()

    async with independent_factory() as s:
        likes = await s.scalar(select(func.count()).select_from(NovelLike).where(NovelLike.novel_id == novel.novel_id))
        count = await s.scalar(
            select(NovelPublication.like_count).where(NovelPublication.novel_id == novel.novel_id)
        )
    assert (likes, count) == (1, 1)
