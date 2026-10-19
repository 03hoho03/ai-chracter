"""재동의 판정과 그 판정으로 쓰기를 막는 게이트. `GET /me` 의 재동의 플래그도 같은 판정 함수를 부른다."""

import uuid
from datetime import datetime

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.session import get_db_session
from api.legal import consents, documents
from api.legal.schemas import LegalConsentUnit
from api.session.dependencies import get_current_user_id


async def _reconsent_required(
    db: AsyncSession, unit: LegalConsentUnit, agreed_version: str | None, *, now: datetime
) -> bool:
    """회원이 그 동의 단위로 동의한 판이 그 단위의 재동의 기준 판(그 단위를 다시 받은 시행된 판 중 가장 늦은 것)보다
    앞이면 재동의가 필요하다. 단위마다 따로 본다 — 처리방침이 국외이전 동의만 다시 받으면 수집·이용 동의는 옛 판이어도
    막지 않는다.

    판의 앞뒤는 버전 문자열이 아니라 시행 시각(같으면 게시 시각)으로 정한다 — 같은 날 다시 게시한 판에는 순번 접미사가
    붙어 `2026-10-18.10` 이 문자열로는 `2026-10-18.2` 보다 앞이 된다. 그래서 회원이 동의한 버전 문자열을 게시본에서
    찾아 그 행의 시행 시각을 본다. **게시본에서 찾지 못한 버전은 미동의로 본다** — 동의로 보면 DB 직접 수정이나 오타로
    들어간 버전이 게이트를 영영 우회한다.
    """
    kind = consents.consent_kind(unit)
    required = await documents.current_legal_document(db, kind, now=now, reconsent_scope=unit)
    if required is None:
        return False
    if agreed_version is None:
        return True
    agreed = await documents.published_legal_document(db, kind, agreed_version)
    if agreed is None:
        return True
    return documents.effective_order(agreed) < documents.effective_order(required)


async def reconsent_required_units(db: AsyncSession, user: User, *, now: datetime) -> list[LegalConsentUnit]:
    """재동의가 필요한 동의 단위를 약관 → 수집·이용 → 국외이전 순서로. 게이트의 403 과 `GET /me` 의 플래그가 이 값이다."""
    return [
        unit
        for unit in consents.CONSENT_UNITS
        if await _reconsent_required(db, unit, consents.agreed_version(user, unit), now=now)
    ]


async def require_legal_consent(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """동의 단위 중 하나라도 재동의가
    필요하면 403 + 기계 판독 가능한 detail로 막는다. detail 의 `consents` 는 다시 받을 동의 단위다. `get_current_user_id`에는
    재동의(버전) 검사를 끼워넣지 않는다 — 그 의존성은 읽기 엔드포인트와 재동의 전에도
    허용하는 쓰기 예외에도 함께 쓰이므로, 거기 넣으면 읽기까지 막힌다. 존재·탈퇴(`deleted_at`)
    확인은 이 제약 밖이라 그쪽이 한다."""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        # `get_current_user_id`가 같은 조건으로 먼저 401을 내므로 요청 경로에서는 여기 닿지
        # 않는다. 그래도 남긴다 — `db.get`이 `User | None`이라
        # 좁히기는 어차피 필요하고(`assert`면 500이다), 앞 의존성이 바뀌어도 이 게이트가
        # 스스로 막는다. `auth/router.py`의 get_me·withdraw 등 같은 모양의 분기도 같은 이유다.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    units = await reconsent_required_units(db, user, now=documents.utcnow())
    if units:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "LEGAL_RECONSENT_REQUIRED", "consents": units},
        )
