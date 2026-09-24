"""consent-gate-goal-prompt.md CG-10: `_latest_published_legal_version`·`_reconsent_required`는
`auth/router.py`에서 옮겨온 것이고 판정 로직은 그대로다. `legal/router.py`의 `_latest_published`
(공개 조회·동의 기록용, `requires_reconsent` 필터가 없다)와는 다른 함수이니 혼동하지 말 것."""

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.legal import LegalDocument
from api.db.session import get_db_session
from api.legal.schemas import LegalDocumentKind
from api.session.dependencies import get_current_user_id


async def _latest_published_legal_version(
    db: AsyncSession, kind: str, *, requires_reconsent: bool | None = None
) -> str | None:
    """kind별 최신 게시본의 version. `requires_reconsent`를 주면 그 값으로 게시된 것만
    보고(`GET /me` 재동의 판정용), 안 주면 전체 게시본 중 최신(가입 시점 기록용)."""
    filters = [LegalDocument.kind == kind, LegalDocument.status == "published"]
    if requires_reconsent is not None:
        filters.append(LegalDocument.requires_reconsent.is_(requires_reconsent))
    document = await db.scalar(
        select(LegalDocument).where(*filters).order_by(LegalDocument.published_at.desc()).limit(1)
    )
    return document.version if document is not None else None


def _reconsent_required(current_version: str | None, required_version: str | None) -> bool:
    """`required_version`이 없으면(=`requires_reconsent=true`로 게시된 문서가 아직
    없으면) 재동의가 필요할 수 없다. 있으면 유저가 그 버전 이상으로 동의했는지 본다.

    **`version`이 zero-padded ISO 날짜 문자열이라 문자열 비교가 시간순과 일치한다는
    전제 위에 이 판정 전체가 서 있다** — 다른 포맷의 버전을 쓰면 이 비교가 깨진다.
    그 전제는 서버가 강제한다: `AdminLegalPublishRequest.version`(`api/admin/schemas.py`)의
    `pattern=r"^\d{4}-\d{2}-\d{2}$"`가 이 포맷이 아닌 버전의 게시 자체를 422로 막는다.
    """
    if required_version is None:
        return False
    return current_version is None or current_version < required_version


async def require_legal_consent(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """consent-gate-goal-prompt.md CG-5·CG-6·CG-7: 약관·처리방침 중 하나라도 재동의가
    필요하면 403 + 기계 판독 가능한 detail(CG-6)로 막는다. `get_current_user_id`에는
    재동의(버전) 검사를 끼워넣지 않는다(CG-7) — 그 의존성은 읽기 엔드포인트와 CG-4의
    예외 15개에도 함께 쓰이므로, 거기 넣으면 읽기까지 막힌다. 존재·탈퇴(`deleted_at`)
    확인은 이 제약 밖이라 그쪽이 한다(backlog-sweep-goal-prompt.md BS-3)."""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        # `get_current_user_id`가 같은 조건으로 먼저 401을 내므로 요청 경로에서는 여기 닿지
        # 않는다(backlog-sweep-goal-prompt.md BS-3). 그래도 남긴다 — `db.get`이 `User | None`이라
        # 좁히기는 어차피 필요하고(`assert`면 500이다), 앞 의존성이 바뀌어도 이 게이트가
        # 스스로 막는다. `auth/router.py`의 get_me·withdraw 등 같은 모양의 분기도 같은 이유다.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    required_terms_version = await _latest_published_legal_version(db, "terms", requires_reconsent=True)
    required_privacy_version = await _latest_published_legal_version(
        db, "privacy", requires_reconsent=True
    )

    kinds: list[LegalDocumentKind] = []
    if _reconsent_required(user.terms_version, required_terms_version):
        kinds.append("terms")
    if _reconsent_required(user.privacy_version, required_privacy_version):
        kinds.append("privacy")

    if kinds:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "LEGAL_RECONSENT_REQUIRED", "kinds": kinds},
        )
