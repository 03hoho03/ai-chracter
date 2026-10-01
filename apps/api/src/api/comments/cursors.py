import base64
import binascii
import uuid
from datetime import datetime

from pydantic import BaseModel, ValidationError

from api.comments.access import comment_error


class CommentCursor(BaseModel):
    scope: str
    sort: str = "latest"
    direction: str = "after"
    id: uuid.UUID
    created_at: datetime | None = None
    likes: int = 0


def encode_cursor(cursor: CommentCursor) -> str:
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode()


def decode_cursor(
    raw: str, scope: str, *, sort: str = "latest", direction: str = "after", has_time: bool = True
) -> CommentCursor:
    try:
        cursor = CommentCursor.model_validate_json(base64.b64decode(raw, altchars=b"-_", validate=True))
        if cursor.scope != scope or cursor.sort != sort or cursor.direction != direction:
            raise ValueError
        if has_time and (cursor.created_at is None or cursor.created_at.tzinfo is None):
            raise ValueError
    except (ValueError, ValidationError, binascii.Error):
        raise comment_error(422, "COMMENT_CURSOR_INVALID", "댓글 페이지 정보가 올바르지 않습니다.") from None
    return cursor
