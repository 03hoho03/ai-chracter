import uuid
from datetime import datetime

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.moderation import AppealStatus, AppealTargetKind


class NotificationResponse(CamelModel):
    id: uuid.UUID
    type: str
    content_id: uuid.UUID
    action_id: uuid.UUID
    reason_category: str
    admin_comment: str
    created_at: datetime
    read: bool


class AppealCreateRequest(CamelModel):
    target_kind: AppealTargetKind
    target_id: uuid.UUID
    reason_text: str = Field(min_length=1)


class AppealResponse(CamelModel):
    appeal_id: uuid.UUID
    status: AppealStatus
