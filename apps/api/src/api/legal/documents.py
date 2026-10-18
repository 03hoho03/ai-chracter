"""법무 문서의 현행판·시행 예정 판을 고르는 규칙의 유일한 자리.

게시본은 게시(공지) 시각 `published_at` 과 시행 시각 `effective_at` 을 따로 갖는다. **현행판**은 시행 시각이 지난 게시본
가운데 가장 늦게 시행된 것(시행 시각이 같으면 늦게 게시된 것)이고, **시행 예정 판**은 시행 시각이 아직 오지 않은 게시본이다.
철회본(`withdrawn`)은 어느 쪽에도 들지 않는다. 판의 앞뒤도 같은 순서로 정한다 — 버전 문자열은 순번 접미사(`.2`, `.10`)가
붙으면 문자열 순서가 시간 순서와 어긋나므로 순서 판단에 쓰지 않는다.

공개 조회, 재동의 판정, 가입·결제·정산 신청이 기록하는 동의 버전, 어드민의 "현재 게시본"이 모두 이 함수들을 부른다. 한
곳이라도 따로 조회하면 시행 예정 판이 그 경로로 먼저 새어 나간다.

`now` 를 인자로 받고 SQL `now()` 를 쓰지 않는다. 요청 경로는 `utcnow()` 를 넘긴다. 테스트는 한 테스트를 한 트랜잭션으로
감싸 SQL `now()` 가 테스트 시작 시각에 고정되므로, 테스트 안에서 방금 게시한 판이 SQL 기준으로는 "아직 시행 전"이 된다.
"""

from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.legal import LegalDocument


def utcnow() -> datetime:
    """법무 문서의 현행 여부를 가르는 시각. 호출부는 모듈 속성으로 불러(`documents.utcnow()`) 테스트가
    `monkeypatch.setattr` 로 시계를 시행 시각 앞뒤로 옮길 수 있게 한다."""
    return datetime.now(UTC)


def _published_in_order(kind: str) -> Select[tuple[LegalDocument]]:
    return (
        select(LegalDocument)
        .where(LegalDocument.kind == kind, LegalDocument.status == "published")
        .order_by(LegalDocument.effective_at.desc(), LegalDocument.published_at.desc())
    )


def effective_order(document: LegalDocument) -> tuple[datetime, datetime]:
    """판의 앞뒤를 정하는 키. 위 조회의 정렬과 같은 두 칸이다."""
    assert document.effective_at is not None  # 초안이 아닌 행은 CHECK 가 채워 둔다
    assert document.published_at is not None  # 게시 경로가 항상 채운다
    return (document.effective_at, document.published_at)


async def current_legal_document(
    db: AsyncSession, kind: str, *, now: datetime, requires_reconsent: bool | None = None
) -> LegalDocument | None:
    """kind 의 현행판. `requires_reconsent=True` 를 주면 시행된 재동의 요구 판 가운데 가장 늦은 것(재동의 기준 판)을 준다."""
    query = _published_in_order(kind).where(LegalDocument.effective_at <= now)
    if requires_reconsent is not None:
        query = query.where(LegalDocument.requires_reconsent.is_(requires_reconsent))
    document: LegalDocument | None = await db.scalar(query.limit(1))
    return document


async def current_legal_version(db: AsyncSession, kind: str, *, now: datetime) -> str | None:
    """동의 기록(가입·결제·정산 신청)에 남길 현행판 버전. 게시본이 없으면 None."""
    document = await current_legal_document(db, kind, now=now)
    return document.version if document is not None else None


async def upcoming_legal_document(db: AsyncSession, kind: str, *, now: datetime) -> LegalDocument | None:
    """kind 의 시행 예정 판. 게시 경로가 kind 마다 하나만 허용하므로 많아야 하나다."""
    document: LegalDocument | None = await db.scalar(
        _published_in_order(kind).where(LegalDocument.effective_at > now).limit(1)
    )
    return document


async def published_legal_document(db: AsyncSession, kind: str, version: str) -> LegalDocument | None:
    """버전 문자열에 해당하는 게시본. 회원이 동의한 판을 찾을 때 쓴다 — 철회본은 시행된 적이 없어 아무도 동의할 수 없다."""
    document: LegalDocument | None = await db.scalar(
        select(LegalDocument).where(
            LegalDocument.kind == kind, LegalDocument.status == "published", LegalDocument.version == version
        )
    )
    return document
