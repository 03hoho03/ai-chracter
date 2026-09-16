import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.core.constants import WITHDRAWN_USER_NICKNAME
from api.core.s3 import generate_presigned_get_url
from api.db.models.auth import User
from api.db.models.media import Asset, ImageGenerationRequest
from api.db.session import get_db_session
from api.images.models import ImageStylePreset
from api.images.schemas import (
    AdminImageGenerationDetailItem,
    AdminImageGenerationDetailListResponse,
    AdminImageGenerationImageItem,
    AdminImageGenerationListItem,
    AdminImageGenerationListResponse,
    AdminImageGenerationViewRequest,
    ImageGenerationRequestStatus,
)

router = APIRouter(tags=["admin"])

# image-monitoring-goal-prompt.md IM-12: limit을 클라이언트에 노출하지 않는다.
ADMIN_IMAGE_GENERATION_PAGE_SIZE = 20


async def _list_owner_requests_page(
    db: AsyncSession, owner_user_id: uuid.UUID, page: int
) -> AdminImageGenerationDetailListResponse:
    """유저 단위 열람(view)과 더보기(list)의 공용 페이지 조립 — `admin/chat_view.py`의
    `_list_messages_page`와 같은 이유로 한 파일 안에서 공유한다. 사유 게이트를 통과한
    뒤에만 불리므로 프롬프트·이미지 URL을 그대로 채운다(IM-2)."""
    filters: list[ColumnElement[bool]] = [ImageGenerationRequest.owner_user_id == owner_user_id]

    total_count = (
        await db.scalar(select(func.count()).select_from(ImageGenerationRequest).where(*filters))
    ) or 0
    total_pages = -(-total_count // ADMIN_IMAGE_GENERATION_PAGE_SIZE) if total_count else 0

    requests = (
        await db.scalars(
            select(ImageGenerationRequest)
            .where(*filters)
            .order_by(ImageGenerationRequest.created_at.desc(), ImageGenerationRequest.id)
            .offset((page - 1) * ADMIN_IMAGE_GENERATION_PAGE_SIZE)
            .limit(ADMIN_IMAGE_GENERATION_PAGE_SIZE)
        )
    ).all()

    # N+1 회피 벌크 조회 — 이 페이지의 요청 전부에 딸린 asset을 한 번에 가져와
    # request_id로 묶는다(`admin/users.py`의 room_stats_by_room_id와 같은 패턴).
    assets_by_request_id: dict[uuid.UUID, list[Asset]] = defaultdict(list)
    request_ids = [request_row.id for request_row in requests]
    if request_ids:
        for asset in (
            await db.scalars(select(Asset).where(Asset.request_id.in_(request_ids)))
        ).all():
            assert asset.request_id is not None
            assets_by_request_id[asset.request_id].append(asset)

    items: list[AdminImageGenerationDetailItem] = []
    for request_row in requests:
        images = [
            AdminImageGenerationImageItem(
                asset_id=asset.id,
                image_url=await run_in_threadpool(generate_presigned_get_url, asset.storage_key),
            )
            for asset in assets_by_request_id.get(request_row.id, [])
        ]
        items.append(
            AdminImageGenerationDetailItem(
                id=request_row.id,
                prompt=request_row.prompt,
                style=request_row.style,
                aspect_ratio=request_row.aspect_ratio,
                model=request_row.model,
                status=request_row.status,
                requested_count=request_row.requested_count,
                completed_count=request_row.completed_count,
                blocked_count=request_row.blocked_count,
                blocked_reason=request_row.blocked_reason,
                input_error_count=request_row.input_error_count,
                input_error=request_row.input_error,
                error=request_row.error,
                created_at=request_row.created_at,
                images=images,
            )
        )

    return AdminImageGenerationDetailListResponse(
        items=items, page=page, total_pages=total_pages, total_count=total_count
    )


@router.get("/admin/image-generations")
async def list_admin_image_generations(
    page: int = Query(1, ge=1),
    q: str | None = Query(None),
    status_filter: ImageGenerationRequestStatus | None = Query(None, alias="status"),
    style: ImageStylePreset | None = Query(None),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminImageGenerationListResponse:
    """image-monitoring-goal-prompt.md IM-11: 유저 식별(닉네임·이메일)·상태·스타일·요청/완료
    이미지 수·생성 시각까지만 싣는다 — 프롬프트와 이미지 URL은 사유 게이트(IM-2) 뒤에서만
    노출한다."""
    if from_date is not None and to_date is not None and to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="to must not be before from"
        )

    filters: list[ColumnElement[bool]] = []
    if q:
        filters.append(or_(User.email.ilike(f"%{q}%"), User.nickname.ilike(f"%{q}%")))
    if status_filter is not None:
        filters.append(ImageGenerationRequest.status == status_filter)
    if style is not None:
        filters.append(ImageGenerationRequest.style == style.value)
    if from_date is not None:
        filters.append(
            ImageGenerationRequest.created_at >= datetime.combine(from_date, time.min, tzinfo=UTC)
        )
    if to_date is not None:
        filters.append(
            ImageGenerationRequest.created_at
            < datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
        )

    total_count = (
        await db.scalar(
            select(func.count())
            .select_from(ImageGenerationRequest)
            .join(User, User.id == ImageGenerationRequest.owner_user_id)
            .where(*filters)
        )
    ) or 0
    total_pages = -(-total_count // ADMIN_IMAGE_GENERATION_PAGE_SIZE) if total_count else 0

    # 동점(같은 created_at) 시 순서가 흔들리면 offset 페이지네이션에서 행이 중복되거나
    # 누락된다(`admin/users.py`와 같은 이유) — `id`까지 더해 결정적으로 만든다.
    rows = (
        await db.execute(
            select(ImageGenerationRequest, User)
            .join(User, User.id == ImageGenerationRequest.owner_user_id)
            .where(*filters)
            .order_by(ImageGenerationRequest.created_at.desc(), ImageGenerationRequest.id)
            .offset((page - 1) * ADMIN_IMAGE_GENERATION_PAGE_SIZE)
            .limit(ADMIN_IMAGE_GENERATION_PAGE_SIZE)
        )
    ).all()

    items = [
        AdminImageGenerationListItem(
            id=request_row.id,
            user_id=request_row.owner_user_id,
            nickname=user.nickname if user.nickname is not None else WITHDRAWN_USER_NICKNAME,
            email=user.email,
            status=request_row.status,
            style=request_row.style,
            requested_count=request_row.requested_count,
            completed_count=request_row.completed_count,
            created_at=request_row.created_at,
        )
        for request_row, user in rows
    ]

    return AdminImageGenerationListResponse(
        items=items, page=page, total_pages=total_pages, total_count=total_count
    )


@router.post("/admin/users/{user_id}/image-generations/view")
async def view_user_image_generations(
    user_id: uuid.UUID,
    body: AdminImageGenerationViewRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminImageGenerationDetailListResponse:
    """image-monitoring-goal-prompt.md IM-2. **열람 1회 = 로그 1행**(`chat_view.py`와 같은
    규약) — 로그는 이 엔드포인트에서만 쌓는다. 더보기는 아래 GET이 맡고 그쪽은 절대 로그를
    쌓지 않는다."""
    if not body.reason_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="reason_text is required"
        )

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    response = await _list_owner_requests_page(db, user_id, page=1)

    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="image-view",
        target_user_id=user_id,
        reason_category=body.reason_category.value,
        reason_text=body.reason_text,
    )
    await db.commit()

    return response


@router.get("/admin/users/{user_id}/image-generations")
async def list_user_image_generations(
    user_id: uuid.UUID,
    page: int = Query(1, ge=1),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminImageGenerationDetailListResponse:
    """더보기 — **로그를 절대 쌓지 않는다**(IM-2): "열람 1회 = 로그 1행"을 여기서
    깨면 더보기 3번에 3행이 쌓인다."""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await _list_owner_requests_page(db, user_id, page)
