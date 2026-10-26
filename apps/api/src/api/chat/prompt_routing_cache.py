"""모델 배정 표의 Redis 캐시. 구조는 프롬프트 세트 캐시(`chat/prompt_set_cache.py`)를 따른다.

표 전체를 키 하나(`prompt_routes:all`)에 담는다. 표는 많아야 (스토리 8 + 캐릭터 5) × 방 모델 2 + 소설 생성 3 × 작업 모델 3 +
소설 구조화 4 = 39 행이라 작고, 키가 하나라야 해석 한 번에 Redis GET 한 번으로 끝난다. 히트면 GET 1, 미스면 GET 1 + DB SELECT 1 + SET 1 이다.

빈 표도 캐시한다. 프롬프트 세트 캐시가 "활성 세트 없음"을 캐시하지 않는 것은 시드·게시 직후 복구가 TTL 만큼 늦어지기
때문인데, 빈 배정 표는 "없음"이 아니라 정상 상태(전부 env 규칙)이고 비우는 것도 어드민 저장이 해 저장 커밋 뒤 무효화로 바로
바뀐다. 빈 표를 캐시하지 않으면 운영 기본 상태에서 매 턴 DB 를 친다.

키에 랜덤 값이 없어 테스트끼리 격리되지 않는다 — `tests/conftest.py` 가 매 테스트 전에 이 접두의 키를 지운다.
"""

import logging
from collections.abc import Iterable

from pydantic import BaseModel, ValidationError
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_routing import PromptRoutes, RouteKey, RouteRow, RouteRowInput, parse_route_row
from api.core.config import settings
from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure
from api.db.models.prompt import PromptRoute

# GET·SET 폴백은 warning 으로 남긴다 — uvicorn 은 root logger 에 핸들러를 붙이지 않아 info 는 사라진다. 캐시가 계속 죽어 매 턴
# DB 를 치는 상태를 조용히 지나치지 않게 한다.
logger = logging.getLogger(__name__)

PROMPT_ROUTES_CACHE_KEY_PREFIX = "prompt_routes:"
PROMPT_ROUTES_CACHE_KEY = f"{PROMPT_ROUTES_CACHE_KEY_PREFIX}all"


class _CachedRoute(BaseModel):
    """표 한 행을 그대로 옮긴 직렬화 전용 모델. 값을 Literal 로 좁히지 않는다 — 지금 코드가 모르는 값(내린 단계·모델)이 한 행에
    있다고 역직렬화가 통째로 터지면 안 된다. 범위 밖 행은 `PromptRoutes` 로 옮길 때 그 행만 버린다."""

    lane: str
    room_model: str
    stage: str
    chain_model: str | None
    call_model: str
    backend: str


class _CachedPromptRoutes(BaseModel):
    rows: list[_CachedRoute]


async def load_prompt_routes_from_db(db: AsyncSession) -> list[RouteRowInput]:
    """표 전체를 DB 에서 그대로 읽는다(값 범위는 보지 않는다)."""
    rows = (await db.scalars(select(PromptRoute))).all()
    return [
        RouteRowInput(
            lane=row.lane,
            room_model=row.room_model,
            stage=row.stage,
            chain_model=row.chain_model,
            call_model=row.call_model,
            backend=row.backend,
        )
        for row in rows
    ]


def _to_routes(rows: Iterable[RouteRowInput]) -> PromptRoutes:
    """읽은 행을 해석이 받는 표로 옮긴다. 지금 코드가 모르는 값이거나 모양이 틀린 행은 그 행만 버리고 경고를 남긴다 — 해석은 그
    칸을 env 규칙으로 푼다. DB 와 캐시에서 읽은 값이 같은 함수를 거친다."""
    by_key: dict[RouteKey, RouteRow] = {}
    for raw in rows:
        row = parse_route_row(raw)
        if row is None:
            logger.warning("모르는 배정 행을 버린다 — 그 칸은 env 규칙으로 푼다 row=%s", raw)
            continue
        key = (row.lane, row.room_model, row.stage)
        if key in by_key:
            logger.warning("모르는 배정 행을 버린다 — 같은 칸의 행이 이미 있다 row=%s", raw)
            continue
        by_key[key] = row
    return PromptRoutes(by_key)


async def _get_cached() -> list[RouteRowInput] | None:
    try:
        raw = await redis_client.get(PROMPT_ROUTES_CACHE_KEY)
    except RedisError:
        logger.warning("배정 표 캐시 조회 실패 — DB 로 폴백한다", exc_info=True)
        capture_dependency_failure(dependency="redis")
        return None
    if raw is None:
        return None
    try:
        cached = _CachedPromptRoutes.model_validate_json(raw)
    except ValidationError:
        # 프롬프트 세트 캐시와 달리 미스로 본다 — 다음에 값의 형식을 바꾸면, 배포가 겹치는 동안 옛 형식 값 때문에 매 턴 500 이
        # 나지 않고 한 번 다시 읽어 갈아 쓴다.
        logger.warning("배정 표 캐시 값의 형식이 다르다 — DB 에서 다시 읽어 갈아 쓴다")
        return None
    return [
        RouteRowInput(
            lane=row.lane,
            room_model=row.room_model,
            stage=row.stage,
            chain_model=row.chain_model,
            call_model=row.call_model,
            backend=row.backend,
        )
        for row in cached.rows
    ]


async def _set_cached(rows: list[RouteRowInput]) -> None:
    cached = _CachedPromptRoutes(
        rows=[
            _CachedRoute(
                lane=row.lane,
                room_model=row.room_model,
                stage=row.stage,
                chain_model=row.chain_model,
                call_model=row.call_model,
                backend=row.backend,
            )
            for row in rows
        ]
    )
    try:
        # TTL 은 프롬프트 세트 캐시와 같은 설정이다 — 무효화가 정공법이고 TTL 은 무효화가 빠진 경로의 안전망이라 근거가 같다.
        await redis_client.set(
            PROMPT_ROUTES_CACHE_KEY, cached.model_dump_json(), ex=settings.prompt_set_cache_ttl_seconds
        )
    except RedisError:
        logger.warning("배정 표 캐시 저장 실패 — 이번 요청은 이미 읽은 값으로 계속한다", exc_info=True)
        capture_dependency_failure(dependency="redis")


async def load_prompt_routes(db: AsyncSession) -> PromptRoutes:
    """표 전체. 캐시 히트면 Redis GET 1 번, 미스면 GET 1 + DB SELECT 1 + SET 1 번이다. `db` 는 부르는 쪽이 정한다(미리보기는 짧게
    여닫는 세션으로 읽는다). Redis 실패는 삼키고 DB 값으로 계속한다 — DB 가 소스이고 캐시는 최적화다."""
    rows = await _get_cached()
    if rows is None:
        rows = await load_prompt_routes_from_db(db)
        await _set_cached(rows)
    return _to_routes(rows)


async def load_prompt_routes_with(session_factory: async_sessionmaker[AsyncSession]) -> PromptRoutes:
    """`load_prompt_routes` 와 같되 캐시 미스일 때만 `session_factory` 로 짧은 세션을 열어 읽는다 — 히트면 세션을 열지 않는다.
    요청 세션에 기대지 않는 미리보기 의존성이 쓴다."""
    rows = await _get_cached()
    if rows is None:
        async with session_factory() as session:
            rows = await load_prompt_routes_from_db(session)
        await _set_cached(rows)
    return _to_routes(rows)


async def invalidate_prompt_routes() -> None:
    """캐시를 지운다. 반드시 저장 트랜잭션이 **커밋된 뒤** 부른다 — 커밋 전에 지우면 그 사이의 미스가 옛 표를 다시 채운다.
    `RedisError` 는 삼키지 않는다. 옛 표가 TTL 만큼 나가는 것을 감수할지는 부르는 쪽(어드민 저장)이 정한다."""
    await redis_client.delete(PROMPT_ROUTES_CACHE_KEY)
