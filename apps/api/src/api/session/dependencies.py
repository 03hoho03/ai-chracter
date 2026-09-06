import uuid

from fastapi import HTTPException, Request, status

from api.session.cookies import get_session_id_from_request
from api.session.store import get_session
from api.session.suspension import is_user_suspended


async def _session_user_id(request: Request) -> uuid.UUID | None:
    session_id = get_session_id_from_request(request)
    if session_id is not None:
        data = await get_session(session_id)
        raw_user_id = data.get("user_id") if data else None
        if raw_user_id is not None:
            return uuid.UUID(str(raw_user_id))
    return None


async def get_current_user_id(request: Request) -> uuid.UUID:
    """Real login (US-021) stores `user_id` in the session on success; until then,
    any endpoint that needs an authenticated user relies on that same convention."""
    user_id = await _session_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # 정지 차단(techspec §2-1). Redis에 user_id 역인덱스가 없어(goal-prompt §3-3) 정지된
    # 유저의 세션을 전부 지울 수 없다 — 그래서 세션은 "만료"되지 않고 그대로 유효한 채,
    # 매 요청마다 이 마커로 통과만 막는 "요청 차단" 방식이다. user_id를 먼저 알아야
    # 마커 키(suspended_user:{user_id})를 만들 수 있어 위 세션 조회와 파이프라인으로
    # 묶을 수 없다 — Redis 왕복이 요청당 1회 늘어난다.
    if await is_user_suspended(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    return user_id


async def get_current_user_id_optional(request: Request) -> uuid.UUID | None:
    """For endpoints that work both logged-out and logged-in but change behavior for the
    latter (e.g. GET /users/{id}/contents exposing extra filters to the profile owner).

    정지된 유저는 403이 아니라 `None`을 돌려준다(비로그인과 동일 취급) — 이 의존성을
    쓰는 엔드포인트는 "로그인 시 추가 정보"를 주는 공개 조회라, 403을 던지면 공개 조회
    자체가 깨진다.
    """
    user_id = await _session_user_id(request)
    if user_id is None:
        return None
    if await is_user_suspended(user_id):
        return None
    return user_id
