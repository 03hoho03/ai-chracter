import uuid
from datetime import datetime

from api.core.schema import CamelModel


class NotificationResponse(CamelModel):
    id: uuid.UUID
    type: str
    content_id: uuid.UUID
    action_id: uuid.UUID
    reason_category: str
    admin_comment: str
    created_at: datetime
    read: bool
