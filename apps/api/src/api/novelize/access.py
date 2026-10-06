"""소설화 접근 판정. 세 조건이 모두 참이어야 쓸 수 있다 — 전역 스위치(`novelize_enabled`)가 켜져 있고, 계정이
env 허용 명단(`novelize_grant_allowlist`)에 있고, 어드민이 준 허용 행(`user_feature_grants`)이 있다.

명단을 허용을 줄 때만이 아니라 접근할 때도 보는 이유는 회수 경로를 하나 더 두기 위해서다. 명단은 처리방침 개정 전
운영 시험 계정만 담는데, env 에서 지우고 재기동하면 허용 행을 지우지 않아도 그 계정이 곧바로 막힌다.

라우트 게이트(`require_novelize_access`)와 `GET /me` 의 허용 기능 목록이 같은 함수(`has_novelize_access`)를 쓴다.
둘이 따로 판정하면 FE 가 진입점을 보여 주는데 라우트는 막는 어긋남이 생긴다."""

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.feature_grant import UserFeatureGrant
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id


async def has_novelize_access(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """스위치와 명단은 메모리 값이라 먼저 보고, 둘 다 통과할 때만 허용 행을 조회한다 — 꺼져 있는 동안 `/me` 가
    쿼리를 하나 더 쓰지 않는다."""
    if not settings.novelize_enabled or user_id not in settings.novelize_grant_allowlist:
        return False
    grant_id = await db.scalar(
        select(UserFeatureGrant.id).where(
            UserFeatureGrant.user_id == user_id, UserFeatureGrant.feature == "novelize"
        )
    )
    return grant_id is not None


async def require_novelize_access(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> uuid.UUID:
    """소설 삭제를 뺀 모든 소설 라우트(읽기 포함)의 게이트. 통과하면 user_id 를 돌려준다. 소설 삭제는 자기 데이터를
    지울 권리라 이 게이트 밖에서 로그인·소유권만 본다(`router.py` 의 `owner_router`).

    거부는 403 + `{"code": "NOVELIZE_NOT_ALLOWED"}` 한 가지다. 꺼짐·미허용·명단 제외를 구분하지 않는다 — 셋 다
    사용자가 할 수 있는 일이 없고, 구분해 내면 기능이 켜져 있는지가 바깥에 드러난다. 403 이어도 FE 의 정지 판정은
    detail 문자열(`"Account suspended"`)만 보므로 이 dict 403 이 세션을 비우지 않는다(작품 이용제한 403 과 같은 꼴)."""
    if not await has_novelize_access(db, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "NOVELIZE_NOT_ALLOWED"})
    return user_id
