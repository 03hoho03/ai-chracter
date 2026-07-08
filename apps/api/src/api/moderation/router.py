import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.moderation import Appeal, AppealStatus, Notification
from api.db.session import get_db_session
from api.moderation.schemas import AppealCreateRequest, AppealResponse, NotificationResponse
from api.session.dependencies import get_current_user_id

router = APIRouter(tags=["moderation"])


def _to_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        type=notification.type,
        content_id=notification.content_id,
        action_id=notification.action_id,
        reason_category=notification.reason_category,
        admin_comment=notification.admin_comment,
        created_at=notification.created_at,
        read=notification.read,
    )


@router.get("/notifications")
async def list_my_notifications(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[NotificationResponse]:
    notifications = (
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
        )
    ).all()
    return [_to_response(notification) for notification in notifications]


@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationResponse:
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not the notification owner"
        )

    notification.read = True
    await db.commit()

    return _to_response(notification)


@router.post("/appeals", status_code=status.HTTP_201_CREATED)
async def create_appeal(
    body: AppealCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> AppealResponse:
    """techspec-backend-admin-moderation.md §1/§3. `target_kind='publish-rejection'`일 때
    `target_id`는 별도 발행거부 이력 엔티티 없이 대상 contentId 그대로다."""
    appeal = Appeal(
        user_id=user_id,
        target_kind=body.target_kind,
        target_id=body.target_id,
        reason_text=body.reason_text,
        status=AppealStatus.PENDING,
    )
    db.add(appeal)
    await db.commit()

    return AppealResponse(appeal_id=appeal.id, status=appeal.status)
