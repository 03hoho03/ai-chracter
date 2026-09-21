"""clover-techspec.md CT-9·CT-10 — 클로버의 HTTP 표면.

`core/clover.py`가 잔액 판정과 원장을 갖고, 이 파일은 그 위의 `/me` 라우트 셋뿐이다.

🔴 **`auth`의 `me_router`에 얹지 않는다** — 그러면 auth 패키지가 재화를 알게 된다. `/me`
prefix를 실제로 가진 본보기는 `inquiry/router.py:22`·`chat/router.py:122`·`assets/router.py:46`
셋이다(clover-techspec.md CT-9).

**레이트리밋 게이트는 붙이지 않는다**(clover-techspec.md §4-1) — 잔액 조회·출석은 LLM·GPU를
태우지 않는다. `require_legal_consent`는 다른 `/me` 라우트와 같게 붙인다.
"""

import base64
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover.missions import (
    MISSION_KEYS,
    MISSION_REWARDS,
    MissionKey,
    mission_achieved,
    mission_claimed,
    mission_idempotency_key,
)
from api.clover.schemas import (
    CloverAttendanceResponse,
    CloverBalanceResponse,
    CloverExpiringSoon,
    CloverLedgerCategory,
    CloverLedgerItem,
    CloverLedgerListResponse,
    CloverMissionClaimResponse,
    CloverMissionItem,
    CloverMissionsResponse,
)
from api.core.clover import (
    ATTENDANCE_GRANT_AMOUNT,
    earned_lot_expiry,
    grant,
    is_same_kst_day,
    kst_today,
)
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.session.dependencies import get_current_user_id

me_router = APIRouter(prefix="/me", tags=["clover"])

# clover-page-goal-prompt.md CE-20 — 유저 대면 목록의 저장소 표준(커서 페이징), 페이지 크기는
# 서버 상수로 고정한다(클라이언트가 못 바꾼다). `content/router.py`의 `CONTENT_LIST_PAGE_SIZE`와
# 같은 관례.
CLOVER_LEDGER_PAGE_SIZE = 20

# clover-page-goal-prompt.md CE-21 — 가르는 축은 부호가 아니라 "유저가 왜 그렇게 됐는가"다.
# 사용은 유저가 쓴 것만, 소멸은 유저 의지와 무관하게 사라진 것 전부다. 환불이 획득인 것은
# 양수라서가 아니라 되돌려받은 것이라서고, 어드민 회수·탈퇴 소멸이 소멸인 것도 음수라서가
# 아니라 유저가 쓴 게 아니라서다. 🔴 맵은 여기 한 벌만 둔다 — 응답(`CloverLedgerItem.category`)에
# 그대로 실어 보내 FE가 같은 맵을 다시 두지 않게 한다(사전 점검 §8 확인 완료 2). 새 `kind`를
# 추가하면 여기도 반드시 추가해야 한다 — 누락을 잡는 그물이 T-14다.
CLOVER_KIND_CATEGORY: dict[str, CloverLedgerCategory] = {
    "attendance_grant": "earn",
    "mission_grant": "earn",
    "admin_grant": "earn",
    "chat_refund": "earn",
    "image_refund": "earn",
    "chat_spend": "use",
    "image_spend": "use",
    "expire_burn": "expire",
    "admin_revoke": "expire",
    "withdrawal_burn": "expire",
}

_CATEGORY_KINDS: dict[CloverLedgerCategory, list[str]] = {
    "use": [kind for kind, category in CLOVER_KIND_CATEGORY.items() if category == "use"],
    "earn": [kind for kind, category in CLOVER_KIND_CATEGORY.items() if category == "earn"],
    "expire": [kind for kind, category in CLOVER_KIND_CATEGORY.items() if category == "expire"],
}


def _encode_cursor(parts: list[str]) -> str:
    # content/router.py의 `_encode_cursor` 복제(사전 점검 PA-7) — 모듈 로컬 비공개 함수라
    # import해서 공유하지 않고 각 리스트 엔드포인트가 자기 것을 갖는 게 이 저장소 관례다.
    return base64.urlsafe_b64encode(json.dumps(parts).encode()).decode()


def _decode_cursor(cursor: str) -> list[str]:
    decoded: list[str] = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return decoded


async def _require_active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """`require_legal_consent`가 같은 세션으로 이미 조회한 행이라 여기서는 identity map 히트다.

    그래도 한 번 더 확인하는 이유는 탈퇴 여부 판정을 이 파일이 갖기 위해서다 — 게이트가
    빠지거나 순서가 바뀌어도 라우트가 스스로 막는다.
    """
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


async def _expiring_soon(db: AsyncSession, *, user_id: uuid.UUID, now: datetime) -> CloverExpiringSoon | None:
    """clover-page-goal-prompt.md CE-22 — 가장 임박한 만료 묶음(같은 시각 만료 로트는 합산).

    🔴 `expires_at > now`인 로트만 본다 — 배치가 아직 못 지운 이미 만료된 로트를 포함하면
    "0일 뒤 소멸"·음수 D-day가 화면에 뜬다. 이건 **표시 전용 필터**라 CE-8(차감·잔액 판정
    경로에는 만료 필터를 걸지 않는다)과 충돌하지 않는다 — 표시와 판정은 다른 경로다.

    유저당 활성 로트가 10행 미만이라는 가정(CE-6)을 재사용해 Python에서 최솟값을 고르고
    합산한다 — 집계 SQL(`GROUP BY`)을 새로 안 쓴다.
    """
    lots = (
        await db.scalars(
            select(CloverLot)
            .where(
                CloverLot.user_id == user_id,
                CloverLot.remaining > 0,
                CloverLot.expires_at.is_not(None),
                CloverLot.expires_at > now,
            )
            .order_by(CloverLot.expires_at.asc())
        )
    ).all()
    if not lots:
        return None
    soonest = lots[0].expires_at
    assert soonest is not None  # 위 `.is_not(None)` 필터가 보장한다
    amount = sum(lot.remaining for lot in lots if lot.expires_at == soonest)
    return CloverExpiringSoon(amount=amount, expires_at=soonest)


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
        expiring_soon=await _expiring_soon(db, user_id=user_id, now=now),
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
                # clover-page-goal-prompt.md CE-11 — 출석 지급도 만료가 붙는다(CE-7과 같은
                # 규칙: 지급일 KST 자정 + 8일).
                expires_at=earned_lot_expiry(now),
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


@me_router.get("/clover/missions", dependencies=[Depends(require_legal_consent)])
async def get_clover_missions(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CloverMissionsResponse:
    """clover-page-goal-prompt.md CE-13 — 3종(`first_publish`·`first_message`·`first_image`)
    달성·청구 여부를 매 조회마다 다시 계산한다. 상태를 저장하지 않으므로(T-13) 이 응답은
    캐시된 값이 아니라 그 순간의 진실이다.
    """
    await _require_active_user(db, user_id)
    missions = [
        CloverMissionItem(
            key=key,
            reward=MISSION_REWARDS[key],
            achieved=await mission_achieved(db, user_id=user_id, key=key),
            claimed=await mission_claimed(db, user_id=user_id, key=key),
        )
        for key in MISSION_KEYS
    ]
    return CloverMissionsResponse(missions=missions)


@me_router.post("/clover/missions/{key}/claim", dependencies=[Depends(require_legal_consent)])
async def claim_clover_mission(
    key: MissionKey,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CloverMissionClaimResponse:
    """미션 청구. 달성하지 못했으면 422. 이미 청구했으면(멱등키 중복) `granted=false`이고
    **에러가 아니다** — 위 출석과 같은 패턴이다.

    🔴 달성 여부를 **저장하지 않으므로**(CE-13) 이 판정도 매 요청 EXISTS다 — 청구 직전에
    달성 신호가 사라져 있으면(방·메시지 삭제 등) 422로 막힌다. 영구 손실은 아니다: 다시
    달성하면 다시 청구할 수 있다(T-13).
    """
    await _require_active_user(db, user_id)
    if not await mission_achieved(db, user_id=user_id, key=key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="mission not achieved"
        )

    now = datetime.now(UTC)
    try:
        # 출석과 같은 패턴(SAVEPOINT + IntegrityError) — 선례는 위 `claim_clover_attendance`.
        async with db.begin_nested():
            balance_after = await grant(
                db,
                user_id=user_id,
                amount=MISSION_REWARDS[key],
                kind="mission_grant",
                idempotency_key=mission_idempotency_key(user_id=user_id, key=key),
                # clover-page-goal-prompt.md CE-11 — 미션 지급도 만료가 붙는다(CE-7과 같은
                # 규칙).
                expires_at=earned_lot_expiry(now),
            )
    except IntegrityError:
        # 이미 청구됨(순차 재호출이든 동시 요청이든 — 여기는 출석과 달리 사전 컬럼 검사가
        # 없어 멱등키 유니크 인덱스 하나가 두 경우를 전부 막는다). SAVEPOINT가 되감겼으므로
        # 지급이 없다 — 잔액은 DB에서 다시 읽는다.
        refreshed = await _require_active_user(db, user_id)
        return CloverMissionClaimResponse(granted=False, balance=refreshed.clover_balance)

    await db.commit()
    return CloverMissionClaimResponse(granted=True, balance=balance_after)


@me_router.get("/clover/ledger", dependencies=[Depends(require_legal_consent)])
async def get_clover_ledger(
    category: CloverLedgerCategory,
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CloverLedgerListResponse:
    """clover-page-goal-prompt.md CE-20 — 자기 자신의 원장만. 어드민 엔드포인트
    (`GET /admin/users/{id}/clover-ledger`, `admin/users.py`)는 인증 스코프가 어드민이고
    임의 `user_id`를 URL로 받아 그대로 재사용할 수 없다(§1-8) — 그래서 복제하지 않고 새로
    만들었다.

    커서 페이징은 `content/router.py`의 `_encode_cursor`/`_decode_cursor` 선례를 복제한다
    (사전 점검 PA-7 — 모듈 로컬 함수라 import 공유가 아니라 각자 갖는 게 관례). 정렬은
    `created_at DESC, id DESC` — 2차 키가 필수인 이유는 한 트랜잭션에 원장 행이 여러 개
    들어갈 수 있어(차감+환불이 같은 요청에서 난다) `created_at`
    (`server_default=func.now()`, 트랜잭션 시작 시각 고정) 동률이 흔해서다(어드민 원장의
    같은 이유, `admin/users.py:list_user_clover_ledger`).
    """
    await _require_active_user(db, user_id)

    query = (
        select(CloverLedger)
        .where(
            CloverLedger.user_id == user_id,
            CloverLedger.kind.in_(_CATEGORY_KINDS[category]),
        )
        .order_by(CloverLedger.created_at.desc(), CloverLedger.id.desc())
    )
    if cursor is not None:
        created_at, last_id = _decode_cursor(cursor)
        # mypy strict 함정(apps/api/CLAUDE.md) — 오른쪽은 평범한 파이썬 튜플로 둔다.
        query = query.where(
            tuple_(CloverLedger.created_at, CloverLedger.id)
            < (datetime.fromisoformat(created_at), uuid.UUID(last_id))
        )

    rows = (await db.scalars(query.limit(CLOVER_LEDGER_PAGE_SIZE + 1))).all()
    has_more = len(rows) > CLOVER_LEDGER_PAGE_SIZE
    page = rows[:CLOVER_LEDGER_PAGE_SIZE]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor([last.created_at.isoformat(), str(last.id)])

    return CloverLedgerListResponse(
        items=[
            CloverLedgerItem(
                id=row.id,
                amount=row.amount,
                balance_after=row.balance_after,
                kind=row.kind,
                category=CLOVER_KIND_CATEGORY[row.kind],
                created_at=row.created_at,
            )
            for row in page
        ],
        next_cursor=next_cursor,
    )
