"""클로버(재화) 서비스 — 잔액 판정과 원장 기록.

`core/`에 두는 이유는 게이트(`core/rate_limit_gate.py`)가 이걸 부르기 때문이다. HTTP 표면은
별도 패키지(`clover/router.py`)로 가른다.

**불변식은 `users.clover_balance`의 조건부 UPDATE 하나다**. 원장은
같은 트랜잭션에 얹는 기록이지 판정 근거가 아니다 — 순서를 뒤집어 원장을 먼저 INSERT하고 잔액을
`SUM()`으로 계산하면 동시 트랜잭션 둘이 서로의 미커밋 행을 못 봐서 **둘 다 통과한다**.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import Integer, case, func, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.rate_limit import KST
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendAllocation

logger = logging.getLogger(__name__)

# **정책값이지 실측 원가가 아니다** — 턴당 원가는
# 8.3~91.1원으로 11배 흔들리고 그 분포를 측정한 적이 없다.
# 게이트 함수는 이 이름들을 **호출 시점에 모듈 전역으로** 읽는다 — 기본 인자로 캡처하면
# `monkeypatch.setattr`가 통하지 않는다(`core/rate_limit.py`의 상한 상수와 같은 규칙).
CHAT_TURN_COST = 10
IMAGE_UNIT_COST = 30
ATTENDANCE_GRANT_AMOUNT = 100
# 소설화 단가 — 화 하나의 클로버와 AI 문단 수정 한 번의 클로버. 생성 한 번은 묶음 하나를 여러 화로 쓰고 화 수 × 화
# 단가를 낸다. 다시 만들기도 같은 호출이라 같은 화 단가다. 본 시험에서 기본 모델로 잰 평균 원가(약 5천 자 장 하나
# 약 $0.049, 문단 수정 약 $0.026 — 이 모델의 2027년 인상 후 단가로 계산)를 1달러 1,400원·1클로버 3원·순매출 88% 로
# 환산하면 화 40·수정 20 에서 원가가 매출의 약 3분의 2다(화 목표 길이가 그 장과 같은 5천 자다). 시험한 장이 다섯 개뿐이고
# 사고 토큰이 보고되지 않은 호출이 있어 원가가 낮게 잡혔을 수 있으므로, 운영에서 원가를 다시 보고 고친다. 웹은 이 값의
# 사본을 갖지 않고 서버 응답으로만 받는다(배포 사이에 열어 둔 화면의 금액이 어긋나지 않게).
NOVELIZE_EPISODE_COST = 40
NOVELIZE_AI_EDIT_COST = 20
# 상위 모델(Bedrock 의 Claude)로 쓰는 채팅 턴 하나와 소설 화 하나의 클로버. 위 Gemini 값과 짝이고 모델 레지스트리
# (`llm/chat_models.py`)가 호출 때마다 여기서 읽는다. **원가 최악 기준의 임시값이다** — 채팅 턴은 조감독 작품 긴 방의
# 캐시 미적중 턴 실측 원가(Sonnet 약 $0.08)를 1달러 1,400원·1클로버 3원으로 환산한 값보다 높게 잡았고 Opus 는 단가 비율로
# 올렸다. Opus 화는 짧은 연결 시험에서 잰 출력 토큰/글자 비로 5천 자 화 하나의 입출력 원가를 어림해 1클로버 3원·순매출
# 88%·원가율 65% 로 환산한 값(약 178)에 가깝게 잡았고, Sonnet 화는 토큰 단가가 Opus 의 0.6배라 그 비율로 낮췄다. 상위
# 모델은 꺼진 채 배포되므로 켜기 전에 실측으로 다시 정한다.
CHAT_TURN_COST_SONNET = 40
CHAT_TURN_COST_OPUS = 65
NOVELIZE_EPISODE_COST_SONNET = 105
NOVELIZE_EPISODE_COST_OPUS = 170

# `db/models/clover.py`의 `kind` 컬럼 주석과 같은 목록이다. 컬럼은 Text라 DB가 값을 막지
# 않으므로(마이그레이션 없이 넓히기 위해서다) 이 `Literal`이 유일한 강제 지점이다.
CloverKind = Literal[
    "admin_grant",
    "admin_revoke",
    "attendance_grant",
    "chat_spend",
    "image_spend",
    "chat_refund",
    "image_refund",
    "withdrawal_burn",
    # 미션 청구(`clover/router.py`)와 만료 배치(`scripts/ops/expire_clover.py`)가 쓴다.
    "mission_grant",
    "expire_burn",
    # 소설화 작업 생성 때의 선차감과, 실패 확정 때의 환불·목표보다 적은 화를 낸 성공의 차액 환불(`novelize/billing.py`).
    "novelize_spend",
    "novelize_refund",
]

# 구매로 생기는 로트 kind. 차감 정렬은 이 둘만 이름으로 집고 나머지 kind 는 전부 무료로 본다 — 무료 kind 를 나열하면
# kind 가 늘 때(Text 라 마이그레이션 없이 는다) 빠뜨린 무료 로트가 유료 뒤로 밀린다. 둘만 집으면 누락이 생길 자리가 없다.
PURCHASE_LOT_KINDS = ("purchase_paid", "purchase_bonus")

# 소진은 만료 임박 우선, 회수는 최근 지급분부터 — 둘 다
# `_apply`의 음수-delta 분기(`guard=True`)를 공유하지만 로트를 잡는 정렬이 정반대다.
_LotOrder = Literal["expiry_first", "recency_first"]

# 차감 등급: 무료 → 구매 보너스 → 구매 유료. 현금으로 산 유료분을 가장 늦게 쓰게 해, 환불할 때 남은 유료 수량이
# 최대가 되게 한다. 같은 구매의 유료·보너스는 등급으로 갈려 동률이 없다.
_SPEND_GRADE = case(
    (CloverLot.kind == "purchase_bonus", 1),
    (CloverLot.kind == "purchase_paid", 2),
    else_=0,
)


@dataclass(frozen=True)
class CloverSpend:
    """차감 결과. `ledger_id` 는 이 차감의 원장 행이고, 환급(`refund_spend`)이 그 배분을 찾는 열쇠다."""

    balance_after: int
    ledger_id: uuid.UUID


class CloverRefundExceedsSpendError(Exception):
    """환급액이 그 차감에서 아직 돌려주지 않은 양보다 크다. 같은 차감을 두 번 환급하려 했다는 뜻이다 — 트랜잭션을
    롤백시켜 이중 환급을 막는다(배분 CHECK 가 그 뒤의 마지막 그물이다)."""


class CloverLotShortfallError(Exception):
    """총액 CAS(`users.clover_balance`)는 통과했는데
    로트 합계가 부족한 비정상 상태(Σ 불변식이 이미 깨졌다는 뜻, 예컨대 백필 누락). 이 예외를
    잡지 않고 그대로 낸다 — 트랜잭션이 롤백돼 총액 CAS까지 되돌아가는 것이 목적이다.
    """


async def _consume_lots(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount: int,
    order: _LotOrder,
    spend_ledger_id: uuid.UUID | None,
) -> None:
    """로트를 `SELECT ... FOR UPDATE`로 잠가 `amount`만큼 순서대로 깎는다.

    호출 전에 총액 CAS가 이미 통과했다는 전제다(락 순서는 `_apply`가 users를 먼저
    잠근 뒤에야 이 함수가 clover_lots를 잠그는 순서로 고정된다). 여기서 부족이 나오면
    잔액 자체가 모자란 정상 부족이 아니라 Σ 불변식이 깨진 비정상 상태라
    `CloverLotShortfallError`를 던진다.

    `order`가 정렬을 가른다 — `expiry_first`는 소진, `recency_first`는 회수다.
    만료 여부로 거르지 않는다 — `remaining > 0`만 본다. 만료의 진실은 배치뿐이다.

    소진은 등급(무료 → 보너스 → 유료) 안에서 만료 임박 순이다. `id` 는 같은 트랜잭션에서 만든 로트의 `created_at`
    동률을 결정적으로 끊는 꼬리다. 회수는 무료 로트만 본다 — 구매분은 결제 환불 경로로만 회수한다.

    `spend_ledger_id` 가 있으면(차감) 로트마다 배분 행을 남긴다. 회수는 환급 대상이 아니라 `None` 이다.
    """
    statement = select(CloverLot).where(CloverLot.user_id == user_id, CloverLot.remaining > 0)
    if order == "expiry_first":
        statement = statement.order_by(
            _SPEND_GRADE,
            CloverLot.expires_at.asc().nulls_last(),
            CloverLot.created_at.asc(),
            CloverLot.id.asc(),
        )
    else:
        statement = statement.where(CloverLot.kind.not_in(PURCHASE_LOT_KINDS)).order_by(CloverLot.created_at.desc())

    lots = (await db.scalars(statement.with_for_update())).all()

    left = amount
    seq = 0
    for lot in lots:
        if left <= 0:
            break
        take = min(lot.remaining, left)
        lot.remaining -= take
        left -= take
        if spend_ledger_id is not None:
            db.add(CloverSpendAllocation(spend_ledger_id=spend_ledger_id, lot_id=lot.id, seq=seq, amount=take))
            seq += 1

    if left > 0:
        raise CloverLotShortfallError(
            f"user {user_id}: 로트 합계가 요청 {amount} 중 {left}만큼 모자라다"
        )


async def _apply(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    delta: int,
    kind: CloverKind,
    idempotency_key: str | None,
    guard: bool,
    expires_at: datetime | None = None,
    lot_order: _LotOrder = "expiry_first",
    record_allocations: bool = False,
) -> CloverLedger | None:
    """잔액 UPDATE + 원장 INSERT를 한 트랜잭션에 넣는다. **커밋하지 않는다.** 원장 행을 돌려준다(유저가 없거나 가드에
    걸리면 `None`).

    `guard=True`면 `WHERE clover_balance >= -delta`를 걸어 음수로 내려가지 않게 한다 — 이
    WHERE가 없으면 동시 요청 둘이 같은 잔액을 읽고 둘 다 통과한다.

    🔴 판정에 `.rowcount`를 쓰지 않는다 — mypy strict에서 `Result[Any]`가 그 속성을 노출하지
    않는다(`admin/users.py:411-412`). `RETURNING clover_balance`가 **행을 돌려줬는가**로 가른다.
    선례는 `admin/users.py:416-423`.

    `guard`가 그대로 로트 처리 분기를 가른다.
    `guard=False`는 항상 `grant()`(양수 `delta`)만 타므로 로트 1행을 새로 만들고,
    `guard=True`는 `spend()`/`revoke()`(음수 `delta`)라 기존 로트를 `lot_order`대로 잠가
    깎는다. `kind`는 `grant()`가 이 분기를 탈 때만 넘어오는 지급 종류라 로트 `kind`로 그대로
    재사용한다(`db/models/clover.py`의 `CloverLot` docstring — 로트 kind는 지급 종류의 부분
    집합이다).

    원장 행을 로트보다 먼저 flush 한다 — 차감 배분(`record_allocations`)이 원장 id 를 FK 로 잡는데, 이 저장소는
    `relationship()` 을 쓰지 않아 단위작업의 INSERT 정렬에 기댈 수 없다.
    """
    statement = update(User).where(User.id == user_id)
    if guard:
        statement = statement.where(User.clover_balance >= -delta)

    balance_after = await db.scalar(
        statement.values(clover_balance=User.clover_balance + delta).returning(User.clover_balance)
    )
    if balance_after is None:
        return None

    ledger = CloverLedger(
        user_id=user_id,
        amount=delta,
        balance_after=balance_after,
        kind=kind,
        idempotency_key=idempotency_key,
    )
    db.add(ledger)
    # 여기서 flush하는 이유: 멱등키 중복의 `IntegrityError`가 **호출한 자리에서** 터져야
    # 라우트가 409로 번역할 수 있다. 커밋까지 미루면 예외가 커밋 지점에서 나와 어느 연산이
    # 중복이었는지 호출부가 알 수 없다. 배분이 가리킬 원장 행도 이 flush 로 먼저 생긴다.
    await db.flush()

    if guard:
        await _consume_lots(
            db,
            user_id=user_id,
            amount=-delta,
            order=lot_order,
            spend_ledger_id=ledger.id if record_allocations else None,
        )
    else:
        db.add(
            CloverLot(
                user_id=user_id,
                granted_amount=delta,
                remaining=delta,
                expires_at=expires_at,
                kind=kind,
            )
        )
    await db.flush()
    return ledger


async def spend(
    db: AsyncSession, *, user_id: uuid.UUID, amount: int, kind: CloverKind
) -> CloverSpend | None:
    """조건부 UPDATE + 원장 INSERT. 잔액이 모자라면 **아무것도 하지 않고 `None`**.

    성공하면 차감 후 잔액과 원장 id 를 돌려준다. 환급은 그 id 로 이 차감의 배분을 찾아 깎은 로트로 되돌린다. **커밋은 호출자가 한다** — 게이트만 별도 트랜잭션이
    필요하고 어드민·출석·탈퇴는 호출자 세션에 얹혀야 조치와 원장이
    같이 커밋되거나 같이 롤백된다. 그래서 커밋 정책을 이 함수가 갖지 않는다.

    총액 CAS가 통과한 뒤 로트를 만료 임박 우선
    순서로 잠가 깎는다. 만료 필터는 걸지 않는다 — 만료의 진실은 배치뿐이다. 로트
    합계가 모자라면 `CloverLotShortfallError`가 나 총액 CAS까지 롤백된다.
    """
    ledger = await _apply(
        db,
        user_id=user_id,
        delta=-amount,
        kind=kind,
        idempotency_key=None,
        guard=True,
        lot_order="expiry_first",
        record_allocations=True,
    )
    if ledger is None:
        return None
    return CloverSpend(balance_after=ledger.balance_after, ledger_id=ledger.id)


async def grant(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: CloverKind,
    idempotency_key: str | None = None,
    expires_at: datetime | None = None,
) -> int:
    """가드 없는 증가 + 원장 INSERT + 로트 1행 생성. 증가 후 잔액을 돌려준다. **커밋은
    호출자가 한다.**

    `idempotency_key`가 중복이면 `IntegrityError`가 그대로 올라온다 — 라우트가 409로 번역한다.
    유니크 인덱스가 그걸 막는 유일한 수단이고, 더블클릭·재시도가
    곧 중복 지급이라 어드민 경로는 반드시 키를 넣는다.

    🔴 `expires_at`은 호출 지점이 명시해야 한다 — 만료가 붙는 지급은 출석·미션·기존
    잔액 백필뿐이고, 어드민 지급과 환불은 `None`(무기한)이다. 기본값을 `None`으로 둔 이유는
    어드민 지급·환불 호출부가 만료를 안 넘겨 기본값에 기대기 때문이다 — 출석·미션(둘 다
    `clover/router.py`)은 `core.clover.earned_lot_expiry`로 계산한 값을 명시적으로 넘긴다.
    """
    ledger = await _apply(
        db,
        user_id=user_id,
        delta=amount,
        kind=kind,
        idempotency_key=idempotency_key,
        guard=False,
        expires_at=expires_at,
    )
    # 가드가 없으므로 `None`은 "유저가 없다"는 뜻뿐이다. 호출부는 전부 인증·조회를 이미 마친
    # 뒤라 도달할 수 없고, 도달했다면 그건 500이 맞다.
    if ledger is None:
        raise ValueError(f"클로버를 지급할 유저를 찾지 못했다: {user_id}")
    return ledger.balance_after


async def revoke(
    db: AsyncSession, *, user_id: uuid.UUID, amount: int, idempotency_key: str | None = None
) -> int | None:
    """어드민 회수. `spend`와 같은 조건부 UPDATE이고 `kind`만 `admin_revoke`다.

    **무료 로트만 회수한다.** 구매로 생긴 유료·보너스 로트는 결제 환불 경로로만 회수한다 — 어드민 수동 회수가 그걸
    깎으면 그 구매의 남은 유료 수량(환불 견적의 바탕)이 결제 기록 밖에서 줄어든다. 그래서 판정도 총액이 아니라 무료
    로트 합이다: 그 합이 모자라면 `None` — 라우트가 422로 번역한다. 총액 CAS 만으로 판정하면 구매 로트가 있는
    사용자에게서 총액은 통과하고 로트가 모자라 `CloverLotShortfallError` 500 이 난다.

    판정 전에 사용자 행을 `FOR UPDATE` 로 잠근다 — 합을 읽은 뒤 차감이 끼어들어 무료 로트가 줄면 판정이 낡는다. 이
    잠금은 `_apply` 의 UPDATE 와 같은 행이라 락 순서(users → clover_lots)가 그대로다.

    **음수로 내려가지 않는다**: 오지급 회수는 이미 쓴 만큼을 빚으로 남기지 않는다는 뜻이다.

    🔴 로트 소진 순서가 `spend`(만료 임박 우선)와 **정반대**다 — 회수는 최근 지급분부터
    (`created_at DESC`). 회수의 실제 쓰임이 "방금 잘못 준 걸 도로 빼는 것"이라 최근
    로트부터 빼야 오지급한 그 로트가 깨끗하게 되돌려진다.
    """
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    revocable = await db.scalar(
        select(func.coalesce(func.sum(CloverLot.remaining), 0)).where(
            CloverLot.user_id == user_id,
            CloverLot.remaining > 0,
            CloverLot.kind.not_in(PURCHASE_LOT_KINDS),
        )
    )
    if revocable is None or revocable < amount:
        return None
    ledger = await _apply(
        db,
        user_id=user_id,
        delta=-amount,
        kind="admin_revoke",
        idempotency_key=idempotency_key,
        guard=True,
        lot_order="recency_first",
    )
    return None if ledger is None else ledger.balance_after


async def burn_all(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """탈퇴 시 남은 잔액 전부를 소멸시킨다. 소멸된 금액을 돌려준다.

    🔴 **금액을 인자로 받지 않는 것이 이 함수의 요점이다.** 소멸은 "얼마를 쓴다"가 아니라
    "남은 걸 없앤다"라 `spend(amount=…)`로 표현하면 두 가지가 틀어진다 — 호출자가 읽어 둔
    잔액이 낡았을 때 ① 조건부 가드(`WHERE clover_balance >= amount`)가 걸려 **아무것도 안
    지워지고** ② 반환값을 버리면 그 실패가 조용하다. 탈퇴 라우트는 `user`를 초입에서 로드하고
    그 뒤 채팅방·메시지·asset 삭제를 거치므로 그 창이 실제로 존재한다.

    잔액이 0이면 아무것도 하지 않는다 — 의미 없는 0원 원장 행을 만들지 않는다. `WHERE
    clover_balance > 0`이 그 규칙과 "유저가 없다"를 한꺼번에 처리한다(둘 다 행이 안 돌아온다).

    🔴 **`_apply`를 쓰지 않고 자기 UPDATE를 갖는다.** `_apply`는 **상대 증감**
    (`clover_balance + delta`)이라 소멸에는 맞지 않는다 — 읽어 둔 값으로 빼는 형태가 되어,
    그 사이 차감이 커밋되면 `90 - 100 = -10`으로 `ck_users_clover_balance_non_negative`에
    걸려 **탈퇴 요청이 500이 된다**. `guard=False`는 `WHERE` 조건을 빼는 것이지 대입을
    절대값으로 만들지 않는다(앞선 판본의 docstring이 그 둘을 혼동했다).

    소멸은 **절대 대입**(`SET clover_balance = 0`)이고 소멸액은 `RETURNING OLD`로 받는다 —
    읽기와 쓰기가 한 문장이라 그 사이에 낄 창이 **없다**. PostgreSQL 18의 문법이고 CI·dev·prod가
    전부 18이다(`docker-compose.*.yml`, `api.yml`). `NEW`는 항상 0이라 볼 것이 없다.

    🔴 그 유저의 미소진 로트도 함께 0으로 만든다 — 안 그러면
    탈퇴 후에도 "만료 예정"으로 남은 유령 로트가 생긴다. `revoke`의 **부분** 무효화와 달리
    **전량** 무효화라 `_apply`/`_consume_lots`를 쓰지 않는다. 잔액이 이미 0이었어도(`burned`가
    `None`이어도) 실행한다 — 불변식이 이미 깨진 상태에서도 유령 로트를 남기지 않기 위해서다.
    """
    # `literal_column`에 타입을 주는 이유: 안 주면 `.returning()`이 `Update`를 그대로 돌려
    # `db.scalar`가 `-> None` 오버로드로 잡혀 mypy strict가 막는다.
    result = await db.execute(
        update(User)
        .where(User.id == user_id, User.clover_balance > 0)
        .values(clover_balance=0)
        .returning(literal_column("OLD.clover_balance", Integer))
    )
    burned = result.scalar_one_or_none()

    await db.execute(
        update(CloverLot)
        .where(CloverLot.user_id == user_id, CloverLot.remaining > 0)
        .values(remaining=0)
    )

    if burned is None:
        return 0
    db.add(
        CloverLedger(
            user_id=user_id,
            amount=-burned,
            balance_after=0,
            kind="withdrawal_burn",
            idempotency_key=None,
        )
    )
    # `_apply`와 같은 이유로 여기서 flush한다 — 예외가 이 자리에서 터져야 호출부가 안다.
    await db.flush()
    return int(burned)


async def spend_in_new_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: CloverKind,
) -> CloverSpend | None:
    """**게이트 전용**. 요청 스코프 세션의 커밋 타이밍과 무관하게
    즉시 커밋한다.

    채팅 4경로의 커밋 시점이 제각각이라(전송·편집은 생성 **전**, 재생성은 생성 **후**,
    빌더 미리보기는 `db.commit()`이 **0건**) 요청 세션에 얹으면 같은 차감이 경로마다 다르게
    동작한다 — 미리보기는 영원히 공짜가 된다.

    🔴 `session_factory`는 반드시 `Depends(get_session_factory)`로 받은 것이어야 한다.
    모듈에서 `async_session_factory`를 직접 import하면 `tests/conftest.py`의 오버라이드를 안
    타서 **테스트가 공유 DB를 건드린다.**
    """
    async with session_factory() as session:
        spent = await spend(session, user_id=user_id, amount=amount, kind=kind)
        if spent is None:
            return None
        await session.commit()
        return spent


async def refund_spend(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    spend_ledger_id: uuid.UUID | None,
    amount: int,
    kind: CloverKind,
) -> int | None:
    """차감을 되돌린다. 환급 후 잔액을 돌려준다. **커밋은 호출자가 한다.**

    `spend_ledger_id` 가 있으면 그 차감의 배분을 깎은 순서의 **역순**(`seq DESC`)으로 되돌린다 — 차감은 무료 →
    보너스 → 유료 순으로 깎으므로, 부분 환급은 유료부터 돌려준다. 무료부터 돌려주면 못 받은 서비스 몫을 8일짜리
    무료로 돌려주고 현금으로 산 유료는 쓴 채로 남아, 그 구매의 환불 견적이 실제로 받은 서비스보다 작아진다. 역순은
    "안 쓴 꼬리"를 되돌리는 것이라 그 차감이 없었을 때와 가장 가깝다.

    이미 만료된 로트에도 그대로 되돌린다(소설화는 몇 시간 뒤에 환급한다). 새 만료를 단 새 로트로 주면 만료된 무료
    클로버에 새 수명이 붙어 차감이 없었을 때보다 많이 갖게 된다. 돌아간 만료분은 다음 만료 배치가 다시 태운다.

    아직 돌려주지 않은 양보다 많이 돌려달라면 `CloverRefundExceedsSpendError` — 같은 차감을 두 번 환급하려 했다는
    뜻이라 롤백시킨다.

    `spend_ledger_id` 가 `None` 이면(배분을 남기기 전의 차감, 배분을 모르는 옛 코드가 만든 소설화 작업) 예전처럼
    무기한 새 로트(무료 등급)로 돌려준다.

    **탈퇴한 회원이면 아무것도 하지 않고 `None`.** 탈퇴가 잔액·로트를 이미 소멸시켰는데 늦게 도착한 환급이 그 위에
    잔액을 되살리면 지울 수 없는 잔액이 남는다. 탈퇴 판정은 잔액 UPDATE 의 조건(`deleted_at IS NULL`)이라 탈퇴와
    경합해도 둘 중 하나만 이긴다.

    락 순서는 users → clover_spend_allocations → clover_lots 다. 차감은 users → clover_lots 이고 배분은 INSERT 만
    하므로 순환이 없다.
    """
    balance_after = await db.scalar(
        update(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .values(clover_balance=User.clover_balance + amount)
        .returning(User.clover_balance)
    )
    if balance_after is None:
        logger.info("탈퇴한 회원(%s)의 클로버 환급은 적용하지 않는다", user_id)
        return None

    if spend_ledger_id is None:
        db.add(CloverLot(user_id=user_id, granted_amount=amount, remaining=amount, expires_at=None, kind=kind))
    else:
        allocations = (
            await db.scalars(
                select(CloverSpendAllocation)
                .where(CloverSpendAllocation.spend_ledger_id == spend_ledger_id)
                .order_by(CloverSpendAllocation.seq.desc())
                .with_for_update()
            )
        ).all()
        # 남의 로트로는 돌려주지 않는다 — 사용자 조건에 걸러진 배분은 환급 가능량에서 빠져 아래 부족 예외로 떨어진다.
        lots = {
            lot.id: lot
            for lot in (
                await db.scalars(
                    select(CloverLot)
                    .where(
                        CloverLot.id.in_([allocation.lot_id for allocation in allocations]),
                        CloverLot.user_id == user_id,
                    )
                    .order_by(CloverLot.id)
                    .with_for_update()
                )
            ).all()
        }
        left = amount
        for allocation in allocations:
            lot = lots.get(allocation.lot_id)
            if left <= 0 or lot is None:
                continue
            take = min(allocation.amount - allocation.refunded_amount, left)
            allocation.refunded_amount += take
            lot.remaining += take
            left -= take
        if left > 0:
            raise CloverRefundExceedsSpendError(
                f"user {user_id}: 차감 {spend_ledger_id} 의 남은 환급 가능량보다 {left} 많이 돌려달라고 했다"
            )

    db.add(
        CloverLedger(
            user_id=user_id,
            amount=amount,
            balance_after=balance_after,
            kind=kind,
            idempotency_key=None,
        )
    )
    await db.flush()
    return int(balance_after)


async def refund_spend_in_new_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    spend_ledger_id: uuid.UUID | None,
    amount: int,
    kind: CloverKind,
) -> None:
    """`refund_spend` 를 자기 트랜잭션에서 커밋한다. 🔴 **절대 예외를 밖으로 내지 않는다.**

    호출 자리가 SSE 제너레이터 본문이거나 이미 실패가 확정된 요청의 정리라, 예외가 새면 이미 시작된 스트림을 뚫고
    나가 태스크가 취소되고 **망가진 asyncpg 커넥션이 풀로 반환돼 무관한 요청이 500**이 된다(`core/rate_limit_gate.py`
    의 모듈 docstring 이 같은 이유로 `Depends`만 쓰라고 적는다).

    실패는 `logger.warning` + `capture_dependency_failure(dependency="clover")`로만 남는다 — 자동 재시도가 없어 이게
    유일한 발견 수단이다. 남는 결과는 "그 요청의 차감이 되돌아가지 않은 것"이고 보정은 어드민 지급이다.
    """
    try:
        async with session_factory() as session:
            await refund_spend(session, user_id=user_id, spend_ledger_id=spend_ledger_id, amount=amount, kind=kind)
            await session.commit()
    # `BaseException`이 아니라 `Exception`인 것이 중요하다 — `asyncio.CancelledError`까지
    # 삼키면 클라이언트가 끊은 스트림이 정리되지 않는다.
    except Exception as exc:
        logger.warning("클로버 환불 실패 — 그 요청의 차감이 남는다", exc_info=True)
        capture_dependency_failure(exc, dependency="clover")


async def refund_in_new_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: CloverKind,
) -> None:
    """차감을 되돌린다. 🔴 **절대 예외를 밖으로 내지 않는다.**

    호출 자리가 SSE 제너레이터 본문이라 예외가 새면 이미 시작된
    스트림을 뚫고 나가 태스크가 취소되고, **망가진 asyncpg 커넥션이 풀로 반환돼 무관한 요청이
    500**이 된다(`core/rate_limit_gate.py`의 모듈 docstring이 같은 이유로 `Depends`만 쓰라고
    적는다).

    실패는 `logger.warning` + `capture_dependency_failure(dependency="clover")`로만 남는다 —
    자동 재시도를 만들지 않기로 했으므로 이게 유일한 발견
    수단이다. 남는 결과는 "그 요청의 차감이 되돌아가지 않은 것"이고 보정은 어드민 지급이다.
    """
    try:
        async with session_factory() as session:
            await grant(session, user_id=user_id, amount=amount, kind=kind)
            await session.commit()
    # `BaseException`이 아니라 `Exception`인 것이 중요하다 — `asyncio.CancelledError`까지
    # 삼키면 클라이언트가 끊은 스트림이 정리되지 않는다.
    except Exception as exc:
        logger.warning("클로버 환불 실패 — 그 요청의 차감이 남는다", exc_info=True)
        capture_dependency_failure(exc, dependency="clover")


def kst_today(now: datetime) -> date:
    """tz-aware `now`를 KST 날짜로 바꾼다. `core/rate_limit.py`의 `KST` 고정 오프셋을 쓴다.

    naive `now`는 거부한다 — `seconds_until_kst_midnight`와 같은 이유다. `astimezone`이
    naive를 **프로세스 로컬 시간**으로 재해석해서 같은 입력이 컨테이너 TZ마다 다른 날짜를 낸다.
    출석·차감 확인이 이 날짜로 판정되므로, 틀리면 하루에 두 번 지급되거나 하루를 건너뛴다.

    `now`를 인자로 받는 이유는 테스트다 — 이 저장소에 시간을 얼리는 수단이 0건이라
    (`freezegun`·`time-machine` 전부 없다) 경계 검증은 리터럴 주입으로만 된다.
    """
    if now.tzinfo is None:
        raise ValueError("tz-aware `now`가 필요하다 — `datetime.now(UTC)`를 넘길 것")
    return now.astimezone(KST).date()


def is_same_kst_day(last: date | None, now: datetime) -> bool:
    """`last`가 `now`와 같은 KST 날짜인가. `last`가 `None`(한 번도 없음)이면 `False`."""
    return last == kst_today(now)


def earned_lot_expiry(now: datetime) -> datetime:
    """출석·미션 지급이 만드는 로트의 만료 시각 — 지급일(KST) 자정 + 8일.
    `kst_today`를 재사용해 날짜를 구하고(naive `now` 거부도 그쪽에
    위임한다), 그 날의 KST 자정에 8일을 더한다.

    🔴 7이 아니라 8인 이유: 자정으로 정규화하면 "+7일"은 실제 보유 기간을 6~7일로 만든다
    (늦게 지급될수록 짧아진다) — "7일 유효기간" 고지와 어긋난다. "+8일"이면 보유 기간이
    7~8일이라 누구도 7일보다 적게 받지 않는다.

    🔴 마이그레이션(`cf74d6d53561_clover_lots.py`)의 `_legacy_lot_expiry`가 같은 계산을
    별도로 갖는다 — 마이그레이션이 `api.*`를 import하지 않는 것이 이 저장소 관례라
    사본이 둘인 것은 의도다. **다만 두 값은 반드시 같아야 한다** — 한쪽만 고치면 백필
    로트와 출석·미션 로트의 유효기간 규칙이 갈린다.
    """
    midnight_kst = datetime.combine(kst_today(now), time.min, tzinfo=KST)
    return midnight_kst + timedelta(days=8)
