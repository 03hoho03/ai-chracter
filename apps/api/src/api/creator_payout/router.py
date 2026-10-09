"""크리에이터 정산의 회원 쪽 HTTP 표면: 신청과 신청 상태·자격 조회.

정산 스위치가 꺼져 있으면 모든 라우트가 503 `CREATOR_PAYOUT_UNAVAILABLE` 이다. 어드민의 신청 처리(`admin/creator_payout.py`)는
스위치와 무관하다.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import case, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import lock_active_user
from api.core.identity_gate import identity_verification_required
from api.creator_payout.config import creator_payout_active
from api.creator_payout.eligibility import CreatorPayoutBlockReason, load_creator_payout_eligibility
from api.creator_payout.schemas import (
    ApplyCreatorPayoutRequest,
    ApplyCreatorPayoutResponse,
    CreatorPayoutApplicationView,
    CreatorPayoutEligibilityView,
    CreatorPayoutResponse,
)
from api.db.models.auth import User
from api.db.models.creator_payout import CreatorPayoutApplication
from api.db.session import get_db_session
from api.legal.dependencies import _latest_published_legal_version, require_legal_consent
from api.payments.notify import PaymentNotifier, get_payment_notifier
from api.session.dependencies import get_current_user_id

me_router = APIRouter(prefix="/me/creator-payout", tags=["creator-payout"])

# 운영자 알림 문구. 회원·신청을 알아볼 단서(id·닉네임)는 싣지 않는다 — 결제 알림과 같은 외부 채널이다.
APPLICATION_RECEIVED_MESSAGE = "크리에이터 정산 신청 1건 접수"

_LIVE_STATUSES = ("pending", "approved")


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


def _unavailable() -> HTTPException:
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "CREATOR_PAYOUT_UNAVAILABLE")


def _refusal(reason: CreatorPayoutBlockReason) -> HTTPException:
    match reason:
        case "withdrawn":
            return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        case "suspended":
            return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
        case "identity_required":
            return identity_verification_required()
        case "age_restricted":
            return _error(status.HTTP_403_FORBIDDEN, "CREATOR_PAYOUT_AGE_RESTRICTED")
        case "no_published_work":
            return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_NO_PUBLISHED_WORK")


@me_router.get("")
async def get_creator_payout(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CreatorPayoutResponse:
    """신청 상태와 신청 자격. 인증·나이·발행 작품이 모자라도 거절하지 않고 `eligibility` 로 보여 준다(신청과 같은 판정)."""
    if not creator_payout_active():
        raise _unavailable()
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    eligibility = await load_creator_payout_eligibility(db, user)

    # 살아 있는 신청(대기·승인)은 한 사람에 하나라 그것이 있으면 그것, 없으면 가장 늦은 끝난 신청이다.
    latest = await db.scalar(
        select(CreatorPayoutApplication)
        .where(CreatorPayoutApplication.user_id == user_id)
        .order_by(
            case((CreatorPayoutApplication.status.in_(_LIVE_STATUSES), 0), else_=1),
            CreatorPayoutApplication.applied_at.desc(),
        )
        .limit(1)
    )
    ever_approved = await db.scalar(
        select(
            exists().where(
                CreatorPayoutApplication.user_id == user_id,
                CreatorPayoutApplication.status.in_(("approved", "revoked")),
            )
        )
    )
    return CreatorPayoutResponse(
        application=None
        if latest is None
        else CreatorPayoutApplicationView(
            status=latest.status,
            applied_at=latest.applied_at,
            decided_at=latest.decided_at,
            decision_reason=latest.decision_reason,
        ),
        eligibility=CreatorPayoutEligibilityView(
            identity_verified=eligibility.identity_verified,
            adult=eligibility.adult,
            has_published_work=eligibility.published_count > 0,
            suspended=eligibility.suspended,
        ),
        ever_approved=bool(ever_approved),
    )


@me_router.post(
    "/application", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def apply_creator_payout(
    body: ApplyCreatorPayoutRequest,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    notifier: PaymentNotifier = Depends(get_payment_notifier),
) -> ApplyCreatorPayoutResponse:
    """정산을 신청한다. 순서: 스위치(503 `CREATOR_PAYOUT_UNAVAILABLE`) → 회원 행 잠금(탈퇴 401·정지 403 — 세션 확인 뒤에
    탈퇴·정지가 커밋됐어도 여기서 막힌다) → 자격(미인증 403 `IDENTITY_VERIFICATION_REQUIRED`, 만 19세 미만 403
    `CREATOR_PAYOUT_AGE_RESTRICTED`, 발행 작품 없음 422 `CREATOR_PAYOUT_NO_PUBLISHED_WORK`) → 대기·승인 중인 신청이 이미
    있으면 409 `CREATOR_PAYOUT_ALREADY_APPLIED`.

    승인 취소·거절된 회원은 다시 신청할 수 있다(새 행). 동의 기록에 남길 처리방침 게시본이 없으면 503 이다.
    """
    if not creator_payout_active():
        raise _unavailable()
    # 같은 회원의 신청·승인이 이 행에서 줄을 서서, 아래 "살아 있는 신청" 확인과 넣기 사이에 다른 신청이 끼지 않는다.
    user = await lock_active_user(db, user_id)
    reason = (await load_creator_payout_eligibility(db, user)).block_reason
    if reason is not None:
        raise _refusal(reason)

    live = await db.scalar(
        select(
            exists().where(
                CreatorPayoutApplication.user_id == user_id, CreatorPayoutApplication.status.in_(_LIVE_STATUSES)
            )
        )
    )
    if live:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_ALREADY_APPLIED")
    privacy_version = await _latest_published_legal_version(db, "privacy")
    if privacy_version is None:
        raise _unavailable()

    try:
        # 회원 행 잠금을 거치지 않는 쓰기가 생겨도 부분 유니크가 두 번째 살아 있는 신청을 막는다. SAVEPOINT 라 그 경우에도
        # 요청 트랜잭션은 살아 있다.
        async with db.begin_nested():
            db.add(
                CreatorPayoutApplication(
                    user_id=user_id,
                    status="pending",
                    consented_at=datetime.now(UTC),
                    privacy_version=privacy_version,
                )
            )
    except IntegrityError:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_ALREADY_APPLIED") from None
    await db.commit()
    background_tasks.add_task(notifier, APPLICATION_RECEIVED_MESSAGE)
    return ApplyCreatorPayoutResponse(status="pending")
