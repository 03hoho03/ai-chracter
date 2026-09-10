"""prompt-db-goal-prompt.md §8-1 (3단계, T-31/T-32/T-35) — Redis 캐시 모듈과 그 앞의 두
`Depends`(`_active_prompt_set_dependency`/`_preview_prompt_set_dependency`) 배선을 검증한다.

`conftest.py`의 `_flush_prompt_set_cache`(autouse)가 매 테스트 전 `prompt_set:active`를
지워준다 — 이 키는 랜덤 ID가 없는 고정 키라 그 픽스처 없이는 한 테스트가 캐싱한 세트를
다음 테스트가 그대로 보게 된다(같은 문서 §8-1의 경고).
"""

import logging

import sqlalchemy as sa
import pytest
import pytest_asyncio
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat.prompt_builder import PromptSetNotFoundError, load_active_prompt_set
from api.chat.prompt_set_cache import (
    ACTIVE_PROMPT_SET_KEY,
    get_cached_active_prompt_set,
    invalidate_active_prompt_set,
    set_cached_active_prompt_set,
)
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models.prompt import PromptSection, PromptSet
from factories import _count_queries


async def _raise_redis_error(*args: object, **kwargs: object) -> None:
    raise RedisError("connection refused")


@pytest_asyncio.fixture
async def active_prompt_set(db_session: AsyncSession) -> tuple[PromptSet, list[PromptSection]]:
    """`_migrated_schema`(세션 스코프 autouse)가 심어 둔 실제 활성 세트를 그대로 읽는다 —
    합성 값 대신 이걸 쓰는 이유는 캐시 대상 함수(`load_active_prompt_set`) 자체를 통해
    읽어, 그 함수가 실제로 반환하는 모양과 캐시 모듈이 어긋나지 않는지까지 같이 본다."""
    return await load_active_prompt_set(db_session)


# ---- 캐시 모듈 자체 — GET/SET/DEL --------------------------------------------


async def test_get_returns_none_on_cache_miss() -> None:
    assert await get_cached_active_prompt_set() is None


async def test_set_then_get_round_trips_prompt_set_and_sections(
    active_prompt_set: tuple[PromptSet, list[PromptSection]],
) -> None:
    prompt_set, sections = active_prompt_set

    await set_cached_active_prompt_set(prompt_set, sections)
    cached = await get_cached_active_prompt_set()

    assert cached is not None
    cached_prompt_set, cached_sections = cached
    assert cached_prompt_set.id == prompt_set.id
    assert cached_prompt_set.version == prompt_set.version
    assert cached_prompt_set.user_label == prompt_set.user_label
    assert cached_prompt_set.story_assistant_label == prompt_set.story_assistant_label
    assert cached_prompt_set.story_example_label == prompt_set.story_example_label
    assert cached_prompt_set.character_assistant_label == prompt_set.character_assistant_label
    assert cached_prompt_set.created_at == prompt_set.created_at
    assert cached_prompt_set.published_at == prompt_set.published_at
    assert {s.id for s in cached_sections} == {s.id for s in sections}
    assert {(s.channel, s.slot, s.variant, s.body, s.conditional, s.order) for s in cached_sections} == {
        (s.channel, s.slot, s.variant, s.body, s.conditional, s.order) for s in sections
    }


async def test_set_applies_the_configured_ttl(
    active_prompt_set: tuple[PromptSet, list[PromptSection]],
) -> None:
    prompt_set, sections = active_prompt_set
    await set_cached_active_prompt_set(prompt_set, sections)

    ttl = await redis_client.ttl(ACTIVE_PROMPT_SET_KEY)

    assert 0 < ttl <= settings.prompt_set_cache_ttl_seconds


async def test_invalidate_deletes_the_cached_value(
    active_prompt_set: tuple[PromptSet, list[PromptSection]],
) -> None:
    prompt_set, sections = active_prompt_set
    await set_cached_active_prompt_set(prompt_set, sections)
    assert await get_cached_active_prompt_set() is not None

    await invalidate_active_prompt_set()

    assert await get_cached_active_prompt_set() is None


# ---- 실제 채팅 경로 — `_active_prompt_set_dependency` --------------------------


async def test_active_prompt_set_dependency_hits_cache_serves_stale_value_and_refreshes_after_invalidation(
    db_session: AsyncSession,
) -> None:
    """한 흐름으로 세 가지를 증명한다 — ① 캐시 히트 시 DB 조회 0건, ② 캐시가 살아있는 동안
    DB를 바꿔도 옛 값이 나온다(진짜 캐시라는 증거), ③ 무효화 뒤 다음 조회는 새 값이다."""
    with _count_queries() as get_count:
        prompt_set, _ = await chat_router._active_prompt_set_dependency(db=db_session)
    assert get_count() > 0  # 콜드 스타트 — 실제로 DB 를 읽었다
    original_note = prompt_set.note

    # 캐시는 그대로 둔 채 DB만 직접 바꾼다.
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.id == prompt_set.id).values(note="캐시-오염-확인용-새-값")
    )
    await db_session.flush()

    with _count_queries() as get_count:
        cached_prompt_set, _ = await chat_router._active_prompt_set_dependency(db=db_session)
    assert get_count() == 0  # 캐시 히트 — DB 조회 0건
    assert cached_prompt_set.note == original_note  # 옛 값 그대로

    await invalidate_active_prompt_set()

    with _count_queries() as get_count:
        refreshed_prompt_set, _ = await chat_router._active_prompt_set_dependency(db=db_session)
    assert get_count() > 0  # 무효화 뒤엔 다시 DB 를 읽는다
    assert refreshed_prompt_set.note == "캐시-오염-확인용-새-값"


async def test_active_prompt_set_dependency_does_not_cache_a_missing_active_set(
    db_session: AsyncSession,
) -> None:
    """negative caching 금지(§8-1) — 활성 세트가 없다는 사실 자체는 캐싱하지 않는다. 그래야
    시드/재게시 직후 복구가 TTL만큼 늦어지지 않는다."""
    await db_session.execute(sa.update(PromptSet).where(PromptSet.status == "published").values(status="archived"))
    await db_session.flush()

    with pytest.raises(PromptSetNotFoundError):
        await chat_router._active_prompt_set_dependency(db=db_session)

    assert await get_cached_active_prompt_set() is None

    await db_session.execute(sa.update(PromptSet).where(PromptSet.status == "archived").values(status="published"))
    await db_session.flush()

    prompt_set, _ = await chat_router._active_prompt_set_dependency(db=db_session)
    assert prompt_set.status == "published"


# ---- Redis 장애 내성 — 적대적 리뷰 대응 --------------------------------------
#
# 근거: `send_message`/`regenerate_message`/`edit_message`는 이 diff 이전에도 `_owned_room_
# dependency` → `get_current_user_id` → `session/store.py`의 `redis_client.get`을 이미 거친다
# (`Depends`는 시그니처 순서대로 순차 resolve되므로 인증이 먼저다) — 그래서 Redis 자체가
# 죽으면 이 캐시 이전에도 채팅은 이미 인증 단계에서 죽는다. 이번 폴백이 "Redis 장애에도
# 채팅이 산다"는 뜻은 아니다. 그래도 고쳐야 했던 건 따로 있다 — DB 조회가 이미 성공해
# 유효한 세트를 손에 쥔 상태에서 그 값을 캐시에 채우는 `SET` 하나(또는 그 앞의 `GET`)가
# 실패했다고 이미 성공한 요청을 500으로 만들면 안 된다는 것. DB가 진짜 소스이고 캐시는
# 순수 최적화라는 구조가 `content/view_count.py`와 같으므로 그쪽 패턴(RedisError를 캐시
# 미스처럼 삼킨다)을 따른다.


async def test_active_prompt_set_dependency_falls_back_to_db_when_cache_read_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(redis_client, "get", _raise_redis_error)

    with caplog.at_level(logging.WARNING):
        prompt_set, sections = await chat_router._active_prompt_set_dependency(db=db_session)

    assert prompt_set.status == "published"
    assert sections
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


async def test_active_prompt_set_dependency_succeeds_when_cache_write_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(redis_client, "set", _raise_redis_error)

    with caplog.at_level(logging.WARNING):
        prompt_set, sections = await chat_router._active_prompt_set_dependency(db=db_session)

    assert prompt_set.status == "published"
    assert sections
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


# ---- 미리보기 경로 — `_preview_prompt_set_dependency` --------------------------


class _ExplodingSessionFactory:
    """캐시 히트에서 세션 팩토리가 호출되면 안 된다는 것을 증명하는 페이크 — 호출되면
    즉시 실패한다."""

    def __call__(self) -> AsyncSession:
        raise AssertionError("캐시 히트인데 세션 팩토리가 호출됐다")


async def test_preview_prompt_set_dependency_does_not_open_a_session_on_cache_hit(
    active_prompt_set: tuple[PromptSet, list[PromptSection]],
) -> None:
    prompt_set, sections = active_prompt_set
    await set_cached_active_prompt_set(prompt_set, sections)

    result_prompt_set, result_sections = await chat_router._preview_prompt_set_dependency(
        session_factory=_ExplodingSessionFactory()  # type: ignore[arg-type]
    )

    assert result_prompt_set.id == prompt_set.id
    assert len(result_sections) == len(sections)
