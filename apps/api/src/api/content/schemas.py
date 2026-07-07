import uuid
from datetime import datetime

from api.core.schema import CamelModel
from api.db.models.content import ContentType


class DraftSummary(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_asset_id: uuid.UUID
    updated_at: datetime
