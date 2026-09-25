"""세션 역인덱스 ZSET `user_sessions:{user_id}`.

score는 세션 만료 epoch(초)다. 세션 TTL은 읽을 때 갱신되지 않으므로 인덱스 키의 수명을
가장 최근 세션의 수명으로 맞추고, 만료된 멤버는 다음 생성 때 정리한다.
"""

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from api.core.config import settings
from api.core.redis import redis_client
from api.session import store


def _index_key(user_id: uuid.UUID) -> str:
    return f"user_sessions:{user_id}"


async def test_create_session_indexes_session_under_user_with_expiry_score() -> None:
    user_id = uuid.uuid4()

    session_id = await store.create_session(user_id)

    raw = await redis_client.get(f"session:{session_id}")
    assert raw is not None
    assert json.loads(raw) == {"user_id": str(user_id)}
    score = await redis_client.zscore(_index_key(user_id), session_id)
    assert score is not None
    assert abs(score - (time.time() + settings.session_ttl_seconds)) < 5
    assert abs(await redis_client.ttl(_index_key(user_id)) - settings.session_ttl_seconds) < 5


async def test_create_session_prunes_expired_members() -> None:
    user_id = uuid.uuid4()
    await redis_client.zadd(_index_key(user_id), {"stale": time.time() - 60})

    await store.create_session(user_id)

    assert await redis_client.zscore(_index_key(user_id), "stale") is None


async def test_create_session_extends_index_ttl_to_newest_session() -> None:
    user_id = uuid.uuid4()
    await redis_client.zadd(_index_key(user_id), {"older": time.time() + 10})
    await redis_client.expire(_index_key(user_id), 10)

    await store.create_session(user_id)

    assert abs(await redis_client.ttl(_index_key(user_id)) - settings.session_ttl_seconds) < 5


async def test_revoke_user_sessions_keeps_only_the_excepted_session() -> None:
    user_id = uuid.uuid4()
    kept, *revoked = [await store.create_session(user_id) for _ in range(3)]

    await store.revoke_user_sessions(user_id, except_session_id=kept)

    assert await redis_client.exists(f"session:{kept}") == 1
    for session_id in revoked:
        assert await redis_client.exists(f"session:{session_id}") == 0
    # 인덱스 키를 통째로 지우지 않고 멤버만 뺀다 — 제외한 세션은 계속 색인돼 있어야 다음 폐기가 찾는다.
    assert await redis_client.zrange(_index_key(user_id), 0, -1) == [kept]


async def test_revoke_user_sessions_spares_session_created_after_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    old = await store.create_session(user_id)
    original_zrange: Callable[..., Awaitable[Any]] = redis_client.zrange
    created_during_revoke: list[str] = []

    async def zrange_then_concurrent_login(*args: Any, **kwargs: Any) -> Any:
        members = await original_zrange(*args, **kwargs)
        created_during_revoke.append(await store.create_session(user_id))
        return members

    monkeypatch.setattr(redis_client, "zrange", zrange_then_concurrent_login)

    await store.revoke_user_sessions(user_id)

    monkeypatch.undo()
    [new] = created_during_revoke
    assert await redis_client.exists(f"session:{old}") == 0
    assert await redis_client.exists(f"session:{new}") == 1
    assert await redis_client.zrange(_index_key(user_id), 0, -1) == [new]


async def test_revoke_user_sessions_without_sessions_is_a_no_op() -> None:
    await store.revoke_user_sessions(uuid.uuid4())
