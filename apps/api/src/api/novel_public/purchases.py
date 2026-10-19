"""노벨 화 소장 구매와, 산 화를 더 읽을 수 없게 될 때의 자동 환급.

**구매**는 화 하나를 클로버로 소장하는 것이다. 화마다 무료·유료는 화 공개본에 저장된 값(`NovelChapterPublication.price`,
0 = 무료)이 정하고 유료 화의 가격은 늘 지금 화당 가격(`NOVEL_READ_COST`)이며, 소설마다 앞 화들(`NOVEL_FREE_CHAPTER_COUNT`)은
그 값과 무관하게 무료다(`chapter_price`). 구매 행에는 그때 낸 값을 남기고 환급은 그 값을 돌려준다. 무료 화와 게시자 본인의 열람은 살
것이 없다(원작자도 무료가 아니다 — 원작자는 이 소설을 쓴 사람이 아니다). 산 뒤 작가가 그 화를 무료로 바꿔도 환불하지 않는다. 환급되지 않은 구매가 있는 화는 다시 사지 않는다.
다시 공개로 본문이 바뀌어도 같은 화이고, 거뒀다 다시 공개하면 소장이 그대로 살아난다(구매 행은 공개 상태를 따라 지워지지
않는다). 환급된 구매는 소장이 아니다 — 그 화가 다시 열리면 다시 산다. 무료·보너스 클로버로도 산다 — 차감 순서는 다른 차감과
같다.

**환급** — 산 화를 더 읽을 수 없게 만드는 쓰기마다 그 구매를 환급하고 사유(`refund_reason`)를 적는다. 게시자가 산 화가 든
소설이나 마지막 묶음을 지우는 것(`deleted`)은 늘 환급한다. 정책 스위치(`novel_public_policy_v2_enabled`)가 켜져 있으면 운영자의
노벨 이용제한(`novel_restricted`), 원작의 자체 이용제한·삭제(`source_restricted`·`source_deleted`)도 환급한다 — 켜져 있을 때는
산 사람이 읽지 못하게 되는 경우와 환급되는 경우가 같다. 공개 거둠·게시자 정지·원작자 정지로 인한 원작 일괄 제한·판매된 소설
삭제(숨김)·게시자 탈퇴(판매된 소설을 숨겨 남김)·운영자의 판매 중단(노벨 판매 중단, 원작을 제한·삭제하면서 파생 소설은 판매만
멈추기로 고른 것 — `source_closing_keeps_buyers`)은 환급하지 않는다 — 산 사람은 계속 읽는다(`access.py` 의 소장자 열람 조건).
다시 열려도 환급은 되돌리지 않는다. 사유 `publisher_withdrawn` 은 새로 쓰지 않는다 — 그 사유로 적힌 옛 행을 읽기 위해 값만
남긴다.

환급은 차감을 깎은 로트로 되돌린다(유료는 유료로, 무료·보너스는 그대로, 만료된 로트면 다음 만료 배치가 태운다). 전액 취소가
성공으로 확정된 결제에서 나온 로트의 몫은 돌려주지 않는다 — 그 로트로 되돌리면 돈과 클로버를 함께 돌려받는다. 부분 환불·진행
중이거나 실패한 취소의 결제는 정상 환급한다. 돌려준 양이 있으면 구매자에게 알림을 하나 보낸다. 탈퇴한 구매자의 구매 행은
구매자 칸이 비어 남지만 환급 대상이 아니다 — 탈퇴로 잔액이 이미 소멸했고 돌려받을 사람이 없다(`_REFUNDABLE`).

**잠금 순서는 사용자 행(관련된 모든 사람, id 순, 한 번에) → 공개 상태 행 → 구매 행 → 클로버(배분 → 로트)다.** 구매는
구매자와 게시자를, 환급하는 쓰기는 대상 소설들의 게시자와 아직 환급하지 않은 구매자 전부를 같은 규칙으로 잡는다. 게시자
탈퇴는 환급하지 않아 탈퇴자 행 하나만 잡는다 — 구매가 게시자 행을 잡으므로 그것으로 구매와 줄을 선다. 사용자 행을 사람마다 따로 잡으면 서로의 소설을 산 두 게시자가 동시에 지울 때, 각자 자기 행을 쥐고 상대(자기 소설의
구매자) 행을 기다려 교착한다. 공개 상태 행을 사용자 행보다 먼저 잡아도 같다 — 구매가 사용자 행을 쥔 채 공개 상태 행을
기다리기 때문이다.

환급하는 쓰기는 구매자를 잠그기 전에 잠금 없이 고른다. 그 사이 새 구매가 커밋되면(그 구매는 게시자 행을 쥐었다 놓았다) 잠근
뒤 다시 고른 목록에 잠그지 않은 구매자가 생긴다. 그 사람을 그 자리에서 더 잡으면 id 순서가 깨지므로 `NovelPartiesChangedError` 로
아무것도 쓰지 않고 돌아간다 — 소설 삭제는 409 `NOVEL_DELETE_CONFLICT`, 운영자 조치는 409 `NOVEL_REFUND_CONFLICT`(다시 누르면
새 구매자까지 잠근다).

이 모듈은 라우터를 import 하지 않는다 — 소설 라우터와 탈퇴가 import 해도 순환이 생기지 않게."""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.core.config import settings
from api.core.rate_limit import seconds_until_kst_midnight
from api.core.rate_limit_gate import _too_many_requests
from api.core.schema import CamelModel
from api.db.models.auth import User
from api.db.models.clover import CloverSpendAllocation, CloverSpendRefund
from api.db.models.content import Content, DerivativeNovelsChoice
from api.db.models.moderation import Notification
from api.db.models.novel import (
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterPublication,
    NovelPublication,
    NovelPurchase,
    NovelPurchaseRefundReason,
)
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
def chapter_price(ordinal: int, stored_price: int) -> int:
    """화의 지금 가격(0 = 무료). 저장된 값은 무료(0)인지 유료(그 밖)인지만 뜻하고, 유료 화는 늘 지금 화당 가격이다 — 화당
    가격 상수를 바꾸면 이미 공개한 유료 화도 그 값으로 팔린다(이미 산 구매 행은 낸 값 그대로다). 앞 화들은 저장된 값과
    무관하게 무료다 — 가격 칸을 모르는 옛 코드가 앞 화를 공개하면 칸의 기본값(유료)이 들어가기 때문이다. 두 상수는 호출 때
    모듈 전역으로 읽는다(테스트가 바꿔 끼울 수 있게)."""
    if ordinal <= clover.NOVEL_FREE_CHAPTER_COUNT or stored_price == 0:
        return 0
    return clover.NOVEL_READ_COST


@dataclass(frozen=True)
class _ChapterForSale:
    ordinal: int
    edition: int
    price: int
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
                NovelChapterPublication.price,
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
    ordinal, edition, stored_price, publisher_id, content_id = row
    return _ChapterForSale(
        ordinal=ordinal,
        edition=edition,
        price=chapter_price(ordinal, stored_price),
        publisher_id=publisher_id,
        content_id=content_id,
    )


class NovelChapterPurchaseRequest(CamelModel):
    """`expected_price` 는 구매 확인 화면에 보인 가격이다. 그 화의 지금 가격과 다르면 사지 않는다 — 확인 화면에 보이지 않은
    금액으로 차감하지 않으려는 것이다(소설화의 `expected_cost` 와 같은 규칙)."""

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

    - 404 `NOVEL_CHAPTER_NOT_FOUND`: 지금 읽을 수 있는 공개 화가 아니다.
    - 409 `NOVEL_CHAPTER_NOT_FOR_SALE`: 무료 화이거나 게시자 본인이다(살 것이 없다). 가격 비교보다 먼저 본다 — 무료가 된 화에
      열려 있던 확인 화면이 "가격이 바뀌었다(0)"를 받으면 0 클로버 확인을 다시 띄운다.
    - 409 `NOVEL_READ_PRICE_CHANGED` + `currentPrice`: 확인 화면의 가격이 그 화의 지금 가격과 다르다.
    - 429 `CLOVER_REQUIRED`(`window: "novel_read"`): 잔액 부족. 재시도 초는 소설화 차감과 같은 KST 자정까지다(참인 재시도
      시각은 없지만 정기적으로 클로버가 생기는 가장 이른 시점이라).

    이미 산 화(환급되지 않은 구매가 있는 화)면 차감 없이 소장 응답이다. 환급된 구매만 있으면 다시 산다. 같은 사람의 동시
    구매 둘은 구매자 행에서 줄을 서고, 뒤의 것은 앞의 구매 행을 본다(미환급 행만 담는 `(chapter_id, buyer_user_id)` 부분
    유니크가 마지막 그물).

    가격·무료 판정·차감·구매 기록은 모두 잠근 뒤 다시 읽은 화의 가격으로 한다. 무료로 전환은 게시자 행을 잡고 쓰므로 그와
    겹친 구매는 게시자 행에서 줄을 서고, 잠근 뒤의 조회가 전환 결과를 본다 — 잠그기 전에 읽은 가격을 쓰면 이미 무료가 된 화에
    차감한다."""
    # 잠그기 전에 게시자를 알아야 사용자 행을 id 순으로 함께 잡는다. 판정은 잠근 뒤에 한다.
    preview = await _chapter_for_sale(db, novel_id, chapter_id)
    if preview is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")

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
    if chapter.price == 0 or chapter.publisher_id == buyer_id:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_CHAPTER_NOT_FOR_SALE")
    price = chapter.price
    if expected_price != price:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_READ_PRICE_CHANGED", currentPrice=price)

    owned = await db.scalar(
        select(NovelPurchase.id).where(
            NovelPurchase.chapter_id == chapter_id,
            NovelPurchase.buyer_user_id == buyer_id,
            NovelPurchase.refunded_at.is_(None),
        )
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


# ── 환급 ────────────────────────────────────────────────────────────────────
# 환급할 구매: 아직 환급하지 않았고 구매자가 있는 것. 탈퇴한 구매자의 구매는 구매자 칸이 비어 남는데, 잠글 사람도 돌려받을
# 잔액도 없으니 잠금·환급·삭제 전 고지에서 모두 뺀다.
_REFUNDABLE = (NovelPurchase.refunded_at.is_(None), NovelPurchase.buyer_user_id.is_not(None))


class NovelPartiesChangedError(Exception):
    """잠근 뒤 다시 고른 환급 대상에 잠그지 않은 구매자가 있다 — 그 사이 새 구매가 커밋됐다(모듈 docstring). 아무것도 쓰지
    않았으니 호출자가 롤백하고 거절하거나 처음부터 다시 한다."""


async def refundable_buyer_ids(db: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> frozenset[uuid.UUID]:
    """소설들의 아직 환급하지 않은 구매자. 잠그지 않고 읽는다."""
    if not novel_ids:
        return frozenset()
    buyers = (
        await db.scalars(
            select(distinct(NovelPurchase.buyer_user_id)).where(NovelPurchase.novel_id.in_(novel_ids), *_REFUNDABLE)
        )
    ).all()
    return frozenset(buyer for buyer in buyers if buyer is not None)  # `_REFUNDABLE` 이 이미 걸렀다


async def lock_novel_parties(
    db: AsyncSession, *, novel_ids: Sequence[uuid.UUID], extra_user_ids: Iterable[uuid.UUID] = ()
) -> frozenset[uuid.UUID]:
    """환급할 수 있는 쓰기의 첫 잠금. 소설들의 게시자와 아직 환급하지 않은 구매자 전부, 그리고 `extra_user_ids` 를 id 순으로
    한 번에 잠그고 잠근 사람들을 돌려준다(`refund_purchases` 가 받는다). 누구를 잠글지는 잠그기 전에 잠금 없이 고른다 —
    잠근 뒤에 모자란 사람이 보이면 `refund_purchases` 가 `NovelPartiesChangedError` 로 알린다."""
    publishers = (
        (await db.scalars(select(Novel.user_id).where(Novel.id.in_(novel_ids)))).all() if novel_ids else []
    )
    user_ids = frozenset({*publishers, *await refundable_buyer_ids(db, novel_ids), *extra_user_ids})
    await lock_users_in_order(db, user_ids)
    return user_ids


async def lock_publisher_and_buyers(
    db: AsyncSession, *, publisher_id: uuid.UUID, novel_id: uuid.UUID
) -> frozenset[uuid.UUID]:
    """소설 하나를 지우거나 그 마지막 묶음을 지우기 전의 `lock_novel_parties`. 소설 경로에서 게시자 행을 잡던 첫 잠금을
    이것이 대신한다 — 그 소설이 그사이 지워졌어도 게시자는 잡는다.

    묶음 삭제도 소설 전체의 구매자를 잡는다 — 어느 묶음이 지워질지는 잠근 뒤에 정해지는데, 그때 모자란 사람을 더 잡을 수
    없다(모듈 docstring)."""
    return await lock_novel_parties(db, novel_ids=[novel_id], extra_user_ids=(publisher_id,))


async def _refunded_amount(db: AsyncSession, spend_ledger_id: uuid.UUID) -> int:
    """그 차감에서 실제로 돌려준 양. 건너뛴 몫은 환급 행이 없어 빠진다."""
    total = await db.scalar(
        select(func.coalesce(func.sum(CloverSpendRefund.amount), 0))
        .join(CloverSpendAllocation, CloverSpendAllocation.id == CloverSpendRefund.allocation_id)
        .where(CloverSpendAllocation.spend_ledger_id == spend_ledger_id)
    )
    return int(total or 0)


async def refund_purchases(
    db: AsyncSession,
    *,
    novel_ids: Sequence[uuid.UUID],
    locked_user_ids: frozenset[uuid.UUID],
    reason: NovelPurchaseRefundReason,
    chapter_ids: Sequence[uuid.UUID] | None = None,
) -> None:
    """소설들(`chapter_ids` 를 주면 그 화들)의 아직 환급하지 않은 구매를 모두 환급하고 구매 행에 환급과 사유를 적는다. 돌려준
    양이 있는 구매자에게는 이번 환급 전체에 알림을 하나씩 보낸다. **커밋하지 않는다** — 닫는 쓰기와 같은 트랜잭션이어야
    "닫혔는데 환급이 없다"가 생기지 않는다.

    `lock_novel_parties` 뒤에 부른다. 공개 상태 행(소설 id 순) → 구매 행 순으로 잠그고, 잠그지 않은 구매자가 보이면
    `NovelPartiesChangedError`(모듈 docstring). 이미 환급한 구매는 고르지 않으므로 같은 노벨을 두 번 닫아도 두 번째는 돌려줄 것이
    없다."""
    if not novel_ids:
        return
    await db.execute(
        select(NovelPublication.novel_id)
        .where(NovelPublication.novel_id.in_(novel_ids))
        .order_by(NovelPublication.novel_id)
        .with_for_update()
    )
    statement = select(NovelPurchase).where(NovelPurchase.novel_id.in_(novel_ids), *_REFUNDABLE)
    if chapter_ids is not None:
        statement = statement.where(NovelPurchase.chapter_id.in_(chapter_ids))
    purchases = (
        await db.scalars(
            statement.order_by(NovelPurchase.buyer_user_id, NovelPurchase.novel_id, NovelPurchase.chapter_ordinal)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    if any(purchase.buyer_user_id not in locked_user_ids for purchase in purchases):
        raise NovelPartiesChangedError

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
            purchase.refund_reason = reason
            total += purchase.refunded_amount
        if total > 0:
            notification = Notification(user_id=buyer_id, type=NOVEL_REFUND_NOTIFICATION_TYPE)
            db.add(notification)
            await db.flush()
            for purchase in owned:
                purchase.refund_notification_id = notification.id
    await db.flush()


async def refund_deleted_purchases(
    db: AsyncSession,
    *,
    novel_id: uuid.UUID,
    locked_user_ids: frozenset[uuid.UUID],
    chapter_ids: Sequence[uuid.UUID] | None = None,
) -> None:
    """게시자가 지울 화(`chapter_ids`, None 이면 소설 전체)를 산 구매의 환급(사유 `deleted`). `lock_publisher_and_buyers`
    뒤에 부른다. 잠그지 않은 구매자가 보이면 409 `NOVEL_DELETE_CONFLICT` 이고 아무것도 쓰지 않는다(다시 누르면 된다)."""
    try:
        await refund_purchases(
            db, novel_ids=[novel_id], locked_user_ids=locked_user_ids, reason="deleted", chapter_ids=chapter_ids
        )
    except NovelPartiesChangedError:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_DELETE_CONFLICT") from None


async def refund_closing_purchases(
    db: AsyncSession,
    *,
    novel_ids: Sequence[uuid.UUID],
    locked_user_ids: frozenset[uuid.UUID],
    reason: NovelPurchaseRefundReason,
) -> None:
    """운영자 조치(노벨 이용제한, 원작 이용제한·삭제)로 닫히는 소설들의 환급. `lock_novel_parties` 뒤에 부른다. 잠그지 않은
    구매자가 보이면 409 `NOVEL_REFUND_CONFLICT` 이고 조치도 함께 되돌아간다 — 운영자가 다시 누르면 새 구매자까지 잠근다."""
    try:
        await refund_purchases(db, novel_ids=novel_ids, locked_user_ids=locked_user_ids, reason=reason)
    except NovelPartiesChangedError:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_REFUND_CONFLICT") from None


@dataclass(frozen=True)
class SourceClosing:
    """원작을 닫는 조치가 환급할 소설들과 잠근 사람들(`lock_source_closing`)."""

    novel_ids: list[uuid.UUID]
    locked_user_ids: frozenset[uuid.UUID]
    reason: NovelPurchaseRefundReason


async def lock_source_closing(
    db: AsyncSession, *, content_id: uuid.UUID, deleting: bool
) -> SourceClosing | None:
    """원작을 이용제한하거나 지우는 조치(직접·신고 처리)의 첫 잠금. 정책 스위치가 켜져 있으면 그 원작으로 만든 소설 전부
    (공개 중·거둠·숨김 모두 — 산 사람이 있으면 그 열람이 함께 닫힌다)의 게시자와 미환급 구매자를 잠그고 돌려준다. 꺼져 있으면
    환급이 없으니 잠그지 않고 None.

    조치 행 INSERT 보다 먼저 부른다. 그 INSERT 가 FK 로 원작 행에 키 공유 잠금을 거는데, 탈퇴는 회원 행을 잡은 뒤 댓글을 단
    원작 행을 `FOR UPDATE` 로 잡는다 — 원작 행을 먼저 쥐고 구매자 행을 기다리면 그 원작에 댓글을 단 구매자의 탈퇴와 교착한다."""
    if not settings.novel_public_policy_v2_enabled:
        return None
    novel_ids = list((await db.scalars(select(Novel.id).where(Novel.content_id == content_id).order_by(Novel.id))).all())
    locked = await lock_novel_parties(db, novel_ids=novel_ids)
    return SourceClosing(
        novel_ids=novel_ids, locked_user_ids=locked, reason="source_deleted" if deleting else "source_restricted"
    )


async def refund_source_closing(db: AsyncSession, closing: SourceClosing | None) -> None:
    """`lock_source_closing` 이 잠근 소설들의 구매를 환급한다(None 이면 아무것도 하지 않는다). 원작 상태를 바꾼 뒤에 부른다."""
    if closing is None:
        return
    await refund_closing_purchases(
        db, novel_ids=closing.novel_ids, locked_user_ids=closing.locked_user_ids, reason=closing.reason
    )


def source_closing_keeps_buyers(*, closes: bool, choice: DerivativeNovelsChoice | None) -> bool:
    """원작 조치(직접·신고 처리)가 파생 소설의 산 사람을 남기는가 — 원작을 닫는 조치(`closes`)이고 `stop_sales` 를 골랐을 때만
    참이다. 참이면 호출자는 `lock_source_closing`·환급을 건너뛰고 원작에 `novel_buyers_kept` 를 세운다(소장자 조건이 그 표식으로
    열람을 둔다). 정책 스위치가 꺼져 있는데 `stop_sales` 를 고르면 409 `NOVEL_SALES_STOP_DISABLED` — 꺼진 동안은 소장자 열람이
    없어 "판매만 멈춤"이 환급 없는 닫힘이 된다. 아무것도 쓰기 전에 부른다."""
    if not closes or choice != "stop_sales":
        return False
    if not settings.novel_public_policy_v2_enabled:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_SALES_STOP_DISABLED")
    return True


# ── 판매된 소설·묶음 ────────────────────────────────────────────────────────
async def novel_was_sold(db: AsyncSession, novel_id: uuid.UUID) -> bool:
    """정책 스위치가 켜졌을 때 이 소설의 삭제가 숨김이 되는가 — 아직 환급되지 않은 구매(탈퇴하지 않은 구매자)가 하나라도
    있는가. 숨기는 까닭은 산 사람이 계속 읽게 하려는 것이라, 소장자가 없으면(모두 환급받았거나 모두 탈퇴) 판매되지 않은
    소설처럼 진짜로 지운다 — 읽을 사람도 없는데 숨겨 두면 작가가 지운 글이 다음 파기까지 남는다.

    삭제는 사용자 행을 잠근 뒤에 이것을 부른다. 같은 노벨의 이용제한(환급)도 같은 사용자 행을 먼저 잡으므로 둘은 줄을 서고,
    어느 쪽이 먼저든 구매는 한 번 환급된다(제재가 먼저면 진짜 삭제, 삭제가 먼저면 숨긴 뒤 제재가 환급). 소유자 화면의 삭제 전
    고지(`purchase_refund_preview`)도 이것을 써서 안내와 실제 동작이 같다."""
    found = await db.scalar(select(NovelPurchase.id).where(NovelPurchase.novel_id == novel_id, *_REFUNDABLE).limit(1))
    return found is not None


async def sold_novel_ids(db: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> frozenset[uuid.UUID]:
    """소설들 가운데 `novel_was_sold` 가 참인 것 — 탈퇴가 지우지 않고 숨겨 남길 소설을 한 번에 고른다. 판정 조건은 같다
    (아직 환급되지 않은 구매, 탈퇴하지 않은 구매자). 탈퇴자 행을 잠근 뒤에 부른다(같은 이유 — 구매가 게시자 행을 잡는다)."""
    if not novel_ids:
        return frozenset()
    found = await db.scalars(
        select(distinct(NovelPurchase.novel_id)).where(NovelPurchase.novel_id.in_(novel_ids), *_REFUNDABLE)
    )
    return frozenset(found.all())


async def chapters_with_unrefunded_purchase(db: AsyncSession, chapter_ids: Sequence[uuid.UUID]) -> bool:
    """그 화들에 아직 환급되지 않은 구매(탈퇴하지 않은 구매자)가 있는가 — 정책 스위치가 켜졌을 때 마지막 묶음을 지울 수
    없는 조건이다(소설 라우터의 409 `NOVEL_BATCH_SOLD`)."""
    if not chapter_ids:
        return False
    found = await db.scalar(
        select(NovelPurchase.id).where(NovelPurchase.chapter_id.in_(chapter_ids), *_REFUNDABLE).limit(1)
    )
    return found is not None


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
    policy_v2 = settings.novel_public_policy_v2_enabled
    return NovelPurchaseRefundPreview(
        novel_buyer_count=novel_buyers,
        novel_refund_amount=novel_amount,
        last_batch_buyer_count=batch_buyers,
        last_batch_refund_amount=batch_amount,
        novel_sold=policy_v2 and await novel_was_sold(db, novel_id),
        # 마지막 묶음 삭제의 409 `NOVEL_BATCH_SOLD` 와 같은 조건(그 묶음 화의 미환급 구매가 있다).
        last_batch_sold=policy_v2 and batch_buyers > 0,
    )
