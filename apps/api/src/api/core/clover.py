"""클로버(재화) 서비스 — 잔액 판정과 원장 기록.

`core/`에 두는 이유는 게이트(`core/rate_limit_gate.py`)가 이걸 부르기 때문이다. HTTP 표면은
별도 패키지(`clover/router.py`)로 가른다.

**불변식은 `users.clover_balance`의 조건부 UPDATE 하나다**(clover-goal-prompt.md CL-4). 원장은
같은 트랜잭션에 얹는 기록이지 판정 근거가 아니다 — 순서를 뒤집어 원장을 먼저 INSERT하고 잔액을
`SUM()`으로 계산하면 동시 트랜잭션 둘이 서로의 미커밋 행을 못 봐서 **둘 다 통과한다**.
"""

import logging
import uuid
from datetime import date, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.rate_limit import KST
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.clover import CloverLedger

logger = logging.getLogger(__name__)

# clover-goal-prompt.md CL-10~CL-12. **정책값이지 실측 원가가 아니다**(CL-15) — 턴당 원가는
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
]


async def _apply(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    delta: int,
    kind: CloverKind,
    idempotency_key: str | None,
    guard: bool,
) -> int | None:
    """잔액 UPDATE + 원장 INSERT를 한 트랜잭션에 넣는다. **커밋하지 않는다.**

    `guard=True`면 `WHERE clover_balance >= -delta`를 걸어 음수로 내려가지 않게 한다 — 이
    WHERE가 없으면 동시 요청 둘이 같은 잔액을 읽고 둘 다 통과한다.

    🔴 판정에 `.rowcount`를 쓰지 않는다 — mypy strict에서 `Result[Any]`가 그 속성을 노출하지
    않는다(`admin/users.py:411-412`). `RETURNING clover_balance`가 **행을 돌려줬는가**로 가른다.
    선례는 `admin/users.py:416-423`.
    """
    statement = update(User).where(User.id == user_id)
    if guard:
        statement = statement.where(User.clover_balance >= -delta)

    balance_after = await db.scalar(
        statement.values(clover_balance=User.clover_balance + delta).returning(User.clover_balance)
    )
    if balance_after is None:
        return None

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
    필요하고(clover-techspec.md CT-4) 어드민·출석·탈퇴는 호출자 세션에 얹혀야 조치와 원장이
    같이 커밋되거나 같이 롤백된다. 그래서 커밋 정책을 이 함수가 갖지 않는다.
    """
    return await _apply(
        db, user_id=user_id, delta=-amount, kind=kind, idempotency_key=None, guard=True
    )


async def grant(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: CloverKind,
    idempotency_key: str | None = None,
) -> int:
    """가드 없는 증가 + 원장 INSERT. 증가 후 잔액을 돌려준다. **커밋은 호출자가 한다.**

    `idempotency_key`가 중복이면 `IntegrityError`가 그대로 올라온다 — 라우트가 409로 번역한다.
    유니크 인덱스가 그걸 막는 유일한 수단이고(clover-goal-prompt.md CL-8), 더블클릭·재시도가
    곧 중복 지급이라 어드민 경로는 반드시 키를 넣는다.
    """
    balance_after = await _apply(
        db, user_id=user_id, delta=amount, kind=kind, idempotency_key=idempotency_key, guard=False
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
    """
    return await _apply(
        db,
        user_id=user_id,
        delta=-amount,
        kind="admin_revoke",
        idempotency_key=idempotency_key,
        guard=True,
    )


async def burn_all(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """탈퇴 시 남은 잔액 전부를 소멸시킨다(clover-goal-prompt.md CL-32). 소멸된 금액을 돌려준다.

    🔴 **금액을 인자로 받지 않는 것이 이 함수의 요점이다.** 소멸은 "얼마를 쓴다"가 아니라
    "남은 걸 없앤다"라 `spend(amount=…)`로 표현하면 두 가지가 틀어진다 — 호출자가 읽어 둔
    잔액이 낡았을 때 ① 조건부 가드(`WHERE clover_balance >= amount`)가 걸려 **아무것도 안
    지워지고** ② 반환값을 버리면 그 실패가 조용하다. 탈퇴 라우트는 `user`를 초입에서 로드하고
    그 뒤 채팅방·메시지·asset 삭제를 거치므로 그 창이 실제로 존재한다.

    잔액이 0이면 아무것도 하지 않는다 — 의미 없는 0원 원장 행을 만들지 않는다.

    ⚠️ 남은 창: 아래 `SELECT`와 `_apply`의 `UPDATE` 사이에 다른 트랜잭션의 차감이 커밋되면
    원장 `amount`가 그만큼 과대 기재된다(**잔액은 그래도 정확히 0이 된다** — `_apply`가
    `guard=False`라 무조건 덮는다). 같은 트랜잭션의 인접한 두 문장이라 창이 극히 좁고, 이걸
    닫으려면 `FOR UPDATE`(이 저장소 선례 0건)가 필요하며 검증에도 독립 커넥션이 있어야 한다 —
    S11의 `independent_session_factory` 항목으로 넘긴다.
    """
    current = await db.scalar(select(User.clover_balance).where(User.id == user_id))
    if not current:
        return 0
    await _apply(
        db,
        user_id=user_id,
        delta=-current,
        kind="withdrawal_burn",
        idempotency_key=None,
        guard=False,
    )
    return current


async def spend_in_new_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: CloverKind,
) -> int | None:
    """clover-techspec.md CT-4 — **게이트 전용**. 요청 스코프 세션의 커밋 타이밍과 무관하게
    즉시 커밋한다.

    채팅 4경로의 커밋 시점이 제각각이라(전송·편집은 생성 **전**, 재생성은 생성 **후**,
    빌더 미리보기는 `db.commit()`이 **0건**) 요청 세션에 얹으면 같은 차감이 경로마다 다르게
    동작한다 — 미리보기는 영원히 공짜가 된다(clover-goal-prompt.md CL-9).

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

    호출 자리가 SSE 제너레이터 본문이라(clover-techspec.md §3-5) 예외가 새면 이미 시작된
    스트림을 뚫고 나가 태스크가 취소되고, **망가진 asyncpg 커넥션이 풀로 반환돼 무관한 요청이
    500**이 된다(`core/rate_limit_gate.py`의 모듈 docstring이 같은 이유로 `Depends`만 쓰라고
    적는다).

    실패는 `logger.warning` + `capture_dependency_failure(dependency="clover")`로만 남는다 —
    자동 재시도를 만들지 않기로 했으므로(clover-goal-prompt.md CL-23) 이게 유일한 발견
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
