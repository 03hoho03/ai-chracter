"""노벨 화 소장 구매와, 게시자가 산 화를 지울 때의 자동 환급.

**구매**는 화 하나를 클로버로 소장하는 것이다. 소설마다 앞 화들(`NOVEL_FREE_CHAPTER_COUNT`)과 게시자 본인의 열람은 무료라
살 것이 없다(원작자도 무료가 아니다 — 원작자는 이 소설을 쓴 사람이 아니다). 같은 화는 다시 사지 않는다. 다시 공개로 본문이
바뀌어도 같은 화이고, 거뒀다 다시 공개하면 소장이 그대로 살아난다(구매 행은 공개 상태를 따라 지워지지 않는다). 무료·보너스
클로버로도 산다 — 차감 순서는 다른 차감과 같다.

**삭제 환급** — 게시자가 산 화가 든 소설이나 마지막 묶음을 지우면, 그 화를 산 구매마다 차감을 깎은 로트로 되돌린다(유료는
유료로, 무료·보너스는 그대로). 전액 취소가 성공으로 확정된 결제에서 나온 로트의 몫은 돌려주지 않는다 — 그 로트로 되돌리면
돈과 클로버를 함께 돌려받는다. 부분 환불·진행 중이거나 실패한 취소의 결제는 정상 환급한다. 돌려준 양이 있으면 구매자에게
알림을 하나 보낸다. 공개 철회·게시자 탈퇴는 환급하지 않는다(열람만 끝난다). 탈퇴한 구매자의 구매 행은 구매자 칸이
비어 남지만 환급 대상이 아니다 — 탈퇴로 잔액이 이미 소멸했고 돌려받을 사람이 없다(`_REFUNDABLE`).

**잠금 순서는 사용자 행(관련된 모든 사람, id 순) → 공개 상태 행 → 구매 행 → 클로버(배분 → 로트)다.** 구매는 구매자와
게시자를, 삭제는 게시자와 그 소설의 구매자 전부를 같은 규칙으로 잡는다. 사용자 행을 사람마다 따로 잡으면 서로의 소설을
산 두 게시자가 동시에 지울 때, 각자 자기 행을 쥐고 상대(자기 소설의 구매자) 행을 기다려 교착한다. 공개 상태 행을 사용자 행
보다 먼저 잡아도 같다 — 삭제는 소설 경로 규칙상 게시자 행을 맨 먼저 잡기 때문이다(`novelize/router.py` 모듈 docstring).

삭제는 구매자를 잠그기 전에 잠금 없이 고른다. 그 사이 새 구매가 커밋되면(그 구매는 게시자 행을 쥐었다 놓았다) 잠근 뒤 다시
고른 목록에 잠그지 않은 구매자가 생긴다. 그 사람을 그 자리에서 더 잡으면 id 순서가 깨지므로 409 `NOVEL_DELETE_CONFLICT` 로
아무것도 지우지 않고 돌려보낸다 — 다시 누르면 새 구매자까지 잠그고 지운다.

이 모듈은 라우터를 import 하지 않는다 — 소설 라우터와 탈퇴가 import 해도 순환이 생기지 않게."""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.core.rate_limit import seconds_until_kst_midnight
from api.core.rate_limit_gate import _too_many_requests
from api.core.schema import CamelModel
from api.db.models.auth import User
from api.db.models.clover import CloverSpendAllocation, CloverSpendRefund
from api.db.models.content import Content
from api.db.models.moderation import Notification
from api.db.models.novel import Novel, NovelBatch, NovelChapter, NovelChapterPublication, NovelPublication, NovelPurchase
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.moderation.notifications import NOVEL_REFUND_NOTIFICATION_TYPE
from api.novel_public.access import readable_publication_conditions, require_novel_public_readable
from api.novel_public.no_store import NoStoreRoute
from api.novelize.schemas import NovelPurchaseRefundPreview
from api.payments.refund import fully_cancelled_purchase_lot
from api.session.dependencies import get_current_user_id

# 잔액 부족 429 의 `window`. 소설화 차감과 같은 바디 모양(`CLOVER_REQUIRED`)이고 이 값으로 어느 기능인지 가른다.
NOVEL_READ_WINDOW = "novel_read"

# 노벨 스위치가 꺼져 있으면 404 다 — 독자에게는 노벨이 없는 것과 같다(읽기 라우트와 같은 응답).
reader_router = APIRouter(
    prefix="/webnovels",
    tags=["webnovels"],
    dependencies=[Depends(require_novel_public_readable)],
    route_class=NoStoreRoute,
)


def _error(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **extra})


async def lock_users_in_order(db: AsyncSession, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, User]:
    """사용자 행들을 id 순으로 `FOR NO KEY UPDATE` 잠근다(모듈 docstring 의 잠금 순서). 행이 없는 id 는 결과에 없다.
    `ORDER BY` 뒤에 잠금이 걸리므로 행은 정렬된 순서로 잡힌다."""
    rows = await db.scalars(
        select(User)
        .where(User.id.in_(set(user_ids)))
        .order_by(User.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    return {user.id: user for user in rows.all()}


# ── 구매 ────────────────────────────────────────────────────────────────────
def is_free_chapter(ordinal: int) -> bool:
    """소설마다 앞 화들은 누구나 무료다. 무료 화 수는 호출 때 모듈 전역으로 읽는다(테스트가 바꿔 끼울 수 있게)."""
    return ordinal <= clover.NOVEL_FREE_CHAPTER_COUNT


@dataclass(frozen=True)
class _ChapterForSale:
    ordinal: int
    edition: int
    publisher_id: uuid.UUID
    content_id: uuid.UUID


async def _chapter_for_sale(db: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID) -> _ChapterForSale | None:
    """지금 독자가 읽을 수 있는 공개 화. 읽을 수 없으면(없음·거둠·이용제한·게시자 탈퇴·정지·원작 숨김) None — 사지 않은
    사람에게는 이유를 가르지 않는다."""
    row = (
        await db.execute(
            select(
                NovelChapterPublication.ordinal,
                NovelChapterPublication.edition,
                Novel.user_id,
                Novel.content_id,
            )
            .join(Novel, Novel.id == NovelChapterPublication.novel_id)
            .join(NovelPublication, NovelPublication.novel_id == Novel.id)
            .join(User, User.id == Novel.user_id)
            .join(Content, Content.id == Novel.content_id)
            .where(
                NovelChapterPublication.chapter_id == chapter_id,
                NovelChapterPublication.novel_id == novel_id,
                *readable_publication_conditions(),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    ordinal, edition, publisher_id, content_id = row
    return _ChapterForSale(ordinal=ordinal, edition=edition, publisher_id=publisher_id, content_id=content_id)


class NovelChapterPurchaseRequest(CamelModel):
    """`expected_price` 는 구매 확인 화면에 보인 가격이다. 지금 가격과 다르면 사지 않는다 — 배포로 가격이 바뀌는 사이 열어 둔
    화면의 금액으로 차감하지 않으려는 것이다(소설화의 `expected_cost` 와 같은 규칙)."""

    expected_price: int


class NovelChapterPurchaseResponse(CamelModel):
    """`charged` 는 이번 요청이 쓴 클로버다 — 이미 소장한 화면 0 이고 아무것도 쓰지 않는다. `balance` 는 요청 뒤 잔액이다."""

    chapter_id: uuid.UUID
    charged: int
    balance: int


async def purchase_chapter(
    db: AsyncSession, *, buyer_id: uuid.UUID, novel_id: uuid.UUID, chapter_id: uuid.UUID, expected_price: int
) -> NovelChapterPurchaseResponse:
    """화 하나를 산다. **커밋하지 않는다**(라우트가 한다). 실패는 `HTTPException` 이고 그때 쓴 것은 없다(호출부가 롤백).

    - 409 `NOVEL_READ_PRICE_CHANGED` + `currentPrice`: 확인 화면의 가격이 지금 가격과 다르다.
    - 404 `NOVEL_CHAPTER_NOT_FOUND`: 지금 읽을 수 있는 공개 화가 아니다.
    - 409 `NOVEL_CHAPTER_NOT_FOR_SALE`: 무료 화이거나 게시자 본인이다(살 것이 없다).
    - 429 `CLOVER_REQUIRED`(`window: "novel_read"`): 잔액 부족. 재시도 초는 소설화 차감과 같은 KST 자정까지다(참인 재시도
      시각은 없지만 정기적으로 클로버가 생기는 가장 이른 시점이라).

    이미 산 화면 차감 없이 소장 응답이다. 같은 사람의 동시 구매 둘은 구매자 행에서 줄을 서고, 뒤의 것은 앞의 구매 행을 본다
    (`(chapter_id, buyer_user_id)` 유니크가 마지막 그물)."""
    price = clover.NOVEL_READ_COST
    if expected_price != price:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_READ_PRICE_CHANGED", currentPrice=price)
    # 잠그기 전에 게시자를 알아야 사용자 행을 id 순으로 함께 잡는다. 판정은 잠근 뒤 다시 한다.
    preview = await _chapter_for_sale(db, novel_id, chapter_id)
    if preview is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    if is_free_chapter(preview.ordinal) or preview.publisher_id == buyer_id:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_CHAPTER_NOT_FOR_SALE")

    locked = await lock_users_in_order(db, (buyer_id, preview.publisher_id))
    buyer = locked.get(buyer_id)
    if buyer is None or buyer.deleted_at is not None:
        # 인증을 통과한 뒤 탈퇴가 먼저 커밋됐다.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    await db.execute(
        select(NovelPublication.novel_id).where(NovelPublication.novel_id == novel_id).with_for_update(read=True)
    )
    chapter = await _chapter_for_sale(db, novel_id, chapter_id)
    if chapter is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")

    owned = await db.scalar(
        select(NovelPurchase.id).where(NovelPurchase.chapter_id == chapter_id, NovelPurchase.buyer_user_id == buyer_id)
    )
    if owned is not None:
        return NovelChapterPurchaseResponse(chapter_id=chapter_id, charged=0, balance=buyer.clover_balance)

    spent = await clover.spend(
        db,
        user_id=buyer_id,
        amount=price,
        kind="novel_read_spend",
        usage=clover.SpendUsage(
            "novel_read", content_id=chapter.content_id, novel_id=novel_id, publisher_user_id=chapter.publisher_id
        ),
    )
    if spent is None:
        raise _too_many_requests(
            buyer_id, NOVEL_READ_WINDOW, seconds_until_kst_midnight(datetime.now(UTC)), code="CLOVER_REQUIRED"
        )
    db.add(
        NovelPurchase(
            buyer_user_id=buyer_id,
            publisher_user_id=chapter.publisher_id,
            novel_id=novel_id,
            chapter_id=chapter_id,
            chapter_ordinal=chapter.ordinal,
            edition=chapter.edition,
            spend_ledger_id=spent.ledger_id,
            price=price,
        )
    )
    await db.flush()
    return NovelChapterPurchaseResponse(chapter_id=chapter_id, charged=price, balance=spent.balance_after)


@reader_router.post(
    "/{novel_id}/chapters/{chapter_id}/purchase", dependencies=[Depends(require_legal_consent)]
)
async def purchase_novel_chapter(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    body: NovelChapterPurchaseRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterPurchaseResponse:
    """노벨 화 하나를 소장한다(`purchase_chapter`). 노벨 스위치가 꺼져 있으면 404 `NOVEL_PUBLIC_DISABLED`."""
    response = await purchase_chapter(
        db, buyer_id=user_id, novel_id=novel_id, chapter_id=chapter_id, expected_price=body.expected_price
    )
    await db.commit()
    return response


# ── 삭제 환급 ────────────────────────────────────────────────────────────────
# 삭제가 돌려줄 구매: 아직 환급하지 않았고 구매자가 있는 것. 탈퇴한 구매자의 구매는 구매자 칸이 비어 남는데, 잠글 사람도
# 돌려받을 잔액도 없으니 잠금·환급·삭제 전 고지에서 모두 뺀다.
_REFUNDABLE = (NovelPurchase.refunded_at.is_(None), NovelPurchase.buyer_user_id.is_not(None))


async def lock_publisher_and_buyers(
    db: AsyncSession, *, publisher_id: uuid.UUID, novel_id: uuid.UUID
) -> frozenset[uuid.UUID]:
    """소설을 지우거나 그 마지막 묶음을 지우기 전에, 게시자와 그 소설의 아직 환급하지 않은 구매자 전부를 id 순으로 잠근다.
    잠근 사람들을 돌려준다(`refund_deleted_purchases` 가 받는다). 소설 경로에서 게시자 행을 잡던 첫 잠금을 이것이 대신한다.

    묶음 삭제도 소설 전체의 구매자를 잡는다 — 어느 묶음이 지워질지는 잠근 뒤에 정해지는데, 그때 모자란 사람을 더 잡을 수
    없다(모듈 docstring)."""
    buyers = (
        await db.scalars(
            select(distinct(NovelPurchase.buyer_user_id)).where(NovelPurchase.novel_id == novel_id, *_REFUNDABLE)
        )
    ).all()
    user_ids = frozenset({publisher_id, *(buyer for buyer in buyers if buyer is not None)})  # `_REFUNDABLE` 이 이미 걸렀다
    await lock_users_in_order(db, user_ids)
    return user_ids


async def _refunded_amount(db: AsyncSession, spend_ledger_id: uuid.UUID) -> int:
    """그 차감에서 실제로 돌려준 양. 건너뛴 몫은 환급 행이 없어 빠진다."""
    total = await db.scalar(
        select(func.coalesce(func.sum(CloverSpendRefund.amount), 0))
        .join(CloverSpendAllocation, CloverSpendAllocation.id == CloverSpendRefund.allocation_id)
        .where(CloverSpendAllocation.spend_ledger_id == spend_ledger_id)
    )
    return int(total or 0)


async def refund_deleted_purchases(
    db: AsyncSession,
    *,
    novel_id: uuid.UUID,
    locked_user_ids: frozenset[uuid.UUID],
    chapter_ids: Sequence[uuid.UUID] | None = None,
) -> None:
    """지울 화(`chapter_ids`, None 이면 소설 전체)를 산 구매마다 환급하고 구매 행에 환급을 적고, 돌려준 양이 있는 구매자에게
    알림을 하나씩 보낸다. **커밋하지 않는다** — 지우기와 같은 트랜잭션이어야 "지웠는데 환급이 없다"가 생기지 않는다.
    `lock_publisher_and_buyers` 뒤에 부른다. 잠그지 않은 구매자가 보이면 409 `NOVEL_DELETE_CONFLICT`(모듈 docstring)."""
    await db.execute(select(NovelPublication.novel_id).where(NovelPublication.novel_id == novel_id).with_for_update())
    statement = select(NovelPurchase).where(NovelPurchase.novel_id == novel_id, *_REFUNDABLE)
    if chapter_ids is not None:
        statement = statement.where(NovelPurchase.chapter_id.in_(chapter_ids))
    purchases = (
        await db.scalars(
            statement.order_by(NovelPurchase.buyer_user_id, NovelPurchase.chapter_ordinal)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    if any(purchase.buyer_user_id not in locked_user_ids for purchase in purchases):
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_DELETE_CONFLICT")

    by_buyer: dict[uuid.UUID, list[NovelPurchase]] = {}
    for purchase in purchases:
        assert purchase.buyer_user_id is not None  # `_REFUNDABLE` 이 구매자 없는 행을 뺐다
        by_buyer.setdefault(purchase.buyer_user_id, []).append(purchase)
    now = await db.scalar(select(func.now()))
    for buyer_id, owned in by_buyer.items():
        total = 0
        for purchase in owned:
            await clover.refund_spend(
                db,
                user_id=buyer_id,
                spend_ledger_id=purchase.spend_ledger_id,
                amount=purchase.price,
                kind="novel_read_refund",
                skip_lot=fully_cancelled_purchase_lot(),
            )
            purchase.refunded_amount = await _refunded_amount(db, purchase.spend_ledger_id)
            purchase.refunded_at = now
            total += purchase.refunded_amount
        if total > 0:
            notification = Notification(user_id=buyer_id, type=NOVEL_REFUND_NOTIFICATION_TYPE)
            db.add(notification)
            await db.flush()
            for purchase in owned:
                purchase.refund_notification_id = notification.id
    await db.flush()


# ── 소유자 화면의 삭제 전 고지 ──────────────────────────────────────────────
async def _buyers_and_amount(
    db: AsyncSession, novel_id: uuid.UUID, chapter_ids: Select[tuple[uuid.UUID]] | None = None
) -> tuple[int, int]:
    statement = select(
        func.count(distinct(NovelPurchase.buyer_user_id)), func.coalesce(func.sum(NovelPurchase.price), 0)
    ).where(NovelPurchase.novel_id == novel_id, *_REFUNDABLE)
    if chapter_ids is not None:
        statement = statement.where(NovelPurchase.chapter_id.in_(chapter_ids))
    buyers, amount = (await db.execute(statement)).one()
    return int(buyers), int(amount)


async def purchase_refund_preview(db: AsyncSession, novel_id: uuid.UUID) -> NovelPurchaseRefundPreview:
    last_batch = (
        select(NovelBatch.id)
        .where(NovelBatch.novel_id == novel_id)
        .order_by(NovelBatch.ordinal.desc())
        .limit(1)
        .scalar_subquery()
    )
    last_batch_chapters = select(NovelChapter.id).where(NovelChapter.batch_id == last_batch)
    novel_buyers, novel_amount = await _buyers_and_amount(db, novel_id)
    batch_buyers, batch_amount = await _buyers_and_amount(db, novel_id, last_batch_chapters)
    return NovelPurchaseRefundPreview(
        novel_buyer_count=novel_buyers,
        novel_refund_amount=novel_amount,
        last_batch_buyer_count=batch_buyers,
        last_batch_refund_amount=batch_amount,
    )
