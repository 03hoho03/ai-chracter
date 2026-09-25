import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.session import get_db_session
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


async def _is_active_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """세션이 살아 있어도 `users` 행이 없거나(dev 재시딩) 탈퇴했으면 로그인으로 치지 않는다.
    재동의 버전은 보지 않는다 — 그건 `require_legal_consent`의
    몫이다. 정지도 DB 컬럼이 아니라 아래 Redis 마커가 본다.

    `db`는 요청 스코프 의존성 캐시라 라우트 본문·다른 게이트와 같은 세션이지만, 뒤에서 같은
    행을 다시 `db.get`해도 SELECT가 또 나간다 — identity map은 약참조라 여기서 읽은 `User`는
    반환과 함께 수거된다. 그래서 이 조회는 인증된 요청마다 PK SELECT 1회를 더한다."""
    user = await db.get(User, user_id)
    return user is not None and user.deleted_at is None


async def get_current_user_id(request: Request, db: AsyncSession = Depends(get_db_session)) -> uuid.UUID:
    """세션 → `users` 행 확인(401) → 정지 마커(403) 순서다. 탈퇴 계정은 정지 여부와 상관없이
    401이다. 세션 쿠키가 없거나 Redis에 없는 요청은 `db`를 쓰지 않는다(SQL 0)."""
    user_id = await _session_user_id(request)
    if user_id is None or not await _is_active_user(db, user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # 정지 차단. 역인덱스로 세션을 전부 지울 수 있게 됐지만 정지는 일부러
    # 지우지 않는다 — 세션이 살아 있어야 다음 요청이 401이
    # 아니라 이 403이 되고, 403이어야 FE가 정지 안내를 띄운다. 새 로그인은 마커가 아니라 DB의
    # `suspended_at`이 막는다. 그래서 세션은 그대로 유효한 채 매 요청마다 이 마커로 통과만
    # 막는 "요청 차단" 방식이다. user_id를 먼저 알아야
    # 마커 키(suspended_user:{user_id})를 만들 수 있어 위 세션 조회와 파이프라인으로
    # 묶을 수 없다 — Redis 왕복이 요청당 1회 늘어난다.
    if await is_user_suspended(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    return user_id


async def get_current_user_id_optional(
    request: Request, db: AsyncSession = Depends(get_db_session)
) -> uuid.UUID | None:
    """For endpoints that work both logged-out and logged-in but change behavior for the
    latter (e.g. GET /users/{id}/contents exposing extra filters to the profile owner).

    정지된 유저는 403이 아니라 `None`을 돌려준다(비로그인과 동일 취급) — 이 의존성을
    쓰는 엔드포인트는 "로그인 시 추가 정보"를 주는 공개 조회라, 403을 던지면 공개 조회
    자체가 깨진다. `users` 행이 없거나 탈퇴한 세션도 같은 이유로 401이 아니라 `None`이다.
    """
    user_id = await _session_user_id(request)
    if user_id is None or not await _is_active_user(db, user_id):
        return None
    if await is_user_suspended(user_id):
        return None
    return user_id
