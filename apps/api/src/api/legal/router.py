import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.legal import LegalDocument
from api.db.session import get_db_session
from api.legal.schemas import LegalConsentRequest, LegalDocumentKind, LegalDocumentPublicResponse
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/legal", tags=["legal"])


async def _latest_published(db: AsyncSession, kind: str) -> LegalDocument | None:
    """kind별 published 중 published_at 최신 1건 — 공개 조회와 동의 기록 둘 다 "지금
    유효한 게시본"을 같은 방식으로 찾아야 해서 이 파일 안에서만 공유한다(파일 간 헬퍼
    비공유 관례 — apps/api/CLAUDE.md — 는 다른 파일끼리에만 적용된다)."""
    document: LegalDocument | None = await db.scalar(
        select(LegalDocument)
        .where(LegalDocument.kind == kind, LegalDocument.status == "published")
        .order_by(LegalDocument.published_at.desc())
        .limit(1)
    )
    return document


@router.get("/{kind}")
async def get_legal_document(
    kind: LegalDocumentKind, db: AsyncSession = Depends(get_db_session)
) -> LegalDocumentPublicResponse:
    """공개 조회 — 인증 없음. web `/terms`가 최신 게시본을 그대로 보여주는 데 쓴다."""
    document = await _latest_published(db, kind)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published document not found")

    assert document.version is not None  # 게시 행은 admin/legal.py가 항상 version을 채운다
    assert document.published_at is not None  # 게시 행은 admin/legal.py가 항상 published_at을 채운다
    return LegalDocumentPublicResponse(
        kind=kind,
        version=document.version,
        body_markdown=document.body_markdown,
        published_at=document.published_at,
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
    받고, 실제로 기록하는 version은 서버가 다시 조회한 "현재 최신 게시본"의 것이다.

    ⚠️ 정지된 유저는 `get_current_user_id`가 403으로 막아 여기 도달하지 못한다. 정지
    중에도 통과시켜야 할 이유는 없다고 판단했다 — 재동의도 다른 유저 행위와 마찬가지로
    "서비스 이용"의 일부고, 정지가 풀리면 다음 로그인 때 `/me`가 재동의 필요를 다시
    알려주므로 동의 자체를 영영 놓치는 것도 아니다.
    """
    document = await _latest_published(db, payload.kind)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published document not found")

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if payload.kind == "terms":
        user.terms_version = document.version
    else:
        user.privacy_version = document.version

    await db.commit()
    return None
