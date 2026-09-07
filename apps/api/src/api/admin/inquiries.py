import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.core.s3 import generate_presigned_get_url
from api.db.models.auth import User
from api.db.models.inquiry import Inquiry, InquiryCategory, InquiryStatus
from api.db.models.media import Asset
from api.db.models.moderation import Notification
from api.db.session import get_db_session
from api.inquiry.schemas import (
    AdminInquiryDetailResponse,
    AdminInquiryListItem,
    AdminInquiryListResponse,
    AdminInquiryReplyRequest,
)

router = APIRouter(prefix="/admin/inquiries", tags=["admin"])

ADMIN_INQUIRY_PAGE_SIZE = 20


async def _resolve_asset_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """`moderation/router.py`의 같은 이름 헬퍼(:121)와 같은 모양 — 파일 간 헬퍼를
    공유하지 않는 이 저장소 관례(`apps/api/CLAUDE.md`)에 따라 이 파일에도 복제한다."""
    if asset_id is None:
        return None
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return None
    return await run_in_threadpool(generate_presigned_get_url, asset.storage_key)


async def _get_or_404(db: AsyncSession, id: uuid.UUID) -> Inquiry:
    inquiry = await db.get(Inquiry, id)
    if inquiry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inquiry not found")
    return inquiry


async def _to_detail(db: AsyncSession, inquiry: Inquiry) -> AdminInquiryDetailResponse:
    author = await db.get(User, inquiry.user_id)
    assert author is not None  # inquiries.user_id -> users.id FK가 보장한다

    return AdminInquiryDetailResponse(
        id=inquiry.id,
        category=inquiry.category,
        title=inquiry.title,
        body=inquiry.body,
        attachment_url=await _resolve_asset_url(db, inquiry.attachment_asset_id),
        status=inquiry.status,
        author_nickname=author.nickname,
        author_email=author.email,
        reply_body=inquiry.reply_body,
        answered_at=inquiry.answered_at,
        created_at=inquiry.created_at,
    )


@router.get("")
async def list_admin_inquiries(
    page: int = Query(1, ge=1),
    status_filter: InquiryStatus | None = Query(None, alias="status"),
    category_filter: InquiryCategory | None = Query(None, alias="category"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminInquiryListResponse:
    """offset 페이징 — `list_admin_reports`(`moderation/router.py:216`)와 같은 모양."""
    filters = []
    if status_filter is not None:
        filters.append(Inquiry.status == status_filter)
    if category_filter is not None:
        filters.append(Inquiry.category == category_filter)

    total_count = await db.scalar(select(func.count()).select_from(Inquiry).where(*filters))
    total_count = total_count or 0
    total_pages = -(-total_count // ADMIN_INQUIRY_PAGE_SIZE) if total_count else 0

    inquiries = (
        await db.scalars(
            select(Inquiry)
            .where(*filters)
            .order_by(Inquiry.created_at.desc())
            .offset((page - 1) * ADMIN_INQUIRY_PAGE_SIZE)
            .limit(ADMIN_INQUIRY_PAGE_SIZE)
        )
    ).all()

    return AdminInquiryListResponse(
        items=[
            AdminInquiryListItem(
                id=inquiry.id,
                category=inquiry.category,
                title=inquiry.title,
                status=inquiry.status,
                created_at=inquiry.created_at,
            )
            for inquiry in inquiries
        ],
        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )


@router.get("/{id}")
async def get_admin_inquiry(
    id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminInquiryDetailResponse:
    inquiry = await _get_or_404(db, id)
    return await _to_detail(db, inquiry)


@router.post("/{id}/reply")
async def reply_to_inquiry(
    id: uuid.UUID,
    body: AdminInquiryReplyRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminInquiryDetailResponse:
    """한 트랜잭션: 답변 기록 → 알림 1건(대상 1명이라 fan-out이 아니다) → 감사 로그 →
    commit.

    이미 `ANSWERED`인 문의에 다시 답변하면 본문은 덮어쓰되 알림은 추가로 만들지
    않는다(오타 수정 경로) — 매 재답변마다 알림이 쌓이면 유저가 같은 건으로 여러 번
    울리는 알림을 받게 된다.
    """
    inquiry = await _get_or_404(db, id)
    is_first_reply = inquiry.status != InquiryStatus.ANSWERED

    inquiry.reply_body = body.reply_body
    inquiry.replied_by_admin_id = admin_id
    inquiry.answered_at = datetime.now(UTC)
    inquiry.status = InquiryStatus.ANSWERED

    if is_first_reply:
        db.add(
            Notification(
                user_id=inquiry.user_id,
                type="inquiry-reply",
                inquiry_id=inquiry.id,
                reason_category=None,
                admin_comment=None,
            )
        )

    await record_admin_action(db, admin_id=admin_id, action_type="inquiry-reply")
    await db.commit()

    return await _to_detail(db, inquiry)
