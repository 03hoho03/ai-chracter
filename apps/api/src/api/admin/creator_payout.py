"""어드민 크리에이터 정산 신청 처리: 대기 큐, 승인(첫 승인이면 지난 기간 소급 확정), 거절, 승인 취소.

정산 스위치와 무관하게 열려 있다 — 스위치를 끄기 전에 들어온 신청을 마무리해야 한다.

잠금 순서는 크리에이터 `users` 행 → 신청 행이다. 회원의 신청과 월 확정도 크리에이터 `users` 행을 먼저 잡으므로 같은 사람의
신청·승인·확정이 그 행에서 줄을 선다. 소급 계산은 잠금 없이 읽는다 — 확정은 앞선 확정의 내역 줄을 읽으므로 같은
크리에이터의 확정이 동시에 돌면 안 되는데, 그것을 `users` 행 잠금이 막는다.
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminCreatorPayoutApplicationItem,
    AdminCreatorPayoutApplicationListResponse,
    AdminCreatorPayoutApproveRequest,
    AdminCreatorPayoutApproveResponse,
    AdminCreatorPayoutDecisionRequest,
    AdminCreatorPayoutEligibility,
)
from api.core.config import settings
from api.creator_payout.eligibility import (
    creator_payout_eligibility,
    load_creator_payout_eligibility,
    published_content_counts,
)
from api.creator_payout.settlement import confirm_window
from api.db.models.auth import User
from api.db.models.creator_payout import (
    CreatorPayoutApplication,
    CreatorPayoutApplicationStatus,
    CreatorPayoutConfirmation,
)
from api.db.session import get_db_session

router = APIRouter(tags=["admin"])

ADMIN_CREATOR_PAYOUT_PAGE_SIZE = 20

# 승인의 적립 경계(컷)를 승인 트랜잭션 시작보다 이만큼 앞에 둔다. 차감·환급 행의 시각은 그 트랜잭션의 시작 시각이라, 승인
# 직전에 시작해 승인 뒤에 커밋한 차감은 컷이 승인 시각이면 소급(이미 읽음)에도 월 확정(시각 < 컷)에도 들지 않는다. 채팅
# 차감·환급 트랜잭션은 길어야 수 초, 소설 차감은 요청 하나라 5분 앞이면 그 전에 시작한 트랜잭션은 승인 때 이미 커밋돼 있다.
APPROVAL_CUT_LAG = timedelta(minutes=5)


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


def _require_reason(reason_text: str) -> None:
    if not reason_text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="reason_text is required")


async def _lock_application(db: AsyncSession, application_id: uuid.UUID) -> tuple[User, CreatorPayoutApplication]:
    """신청자 `users` 행 → 신청 행 순서로 잠근다. 신청자를 먼저 알아야 하므로 신청 행의 `user_id` 는 잠금 없이 읽는다
    (그 칸은 바뀌지 않는다). 탈퇴 회원도 잠근다 — 거절·승인 취소는 탈퇴 회원의 신청에도 할 수 있어야 큐에서 빠진다."""
    user_id = await db.scalar(
        select(CreatorPayoutApplication.user_id).where(CreatorPayoutApplication.id == application_id)
    )
    if user_id is None:
        raise _error(status.HTTP_404_NOT_FOUND, "CREATOR_PAYOUT_APPLICATION_NOT_FOUND")
    # FK 의 KEY SHARE 는 허용하고 같은 회원의 쓰기·탈퇴와는 줄을 선다(`lock_active_user` 와 같은 잠금).
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    application = await db.scalar(
        select(CreatorPayoutApplication)
        .where(CreatorPayoutApplication.id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # 회원 행은 탈퇴해도 지우지 않고 신청 행은 지우는 경로가 없다.
    assert user is not None and application is not None
    return user, application


async def _transaction_now(db: AsyncSession) -> datetime:
    """이 트랜잭션의 시작 시각(`now()`). 차감·환급 행의 시각과 같은 시계라 컷을 이것으로 잰다."""
    now = await db.scalar(select(func.now()))
    assert now is not None
    return now


@router.get("/admin/creator-payout/applications")
async def list_creator_payout_applications(
    status_filter: CreatorPayoutApplicationStatus = Query("pending", alias="status"),
    page: int = Query(1, ge=1),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCreatorPayoutApplicationListResponse:
    """그 상태의 신청(기본 대기), 오래된 신청부터. 신청자 자격은 지금 값이다(신청 때가 아니라)."""
    total_count = await db.scalar(
        select(func.count(CreatorPayoutApplication.id)).where(CreatorPayoutApplication.status == status_filter)
    )
    assert total_count is not None
    rows = (
        await db.execute(
            select(CreatorPayoutApplication, User)
            .join(User, User.id == CreatorPayoutApplication.user_id)
            .where(CreatorPayoutApplication.status == status_filter)
            .order_by(CreatorPayoutApplication.applied_at, CreatorPayoutApplication.id)
            .offset((page - 1) * ADMIN_CREATOR_PAYOUT_PAGE_SIZE)
            .limit(ADMIN_CREATOR_PAYOUT_PAGE_SIZE)
        )
    ).tuples().all()
    counts = await published_content_counts(db, {user.id for _, user in rows})
    items = []
    for application, user in rows:
        eligibility = creator_payout_eligibility(user, counts.get(user.id, 0))
        items.append(
            AdminCreatorPayoutApplicationItem(
                id=application.id,
                user_id=user.id,
                nickname=None if eligibility.withdrawn else user.nickname,
                status=application.status,
                applied_at=application.applied_at,
                decided_at=application.decided_at,
                decision_reason=application.decision_reason,
                revoked_at=application.revoked_at,
                eligibility=AdminCreatorPayoutEligibility(
                    identity_verified=eligibility.identity_verified,
                    adult=eligibility.adult,
                    published_count=eligibility.published_count,
                    suspended=eligibility.suspended,
                    withdrawn=eligibility.withdrawn,
                ),
            )
        )
    return AdminCreatorPayoutApplicationListResponse(
        items=items,
        page=page,
        total_pages=-(-total_count // ADMIN_CREATOR_PAYOUT_PAGE_SIZE) if total_count else 0,
        total_count=total_count,
    )


@router.post("/admin/creator-payout/applications/{application_id}/approve")
async def approve_creator_payout_application(
    application_id: uuid.UUID,
    body: AdminCreatorPayoutApproveRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCreatorPayoutApproveResponse:
    """승인한다. 대기 중이 아니면 409 `CREATOR_PAYOUT_APPLICATION_NOT_PENDING`. 신청 뒤 자격이 바뀌었으면(탈퇴·정지·인증·
    나이·발행 작품) 409 `CREATOR_PAYOUT_NOT_ELIGIBLE` + `reason` — 회원의 신청과 같은 판정이다.

    컷 C = 이 트랜잭션 시작 − 5분. 월 확정은 C 부터 센다. 이 크리에이터의 소급 확정 행이 아직 없으면(첫 승인) 적립 시작을
    C − 소급 일수로 두고 [C − 소급 일수, C) 를 같은 트랜잭션에서 소급 확정한다(0원이어도 행을 남긴다 — 소급을 했다는 표식).
    소급 확정 행이 이미 있으면(승인 취소 뒤 재승인) 소급하지 않고 적립도 C 부터다.
    """
    user, application = await _lock_application(db, application_id)
    if application.status != "pending":
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_APPLICATION_NOT_PENDING")
    reason = (await load_creator_payout_eligibility(db, user)).block_reason
    if reason is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "CREATOR_PAYOUT_NOT_ELIGIBLE", "reason": reason}
        )

    now = await _transaction_now(db)
    cut = now - APPROVAL_CUT_LAG
    retro_start = cut - timedelta(days=settings.creator_payout_retro_days)
    already_retro = await db.scalar(
        select(
            exists().where(
                CreatorPayoutConfirmation.user_id == user.id, CreatorPayoutConfirmation.kind == "retro"
            )
        )
    )
    application.status = "approved"
    application.decided_at = now
    application.decided_by_admin_id = admin_id
    # 소급 창과 적립 시작이 같은 값에서 나온다 — 소급 일수 설정을 바꿔도 둘이 어긋나지 않는다.
    application.accrual_start_at = cut if already_retro else retro_start
    application.monthly_from_at = cut
    # 소급 계산은 신청 행의 적립 시작을 읽는다.
    await db.flush()

    retro_amount_krw: int | None = None
    if not already_retro:
        confirmation = await confirm_window(
            db,
            creator_id=user.id,
            kind="retro",
            period_month=None,
            windows=[(retro_start, cut)],
            cancel_adjust_month=None,
        )
        # 구간이 있는 확정은 0원이어도 행을 넣는다.
        assert confirmation is not None
        retro_amount_krw = confirmation.amount_krw

    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-approve",
        target_user_id=user.id,
        reason_text=body.reason_text,
    )
    await db.commit()
    return AdminCreatorPayoutApproveResponse(retro_amount_krw=retro_amount_krw)


@router.post(
    "/admin/creator-payout/applications/{application_id}/reject", status_code=status.HTTP_204_NO_CONTENT
)
async def reject_creator_payout_application(
    application_id: uuid.UUID,
    body: AdminCreatorPayoutDecisionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """거절한다. 사유는 신청자에게 보인다. 대기 중이 아니면 409 `CREATOR_PAYOUT_APPLICATION_NOT_PENDING`. 거절된 회원은
    다시 신청할 수 있다(새 행)."""
    _require_reason(body.reason_text)
    user, application = await _lock_application(db, application_id)
    if application.status != "pending":
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_APPLICATION_NOT_PENDING")
    application.status = "rejected"
    application.decided_at = await _transaction_now(db)
    application.decided_by_admin_id = admin_id
    application.decision_reason = body.reason_text
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-reject",
        target_user_id=user.id,
        reason_text=body.reason_text,
    )
    await db.commit()


@router.post(
    "/admin/creator-payout/applications/{application_id}/revoke", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_creator_payout_application(
    application_id: uuid.UUID,
    body: AdminCreatorPayoutDecisionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """승인을 취소한다. 승인 중이 아니면 409 `CREATOR_PAYOUT_APPLICATION_NOT_APPROVED`.

    효과는 "이 시각 이후 적립 중단" 하나다. 그 전까지의 사용은 그대로 적립되고(취소한 달의 앞부분도 다음 월 확정이 센다),
    이미 확정된 적립과 소급 확정 행은 그대로 남는다. 다시 신청해 승인받으면 소급 없이 그 승인부터 적립한다.
    """
    _require_reason(body.reason_text)
    user, application = await _lock_application(db, application_id)
    if application.status != "approved":
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_APPLICATION_NOT_APPROVED")
    application.status = "revoked"
    application.revoked_at = await _transaction_now(db)
    application.revoked_by_admin_id = admin_id
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-revoke",
        target_user_id=user.id,
        reason_text=body.reason_text,
    )
    await db.commit()
