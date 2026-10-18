import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminLegalDocumentResponse,
    AdminLegalDraftItem,
    AdminLegalDraftUpsertRequest,
    AdminLegalPublishedItem,
    AdminLegalPublishRequest,
    AdminLegalVersionItem,
    AdminLegalVersionsResponse,
    AdminLegalVersionState,
)
from api.db.models.legal import LegalDocument
from api.db.session import get_db_session
from api.legal import consents, documents
from api.legal.schemas import LegalConsentUnit, LegalDocumentKind

router = APIRouter(tags=["admin"])


def _requested_reconsent_scopes(kind: LegalDocumentKind, body: AdminLegalPublishRequest) -> tuple[LegalConsentUnit, ...]:
    """게시가 다시 받을 동의 단위. `reconsent_scopes` 가 오면 그것을, 없으면 이전 화면의 `requires_reconsent` 를 그 문서의
    동의 단위 전부로 읽는다. 그 문서에 없는 동의 단위는 422 다 — 재동의 게이트는 문서의 동의 단위만 보므로 그 범위는 아무
    효과가 없는데, 게시 이력·감사 로그에는 재동의를 받은 것으로 남아 운영자를 오도한다(정책 문서에 재동의를 거는 것도
    같다)."""
    allowed = consents.kind_consent_units(kind)
    if body.reconsent_scopes is not None:
        requested = set(body.reconsent_scopes)
        if not requested <= set(allowed):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="이 문서가 받지 않는 동의를 재동의 범위로 고를 수 없습니다.",
            )
        return tuple(unit for unit in allowed if unit in requested)
    if body.requires_reconsent:
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="이 문서는 회원 동의 대상이 아니라 재동의를 요구할 수 없습니다.",
            )
        return allowed
    return ()


async def _get_draft(
    db: AsyncSession, kind: LegalDocumentKind, *, for_update: bool = False
) -> LegalDocument | None:
    query = select(LegalDocument).where(LegalDocument.kind == kind, LegalDocument.status == "draft")
    if for_update:
        query = query.with_for_update()
    document: LegalDocument | None = await db.scalar(query)
    return document


def _published_item(document: LegalDocument | None) -> AdminLegalPublishedItem | None:
    if document is None:
        return None
    assert document.version is not None  # 게시 행은 publish_legal_document가 항상 채운다
    effective_at, published_at = documents.effective_order(document)
    return AdminLegalPublishedItem(
        version=document.version,
        body_markdown=document.body_markdown,
        change_notice_markdown=document.change_notice_markdown,
        published_at=published_at,
        effective_at=effective_at,
        requires_reconsent=document.requires_reconsent,
        reconsent_scopes=consents.reconsent_scopes(document),
    )


async def _build_legal_document_response(
    db: AsyncSession, kind: LegalDocumentKind
) -> AdminLegalDocumentResponse:
    draft = await _get_draft(db, kind)
    now = documents.utcnow()

    draft_item = (
        AdminLegalDraftItem(
            body_markdown=draft.body_markdown,
            change_notice_markdown=draft.change_notice_markdown,
            created_at=draft.created_at,
        )
        if draft is not None
        else None
    )
    return AdminLegalDocumentResponse(
        kind=kind,
        draft=draft_item,
        published=_published_item(await documents.current_legal_document(db, kind, now=now)),
        upcoming=_published_item(await documents.upcoming_legal_document(db, kind, now=now)),
    )


async def _build_versions_response(db: AsyncSession, kind: LegalDocumentKind) -> AdminLegalVersionsResponse:
    """게시본과 철회본을 시행 순서(최신 먼저)로. 상태는 현행 조회 함수가 고른 판과 시행 시각으로 매긴다."""
    now = documents.utcnow()
    current = await documents.current_legal_document(db, kind, now=now)
    rows = (
        await db.scalars(
            select(LegalDocument)
            .where(LegalDocument.kind == kind, LegalDocument.status.in_(("published", "withdrawn")))
            .order_by(LegalDocument.effective_at.desc(), LegalDocument.published_at.desc())
        )
    ).all()

    items = []
    for document in rows:
        assert document.version is not None  # 게시 행은 항상 채워짐
        effective_at, published_at = documents.effective_order(document)
        state: AdminLegalVersionState
        if document.status == "withdrawn":
            state = "withdrawn"
        elif effective_at > now:
            state = "scheduled"
        elif current is not None and document.id == current.id:
            state = "current"
        else:
            state = "past"
        items.append(
            AdminLegalVersionItem(
                version=document.version,
                published_at=published_at,
                effective_at=effective_at,
                requires_reconsent=document.requires_reconsent,
                reconsent_scopes=consents.reconsent_scopes(document),
                change_notice_markdown=document.change_notice_markdown,
                state=state,
            )
        )
    return AdminLegalVersionsResponse(items=items)


@router.get("/admin/legal/{kind}")
async def get_admin_legal_document(
    kind: LegalDocumentKind,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminLegalDocumentResponse:
    return await _build_legal_document_response(db, kind)


@router.put("/admin/legal/{kind}/draft")
async def upsert_legal_draft(
    kind: LegalDocumentKind,
    body: AdminLegalDraftUpsertRequest,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminLegalDocumentResponse:
    """초안 저장은 게시본을 건드리지 않는다 — status='draft'인 행만
    upsert하고, published 행은 이 함수가 아예 조회조차 하지 않는다.

    `_get_draft`가 None을 본 뒤 이 INSERT 사이에 다른 요청이 먼저 초안을 커밋하면
    부분 유니크 인덱스(`ix_legal_documents_kind_draft`)에 걸린다.
    `publish_legal_document`와 같은 이유로 `begin_nested()`(SAVEPOINT)로 감싼다.
    다만 이 엔드포인트는 게시(발행)와 달리 upsert이므로, 경쟁에서 진 요청을 409로
    거부하지 않는다 — "초안이 이 내용이 되게 하라"는 upsert의 의미는 먼저 커밋된 게
    자신인지 남인지와 무관하게 그대로 성립하므로, 방금 다른 요청이 만든 초안을 다시
    읽어 이 요청의 내용으로 덮어쓴다."""
    # 안내 칸을 보내지 않은 요청(안내 칸을 모르는 이전 화면)은 초안의 안내를 건드리지 않는다.
    notice_given = "change_notice_markdown" in body.model_fields_set
    draft = await _get_draft(db, kind)
    if draft is None:
        try:
            async with db.begin_nested():
                db.add(
                    LegalDocument(
                        kind=kind,
                        body_markdown=body.body_markdown,
                        change_notice_markdown=body.change_notice_markdown,
                        status="draft",
                    )
                )
                await db.flush()
        except IntegrityError:
            draft = await _get_draft(db, kind)
            assert draft is not None  # 유니크 위반은 곧 초안이 이제 존재한다는 뜻이다
    if draft is not None:
        draft.body_markdown = body.body_markdown
        if notice_given:
            draft.change_notice_markdown = body.change_notice_markdown

    await db.commit()
    return await _build_legal_document_response(db, kind)


@router.post("/admin/legal/{kind}/publish")
async def publish_legal_document(
    kind: LegalDocumentKind,
    body: AdminLegalPublishRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminLegalDocumentResponse:
    """게시는 현재 초안의 `body_markdown`을 그대로 복제해 새 published 행을 만든다 —
    초안 행 자체를 published로 전환하는 게 아니라 내용을 새 행으로 하나 더 만든다
    (버전마다 별도 행으로 남아야 `GET .../versions` 이력 조회가 가능하기 때문).

    **게시 후에도 초안 행은 지우지 않고 그대로 둔다.** "초안 저장 → 게시 → 다시 초안
    저장"은 지우든 남기든 둘 다 성립한다(부분 유니크 인덱스는 draft 행의 개수만
    제한할 뿐 내용과 무관하다) — 그래도 남기는 쪽을 골랐다. 남기면 게시 직후에도 방금
    편집하던 내용이 초안 조회에 그대로 남아 관리자가 바로 이어서 다듬을 수 있다(예:
    오타 하나만 고쳐 재게시). 지우는 쪽을 골랐다면 매번 원고를 통째로 다시 붙여넣게
    되어 더 불편해질 뿐, 더 안전해지는 지점이 없다.

    **다만 게시가 성공하면 초안의 변경 안내는 비운다.** 안내는 그 판에서 무엇이 바뀌었는지를 적은 것이라 다음 판에 그대로
    쓸 수 없다. 남겨 두면 다음 게시가 이미 나간 안내를 자기 안내로 복제하고, 재동의 게시의 "안내 필수" 검사도 그 낡은
    안내로 통과해 회원이 엉뚱한 안내를 보고 동의하게 된다. 비우면 새 판의 안내는 늘 새로 써야 한다. 직전 안내를 고쳐 쓰고
    싶으면 화면이 게시본의 안내를 불러와 채우면 된다.

    재동의 범위는 그 문서의 동의 단위 안에서만 고른다(`_requested_reconsent_scopes`). 변경 안내도 초안에서 복제하고, 앞뒤
    공백만 있는 안내는 없는 것으로 저장한다. **재동의 범위가 하나라도 걸린 게시는 안내가 없으면 422 다** — 재동의 화면은
    전문보다 안내를 먼저 보여 주므로, 안내 없이 재동의를 걸면 회원이 무엇이 바뀌었는지 모른 채 동의하게 된다.

    **시행 시각**: 비우면 게시 시각으로 즉시 시행한다. 게시 시각보다 이르면 422 — 과거로 소급하면 그 판이 직전 현행판보다
    앞에 놓여 영영 현행이 되지 못하거나, 그 사이에 옛 판에 동의한 회원이 새 판에 동의한 것으로 읽힌다. 미래면 시행 예정
    판이 된다. **예정 판이 있는 동안 같은 kind 의 다른 게시는 즉시든 예약이든 409 다**(먼저 예정 판을 철회한다). 즉시 게시를
    허용하면 예정 판이 시행되는 순간 그 판이 현행이 되어 사이에 게시한 수정이 조용히 사라지고, 초안에 남은 예정 판 본문을
    즉시 게시하면 공지 기간 없이 오늘 시행된다. 급한 수정은 예정 판 철회 → 수정판 게시 → 수정을 반영한 판 재예약 순서로 한다.
    이 검사는 부분 유니크 인덱스로 할 수 없다(인덱스 조건에 현재 시각을 쓸 수 없다). 그래서 kind 의 초안 행을 잠가 같은
    kind 의 게시를 줄 세운 뒤 검사한다 — 게시는 초안이 있어야 하므로 초안 행이 kind 단위의 잠금 대상이 된다.
    """
    reconsent_scopes = _requested_reconsent_scopes(kind, body)
    now = documents.utcnow()
    effective_at = body.effective_at if body.effective_at is not None else now
    if effective_at < now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="시행 시각은 게시 시각보다 이를 수 없습니다.",
        )

    draft = await _get_draft(db, kind, for_update=True)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="발행할 초안이 없습니다.")
    change_notice = (draft.change_notice_markdown or "").strip() or None
    if reconsent_scopes and change_notice is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="재동의를 받는 판은 변경 안내가 있어야 합니다. 초안에 변경 안내를 써 주세요.",
        )
    if await documents.upcoming_legal_document(db, kind, now=now) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="시행 예정인 판이 있어 게시할 수 없습니다. 그 판을 먼저 철회한 뒤 게시해 주세요.",
        )

    # 부분 유니크 인덱스(`kind`, `version`) WHERE status='published'가 중복 버전을
    # 막아준다 — 그 IntegrityError를 500으로 흘리지 않고 409로 정리해 내려준다.
    # `begin_nested()`(SAVEPOINT)로 감싸는 이유: 이 세션이 이미 더 바깥 트랜잭션(예:
    # 이 요청 자체, 혹은 테스트의 롤백 트랜잭션) 안에 있을 수 있는데, 세션 전체를
    # `rollback()`하면 SAVEPOINT 없이는 그 바깥 트랜잭션까지 통째로 되감겨 이전에 이미
    # 커밋된 내용(예: 이 kind의 기존 published 행들)까지 사라진다(실측으로 확인) —
    # 이 INSERT 하나만 되감으려면 명시적 SAVEPOINT가 필요하다.
    try:
        async with db.begin_nested():
            db.add(
                LegalDocument(
                    kind=kind,
                    version=body.version,
                    body_markdown=draft.body_markdown,
                    change_notice_markdown=change_notice,
                    status="published",
                    requires_reconsent=bool(reconsent_scopes),
                    reconsent_scopes=list(reconsent_scopes),
                    published_at=now,
                    effective_at=effective_at,
                )
            )
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 버전입니다. 버전을 수정해 주세요.",
        ) from None
    draft.change_notice_markdown = None

    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="legal-publish",
        reason_text=(
            f"{kind} 문서를 버전 {body.version}으로 게시"
            + (f"(재동의 필요: {', '.join(reconsent_scopes)})" if reconsent_scopes else "")
            + (f", 시행 {effective_at.isoformat()}" if effective_at > now else "")
        ),
    )
    await db.commit()

    return await _build_legal_document_response(db, kind)


@router.get("/admin/legal/{kind}/versions")
async def list_legal_document_versions(
    kind: LegalDocumentKind,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminLegalVersionsResponse:
    return await _build_versions_response(db, kind)


@router.post("/admin/legal/{kind}/versions/{version}/withdraw")
async def withdraw_legal_document(
    kind: LegalDocumentKind,
    version: str,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminLegalVersionsResponse:
    """시행 예정 판을 철회한다. 행은 지우지 않고 `withdrawn` 으로 남기며 그 버전 이름은 다시 쓸 수 없다(이미 공지로
    나갔을 수 있다). 시행 시각이 지난 판은 409 — 시행된 판에는 이미 동의한 회원이 있을 수 있어 거둘 수 없고, 고치려면 새
    판을 게시한다. 행을 잠그고 시각을 본다(같은 판을 두 번 철회하는 요청이 둘 다 감사 로그를 남기지 않게)."""
    now = documents.utcnow()
    document: LegalDocument | None = await db.scalar(
        select(LegalDocument)
        .where(LegalDocument.kind == kind, LegalDocument.version == version, LegalDocument.status == "published")
        .with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="철회할 게시본이 없습니다.")
    if documents.effective_order(document)[0] <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 시행된 판은 철회할 수 없습니다. 고치려면 새 판을 게시해 주세요.",
        )

    document.status = "withdrawn"
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="legal-withdraw",
        reason_text=f"{kind} 문서의 시행 예정 판 {version}을 철회",
    )
    await db.commit()
    return await _build_versions_response(db, kind)
