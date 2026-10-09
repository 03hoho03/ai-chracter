"""노벨 조회 수의 하루 한 번 거르기.

작품 조회(`content/view_count.py`)와 같은 Redis `SET NX` 꼴이지만 키 접두(`novel_view:`)가 다르다 — 접두나 TTL 이 다른
Redis 상태는 기존 모듈을 인자로 넓히지 않고 모듈을 나누는 것이 이 저장소의 관례다. 노벨은 로그인한 회원만 읽으므로 비회원
쿠키 갈래가 없다."""

import uuid

from redis.exceptions import RedisError

from api.core.config import settings
from api.core.redis import redis_client


async def try_mark_novel_viewed(novel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """(소설, 회원)을 본 것으로 표시하고, 거르기 창(작품 조회와 같은 길이) 안의 첫 조회일 때만 참이다. `SET NX` 가 검사와
    표시를 한 번에 한다. Redis 가 실패하면 거짓이다 — 조회 수 때문에 읽기 요청이 실패하지 않게."""
    try:
        was_set = await redis_client.set(
            f"novel_view:{novel_id}:user:{user_id}",
            "1",
            nx=True,
            ex=settings.content_view_dedup_ttl_seconds,
        )
    except RedisError:
        return False
    return bool(was_set)
