"""클로버의 HTTP 표면.

`core/clover.py`가 잔액 판정과 원장을 갖고, 이 파일은 그 위의 `/me` 라우트들(`me_router`)과 로그인 없이 읽는
공개 가격 안내(`router`, prefix `/clover`)다. 공개 라우트에는 세션도 재동의 게이트도 붙이지 않는다 — 비로그인
방문자가 결제 전에 상품을 볼 수 있어야 한다.

🔴 **`auth`의 `me_router`에 얹지 않는다** — 그러면 auth 패키지가 재화를 알게 된다. `/me`
prefix를 실제로 가진 본보기는 `inquiry/router.py:22`·`chat/router.py:122`·`assets/router.py:46`
셋이다.

**레이트리밋 게이트는 붙이지 않는다** — 잔액 조회·미션 청구는 LLM·GPU를
태우지 않는다. `require_legal_consent`는 다른 `/me` 라우트와 같게 붙인다.
"""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover import products
from api.clover.missions import (
    MISSION_KEYS,
    MISSION_REWARDS,
    MissionKey,
    mission_achieved,
    mission_claimed,
    mission_claimed_before_withdrawal,
    mission_idempotency_key,
)
from api.clover.schemas import (
    CloverBalanceResponse,
    CloverExpiringSoon,
    CloverLedgerCategory,
    CloverLedgerItem,
    CloverLedgerListResponse,
    CloverMissionClaimResponse,
    CloverMissionItem,
    CloverMissionsResponse,
    CloverPayMethodItem,
    CloverPricingResponse,
    CloverProductItem,
)
from api.core import clover
from api.core.clover import (
    PURCHASE_LOT_KINDS,
    earned_lot_expiry,
    grant,
    is_same_kst_day,
    kst_today,
)
from api.core.identity_gate import identity_verification_required, is_identity_gated
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.llm.chat_models import DEFAULT_CHAT_MODEL, chat_turn_cost
from api.payments.config import identity_gate_active, payments_active
from api.payments.methods import PAY_METHODS
from api.session.dependencies import get_current_user_id

me_router = APIRouter(prefix="/me", tags=["clover"])
router = APIRouter(prefix="/clover", tags=["clover"])

# 유저 대면 목록의 저장소 표준(커서 페이징), 페이지 크기는
# 서버 상수로 고정한다(클라이언트가 못 바꾼다). `content/router.py`의 `CONTENT_LIST_PAGE_SIZE`와
# 같은 관례.
CLOVER_LEDGER_PAGE_SIZE = 20

# 가르는 축은 부호가 아니라 "유저가 왜 그렇게 됐는가"다.
# 사용은 유저가 쓴 것만, 소멸은 유저 의지와 무관하게 사라진 것 전부다. 환불이 획득인 것은
# 양수라서가 아니라 되돌려받은 것이라서고, 어드민 회수·탈퇴 소멸이 소멸인 것도 음수라서가
# 아니라 유저가 쓴 게 아니라서다. 🔴 맵은 여기 한 벌만 둔다 — 응답(`CloverLedgerItem.category`)에
# 그대로 실어 보내 FE가 같은 맵을 다시 두지 않게 한다. 새 `kind`를
# 추가하면 여기도 반드시 추가해야 한다 — 누락을 잡는 그물은
# `test_clover_ledger_api.py`의 `test_kind_category_map_covers_every_clover_kind`다.
CLOVER_KIND_CATEGORY: dict[str, CloverLedgerCategory] = {
    "attendance_grant": "earn",
    "mission_grant": "earn",
    "admin_grant": "earn",
    "chat_refund": "earn",
    "image_refund": "earn",
    "novelize_refund": "earn",
    "purchase_paid": "earn",
    "purchase_bonus": "earn",
    # 포트원이 환불을 거절해 회수를 되돌린 것 — 되돌려받은 것이라 환불과 같은 획득이다.
    "purchase_restore": "earn",
    "chat_spend": "use",
    "image_spend": "use",
    "novelize_spend": "use",
    "expire_burn": "expire",
    "admin_revoke": "expire",
    "withdrawal_burn": "expire",
    # 결제 취소에 따른 회수 — 유저가 쓴 것이 아니라 어드민 회수와 같은 범주다.
    "purchase_revoke": "expire",
}

_CATEGORY_KINDS: dict[CloverLedgerCategory, list[str]] = {
    "use": [kind for kind, category in CLOVER_KIND_CATEGORY.items() if category == "use"],
    "earn": [kind for kind, category in CLOVER_KIND_CATEGORY.items() if category == "earn"],
    "expire": [kind for kind, category in CLOVER_KIND_CATEGORY.items() if category == "expire"],
}

# 임박 임계값은 3일이다 — 만료까지 3일 이내인 로트가
# 있을 때만 expiringSoon을 채우고, 아니면 null이다. 근거: 유효기간 7일의 절반이 지난 시점.
# 값(3일)과 주체(BE가 채운다) 둘 다 설계에서 정해진 것이다.
EXPIRING_SOON_THRESHOLD = timedelta(days=3)


def _encode_cursor(parts: list[str]) -> str:
    # content/router.py의 `_encode_cursor` 복제 — 모듈 로컬 비공개 함수라
    # import해서 공유하지 않고 각 리스트 엔드포인트가 자기 것을 갖는 게 이 저장소 관례다.
    return base64.urlsafe_b64encode(json.dumps(parts).encode()).decode()


def _decode_cursor(cursor: str) -> list[str]:
    decoded: list[str] = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return decoded


async def _require_active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """탈퇴·부재는 `get_current_user_id`가 이미 401로 막는다.
    앞 의존성들이 같은 세션으로 읽은 행이지만 아무도 붙잡지 않아 수거됐으므로(identity map은
    약참조) 여기서 SELECT가 다시 나간다 — 어차피 잔액을 읽으려면 행이 필요하다.

    그래도 한 번 더 확인하는 이유는 탈퇴 여부 판정을 이 파일이 갖기 위해서다 — 게이트가
    빠지거나 순서가 바뀌어도 라우트가 스스로 막는다.
    """
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


async def _expiring_soon(db: AsyncSession, *, user_id: uuid.UUID, now: datetime) -> CloverExpiringSoon | None:
    """가장 임박한 만료 묶음(같은 시각 만료 로트는 합산).

    🔴 `expires_at > now`인 로트만 본다 — 배치가 아직 못 지운 이미 만료된 로트를 포함하면
    "0일 뒤 소멸"·음수 D-day가 화면에 뜬다. 이건 **표시 전용 필터**라 "차감·잔액 판정
    경로에는 만료 필터를 걸지 않는다"는 원칙과 충돌하지 않는다 — 표시와 판정은 다른 경로다.

    🔴 **3일 임박 게이트** — `expires_at <= now + EXPIRING_SOON_THRESHOLD`인 로트가
    없으면 `None`을 돌려준다. 경계(정확히 3일 남음)는 **포함**으로 뒀다 — 이건 이 함수가
    고른 값이다(설계는 "3일 이내"의 등호 포함 여부까지는 정하지 않았다. "이내"의 통상 의미를
    따라 포함 쪽을 골랐다).

    유저당 활성 로트가 10행 미만이라는 가정을 재사용해 Python에서 최솟값을 고르고
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
                CloverLot.expires_at <= now + EXPIRING_SOON_THRESHOLD,
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


@router.get("/pricing")
async def get_clover_pricing() -> CloverPricingResponse:
    """공개 조회 — 인증 없음. 충전 상품과 기본 모델 기준 사용 단가를 한 응답에 싣는다. 웹 상품 안내는 숫자 사본 없이
    이 값만 쓴다. DB 를 읽지 않아 비용이 없으므로 레이트리밋도 붙이지 않는다."""
    # 상품과 단가는 요청마다 모듈 속성으로 다시 읽는다 — import 로 값을 묶어 두면 상수를 바꿔도(테스트의 monkeypatch 포함)
    # 응답이 따라오지 않는다.
    return CloverPricingResponse(
        products=[
            CloverProductItem(
                key=p.key,
                name=p.name,
                price_krw=p.price_krw,
                paid_amount=p.paid_amount,
                bonus_amount=p.bonus_amount,
            )
            for p in products.CLOVER_PRODUCTS
        ],
        chat_turn_cost=chat_turn_cost(DEFAULT_CHAT_MODEL),
        image_cost=clover.IMAGE_UNIT_COST,
        payments_enabled=payments_active(),
        identity_gate_enabled=identity_gate_active(),
        pay_methods=[
            CloverPayMethodItem(pay_method=m.pay_method, easy_pay_provider=m.easy_pay_provider) for m in PAY_METHODS
        ],
    )


@me_router.get("/clover", dependencies=[Depends(require_legal_consent)])
async def get_clover_balance(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CloverBalanceResponse:
    """🔴 **부작용이 없다** — 클로버 지급은 전용 POST(미션 청구)다.

    GET이 지급까지 하면 프리페치·재조회가 곧 지급이 되어, 화면이 다시 그려질 때마다 돈이 움직일 수 있는
    경로가 생긴다.
    """
    user = await _require_active_user(db, user_id)
    now = datetime.now(UTC)
    return CloverBalanceResponse(
        balance=user.clover_balance,
        spend_confirmed_today=is_same_kst_day(user.clover_spend_confirmed_on, now),
        paid_balance=await clover.paid_balance(db, user_id=user_id),
        expiring_soon=await _expiring_soon(db, user_id=user_id, now=now),
    )


@me_router.post("/clover/spend-confirmation", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_clover_spend(
    _consent: None = Depends(require_legal_consent),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """"오늘 클로버를 쓴다"에 하루 1회 동의한 사실을 남긴다.

    잔액 변동이 아니라 원장에 자리가 없다. 같은 날 다시 불러도 같은 날짜를 덮어쓸 뿐이라
    멱등이고, 그래서 이미 확인했는지 미리 보지 않는다(조회 한 번을 아끼는 것이 아니라
    분기를 하나 없애는 것이다). 🔴 돈이 움직이지 않으므로 아래 미션 청구의 원장 멱등키가 여기엔 필요 없다.

    ⚠️ `_consent`를 데코레이터의 `dependencies=`가 아니라 **파라미터로** 받는 것은 다른 `/me` 라우트와
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
    """3종(`first_publish`·`first_message`·`first_image`)
    달성·청구 여부를 매 조회마다 다시 계산한다. 상태를 저장하지 않으므로 이 응답은
    캐시된 값이 아니라 그 순간의 진실이다.
    """
    user = await _require_active_user(db, user_id)
    now = datetime.now(UTC)
    missions = [
        CloverMissionItem(
            key=key,
            reward=MISSION_REWARDS[key],
            achieved=await mission_achieved(db, user_id=user_id, key=key),
            claimed=await mission_claimed(db, user_id=user_id, key=key)
            or await mission_claimed_before_withdrawal(db, ci_hmac=user.identity_ci_hmac, key=key, now=now),
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
    **에러가 아니다.**

    🔴 **멱등은 원장 멱등키의 유니크 인덱스 하나가 맡는다**(키는 유저+미션이라 결정적이다). 사전 컬럼 검사가 없으므로
    순차 재호출도 동시 요청도 같은 `IntegrityError` 경로로 막힌다. 지급과 로트·원장 행이 한 트랜잭션이라 "돈은
    나갔는데 기록이 없는" 구간도 생기지 않는다.

    🔴 달성 여부를 **저장하지 않으므로** 이 판정도 매 요청 EXISTS다 — 청구 직전에
    달성 신호가 사라져 있으면(방·메시지 삭제 등) 422로 막힌다. 영구 손실은 아니다: 다시
    달성하면 다시 청구할 수 있다.
    """
    user = await _require_active_user(db, user_id)
    if is_identity_gated(user):
        raise identity_verification_required()
    if not await mission_achieved(db, user_id=user_id, key=key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="mission not achieved"
        )

    now = datetime.now(UTC)
    # 같은 사람이 탈퇴 전 계정에서 이미 받은 1회성 보상이면 이미 받은 것과 같은 응답이다(보관 기간 안).
    if await mission_claimed_before_withdrawal(db, ci_hmac=user.identity_ci_hmac, key=key, now=now):
        return CloverMissionClaimResponse(granted=False, balance=user.clover_balance)
    try:
        # SAVEPOINT 안에서 시도한다 — 유니크 위반이 나도 **바깥 트랜잭션은 살아 있어야**
        # 아래에서 잔액을 다시 읽을 수 있다. `db.rollback()`이면 요청 전체가 날아간다.
        # 선례: `auth/router.py`의 가입이 같은 이유로 `begin_nested()`를 쓴다.
        async with db.begin_nested():
            balance_after = await grant(
                db,
                user_id=user_id,
                amount=MISSION_REWARDS[key],
                kind="mission_grant",
                idempotency_key=mission_idempotency_key(user_id=user_id, key=key),
                # 무료 지급에는 만료가 붙는다(지급일 KST 자정 + 8일).
                expires_at=earned_lot_expiry(now),
            )
    except IntegrityError:
        # 이미 청구됨(순차 재호출이든 동시 요청이든). `grant`는 `guard=False`라 조건 없는
        # `WHERE users.id = :u`만 내므로 동시 요청의 둘째도 락이 풀린 뒤 그대로 통과한다 — 이중 지급을 막는 것은
        # `ux_clover_ledger_idempotency_key`뿐이다. 유니크 위반은 에러가 아니라 "이미 받음"이라 409가 아니라
        # `granted=false`다. SAVEPOINT가 되감겼으므로 지급이 없다 — 잔액은 DB에서 다시 읽는다.
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
    """자기 자신의 원장만. 어드민 엔드포인트
    (`GET /admin/users/{id}/clover-ledger`, `admin/users.py`)는 인증 스코프가 어드민이고
    임의 `user_id`를 URL로 받아 그대로 재사용할 수 없다 — 그래서 복제하지 않고 새로
    만들었다.

    커서 페이징은 `content/router.py`의 `_encode_cursor`/`_decode_cursor` 선례를 복제한다
    (모듈 로컬 함수라 import 공유가 아니라 각자 갖는 게 관례). 정렬은
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
