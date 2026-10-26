"""모델 배정 표의 Redis 캐시 — 조회 수, Redis 실패 흡수, 범위 밖 행 버리기, 옛 형식 값."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import prompt_routing_cache
from api.chat.prompt_routing import PromptRoutes, RouteRow
from api.chat.prompt_routing_cache import (
    PROMPT_ROUTES_CACHE_KEY,
    invalidate_prompt_routes,
    load_prompt_routes,
)
from api.core.redis import redis_client
from api.db.models.prompt import PromptRoute
from factories import _count_queries


class _Calls:
    def __init__(self) -> None:
        self.get = 0
        self.set = 0
        self.db = 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    counted = _Calls()
    real_get = redis_client.get
    real_set = redis_client.set
    real_load = prompt_routing_cache.load_prompt_routes_from_db

    async def counting_get(*args: Any, **kwargs: Any) -> Any:
        counted.get += 1
        return await real_get(*args, **kwargs)

    async def counting_set(*args: Any, **kwargs: Any) -> Any:
        counted.set += 1
        return await real_set(*args, **kwargs)

    async def counting_load(db: AsyncSession) -> Any:
        counted.db += 1
        return await real_load(db)

    monkeypatch.setattr(redis_client, "get", counting_get)
    monkeypatch.setattr(redis_client, "set", counting_set)
    monkeypatch.setattr(prompt_routing_cache, "load_prompt_routes_from_db", counting_load)
    return counted


def _stat_row() -> PromptRoute:
    return PromptRoute(
        lane="story",
        room_model="opus",
        stage="stat_judgment",
        chain_model="opus",
        call_model="haiku",
        backend="anthropic",
    )


_EXPECTED_STAT_ROW = RouteRow(
    lane="story", room_model="opus", stage="stat_judgment", chain_model="opus", call_model="haiku", backend="anthropic"
)


async def test_an_empty_table_is_cached_so_the_second_read_skips_the_db(
    db_session: AsyncSession, calls: _Calls
) -> None:
    with _count_queries() as statements:
        first = await load_prompt_routes(db_session)
        after_first = statements()
        second = await load_prompt_routes(db_session)
        after_second = statements()

    assert first == second == PromptRoutes.empty()
    assert (calls.get, calls.db, calls.set) == (2, 1, 1)
    assert (after_first, after_second - after_first) == (1, 0)


async def test_a_table_with_rows_is_read_once_and_served_from_the_cache(
    db_session: AsyncSession, calls: _Calls
) -> None:
    db_session.add(_stat_row())
    db_session.add(
        PromptRoute(
            lane="character",
            room_model="gemini",
            stage="chat_generate",
            chain_model=None,
            call_model="gemini",
            backend="gemini",
        )
    )
    await db_session.flush()

    first = await load_prompt_routes(db_session)
    second = await load_prompt_routes(db_session)

    assert first == second
    assert first.get("story", "opus", "stat_judgment") == _EXPECTED_STAT_ROW
    generation = first.get("character", "gemini", "chat_generate")
    assert generation is not None
    assert (generation.chain_model, generation.call_model, generation.backend) == (None, "gemini", "gemini")
    assert (calls.get, calls.db, calls.set) == (2, 1, 1)


async def test_a_row_the_code_does_not_know_is_dropped_and_the_rest_is_read(
    db_session: AsyncSession, calls: _Calls, caplog: pytest.LogCaptureFixture
) -> None:
    db_session.add(_stat_row())
    db_session.add(
        PromptRoute(
            lane="character",
            room_model="opus",
            stage="stat_judgment",
            chain_model="opus",
            call_model="haiku",
            backend="anthropic",
        )
    )
    db_session.add(
        PromptRoute(
            lane="story",
            room_model="opus",
            stage="memory_fact",
            chain_model="opus",
            call_model="gpt",
            backend="anthropic",
        )
    )
    await db_session.flush()

    with caplog.at_level(logging.WARNING):
        from_db = await load_prompt_routes(db_session)
        from_cache = await load_prompt_routes(db_session)

    for routes in (from_db, from_cache):
        assert dict(routes.rows) == {("story", "opus", "stat_judgment"): _EXPECTED_STAT_ROW}
    assert sum("모르는 배정 행" in record.getMessage() for record in caplog.records) == 4


async def test_novel_rows_are_read_and_cached_with_their_own_cell_axes(db_session: AsyncSession, calls: _Calls) -> None:
    """소설 생성 칸은 작업 모델, 소설 구조화 칸은 표지 `any` 로 키가 잡힌다. 캐시를 거쳐도 같은 칸으로 읽혀야 해석이 그 행을 찾는다."""
    db_session.add(
        PromptRoute(
            lane="novel",
            room_model="any",
            stage="novel_revise",
            chain_model="sonnet",
            call_model="haiku",
            backend="anthropic",
        )
    )
    db_session.add(
        PromptRoute(
            lane="novel",
            room_model="sonnet",
            stage="novel_chapter",
            chain_model=None,
            call_model="sonnet",
            backend="anthropic",
        )
    )
    await db_session.flush()

    from_db = await load_prompt_routes(db_session)
    from_cache = await load_prompt_routes(db_session)

    assert from_db == from_cache
    assert from_db.get("novel", "any", "novel_revise") == RouteRow(
        lane="novel",
        room_model="any",
        stage="novel_revise",
        chain_model="sonnet",
        call_model="haiku",
        backend="anthropic",
    )
    chapter = from_db.get("novel", "sonnet", "novel_chapter")
    assert chapter is not None
    assert (chapter.chain_model, chapter.call_model) == (None, "sonnet")
    assert (calls.get, calls.db, calls.set) == (2, 1, 1)


def _failing() -> Callable[..., Awaitable[Any]]:
    async def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RedisError("down")

    return fail


async def test_redis_failures_on_get_and_set_fall_back_to_the_db_value(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    failures: list[str] = []
    monkeypatch.setattr(redis_client, "get", _failing())
    monkeypatch.setattr(redis_client, "set", _failing())
    monkeypatch.setattr(
        prompt_routing_cache, "capture_dependency_failure", lambda *, dependency: failures.append(dependency)
    )
    db_session.add(_stat_row())
    await db_session.flush()

    with caplog.at_level(logging.WARNING):
        routes = await load_prompt_routes(db_session)

    assert routes.get("story", "opus", "stat_judgment") == _EXPECTED_STAT_ROW
    assert failures == ["redis", "redis"]
    assert sum(record.levelno >= logging.WARNING for record in caplog.records) >= 2


async def test_a_cached_value_in_an_old_shape_is_a_miss_and_is_rewritten(
    db_session: AsyncSession, calls: _Calls
) -> None:
    await redis_client.set(PROMPT_ROUTES_CACHE_KEY, '{"routes": "old shape"}')
    calls.set = 0  # 옛 값을 심은 SET 은 세지 않는다
    db_session.add(_stat_row())
    await db_session.flush()

    first = await load_prompt_routes(db_session)
    second = await load_prompt_routes(db_session)

    assert first == second
    assert first.get("story", "opus", "stat_judgment") == _EXPECTED_STAT_ROW
    assert (calls.get, calls.db, calls.set) == (2, 1, 1)


async def test_invalidation_removes_the_cached_table(db_session: AsyncSession, calls: _Calls) -> None:
    await load_prompt_routes(db_session)
    await invalidate_prompt_routes()
    await load_prompt_routes(db_session)

    assert calls.db == 2


async def test_invalidation_does_not_swallow_a_redis_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """무효화가 실패하면 옛 표가 TTL 만큼 나간다. 감수할지 저장 자체를 실패시킬지는 저장 API 가 정한다."""
    monkeypatch.setattr(redis_client, "delete", _failing())

    with pytest.raises(RedisError):
        await invalidate_prompt_routes()
