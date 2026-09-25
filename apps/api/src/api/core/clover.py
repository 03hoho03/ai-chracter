"""클로버(재화) 서비스 — 잔액 판정과 원장 기록.

`core/`에 두는 이유는 게이트(`core/rate_limit_gate.py`)가 이걸 부르기 때문이다. HTTP 표면은
별도 패키지(`clover/router.py`)로 가른다.

**불변식은 `users.clover_balance`의 조건부 UPDATE 하나다**. 원장은
같은 트랜잭션에 얹는 기록이지 판정 근거가 아니다 — 순서를 뒤집어 원장을 먼저 INSERT하고 잔액을
`SUM()`으로 계산하면 동시 트랜잭션 둘이 서로의 미커밋 행을 못 봐서 **둘 다 통과한다**.
"""

import logging
import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import Integer, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.rate_limit import KST
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot

logger = logging.getLogger(__name__)

# **정책값이지 실측 원가가 아니다** — 턴당 원가는
# 8.3~91.1원으로 11배 흔들리고 그 분포를 측정한 적이 없다.
# 게이트 함수는 이 이름들을 **호출 시점에 모듈 전역으로** 읽는다 — 기본 인자로 캡처하면
# `monkeypatch.setattr`가 통하지 않는다(`core/rate_limit.py`의 상한 상수와 같은 규칙).
CHAT_TURN_COST = 10
IMAGE_UNIT_COST = 30
ATTENDANCE_GRANT_AMOUNT = 100

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
]

# 소진은 만료 임박 우선, 회수는 최근 지급분부터 — 둘 다
# `_apply`의 음수-delta 분기(`guard=True`)를 공유하지만 로트를 잡는 정렬이 정반대다.
_LotOrder = Literal["expiry_first", "recency_first"]


class CloverLotShortfallError(Exception):
    """총액 CAS(`users.clover_balance`)는 통과했는데
    로트 합계가 부족한 비정상 상태(Σ 불변식이 이미 깨졌다는 뜻, 예컨대 백필 누락). 이 예외를
    잡지 않고 그대로 낸다 — 트랜잭션이 롤백돼 총액 CAS까지 되돌아가는 것이 목적이다.
    """


async def _consume_lots(
    db: AsyncSession, *, user_id: uuid.UUID, amount: int, order: _LotOrder
) -> None:
    """로트를 `SELECT ... FOR UPDATE`로 잠가 `amount`만큼 순서대로 깎는다.

    호출 전에 총액 CAS가 이미 통과했다는 전제다(락 순서는 `_apply`가 users를 먼저
    잠근 뒤에야 이 함수가 clover_lots를 잠그는 순서로 고정된다). 여기서 부족이 나오면
    잔액 자체가 모자란 정상 부족이 아니라 Σ 불변식이 깨진 비정상 상태라
    `CloverLotShortfallError`를 던진다.

    `order`가 정렬을 가른다 — `expiry_first`는 소진, `recency_first`는 회수다.
    만료 여부로 거르지 않는다 — `remaining > 0`만 본다. 만료의 진실은 배치뿐이다.
    """
    order_by: tuple[object, ...]
    if order == "expiry_first":
        order_by = (CloverLot.expires_at.asc().nulls_last(), CloverLot.created_at.asc())
    else:
        order_by = (CloverLot.created_at.desc(),)

    lots = (
        await db.scalars(
            select(CloverLot)
            .where(CloverLot.user_id == user_id, CloverLot.remaining > 0)
            .order_by(*order_by)
            .with_for_update()
        )
    ).all()

    left = amount
    for lot in lots:
        if left <= 0:
            break
        take = min(lot.remaining, left)
        lot.remaining -= take
        left -= take

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
) -> int | None:
    """잔액 UPDATE + 원장 INSERT를 한 트랜잭션에 넣는다. **커밋하지 않는다.**

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
    """
    statement = update(User).where(User.id == user_id)
    if guard:
        statement = statement.where(User.clover_balance >= -delta)

    balance_after = await db.scalar(
        statement.values(clover_balance=User.clover_balance + delta).returning(User.clover_balance)
    )
    if balance_after is None:
        return None

    if guard:
        await _consume_lots(db, user_id=user_id, amount=-delta, order=lot_order)
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

    db.add(
        CloverLedger(
            user_id=user_id,
            amount=delta,
            balance_after=balance_after,
            kind=kind,
            idempotency_key=idempotency_key,
        )
    )
    # 여기서 flush하는 이유: 멱등키 중복의 `IntegrityError`가 **호출한 자리에서** 터져야
    # 라우트가 409로 번역할 수 있다. 커밋까지 미루면 예외가 커밋 지점에서 나와 어느 연산이
    # 중복이었는지 호출부가 알 수 없다.
    await db.flush()
    return balance_after


async def spend(
    db: AsyncSession, *, user_id: uuid.UUID, amount: int, kind: CloverKind
) -> int | None:
    """조건부 UPDATE + 원장 INSERT. 잔액이 모자라면 **아무것도 하지 않고 `None`**.

    성공하면 차감 후 잔액을 돌려준다. **커밋은 호출자가 한다** — 게이트만 별도 트랜잭션이
    필요하고 어드민·출석·탈퇴는 호출자 세션에 얹혀야 조치와 원장이
    같이 커밋되거나 같이 롤백된다. 그래서 커밋 정책을 이 함수가 갖지 않는다.

    총액 CAS가 통과한 뒤 로트를 만료 임박 우선
    순서로 잠가 깎는다. 만료 필터는 걸지 않는다 — 만료의 진실은 배치뿐이다. 로트
    합계가 모자라면 `CloverLotShortfallError`가 나 총액 CAS까지 롤백된다.
    """
    return await _apply(
        db,
        user_id=user_id,
        delta=-amount,
        kind=kind,
        idempotency_key=None,
        guard=True,
        lot_order="expiry_first",
    )


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
    balance_after = await _apply(
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
    if balance_after is None:
        raise ValueError(f"클로버를 지급할 유저를 찾지 못했다: {user_id}")
    return balance_after


async def revoke(
    db: AsyncSession, *, user_id: uuid.UUID, amount: int, idempotency_key: str | None = None
) -> int | None:
    """어드민 회수. `spend`와 같은 조건부 UPDATE이고 `kind`만 `admin_revoke`다.

    잔액이 모자라면 `None` — 라우트가 422로 번역한다. **음수로 내려가지 않는다**: 오지급 회수는
    이미 쓴 만큼을 빚으로 남기지 않는다는 뜻이고, 그게 유상화 시점에 환불 계산을 단순하게 둔다.

    🔴 로트 소진 순서가 `spend`(만료 임박 우선)와 **정반대**다 — 회수는 최근 지급분부터
    (`created_at DESC`). 회수의 실제 쓰임이 "방금 잘못 준 걸 도로 빼는 것"이라 최근
    로트부터 빼야 오지급한 그 로트가 깨끗하게 되돌려진다.
    """
    return await _apply(
        db,
        user_id=user_id,
        delta=-amount,
        kind="admin_revoke",
        idempotency_key=idempotency_key,
        guard=True,
        lot_order="recency_first",
    )


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
) -> int | None:
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
        balance_after = await spend(session, user_id=user_id, amount=amount, kind=kind)
        if balance_after is None:
            return None
        await session.commit()
        return balance_after


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
