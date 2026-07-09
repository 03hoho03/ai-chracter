import uuid

from fastapi import HTTPException, Request, status

from api.admin.cookies import get_admin_session_id_from_request
from api.admin.session import get_admin_session


async def get_current_admin_id(request: Request) -> uuid.UUID:
    """A regular user's session cookie (different name, different Redis prefix)
    never satisfies this — cross-authentication between the two session scopes
    is impossible by construction, not by an extra check here."""
    session_id = get_admin_session_id_from_request(request)
    if session_id is not None:
        data = await get_admin_session(session_id)
        raw_admin_id = data.get("admin_id") if data else None
        if raw_admin_id is not None:
            return uuid.UUID(str(raw_admin_id))

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
