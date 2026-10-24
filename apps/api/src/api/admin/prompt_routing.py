"""어드민 모델 배정 표 API — 실효 표 조회, 표 전체 저장, 이력 목록·상세, 이력으로 되돌리기."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminPromptRouteRevisionDetailResponse,
    AdminPromptRouteRevisionListResponse,
    AdminPromptRoutingResponse,
    AdminPromptRoutingRestoreRequest,
    AdminPromptRoutingSaveRequest,
)
from api.db.session import get_db_session

router = APIRouter(tags=["admin"])


def _not_implemented() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/admin/prompt-routing")
async def get_prompt_routing(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRoutingResponse:
    raise _not_implemented()


@router.put("/admin/prompt-routing")
async def save_prompt_routing(
    body: AdminPromptRoutingSaveRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRoutingResponse:
    raise _not_implemented()


@router.get("/admin/prompt-routing/revisions")
async def list_prompt_route_revisions(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRouteRevisionListResponse:
    raise _not_implemented()


@router.get("/admin/prompt-routing/revisions/{id}")
async def get_prompt_route_revision(
    id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRouteRevisionDetailResponse:
    raise _not_implemented()


@router.post("/admin/prompt-routing/revisions/{id}/restore")
async def restore_prompt_route_revision(
    id: uuid.UUID,
    body: AdminPromptRoutingRestoreRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRoutingResponse:
    raise _not_implemented()
