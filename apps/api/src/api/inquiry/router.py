import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.core.s3 import generate_presigned_get_url
from api.db.models.inquiry import Inquiry, InquiryStatus
from api.db.models.media import Asset
from api.db.session import get_db_session
from api.inquiry.schemas import (
    InquiryCreateRequest,
    InquiryCreateResponse,
    MyInquiryDetailResponse,
    MyInquiryListItem,
    MyInquiryListResponse,
)
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/inquiries", tags=["inquiry"])
me_router = APIRouter(prefix="/me", tags=["inquiry"])


async def _resolve_asset_url(db: AsyncSession, asset_id: uuid.UUID | None) -> str | None:
    """`moderation/router.py`의 같은 이름 헬퍼(:164)와 같은 모양 — 파일 간 헬퍼를
    공유하지 않는 이 저장소 관례(`apps/api/CLAUDE.md`)에 따라 이 파일에도 복제한다."""
    if asset_id is None:
        return None
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return None
    return await run_in_threadpool(generate_presigned_get_url, asset.storage_key)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_inquiry(
    body: InquiryCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> InquiryCreateResponse:
    if body.attachment_asset_id is not None:
        asset = await db.get(Asset, body.attachment_asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        if asset.owner_user_id != user_id:
            # 남의 asset id를 붙여 접수하는 경로를 막는다 — `complete_asset_upload`
            # (assets/router.py)가 업로드 완료 시점에 같은 검사를 이미 하지만, 그건
            # 다른 시점이라 여기서 다시 본다.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the asset owner")

    inquiry = Inquiry(
        user_id=user_id,
        category=body.category,
        title=body.title,
        body=body.body,
        attachment_asset_id=body.attachment_asset_id,
        status=InquiryStatus.PENDING,
    )
    db.add(inquiry)
    await db.commit()

    return InquiryCreateResponse(id=inquiry.id)


@me_router.get("/inquiries")
async def list_my_inquiries(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> MyInquiryListResponse:
    """페이징하지 않는다(D-13과 같은 이유) — 내 문의는 공지보다도 적다."""
    inquiries = (
        await db.scalars(
            select(Inquiry).where(Inquiry.user_id == user_id).order_by(Inquiry.created_at.desc())
        )
    ).all()

    return MyInquiryListResponse(
        items=[
            MyInquiryListItem(
                id=inquiry.id,
                category=inquiry.category,
                title=inquiry.title,
                status=inquiry.status,
                created_at=inquiry.created_at,
            )
            for inquiry in inquiries
        ]
    )


@me_router.get("/inquiries/{id}")
async def get_my_inquiry(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> MyInquiryDetailResponse:
    """남의 문의 상세는 404 — 403이 아니다. `notice/router.py`의 `get_notice`와 같은
    이유로, URL 추측으로 존재 자체가 새면 안 된다."""
    inquiry = await db.get(Inquiry, id)
    if inquiry is None or inquiry.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inquiry not found")

    return MyInquiryDetailResponse(
        id=inquiry.id,
        category=inquiry.category,
        title=inquiry.title,
        body=inquiry.body,
        attachment_url=await _resolve_asset_url(db, inquiry.attachment_asset_id),
        status=inquiry.status,
        reply_body=inquiry.reply_body,
        answered_at=inquiry.answered_at,
        created_at=inquiry.created_at,
    )
