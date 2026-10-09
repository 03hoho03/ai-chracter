"""어드민 크리에이터 정산 신청 처리: 대기 큐, 승인(첫 승인이면 지난 기간 소급 확정), 거절, 승인 취소. 그리고 지급 처리:
지급 큐·상세(원천징수 미리보기), 지급 정보 원문 열람(사유 + 열람마다 감사 1행), 이체 완료 기록, 반려.

정산 스위치와 무관하게 열려 있다 — 스위치를 끄기 전에 들어온 신청과 지급, 탈퇴 전에 신청한 지급을 마무리해야 한다.

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
    AdminCreatorPayoutDetail,
    AdminCreatorPayoutEligibility,
    AdminCreatorPayoutItem,
    AdminCreatorPayoutListResponse,
    AdminCreatorPayoutReturnRequest,
    AdminCreatorPayoutTransferRequest,
    AdminCreatorPayoutWithholding,
    AdminPayeeInfoViewRequest,
    AdminPayeeInfoViewResponse,
)
from api.core.config import settings
from api.core.field_crypto import FieldDecryptError
from api.core.rate_limit import KST
from api.core.sentry import capture_dependency_failure
from api.creator_payout.config import payout_keyring
from api.creator_payout.eligibility import (
    creator_payout_eligibility,
    load_creator_payout_eligibility,
    published_content_counts,
)
from api.creator_payout.payout_info import decrypt_field, mask_name
from api.creator_payout.settlement import confirm_window
from api.creator_payout.tax import withholding
from api.db.models.auth import User
from api.db.models.creator_payout import (
    CreatorPayout,
    CreatorPayoutApplication,
    CreatorPayoutApplicationStatus,
    CreatorPayoutConfirmation,
    CreatorPayoutProfile,
    CreatorPayoutStatus,
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
    (그 칸은 바뀌지 않는다). 탈퇴는 같은 `users` 행을 잠근 채 신청 행을 지우므로, 그 사이에 탈퇴가 끝났으면 신청 행이 없어
    404 다."""
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
    # 회원 행은 탈퇴해도 지우지 않는다.
    assert user is not None
    if application is None:
        raise _error(status.HTTP_404_NOT_FOUND, "CREATOR_PAYOUT_APPLICATION_NOT_FOUND")
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
    """승인을 취소한다. 사유는 거절 사유와 같은 칸에 남아 신청자에게 보인다. 승인 중이 아니면 409
    `CREATOR_PAYOUT_APPLICATION_NOT_APPROVED`.

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
    application.decision_reason = body.reason_text
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-revoke",
        target_user_id=user.id,
        reason_text=body.reason_text,
    )
    await db.commit()


# ── 지급 ─────────────────────────────────────────────────────────────────────
# 지급 건 처리는 지급 행 하나만 잠근다. 잔액은 파생값이라 다른 쓰기와 줄을 설 필요가 없고, 탈퇴 회원의 건도 처리해야 해서
# 회원 행을 잡지 않는다. 실제 이체는 운영자가 은행에서 하고 여기서는 그 기록만 남긴다.


def _unreadable() -> HTTPException:
    return _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_INFO_UNREADABLE")


def _withholding_view(
    income_tax_rate_bps: int, income_tax_krw: int, local_tax_krw: int, net_amount_krw: int
) -> AdminCreatorPayoutWithholding:
    return AdminCreatorPayoutWithholding(
        income_tax_rate_bps=income_tax_rate_bps,
        income_tax_krw=income_tax_krw,
        local_tax_krw=local_tax_krw,
        net_amount_krw=net_amount_krw,
    )


async def _payout_with_parties(
    db: AsyncSession, payout_id: uuid.UUID
) -> tuple[CreatorPayout, CreatorPayoutProfile, User]:
    row = (
        await db.execute(
            select(CreatorPayout, CreatorPayoutProfile, User)
            .join(CreatorPayoutProfile, CreatorPayoutProfile.id == CreatorPayout.profile_id)
            .join(User, User.id == CreatorPayout.user_id)
            .where(CreatorPayout.id == payout_id)
        )
    ).tuples().one_or_none()
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "CREATOR_PAYOUT_NOT_FOUND")
    return row


async def _lock_requested_payout(db: AsyncSession, payout_id: uuid.UUID) -> CreatorPayout:
    payout = await db.scalar(
        select(CreatorPayout)
        .where(CreatorPayout.id == payout_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if payout is None:
        raise _error(status.HTTP_404_NOT_FOUND, "CREATOR_PAYOUT_NOT_FOUND")
    if payout.status != "requested":
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_NOT_REQUESTED")
    return payout


@router.get("/admin/creator-payout/payouts")
async def list_creator_payouts(
    status_filter: CreatorPayoutStatus = Query("requested", alias="status"),
    page: int = Query(1, ge=1),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCreatorPayoutListResponse:
    """그 상태의 지급(기본 처리 중), 오래된 신청부터. 탈퇴 회원의 건도 나온다(닉네임 null)."""
    total_count = await db.scalar(
        select(func.count(CreatorPayout.id)).where(CreatorPayout.status == status_filter)
    )
    assert total_count is not None
    rows = (
        await db.execute(
            select(CreatorPayout, User)
            .join(User, User.id == CreatorPayout.user_id)
            .where(CreatorPayout.status == status_filter)
            .order_by(CreatorPayout.requested_at, CreatorPayout.id)
            .offset((page - 1) * ADMIN_CREATOR_PAYOUT_PAGE_SIZE)
            .limit(ADMIN_CREATOR_PAYOUT_PAGE_SIZE)
        )
    ).tuples().all()
    return AdminCreatorPayoutListResponse(
        items=[
            AdminCreatorPayoutItem(
                id=payout.id,
                user_id=user.id,
                nickname=None if user.deleted_at is not None else user.nickname,
                withdrawn=user.deleted_at is not None,
                status=payout.status,
                amount_krw=payout.amount_krw,
                net_amount_krw=payout.net_amount_krw,
                requested_at=payout.requested_at,
            )
            for payout, user in rows
        ],
        page=page,
        total_pages=-(-total_count // ADMIN_CREATOR_PAYOUT_PAGE_SIZE) if total_count else 0,
        total_count=total_count,
    )


@router.get("/admin/creator-payout/payouts/{payout_id}")
async def get_creator_payout_detail(
    payout_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCreatorPayoutDetail:
    """지급 건 하나와 마스킹한 수취인, 신청 때의 원천징수와 지금 세율로 다시 계산한 값. 수취인 실명을 복호화하지 못하면
    (키 분실 등) 409 `CREATOR_PAYOUT_INFO_UNREADABLE` — 작가에게 지급 정보를 다시 입력받고 이 건은 반려 뒤 재신청한다."""
    payout, profile, user = await _payout_with_parties(db, payout_id)
    try:
        masked_name = mask_name(decrypt_field(payout_keyring(), profile, "legal_name"))
    except FieldDecryptError as exc:
        capture_dependency_failure(exc, dependency="creator_payout")
        raise _unreadable() from None
    current = withholding(payout.amount_krw)
    return AdminCreatorPayoutDetail(
        id=payout.id,
        user_id=user.id,
        nickname=None if user.deleted_at is not None else user.nickname,
        withdrawn=user.deleted_at is not None,
        status=payout.status,
        amount_krw=payout.amount_krw,
        for_withdrawal=payout.for_withdrawal,
        withholding=_withholding_view(
            payout.income_tax_rate_bps, payout.income_tax_krw, payout.local_tax_krw, payout.net_amount_krw
        ),
        current_withholding=_withholding_view(
            current.income_tax_rate_bps, current.income_tax_krw, current.local_tax_krw, current.net_amount_krw
        ),
        masked_name=masked_name,
        bank_code=profile.bank_code,
        account_last4=profile.account_last4,
        requested_at=payout.requested_at,
        paid_at=payout.paid_at,
        transferred_on=payout.transferred_on,
        returned_at=payout.returned_at,
        admin_memo=payout.admin_memo,
        return_reason=payout.return_reason,
    )


@router.post("/admin/creator-payout/payouts/{payout_id}/payee-info-view")
async def view_creator_payout_payee_info(
    payout_id: uuid.UUID,
    body: AdminPayeeInfoViewRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPayeeInfoViewResponse:
    """지급 건 수취인의 지급 정보 원문(실명·주민등록번호·은행·계좌번호). 사유가 필요하고, **열람 1회 = 감사 1행**이다 —
    감사 행을 커밋한 뒤에만 원문을 돌려준다. 복호화하지 못하면 409 `CREATOR_PAYOUT_INFO_UNREADABLE`(본 것이 없어 감사 행도
    남기지 않는다). 원문은 이 응답에만 있고 로그·감사 기록·예외 메시지에는 넣지 않는다."""
    _require_reason(body.reason_text)
    payout, profile, _user = await _payout_with_parties(db, payout_id)
    try:
        keyring = payout_keyring()
        response = AdminPayeeInfoViewResponse(
            legal_name=decrypt_field(keyring, profile, "legal_name"),
            rrn=decrypt_field(keyring, profile, "rrn"),
            bank_code=profile.bank_code,
            account_number=decrypt_field(keyring, profile, "account_number"),
        )
    except FieldDecryptError as exc:
        capture_dependency_failure(exc, dependency="creator_payout")
        raise _unreadable() from None
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-info-view",
        target_user_id=payout.user_id,
        reason_category=body.reason_category.value,
        reason_text=body.reason_text,
    )
    await db.commit()
    return response


@router.post("/admin/creator-payout/payouts/{payout_id}/transfer", status_code=status.HTTP_204_NO_CONTENT)
async def record_creator_payout_transfer(
    payout_id: uuid.UUID,
    body: AdminCreatorPayoutTransferRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """은행에서 이체를 마쳤다고 기록한다. 처리 중이 아니면 409 `CREATOR_PAYOUT_NOT_REQUESTED`. 이체일이 신청일(KST)보다
    앞서거나 오늘(KST)보다 뒤면 422 `CREATOR_PAYOUT_TRANSFER_DATE_INVALID`. 금액은 신청 때 이미 잔액에서 빠져 있어 잔액은
    그대로다."""
    payout = await _lock_requested_payout(db, payout_id)
    if not payout.requested_at.astimezone(KST).date() <= body.transferred_on <= datetime.now(KST).date():
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_TRANSFER_DATE_INVALID")
    payout.status = "paid"
    payout.paid_at = await _transaction_now(db)
    payout.transferred_on = body.transferred_on
    payout.admin_memo = body.admin_memo
    payout.decided_by_admin_id = admin_id
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-transfer",
        target_user_id=payout.user_id,
        reason_text=body.admin_memo,
    )
    await db.commit()


@router.post("/admin/creator-payout/payouts/{payout_id}/return", status_code=status.HTTP_204_NO_CONTENT)
async def return_creator_payout(
    payout_id: uuid.UUID,
    body: AdminCreatorPayoutReturnRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """반려한다(지급 정보가 사실과 다름, 이체 실패 등). 사유는 신청자에게 보인다. 처리 중이 아니면 409
    `CREATOR_PAYOUT_NOT_REQUESTED`. 반려된 금액은 잔액(파생값)으로 저절로 돌아온다."""
    _require_reason(body.reason_text)
    payout = await _lock_requested_payout(db, payout_id)
    payout.status = "returned"
    payout.returned_at = await _transaction_now(db)
    payout.return_reason = body.reason_text
    payout.decided_by_admin_id = admin_id
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-return",
        target_user_id=payout.user_id,
        reason_text=body.reason_text,
    )
    await db.commit()
