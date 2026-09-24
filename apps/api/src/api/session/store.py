import json
import time
import uuid
from typing import Any

from api.core.config import settings
from api.core.redis import redis_client


def _session_key(session_id: str) -> str:
    return f"session:{session_id}"


def _user_sessions_key(user_id: uuid.UUID) -> str:
    return f"user_sessions:{user_id}"


async def create_session(user_id: uuid.UUID) -> str:
    """새 세션을 만들고 그 유저의 역인덱스 ZSET(score = 세션 만료 epoch)에 올린다
    (backlog-sweep-goal-prompt.md BS-5).

    세션 TTL은 읽을 때 갱신되지 않으므로 방금 만든 세션이 그 유저의 가장 늦게 만료되는
    세션이다 — 그래서 인덱스 키 TTL을 매번 세션 TTL로 다시 걸면 키 수명이 가장 최근 세션의
    수명과 같아진다. 이미 만료된 멤버는 여기서 정리해 멤버 수를 "최근 TTL 기간의 로그인 수"로 묶는다.
    """
    session_id = uuid.uuid4().hex
    ttl = settings.session_ttl_seconds
    now = time.time()
    index_key = _user_sessions_key(user_id)
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.set(_session_key(session_id), json.dumps({"user_id": str(user_id)}), ex=ttl)
        pipe.zadd(index_key, {session_id: now + ttl})
        pipe.zremrangebyscore(index_key, "-inf", now)
        pipe.expire(index_key, ttl)
        await pipe.execute()
    return session_id


async def get_session(session_id: str) -> dict[str, Any] | None:
    raw = await redis_client.get(_session_key(session_id))
    if raw is None:
        return None
    data: dict[str, Any] = json.loads(raw)
    return data


async def delete_session(session_id: str) -> None:
    await redis_client.delete(_session_key(session_id))


async def revoke_user_sessions(user_id: uuid.UUID, *, except_session_id: str | None = None) -> None:
    """그 유저의 색인된 세션을 전부(`except_session_id`만 빼고) 지운다(backlog-sweep-goal-prompt.md BS-6).

    인덱스 키를 통째로 DEL하지 않고 읽은 멤버만 ZREM한다 — 읽은 뒤 동시 로그인이 추가한 멤버를
    날리지 않기 위해서다. WATCH는 쓰지 않는다(BS-5): 고쳐 쓸 값이 없어 갱신 유실이 없고, 남는
    경합은 "ZRANGE 뒤에 생긴 새 세션이 산다" 하나다 — 탈퇴 뒤의 세션은 `get_current_user_id`의
    `users` 조회가 401로 막고, 비밀번호 변경·재설정 뒤의 새 로그인은 새 비밀번호로 한 정상 로그인이다.
    """
    index_key = _user_sessions_key(user_id)
    # `decode_responses=True`(core/redis.py)라 멤버는 이미 str이다 — 스텁이 withscores 형태까지
    # 합친 유니언을 돌려줘서 str로 좁힌다.
    members = await redis_client.zrange(index_key, 0, -1)
    session_ids = [str(sid) for sid in members if sid != except_session_id]
    if not session_ids:
        return
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.delete(*[_session_key(sid) for sid in session_ids])
        pipe.zrem(index_key, *session_ids)
        await pipe.execute()
