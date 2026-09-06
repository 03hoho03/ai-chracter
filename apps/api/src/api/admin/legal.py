import uuid
from datetime import UTC, datetime

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
)
from api.db.models.legal import LegalDocument
from api.db.session import get_db_session
from api.legal.schemas import LegalDocumentKind

router = APIRouter(tags=["admin"])


async def _get_draft(db: AsyncSession, kind: LegalDocumentKind) -> LegalDocument | None:
    document: LegalDocument | None = await db.scalar(
        select(LegalDocument).where(LegalDocument.kind == kind, LegalDocument.status == "draft")
    )
    return document


async def _get_latest_published(db: AsyncSession, kind: LegalDocumentKind) -> LegalDocument | None:
    """`api/legal/router.py`의 동명 헬퍼와 조회 내용이 같지만 파일 간 헬퍼 비공유
    관례(apps/api/CLAUDE.md)에 따라 이 파일에도 복제한다."""
    document: LegalDocument | None = await db.scalar(
        select(LegalDocument)
        .where(LegalDocument.kind == kind, LegalDocument.status == "published")
        .order_by(LegalDocument.published_at.desc())
        .limit(1)
    )
    return document


async def _build_legal_document_response(
    db: AsyncSession, kind: LegalDocumentKind
) -> AdminLegalDocumentResponse:
    draft = await _get_draft(db, kind)
    published = await _get_latest_published(db, kind)

    draft_item = (
        AdminLegalDraftItem(body_markdown=draft.body_markdown, created_at=draft.created_at)
        if draft is not None
        else None
    )

    published_item = None
    if published is not None:
        assert published.version is not None  # 게시 행은 publish_legal_document가 항상 채운다
        assert published.published_at is not None  # 위와 동일
        published_item = AdminLegalPublishedItem(
            version=published.version,
            body_markdown=published.body_markdown,
            published_at=published.published_at,
            requires_reconsent=published.requires_reconsent,
        )

    return AdminLegalDocumentResponse(kind=kind, draft=draft_item, published=published_item)


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
    """초안 저장은 게시본을 건드리지 않는다(T-12의 핵심) — status='draft'인 행만
    upsert하고, published 행은 이 함수가 아예 조회조차 하지 않는다.

    `_get_draft`가 None을 본 뒤 이 INSERT 사이에 다른 요청이 먼저 초안을 커밋하면
    부분 유니크 인덱스(`ix_legal_documents_kind_draft`)에 걸린다.
    `publish_legal_document`와 같은 이유로 `begin_nested()`(SAVEPOINT)로 감싼다.
    다만 이 엔드포인트는 게시(발행)와 달리 upsert이므로, 경쟁에서 진 요청을 409로
    거부하지 않는다 — "초안이 이 내용이 되게 하라"는 upsert의 의미는 먼저 커밋된 게
    자신인지 남인지와 무관하게 그대로 성립하므로, 방금 다른 요청이 만든 초안을 다시
    읽어 이 요청의 내용으로 덮어쓴다."""
    draft = await _get_draft(db, kind)
    if draft is None:
        try:
            async with db.begin_nested():
                db.add(LegalDocument(kind=kind, body_markdown=body.body_markdown, status="draft"))
                await db.flush()
        except IntegrityError:
            draft = await _get_draft(db, kind)
            assert draft is not None  # 유니크 위반은 곧 초안이 이제 존재한다는 뜻이다
            draft.body_markdown = body.body_markdown
    else:
        draft.body_markdown = body.body_markdown

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
    """
    draft = await _get_draft(db, kind)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="발행할 초안이 없습니다.")

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
                    status="published",
                    requires_reconsent=body.requires_reconsent,
                    published_at=datetime.now(UTC),
                )
            )
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 버전입니다. 버전을 수정해 주세요.",
        ) from None

    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="legal-publish",
        reason_text=(
            f"{kind} 문서를 버전 {body.version}으로 게시"
            + ("(재동의 필요)" if body.requires_reconsent else "")
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
    documents = (
        await db.scalars(
            select(LegalDocument)
            .where(LegalDocument.kind == kind, LegalDocument.status == "published")
            .order_by(LegalDocument.published_at.desc())
        )
    ).all()

    items = []
    for document in documents:
        assert document.version is not None  # 게시 행은 항상 채워짐
        assert document.published_at is not None  # 게시 행은 항상 채워짐
        items.append(
            AdminLegalVersionItem(
                version=document.version,
                published_at=document.published_at,
                requires_reconsent=document.requires_reconsent,
            )
        )
    return AdminLegalVersionsResponse(items=items)
