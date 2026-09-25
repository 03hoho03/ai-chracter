import logging
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from redis.exceptions import RedisError

from api.chat.prompt_builder import PromptLane
from api.core.config import settings
from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure
from api.db.models.prompt import PromptSection, PromptSet

# uvicorn은 root logger에 핸들러를 안 붙여 info는 조용히 사라진다(apps/api/CLAUDE.md
# "SSE 스트리밍" 절) — 아래 GET/SET 폴백은 warning 이상으로 남겨야 캐시가 계속 죽어 있어 매 턴 DB를
# 치는 상태를 조용히 지나치지 않는다.
logger = logging.getLogger(__name__)

# 레인마다 키가 하나다 — `prompt_set:active:story`
# 등. 옛 키(`prompt_set:active`)를 재사용하면 옛 코드가 쓴 48행 통짜 세트를 새 코드가
# 자기 레인 값으로 오인해 읽는다. 이름을 바꾸면 그 사고가 타입 수준으로 불가능해진다 —
# 옛 키는 아무도 안 쓴 채 TTL 300초(core/config.py:161)로 자연 소멸한다.
#
# 세 Redis 모듈(`preview_session.py` 등)과 달리 키에 랜덤
# ID가 없다 — 레인별 활성 세트는 전역에 하나뿐이다. 그래서 conftest.py가 매 테스트 전 이
# 프리픽스로 시작하는 키를 전부 지우는 autouse 픽스처를 따로 둬야 한다(고정 키는 테스트끼리
# 안 격리된다).
ACTIVE_PROMPT_SET_KEY_PREFIX = "prompt_set:active:"


def _active_prompt_set_key(lane: PromptLane) -> str:
    return f"{ACTIVE_PROMPT_SET_KEY_PREFIX}{lane}"


class _CachedPromptSet(BaseModel):
    """`PromptSet` 헤더 필드를 그대로 옮긴 직렬화 전용 모델.

    `lane`은 `PromptLane`이 아니라 `str`이다 — 같은 모델의 `status`가 전부 `str`이고,
    Literal로 좁히면 legacy 값이 들어왔을 때 역직렬화가 통째로 터진다(캐시는 순수
    최적화라 실패가 요청을 죽이면 안 된다는 이 모듈의 설계와 충돌한다)."""

    id: UUID
    version: str | None
    status: str
    lane: str
    user_label: str
    story_assistant_label: str
    story_example_label: str
    character_assistant_label: str
    note: str
    created_at: datetime
    published_at: datetime | None


class _CachedPromptSection(BaseModel):
    """`PromptSection` 한 행을 그대로 옮긴 직렬화 전용 모델."""

    id: UUID
    prompt_set_id: UUID
    channel: str
    scope: str
    slot: str
    variant: str
    body: str
    conditional: bool
    order: int


class _CachedActivePromptSet(BaseModel):
    """`_active_prompt_set_key(lane)`에 저장하는 값 — 세트 헤더 + 섹션 목록을 함께 담는다."""

    prompt_set: _CachedPromptSet
    sections: list[_CachedPromptSection]


def _to_cached_prompt_set(prompt_set: PromptSet) -> _CachedPromptSet:
    return _CachedPromptSet(
        id=prompt_set.id,
        version=prompt_set.version,
        status=prompt_set.status,
        lane=prompt_set.lane,
        user_label=prompt_set.user_label,
        story_assistant_label=prompt_set.story_assistant_label,
        story_example_label=prompt_set.story_example_label,
        character_assistant_label=prompt_set.character_assistant_label,
        note=prompt_set.note,
        created_at=prompt_set.created_at,
        published_at=prompt_set.published_at,
    )


def _to_cached_section(section: PromptSection) -> _CachedPromptSection:
    return _CachedPromptSection(
        id=section.id,
        prompt_set_id=section.prompt_set_id,
        channel=section.channel,
        scope=section.scope,
        slot=section.slot,
        variant=section.variant,
        body=section.body,
        conditional=section.conditional,
        order=section.order,
    )


def _from_cached_prompt_set(cached: _CachedPromptSet) -> PromptSet:
    return PromptSet(
        id=cached.id,
        version=cached.version,
        status=cached.status,
        lane=cached.lane,
        user_label=cached.user_label,
        story_assistant_label=cached.story_assistant_label,
        story_example_label=cached.story_example_label,
        character_assistant_label=cached.character_assistant_label,
        note=cached.note,
        created_at=cached.created_at,
        published_at=cached.published_at,
    )


def _from_cached_section(cached: _CachedPromptSection) -> PromptSection:
    return PromptSection(
        id=cached.id,
        prompt_set_id=cached.prompt_set_id,
        channel=cached.channel,
        scope=cached.scope,
        slot=cached.slot,
        variant=cached.variant,
        body=cached.body,
        conditional=cached.conditional,
        order=cached.order,
    )


async def get_cached_active_prompt_set(lane: PromptLane) -> tuple[PromptSet, list[PromptSection]] | None:
    """`lane`의 캐시 히트면 DB에 닿지 않고 값을 재구성해 돌려준다. 미스면 `None` — 활성
    세트가 없다는 사실 자체는 절대 캐싱하지 않는다(negative caching 금지) —
    시드/게시 직후 복구가 TTL만큼 늦어지는 것을 막기 위해서다.

    `RedisError`는 캐시 미스처럼 삼킨다 — DB가 진짜 소스이고 캐시는 순수 최적화라
    (`content/view_count.py`와 같은 구조), 최적화가 죽었다고 진짜 소스가 멀쩡한 요청까지
    실패할 이유가 없다. 다만 이 함수 앞에는 이미 `get_current_user_id` 등 Redis에 의존하는
    `Depends`가 있어(`session/store.py`) **Redis 장애 자체는 이 변경과 무관하게 채팅을
    이미 인증 단계에서 죽인다** — 이 폴백이 "Redis 장애에도 채팅이 산다"는 뜻은 아니다.
    이건 그와 별개로, 캐시 계층 자체의 실패가 (Redis가 살아 있든 죽어 있든) 원래 성공했을
    DB 폴백 경로까지 끌어내리지 않게 하는 방어다."""
    try:
        raw = await redis_client.get(_active_prompt_set_key(lane))
    except RedisError:
        logger.warning("프롬프트 세트 캐시 조회 실패 — DB로 폴백한다", exc_info=True)
        # 조용한 성능 저하이자 Redis 이상 신호라 이벤트로도 남긴다.
        capture_dependency_failure(dependency="redis")
        return None
    if raw is None:
        return None
    cached = _CachedActivePromptSet.model_validate_json(raw)
    return _from_cached_prompt_set(cached.prompt_set), [_from_cached_section(s) for s in cached.sections]


async def set_cached_active_prompt_set(
    lane: PromptLane, prompt_set: PromptSet, sections: Sequence[PromptSection]
) -> None:
    """캐시 미스 뒤 DB에서 읽은 값을 `lane` 키에 채운다. `settings.prompt_set_cache_ttl_seconds`를
    상한으로 둔다 — `invalidate_active_prompt_set`의 `DEL`이 무효화의 정공법이고, TTL은 그
    호출이 누락되는 경로가 생겼을 때만 옛 문안을 걷어내는 안전망이다.

    `RedisError`는 조용히 포기한다(위 `get_cached_active_prompt_set`과 같은 근거) — 호출
    시점에 이미 DB 조회가 성공해 유효한 세트를 손에 쥐고 있다. 그 값을 캐시에 채우는 것은
    다음 요청을 위한 최적화일 뿐이라, 이 `SET` 하나가 실패했다고 이미 손에 쥔 값을 버리고
    이번 요청 전체를 500으로 만들면 안 된다."""
    cached = _CachedActivePromptSet(
        prompt_set=_to_cached_prompt_set(prompt_set),
        sections=[_to_cached_section(section) for section in sections],
    )
    try:
        await redis_client.set(
            _active_prompt_set_key(lane), cached.model_dump_json(), ex=settings.prompt_set_cache_ttl_seconds
        )
    except RedisError:
        logger.warning("프롬프트 세트 캐시 저장 실패 — 이번 요청은 이미 손에 쥔 값으로 계속 진행한다", exc_info=True)
        # 조용한 성능 저하이자 Redis 이상 신호라 이벤트로도 남긴다.
        capture_dependency_failure(dependency="redis")


async def invalidate_active_prompt_set(lane: PromptLane) -> None:
    """`lane` 키 하나만 지운다 — 게시는 레인 단위 이벤트이고, 셋을 다 지우면 다른
    레인의 캐시를 이유 없이 버린다.

    ⚠️ 반드시 게시 트랜잭션이 **커밋된 뒤** 호출해야 한다 — 커밋 전에 지우면 그 사이에 들어온
    캐시 미스가 아직 커밋되지 않은(=옛) 값을 다시 읽어 SET 해버려, 게시 자체가 통째로
    씹힌다.

    위 GET/SET과 달리 `RedisError`를 여기서 삼키지 않는다 — 무효화가 실패하면 옛 문안이
    TTL만큼 계속 나가는데, 그걸 감수할지·재시도할지·게시 자체를 실패시킬지는 호출자(게시
    API)가 알고 결정할 문제다. 이 모듈이 대신 정하지 않는다."""
    await redis_client.delete(_active_prompt_set_key(lane))
