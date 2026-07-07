from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from api.session.cookies import clear_session_cookie, get_session_id_from_request, set_session_cookie
from api.session.store import create_session, delete_session, get_session

router = APIRouter(prefix="/dev/session-echo", tags=["session (dev skeleton)"])


class SessionEchoPayload(BaseModel):
    data: dict[str, Any] = {}


def _require_session_id(request: Request) -> str:
    session_id = get_session_id_from_request(request)
    if session_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session cookie")
    return session_id


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session_echo(payload: SessionEchoPayload, response: Response) -> dict[str, str]:
    session_id = await create_session(payload.data)
    set_session_cookie(response, session_id)
    return {"session_id": session_id}


@router.get("")
async def read_session_echo(request: Request) -> dict[str, Any]:
    session_id = _require_session_id(request)
    data = await get_session(session_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or expired")
    return data


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session_echo(request: Request, response: Response) -> None:
    session_id = _require_session_id(request)
    await delete_session(session_id)
    clear_session_cookie(response)
