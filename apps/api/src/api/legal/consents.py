"""동의 단위(약관, 개인정보 수집·이용, 국외이전)와 그 기록.

동의 단위마다 동의한 판을 `users` 칸 하나에 덮어써 빠르게 판정하고, 같은 동의를 `user_legal_consents` 에 한 행씩 쌓아
과거 판 동의를 남긴다. 가입과 재동의가 둘 다 이 함수들로 기록해 두 곳이 어긋나지 않게 한다.
"""

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import assert_never, get_args

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.legal import LegalDocument, UserLegalConsent
from api.legal import documents
from api.legal.schemas import LegalConsentKind, LegalConsentUnit

CONSENT_UNITS: tuple[LegalConsentUnit, ...] = get_args(LegalConsentUnit)


def consent_kind(unit: LegalConsentUnit) -> LegalConsentKind:
    """동의 단위가 딸린 문서. 수집·이용과 국외이전은 둘 다 처리방침에 적혀 있다."""
    if unit == "terms":
        return "terms"
    if unit == "collection" or unit == "transfer":
        return "privacy"
    assert_never(unit)


def kind_consent_units(kind: str) -> tuple[LegalConsentUnit, ...]:
    """문서가 다시 받을 수 있는 동의 단위. 동의를 기록하지 않는 정책 문서는 빈 튜플이다."""
    return tuple(unit for unit in CONSENT_UNITS if consent_kind(unit) == kind)


def reconsent_scopes(document: LegalDocument) -> list[LegalConsentUnit]:
    """게시본이 다시 받는 동의 단위를 약관 → 수집·이용 → 국외이전 순서로."""
    return [unit for unit in CONSENT_UNITS if unit in document.reconsent_scopes]


def agreed_version(user: User, unit: LegalConsentUnit) -> str | None:
    if unit == "terms":
        return user.terms_version
    if unit == "collection":
        return user.privacy_version
    if unit == "transfer":
        return user.transfer_version
    assert_never(unit)


async def current_consent_documents(
    db: AsyncSession, units: Iterable[LegalConsentUnit], *, now: datetime
) -> dict[LegalConsentUnit, LegalDocument | None]:
    """단위마다 동의할 현행판. 같은 문서의 두 단위는 한 번 조회한 같은 행을 쓴다 — 따로 조회하면 그 사이에 새 판이
    시행될 때 수집·이용과 국외이전이 서로 다른 판으로 기록된다."""
    by_kind: dict[LegalConsentKind, LegalDocument | None] = {}
    result: dict[LegalConsentUnit, LegalDocument | None] = {}
    for unit in units:
        kind = consent_kind(unit)
        if kind not in by_kind:
            by_kind[kind] = await documents.current_legal_document(db, kind, now=now)
        result[unit] = by_kind[kind]
    return result


def apply_consent_versions(
    user: User, consented: Mapping[LegalConsentUnit, LegalDocument | None], *, at: datetime
) -> None:
    """`users` 의 동의 칸에 판 버전과 시각을 적는다. 게시본이 없는 문서는 버전을 비우고 시각만 적는다(가입이 그렇게
    기록해 왔다)."""
    for unit, document in consented.items():
        version = document.version if document is not None else None
        if unit == "terms":
            user.terms_version = version
            user.terms_agreed_at = at
        elif unit == "collection":
            user.privacy_version = version
            user.privacy_agreed_at = at
        elif unit == "transfer":
            user.transfer_version = version
            user.transfer_agreed_at = at
        else:
            assert_never(unit)


def add_consent_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    consented: Mapping[LegalConsentUnit, LegalDocument | None],
    *,
    at: datetime,
) -> None:
    """동의 이력 행을 단위마다 하나 더한다. 게시본이 없는 문서는 가리킬 판이 없어 행을 만들지 않는다. 회원 행이 이미
    flush 된 뒤에 부른다(새 회원은 그때 id 가 정해진다)."""
    for unit, document in consented.items():
        if document is not None:
            db.add(UserLegalConsent(user_id=user_id, legal_document_id=document.id, consent=unit, consented_at=at))


async def replace_signup_consent_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    consented: Mapping[LegalConsentUnit, LegalDocument | None],
    *,
    at: datetime,
) -> None:
    """가입이 받은 동의로 그 회원의 이력을 새로 쓴다. 새 회원이면 행을 더하기만 하는 것과 같다. 이메일 인증을 마치지 않고
    방치된 가입 행을 새 가입(이메일·카카오)이 재사용할 때는 그 행의 이력을 먼저 지운다 — 비밀번호·닉네임·대화 프로필까지
    새 가입으로 갈아 끼우는 자리라, 옛 이력을 남기면 이 회원이 하지 않은 동의가 이 회원의 것으로 남는다."""
    await db.execute(delete(UserLegalConsent).where(UserLegalConsent.user_id == user_id))
    add_consent_history(db, user_id, consented, at=at)
