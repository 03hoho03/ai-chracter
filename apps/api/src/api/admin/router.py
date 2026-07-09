import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.cookies import (
    clear_admin_session_cookie,
    get_admin_session_id_from_request,
    set_admin_session_cookie,
)
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import AdminLoginRequest, AdminMeResponse
from api.admin.session import create_admin_session, delete_admin_session
from api.core.security import verify_password
from api.db.models.auth import AdminUser
from api.db.session import get_db_session

router = APIRouter(prefix="/admin/auth", tags=["admin"])
me_router = APIRouter(tags=["admin"])


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def admin_login(
    payload: AdminLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    admin = await db.scalar(select(AdminUser).where(AdminUser.email == payload.email))
    if admin is None or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    session_id = await create_admin_session({"admin_id": str(admin.id)})
    set_admin_session_cookie(response, session_id)
    return None


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(request: Request, response: Response) -> None:
    session_id = get_admin_session_id_from_request(request)
    if session_id is not None:
        await delete_admin_session(session_id)
    clear_admin_session_cookie(response)
    return None


@me_router.get("/admin/me")
async def get_admin_me(
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminMeResponse:
    admin = await db.get(AdminUser, admin_id)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    return AdminMeResponse(id=admin.id, email=admin.email)
