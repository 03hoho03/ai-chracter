"""노벨 화 소장 구매, 게시자 삭제 환급, 탈퇴가 구매 행에 하는 일.

공개 소설은 `_make_public_novel`(원작 = 다른 회원의 공개 작품, 6화 + 2화 묶음, 전부 공개)로 만든다. 앞 5화가 무료라 6화가 첫
유료 화이고, 마지막 묶음은 7·8화다. 같은 `db_client` 로 회원을 바꿔 가며 부른다(`_login_as`)."""

import uuid
from collections.abc import Sequence

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.core.config import settings
from api.db.models import User
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendUsage
from api.db.models.content import Content
from api.db.models.moderation import Notification
from api.db.models.novel import Novel, NovelChapter, NovelPublication, NovelPurchase
from api.db.models.payment import Payment, PaymentCancellation
from api.payments.refund import kst_today
from factories import (
    PublicNovel,
    _allow_novelize,
    _create_admin,
    _login_as,
    _make_payment,
    _make_public_novel,
    _make_user,
    _make_user_with_clover_lot,
)


@pytest.fixture(autouse=True)
def _novel_public_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)


async def _setup(db_session: AsyncSession) -> PublicNovel:
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id)
    await db_session.commit()
    return novel


async def _buyer(db_session: AsyncSession, balance: int = 100) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance)
    await db_session.commit()
    return user.id


async def _buy(
    client: httpx.AsyncClient, novel: PublicNovel, ordinal: int, *, as_user: uuid.UUID, price: int = 30
) -> httpx.Response:
    await _login_as(client, as_user)
    return await client.post(
        f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[ordinal - 1]}/purchase", json={"expectedPrice": price}
    )


async def _balance(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db_session.scalar(
        sa.select(User.clover_balance).where(User.id == user_id).execution_options(populate_existing=True)
    )
    assert balance is not None
    return balance


async def _ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = await db_session.execute(
        sa.select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.created_at, CloverLedger.amount)
    )
    return [(kind, amount) for kind, amount in rows.tuples()]


async def _purchases(db_session: AsyncSession, buyer_id: uuid.UUID) -> Sequence[NovelPurchase]:
    return (
        await db_session.scalars(
            sa.select(NovelPurchase)
            .where(NovelPurchase.buyer_user_id == buyer_id)
            .order_by(NovelPurchase.chapter_ordinal)
            .execution_options(populate_existing=True)
        )
    ).all()


# ── 구매 ────────────────────────────────────────────────────────────────────
async def test_buying_a_locked_chapter_charges_and_records_who_gets_what(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """6화(첫 유료 화)를 산다 — 차감 원장, 구매 행(번호·판·가격·차감 id), 사용처(원작·원작자·게시자)가 한 번에 남는다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session)

    resp = await _buy(db_client, novel, 6, as_user=buyer)

    assert resp.status_code == 200
    assert resp.json() == {"chapterId": str(novel.chapter_ids[5]), "charged": 30, "balance": 70}
    assert await _ledger(db_session, buyer) == [("novel_read_spend", -30)]
    [purchase] = await _purchases(db_session, buyer)
    assert (purchase.chapter_ordinal, purchase.edition, purchase.price, purchase.publisher_user_id) == (
        6,
        1,
        30,
        novel.publisher_id,
    )
    usage = await db_session.get_one(CloverSpendUsage, purchase.spend_ledger_id)
    source = await db_session.get_one(Content, novel.content_id)
    assert (usage.usage_kind, usage.content_id, usage.content_owner_user_id, usage.novel_id, usage.publisher_user_id) == (
        "novel_read",
        novel.content_id,
        source.creator_user_id,
        novel.novel_id,
        novel.publisher_id,
    )


async def test_an_owned_chapter_is_never_charged_again_even_after_withdraw_and_reopen(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소장은 한 번이다. 게시자가 거두면 사지 못하고(404), 다시 열면 이미 산 화는 차감 없이 소장 응답이다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session)
    assert (await _buy(db_client, novel, 6, as_user=buyer)).status_code == 200

    again = await _buy(db_client, novel, 6, as_user=buyer)
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(visibility="withdrawn")
    )
    await db_session.commit()
    while_withdrawn = await _buy(db_client, novel, 6, as_user=buyer)
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(visibility="public")
    )
    await db_session.commit()
    reopened = await _buy(db_client, novel, 6, as_user=buyer)

    assert again.json()["charged"] == 0 and reopened.json()["charged"] == 0
    assert while_withdrawn.status_code == 404
    assert await _ledger(db_session, buyer) == [("novel_read_spend", -30)]
    assert await _balance(db_session, buyer) == 70


async def test_free_chapters_and_the_publisher_have_nothing_to_buy(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5화는 무료(6화는 유료 — 위 시험)라 살 것이 없다. 게시자 본인은 유료 화도 무료다. 무료 화 수는 호출 때 읽는 설정값이라
    6 으로 바꾸면 6화도 무료가 된다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session)

    fifth = await _buy(db_client, novel, 5, as_user=buyer)
    by_publisher = await _buy(db_client, novel, 6, as_user=novel.publisher_id)
    monkeypatch.setattr(clover, "NOVEL_FREE_CHAPTER_COUNT", 6)
    sixth_when_six_are_free = await _buy(db_client, novel, 6, as_user=buyer)

    for resp in (fifth, by_publisher, sixth_when_six_are_free):
        assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "NOVEL_CHAPTER_NOT_FOR_SALE"})
    assert await _ledger(db_session, buyer) == []


async def test_the_source_creator_pays_like_any_reader(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _setup(db_session)
    creator_id = await db_session.scalar(sa.select(Content.creator_user_id).where(Content.id == novel.content_id))
    assert creator_id is not None
    db_session.add(CloverLot(user_id=creator_id, granted_amount=50, remaining=50, expires_at=None, kind="admin_grant"))
    await db_session.execute(sa.update(User).where(User.id == creator_id).values(clover_balance=50))
    await db_session.commit()

    resp = await _buy(db_client, novel, 6, as_user=creator_id)

    assert resp.json()["charged"] == 30


async def test_short_balance_is_429_and_writes_nothing(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _setup(db_session)
    buyer = await _buyer(db_session, balance=29)

    resp = await _buy(db_client, novel, 6, as_user=buyer)

    assert resp.status_code == 429
    assert (resp.json()["detail"]["code"], resp.json()["detail"]["window"]) == ("CLOVER_REQUIRED", "novel_read")
    assert await _purchases(db_session, buyer) == []
    assert await _balance(db_session, buyer) == 29


async def test_a_stale_price_is_409_and_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """확인 화면의 가격(30)이 지금 가격(40)과 다르면 사지 않는다 — 가격은 호출 때 읽는 설정값이다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session)
    monkeypatch.setattr(clover, "NOVEL_READ_COST", 40)

    resp = await _buy(db_client, novel, 6, as_user=buyer)

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "NOVEL_READ_PRICE_CHANGED", "currentPrice": 40})
    assert await _ledger(db_session, buyer) == []


async def test_unreadable_novels_cannot_be_bought(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """운영자 이용제한·정지된 게시자의 소설은 사지 못한다(이유를 가르지 않는 404). 공개 스위치가 꺼져도 404 다 — 독자에게는
    노벨이 없는 것과 같다(읽기 라우트와 같은 응답)."""
    restricted = await _setup(db_session)
    suspended = await _setup(db_session)
    buyer = await _buyer(db_session)
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == restricted.novel_id)
        .values(moderation_status="restricted")
    )
    await db_session.execute(sa.update(User).where(User.id == suspended.publisher_id).values(suspended_at=sa.func.now()))
    await db_session.commit()

    assert (await _buy(db_client, restricted, 6, as_user=buyer)).status_code == 404
    assert (await _buy(db_client, suspended, 6, as_user=buyer)).status_code == 404
    monkeypatch.setattr(settings, "novel_public_enabled", False)
    off = await _buy(db_client, restricted, 6, as_user=buyer)
    assert (off.status_code, off.json()["detail"]) == (404, {"code": "NOVEL_PUBLIC_DISABLED"})
    assert await _ledger(db_session, buyer) == []


# ── 구매 행 CHECK ───────────────────────────────────────────────────────────
async def _purchase_row(db_session: AsyncSession, **overrides: object) -> None:
    """정상 구매 행을 기본값으로, `overrides` 로 칸 하나를 틀어 넣는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    ledger = CloverLedger(user_id=user.id, amount=-30, balance_after=0, kind="novel_read_spend")
    db_session.add(ledger)
    await db_session.flush()
    values: dict[str, object] = {
        "buyer_user_id": user.id,
        "publisher_user_id": user.id,
        "novel_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "chapter_ordinal": 6,
        "edition": 1,
        "spend_ledger_id": ledger.id,
        "price": 30,
    }
    values.update(overrides)
    db_session.add(NovelPurchase(**values))
    await db_session.flush()


async def test_valid_purchase_rows_are_accepted(db_session: AsyncSession) -> None:
    """대조군 — 아래 거부들이 셋업 탓이 아니라 그 값 탓임을 보인다. 전부 건너뛴 환급(0)도 정상이다."""
    await _purchase_row(db_session)
    await _purchase_row(db_session, refunded_at=sa.func.now(), refunded_amount=0)
    await _purchase_row(db_session, refunded_at=sa.func.now(), refunded_amount=30)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"price": 0}, "ck_novel_purchases_price_positive", id="free-price"),
        pytest.param({"edition": 0}, "ck_novel_purchases_ordinal_edition_positive", id="edition-zero"),
        pytest.param({"refunded_amount": 30}, "ck_novel_purchases_refund_pair", id="amount-without-time"),
        pytest.param({"refunded_at": sa.func.now()}, "ck_novel_purchases_refund_pair", id="time-without-amount"),
        pytest.param(
            {"refunded_at": sa.func.now(), "refunded_amount": 31},
            "ck_novel_purchases_refunded_amount_range",
            id="refund-over-price",
        ),
        pytest.param(
            {"refunded_at": sa.func.now(), "refunded_amount": -1},
            "ck_novel_purchases_refunded_amount_range",
            id="refund-negative",
        ),
    ],
)
async def test_purchase_check_constraints_reject(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        await _purchase_row(db_session, **overrides)


async def test_refund_notification_needs_a_refund(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    notification = Notification(user_id=user.id, type="novel-purchase-refund")
    db_session.add(notification)
    await db_session.flush()

    with pytest.raises(IntegrityError, match="ck_novel_purchases_notification_after_refund"):
        await _purchase_row(db_session, refund_notification_id=notification.id)


# ── 삭제 환급 ───────────────────────────────────────────────────────────────
async def _notifications(client: httpx.AsyncClient, user_id: uuid.UUID) -> list[dict[str, object]]:
    await _login_as(client, user_id)
    resp = await client.get("/notifications")
    assert resp.status_code == 200
    items: list[dict[str, object]] = resp.json()["items"]
    return items


async def test_deleting_a_novel_refunds_every_purchase_and_tells_each_buyer_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 구매자(한 명은 두 화)의 구매가 모두 그 로트로 돌아가고, 구매자마다 알림 하나에 화 수·클로버 수가 실린다. 삭제
    전 소유자 상세의 고지 수와도 맞는다."""
    novel = await _setup(db_session)
    first, second = await _buyer(db_session), await _buyer(db_session)
    for ordinal in (6, 7):
        assert (await _buy(db_client, novel, ordinal, as_user=first)).status_code == 200
    assert (await _buy(db_client, novel, 8, as_user=second)).status_code == 200

    await _login_as(db_client, novel.publisher_id)
    resp = await db_client.delete(f"/novels/{novel.novel_id}")

    assert resp.status_code == 204
    assert await _balance(db_session, first) == 100 and await _balance(db_session, second) == 100
    assert await _ledger(db_session, first) == [
        ("novel_read_spend", -30),
        ("novel_read_spend", -30),
        ("novel_read_refund", 30),
        ("novel_read_refund", 30),
    ]
    assert [(p.chapter_ordinal, p.refunded_amount) for p in await _purchases(db_session, first)] == [(6, 30), (7, 30)]
    [notice] = await _notifications(db_client, first)
    assert (notice["type"], notice["novelRefund"]) == ("novel-purchase-refund", {"chapterCount": 2, "cloverAmount": 60})
    [notice] = await _notifications(db_client, second)
    assert notice["novelRefund"] == {"chapterCount": 1, "cloverAmount": 30}


async def test_owner_detail_tells_how_many_buyers_a_delete_will_refund(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """소설 전체는 6·7·8화 구매(두 사람, 90), 마지막 묶음은 7·8화(두 사람, 60)."""
    novel = await _setup(db_session)
    first, second = await _buyer(db_session), await _buyer(db_session)
    for buyer, ordinal in ((first, 6), (first, 7), (second, 8)):
        assert (await _buy(db_client, novel, ordinal, as_user=buyer)).status_code == 200
    await _allow_novelize(db_session, monkeypatch, novel.publisher_id)
    await _login_as(db_client, novel.publisher_id)

    resp = await db_client.get(f"/novels/{novel.novel_id}")

    assert resp.status_code == 200
    assert resp.json()["purchaseRefunds"] == {
        "novelBuyerCount": 2,
        "novelRefundAmount": 90,
        "lastBatchBuyerCount": 2,
        "lastBatchRefundAmount": 60,
    }


@pytest.mark.parametrize("route", ["batches", "chapters"])
async def test_deleting_the_last_batch_refunds_only_its_chapters(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """마지막 묶음(7·8화) 삭제는 그 화들의 구매만 돌려준다 — 6화 구매는 그대로다. 옛 이름의 마지막 화 삭제도 같다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session)
    for ordinal in (6, 7):
        assert (await _buy(db_client, novel, ordinal, as_user=buyer)).status_code == 200
    await _allow_novelize(db_session, monkeypatch, novel.publisher_id)
    await _login_as(db_client, novel.publisher_id)
    target = novel.batch_ids[1] if route == "batches" else novel.chapter_ids[7]

    resp = await db_client.delete(f"/novels/{novel.novel_id}/{route}/{target}")

    assert resp.status_code == 204
    assert [(p.chapter_ordinal, p.refunded_amount) for p in await _purchases(db_session, buyer)] == [(6, None), (7, 30)]
    assert await _balance(db_session, buyer) == 70


async def test_delete_refund_skips_what_came_from_a_fully_cancelled_payment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """무료 10 + 결제 유료 로트로 30 을 산 뒤 그 결제가 전액 취소로 성공 확정됐다. 삭제는 무료 10 만 돌려준다 — 결제 로트로
    20 을 되돌리면 돈과 클로버를 함께 돌려받는다. 알림·구매 행도 실제로 돌려준 10 이다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session, balance=10)
    payment = await _make_payment(db_session, user_id=buyer, status="paid")
    paid_lot = CloverLot(
        user_id=buyer, granted_amount=100, remaining=100, expires_at=None, kind="purchase_paid", payment_id=payment.id
    )
    db_session.add(paid_lot)
    await db_session.execute(sa.update(User).where(User.id == buyer).values(clover_balance=110))
    await db_session.commit()
    assert (await _buy(db_client, novel, 6, as_user=buyer)).status_code == 200
    await _settle_cancellation(db_session, payment.id, paid_lot.id, "full")

    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete(f"/novels/{novel.novel_id}")).status_code == 204

    assert await _balance(db_session, buyer) == 10
    assert (await _ledger(db_session, buyer))[-1] == ("novel_read_refund", 10)
    assert (
        await db_session.scalar(
            sa.select(CloverLot.remaining).where(CloverLot.id == paid_lot.id).execution_options(populate_existing=True)
        )
        == 0
    )
    [purchase] = await _purchases(db_session, buyer)
    assert purchase.refunded_amount == 10
    [notice] = await _notifications(db_client, buyer)
    assert notice["novelRefund"] == {"chapterCount": 1, "cloverAmount": 10}


async def test_a_purchase_paid_wholly_from_a_fully_cancelled_payment_gets_nothing_and_no_notice(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """전부 건너뛰면 원장 행도 알림도 없고, 구매 행에는 돌려준 0 이 적힌다(다시 환급하지 않는다)."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session, balance=0)
    payment = await _make_payment(db_session, user_id=buyer, status="paid")
    paid_lot = CloverLot(
        user_id=buyer, granted_amount=30, remaining=30, expires_at=None, kind="purchase_paid", payment_id=payment.id
    )
    db_session.add(paid_lot)
    await db_session.execute(sa.update(User).where(User.id == buyer).values(clover_balance=30))
    await db_session.commit()
    assert (await _buy(db_client, novel, 6, as_user=buyer)).status_code == 200
    await _settle_cancellation(db_session, payment.id, paid_lot.id, "full")

    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete(f"/novels/{novel.novel_id}")).status_code == 204

    assert await _balance(db_session, buyer) == 0
    assert await _ledger(db_session, buyer) == [("novel_read_spend", -30)]
    [purchase] = await _purchases(db_session, buyer)
    assert (purchase.refunded_amount, purchase.refund_notification_id) == (0, None)
    assert await _notifications(db_client, buyer) == []


@pytest.mark.parametrize("outcome", ["partial", "requested", "failed"])
async def test_delete_refund_returns_what_came_from_a_payment_not_fully_refunded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, outcome: str
) -> None:
    """결제 로트로 30 을 산 뒤 그 결제에 전액 취소 성공이 아닌 취소가 있다 — 남은 유료분만 돈으로 돌려준 부분 환불, 회수만
    하고 포트원 결과를 기다리는 취소, 거절로 확정돼 회수분을 되돌린 취소. 어느 쪽이든 소설 구매에 쓴 30 은 돈으로 돌려받지
    않았으니 삭제가 결제 로트로 30 을 돌려준다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session, balance=0)
    payment = await _make_payment(db_session, user_id=buyer, status="paid")
    paid_lot = CloverLot(
        user_id=buyer, granted_amount=100, remaining=100, expires_at=None, kind="purchase_paid", payment_id=payment.id
    )
    db_session.add(paid_lot)
    await db_session.execute(sa.update(User).where(User.id == buyer).values(clover_balance=100))
    await db_session.commit()
    assert (await _buy(db_client, novel, 6, as_user=buyer)).status_code == 200
    await _settle_cancellation(db_session, payment.id, paid_lot.id, outcome)
    left = 70 if outcome == "failed" else 0

    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete(f"/novels/{novel.novel_id}")).status_code == 204

    assert await _balance(db_session, buyer) == left + 30
    assert (await _ledger(db_session, buyer))[-1] == ("novel_read_refund", 30)
    [purchase] = await _purchases(db_session, buyer)
    assert purchase.refunded_amount == 30


async def _settle_cancellation(
    db_session: AsyncSession, payment_id: uuid.UUID, lot_id: uuid.UUID, outcome: str
) -> None:
    """그 결제(9,900원)의 취소 하나를 결과별로 적는다. 회수는 결제 로트의 남은 양 전부다.

    - full: 전액 취소 성공 — 남은 유료를 회수했고 결제의 취소액이 결제액과 같다.
    - partial: 어드민 부분 환불 성공 — 남은 유료만 돈으로 돌려줬다(취소액 < 결제액).
    - requested: 어드민 환불이 남은 유료를 회수하고 포트원 결과를 기다린다(취소액 0).
    - failed: 포트원이 거절해 회수분을 로트로 되돌렸다(로트·잔액·취소액 그대로)."""
    lot = await db_session.get_one(CloverLot, lot_id, populate_existing=True)
    revoked = 0 if outcome == "failed" else lot.remaining
    admin = await _create_admin(db_session)
    db_session.add(
        PaymentCancellation(
            payment_id=payment_id,
            source="admin",
            admin_id=admin["id"],
            request_received_on=kst_today(),
            status={"full": "succeeded", "partial": "succeeded"}.get(outcome, outcome),
            amount_krw=9_900 if outcome == "full" else 6_930,
            clawback_paid=revoked,
        )
    )
    if outcome in ("full", "partial"):
        cancelled = 9_900 if outcome == "full" else 6_930
        await db_session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id)
            .values(status="cancelled" if outcome == "full" else "partially_cancelled", cancelled_amount_krw=cancelled)
        )
    await db_session.execute(
        sa.update(CloverLot).where(CloverLot.id == lot_id).values(remaining=lot.remaining - revoked)
    )
    await db_session.execute(
        sa.update(User).where(User.id == lot.user_id).values(clover_balance=User.clover_balance - revoked)
    )
    await db_session.commit()


# ── 탈퇴 ────────────────────────────────────────────────────────────────────
async def test_a_withdrawn_buyer_is_left_out_of_the_delete_refund(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """구매자 탈퇴는 204 이고 그 사람의 구매 행을 지운다. 그 뒤 게시자가 소설을 지우면 탈퇴한 구매자에게는 아무것도 돌려주지
    않고(잔액은 탈퇴로 소멸했다) 남은 구매자만 돌려받는다."""
    novel = await _setup(db_session)
    leaving, staying = await _buyer(db_session), await _buyer(db_session)
    for buyer in (leaving, staying):
        assert (await _buy(db_client, novel, 6, as_user=buyer)).status_code == 200

    await _login_as(db_client, leaving)
    assert (await db_client.delete("/me")).status_code == 204
    assert await _purchases(db_session, leaving) == []
    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete(f"/novels/{novel.novel_id}")).status_code == 204

    assert await _balance(db_session, leaving) == 0
    assert sorted(kind for kind, _ in await _ledger(db_session, leaving)) == ["novel_read_spend", "withdrawal_burn"]
    assert await _balance(db_session, staying) == 100


async def test_a_withdrawing_publisher_ends_reading_without_refunds(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """게시자 탈퇴는 204 이고 소설은 지워지지만 환급하지 않는다 — 구매 행은 남아 "게시자가 탈퇴했다"의 근거가 된다."""
    novel = await _setup(db_session)
    buyer = await _buyer(db_session)
    assert (await _buy(db_client, novel, 6, as_user=buyer)).status_code == 200

    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete("/me")).status_code == 204

    assert await db_session.scalar(sa.select(Novel.id).where(Novel.id == novel.novel_id)) is None
    assert await db_session.scalar(sa.select(NovelChapter.id).where(NovelChapter.novel_id == novel.novel_id)) is None
    [purchase] = await _purchases(db_session, buyer)
    assert purchase.refunded_at is None
    assert await _ledger(db_session, buyer) == [("novel_read_spend", -30)]
    assert await _notifications(db_client, buyer) == []
