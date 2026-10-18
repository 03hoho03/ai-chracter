"""Voyage 임베딩 호출의 연속 실패 백오프 — 방과 무관한 Redis 키 하나로 연속 실패를 세고, 쌓이면 정한 시각까지 부르지 않는다.

Voyage 가 내려가거나 키가 거부되면 모든 방의 모든 턴이 같은 실패를 되풀이한다. 질의 임베딩은 생성 앞에서 기다리므로 실패할 때마다
첫 글자 지연이 늘고, 실패마다 경고·Bugsink 승격이 쌓인다. 장애는 방이 아니라 Voyage 쪽 사정이라 카운터도 방마다가 아니라 하나다.

- 질의 임베딩(`chat/turn_prompt.py`)과 기억 임베딩 채우기(`chat/memory_embeddings.py`)가 같은 카운터를 함께 쓴다. 둘 다 부르기 전에
  `voyage_allowed` 로 묻고, 호출이 실패하면 `record_voyage_failure`, 성공하면 `clear_voyage_backoff` 를 부른다.
- 질의 임베딩의 시간 초과는 실패로 세지 않는다 — 우리 상한(1초)이 짧아 느리지만 살아 있는 Voyage 를 세면 채우기까지 멈춘다.
- 건너뛴 질의 임베딩은 임베딩 회상이 꺼진 턴과 같다(명사 단독 회상, 턴 기록에 호출 칸 없음).
- Redis 를 못 읽거나 못 쓰면 백오프 없이 지금처럼 부른다 — 막아서 잃는 것은 회상 품질이고, 불러서 잃는 것은 호출 원가뿐이다.

상태는 해시 하나(`failures` 연속 실패 수, `until` 다시 부를 수 있는 유닉스 시각)이고 TTL 이 있어 잊힌 상태가 남지 않는다."""

import time

# 상태를 읽고 쓰는 곳. 테스트가 이 이름을 갈아 끼워 Redis 장애를 흉내 낸다.
from api.core.redis import redis_client

# 연속 실패가 이만큼 쌓이면 멈춘다. 한두 번은 일시적인 연결 끊김일 수 있어 바로 멈추지 않는다.
BACKOFF_AFTER_FAILURES = 3
# 처음 멈추는 시간(초). 이후 실패마다 `BACKOFF_FACTOR` 배로 늘어 `BACKOFF_MAX_SECONDS` 에서 멈춘다 — 짧은 장애는 금방 다시
# 확인하고, 긴 장애에는 확인 호출이 몇 분에 한 번으로 준다.
BACKOFF_BASE_SECONDS = 30
BACKOFF_FACTOR = 2
# 멈춤의 상한(초). 장애가 풀린 뒤 이보다 오래 임베딩 없이 지내지 않는다.
BACKOFF_MAX_SECONDS = 15 * 60
VOYAGE_BACKOFF_KEY = "voyage_backoff"
# 마지막 실패 뒤 이만큼 지나면 상태를 잊는다. 멈춤 상한보다 넉넉히 길어야 연속 실패 수가 상한 도중에 사라지지 않는다.
_BACKOFF_TTL_SECONDS = 60 * 60 * 24


def _now() -> float:
    return time.time()


def backoff_seconds(failures: int) -> float:
    """연속 실패 `failures` 번째 뒤에 멈출 시간(초). 문턱 아래면 0이다."""
    return 0.0


async def voyage_allowed() -> bool:
    """지금 Voyage 를 불러도 되는지. Redis 를 못 읽으면 부른다."""
    return True


async def record_voyage_failure() -> None:
    """Voyage 호출 실패 하나를 센다. 문턱에 닿으면 다시 부를 수 있는 시각을 적는다. Redis 오류는 삼킨다."""


async def clear_voyage_backoff() -> None:
    """Voyage 호출이 성공했다 — 연속 실패 수와 멈춤 시각을 지운다. Redis 오류는 삼킨다."""
