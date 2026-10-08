"""휴대폰 본인인증의 HTTP 표면: 인증 시작(인증 id 발급)과 완료(포트원 재조회 후 저장).

브라우저가 말하는 인증 결과를 믿지 않는다 — 완료는 포트원에 그 인증 건을 다시 물어 `VERIFIED` 일 때만 저장한다. 저장하는
것은 CI 의 HMAC·인증 시각·인증된 생년월일뿐이다. CI 원문·이름·전화·통신사·성별·DI·PG 원문 응답은 저장하지 않는다.

인증 id 는 서버가 발급해 Redis 에 그 사용자로 묶어 둔다(1시간). 완료는 그 묶음이 자기 것일 때만 받는다 — 남이 끝낸
인증 id 를 들고 와 자기 계정을 인증하는 것을 막는다. 묶음은 한 시간짜리 일회 상태라 DB 에 두면 버려진 시작 기록을 치울
작업만 하나 는다.
"""

import logging
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from portone_server_sdk.identity_verification import VerifiedIdentityVerification
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.age import is_under_beta_minimum_age, is_under_minimum_age
from api.core.config import settings
from api.core.redis import redis_client
from api.core.security import hash_identity_ci
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.session import get_db_session
from api.identity.schemas import CompleteIdentityVerificationResponse, StartIdentityVerificationResponse
from api.legal.dependencies import require_legal_consent
from api.payments.config import identity_configured, identity_gate_active, payments_active
from api.payments.errors import PortOneUnavailableError
from api.payments.portone import PortOneGateway, get_portone_gateway
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

me_router = APIRouter(prefix="/me", tags=["identity"])

# 인증 창을 열고 끝내기까지 기다리는 상한. 넘기면 처음부터 다시 시작한다.
IDENTITY_VERIFICATION_BINDING_TTL_SECONDS = 60 * 60


def _binding_key(identity_verification_id: str) -> str:
    return f"identity_verification:{identity_verification_id}"


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


async def _require_active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


@me_router.post("/identity-verifications", status_code=status.HTTP_201_CREATED)
async def start_identity_verification(
    _consent: None = Depends(require_legal_consent),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> StartIdentityVerificationResponse:
    """인증 id 를 발급하고 이 사용자에게 묶는다.

    인증 설정이 없거나, 인증을 요구하는 기능(결제·게이트)이 둘 다 꺼져 있으면 503 `IDENTITY_VERIFICATION_UNAVAILABLE` —
    쓰일 곳이 없는 인증으로 개인정보를 받지 않는다. 이미 인증한 계정은 409 `IDENTITY_ALREADY_VERIFIED`.
    """
    if not (identity_configured() and (payments_active() or identity_gate_active())):
        raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, "IDENTITY_VERIFICATION_UNAVAILABLE")
    user = await _require_active_user(db, user_id)
    if user.identity_verified_at is not None:
        raise _error(status.HTTP_409_CONFLICT, "IDENTITY_ALREADY_VERIFIED")

    identity_verification_id = f"idv{uuid.uuid4().hex}"
    await redis_client.set(
        _binding_key(identity_verification_id), str(user_id), ex=IDENTITY_VERIFICATION_BINDING_TTL_SECONDS
    )
    return StartIdentityVerificationResponse(
        identity_verification_id=identity_verification_id,
        store_id=settings.portone_store_id,
        channel_key=settings.portone_identity_channel_key,
    )


def _parse_birth_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@me_router.post("/identity-verifications/{identity_verification_id}/complete")
async def complete_identity_verification(
    identity_verification_id: str,
    _consent: None = Depends(require_legal_consent),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    gateway: PortOneGateway = Depends(get_portone_gateway),
) -> CompleteIdentityVerificationResponse:
    """포트원에 인증 건을 다시 물어 결과를 저장한다.

    거절은 모두 아무것도 저장하지 않는다:
    - 이 사용자에게 묶인 인증 id 가 아니면 404 `IDENTITY_VERIFICATION_NOT_FOUND`.
    - 이미 인증한 계정이면 409 `IDENTITY_ALREADY_VERIFIED` — 묶음이 남은 두 번째 인증 창으로 다른 사람의 인증을 덮어써 계정의
      주인을 바꾸지 못하게 한다.
    - 포트원 조회 실패 502 `PORTONE_UNAVAILABLE`(다시 시도하면 된다).
    - 인증 완료가 아니거나 우리 본인인증 채널이 아니면 422 `IDENTITY_VERIFICATION_NOT_VERIFIED`.
    - CI 가 없으면 422 `IDENTITY_CI_MISSING` — 한 사람 한 계정을 지킬 수 없다.
    - 생년월일이 없거나 읽을 수 없으면 422 `IDENTITY_BIRTH_DATE_MISSING` — 생년월일 없이 덮어쓰면 로그인의 연령 확인이 그
      계정을 매번 실패시킨다.
    - 만 14세 미만이면 403 `IDENTITY_UNDER_MINIMUM_AGE`. CI 도 생년월일도 저장하지 않는다(14세 미만의 개인정보를 받지
      않는다).
    - 같은 사람이 다른 살아 있는 계정으로 이미 인증했으면 409 `IDENTITY_ALREADY_USED`.

    통과하면 CI 해시·인증 시각을 저장하고 생년월일을 인증값으로 덮어쓴다. 나이 판정은 로그인의 연령 확인과 같은 기준(UTC
    날짜)이다. 만 19세 미만으로 인증되면 베타 참가 자격을 같은 트랜잭션에서 거둔다 — 베타는 성인만 받는데 지정 때의 자기
    신고 생년월일만 확인했다.
    """
    bound_user_id = await redis_client.get(_binding_key(identity_verification_id))
    if bound_user_id != str(user_id):
        raise _error(status.HTTP_404_NOT_FOUND, "IDENTITY_VERIFICATION_NOT_FOUND")
    user = await _require_active_user(db, user_id)
    if user.identity_verified_at is not None:
        raise _error(status.HTTP_409_CONFLICT, "IDENTITY_ALREADY_VERIFIED")

    try:
        verification = await gateway.get_identity_verification(identity_verification_id)
    except PortOneUnavailableError as exc:
        logger.warning("identity verification could not reach portone: %s", exc)
        capture_dependency_failure(exc, dependency="portone")
        raise _error(status.HTTP_502_BAD_GATEWAY, "PORTONE_UNAVAILABLE") from None

    if not isinstance(verification, VerifiedIdentityVerification):
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "IDENTITY_VERIFICATION_NOT_VERIFIED")
    if verification.channel is not None and verification.channel.key != settings.portone_identity_channel_key:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "IDENTITY_VERIFICATION_NOT_VERIFIED")
    customer = verification.verified_customer
    if not customer.ci:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "IDENTITY_CI_MISSING")
    birth_date = _parse_birth_date(customer.birth_date)
    if birth_date is None:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "IDENTITY_BIRTH_DATE_MISSING")
    today = datetime.now(UTC).date()
    if is_under_minimum_age(birth_date, today):
        raise _error(status.HTTP_403_FORBIDDEN, "IDENTITY_UNDER_MINIMUM_AGE")

    ci_hmac = hash_identity_ci(customer.ci)
    taken = await db.scalar(
        select(User.id).where(User.identity_ci_hmac == ci_hmac, User.deleted_at.is_(None), User.id != user_id)
    )
    if taken is not None:
        raise _error(status.HTTP_409_CONFLICT, "IDENTITY_ALREADY_USED")

    verified_at = datetime.now(UTC)
    try:
        # 위 조회와 이 쓰기 사이에 다른 계정이 같은 CI 로 인증을 마치면 부분 유니크가 막는다. SAVEPOINT 라 그 경우에도 요청
        # 트랜잭션은 살아 있다.
        async with db.begin_nested():
            user.identity_ci_hmac = ci_hmac
            user.identity_verified_at = verified_at
            user.birth_date = birth_date
            if is_under_beta_minimum_age(birth_date, today):
                user.beta_joined_at = None
    except IntegrityError:
        raise _error(status.HTTP_409_CONFLICT, "IDENTITY_ALREADY_USED") from None
    await db.commit()
    await redis_client.delete(_binding_key(identity_verification_id))
    return CompleteIdentityVerificationResponse(verified_at=verified_at)
