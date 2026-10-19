"""노벨 구매자 보호의 경합 — 환급이 걸린 쓰기(탈퇴·노벨 이용제한·원작 이용제한·판매 소설 숨김·숨긴 소설 파기)가 구매나 서로와
실제로 겹칠 때(독립 커넥션, 정책 스위치 켜짐).

같은 커넥션의 테스트로는 두 요청이 순서대로 돌아 경합이 드러나지 않는다. 그래서 잠금을 쥔 상대 트랜잭션(`holder`)을 세워
두고 두 쓰기를 띄워, 둘 다 정말 막혀 있는 것(`_assert_blocked`)을 먼저 확인한 뒤 놓는다. 막힘 확인이 없으면 둘을 순서대로
돌려도 같은 최종 상태가 나와 아무것도 증명하지 못한다.

잠금 규칙은 사용자 행(관련된 모든 사람, id 순, 한 번에) → 공개 상태 행 → 구매 행 → 클로버다. 구매는 (구매자, 게시자)를 id
순으로 잡으므로, 사용자 행보다 다른 행을 먼저 잡거나 사람을 따로따로 잡는 쓰기는 구매자 id 가 게시자 id 보다 작을 때 구매와
교착한다. 두 경우를 모두 돌린다.

탈퇴는 앱 세션(실제 커밋)으로 `DELETE /me` 를 부르고, 나머지는 라우트 함수를 자기 세션으로 직접 부른다. 만든 행은 롤백되지
않으므로 끝에서 직접 지운다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import pytest
import pytest_asyncio
from factories import PublicNovel, _assert_blocked, _login_as, _make_public_novel, _make_user_with_clover_lot
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.admin.contents import act_on_content
from api.admin.schemas import AdminContentActionRequest
from api.core.config import settings
from api.db.models import AdminActionLog, AdminUser, User
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendAllocation, CloverSpendRefund, CloverSpendUsage
from api.db.models.content import Content
from api.db.models.moderation import ModerationAction, ModerationActionType, Notification, ReportReasonCategory
from api.db.models.novel import Novel, NovelPublication, NovelPurchase
from api.main import app
from api.novel_public.admin import moderate_admin_novel
from api.novel_public.admin_schemas import AdminNovelModerationRequest
from api.novel_public.purchases import NovelChapterPurchaseResponse, purchase_chapter
from api.novelize import router as novelize_router
from api.novelize.deletion import delete_novels
from api.novelize.hidden_purge import purge_hidden_novels

_SETTLE_SECONDS = 10


@pytest.fixture(autouse=True)
def _switches_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)


@dataclass
class _World:
    """커밋되는 독립 세션 팩토리와, 테스트가 만든 회원·운영자 id(끝에서 지울 것)."""

    factory: async_sessionmaker[AsyncSession]
    users: list[uuid.UUID] = field(default_factory=list)
    admins: list[uuid.UUID] = field(default_factory=list)

    async def member(self, balance: int = 100) -> uuid.UUID:
        async with self.factory() as s:
            user = await _make_user_with_clover_lot(s, clover_balance=balance)
            await s.commit()
        self.users.append(user.id)
        return user.id

    async def pair(self) -> tuple[uuid.UUID, uuid.UUID]:
        """회원 둘을 (id 가 작은 쪽, 큰 쪽)으로."""
        first, second = await self.member(), await self.member()
        return (first, second) if first < second else (second, first)

    async def publish(self, publisher_id: uuid.UUID) -> PublicNovel:
        """6화 + 2화짜리 공개 소설(6·7·8화가 유료). 원작자도 지울 대상에 넣는다."""
        async with self.factory() as s:
            novel = await _make_public_novel(s, publisher_id)
            creator = await s.scalar(select(Content.creator_user_id).where(Content.id == novel.content_id))
            await s.commit()
        assert creator is not None
        self.users.append(creator)
        return novel

    async def admin(self) -> uuid.UUID:
        async with self.factory() as s:
            admin = AdminUser(email=f"admin-{uuid.uuid4()}@example.com", password_hash="x")
            s.add(admin)
            await s.commit()
        self.admins.append(admin.id)
        return admin.id


@pytest_asyncio.fixture
async def world(db_engine: AsyncEngine) -> AsyncGenerator[_World, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    created = _World(factory)
    yield created
    async with factory() as cleanup:
        users, admins = created.users, created.admins
        novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(users)))).all()
        content_ids = select(Content.id).where(Content.creator_user_id.in_(users))
        await cleanup.execute(
            delete(NovelPurchase).where(
                or_(NovelPurchase.buyer_user_id.in_(users), NovelPurchase.publisher_user_id.in_(users))
            )
        )
        await cleanup.execute(delete(AdminActionLog).where(AdminActionLog.admin_id.in_(admins)))
        await cleanup.execute(delete(Notification).where(Notification.user_id.in_(users)))
        await cleanup.execute(delete(ModerationAction).where(ModerationAction.content_id.in_(content_ids)))
        ledger_ids = select(CloverLedger.id).where(CloverLedger.user_id.in_(users))
        allocation_ids = select(CloverSpendAllocation.id).where(CloverSpendAllocation.spend_ledger_id.in_(ledger_ids))
        await cleanup.execute(delete(CloverSpendRefund).where(CloverSpendRefund.allocation_id.in_(allocation_ids)))
        await cleanup.execute(delete(CloverSpendAllocation).where(CloverSpendAllocation.spend_ledger_id.in_(ledger_ids)))
        await cleanup.execute(delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(ledger_ids)))
        await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(users)))
        await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(users)))
        await delete_novels(cleanup, novel_ids)
        await cleanup.execute(delete(Content).where(Content.creator_user_id.in_(users)))
        # 탈퇴한 회원 행도 지운다 — 파기로 비워진 칸(생년월일 등)이 남으면 세션 끝 downgrade 의 NOT NULL 복원이 깨진다.
        await cleanup.execute(delete(User).where(User.id.in_(users)))
        await cleanup.execute(delete(AdminUser).where(AdminUser.id.in_(admins)))
        await cleanup.commit()


async def _buy(db: AsyncSession, novel: PublicNovel, buyer_id: uuid.UUID, ordinal: int) -> NovelChapterPurchaseResponse:
    return await purchase_chapter(
        db, buyer_id=buyer_id, novel_id=novel.novel_id, chapter_id=novel.chapter_ids[ordinal - 1], expected_price=30
    )


async def _bought(world: _World, novel: PublicNovel, buyer_id: uuid.UUID, ordinal: int) -> None:
    async with world.factory() as s:
        assert (await _buy(s, novel, buyer_id, ordinal)).charged == 30
        await s.commit()


def _in_own_session(
    world: _World, step: Callable[[AsyncSession], Awaitable[object]]
) -> "asyncio.Task[object]":
    """`step` 을 자기 세션으로 띄우고 커밋한다. 거절(`HTTPException`)은 결과로 돌려준다 — 교착 같은 다른 예외는 그대로 터져
    테스트를 실패시킨다."""

    async def run() -> object:
        async with world.factory() as s:
            try:
                result = await step(s)
            except HTTPException as exc:
                return exc
            await s.commit()
            return result

    return asyncio.create_task(run())


def _purchase_task(world: _World, novel: PublicNovel, buyer_id: uuid.UUID, ordinal: int) -> "asyncio.Task[object]":
    return _in_own_session(world, lambda s: _buy(s, novel, buyer_id, ordinal))


def _restrict_task(world: _World, novel: PublicNovel, admin_id: uuid.UUID) -> "asyncio.Task[object]":
    body = AdminNovelModerationRequest(action="restrict", admin_comment="운영정책 위반")
    return _in_own_session(
        world, lambda s: moderate_admin_novel(novel_id=novel.novel_id, body=body, admin_id=admin_id, db=s)
    )


def _restrict_source_task(world: _World, novel: PublicNovel, admin_id: uuid.UUID) -> "asyncio.Task[object]":
    body = AdminContentActionRequest(action=ModerationActionType.RESTRICT, reason_category=ReportReasonCategory.SPAM)
    return _in_own_session(
        world, lambda s: act_on_content(content_id=novel.content_id, body=body, admin_id=admin_id, db=s)
    )


def _delete_novel_task(world: _World, novel_id: uuid.UUID) -> "asyncio.Task[object]":
    async def step(s: AsyncSession) -> None:
        novel = await s.get_one(Novel, novel_id)
        await novelize_router.delete_novel(novel=novel, db=s)

    return _in_own_session(world, step)


def _withdraw_task(user_id: uuid.UUID) -> "asyncio.Task[object]":
    """앱 세션으로 `DELETE /me` 를 부르고 상태 코드를 돌려준다(회원마다 쿠키가 따로라 클라이언트를 새로 연다)."""

    async def run() -> object:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            await _login_as(client, user_id)
            return (await client.delete("/me")).status_code

    return asyncio.create_task(run())


async def _hold_user(world: _World, user_id: uuid.UUID) -> AsyncSession:
    """그 회원 행을 쥔 채 커밋하지 않는 트랜잭션. 호출자가 닫는다."""
    holder = world.factory()
    await holder.execute(select(User.id).where(User.id == user_id).with_for_update())
    return holder


async def _settle(holder: AsyncSession, tasks: list["asyncio.Task[object]"]) -> list[object]:
    """쥔 행을 놓고 띄운 쓰기들이 끝나기를 기다린다."""
    await holder.rollback()
    return list(await asyncio.wait_for(asyncio.gather(*tasks), _SETTLE_SECONDS))


async def _close_quietly(holder: AsyncSession, tasks: list["asyncio.Task[object]"]) -> None:
    """단언이 중간에 깨져도 쥔 행을 놓고 띄운 쓰기를 끝까지 기다려, 다음 테스트로 커넥션이 새지 않게 한다."""
    await holder.close()
    await asyncio.wait(tasks, timeout=_SETTLE_SECONDS)


async def _refunds(world: _World, buyer_id: uuid.UUID) -> list[tuple[int, int | None]]:
    async with world.factory() as s:
        rows = await s.execute(
            select(NovelPurchase.chapter_ordinal, NovelPurchase.refunded_amount)
            .where(NovelPurchase.buyer_user_id == buyer_id)
            .order_by(NovelPurchase.chapter_ordinal, NovelPurchase.created_at)
        )
        return [(ordinal, amount) for ordinal, amount in rows.tuples()]


async def _refund_entries(world: _World, user_id: uuid.UUID) -> int:
    async with world.factory() as s:
        count = await s.scalar(
            select(func.count())
            .select_from(CloverLedger)
            .where(CloverLedger.user_id == user_id, CloverLedger.kind == "novel_read_refund")
        )
    return count or 0


async def _balance(world: _World, user_id: uuid.UUID) -> int:
    async with world.factory() as s:
        balance = await s.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


async def _novel_exists(world: _World, novel_id: uuid.UUID) -> bool:
    async with world.factory() as s:
        return await s.scalar(select(Novel.id).where(Novel.id == novel_id)) is not None


def _assert_each_purchase_refunded_once(refunds: list[tuple[int, int | None]], entries: int) -> None:
    assert refunds, "구매가 하나도 없다"
    assert all(amount == 30 for _, amount in refunds), refunds
    assert entries == len(refunds)


# ── 재구매 ──────────────────────────────────────────────────────────────────
async def test_the_same_buyer_buying_a_reopened_chapter_twice_at_once_pays_once(world: _World) -> None:
    """환급된 뒤 다시 열린 6화를 같은 사람이 동시에 두 번 산다. 둘은 구매자 행에서 줄을 서고, 뒤의 것은 앞의 새 구매를 보고
    차감 없이 소장 응답이다 — 차감 한 번, 미환급 구매 행 하나. 깨지는 시나리오: 환급된 옛 구매를 소장으로 보아 둘 다 0
    클로버로 끝나거나, 둘 다 차감해 같은 화를 두 번 산다."""
    publisher, buyer = await world.member(), await world.member()
    novel = await world.publish(publisher)
    await _bought(world, novel, buyer, 6)
    async with world.factory() as s:
        await s.execute(
            update(NovelPurchase)
            .where(NovelPurchase.buyer_user_id == buyer)
            .values(refunded_at=func.now(), refunded_amount=30, refund_reason="novel_restricted")
        )
        await s.commit()
    holder = await _hold_user(world, buyer)
    tasks = [_purchase_task(world, novel, buyer, 6), _purchase_task(world, novel, buyer, 6)]
    try:
        for task in tasks:
            await _assert_blocked(task)
        results = await _settle(holder, tasks)
    finally:
        await _close_quietly(holder, tasks)

    charged = sorted(result.charged for result in results if isinstance(result, NovelChapterPurchaseResponse))
    assert charged == [0, 30]
    assert await _refunds(world, buyer) == [(6, 30), (6, None)]


# ── 탈퇴 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("buyer_below_publisher", [True, False], ids=["buyer-id-lower", "buyer-id-higher"])
async def test_a_withdrawal_racing_a_purchase_refunds_it_once_or_stops_it_without_deadlock(
    world: _World, buyer_below_publisher: bool
) -> None:
    """6화를 이미 산 사람이 7화를 사는 동안 게시자가 탈퇴한다. 두 사람 중 id 가 작은 쪽의 행을 쥔 트랜잭션 뒤에 구매·탈퇴가
    차례로 막힌다. 놓으면 교착 없이 둘 다 끝나고, 그 사람의 구매는 모두 정확히 한 번 환급된다(구매가 먼저면 7화도 환급, 탈퇴가
    먼저면 7화 구매는 없다). 깨지는 시나리오: 탈퇴가 게시자 행을 먼저 쥐고 구매자 행을 나중에 잡아, 구매자 id 가 더 작을 때
    구매(구매자 → 게시자)와 서로 기다린다."""
    lower, higher = await world.pair()
    publisher, buyer = (higher, lower) if buyer_below_publisher else (lower, higher)
    novel = await world.publish(publisher)
    await _bought(world, novel, buyer, 6)
    holder = await _hold_user(world, lower)
    purchase = _purchase_task(world, novel, buyer, 7)
    withdrawal = _withdraw_task(publisher)
    try:
        await _assert_blocked(purchase)
        await _assert_blocked(withdrawal)
        bought, withdrawn = await _settle(holder, [purchase, withdrawal])
    finally:
        await _close_quietly(holder, [purchase, withdrawal])

    assert withdrawn == 204
    assert isinstance(bought, NovelChapterPurchaseResponse) or (
        isinstance(bought, HTTPException) and bought.status_code == 404
    ), bought
    _assert_each_purchase_refunded_once(await _refunds(world, buyer), await _refund_entries(world, buyer))
    assert await _balance(world, buyer) == 100


async def test_a_withdrawal_that_waited_for_a_new_purchase_retries_and_refunds_that_buyer_too(world: _World) -> None:
    """탈퇴가 구매자 집합을 읽은 뒤, 아직 커밋되지 않은 새 구매가 게시자 행을 쥐고 있다. 탈퇴는 그 구매를 기다렸다가 잠그지
    않은 새 구매자를 보고 처음부터 다시 해, 새 구매자까지 환급하고 204 로 끝난다. 깨지는 시나리오: 잠그지 않은 구매자를 건너뛰어
    그 구매가 환급 없이 버려지거나, 그 사람을 순서 밖에서 잡아 교착하거나, 다시 하지 않고 탈퇴를 실패시킨다."""
    publisher = await world.member()
    earlier, later = await world.member(), await world.member()
    novel = await world.publish(publisher)
    await _bought(world, novel, earlier, 6)
    purchase = world.factory()
    tasks: list[asyncio.Task[object]] = []
    try:
        await _buy(purchase, novel, later, 6)
        # 구매가 게시자 행을 쥔 뒤에 띄운다 — 먼저 띄우면 탈퇴가 그 행을 먼저 잡을 수 있다.
        tasks.append(_withdraw_task(publisher))
        await _assert_blocked(tasks[0])
        await purchase.commit()
        status_code = await asyncio.wait_for(tasks[0], _SETTLE_SECONDS)
    finally:
        await purchase.close()
        if tasks:
            await asyncio.wait(tasks, timeout=_SETTLE_SECONDS)

    assert status_code == 204
    for buyer in (earlier, later):
        assert await _refunds(world, buyer) == [(6, 30)]
        assert await _balance(world, buyer) == 100


# ── 제재 ────────────────────────────────────────────────────────────────────
Restrict = Callable[[_World, PublicNovel, uuid.UUID], "asyncio.Task[object]"]


@pytest.mark.parametrize(
    "restrict",
    [pytest.param(_restrict_task, id="novel"), pytest.param(_restrict_source_task, id="source")],
)
async def test_a_restriction_racing_a_purchase_by_a_lower_id_buyer_refunds_once_without_deadlock(
    world: _World, restrict: Restrict
) -> None:
    """구매자 id 가 게시자 id 보다 작다. 6화를 이미 산 그 사람이 7화를 사는 동안 운영자가 노벨(또는 원작)을 이용제한한다. 구매자
    행을 쥔 트랜잭션 뒤에 구매·제재가 차례로 막히고, 놓으면 교착 없이 둘 다 끝나며 그 사람의 구매는 모두 정확히 한 번 환급된다.
    깨지는 시나리오: 제재가 공개 상태 행(또는 작품 조치 행)을 먼저 쥔 채 환급하러 구매자 행을 기다리고, 구매는 구매자 행을 쥔
    채 공개 상태 행을 기다려 교착한다(500)."""
    buyer, publisher = await world.pair()
    novel = await world.publish(publisher)
    await _bought(world, novel, buyer, 6)
    admin = await world.admin()
    holder = await _hold_user(world, buyer)
    purchase = _purchase_task(world, novel, buyer, 7)
    restriction = restrict(world, novel, admin)
    try:
        await _assert_blocked(purchase)
        await _assert_blocked(restriction)
        bought, restricted = await _settle(holder, [purchase, restriction])
    finally:
        await _close_quietly(holder, [purchase, restriction])

    assert not isinstance(restricted, HTTPException), restricted
    assert isinstance(bought, NovelChapterPurchaseResponse) or (
        isinstance(bought, HTTPException) and bought.status_code == 404
    ), bought
    _assert_each_purchase_refunded_once(await _refunds(world, buyer), await _refund_entries(world, buyer))
    assert await _balance(world, buyer) == 100


async def test_a_restriction_racing_the_publishers_withdrawal_refunds_each_purchase_once(world: _World) -> None:
    """노벨 이용제한과 게시자 탈퇴가 겹친다. 두 사람 중 id 가 작은 쪽의 행을 쥔 트랜잭션 뒤에 둘 다 막히고, 놓으면 어느 쪽이
    먼저든 산 사람의 구매는 한 번만 환급된다(뒤에 온 쪽은 돌려줄 것이 없거나, 소설이 지워져 이용제한할 대상이 없다). 깨지는
    시나리오: 둘이 같은 구매를 각자 미환급으로 읽어 이중 환급하거나 환급 초과 오류로 하나가 500 이 된다."""
    publisher, buyer = await world.member(), await world.member()
    novel = await world.publish(publisher)
    await _bought(world, novel, buyer, 6)
    admin = await world.admin()
    holder = await _hold_user(world, min(publisher, buyer))
    withdrawal = _withdraw_task(publisher)
    restriction = _restrict_task(world, novel, admin)
    try:
        await _assert_blocked(withdrawal)
        await _assert_blocked(restriction)
        withdrawn, restricted = await _settle(holder, [withdrawal, restriction])
    finally:
        await _close_quietly(holder, [withdrawal, restriction])

    assert withdrawn == 204
    assert not isinstance(restricted, HTTPException) or restricted.status_code == 404, restricted
    assert await _refunds(world, buyer) == [(6, 30)]
    assert await _refund_entries(world, buyer) == 1
    assert await _balance(world, buyer) == 100


async def test_deleting_a_sold_novel_and_restricting_it_at_once_refund_once_without_deadlock(world: _World) -> None:
    """판매된 소설 삭제와 노벨 이용제한이 겹친다. 둘 다 막힌 뒤 놓으면 교착 없이 끝나고 산 사람의 구매는 이용제한으로 한 번
    환급된다. 어느 쪽이 먼저 줄을 통과하느냐에 따라 소설은 숨겨지거나(삭제가 먼저 — 숨긴 뒤 이용제한이 환급) 진짜로 지워진다
    (이용제한이 먼저 — 환급 뒤 소장자가 없어 삭제가 지운다). 깨지는 시나리오: 삭제와 제재가 사용자 행·공개 상태 행을 서로 다른
    순서로 잡아 교착하거나, 삭제가 환급하고 제재가 또 환급하거나, 숨김 판정을 잠그기 전에 해 아무도 환급하지 않는다."""
    publisher, buyer = await world.member(), await world.member()
    novel = await world.publish(publisher)
    await _bought(world, novel, buyer, 6)
    admin = await world.admin()
    holder = await _hold_user(world, min(publisher, buyer))
    deleting = _delete_novel_task(world, novel.novel_id)
    restriction = _restrict_task(world, novel, admin)
    try:
        await _assert_blocked(deleting)
        await _assert_blocked(restriction)
        deleted, restricted = await _settle(holder, [deleting, restriction])
    finally:
        await _close_quietly(holder, [deleting, restriction])

    assert (deleted, isinstance(restricted, HTTPException)) == (None, False)
    async with world.factory() as s:
        row = await s.get(Novel, novel.novel_id)
        visibility = await s.scalar(select(NovelPublication.visibility).where(NovelPublication.novel_id == novel.novel_id))
    assert row is None or (row.hidden_at is not None and visibility == "withdrawn")
    assert await _refunds(world, buyer) == [(6, 30)]
    assert await _refund_entries(world, buyer) == 1
    assert await _balance(world, buyer) == 100


# ── 숨긴 소설 파기 ───────────────────────────────────────────────────────────
async def test_the_purge_and_the_publishers_withdrawal_delete_a_hidden_novel_once_without_deadlock(
    world: _World,
) -> None:
    """미환급 소장자가 남지 않은 숨긴 소설을 파기하는 동안 게시자가 탈퇴한다. 게시자 행을 쥔 트랜잭션 뒤에 둘 다 막히고(파기도
    게시자 행을 먼저 잡는다), 놓으면 교착·오류 없이 소설이 한 번 지워진다. 깨지는 시나리오: 파기가 소설 행부터 지우다 탈퇴의
    소설 삭제와 서로 기다리거나, 이미 지워진 소설을 다시 지우다 실패한다."""
    publisher, buyer = await world.member(), await world.member()
    novel = await world.publish(publisher)
    await _bought(world, novel, buyer, 6)
    async with world.factory() as s:
        await s.execute(
            update(NovelPurchase)
            .where(NovelPurchase.novel_id == novel.novel_id)
            .values(refunded_at=func.now(), refunded_amount=30, refund_reason="novel_restricted")
        )
        await s.execute(update(Novel).where(Novel.id == novel.novel_id).values(hidden_at=func.now(), chat_room_id=None))
        await s.execute(
            update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(visibility="withdrawn")
        )
        await s.commit()
    holder = await _hold_user(world, publisher)
    withdrawal = _withdraw_task(publisher)
    purge = _in_own_session(world, purge_hidden_novels)
    try:
        await _assert_blocked(withdrawal)
        await _assert_blocked(purge)
        withdrawn, _purged = await _settle(holder, [withdrawal, purge])
    finally:
        await _close_quietly(holder, [withdrawal, purge])

    assert withdrawn == 204
    assert not await _novel_exists(world, novel.novel_id)
