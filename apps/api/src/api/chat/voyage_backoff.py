"""Voyage 임베딩 호출의 연속 실패 백오프 — 방과 무관한 Redis 키 하나로 연속 실패를 세고, 쌓이면 정한 시각까지 부르지 않는다.

Voyage 가 내려가거나 키가 거부되면 모든 방의 모든 턴이 같은 실패를 되풀이한다. 질의 임베딩은 생성 앞에서 기다리므로 실패할 때마다
첫 글자 지연이 늘고, 실패마다 경고·Bugsink 승격이 쌓인다. 장애는 방이 아니라 Voyage 쪽 사정이라 카운터도 방마다가 아니라 하나다.

- 질의 임베딩(`chat/turn_prompt.py`·`chat/memory_vector.py`)과 기억 임베딩 채우기(`chat/memory_embeddings.py`)가 같은 카운터를
  함께 쓴다. 둘 다 부르기 전에 `voyage_allowed` 로 묻고, Voyage 호출이 실패하면 `record_voyage_failure`, 성공하면
  `clear_voyage_backoff` 를 부른다. Voyage 가 답한 뒤 우리 쪽(DB)에서 난 실패는 세지 않는다.
- 질의 임베딩의 시간 초과는 실패로 세지 않는다 — 우리 상한(1초)이 짧아 느리지만 살아 있는 Voyage 를 세면 채우기까지 멈춘다.
  질의 임베딩은 5xx·429·연결 실패에도 다시 보내지 않으므로 그런 장애는 상한 안에 실패로 끝나 센다. 다시 보내려 첫 재시도
  대기(1초)를 기다리면 그동안 상한이 다 차 시간 초과로 분류되고, 장애 중에도 수가 오르지 않는다(`chat/memory_vector.py`).
- 건너뛴 질의 임베딩은 임베딩 회상이 꺼진 턴과 같다(명사 단독 회상, 턴 기록에 호출 칸 없음).
- Redis 를 못 읽거나 못 쓰면 백오프 없이 지금처럼 부른다 — 막아서 잃는 것은 회상 품질이고, 불러서 잃는 것은 호출 원가뿐이다.

상태는 해시 하나(`failures` 연속 실패 수, `failed_at` 마지막 실패의 유닉스 시각)다. 실패 하나를 적는 일은 두 칸 갱신을 한
트랜잭션으로 보내는 것뿐이라 동시에 실패한 두 요청이 서로의 갱신을 잃지 않는다. 다시 부를 수 있는 시각은 읽을 때
`failed_at + backoff_seconds(failures)` 로 계산한다. TTL 이 있어 잊힌 상태가 남지 않는다."""

import logging
import time

from redis.exceptions import RedisError

# 상태를 읽고 쓰는 곳. 테스트가 이 이름을 갈아 끼워 Redis 장애를 흉내 낸다.
from api.core.redis import redis_client

logger = logging.getLogger(__name__)

# 연속 실패가 이만큼 쌓이면 멈춘다. 채우기의 실패는 클라이언트가 이미 시간 초과·연결 실패·429·5xx 를 몇 번 다시 보낸 뒤의
# 실패이고, 질의 임베딩의 실패는 다시 보내지 않은 요청 하나의 실패다. 어느 쪽이든 한두 번은 배포·네트워크의 순간 끊김일 수
# 있어 세 번째에 멈춘다.
BACKOFF_AFTER_FAILURES = 3
# 처음 멈추는 시간(초). 한 방의 턴 간격이 수십 초라 짧은 장애에는 벡터 회상을 한두 턴만 잃고 곧 다시 확인한다.
BACKOFF_BASE_SECONDS = 30
# 문턱을 넘은 뒤로는 실패 하나가 셀 때마다 멈춤이 이 배수로 늘어 긴 장애에서는 확인 호출이 빠르게 드물어진다. 실패를 하나씩
# 세므로 확인 한 번에 한 단계씩 늘지는 않는다 — 멈춤이 풀린 순간 여러 호출(여러 방의 턴, 채우기)이 함께 통과해 모두 실패하면
# 각자 수를 올려 한 번에 여러 단계(상한까지) 뛰고, 멈춤이 걸리기 전에 이미 떠 있던 호출이 늦게 실패해도 센다. 지금은 Voyage 를
# 동시에 부르는 호출이 적어 한 번에 뛰는 폭이 작고, 뛰어도 상한 안에서 장애가 풀린 뒤 첫 성공이 수를 지우므로 받아들인다.
BACKOFF_FACTOR = 2
# 멈춤의 상한(초). 장애가 풀린 뒤 이보다 오래 벡터 회상 없이 지내지 않는다. 밀린 기억 임베딩은 풀린 뒤 채우기가 따라잡는다.
BACKOFF_MAX_SECONDS = 15 * 60
VOYAGE_BACKOFF_KEY = "voyage_backoff"
# 마지막 실패 뒤 이만큼 지나면 상태를 잊는다. 멈춤 상한보다 넉넉히 길어 긴 장애 도중 실패 수가 사라지지 않고, 하루 동안
# 실패가 없었다면 다음 실패는 처음부터 센다.
_BACKOFF_TTL_SECONDS = 60 * 60 * 24
# 거듭제곱 지수의 상한. 상한 시간에 닿은 뒤로는 더 키워도 같으므로 실패 수가 아주 커도 큰 정수를 만들지 않는다.
_MAX_EXPONENT = 32


def _now() -> float:
    return time.time()


def backoff_seconds(failures: int) -> float:
    """연속 실패 `failures` 번째 뒤에 멈출 시간(초). 문턱 아래면 0이다."""
    if failures < BACKOFF_AFTER_FAILURES:
        return 0.0
    exponent = min(failures - BACKOFF_AFTER_FAILURES, _MAX_EXPONENT)
    return float(min(BACKOFF_BASE_SECONDS * BACKOFF_FACTOR**exponent, BACKOFF_MAX_SECONDS))


async def voyage_allowed() -> bool:
    """지금 Voyage 를 불러도 되는지. Redis 를 못 읽거나 상태가 깨져 있으면 부른다."""
    try:
        state = await redis_client.hgetall(VOYAGE_BACKOFF_KEY)
        if not state:
            return True
        failures = int(state["failures"])
        failed_at = float(state["failed_at"])
    except (RedisError, KeyError, ValueError) as exc:
        logger.warning("Voyage 실패 백오프 상태를 못 읽었다 — 부른다: %s", exc)
        return True
    return _now() >= failed_at + backoff_seconds(failures)


async def record_voyage_failure() -> None:
    """Voyage 호출 실패 하나를 센다. Redis 오류는 삼킨다."""
    try:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.hincrby(VOYAGE_BACKOFF_KEY, "failures", 1)
            pipe.hset(VOYAGE_BACKOFF_KEY, "failed_at", str(_now()))
            pipe.expire(VOYAGE_BACKOFF_KEY, _BACKOFF_TTL_SECONDS)
            await pipe.execute()
    except RedisError as exc:
        logger.warning("Voyage 실패 횟수를 못 적었다: %s", exc)


async def clear_voyage_backoff() -> None:
    """Voyage 호출이 성공했다 — 연속 실패 수를 지운다. Redis 오류는 삼킨다."""
    try:
        await redis_client.delete(VOYAGE_BACKOFF_KEY)
    except RedisError as exc:
        logger.warning("Voyage 실패 횟수를 못 지웠다: %s", exc)
