"""노벨 화 소장 구매.

**구매**는 화 하나를 클로버로 소장하는 것이다. 소설마다 앞 화들(`NOVEL_FREE_CHAPTER_COUNT`)과 게시자 본인의 열람은 무료라
살 것이 없다(원작자도 무료가 아니다 — 원작자는 이 소설을 쓴 사람이 아니다). 같은 화는 다시 사지 않는다. 다시 공개로 본문이
바뀌어도 같은 화이고, 거뒀다 다시 공개하면 소장이 그대로 살아난다(구매 행은 공개 상태를 따라 지워지지 않는다). 무료·보너스
클로버로도 산다 — 차감 순서는 다른 차감과 같다.

**잠금 순서는 사용자 행(관련된 모든 사람, id 순) → 공개 상태 행 → 구매 행 → 클로버(배분 → 로트)다.** 구매는 구매자와
게시자를, 삭제는 게시자와 그 소설의 구매자 전부를 같은 규칙으로 잡는다. 사용자 행을 사람마다 따로 잡으면 서로의 소설을
산 두 게시자가 동시에 지울 때, 각자 자기 행을 쥐고 상대(자기 소설의 구매자) 행을 기다려 교착한다. 공개 상태 행을 사용자 행
보다 먼저 잡아도 같다 — 삭제는 소설 경로 규칙상 게시자 행을 맨 먼저 잡기 때문이다(`novelize/router.py` 모듈 docstring).

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
from api.novel_public.access import readable_publication_conditions, require_novel_public_enabled
from api.novelize.schemas import NovelPurchaseRefundPreview
from api.payments.refund import refunded_purchase_lot
from api.session.dependencies import get_current_user_id

# 잔액 부족 429 의 `window`. 소설화 차감과 같은 바디 모양(`CLOVER_REQUIRED`)이고 이 값으로 어느 기능인지 가른다.
NOVEL_READ_WINDOW = "novel_read"

reader_router = APIRouter(
    prefix="/webnovels",
    tags=["webnovels"],
    dependencies=[Depends(require_novel_public_enabled)],
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
    """노벨 화 하나를 소장한다(`purchase_chapter`). 공개 스위치가 꺼져 있으면 403 `NOVEL_PUBLIC_DISABLED`."""
    response = await purchase_chapter(
        db, buyer_id=user_id, novel_id=novel_id, chapter_id=chapter_id, expected_price=body.expected_price
    )
    await db.commit()
    return response
