"""크리에이터 정산의 회원 쪽 HTTP 표면: 신청, 신청 상태·자격·적립 잔액 조회, 확정 내역, 지급 정보 입력, 지급 신청·내역.

정산 스위치가 꺼져 있으면 모든 라우트가 503 `CREATOR_PAYOUT_UNAVAILABLE` 이다. 지급 정보 입력과 지급 신청은 지급 정보
암호화 키도 있어야 받고, 없으면 같은 503 이다(조회 응답의 `payoutAvailable` 이 거짓). 신청·적립·확정·조회는 키와 무관하다.
어드민의 신청·지급 처리(`admin/creator_payout.py`)는 스위치와 무관하다.

지급 정보(실명·주민등록번호·계좌번호)는 암호화해 저장하고, 복호화한 값과 요청 본문을 로그·예외 메시지에 싣지 않는다.
"""

import base64
import binascii
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import case, exists, func, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import lock_active_user
from api.core.config import settings
from api.core.field_crypto import FieldDecryptError
from api.core.identity_gate import identity_verification_required
from api.core.sentry import capture_dependency_failure
from api.creator_payout.config import creator_payout_active, creator_payout_transfer_active, payout_keyring
from api.creator_payout.eligibility import CreatorPayoutBlockReason, load_creator_payout_eligibility
from api.creator_payout.payout_info import decrypt_field, mask_name, new_profile, parse_payout_info
from api.creator_payout.schemas import (
    ApplyCreatorPayoutRequest,
    ApplyCreatorPayoutResponse,
    CreatorPayoutApplicationView,
    CreatorPayoutEligibilityView,
    CreatorPayoutInfoView,
    CreatorPayoutInProgressView,
    CreatorPayoutPayoutsResponse,
    CreatorPayoutPayoutView,
    CreatorPayoutResponse,
    CreatorPayoutStatementLineView,
    CreatorPayoutStatementsResponse,
    CreatorPayoutStatementView,
    PutPayoutInfoRequest,
    RequestPayoutRequest,
    RequestPayoutResponse,
)
from api.creator_payout.tax import withholding
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import ContentVersion
from api.db.models.creator_payout import (
    CreatorPayout,
    CreatorPayoutApplication,
    CreatorPayoutConfirmation,
    CreatorPayoutConfirmationLine,
    CreatorPayoutProfile,
)
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session
from api.legal.dependencies import _latest_published_legal_version, require_legal_consent
from api.payments.notify import PaymentNotifier, get_payment_notifier
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

me_router = APIRouter(prefix="/me/creator-payout", tags=["creator-payout"])

# 운영자 알림 문구. 회원·신청을 알아볼 단서(id·닉네임)는 싣지 않는다 — 결제 알림과 같은 외부 채널이다.
APPLICATION_RECEIVED_MESSAGE = "크리에이터 정산 신청 1건 접수"


def payout_requested_message(amount_krw: int) -> str:
    return f"크리에이터 지급 신청 {amount_krw:,}원 접수"


# 잔액에서 빼는 지급 상태. 반려된 지급은 빼지 않아 금액이 잔액으로 돌아온다.
BALANCE_DEBITING_PAYOUT_STATUSES = ("requested", "paid")

_LIVE_STATUSES = ("pending", "approved")

STATEMENTS_PAGE_SIZE = 20


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
    """신청 상태와 신청 자격, 적립 잔액, 지급 정보 표시값과 처리 중인 지급. 인증·나이·발행 작품이 모자라도 거절하지
    않고 `eligibility` 로 보여 준다(신청과 같은 판정)."""
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
    in_progress = await _in_progress_payout(db, user_id)
    return CreatorPayoutResponse(
        application=None
        if latest is None
        else CreatorPayoutApplicationView(
            status=latest.status,
            applied_at=latest.applied_at,
            decided_at=latest.decided_at,
            decision_reason=latest.decision_reason,
            revoked_at=latest.revoked_at,
        ),
        eligibility=CreatorPayoutEligibilityView(
            identity_verified=eligibility.identity_verified,
            adult=eligibility.adult,
            has_published_work=eligibility.published_count > 0,
            suspended=eligibility.suspended,
        ),
        ever_approved=await _ever_approved(db, user_id),
        balance_krw=await balance_krw(db, user_id),
        rate_bps=settings.creator_payout_rate_bps,
        minimum_payout_krw=settings.creator_payout_minimum_krw,
        payout_available=creator_payout_transfer_active(),
        payout_info=await _payout_info_view(db, user_id),
        in_progress_payout=None
        if in_progress is None
        else CreatorPayoutInProgressView(amount_krw=in_progress.amount_krw, requested_at=in_progress.requested_at),
    )


async def balance_krw(db: AsyncSession, user_id: uuid.UUID) -> int:
    """적립 잔액 = 확정 행 금액의 합 − 처리 중·지급된 지급 금액. 저장하지 않으므로 확정·지급 신청·반려·탈퇴가 잔액을
    따로 고치지 않는다 — 반려는 지급 행 상태만 바꾸면 금액이 돌아온다."""
    confirmed = await db.scalar(
        select(func.coalesce(func.sum(CreatorPayoutConfirmation.amount_krw), 0)).where(
            CreatorPayoutConfirmation.user_id == user_id
        )
    )
    paid_out = await db.scalar(
        select(func.coalesce(func.sum(CreatorPayout.amount_krw), 0)).where(
            CreatorPayout.user_id == user_id, CreatorPayout.status.in_(BALANCE_DEBITING_PAYOUT_STATUSES)
        )
    )
    return int(confirmed or 0) - int(paid_out or 0)


async def _ever_approved(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """승인된 적이 있는가 — 승인 중이거나 승인 취소됨. 승인 취소 뒤에도 확정된 적립금의 지급은 받을 수 있다."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    CreatorPayoutApplication.user_id == user_id,
                    CreatorPayoutApplication.status.in_(("approved", "revoked")),
                )
            )
        )
    )


async def _current_profile(db: AsyncSession, user_id: uuid.UUID) -> CreatorPayoutProfile | None:
    profile: CreatorPayoutProfile | None = await db.scalar(
        select(CreatorPayoutProfile).where(
            CreatorPayoutProfile.user_id == user_id, CreatorPayoutProfile.superseded_at.is_(None)
        )
    )
    return profile


async def _in_progress_payout(db: AsyncSession, user_id: uuid.UUID) -> CreatorPayout | None:
    payout: CreatorPayout | None = await db.scalar(
        select(CreatorPayout).where(CreatorPayout.user_id == user_id, CreatorPayout.status == "requested")
    )
    return payout


_owner_view_decrypt_failure_reported = False


def _report_owner_view_decrypt_failure_once(exc: FieldDecryptError) -> None:
    """작가 조회의 복호화 실패는 프로세스당 한 번만 Bugsink 로 올린다. 키를 잃으면 작가가 화면을 열 때마다 같은 실패가
    나는데, 원인은 하나이고 할 일(키 복구 또는 재입력 요청)도 하나다. 그 뒤로는 경고 로그만 남는다."""
    global _owner_view_decrypt_failure_reported
    if not _owner_view_decrypt_failure_reported:
        _owner_view_decrypt_failure_reported = True
        capture_dependency_failure(exc, dependency="creator_payout")


async def _payout_info_view(db: AsyncSession, user_id: uuid.UUID) -> CreatorPayoutInfoView | None:
    """지금 쓰는 지급 정보의 표시값. 실명을 복호화하지 못하면(키 분실 등) 마스킹 이름만 비우고 나머지를 보인다 — 이
    화면이 실패하면 잔액·내역까지 볼 수 없다. 실패는 값 없이 남긴다."""
    profile = await _current_profile(db, user_id)
    if profile is None:
        return None
    try:
        masked_name: str | None = mask_name(decrypt_field(payout_keyring(), profile, "legal_name"))
    except FieldDecryptError as exc:
        logger.warning("creator payout info could not be decrypted for the owner view")
        _report_owner_view_decrypt_failure_once(exc)
        masked_name = None
    return CreatorPayoutInfoView(
        masked_name=masked_name, bank_code=profile.bank_code, account_last4=profile.account_last4
    )


def _encode_cursor(confirmation: CreatorPayoutConfirmation) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([confirmation.window_end.isoformat(), str(confirmation.id)]).encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        window_end, confirmation_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        decoded = datetime.fromisoformat(window_end), uuid.UUID(confirmation_id)
    except (ValueError, TypeError, AttributeError, binascii.Error):
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_CURSOR_INVALID") from None
    if decoded[0].tzinfo is None:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_CURSOR_INVALID")
    return decoded


async def _content_titles(db: AsyncSession, content_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """작품마다 가장 최근 발행본의 이름. 내려간 작품도 적립 내역에는 남으므로 지금 발행본이 아니라 마지막 발행본을 본다."""
    ids = list(content_ids)
    titles: dict[uuid.UUID, str] = {}
    if not ids:
        return titles
    for detail in (CharacterVersionDetail, StoryVersionDetail):
        rows = await db.execute(
            select(ContentVersion.content_id, detail.name)
            .join(detail, detail.content_version_id == ContentVersion.id)
            .where(ContentVersion.content_id.in_(ids), ContentVersion.published_at.is_not(None))
            .order_by(ContentVersion.published_at.desc())
        )
        for content_id, name in rows:
            titles.setdefault(content_id, name)
    return titles


@me_router.get("/statements")
async def list_creator_payout_statements(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CreatorPayoutStatementsResponse:
    # 확정 내역(소급·월), 최신순 20개. 각 확정의 결제별 내역을 작품으로 합쳐 보인다. 커서가 깨졌으면 422
    # `CREATOR_PAYOUT_CURSOR_INVALID`.
    if not creator_payout_active():
        raise _unavailable()
    query = (
        select(CreatorPayoutConfirmation)
        .where(CreatorPayoutConfirmation.user_id == user_id)
        .order_by(CreatorPayoutConfirmation.window_end.desc(), CreatorPayoutConfirmation.id.desc())
    )
    if cursor is not None:
        # mypy strict 함정(apps/api/CLAUDE.md) — 오른쪽은 평범한 파이썬 튜플로 둔다.
        query = query.where(
            tuple_(CreatorPayoutConfirmation.window_end, CreatorPayoutConfirmation.id) < _decode_cursor(cursor)
        )
    rows = (await db.scalars(query.limit(STATEMENTS_PAGE_SIZE + 1))).all()
    page = rows[:STATEMENTS_PAGE_SIZE]

    # (확정, 작품) 마다 결제별 줄을 합친다. 원 미만은 합친 뒤 한 번 버린다.
    sums: dict[uuid.UUID, dict[uuid.UUID, tuple[int, Decimal, Decimal]]] = defaultdict(dict)
    if page:
        lines = await db.scalars(
            select(CreatorPayoutConfirmationLine).where(
                CreatorPayoutConfirmationLine.confirmation_id.in_([row.id for row in page])
            )
        )
        for line in lines:
            units, adjust, exact = sums[line.confirmation_id].get(line.content_id, (0, Decimal(0), Decimal(0)))
            sums[line.confirmation_id][line.content_id] = (
                units + line.net_units,
                adjust + line.cancel_adjust_krw,
                exact + line.exact_krw,
            )
    titles = await _content_titles(db, {content_id for by_content in sums.values() for content_id in by_content})

    return CreatorPayoutStatementsResponse(
        items=[
            CreatorPayoutStatementView(
                kind=row.kind,
                period_month=row.period_month,
                window_start=row.window_start,
                window_end=row.window_end,
                gross_units=row.gross_units,
                refunded_units=row.refunded_units,
                amount_krw=row.amount_krw,
                lines=[
                    CreatorPayoutStatementLineView(
                        content_id=content_id,
                        content_title=titles.get(content_id, ""),
                        net_units=units,
                        # `int()` 는 0 쪽으로 버린다.
                        cancel_adjust_krw=int(adjust),
                        amount_krw=int(exact),
                    )
                    for content_id, (units, adjust, exact) in sorted(
                        sums[row.id].items(), key=lambda item: (-item[1][2], str(item[0]))
                    )
                ],
            )
            for row in page
        ],
        next_cursor=_encode_cursor(page[-1]) if len(rows) > STATEMENTS_PAGE_SIZE else None,
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


async def _lock_payout_member(db: AsyncSession, user_id: uuid.UUID) -> User:
    """지급 정보 입력·지급 신청의 공통 게이트: 회원 행 잠금(탈퇴 401·정지 403) → 미인증 403 → 만 19세 미만 403 → 승인된
    적 없음 403 `CREATOR_PAYOUT_NOT_APPROVED`. 같은 회원의 지급 정보 변경·지급 신청·탈퇴가 이 행에서 줄을 선다."""
    user = await lock_active_user(db, user_id)
    reason = (await load_creator_payout_eligibility(db, user)).payout_block_reason
    if reason is not None:
        raise _refusal(reason)
    if not await _ever_approved(db, user_id):
        raise _error(status.HTTP_403_FORBIDDEN, "CREATOR_PAYOUT_NOT_APPROVED")
    return user


@me_router.put(
    "/payout-info", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_legal_consent)]
)
async def put_payout_info(
    body: PutPayoutInfoRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """지급 정보를 등록하거나 새로 입력한다(이전 판은 남기고 새 판을 넣는다). 순서: 스위치·암호화 키
    503 → 회원 행 잠금(탈퇴 401·정지 403) → 미인증·만 19세 미만 403 → 승인된 적 없음 403 `CREATOR_PAYOUT_NOT_APPROVED` → 형식 422
    `CREATOR_PAYOUT_INFO_INVALID` → 외국인등록번호 422 `CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED` → 주민등록번호 앞 7자리가
    본인인증 생년월일과 다름 422 `CREATOR_PAYOUT_RRN_MISMATCH` → 처리 중인 지급이 있음 409 `CREATOR_PAYOUT_IN_PROGRESS`
    (처리 중인 건의 수취인을 바꾸지 않는다).

    동의 기록에 남길 처리방침 게시본이 없으면 503 이다.
    """
    if not creator_payout_transfer_active():
        raise _unavailable()
    user = await _lock_payout_member(db, user_id)
    info = parse_payout_info(
        legal_name=body.legal_name,
        rrn=body.rrn,
        bank_code=body.bank_code,
        account_number=body.account_number,
        birth_date=user.birth_date,
    )
    match info:
        case "invalid":
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_INFO_INVALID")
        case "foreigner":
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED")
        case "rrn_mismatch":
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_RRN_MISMATCH")
    if await _in_progress_payout(db, user_id) is not None:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_IN_PROGRESS")
    privacy_version = await _latest_published_legal_version(db, "privacy")
    if privacy_version is None:
        raise _unavailable()

    now = datetime.now(UTC)
    # 지금 판을 먼저 내려야 새 판이 "지금 쓰는 판은 하나" 부분 유니크에 걸리지 않는다.
    await db.execute(
        update(CreatorPayoutProfile)
        .where(CreatorPayoutProfile.user_id == user_id, CreatorPayoutProfile.superseded_at.is_(None))
        .values(superseded_at=now)
    )
    db.add(
        new_profile(
            payout_keyring(),
            info,
            user_id=user_id,
            consented_at=now,
            privacy_version=privacy_version,
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post("/payouts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)])
async def request_payout(
    body: RequestPayoutRequest,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    notifier: PaymentNotifier = Depends(get_payment_notifier),
) -> RequestPayoutResponse:
    """확정 잔액 전액의 지급을 신청한다(금액을 고르지 않는다). 순서: 스위치·암호화 키 503 → 회원 행 잠금(탈퇴 401·정지 403) →
    미인증·만 19세 미만 403 → 승인된 적 없음 403 `CREATOR_PAYOUT_NOT_APPROVED`(승인 취소된 회원은 신청할 수 있다) →
    지급 정보 없음 409 `CREATOR_PAYOUT_INFO_REQUIRED` → 처리 중인 지급이 있음 409 `CREATOR_PAYOUT_IN_PROGRESS` → 잔액 0
    이하 422 `CREATOR_PAYOUT_NOTHING_TO_PAY` → 잔액이 최소 지급액 미만이고 탈퇴 전 신청이 아님 422
    `CREATOR_PAYOUT_BELOW_MINIMUM`(+ `minimumKrw`·`balanceKrw`).

    `forWithdrawal` 은 잔액이 최소액 미만일 때만 쓰인다 — 최소액 이상이면 일반 신청으로 남긴다. 실제로 탈퇴하는지는
    강제하지 않는다(악용해도 최소액 미만을 조금 일찍 받는 것뿐이다). 원천징수 세율·세액은 신청 때 계산해 행에 남긴다.
    """
    if not creator_payout_transfer_active():
        raise _unavailable()
    await _lock_payout_member(db, user_id)
    profile = await _current_profile(db, user_id)
    if profile is None:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_INFO_REQUIRED")
    if await _in_progress_payout(db, user_id) is not None:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_IN_PROGRESS")
    balance = await balance_krw(db, user_id)
    if balance <= 0:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "CREATOR_PAYOUT_NOTHING_TO_PAY")
    minimum = settings.creator_payout_minimum_krw
    below_minimum = balance < minimum
    if below_minimum and not body.for_withdrawal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CREATOR_PAYOUT_BELOW_MINIMUM", "minimumKrw": minimum, "balanceKrw": balance},
        )

    tax = withholding(balance)
    try:
        # 회원 행 잠금을 거치지 않는 쓰기가 생겨도 부분 유니크가 두 번째 처리 중 지급을 막는다. SAVEPOINT 라 그 경우에도
        # 요청 트랜잭션은 살아 있다.
        async with db.begin_nested():
            db.add(
                CreatorPayout(
                    user_id=user_id,
                    profile_id=profile.id,
                    status="requested",
                    amount_krw=balance,
                    for_withdrawal=below_minimum,
                    income_tax_rate_bps=tax.income_tax_rate_bps,
                    income_tax_krw=tax.income_tax_krw,
                    local_tax_krw=tax.local_tax_krw,
                    net_amount_krw=tax.net_amount_krw,
                )
            )
    except IntegrityError:
        raise _error(status.HTTP_409_CONFLICT, "CREATOR_PAYOUT_IN_PROGRESS") from None
    await db.commit()
    background_tasks.add_task(notifier, payout_requested_message(balance))
    return RequestPayoutResponse(
        amount_krw=balance,
        income_tax_krw=tax.income_tax_krw,
        local_tax_krw=tax.local_tax_krw,
        net_amount_krw=tax.net_amount_krw,
    )


@me_router.get("/payouts")
async def list_payouts(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CreatorPayoutPayoutsResponse:
    # 내 지급 신청, 최신순. 처리 중인 지급은 한 번에 하나라 건수가 적어 페이지를 나누지 않는다.
    if not creator_payout_active():
        raise _unavailable()
    rows = await db.scalars(
        select(CreatorPayout)
        .where(CreatorPayout.user_id == user_id)
        .order_by(CreatorPayout.requested_at.desc(), CreatorPayout.id.desc())
    )
    return CreatorPayoutPayoutsResponse(
        items=[
            CreatorPayoutPayoutView(
                id=row.id,
                status=row.status,
                amount_krw=row.amount_krw,
                income_tax_krw=row.income_tax_krw,
                local_tax_krw=row.local_tax_krw,
                net_amount_krw=row.net_amount_krw,
                requested_at=row.requested_at,
                transferred_on=row.transferred_on,
                return_reason=row.return_reason,
            )
            for row in rows
        ]
    )
