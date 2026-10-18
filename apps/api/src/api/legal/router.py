import uuid
from datetime import UTC, datetime
from typing import assert_never

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.session import get_db_session
from api.legal import documents
from api.legal.schemas import (
    LegalConsentRequest,
    LegalDocumentKind,
    LegalDocumentPublicResponse,
    LegalUpcomingDocumentResponse,
    LegalUpcomingSummary,
)
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/{kind}")
async def get_legal_document(
    kind: LegalDocumentKind, db: AsyncSession = Depends(get_db_session)
) -> LegalDocumentPublicResponse:
    """공개 조회 — 인증 없음. web `/terms` 등이 현행판을 보여 주는 데 쓴다. 시행 예정 판이 있으면 그 버전과 시행 시각을
    `upcoming` 으로 곁들인다(시행일 전 게시를 알리기 위해서다)."""
    now = documents.utcnow()
    document = await documents.current_legal_document(db, kind, now=now)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published document not found")
    upcoming = await documents.upcoming_legal_document(db, kind, now=now)

    assert document.version is not None  # 게시 행은 admin/legal.py가 항상 version을 채운다
    effective_at, published_at = documents.effective_order(document)
    upcoming_summary = None
    if upcoming is not None:
        assert upcoming.version is not None  # 위와 같다
        upcoming_summary = LegalUpcomingSummary(
            version=upcoming.version, effective_at=documents.effective_order(upcoming)[0]
        )
    return LegalDocumentPublicResponse(
        kind=kind,
        version=document.version,
        body_markdown=document.body_markdown,
        published_at=published_at,
        effective_at=effective_at,
        upcoming=upcoming_summary,
    )


@router.get("/{kind}/upcoming")
async def get_upcoming_legal_document(
    kind: LegalDocumentKind, db: AsyncSession = Depends(get_db_session)
) -> LegalUpcomingDocumentResponse:
    """시행 예정 판의 전문 — 인증 없음. 없으면 404."""
    document = await documents.upcoming_legal_document(db, kind, now=documents.utcnow())
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upcoming document not found")

    assert document.version is not None  # 게시 행은 admin/legal.py가 항상 version을 채운다
    effective_at, published_at = documents.effective_order(document)
    return LegalUpcomingDocumentResponse(
        kind=kind,
        version=document.version,
        body_markdown=document.body_markdown,
        published_at=published_at,
        effective_at=effective_at,
    )


@router.post("/consent", status_code=status.HTTP_204_NO_CONTENT)
async def consent_legal_document(
    payload: LegalConsentRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """재동의 기록. **요청의 `version`은 신뢰하지 않는다** — 클라이언트가 값을 조작해
    보내면 실제로 게시된 적 없는 버전이 `users.terms_version`에 남아 `GET /me`의
    재동의 판정을 영구히 우회할 수 있다. 그래서 body의 `kind`로 어떤 문서에 동의했는지만
    받고, 실제로 기록하는 version은 서버가 다시 조회한 현행판의 것이다(시행 예정 판이 아니다).

    ⚠️ 정지된 유저는 `get_current_user_id`가 403으로 막아 여기 도달하지 못한다. 정지
    중에도 통과시켜야 할 이유는 없다고 판단했다 — 재동의도 다른 유저 행위와 마찬가지로
    "서비스 이용"의 일부고, 정지가 풀리면 다음 로그인 때 `/me`가 재동의 필요를 다시
    알려주므로 동의 자체를 영영 놓치는 것도 아니다.
    """
    document = await documents.current_legal_document(db, payload.kind, now=documents.utcnow())
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published document not found")

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    now = datetime.now(UTC)
    if payload.kind == "terms":
        user.terms_version = document.version
        user.terms_agreed_at = now
    elif payload.kind == "privacy":
        user.privacy_version = document.version
        user.privacy_agreed_at = now
        # 국외이전 동의는 처리방침 버전에 묶인다.
        # 이미 위에서 조회해 둔 document(privacy 게시본)를 그대로 재사용한다 — 여기서
        # 현행판을 다시 조회하면 그 사이 재게시·시행될 경우 privacy·transfer 버전이
        # 어긋날 수 있다.
        user.transfer_version = document.version
        user.transfer_agreed_at = now
    else:
        # 동의 종류가 늘면 여기서 mypy 가 멈춘다 — 새 종류를 기존 분기에 흘려 넣으면
        # 다른 문서의 동의 버전을 덮어쓰게 된다.
        assert_never(payload.kind)

    await db.commit()
    return None
