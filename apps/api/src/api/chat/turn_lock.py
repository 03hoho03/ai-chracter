"""한 대화방에서 대화 내용을 바꾸는 요청을 한 번에 하나만 들이는 Redis 락.

턴(보내기·수정·재생성)은 LLM 을 기다리는 동안 DB 트랜잭션을 쥐지 않는다 — 쥐면 동시에 진행할 수 있는 턴 수가
커넥션 풀 크기에 묶인다. 그 대가로 같은 방에 두 턴이 겹치면(두 탭, 응답 중에 방을 떠났다 돌아온 탭, 직접 API)
서로의 스탯 변화를 못 본 채 판정하고, 초기화·메시지 삭제가 끝난 방에 앞 턴의 응답이 붙는다. 그래서 같은 방의
턴·초기화·메시지 삭제를 이 락 하나로 줄 세우고, 이미 누가 쥐고 있으면 기다리지 않고 409 로 거절한다(응답이 끝날
때까지 요청을 붙잡아 두면 그 사이 연결·워커를 쥔다).

- 방 삭제·기억 요약 편집·빌더 미리보기는 대상이 아니다. 삭제는 언제나 성공해야 하고(진행 중 턴은 쓰기 직전에 방이
  사라진 것을 보고 아무것도 쓰지 않는다), 요약 편집은 이미 버전 비교로 충돌을 거절하고, 미리보기는 DB 방이 없다.
- TTL 은 60초 고정이다. 운영에서 잰 가장 긴 턴(약 21초)의 세 배쯤이다. LLM 호출마다 타임아웃이 있어 턴 길이에
  상한은 있지만(`core/config.py` 의 `gemini_*_timeout_ms` — 생성 45초 + 스탯·그림 판정 20초 + 엔딩 판정 20초 ×
  판정할 엔딩 수) 그 합이 TTL 을 넘을 수 있다. 넘친 턴은 "그 한 턴 동안만 다음 요청이 들어올 수 있다"로 받아들이고
  해제 때 경고를 남겨 관측한다.
  소유자 토큰으로 지우므로 늦게 끝난 턴이 뒤에 잡힌 락을 지우지는 않는다. 배포·크래시로 해제 없이 죽은 턴의 락은
  TTL 이 지나 풀린다 — 그동안 그 사용자는 409 를 본다(그래서 길게 잡지 않는다).
- Redis 장애면 락 없이 진행한다(fail-open). 이미지 생성 락·업로드 완료 락은 장애 때 거부하는데, 그쪽은 GPU·심사를
  지키고 이 락은 판정 품질을 지킬 뿐 돈(클로버 차감은 게이트가 자기 트랜잭션에서 한다)과 무관하다. 바로 뒤의 채팅
  차감 게이트는 Gemini 턴이면 장애 때 통과시키고(채팅 경로의 장애 동작이 한쪽으로 맞는다), 상위 모델 턴이면 분당 상한을
  못 센 채 비싼 호출을 열지 않으려고 거절한다 — 그 거절은 돈을 지키는 게이트의 판단이라 이 락의 선택과 따로다. Redis
  전체가 죽으면 그보다 먼저 세션 조회가 실패하므로 이 선택이 의미 있는 것은 일부 장애뿐이다.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import HTTPException, status
from redis.exceptions import RedisError

from api.core.rate_limit_gate import _report_redis_failure
from api.core.redis import redis_client
from api.core.redis_lock import release_lock, try_acquire_lock

logger = logging.getLogger(__name__)

TURN_LOCK_TTL_MS = 60_000
TURN_IN_PROGRESS_CODE = "CHAT_TURN_IN_PROGRESS"


def _key(room_id: uuid.UUID) -> str:
    return f"chat_room:turn_lock:{room_id}"


@dataclass
class RoomTurnLock:
    """잡은 락 하나. `token` 이 None 이면 Redis 장애로 락 없이 진행 중이다.

    `released` 는 해제를 한 번 마쳤다는 표시다 — 턴 경로는 스트림 끝과 요청 정리 두 자리에서 해제를 부르므로, 앞에서
    이미 지운 락을 뒤에서 "남의 락"으로 오인해 경고하지 않게 한다."""

    room_id: uuid.UUID
    token: str | None
    acquired_at: float
    released: bool = False


async def acquire_room_turn_lock(room_id: uuid.UUID) -> RoomTurnLock:
    """방 락을 잡는다. 이미 누가 쥐고 있으면 409 `CHAT_TURN_IN_PROGRESS` 를 던진다 — 남은 시간은 서버도 모르므로
    (TTL 잔여는 턴 잔여가 아니다) 재시도 시각은 싣지 않는다."""
    acquired_at = time.monotonic()
    try:
        token = await try_acquire_lock(redis_client, _key(room_id), ttl_ms=TURN_LOCK_TTL_MS)
    except RedisError as exc:
        logger.warning("대화방 %s 턴 락을 잡지 못했다(Redis 장애) — 락 없이 진행한다: %s", room_id, exc)
        _report_redis_failure()
        return RoomTurnLock(room_id=room_id, token=None, acquired_at=acquired_at)
    if token is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": TURN_IN_PROGRESS_CODE})
    return RoomTurnLock(room_id=room_id, token=token, acquired_at=acquired_at)


async def release_room_turn_lock(lock: RoomTurnLock) -> None:
    """내가 잡은 락이면 지운다. 예외를 내지 않는다 — SSE 제너레이터 본문과 요청 정리에서 불리고, 못 지운 락은 TTL 이
    회수한다. 락이 이미 내 것이 아니면(TTL 이 지나 풀렸거나 다른 요청이 새로 잡음) 경고를 남긴다 — TTL 이 짧았는지를
    운영 로그로 판정하는 근거다."""
    if lock.released or lock.token is None:
        return
    elapsed = time.monotonic() - lock.acquired_at
    try:
        still_mine = await release_lock(redis_client, _key(lock.room_id), lock.token)
    except RedisError as exc:
        logger.warning("대화방 %s 턴 락을 풀지 못했다(Redis 장애) — TTL 이 지나면 풀린다: %s", lock.room_id, exc)
        return
    lock.released = True
    if not still_mine:
        logger.warning(
            "대화방 %s 턴 락이 해제 전에 이미 풀려 있었다 — 턴이 %.1f초 걸려 락 TTL(%d초)을 넘겼을 수 있다",
            lock.room_id,
            elapsed,
            TURN_LOCK_TTL_MS // 1000,
        )


@asynccontextmanager
async def hold_room_turn_lock(room_id: uuid.UUID) -> AsyncIterator[RoomTurnLock]:
    """잡고, 블록이 어떻게 끝나든 푼다. 거절이면 블록에 들어가기 전에 409 가 난다."""
    lock = await acquire_room_turn_lock(room_id)
    try:
        yield lock
    finally:
        await release_room_turn_lock(lock)
