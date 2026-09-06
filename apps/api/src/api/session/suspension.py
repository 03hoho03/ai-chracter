import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.redis import redis_client
from api.db.models.auth import User

# `session/store.py`가 다루는 "세션"(session:{uuid} -> user_id, TTL 있음, 로그인 상태)과는
# 반대 방향(user_id -> 정지 여부)이고 TTL도 없어(정지가 풀릴 때까지 영구) 별도 모듈로 뺐다 —
# `api/admin/session.py`가 `session/{store,cookies,dependencies}.py`를 파라미터화 대신
# 통째로 복제한 것과 같은 판단 기준(키 프리픽스/TTL 정책이 다르면 새 모듈)이다.
SUSPENDED_USER_KEY_PREFIX = "suspended_user:"


def _suspended_user_key(user_id: uuid.UUID) -> str:
    return f"{SUSPENDED_USER_KEY_PREFIX}{user_id}"


async def mark_user_suspended(user_id: uuid.UUID) -> None:
    """TTL 없음 — `unmark_user_suspended`로 해제될 때까지 영구."""
    await redis_client.set(_suspended_user_key(user_id), "1")


async def unmark_user_suspended(user_id: uuid.UUID) -> None:
    await redis_client.delete(_suspended_user_key(user_id))


async def is_user_suspended(user_id: uuid.UUID) -> bool:
    return bool(await redis_client.exists(_suspended_user_key(user_id)))


async def rebuild_suspended_user_markers(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """앱 기동 시(TS-4) DB의 `suspended_at`을 진실로 삼아 Redis 마커를 다시 세운다.

    Redis 볼륨이 날아가도(재시작, AOF/RDB 유실) 정지가 조용히 풀리지 않게 하는 안전장치다
    — DB가 진실이므로 기동 시 한 번 다시 SET한다.

    **마커를 지우지는 않는다(추가만).** DB에서는 해제됐는데 마커가 남는 경우는 정지·해제
    트랜잭션의 DB 커밋과 Redis SET/DEL 사이 크래시뿐이고, 그때는 관리자가 해제를 한 번 더
    누르면 낫는다. 전체 동기화(마커 삭제 포함)를 하려면 Redis SCAN으로 기존 마커 전체를
    훑어야 하는데, 그건 goal-prompt §3-3이 "SCAN 전수 순회는 O(n)이라 습관으로 삼을 게
    못 된다"며 배제한 것과 같은 종류의 경로라 여기서도 하지 않는다. 정지 유저 수가 적어
    이 비용은 사실상 0이다.
    """
    async with session_factory() as session:
        user_ids = (
            await session.scalars(
                select(User.id).where(User.suspended_at.is_not(None), User.deleted_at.is_(None))
            )
        ).all()

    if not user_ids:
        return

    async with redis_client.pipeline() as pipe:
        for user_id in user_ids:
            pipe.set(_suspended_user_key(user_id), "1")
        await pipe.execute()
