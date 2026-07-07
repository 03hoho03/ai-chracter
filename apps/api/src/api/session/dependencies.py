import uuid

from fastapi import HTTPException, Request, status

from api.session.cookies import get_session_id_from_request
from api.session.store import get_session


async def get_current_user_id(request: Request) -> uuid.UUID:
    """Real login (US-021) stores `user_id` in the session on success; until then,
    any endpoint that needs an authenticated user relies on that same convention."""
    session_id = get_session_id_from_request(request)
    if session_id is not None:
        data = await get_session(session_id)
        raw_user_id = data.get("user_id") if data else None
        if raw_user_id is not None:
            return uuid.UUID(str(raw_user_id))

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
