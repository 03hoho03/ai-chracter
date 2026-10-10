"""어드민 크리에이터 정산 신청 처리: 대기 큐, 승인(첫 승인이면 지난 기간 소급 확정), 거절, 승인 취소. 그리고 지급 처리:
지급 큐·상세(원천징수 미리보기), 지급 정보 원문 열람(사유 + 열람마다 감사 1행), 이체 완료 기록, 반려, 탈퇴한 회원 건의
보류와 수취 정보 교체. 회원 상세의 정산 섹션(신청 이력·잔액·최근 확정·최근 지급).

정산 스위치와 무관하게 열려 있다 — 스위치를 끄기 전에 들어온 신청과 지급, 탈퇴 전에 신청한 지급을 마무리해야 한다.

잠금 순서는 크리에이터 `users` 행 → 신청 행이다. 회원의 신청과 월 확정도 크리에이터 `users` 행을 먼저 잡으므로 같은 사람의
신청·승인·확정이 그 행에서 줄을 선다. 소급 계산은 잠금 없이 읽는다 — 확정은 앞선 확정의 내역 줄을 읽으므로 같은
크리에이터의 확정이 동시에 돌면 안 되는데, 그것을 `users` 행 잠금이 막는다.
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, exists, func, select, update
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
    AdminCreatorPayoutHoldRequest,
    AdminCreatorPayoutItem,
    AdminCreatorPayoutListResponse,
    AdminCreatorPayoutPayeeReplaceRequest,
    AdminCreatorPayoutReturnRequest,
    AdminCreatorPayoutTransferRequest,
    AdminCreatorPayoutWithholding,
    AdminPayeeInfoViewRequest,
    AdminPayeeInfoViewResponse,
    AdminUserCreatorPayoutApplication,
    AdminUserCreatorPayoutConfirmation,
    AdminUserCreatorPayoutPayout,
    AdminUserCreatorPayoutResponse,
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
from api.creator_payout.payout_info import (
    PayoutInfo,
    PayoutInfoRefusal,
    decrypt_field,
    decrypt_profile,
    mask_name,
    new_admin_profile,
    parse_payout_info,
    parse_payout_info_format,
    rrn_birth_date,
)
from api.creator_payout.router import balance_krw
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
    IN_PROGRESS_PAYOUT_STATUSES,
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
# 이체 기록은 지급 행 하나만 잠근다. 잔액은 파생값이라 다른 쓰기와 줄을 설 필요가 없고, 탈퇴 회원의 건도 처리해야 한다.
# 반려·보류·수취 정보 교체는 수취인이 탈퇴했는지에 따라 갈리므로 회원 `users` 행 → 지급 행 순서로 잠근다 — 탈퇴도 그 행을
# 잠그므로, 반려가 "탈퇴하지 않았다"를 본 뒤 탈퇴가 끼어들어 반려된 금액이 갈 곳을 잃는 일이 없다. 실제 이체는 운영자가
# 은행에서 하고 여기서는 그 기록만 남긴다.


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


async def _lock_payout_row(
    db: AsyncSession, payout_id: uuid.UUID, allowed: tuple[CreatorPayoutStatus, ...]
) -> CreatorPayout:
    """지급 행을 잠근다. 상태가 `allowed` 밖이면 409 `CREATOR_PAYOUT_NOT_REQUESTED`."""
    payout = await db.scalar(
        select(CreatorPayout)
        .where(CreatorPayout.id == payout_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if payout is None:
        raise _error(status.HTTP_404_NOT_FOUND, "CREATOR_PAYOUT_NOT_FOUND")
    if payout.status not in allowed:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_NOT_REQUESTED")
    return payout


async def _lock_payout_and_payee(
    db: AsyncSession, payout_id: uuid.UUID, allowed: tuple[CreatorPayoutStatus, ...]
) -> tuple[CreatorPayout, User]:
    """수취인 `users` 행 → 지급 행 순서로 잠근다. 수취인을 먼저 알아야 하므로 지급 행의 `user_id` 는 잠금 없이 읽는다(그
    칸은 바뀌지 않는다)."""
    user_id = await db.scalar(select(CreatorPayout.user_id).where(CreatorPayout.id == payout_id))
    if user_id is None:
        raise _error(status.HTTP_404_NOT_FOUND, "CREATOR_PAYOUT_NOT_FOUND")
    # 회원의 쓰기·탈퇴와 같은 잠금(`lock_active_user`)이라 탈퇴와 줄을 선다.
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    # 회원 행은 탈퇴해도 지우지 않는다.
    assert user is not None
    return await _lock_payout_row(db, payout_id, allowed), user


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
    """지급 건 하나와 마스킹한 수취인, 신청 때의 원천징수와 지금 세율로 다시 계산한 값. 수취인의 암호화한 칸(실명·주민등록번호·
    계좌번호) 중 하나라도 복호화하지 못하면(키 분실 등) 거절하지 않고 `payeeInfoReadable` 거짓·`maskedName` null 로 답한다
    — 원문 열람과 이체 기록이 세 칸을 모두 읽어야 하므로 한 칸만 깨져도 그 둘은 409 다 — 운영자가 그 건을 열어 처리할 수
    있어야 한다. 살아 있는 회원의 건은 반려하고 작가에게 지급 정보를 다시 입력받아 재신청하게 한다. 탈퇴한 회원의 건은
    반려할 수 없어 보류하고 문의로 받은 정보로 수취 정보를 바꾼다(`payee-info`)."""
    payout, profile, user = await _payout_with_parties(db, payout_id)
    masked_name: str | None
    try:
        # 마스킹에는 실명만 쓰지만 세 칸을 다 풀어 본다. 복호화한 값은 이 함수 밖으로 내보내지 않는다.
        masked_name = mask_name(decrypt_profile(payout_keyring(), profile)["legal_name"])
    except FieldDecryptError as exc:
        capture_dependency_failure(exc, dependency="creator_payout")
        masked_name = None
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
        payee_info_readable=masked_name is not None,
        masked_name=masked_name,
        bank_code=profile.bank_code,
        account_last4=profile.account_last4,
        requested_at=payout.requested_at,
        paid_at=payout.paid_at,
        transferred_on=payout.transferred_on,
        returned_at=payout.returned_at,
        held_at=payout.held_at,
        hold_reason=payout.hold_reason,
        admin_memo=payout.admin_memo,
        return_reason=payout.return_reason,
        payee_entered_by_admin=profile.entered_by_admin_id is not None,
        payee_profile_id=profile.id,
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
            payee_profile_id=profile.id,
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
    """은행에서 이체를 마쳤다고 기록한다. 처리 중·보류가 아니면 409 `CREATOR_PAYOUT_NOT_REQUESTED`. 운영자가 보고 이체한
    수취인 판(`payeeProfileId`)이 지금 판과 다르면 409 `CREATOR_PAYOUT_PAYEE_CHANGED` — 그 사이 다른 운영자가 수취 정보를
    바꿨으면 기록이 실제로 돈을 받지 않은 판을 가리키고, 실제로 받은 판은 참조를 잃어 지워지기 때문이다. 이체일이
    신청일(KST)보다 앞서거나 오늘(KST)보다 뒤면 422 `CREATOR_PAYOUT_TRANSFER_DATE_INVALID`. 금액은 신청 때 이미 잔액에서
    빠져 있어 잔액은 그대로다.

    지금 판을 복호화할 수 없으면(키 분실 등, 세 칸 중 하나라도) 409 `CREATOR_PAYOUT_INFO_UNREADABLE` — 지급명세서는 이
    기록이 가리키는 판의 실명·주민등록번호로 쓰므로, 읽을 수 없는 판에 이체를 기록하면 누구에게 지급했는지 신고할 수
    없다. 상세 화면은 이 경우 이체 기록을 숨기지만, 읽히던 때 연 화면에서 보내는 기록은 여기서 막는다. 순서는 상태 409 →
    판 바뀜 409 → 읽을 수 없음 409 → 이체일 422 다 — 판이 바뀌었으면 운영자가 새 판부터 다시 봐야 하고, 읽을 수 없는
    판이면 날짜를 고쳐도 기록할 수 없다."""
    payout = await _lock_payout_row(db, payout_id, IN_PROGRESS_PAYOUT_STATUSES)
    # 수취 정보 교체도 이 지급 행을 잠근 채 판을 바꾸므로, 잠근 뒤 읽은 판 id 는 이 트랜잭션이 끝날 때까지 그대로다.
    if payout.profile_id != body.payee_profile_id:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_PAYEE_CHANGED")
    profile = await db.get(CreatorPayoutProfile, payout.profile_id)
    # 지급 행이 FK 로 가리키는 판이라 있다.
    assert profile is not None
    try:
        decrypt_profile(payout_keyring(), profile)
    except FieldDecryptError as exc:
        capture_dependency_failure(exc, dependency="creator_payout")
        raise _unreadable() from None
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
    `CREATOR_PAYOUT_NOT_REQUESTED`. 반려된 금액은 잔액(파생값)으로 저절로 돌아온다.

    수취인이 탈퇴했으면 409 `CREATOR_PAYOUT_PAYEE_WITHDRAWN` — 탈퇴한 회원은 다시 신청할 수 없어 반려하면 금액이 갈 곳을
    잃는다. 그 건은 보류(`hold`)하고 수취 정보를 바꿔(`payee-info`) 이체한다."""
    _require_reason(body.reason_text)
    payout, user = await _lock_payout_and_payee(db, payout_id, ("requested",))
    if user.deleted_at is not None:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_PAYEE_WITHDRAWN")
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


@router.post("/admin/creator-payout/payouts/{payout_id}/hold", status_code=status.HTTP_204_NO_CONTENT)
async def hold_creator_payout(
    payout_id: uuid.UUID,
    body: AdminCreatorPayoutHoldRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """탈퇴한 회원의 처리 중인 지급을 보류한다 — 등록된 정보로 이체할 수 없어 새 수취 정보를 기다리는 동안. 사유는 운영자만
    본다. 처리 중이 아니면 409 `CREATOR_PAYOUT_NOT_REQUESTED`, 수취인이 탈퇴하지 않았으면 409
    `CREATOR_PAYOUT_PAYEE_NOT_WITHDRAWN`(살아 있는 회원의 건은 반려하면 회원이 다시 신청한다). 보류된 금액은 잔액으로
    돌아오지 않고 그 지급 건에 남아, 수취 정보를 바꾼 뒤 이체한다."""
    _require_reason(body.reason_text)
    payout, user = await _lock_payout_and_payee(db, payout_id, ("requested",))
    if user.deleted_at is None:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_PAYEE_NOT_WITHDRAWN")
    payout.status = "held"
    payout.held_at = await _transaction_now(db)
    payout.hold_reason = body.reason_text
    payout.decided_by_admin_id = admin_id
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-hold",
        target_user_id=payout.user_id,
        reason_text=body.reason_text,
    )
    await db.commit()


@router.put("/admin/creator-payout/payouts/{payout_id}/payee-info", status_code=status.HTTP_204_NO_CONTENT)
async def replace_creator_payout_payee_info(
    payout_id: uuid.UUID,
    body: AdminCreatorPayoutPayeeReplaceRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """탈퇴한 회원의 처리 중·보류 지급의 수취 정보를 운영자가 문의로 받은 새 정보로 바꾼다. 순서: 사유 공백 422 → 처리
    중·보류가 아님 409 `CREATOR_PAYOUT_NOT_REQUESTED` → 수취인이 탈퇴하지 않음 409 `CREATOR_PAYOUT_PAYEE_NOT_WITHDRAWN`(살아
    있는 회원은 반려 뒤 직접 다시 입력한다) → 암호화 키 없음 503 `CREATOR_PAYOUT_UNAVAILABLE` → 형식 422
    `CREATOR_PAYOUT_INFO_INVALID` → 외국인등록번호 422 `CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED` → 주민등록번호의 생년월일이
    지금 수취인 판의 것과 다름 422 `CREATOR_PAYOUT_RRN_MISMATCH`.

    생년월일 대조는 회원 입력의 본인인증 생년월일 대조를 대신한다 — 탈퇴하면 회원의 생년월일이 지워지지만, 지금 판의
    주민등록번호는 입력 때 그 생년월일과 맞춰 본 값이다. 지금 판을 복호화할 수 없으면(키 분실) 대조할 값이 없어 형식만 본다.

    새 판을 넣고 지급 행이 그것을 가리키게 한다 — 지급 행이 가리키는 판이 실제로 이체한 수취인이라 지급명세서가 그 판을
    읽는다. 원천징수는 금액에서 나와 바뀌지 않는다. 앞 판은 내리고, 어느 지급도 가리키지 않게 되면 지운다(탈퇴 때 지급에
    쓰이지 않는 판을 지우는 것과 같은 규칙). 감사 로그에는 사유만 남고 값은 남지 않는다. 상태는 그대로다.
    """
    _require_reason(body.reason_text)
    payout, user = await _lock_payout_and_payee(db, payout_id, IN_PROGRESS_PAYOUT_STATUSES)
    if user.deleted_at is None:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_PAYEE_NOT_WITHDRAWN")
    try:
        keyring = payout_keyring()
    except FieldDecryptError:
        raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, "CREATOR_PAYOUT_UNAVAILABLE") from None
    previous = await db.get(CreatorPayoutProfile, payout.profile_id)
    # 지급 행이 FK 로 가리키는 판이라 있다.
    assert previous is not None
    info: PayoutInfo | PayoutInfoRefusal
    try:
        expected_birth_date = rrn_birth_date(decrypt_field(keyring, previous, "rrn"))
    except FieldDecryptError as exc:
        capture_dependency_failure(exc, dependency="creator_payout")
        info = parse_payout_info_format(
            legal_name=body.legal_name, rrn=body.rrn, bank_code=body.bank_code, account_number=body.account_number
        )
    else:
        info = parse_payout_info(
            legal_name=body.legal_name,
            rrn=body.rrn,
            bank_code=body.bank_code,
            account_number=body.account_number,
            birth_date=expected_birth_date,
        )
    match info:
        case "invalid":
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_INFO_INVALID")
        case "foreigner":
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED")
        case "rrn_mismatch":
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_RRN_MISMATCH")

    # 지금 판을 먼저 내려야 새 판이 "지금 쓰는 판은 하나" 부분 유니크에 걸리지 않는다.
    await db.execute(
        update(CreatorPayoutProfile)
        .where(CreatorPayoutProfile.user_id == user.id, CreatorPayoutProfile.superseded_at.is_(None))
        .values(superseded_at=await _transaction_now(db))
    )
    replacement = new_admin_profile(keyring, info, user_id=user.id, admin_id=admin_id)
    db.add(replacement)
    await db.flush()
    payout.profile_id = replacement.id
    await db.flush()
    await db.execute(
        delete(CreatorPayoutProfile).where(
            CreatorPayoutProfile.id == previous.id,
            ~exists().where(CreatorPayout.profile_id == CreatorPayoutProfile.id),
        )
    )
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-creator-payout-payee-replace",
        target_user_id=user.id,
        reason_text=body.reason_text,
    )
    await db.commit()


# ── 회원 상세 ─────────────────────────────────────────────────────────────────

ADMIN_USER_CONFIRMATION_LIMIT = 12
ADMIN_USER_PAYOUT_LIMIT = 20


@router.get("/admin/users/{user_id}/creator-payout")
async def get_user_creator_payout(
    user_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserCreatorPayoutResponse:
    """회원 상세의 크리에이터 정산 섹션: 신청 이력 전부(최신순), 적립 잔액, 최근 확정 12개, 최근 지급 20개. 없는 회원과
    탈퇴한 회원은 회원 상세와 같이 404 다 — 탈퇴한 회원의 지급은 지급 큐에서 처리한다(지급 상세가 필요한 값을 다 갖는다)."""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    applications = await db.scalars(
        select(CreatorPayoutApplication)
        .where(CreatorPayoutApplication.user_id == user_id)
        .order_by(CreatorPayoutApplication.applied_at.desc(), CreatorPayoutApplication.id)
    )
    confirmations = await db.scalars(
        select(CreatorPayoutConfirmation)
        .where(CreatorPayoutConfirmation.user_id == user_id)
        .order_by(CreatorPayoutConfirmation.window_end.desc(), CreatorPayoutConfirmation.id)
        .limit(ADMIN_USER_CONFIRMATION_LIMIT)
    )
    payouts = await db.scalars(
        select(CreatorPayout)
        .where(CreatorPayout.user_id == user_id)
        .order_by(CreatorPayout.requested_at.desc(), CreatorPayout.id)
        .limit(ADMIN_USER_PAYOUT_LIMIT)
    )
    return AdminUserCreatorPayoutResponse(
        applications=[
            AdminUserCreatorPayoutApplication(
                id=row.id,
                status=row.status,
                applied_at=row.applied_at,
                decided_at=row.decided_at,
                decision_reason=row.decision_reason,
                accrual_start_at=row.accrual_start_at,
                revoked_at=row.revoked_at,
            )
            for row in applications
        ],
        balance_krw=await balance_krw(db, user_id),
        confirmations=[
            AdminUserCreatorPayoutConfirmation(
                id=row.id,
                kind=row.kind,
                period_month=row.period_month,
                window_start=row.window_start,
                window_end=row.window_end,
                gross_units=row.gross_units,
                refunded_units=row.refunded_units,
                rate_bps=row.rate_bps,
                amount_krw=row.amount_krw,
                created_at=row.created_at,
            )
            for row in confirmations
        ],
        payouts=[
            AdminUserCreatorPayoutPayout(
                id=row.id,
                status=row.status,
                amount_krw=row.amount_krw,
                net_amount_krw=row.net_amount_krw,
                requested_at=row.requested_at,
                transferred_on=row.transferred_on,
            )
            for row in payouts
        ],
    )
