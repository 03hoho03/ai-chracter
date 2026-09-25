"""유저별 채팅 레이트리밋 게이트.

`core/rate_limit.py`가 기구(고정 창 카운터)를, 이 모듈이 **정책**(누구를, 무엇을, 몇 번까지)을
맡는다. 채팅 4경로 — 메시지 전송 · 재생성 · 편집 · 빌더 미리보기 — 가 `Depends`로 이
함수 하나를 공유한다.

**단일 버킷이다.** 세는 단위는 "LLM을 태우는 요청 1건"이라 재생성도 편집도 1로 센다 —
방의 `turn_count`는 재생성에서 늘지 않고 편집에서는 되감겼다가 다시 늘지만, 그 회계는 대화의
길이를 재는 것이고 여기서 재는 것은 우리가 지불하는 호출 수다. 두 숫자는 일부러 다르다.

**검사는 `Depends`로만 한다.** 네 경로 전부 SSE(`EventSourceResponse`) 라우트라
제너레이터 본문에서 `HTTPException`을 던지면 이미 시작된 스트림을 뚫고 나가 커넥션이 깨지고,
최악에는 망가진 asyncpg 커넥션이 풀로 반환돼 무관한 요청이 500이 된다(`apps/api/CLAUDE.md`
§SSE 스트리밍). 그래서 라우트 시그니처의 `Depends` 자리에서만 429를 낸다.

**이미지 생성도 이 모듈이 맡는다.** 기구가 다르고(고정 창이
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
from typing import Literal, assert_never

from fastapi import Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
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
from api.db.session import get_db_session, get_session_factory
from api.images.schemas import GenerateImageRequest
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

# 정책값은 여기 모듈 상수다(env로 빼지 않는다 — 조정은 재배포 한 줄).
# ⚠️ 게이트 함수는 이 이름들을 **호출 시점에 모듈 전역으로** 읽는다. 기본 인자로 캡처하면
# 함수 정의 시점의 값이 박혀 `monkeypatch.setattr`가 통하지 않는다.
CHAT_BURST_LIMIT = 10
CHAT_BURST_WINDOW_SECONDS = 60
# 30은 **정책값이지 실측값이 아니다** — "하루 30턴이면 충분하다"는 관측이 아니라 쿼터를 지키기
# 위해 고른 수다. 실제 사용 분포가 나오면 그 숫자로 다시 정해야 한다.
CHAT_DAILY_LIMIT = 30

# 이미지는 고정 창이 아니라 토큰 버킷이다 — 10장을 모아 뒀다가 한 번에 쓰고
# 시간당 1장씩 연속 충전된다. **토큰 1개 = 이미지 1장**이라 `count=2` 요청은 2를 깎는다
# (비용은 요청 수가 아니라 장수에 붙는다 — 집 PC가 장당 한 번씩 돈다).
# 30과 마찬가지로 실측값이 아니라 정책값이다.
IMAGE_TOKEN_CAPACITY = 10
IMAGE_TOKEN_REFILL_SECONDS = 3600

# 큐가 찼을 때 주는 재시도 초. **큐 길이 추정이 아니라 잡 하나의 최대 소요**를 고정값
# 으로 준다 — `core/config.py`의 `local_image_queue_limit` 주석이 근거로 쓰는 그 60초(장당
# 약 30초 × `count` 상한 2)다. 앞선 대기자 수는 `local_image._queue_depth`가 정확히 들고
# 있다 — 모르는 것은 **각 잡의 잔여 시간**이라 그 깊이를 초로 환산할 수 없다. 그래서 잡
# 하나의 상한 60초를 고정값으로 답한다("최대 60초 뒤 다시").
# ⚠️ config에는 이 60이 **설정값이 아니라 주석으로만** 있어서 여기에 상수로 둔다
# (둘이 어긋나면 config 주석이 아니라 이 값이 응답에 나간다).
QUEUE_FULL_RETRY_AFTER_SECONDS = 60

# Redis 장애 보고는 창당 1회. 장애는 초당 수십 요청에 그대로 곱해져서, 요청마다 보고하면
# Bugsink 이벤트가 그 수만큼 쏟아진다.
# ⚠️ **1워커 전제다.** 이 타임스탬프는 프로세스 전역이라 워커를 늘리면 워커 수만큼 보고된다
# (현재 배포는 uvicorn 단일 워커 — `DEPLOY.md`). 워커를 늘릴 때 Redis 공유 키로 옮길 것.
REDIS_FAILURE_REPORT_WINDOW_SECONDS = 60

_BURST_SCOPE = "chat_burst"
_DAY_SCOPE = "chat_day"
_IMAGE_SCOPE = "image_tokens"
# 이미지 429 두 종류(`USER_LIMIT`·`QUEUE_FULL`)는 같은 `window`를 쓴다 — 둘을
# 가르는 것은 `code`고, `window`는 "어느 상한이냐"가 아니라 "어느 기능이냐"다(채팅은 창 길이가
# 곧 재시도 안내라 minute/day를 싣지만, 이미지는 그 역할을 `retryAfterSeconds`가 한다). auth도
# 같은 형태다 — `window:"auth"` 아래 시간당 상한은
# `code:"AUTH_LIMIT"`, 60초 쿨다운은 `code:"AUTH_COOLDOWN"`이다. 바디는 이 파일의
# `_too_many_requests`가 아니라 `auth/router.py`의 지역 헬퍼가 만든다(그 함수는
# `user_id` 필수라 인증 전인 auth에 안 맞는다).
_IMAGE_WINDOW = "image"

# 클로버 부족은 **새 `code`**다. `window`는 경로마다 다르다 — 채팅은
# 신규 `"clover"`, 이미지는 기존 `"image"`를 유지한다(위 주석의 규칙 그대로 — `window`는
# "어느 기능이냐"고 이미지에서 상한 종류를 가르는 축은 이미 `code`다).
_CLOVER_CODE = "CLOVER_REQUIRED"
_CLOVER_WINDOW = "clover"

# "소진 시 하루 1회 확인 **후** 자동
# 차감"의 *후*를 강제하는 코드다. `_CLOVER_CODE`와 같은 `window`를 쓰고 `code`로만 갈린다 —
# 둘은 같은 기능("클로버로 계속하기")의 서로 다른 단계이지 다른 기능이 아니다.
#
# 🔴 **판정이 BE에 있어야 하는 이유**: FE는 "이번 요청이 무료분을 넘는가"를 보내기 전에 알 수
# 없다(`GET /me/clover`는 잔액·확인여부·출석가능만 준다). 미확인인 모든 첫 요청에 모달을
# 띄우면 **무료분을 안 쓴 사용자까지 매일 붙잡는다.** 게이트만이 그 시점을 알고, 그래서 게이트가
# 단일 판정자다 — 경쟁 조건도 여기서 사라진다.
_CLOVER_CONFIRM_CODE = "CLOVER_CONFIRM_REQUIRED"

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
    # `user_id`를 넘기지 않는다 — `capture_dependency_failure`의 태그에는 리터럴
    # `dependency` 문자열 외에 아무것도 싣지 않는다(PII 금지).
    capture_dependency_failure(dependency="redis")


def _too_many_requests(
    user_id: uuid.UUID, window: str, retry_after: int, *, code: str = "USER_LIMIT"
) -> HTTPException:
    # 초과 로그: 검색 가능한 고정 토큰 하나(`user_limit_exceeded`) + code·user_id·window·retry_after
    # 까지. 이메일·프롬프트 본문 등 나머지는 절대 싣지 않는다(`code`는 이 모듈이 내는 리터럴
    # 4종 — `USER_LIMIT`/`QUEUE_FULL`/`CLOVER_REQUIRED`/`CLOVER_CONFIRM_REQUIRED` — 이라 PII가
    # 아니다. auth의 2종은 `auth/router.py`의 지역 헬퍼가 따로 만든다).
    # Bugsink 이벤트로는 승격하지 않는다 — 상한에 걸리는 것은 설계된 동작이지
    # 장애가 아니다. `code`가 없으면 이미지의 두 429(`USER_LIMIT`/`QUEUE_FULL`)가 같은
    # `window=image`로 찍혀 로그만으로는 갈리지 않는다(유저 쿼터냐 GPU 큐냐를 셀 수 없다).
    logger.warning(
        "user_limit_exceeded code=%s user_id=%s window=%s retry_after=%s",
        code,
        user_id,
        window,
        retry_after,
    )
    # `headers={"Retry-After": ...}`를 주지 않는다. 브라우저가 CORS 응답에서 읽을 수 있는
    # 헤더는 `Access-Control-Expose-Headers`에 실린 것뿐이라 프런트가 못 읽는다 — 값은 본문에
    # 담아 보낸다(`window`도 같은 이유로 본문 필드다).
    # `code`만 인자로 열려 있는 이유는 이미지 큐 거절(`QUEUE_FULL`)이 **같은 바디
    # 모양·같은 로그 토큰**을 써야 하기 때문이다 — 예전 큐 429는 detail이 평문 문자열이라
    # 클라이언트가 두 429를 구분할 수도, 재시도 시점을 알 수도 없었다.
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": code, "retryAfterSeconds": retry_after, "window": window},
    )


async def is_rate_limit_exempt(user_id: uuid.UUID, db: AsyncSession) -> bool:
    """예외 판정. 소스는 `users.rate_limit_exempt` 행 하나다 — Redis 미러도, 로그인 시점에
    세션에 굳는 사본도 없어서 무효화할 캐시가 없다(어드민이 뒤집으면 다음 요청부터 곧바로
    적용된다).

    **면제 범위는 일일 상한과 이미지 토큰버킷뿐이다.** 분당 버스트는 예외 계정도 그대로
    받고(폭주 방어는 쿼터가 아니다), 이미지 유저별 동시 큐 1칸도 예외 계정에 그대로 적용된다.
    이미지 쪽이 이 함수를 그대로 다시 부른다 — 그래서 게이트 본문이 아니라 별도
    함수다.

    `is True`로 판정한다. `db.get`은 persistent 행만 돌려주므로 `rate_limit_exempt`가 `None`인
    경우(flush 전 인스턴스)는 여기 도달하지 않지만, 그래도 `None`이 새면 "면제 아님"이 되게
    한다 — 그 자리에서 falsy는 "예외가 아니다"가 아니라 "아직 모른다"다.
    """
    user = await db.get(User, user_id)
    # 행이 없으면(세션은 살아 있는데 유저 행이 없는 경우) 면제가 아니다. 그 상태는
    # `get_current_user_id`가 이미 401로 끊으므로 여기까지
    # 오지 않지만, 판정 함수 혼자서도 안전한 쪽으로 떨어져야 한다.
    return user is not None and user.rate_limit_exempt is True


async def _needs_clover_spend_confirmation(
    user_id: uuid.UUID, db: AsyncSession, now: datetime, cost: int
) -> bool:
    """오늘(KST) 동의가 없고, **동의하면 실제로 쓸 수 있을 때만** True.

    `is_rate_limit_exempt`와 같은 행을 다시 `db.get`한다 — 같은 세션이어도 SELECT가 한 번 더
    나간다(identity map은 약참조라 앞 호출이 읽은 `User`는 이미 수거됐다).

    🔴 **잔액이 모자라면 묻지 않는다.** 0원인 사용자에게 *"지금부터 클로버를 써요"*를 물어 놓고
    동의 직후 *"부족해요"*를 내는 것은 두 단계를 헛되이 쓰는 것이다. 그 경우는 그대로 아래
    차감으로 떨어져 `CLOVER_REQUIRED`가 나간다.

    ⚠️ 여기 읽은 잔액은 **판정의 권한이 아니다** — 권한은 `spend`의 조건부 UPDATE에 있다.
    이 읽기가 고르는 것은 "어느 429를 낼 것인가" 하나뿐이고, 읽은 뒤 잔액이 줄어드는 경쟁이
    나도 차감이 실패해 `CLOVER_REQUIRED`로 떨어지므로 틀린 결과가 나오지 않는다.

    🔴 날짜 판정을 `is not None`("한 번이라도 확인했으면 끝")으로 쓰면 **하루 1회가 평생 1회**가
    되어 이튿날부터 무단 차감이 된다. 비교는 `core/clover.py`의 순수 함수에 맡긴다 — 시간을
    얼리지 않고 `now`를 인자로 받는 것이 이 저장소의 유일한 KST 테스트 선례다(freezegun 0건).

    행이 없으면 묻지 않는다 — 그 상태는 `get_current_user_id`가 이미 401로 끊는다.
    """
    user = await db.get(User, user_id)
    if user is None or clover.is_same_kst_day(user.clover_spend_confirmed_on, now):
        return False
    return user.clover_balance >= cost


@dataclass(frozen=True)
class ChatCharge:
    """채팅 게이트가 라우트에 넘기는 **차감 영수증**.

    `source`가 환불 대상을 가른다:
    - `"free"` — 일일 창 안에서 통과. 환불할 것이 없다(`check_rate_limit`에 역연산이 없어
      무료분은 애초에 되돌릴 수 없다).
    - `"clover"` — 클로버를 깎았다. 실패 시 `clover_amount`만큼 되돌린다.
    - `"skipped"` — 예외 계정 또는 Redis fail-open. 아무것도 깎지 않았다.
    """

    source: Literal["free", "clover", "skipped"]
    # `source != "clover"`이면 0이다. 되돌릴 양을 라우트가 상수에서 다시 계산하지 않고
    # 영수증에서 읽게 한다 — 상수가 바뀌어도 진행 중이던 요청의 환불액이 어긋나지 않는다.
    clover_amount: int = 0


async def enforce_chat_rate_limit(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> ChatCharge:
    """채팅 4경로 공용 게이트. 키는 `user_id`다 — IP가 아니라 계정이 비용의 단위다.

    `get_current_user_id`는 재동의 게이트(`require_legal_consent`)도 이미 `Depends`로 쓰고 있어
    FastAPI의 요청 스코프 캐시가 한 번만 해석한다 — Redis 왕복이 더 늘지 않는다.

    `db`도 같은 요청 스코프 캐시로 받는다 — 전송·재생성·편집 3경로에서는 라우트 본문·
    `require_legal_consent`와 같은 세션이다. 미리보기 경로만은 라우트 본문이 세션을 받지 않아
    (`_preview_prompt_set_dependency`가 풀 상한 때문에 `Depends(get_db_session)`을 피한다)
    `get_current_user_id`·재동의 게이트·이 게이트만 그 세션을 쓴다 — 의존성 캐시라 커넥션이
    더 열리지는 않는다. ⚠️ 같은 세션이어도 `is_rate_limit_exempt`의 `db.get(User, user_id)`는
    identity map 히트가 **아니다** — 앞 의존성들이 읽은 `User`는 아무도 붙잡지 않아 이미
    수거됐으므로(약참조) SELECT가 따로 나간다.

    순서는 **버스트 → 면제 → 일일 → 클로버**다. 짧은
    창이 먼저 걸리는 게 사용자에게 유용한 `retryAfterSeconds`(몇 초 뒤 재시도)를 주기 때문이고,
    일일 창이 먼저면 몇 시간짜리 값이 앞서 나간다. 면제가 그 사이에 있는 이유는 면제 대상도
    버스트는 받기 때문이다. 클로버가 맨 뒤인 이유는 두 가지다 — 분당 버스트는 **폭주 방어라
    돈으로 끌 수 없고**, 예외 계정은 애초에 차감 대상이 아니다.
    """
    now = datetime.now(UTC)
    key = str(user_id)
    try:
        burst_retry_after = await check_rate_limit(
            _BURST_SCOPE, key, CHAT_BURST_LIMIT, window_seconds=CHAT_BURST_WINDOW_SECONDS
        )
        if burst_retry_after > 0:
            raise _too_many_requests(user_id, "minute", burst_retry_after)

        # 면제 대상은 버스트를 그대로 받고 일일만 건너뛴다. 건너뛰는 것이라 일일
        # 카운터도 올라가지 않는다 — 어드민이 도중에 면제를 거두면 그날 그때까지의 요청은
        # 일일 창에 세어져 있지 않다.
        if await is_rate_limit_exempt(user_id, db):
            return ChatCharge(source="skipped")

        # 일일 창은 KST 자정에 끊긴다. 기구에는 "자정"이라는 개념이 없으므로 호출자가
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
            # 무료 일일분을 다 쓴
            # 뒤에만 클로버가 대신 낸다.
            #
            # 🔴 **이 분기는 반드시 `try` 블록 안에 있어야 한다.** Redis 장애에서는
            # `check_rate_limit`이 `RedisError`를 던져 아래 `except`로 빠지므로 여기 도달하지
            # 않는다 — 의도한 동작이다(장애 중에는 무료로 통과시킨다). `try`
            # 바깥(함수 끝)으로 옮기면 fail-open으로 빠져나온 뒤에도 실행돼 **장애 동안
            # 전원이 차감된다.** 코드만 보면 어느 쪽도 자연스러워 보여서 이 주석을 남긴다.
            #
            # **차감보다 먼저** 오늘치 동의를 확인한다. 이 순서가
            # 뒤집히면 "확인 후 자동 차감"이 "차감 후 확인"이 되어 결정 자체가 무의미해진다.
            #
            # 🔴 이 검사는 **일일 분기 안**이다. 밖으로 옮기면 무료분이 남은 사용자까지 429를
            # 받는다 — "소진 시 하루 1회 확인"의 "소진 시"가 지켜지지 않는다. 그리고 면제 `return`(위)보다 뒤라
            # 예외 계정에게는 묻지 않는다.
            if await _needs_clover_spend_confirmation(
                user_id, db, now, clover.CHAT_TURN_COST
            ):
                # `retryAfterSeconds`는 부족(`CLOVER_REQUIRED`)과 같은 자정까지 초다 — 동의를
                # 안 하고 기다리기만 해도 그때 무료 일일분이 돌아오므로 여전히 참값이다.
                raise _too_many_requests(
                    user_id,
                    _CLOVER_WINDOW,
                    seconds_until_kst_midnight(now),
                    code=_CLOVER_CONFIRM_CODE,
                )

            # 차감은 **자기 트랜잭션**이다 — 채팅 4경로의 커밋 시점이 제각각이라
            # 요청 세션에 얹으면 미리보기는 영원히 공짜가 된다.
            spent = await clover.spend_in_new_transaction(
                session_factory,
                user_id=user_id,
                amount=clover.CHAT_TURN_COST,
                kind="chat_spend",
            )
            if spent is None:
                # 클로버 부족 429(채팅): 자정까지 남은 초는 거짓이 아니다 — 그때 무료 일일분이
                # 돌아오므로 실제로 다시 보낼 수 있다.
                raise _too_many_requests(
                    user_id,
                    _CLOVER_WINDOW,
                    seconds_until_kst_midnight(now),
                    code=_CLOVER_CODE,
                )
            return ChatCharge(source="clover", clover_amount=clover.CHAT_TURN_COST)
        return ChatCharge(source="free")
    except RedisError:
        # fail-open. 상한을 세는 장치가 죽었다고 채팅까지 죽일 이유가 없다 —
        # 최악의 결과는 그 창 동안 상한이 느슨해지는 것이고, fail-closed의 최악은 전면 장애다.
        # ⚠️ 이 fail-open이 지키는 것은 **부분 장애**다(Redis는 살았는데 이 키에만 문제가 있는
        # 경우). Redis 전면 장애에서는 이 게이트에 닿기도 전에 `session/store.py`의
        # `get_session`이 `RedisError`를 그대로 올려 500이 난다 — `get_current_user_id`가
        # 세션 쿠키를 받으면 조건 없이 먼저 부르는 `redis_client.get`이다(같은 의존성의
        # `is_user_suspended`는 그보다 뒤라 전면 장애에서는 호출조차 되지 않는다).
        # "Redis가 죽어도 채팅은 산다"는 뜻이 아니다.
        logger.warning("채팅 레이트리밋 검사 실패 — fail-open으로 통과시킨다", exc_info=True)
        _report_redis_failure()
        # 차감이 없었으므로 환불 대상도 아니다 — 이미지 쪽 `:279`와 같은 결론이다.
        return ChatCharge(source="skipped")


@dataclass(frozen=True)
class ImageCharge:
    """`enforce_image_rate_limit`이 라우트에 넘기는 **차감 영수증**.

    `source="skipped"`는 "차감이 일어나지 않았다"는 뜻이다(예외 계정 또는 Redis
    fail-open). 환불이 이 값을 봐야 하는 이유가 여기 있다 — `refund_tokens`는 차감 여부를
    모른 채 무조건 용량 천장까지 올리므로, 차감하지 않은 요청을 환불하면 면제 계정이 요청을
    보낼 때마다 그 사용자의 버킷이 만땅으로 리셋된다(면제를 거둔 직후가 특히 그렇다).

    🔴 **`charged: bool`을 `source`로 바꿨다**. 불리언 하나로는
    "토큰이냐 클로버냐"를 못 가려 환불이 **엉뚱한 자원을 돌려놓는다** — 클로버로 낸 요청을
    `refund_tokens`로 되돌리면 안 깎은 토큰이 늘고 깎인 클로버는 그대로 사라진다."""

    count: int
    source: Literal["token", "clover", "skipped"]
    # `source != "clover"`이면 0. 채팅의 `ChatCharge`와 같은 이유로 영수증에 담는다.
    clover_amount: int = 0


async def enforce_image_rate_limit(
    payload: GenerateImageRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> ImageCharge:
    """`POST /images/generate` 게이트. 반환값이 라우트의 환불 근거가 된다.

    **라우트와 같은 바디 모델을 같은 이름으로 선언한다.** 그래야 FastAPI가 같은 JSON을 한 번
    파싱해 게이트와 라우트가 각각 검증한다 — 같은 값이지만 서로 **다른 인스턴스**다(202 요청
    하나당 `GenerateImageRequest` 검증 2회, 실측). 같은 객체가 아니므로 한쪽에서 바디를
    고쳐 다른 쪽에 넘기는 식의 배선은 성립하지 않는다(`chat/router.py`의 `_validate_shortcut`
    선례, `apps/api/CLAUDE.md` §SSE). 게이트가 바디를 봐야 하는 이유는 차감량이 요청 수가
    아니라 **장수**(`count`)이기 때문이다.

    검사를 라우트 본문이 아니라 `Depends`에 두는 이유는 채팅과 **같지 않다** — 이
    라우트는 SSE 제너레이터가 아니라 본문에서 raise해도 스트림이 깨지지 않는다. 여기서
    `Depends`를 쓰는 이유는 둘이다: ① 잡 생성·가용성 확인 등 라우트 본문의 다른 검증보다
    반드시 먼저 끊긴다(그래서 토큰이 없는 요청은 큐 칸도 건드리지 않는다), ② 채팅 게이트와
    같은 자리에 있어야 "레이트리밋은 시그니처에서 본다"는 규칙이 경로마다 달라지지 않는다.

    순서는 **면제 → 토큰**이다. 면제 계정은 토큰 버킷만 건너뛰고 큐(전역·유저별
    1칸)는 그대로 받는다 — 큐는 쿼터가 아니라 GPU 직렬 처리량의 분배라서 면제 대상에게
    열어 줄 이유가 없다. 큐 판정은 라우트 본문의 `try_admit`이 계속 맡는다(검사+증가가 한
    동기 블록이어야 하는 불변식이 그쪽(`local_image.try_admit`)에 있다).
    """
    try:
        if await is_rate_limit_exempt(user_id, db):
            return ImageCharge(count=payload.count, source="skipped")

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
        # 채팅과 같은 fail-open이고 같은 이유다 — 상한을 세는 장치가 죽었다고 기능까지
        # 죽일 이유가 없다. 여기서 통과시킨 요청은 차감이 없었으므로 환불 대상도 아니다.
        logger.warning("이미지 레이트리밋 검사 실패 — fail-open으로 통과시킨다", exc_info=True)
        _report_redis_failure()
        return ImageCharge(count=payload.count, source="skipped")

    if retry_after > 0:
        # 🔴 여기는 채팅과 달리 `try` **바깥**인데도 "Redis 장애 중에는 클로버를 깎지 않는다"가 지켜진다 —
        # Redis 장애는 위 `except`가 `return`으로 함수를 끝내므로 이 줄에 **도달하지 못한다.**
        # 채팅의 "반드시 `try` 안" 규칙을 기계적으로 옮기면 안 된다. 판정 기준은 "`try` 안이냐"가
        # 아니라 **"fail-open 경로가 이 줄에 도달할 수 있느냐"**다.
        # 채팅과 같은 이유로 차감보다 먼저 오늘치 동의를 본다.
        # 확인 상태는 `users` 컬럼 하나라 **채팅과 이미지가 같은 동의를 공유한다**(하루 한 번
        # 묻는다는 결정이 기능마다 따로 물으면 하루 두 번이 된다).
        # `retryAfterSeconds`는 `take_tokens`가 준 값 그대로다 — 🔴 자정까지 초를 쓰면 이미지는
        # 시간당 충전이라 최대 24시간짜리 거짓이 된다(아래 클로버 부족 429와 같은 이유).
        clover_amount = payload.count * clover.IMAGE_UNIT_COST
        if await _needs_clover_spend_confirmation(
            user_id, db, datetime.now(UTC), clover_amount
        ):
            raise _too_many_requests(
                user_id, _IMAGE_WINDOW, retry_after, code=_CLOVER_CONFIRM_CODE
            )

        spent = await clover.spend_in_new_transaction(
            session_factory, user_id=user_id, amount=clover_amount, kind="image_spend"
        )
        if spent is None:
            # 클로버 부족 429(이미지): `window`는 `"image"`를 유지하고 `retryAfterSeconds`는 방금
            # `take_tokens`가 준 값을 그대로 쓴다. 🔴 자정까지 초를 쓰면 **최대 24시간짜리
            # 거짓값**이다 — 이미지 무료분은 시간당 충전이지 자정 리셋이 아니다.
            raise _too_many_requests(
                user_id, _IMAGE_WINDOW, retry_after, code=_CLOVER_CODE
            )
        return ImageCharge(count=payload.count, source="clover", clover_amount=clover_amount)
    return ImageCharge(count=payload.count, source="token")


def image_queue_full(user_id: uuid.UUID) -> HTTPException:
    """큐(전역·유저별) 거절 429. 유저 상한 429와 바디 모양이 같고 `code`로만 갈린다."""
    return _too_many_requests(
        user_id, _IMAGE_WINDOW, QUEUE_FULL_RETRY_AFTER_SECONDS, code="QUEUE_FULL"
    )


async def refund_image_charge(
    user_id: uuid.UUID,
    charge: ImageCharge,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """토큰은 잡이 실제로 생성(202)될 때만 소모된다 — 차감 이후 202 이전에 끝난 요청의
    차감을 돌려놓는다. 차감이 없었으면(`source="skipped"`) 아무 일도 하지 않는다.

    🔴 **무엇으로 냈는지에 따라 돌려놓는 자원이 다르다**. `assert_never`로
    망라성을 강제하므로 새 `source`가 생기면 mypy가 여기를 잡는다(`images/router.py`의
    `assert_never(result.outcome)` 관례).

    `RedisError`를 여기서 삼키는 이유: 이 함수는 **이미 실패가 확정된 요청**(429/503/400)의
    정리 작업이라, 예외가 새어 나가면 사용자가 받아야 할 429가 원인과 무관한 500으로 바뀐다.
    환불 유실 자체는 조용히 사라지지 않는다 — `refund_tokens`도 여기도 로그를 남긴다.
    클로버 환불도 같은 이유로 예외를 삼킨다(`clover.refund_in_new_transaction`이 자체적으로)."""
    match charge.source:
        case "skipped":
            return
        case "clover":
            await clover.refund_in_new_transaction(
                session_factory,
                user_id=user_id,
                amount=charge.clover_amount,
                kind="image_refund",
            )
        case "token":
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
        case _:
            assert_never(charge.source)
