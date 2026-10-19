import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import lock_active_user
from api.db.session import get_db_session
from api.legal import consents, documents
from api.legal.schemas import (
    LegalChangeItem,
    LegalChangesResponse,
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
            version=upcoming.version,
            effective_at=documents.effective_order(upcoming)[0],
            change_notice=upcoming.change_notice_markdown,
        )
    return LegalDocumentPublicResponse(
        kind=kind,
        version=document.version,
        body_markdown=document.body_markdown,
        published_at=published_at,
        effective_at=effective_at,
        change_notice=document.change_notice_markdown,
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
        change_notice=document.change_notice_markdown,
    )


@router.get("/{kind}/changes")
async def list_legal_document_changes(
    kind: LegalDocumentKind,
    since: str | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> LegalChangesResponse:
    """누적 변경 안내 — 인증 없음. `since` 판보다 뒤에 시행된 판들의 변경 안내를 최신 판부터 준다. 재동의 화면이 회원이
    마지막으로 동의한 판을 `since` 로 넘겨, 그 뒤로 바뀐 것을 재동의가 걸리지 않은 판까지 모두 보여 준다(지금 동의하는
    대상은 최신 전문 전체라 그 안에 다 들어 있다). 시행 예정 판과 철회본은 들지 않는다.

    `since` 가 없거나 시행된 판에서 찾지 못하면 시행된 판 전부를 준다 — 모르는 판을 기준으로 아무것도 안 보여 주는 것보다
    전부 보여 주는 쪽이 안전하다. 판의 앞뒤는 버전 문자열이 아니라 시행 순서로 정한다."""
    effective = await documents.effective_legal_documents(db, kind, now=documents.utcnow())
    since_document = next((document for document in effective if document.version == since), None)
    if since_document is not None:
        since_order = documents.effective_order(since_document)
        effective = [document for document in effective if documents.effective_order(document) > since_order]

    items = []
    for document in effective:
        assert document.version is not None  # 게시 행은 admin/legal.py가 항상 version을 채운다
        items.append(
            LegalChangeItem(
                version=document.version,
                effective_at=documents.effective_order(document)[0],
                change_notice=document.change_notice_markdown,
                reconsent_scopes=consents.reconsent_scopes(document),
            )
        )
    return LegalChangesResponse(items=items)


@router.post("/consent", status_code=status.HTTP_204_NO_CONTENT)
async def consent_legal_document(
    payload: LegalConsentRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """재동의 기록. 동의 단위(`consents`)마다 그 문서의 현행판 버전을 `users` 칸에 적고 동의 이력 행을 하나씩 더한다.

    **요청은 버전을 받지 않는다** — 클라이언트가 보낸 버전을 기록하면 실제로 게시된 적 없는 버전이
    `users.terms_version`에 남아 `GET /me`의 재동의 판정을 영구히 우회할 수 있다. 그래서 어떤 동의인지만
    받고, 실제로 기록하는 version은 서버가 다시 조회한 현행판의 것이다(시행 예정 판이 아니다).

    **회원 행을 잠그고 탈퇴 여부를 다시 본 뒤 쓴다.** 잠그지 않으면 탈퇴와 겹친 요청이 탈퇴 커밋을 기다렸다가 이력 행을
    넣어(회원 행은 지우지 않으므로 FK 검사도 통과한다) 탈퇴 뒤에 그 회원의 동의 이력이 남는다.

    ⚠️ 정지된 유저는 `get_current_user_id`가 403으로 막아 여기 도달하지 못한다. 정지
    중에도 통과시켜야 할 이유는 없다고 판단했다 — 재동의도 다른 유저 행위와 마찬가지로
    "서비스 이용"의 일부고, 정지가 풀리면 다음 로그인 때 `/me`가 재동의 필요를 다시
    알려주므로 동의 자체를 영영 놓치는 것도 아니다.
    """
    units = list(dict.fromkeys(payload.consents))
    consented = await consents.current_consent_documents(db, units, now=documents.utcnow())
    if any(document is None for document in consented.values()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published document not found")

    user = await lock_active_user(db, user_id)
    now = datetime.now(UTC)
    consents.apply_consent_versions(user, consented, at=now)
    consents.add_consent_history(db, user.id, consented, at=now)
    await db.commit()
    return None
