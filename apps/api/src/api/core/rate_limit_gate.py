"""유저별 채팅 레이트리밋 게이트(limit-goal-prompt.md RL-1~RL-4, RL-8, RL-11~RL-15, RL-20·RL-21).

`core/rate_limit.py`가 기구(고정 창 카운터)를, 이 모듈이 **정책**(누구를, 무엇을, 몇 번까지)을
맡는다(RL-14). 채팅 4경로 — 메시지 전송 · 재생성 · 편집 · 빌더 미리보기 — 가 `Depends`로 이
함수 하나를 공유한다(RL-1).

**단일 버킷이다(RL-3).** 세는 단위는 "LLM을 태우는 요청 1건"이라 재생성도 편집도 1로 센다 —
방의 `turn_count`는 재생성에서 늘지 않고 편집에서는 되감겼다가 다시 늘지만, 그 회계는 대화의
길이를 재는 것이고 여기서 재는 것은 우리가 지불하는 호출 수다. 두 숫자는 일부러 다르다.

**검사는 `Depends`로만 한다(RL-13).** 네 경로 전부 SSE(`EventSourceResponse`) 라우트라
제너레이터 본문에서 `HTTPException`을 던지면 이미 시작된 스트림을 뚫고 나가 커넥션이 깨지고,
최악에는 망가진 asyncpg 커넥션이 풀로 반환돼 무관한 요청이 500이 된다(`apps/api/CLAUDE.md`
§SSE 스트리밍). 그래서 라우트 시그니처의 `Depends` 자리에서만 429를 낸다.
"""

import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from redis.exceptions import RedisError

from api.core.rate_limit import KST, check_rate_limit, seconds_until_kst_midnight
from api.core.sentry import capture_dependency_failure
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

# RL-14: 정책값은 여기 모듈 상수다(env로 빼지 않는다 — 조정은 재배포 한 줄).
# ⚠️ 게이트 함수는 이 이름들을 **호출 시점에 모듈 전역으로** 읽는다. 기본 인자로 캡처하면
# 함수 정의 시점의 값이 박혀 `monkeypatch.setattr`가 통하지 않는다.
CHAT_BURST_LIMIT = 10
CHAT_BURST_WINDOW_SECONDS = 60
# 30은 **정책값이지 실측값이 아니다** — "하루 30턴이면 충분하다"는 관측이 아니라 쿼터를 지키기
# 위해 고른 수다. 실제 사용 분포가 나오면 그 숫자로 다시 정해야 한다.
CHAT_DAILY_LIMIT = 30

# RL-21: Redis 장애 보고는 창당 1회. 장애는 초당 수십 요청에 그대로 곱해져서, 요청마다 보고하면
# Bugsink 이벤트가 그 수만큼 쏟아진다.
# ⚠️ **1워커 전제다.** 이 타임스탬프는 프로세스 전역이라 워커를 늘리면 워커 수만큼 보고된다
# (현재 배포는 uvicorn 단일 워커 — `DEPLOY.md`). 워커를 늘릴 때 Redis 공유 키로 옮길 것.
REDIS_FAILURE_REPORT_WINDOW_SECONDS = 60

_BURST_SCOPE = "chat_burst"
_DAY_SCOPE = "chat_day"

_last_redis_failure_reported_at: float | None = None


def _report_redis_failure() -> None:
    global _last_redis_failure_reported_at
    now = time.monotonic()
    if (
        _last_redis_failure_reported_at is not None
        and now - _last_redis_failure_reported_at < REDIS_FAILURE_REPORT_WINDOW_SECONDS
    ):
        return
    _last_redis_failure_reported_at = now
    # RL-8: `user_id`를 넘기지 않는다 — `capture_dependency_failure`의 태그에는 리터럴
    # `dependency` 문자열 외에 아무것도 싣지 않는다(monitoring-techspec.md MT-6, PII 금지).
    capture_dependency_failure(dependency="redis")


def _too_many_requests(user_id: uuid.UUID, window: str, retry_after: int) -> HTTPException:
    # RL-12: 검색 가능한 고정 토큰 하나(`user_limit_exceeded`) + user_id·window·retry_after까지.
    # 이메일·프롬프트 본문 등 나머지는 절대 싣지 않는다. Bugsink 이벤트로는 승격하지 않는다 —
    # 상한에 걸리는 것은 설계된 동작이지 장애가 아니다.
    logger.warning(
        "user_limit_exceeded user_id=%s window=%s retry_after=%s", user_id, window, retry_after
    )
    # RL-11: `headers={"Retry-After": ...}`를 주지 않는다. 브라우저가 CORS 응답에서 읽을 수 있는
    # 헤더는 `Access-Control-Expose-Headers`에 실린 것뿐이라 프런트가 못 읽는다 — 값은 본문에
    # 담아 보낸다(RL-15의 `window`도 같은 이유로 본문 필드다).
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "USER_LIMIT", "retryAfterSeconds": retry_after, "window": window},
    )


async def enforce_chat_rate_limit(user_id: uuid.UUID = Depends(get_current_user_id)) -> None:
    """채팅 4경로 공용 게이트(RL-1). 키는 `user_id`다(RL-2) — IP가 아니라 계정이 비용의 단위다.

    `get_current_user_id`는 재동의 게이트(`require_legal_consent`)도 이미 `Depends`로 쓰고 있어
    FastAPI의 요청 스코프 캐시가 한 번만 해석한다 — Redis 왕복이 더 늘지 않는다.

    순서는 **버스트 → 일일**이다. 짧은 창이 먼저 걸리는 게 사용자에게 유용한 `retryAfterSeconds`
    (몇 초 뒤 재시도)를 주기 때문이고, 일일 창이 먼저면 몇 시간짜리 값이 앞서 나간다.
    """
    now = datetime.now(UTC)
    key = str(user_id)
    try:
        burst_retry_after = await check_rate_limit(
            _BURST_SCOPE, key, CHAT_BURST_LIMIT, window_seconds=CHAT_BURST_WINDOW_SECONDS
        )
        if burst_retry_after > 0:
            raise _too_many_requests(user_id, "minute", burst_retry_after)

        # S5(면제 판정)가 들어올 자리다 — 면제 대상은 버스트는 그대로 받고 일일만 건너뛴다.

        # RL-4: 일일 창은 KST 자정에 끊긴다. 기구에는 "자정"이라는 개념이 없으므로 호출자가
        # 키에 KST 날짜를 섞고(날짜가 바뀌면 키 자체가 바뀐다) TTL로 남은 초를 넘긴다 —
        # 둘 중 하나만 하면 어긋난다(날짜만 섞으면 어제 키가 TTL 없이 남고, TTL만 주면
        # 자정 직전 요청이 만든 창이 자정 직후 요청과 같은 키를 공유한다).
        day_retry_after = await check_rate_limit(
            _DAY_SCOPE,
            f"{key}:{now.astimezone(KST).date().isoformat()}",
            CHAT_DAILY_LIMIT,
            window_seconds=seconds_until_kst_midnight(now),
        )
        if day_retry_after > 0:
            raise _too_many_requests(user_id, "day", day_retry_after)
    except RedisError:
        # RL-8: fail-open. 상한을 세는 장치가 죽었다고 채팅까지 죽일 이유가 없다 —
        # 최악의 결과는 그 창 동안 상한이 느슨해지는 것이고, fail-closed의 최악은 전면 장애다.
        # ⚠️ 이 fail-open이 지키는 것은 **부분 장애**다(Redis는 살았는데 이 키에만 문제가 있는
        # 경우). Redis 전면 장애에서는 이 게이트에 닿기도 전에 `session/store.py`의
        # `get_session`이 `RedisError`를 그대로 올려 500이 난다 — `get_current_user_id`가
        # 세션 쿠키를 받으면 조건 없이 먼저 부르는 `redis_client.get`이다(같은 의존성의
        # `is_user_suspended`는 그보다 뒤라 전면 장애에서는 호출조차 되지 않는다).
        # "Redis가 죽어도 채팅은 산다"는 뜻이 아니다.
        logger.warning("채팅 레이트리밋 검사 실패 — fail-open으로 통과시킨다", exc_info=True)
        _report_redis_failure()
