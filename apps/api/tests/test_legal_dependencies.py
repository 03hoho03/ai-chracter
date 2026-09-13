"""`api/legal/dependencies.py`의 `require_legal_consent` 단독 테스트.

consent-gate-goal-prompt.md S1: 이 단계에서는 어떤 엔드포인트에도 아직 안 붙는다(S2가 붙인다).
그래서 HTTP 라운드트립으로는 테스트할 수 없다 — 테스트 전용 임시 라우트를 새로 만드는 대신,
`require_legal_consent`가 평범한 async 함수라는 점을 이용해 `Depends(...)` 기본값을 무시하고
`user_id`/`db`를 직접 넘겨 호출한다. `app.dependency_overrides`는 "앱에 이미 걸린 의존성을
갈아끼운다"는 것이라, 아직 아무 라우트에도 안 걸린 의존성 자체를 단위 테스트하는 이 상황에는
맞지 않는다.
"""

from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import LegalDocument
from api.legal.dependencies import require_legal_consent
from factories import _make_published, _make_user


async def _clear_published_legal_documents(db_session: AsyncSession) -> None:
    """migration c49014ae5b62가 terms·privacy 둘 다 `requires_reconsent=True`로 시드해둔다
    (test_legal_public_api.py의 같은 관례 참고) — 각 케이스가 어떤 kind를 미동의로 만들지
    직접 통제하려면 그 시드부터 지워야 한다."""
    await db_session.execute(delete(LegalDocument))


async def test_require_legal_consent_blocks_when_terms_unconsented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)

    with pytest.raises(HTTPException) as exc_info:
        await require_legal_consent(user_id=user.id, db=db_session)

    assert exc_info.value.status_code == 403
    # HTTPException.detail은 starlette 스텁상 str이지만 실제로는 dict을 그대로 담아 보낸다
    # (기존 라우터들의 detail={"reason": ...} 관례와 같다) — cast로 그 간극만 메운다.
    assert cast(dict[str, object], exc_info.value.detail) == {
        "code": "LEGAL_RECONSENT_REQUIRED",
        "kinds": ["terms"],
    }


async def test_require_legal_consent_blocks_when_privacy_unconsented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="privacy", version="2099-01-01", requires_reconsent=True)

    with pytest.raises(HTTPException) as exc_info:
        await require_legal_consent(user_id=user.id, db=db_session)

    assert exc_info.value.status_code == 403
    assert cast(dict[str, object], exc_info.value.detail) == {
        "code": "LEGAL_RECONSENT_REQUIRED",
        "kinds": ["privacy"],
    }


async def test_require_legal_consent_blocks_when_both_unconsented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await _make_published(db_session, kind="privacy", version="2099-02-01", requires_reconsent=True)

    with pytest.raises(HTTPException) as exc_info:
        await require_legal_consent(user_id=user.id, db=db_session)

    assert exc_info.value.status_code == 403
    assert cast(dict[str, object], exc_info.value.detail) == {
        "code": "LEGAL_RECONSENT_REQUIRED",
        "kinds": ["terms", "privacy"],
    }


async def test_require_legal_consent_passes_when_both_consented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user(terms_version="2099-01-01", privacy_version="2099-02-01")
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await _make_published(db_session, kind="privacy", version="2099-02-01", requires_reconsent=True)

    await require_legal_consent(user_id=user.id, db=db_session)  # 예외 없이 통과하면 성공
