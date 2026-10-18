"""`api/legal/dependencies.py`의 `require_legal_consent` 단독 테스트.

작성 당시에는 어떤 엔드포인트에도 아직 안 붙어 있었다(지금은 쓰기 라우트들에 붙어 있다).
그래서 HTTP 라운드트립으로는 테스트할 수 없었다 — 테스트 전용 임시 라우트를 새로 만드는 대신,
`require_legal_consent`가 평범한 async 함수라는 점을 이용해 `Depends(...)` 기본값을 무시하고
`user_id`/`db`를 직접 넘겨 호출한다. `app.dependency_overrides`는 "앱에 이미 걸린 의존성을
갈아끼운다"는 것이라, 당시 아무 라우트에도 안 걸려 있던 의존성 자체를 단위 테스트하는 이 상황에는
맞지 않는다.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import LegalDocument
from api.legal import documents
from api.legal.dependencies import reconsent_required_units, require_legal_consent
from factories import _make_published, _make_user


async def _clear_published_legal_documents(db_session: AsyncSession) -> None:
    """migration c49014ae5b62가 terms·privacy 둘 다 `requires_reconsent=True`로 시드해둔다
    (test_legal_public_api.py의 같은 관례 참고) — 각 케이스가 어떤 kind를 미동의로 만들지
    직접 통제하려면 그 시드부터 지워야 한다."""
    await db_session.execute(delete(LegalDocument))


async def test_require_legal_consent_blocks_when_terms_unconsented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user(terms_version=None)
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
        "consents": ["terms"],
    }


async def test_require_legal_consent_blocks_when_privacy_unconsented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user(privacy_version=None)
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="privacy", version="2099-01-01", requires_reconsent=True)

    with pytest.raises(HTTPException) as exc_info:
        await require_legal_consent(user_id=user.id, db=db_session)

    assert exc_info.value.status_code == 403
    assert cast(dict[str, object], exc_info.value.detail) == {
        "code": "LEGAL_RECONSENT_REQUIRED",
        "consents": ["collection", "transfer"],
    }


async def test_require_legal_consent_blocks_when_both_unconsented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user(terms_version=None, privacy_version=None)
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await _make_published(db_session, kind="privacy", version="2099-02-01", requires_reconsent=True)

    with pytest.raises(HTTPException) as exc_info:
        await require_legal_consent(user_id=user.id, db=db_session)

    assert exc_info.value.status_code == 403
    assert cast(dict[str, object], exc_info.value.detail) == {
        "code": "LEGAL_RECONSENT_REQUIRED",
        "consents": ["terms", "collection", "transfer"],
    }


async def test_require_legal_consent_passes_when_both_consented(db_session: AsyncSession) -> None:
    await _clear_published_legal_documents(db_session)
    user = _make_user(terms_version="2099-01-01", privacy_version="2099-02-01", transfer_version="2099-02-01")
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await _make_published(db_session, kind="privacy", version="2099-02-01", requires_reconsent=True)

    await require_legal_consent(user_id=user.id, db=db_session)  # 예외 없이 통과하면 성공


@pytest.mark.parametrize("kind", ["operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"])
async def test_require_legal_consent_ignores_policy_kind_marked_reconsent(
    db_session: AsyncSession, kind: str
) -> None:
    """게이트는 약관·처리방침의 동의 단위만 요구한다 — 정책 문서 행에 재동의 범위가 들어가 있어도(게시 경로는 막지만
    DB 직접 수정 등으로) 두 문서에 동의한 회원은 막히지 않는다."""
    await _clear_published_legal_documents(db_session)
    user = _make_user(terms_version="2099-01-01", privacy_version="2099-02-01", transfer_version="2099-02-01")
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await _make_published(db_session, kind="privacy", version="2099-02-01", requires_reconsent=True)
    await _make_published(db_session, kind=kind, version="2099-12-31", reconsent_scopes=["terms", "collection", "transfer"])

    await require_legal_consent(user_id=user.id, db=db_session)  # 예외 없이 통과하면 성공


async def test_same_day_editions_are_ordered_by_effective_time_not_by_version_string(
    db_session: AsyncSession,
) -> None:
    """같은 날 열 번째 판 `.10` 은 두 번째 판 `.2` 보다 뒤다. 깨지는 시나리오: 버전을 문자열로 비교하면
    `"2026-10-18.10" < "2026-10-18.2"` 라서, `.10` 에 동의한 회원이 앞선 `.2` 재동의에 다시 막히고(약관), 뒤에 나온
    `.10` 재동의를 `.2` 에 동의한 회원이 건너뛴다(처리방침)."""
    await _clear_published_legal_documents(db_session)
    earlier = datetime.now(UTC) - timedelta(hours=2)
    later = earlier + timedelta(hours=1)
    await _make_published(
        db_session, kind="terms", version="2026-10-18.2", requires_reconsent=True, published_at=earlier
    )
    await _make_published(db_session, kind="terms", version="2026-10-18.10", published_at=later)
    await _make_published(db_session, kind="privacy", version="2026-10-18.2", published_at=earlier)
    await _make_published(
        db_session, kind="privacy", version="2026-10-18.10", requires_reconsent=True, published_at=later
    )
    user = _make_user(terms_version="2026-10-18.10", privacy_version="2026-10-18.2", transfer_version="2026-10-18.10")

    assert await reconsent_required_units(db_session, user, now=datetime.now(UTC)) == ["collection"]


async def test_version_missing_from_published_documents_counts_as_unconsented(db_session: AsyncSession) -> None:
    """회원이 동의한 버전 문자열이 게시본에 없으면 미동의다. 깨지는 시나리오: DB 직접 수정이나 오타로 들어간 버전을
    동의로 읽어 재동의 게이트를 영영 건너뛴다. 시드 판(`_make_user` 기본값)에 동의한 회원은 그대로 통과한다."""
    consented = _make_user()
    unknown = _make_user(terms_version="2026-10-17", privacy_version="2026-10-17", transfer_version="2026-10-17")

    assert await reconsent_required_units(db_session, consented, now=datetime.now(UTC)) == []
    assert await reconsent_required_units(db_session, unknown, now=datetime.now(UTC)) == [
        "terms",
        "collection",
        "transfer",
    ]


async def test_scheduled_reconsent_edition_applies_only_once_its_effective_time_passes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시행 예정인 재동의 판은 시행 전에는 아무도 막지 않고, 시계가 시행 시각을 넘으면 그 판에 동의하지 않은 회원을
    막는다. 깨지는 시나리오: 판정이 시행 시각을 보지 않아 예약하자마자 전원이 재동의 모달에 갇힌다."""
    effective_at = datetime.now(UTC) + timedelta(days=30)
    await _make_published(
        db_session, kind="terms", version="2026-11-17", requires_reconsent=True, effective_at=effective_at
    )
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    assert await reconsent_required_units(db_session, user, now=effective_at - timedelta(seconds=1)) == []
    assert await reconsent_required_units(db_session, user, now=effective_at) == ["terms"]

    await require_legal_consent(user_id=user.id, db=db_session)  # 지금은 시행 전이라 통과한다
    monkeypatch.setattr(documents, "utcnow", lambda: effective_at + timedelta(minutes=1))
    with pytest.raises(HTTPException) as exc_info:
        await require_legal_consent(user_id=user.id, db=db_session)
    assert cast(dict[str, object], exc_info.value.detail) == {
        "code": "LEGAL_RECONSENT_REQUIRED",
        "consents": ["terms"],
    }
