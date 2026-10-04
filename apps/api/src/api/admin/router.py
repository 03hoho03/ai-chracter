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
from api.auth.router import _auth_too_many_requests
from api.core import rate_limit
from api.core.security import verify_password
from api.db.models.auth import AdminUser
from api.db.session import get_db_session

router = APIRouter(prefix="/admin/auth", tags=["admin"])
me_router = APIRouter(tags=["admin"])


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    # 사용자 로그인과 같은 규칙이다 — DB 조회보다 먼저, 결과와 무관하게 세어 없는 이메일도 같은
    # 횟수에서 429 가 나게 한다. 응답 모양도 사용자 auth 429 와 같게 둔다.
    client_ip = request.client.host if request.client else "unknown"
    ip_retry_after = await rate_limit.check_rate_limit(
        "admin_login_ip",
        client_ip,
        rate_limit.ADMIN_LOGIN_IP_LIMIT,
        window_seconds=rate_limit.ADMIN_LOGIN_IP_WINDOW_SECONDS,
    )
    email_retry_after = await rate_limit.check_rate_limit(
        "admin_login_email",
        payload.email,
        rate_limit.ADMIN_LOGIN_EMAIL_LIMIT,
        window_seconds=rate_limit.ADMIN_LOGIN_EMAIL_WINDOW_SECONDS,
    )
    retry_after = ip_retry_after or email_retry_after
    if retry_after > 0:
        raise _auth_too_many_requests(retry_after, code="AUTH_LIMIT")

    admin = await db.scalar(select(AdminUser).where(AdminUser.email == payload.email))
    if admin is None or not await verify_password(payload.password, admin.password_hash):
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
