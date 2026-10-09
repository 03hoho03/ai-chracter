"""노벨 화 소장 구매.

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
from api.db.models.payment import PaymentCancellation
from factories import PublicNovel, _allow_novelize, _login_as, _make_payment, _make_public_novel, _make_user, _make_user_with_clover_lot


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
    """운영자 이용제한·정지된 게시자의 소설은 사지 못한다(이유를 가르지 않는 404). 공개 스위치가 꺼지면 403 이다."""
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
    assert (off.status_code, off.json()["detail"]) == (403, {"code": "NOVEL_PUBLIC_DISABLED"})
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
