from fastapi import Request, Response

from api.core.config import settings


def set_admin_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=settings.admin_session_cookie_name,
        value=session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
    )


def clear_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.admin_session_cookie_name)


def get_admin_session_id_from_request(request: Request) -> str | None:
    return request.cookies.get(settings.admin_session_cookie_name)
