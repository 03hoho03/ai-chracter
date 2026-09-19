"""clover-techspec.md CT-9·CT-10 — 클로버의 HTTP 표면.

`core/clover.py`가 잔액 판정과 원장을 갖고, 이 파일은 그 위의 `/me` 라우트 셋뿐이다.

🔴 **`auth`의 `me_router`에 얹지 않는다** — 그러면 auth 패키지가 재화를 알게 된다. `/me`
prefix를 실제로 가진 본보기는 `inquiry/router.py:22`·`chat/router.py:122`·`assets/router.py:46`
셋이다(clover-techspec.md CT-9).

**레이트리밋 게이트는 붙이지 않는다**(clover-techspec.md §4-1) — 잔액 조회·출석은 LLM·GPU를
태우지 않는다. `require_legal_consent`는 다른 `/me` 라우트와 같게 붙인다.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover.schemas import CloverAttendanceResponse, CloverBalanceResponse
from api.core.clover import ATTENDANCE_GRANT_AMOUNT, grant, is_same_kst_day, kst_today
from api.db.models.auth import User
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.session.dependencies import get_current_user_id

me_router = APIRouter(prefix="/me", tags=["clover"])


async def _require_active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """`require_legal_consent`가 같은 세션으로 이미 조회한 행이라 여기서는 identity map 히트다.

    그래도 한 번 더 확인하는 이유는 탈퇴 여부 판정을 이 파일이 갖기 위해서다 — 게이트가
    빠지거나 순서가 바뀌어도 라우트가 스스로 막는다.
    """
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


@me_router.get("/clover", dependencies=[Depends(require_legal_consent)])
async def get_clover_balance(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CloverBalanceResponse:
    """🔴 **부작용이 없다**(clover-techspec.md CT-10) — 출석 지급은 전용 POST다.

    GET이 지급까지 하면 프리페치·재조회가 곧 지급이 되고, 그때 멱등을 보장하는 것은
    `clover_attendance_granted_on` 하나뿐이라 실패 모드가 조용해진다.
    """
    user = await _require_active_user(db, user_id)
    now = datetime.now(UTC)
    return CloverBalanceResponse(
        balance=user.clover_balance,
        spend_confirmed_today=is_same_kst_day(user.clover_spend_confirmed_on, now),
        attendance_claimable=not is_same_kst_day(user.clover_attendance_granted_on, now),
    )


@me_router.post("/clover/attendance", dependencies=[Depends(require_legal_consent)])
async def claim_clover_attendance(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CloverAttendanceResponse:
    """일일 출석 지급. 오늘(KST) 이미 받았으면 `granted=false`이고 **에러가 아니다.**

    멱등이 **두 겹**이다. 둘이 막는 것이 다르다:

    - `clover_attendance_granted_on` 검사 — **순차 재호출**을 막는다(FE가 여러 번 부르는 경우).
      빠른 길이고, 이것만으로는 동시 요청을 못 막는다.
    - 원장 **멱등키의 유니크 인덱스** — **동시 요청**을 막는다. 아래 `except` 참조.

    🔴 **지급과 멱등 표지가 한 트랜잭션이다.** 둘을 갈라 커밋하면 그 사이에서 실패할 때
    "돈은 나갔는데 표지가 없는" 상태가 남고, 재시도가 곧 이중 지급이 된다 — S4·S5가 두 번
    겪은 "자원을 커밋한 뒤 되돌릴 수 있는 첫 지점까지의 구간"이 여기서는 **아예 생기지 않는다.**
    ⚠️ 그건 **원자성** 논증이고 **격리**는 논증하지 않는다 — 격리는 위의 멱등키가 맡는다.
    """
    user = await _require_active_user(db, user_id)
    now = datetime.now(UTC)
    today = kst_today(now)
    if is_same_kst_day(user.clover_attendance_granted_on, now):
        return CloverAttendanceResponse(granted=False, balance=user.clover_balance)

    try:
        # SAVEPOINT 안에서 시도한다 — 유니크 위반이 나도 **바깥 트랜잭션은 살아 있어야**
        # 아래에서 잔액을 다시 읽을 수 있다. `db.rollback()`이면 요청 전체가 날아간다.
        # 선례: `auth/router.py`의 가입이 같은 이유로 `begin_nested()`를 쓴다.
        async with db.begin_nested():
            balance_after = await grant(
                db,
                user_id=user_id,
                amount=ATTENDANCE_GRANT_AMOUNT,
                kind="attendance_grant",
                idempotency_key=f"attendance:{user_id}:{today}",
            )
    except IntegrityError:
        # 🔴 동시 요청의 둘째다. 위 `is_same_kst_day` 검사는 **격리를 논증하지 못한다** —
        # 둘째는 첫째가 커밋하기 전에 표지를 읽어 못 보고 통과하고, `grant`는 `guard=False`라
        # 조건 없는 `WHERE users.id = :u`만 내므로 락이 풀린 뒤 재평가에서도 그대로 통과한다
        # (`spend`가 안전한 것은 `WHERE clover_balance >= -delta`가 재평가에서 거짓이 되기
        # 때문이고, 지급에는 그 자리가 없다).
        # 그래서 멱등을 DB가 강제하게 둔다 — `ux_clover_ledger_idempotency_key`가
        # 정확히 이 목적으로 있다(clover-goal-prompt.md CL-8). 키는 유저+KST날짜라 결정적이다.
        # 유니크 위반은 에러가 아니라 "이미 받음"이므로 409가 아니라 `granted=false`로 돌려준다.
        # SAVEPOINT가 되감겼으므로 지급도 표지도 없다 — 잔액은 DB에서 다시 읽는다.
        refreshed = await _require_active_user(db, user_id)
        return CloverAttendanceResponse(granted=False, balance=refreshed.clover_balance)

    user.clover_attendance_granted_on = today
    await db.commit()
    return CloverAttendanceResponse(granted=True, balance=balance_after)


@me_router.post("/clover/spend-confirmation", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_clover_spend(
    _consent: None = Depends(require_legal_consent),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """clover-goal-prompt.md CL-19 — "오늘 클로버를 쓴다"에 하루 1회 동의한 사실을 남긴다.

    잔액 변동이 아니라 원장에 자리가 없다. 같은 날 다시 불러도 같은 날짜를 덮어쓸 뿐이라
    멱등이고, 그래서 이미 확인했는지 미리 보지 않는다(조회 한 번을 아끼는 것이 아니라
    분기를 하나 없애는 것이다). 🔴 돈이 움직이지 않으므로 위 출석의 멱등키가 여기엔 필요 없다.

    ⚠️ `_consent`를 데코레이터의 `dependencies=`가 아니라 **파라미터로** 받는 것은 위 둘과
    형태가 다르다. 반환형·상태코드와는 무관하고(`dependencies=`는 그것들을 안 건드린다),
    이유는 이 라우트만 반환할 값이 없어서다 — 본문이 두 줄뿐이라 의존성이 시그니처에 보이는
    쪽이 "무엇을 거쳐 왔는지"를 읽기 쉽다. 한 파일에 두 형태가 섞인 것은 의도다.
    """
    user = await _require_active_user(db, user_id)
    user.clover_spend_confirmed_on = kst_today(datetime.now(UTC))
    await db.commit()
