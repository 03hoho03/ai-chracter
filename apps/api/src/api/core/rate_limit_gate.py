"""유저별 채팅 레이트리밋 게이트(limit-goal-prompt.md RL-1~RL-4, RL-8~RL-10, RL-11~RL-15, RL-20·RL-21).

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

**이미지 생성(S6, RL-5/RL-11/RL-16/RL-18)도 이 모듈이 맡는다.** 기구가 다르고(고정 창이
아니라 토큰 버킷) 세는 단위도 다르지만(요청 1건이 아니라 이미지 장수), 정책이 한 모듈에
모여 있어야 예외 계정 판정(`is_rate_limit_exempt`)과 Redis fail-open(`_report_redis_failure`)
을 채팅과 **같은 구현**으로 공유한다 — 사본이 두 벌이 되면 한쪽만 고쳐진다. 그래서
`api.images.schemas`를 이 모듈이 import한다(반대 방향은 없다 — `images/router.py`가 이
게이트를 부르지만 이 모듈은 라우터를 모른다).
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.rate_limit import (
    KST,
    check_rate_limit,
    refund_tokens,
    seconds_until_kst_midnight,
    take_tokens,
)
from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.session import get_db_session
from api.images.schemas import GenerateImageRequest
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

# RL-5(S6): 이미지는 고정 창이 아니라 토큰 버킷이다 — 10장을 모아 뒀다가 한 번에 쓰고
# 시간당 1장씩 연속 충전된다. **토큰 1개 = 이미지 1장**이라 `count=2` 요청은 2를 깎는다
# (비용은 요청 수가 아니라 장수에 붙는다 — 집 PC가 장당 한 번씩 돈다, LG-6).
# 30과 마찬가지로 실측값이 아니라 정책값이다.
IMAGE_TOKEN_CAPACITY = 10
IMAGE_TOKEN_REFILL_SECONDS = 3600

# RL-11: 큐가 찼을 때 주는 재시도 초. **큐 길이 추정이 아니라 잡 하나의 최대 소요**를 고정값
# 으로 준다 — `core/config.py`의 `local_image_queue_limit` 주석이 근거로 쓰는 그 60초(장당
# 약 30초 × `count` 상한 2)다. 앞선 대기자 수는 `local_image._queue_depth`가 정확히 들고
# 있다 — 모르는 것은 **각 잡의 잔여 시간**이라 그 깊이를 초로 환산할 수 없다. 그래서 잡
# 하나의 상한 60초를 고정값으로 답한다("최대 60초 뒤 다시").
# ⚠️ config에는 이 60이 **설정값이 아니라 주석으로만** 있어서 여기에 상수로 둔다
# (둘이 어긋나면 config 주석이 아니라 이 값이 응답에 나간다).
QUEUE_FULL_RETRY_AFTER_SECONDS = 60

# RL-21: Redis 장애 보고는 창당 1회. 장애는 초당 수십 요청에 그대로 곱해져서, 요청마다 보고하면
# Bugsink 이벤트가 그 수만큼 쏟아진다.
# ⚠️ **1워커 전제다.** 이 타임스탬프는 프로세스 전역이라 워커를 늘리면 워커 수만큼 보고된다
# (현재 배포는 uvicorn 단일 워커 — `DEPLOY.md`). 워커를 늘릴 때 Redis 공유 키로 옮길 것.
REDIS_FAILURE_REPORT_WINDOW_SECONDS = 60

_BURST_SCOPE = "chat_burst"
_DAY_SCOPE = "chat_day"
_IMAGE_SCOPE = "image_tokens"
# RL-11/RL-12: 이미지 429 두 종류(`USER_LIMIT`·`QUEUE_FULL`)는 같은 `window`를 쓴다 — 둘을
# 가르는 것은 `code`고, `window`는 "어느 상한이냐"가 아니라 "어느 기능이냐"다(채팅은 창 길이가
# 곧 재시도 안내라 minute/day를 싣지만, 이미지는 그 역할을 `retryAfterSeconds`가 한다).
_IMAGE_WINDOW = "image"

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


def _too_many_requests(
    user_id: uuid.UUID, window: str, retry_after: int, *, code: str = "USER_LIMIT"
) -> HTTPException:
    # RL-12: 검색 가능한 고정 토큰 하나(`user_limit_exceeded`) + code·user_id·window·retry_after
    # 까지. 이메일·프롬프트 본문 등 나머지는 절대 싣지 않는다(`code`는 리터럴 2종이라 PII가
    # 아니다). Bugsink 이벤트로는 승격하지 않는다 — 상한에 걸리는 것은 설계된 동작이지
    # 장애가 아니다. `code`가 없으면 이미지의 두 429(`USER_LIMIT`/`QUEUE_FULL`)가 같은
    # `window=image`로 찍혀 로그만으로는 갈리지 않는다(유저 쿼터냐 GPU 큐냐를 셀 수 없다).
    logger.warning(
        "user_limit_exceeded code=%s user_id=%s window=%s retry_after=%s",
        code,
        user_id,
        window,
        retry_after,
    )
    # RL-11: `headers={"Retry-After": ...}`를 주지 않는다. 브라우저가 CORS 응답에서 읽을 수 있는
    # 헤더는 `Access-Control-Expose-Headers`에 실린 것뿐이라 프런트가 못 읽는다 — 값은 본문에
    # 담아 보낸다(RL-15의 `window`도 같은 이유로 본문 필드다).
    # RL-11(S6): `code`만 인자로 열려 있는 이유는 이미지 큐 거절(`QUEUE_FULL`)이 **같은 바디
    # 모양·같은 로그 토큰**을 써야 하기 때문이다 — 예전 큐 429는 detail이 평문 문자열이라
    # 클라이언트가 두 429를 구분할 수도, 재시도 시점을 알 수도 없었다.
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": code, "retryAfterSeconds": retry_after, "window": window},
    )


async def is_rate_limit_exempt(user_id: uuid.UUID, db: AsyncSession) -> bool:
    """예외 판정(RL-9). 소스는 `users.rate_limit_exempt` 행 하나다 — Redis 미러도, 로그인 시점에
    세션에 굳는 사본도 없어서 무효화할 캐시가 없다(어드민이 뒤집으면 다음 요청부터 곧바로
    적용된다 — S7).

    **면제 범위는 일일 상한과 이미지 토큰버킷뿐이다(RL-10).** 분당 버스트는 예외 계정도 그대로
    받고(폭주 방어는 쿼터가 아니다), 이미지 유저별 동시 큐 1칸도 예외 계정에 그대로 적용된다
    (RL-18). 이미지 쪽(S6)이 이 함수를 그대로 다시 부른다 — 그래서 게이트 본문이 아니라 별도
    함수다.

    `is True`로 판정한다. `db.get`은 persistent 행만 돌려주므로 `rate_limit_exempt`가 `None`인
    경우(flush 전 인스턴스)는 여기 도달하지 않지만, 그래도 `None`이 새면 "면제 아님"이 되게
    한다 — 그 자리에서 falsy는 "예외가 아니다"가 아니라 "아직 모른다"다.
    """
    user = await db.get(User, user_id)
    # 행이 없으면(세션은 살아 있는데 유저 행이 없는 경우) 면제가 아니다. 이 게이트가 붙은 네
    # 경로는 모두 바로 앞 `require_legal_consent`가 그 상태에 이미 401을 내므로 여기까지 오지
    # 않지만, 판정 함수 혼자서도 안전한 쪽으로 떨어져야 한다.
    return user is not None and user.rate_limit_exempt is True


async def enforce_chat_rate_limit(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """채팅 4경로 공용 게이트(RL-1). 키는 `user_id`다(RL-2) — IP가 아니라 계정이 비용의 단위다.

    `get_current_user_id`는 재동의 게이트(`require_legal_consent`)도 이미 `Depends`로 쓰고 있어
    FastAPI의 요청 스코프 캐시가 한 번만 해석한다 — Redis 왕복이 더 늘지 않는다.

    `db`도 같은 요청 스코프 캐시로 받는다 — 전송·재생성·편집 3경로에서는 라우트 본문·
    `require_legal_consent`와 같은 세션이다. 미리보기 경로만은 라우트 본문이 세션을 받지 않아
    (`_preview_prompt_set_dependency`가 풀 상한 때문에 `Depends(get_db_session)`을 피한다)
    재동의 게이트와 이 게이트만 그 세션을 쓴다 — 의존성 캐시라 커넥션이 더 열리지는 않는다.
    ⚠️ 지금 이 게이트가 붙은 경로들에서는 바로 앞 `require_legal_consent`가 같은 세션으로
    `db.get(User, user_id)`를 이미 했으므로 `is_rate_limit_exempt`의 조회가 identity map
    히트다 — **그 경로 집합에 한정된 사실**이고, 재동의 게이트가 없는 경로에 이 게이트를 붙이면
    SELECT가 하나 는다.

    순서는 **버스트 → 면제 → 일일**이다(RL-10). 짧은 창이 먼저 걸리는 게 사용자에게 유용한
    `retryAfterSeconds`(몇 초 뒤 재시도)를 주기 때문이고, 일일 창이 먼저면 몇 시간짜리 값이
    앞서 나간다. 면제가 그 사이에 있는 이유는 면제 대상도 버스트는 받기 때문이다.
    """
    now = datetime.now(UTC)
    key = str(user_id)
    try:
        burst_retry_after = await check_rate_limit(
            _BURST_SCOPE, key, CHAT_BURST_LIMIT, window_seconds=CHAT_BURST_WINDOW_SECONDS
        )
        if burst_retry_after > 0:
            raise _too_many_requests(user_id, "minute", burst_retry_after)

        # RL-10: 면제 대상은 버스트를 그대로 받고 일일만 건너뛴다. 건너뛰는 것이라 일일
        # 카운터도 올라가지 않는다 — 어드민이 도중에 면제를 거두면(S7) 그날 그때까지의 요청은
        # 일일 창에 세어져 있지 않다.
        if await is_rate_limit_exempt(user_id, db):
            return

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


@dataclass(frozen=True)
class ImageCharge:
    """`enforce_image_rate_limit`이 라우트에 넘기는 **차감 영수증**(RL-13/RL-16).

    `charged=False`는 "차감이 일어나지 않았다"는 뜻이다(예외 계정 RL-10, Redis fail-open
    RL-8). 환불이 이 플래그를 봐야 하는 이유가 여기 있다 — `refund_tokens`는 차감 여부를
    모른 채 무조건 용량 천장까지 올리므로, 차감하지 않은 요청을 환불하면 면제 계정이 요청을
    보낼 때마다 그 사용자의 버킷이 만땅으로 리셋된다(면제를 거둔 직후가 특히 그렇다)."""

    count: int
    charged: bool


async def enforce_image_rate_limit(
    payload: GenerateImageRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ImageCharge:
    """`POST /images/generate` 게이트(RL-5/RL-13). 반환값이 라우트의 환불 근거가 된다.

    **라우트와 같은 바디 모델을 같은 이름으로 선언한다.** 그래야 FastAPI가 같은 JSON을 한 번
    파싱해 게이트와 라우트가 각각 검증한다 — 같은 값이지만 서로 **다른 인스턴스**다(202 요청
    하나당 `GenerateImageRequest` 검증 2회, 실측). 같은 객체가 아니므로 한쪽에서 바디를
    고쳐 다른 쪽에 넘기는 식의 배선은 성립하지 않는다(`chat/router.py`의 `_validate_shortcut`
    선례, `apps/api/CLAUDE.md` §SSE). 게이트가 바디를 봐야 하는 이유는 차감량이 요청 수가
    아니라 **장수**(`count`)이기 때문이다.

    검사를 라우트 본문이 아니라 `Depends`에 두는 이유는 채팅(RL-13)과 **같지 않다** — 이
    라우트는 SSE 제너레이터가 아니라 본문에서 raise해도 스트림이 깨지지 않는다. 여기서
    `Depends`를 쓰는 이유는 둘이다: ① 잡 생성·가용성 확인 등 라우트 본문의 다른 검증보다
    반드시 먼저 끊긴다(그래서 토큰이 없는 요청은 큐 칸도 건드리지 않는다), ② 채팅 게이트와
    같은 자리에 있어야 "레이트리밋은 시그니처에서 본다"는 규칙이 경로마다 달라지지 않는다.

    순서는 **면제 → 토큰**이다(RL-10/RL-18). 면제 계정은 토큰 버킷만 건너뛰고 큐(전역·유저별
    1칸)는 그대로 받는다 — 큐는 쿼터가 아니라 GPU 직렬 처리량(LG-6)의 분배라서 면제 대상에게
    열어 줄 이유가 없다. 큐 판정은 라우트 본문의 `try_admit`이 계속 맡는다(검사+증가가 한
    동기 블록이어야 하는 P2-R 불변식이 그쪽에 있다).
    """
    try:
        if await is_rate_limit_exempt(user_id, db):
            return ImageCharge(count=payload.count, charged=False)

        retry_after = await take_tokens(
            redis_client,
            _IMAGE_SCOPE,
            str(user_id),
            payload.count,
            capacity=IMAGE_TOKEN_CAPACITY,
            refill_seconds=IMAGE_TOKEN_REFILL_SECONDS,
            # `now`는 주입값이다(`take_tokens` docstring) — 단조 증가하는 epoch 초라야
            # 충전 계산이 맞는다. `time.monotonic()`은 프로세스 기준점이 매번 달라져
            # Redis에 저장된 `updated_at`과 비교할 수 없다.
            now=time.time(),
        )
    except RedisError:
        # RL-8: 채팅과 같은 fail-open이고 같은 이유다 — 상한을 세는 장치가 죽었다고 기능까지
        # 죽일 이유가 없다. 여기서 통과시킨 요청은 차감이 없었으므로 환불 대상도 아니다.
        logger.warning("이미지 레이트리밋 검사 실패 — fail-open으로 통과시킨다", exc_info=True)
        _report_redis_failure()
        return ImageCharge(count=payload.count, charged=False)

    if retry_after > 0:
        raise _too_many_requests(user_id, _IMAGE_WINDOW, retry_after)
    return ImageCharge(count=payload.count, charged=True)


def image_queue_full(user_id: uuid.UUID) -> HTTPException:
    """큐(전역·유저별) 거절 429(RL-11). 유저 상한 429와 바디 모양이 같고 `code`로만 갈린다."""
    return _too_many_requests(
        user_id, _IMAGE_WINDOW, QUEUE_FULL_RETRY_AFTER_SECONDS, code="QUEUE_FULL"
    )


async def refund_image_charge(user_id: uuid.UUID, charge: ImageCharge) -> None:
    """RL-16: 토큰은 잡이 실제로 생성(202)될 때만 소모된다 — 차감 이후 202 이전에 끝난 요청의
    토큰을 돌려놓는다. 차감이 없었으면(`charged=False`) 아무 일도 하지 않는다.

    `RedisError`를 여기서 삼키는 이유: 이 함수는 **이미 실패가 확정된 요청**(429/503/400)의
    정리 작업이라, 예외가 새어 나가면 사용자가 받아야 할 429가 원인과 무관한 500으로 바뀐다.
    환불 유실 자체는 조용히 사라지지 않는다 — `refund_tokens`도 여기도 로그를 남긴다."""
    if not charge.charged:
        return
    try:
        await refund_tokens(
            redis_client,
            _IMAGE_SCOPE,
            str(user_id),
            charge.count,
            capacity=IMAGE_TOKEN_CAPACITY,
            refill_seconds=IMAGE_TOKEN_REFILL_SECONDS,
            now=time.time(),
        )
    except RedisError:
        logger.warning("이미지 토큰 환불 실패 — 그 요청의 차감이 남는다", exc_info=True)
        _report_redis_failure()
