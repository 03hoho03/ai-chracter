"""채팅 턴 하나의 차감을 끝까지 정산한다 — 응답이 저장되지 않은 채 턴이 끝나면, 끝난 이유가 무엇이든 되돌린다.

게이트가 `Depends` 단계에서 클로버를 자기 트랜잭션으로 커밋하므로, 그 뒤 라우트 제너레이터가 응답을 저장하지 못하고
끝나면 차감만 남는다. 생성·렌더 실패처럼 우리가 아는 자리는 제너레이터 안에서 명시적으로 되돌리지만, 클라이언트가
연결을 끊거나 예상하지 못한 예외가 나면 그 자리에 닿지 않는다. 끊김이 제너레이터에 닿는 길은 둘이다.

- 제너레이터가 `await`(LLM 스트림·판정·DB) 중이면 그 자리에서 `CancelledError` 가 난다. anyio 취소는 한 번 전달되고
  끝나지 않는다 — 취소된 범위 안에서는 `except` 블록의 다음 `await` 도 다시 취소된다. 그래서 정산 본문 전체를
  차폐(shield)된 범위에서 돌린다.
- 제너레이터가 `yield` 에 멈춰 있을 때(토큰이 흐르는 중의 끊김, 운영에서 가장 흔하다) 취소되는 것은 FastAPI 의
  생산자 태스크이고 제너레이터는 그대로 남는다. 참조가 사라지면 asyncio 의 비동기 제너레이터 종료 훅이 새 태스크에서
  `aclose()` 해 `GeneratorExit` 가 난다. `CancelledError` 만 잡으면 이 길을 놓치므로 `BaseException` 을 잡는다.

취소 전파는 바꾸지 않는다 — 정산 뒤 원래 예외를 그대로 다시 올린다.

정산이 끝났다는 표시(`mark_settled`)는 응답이 커밋된 직후, 그리고 환급하지 않기로 한 끝(정책 위반·방 삭제)에 세운다.
응답 커밋이 끊김과 겹치면 커밋이 서버에서 끝났는지 알 수 없으므로, 정산이 새 세션으로 응답 행이 있는지 직접 본다.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.rate_limit_gate import ChatCharge
from api.core.sentry import capture_dependency_failure
from api.db.models.chat import ChatMessage, ChatRoom

logger = logging.getLogger(__name__)

# 끊긴 턴의 정산(응답 확인 + 환급)에 주는 시간. 환급 래퍼 자신의 상한(10초)에 응답 확인 몫을 더했다. 상한이 있어야
# 종료 중인 프로세스가 끊긴 턴 하나로 멈추지 않는다.
SETTLE_TIMEOUT_SECONDS = 15.0


@dataclass
class _PendingReply:
    # 응답을 쓰는 요청 세션. 확인 전에 닫아 그 트랜잭션이 쥔 방 행 잠금을 놓게 한다.
    db: AsyncSession
    room_id: uuid.UUID
    message_id: uuid.UUID


@dataclass
class TurnSettlement:
    charge: ChatCharge
    user_id: uuid.UUID
    session_factory: async_sessionmaker[AsyncSession]
    settled: bool = False
    _pending: _PendingReply | None = None

    def mark_settled(self) -> None:
        """환급 판단이 끝났다 — 응답이 커밋됐거나, 환급하지 않기로 한 끝이다."""
        self.settled = True

    def set_pending_message(self, db: AsyncSession, room_id: uuid.UUID, message_id: uuid.UUID) -> None:
        """응답 행을 세션에 올린 뒤 부른다. 여기부터 커밋이 돌아올 때까지는 끊김이 와도 응답이 저장됐을 수 있다."""
        self._pending = _PendingReply(db=db, room_id=room_id, message_id=message_id)

    async def refund(self) -> None:
        """이 턴의 차감을 되돌린다. 표시를 **먼저** 세워, 환급 도중 끊김이 와도 가드가 두 번째로 되돌리지 않게 한다.
        무료 창(`free`)·면제(`skipped`)는 깎은 것이 없어 되돌릴 것도 없다."""
        self.settled = True
        if self.charge.source != "clover":
            return
        await clover.refund_spend_in_new_transaction(
            self.session_factory,
            user_id=self.user_id,
            spend_ledger_id=self.charge.spend_ledger_id,
            amount=self.charge.clover_amount,
            kind="chat_refund",
        )

    async def refund_if_unsettled(self) -> None:
        """정산되지 않은 채 끝난 턴을 되돌린다. 응답 확인과 환급 둘 다 차폐 안에서 한다 — 확인만 밖에 두면 취소된
        범위의 첫 `await` 에서 다시 취소돼 환급까지 가지 못한다."""
        if self.settled:
            return
        with anyio.move_on_after(SETTLE_TIMEOUT_SECONDS, shield=True) as scope:
            if self._pending is not None and not await self._reply_missing(self._pending):
                self.settled = True
                return
            await self.refund()
        if scope.cancelled_caught:
            logger.warning("끊긴 턴의 정산이 시간 안에 끝나지 않았다 — 그 턴의 차감이 남았을 수 있다")
            capture_dependency_failure(TimeoutError("turn settlement timed out"), dependency="clover")

    async def _reply_missing(self, pending: _PendingReply) -> bool:
        """응답이 저장되지 않았으면 참이다. 방이 지워졌으면 거짓이다 — 사용자가 지운 방은 환급하지 않는다.
        확인 자체가 실패하면 거짓으로 보고 남긴다(이중 환급보다 덜 위험한 쪽이다).

        요청 세션을 먼저 닫는다. 쓰기 구간은 방 행을 `FOR NO KEY UPDATE` 로 잠그고 있고, 예외로 끝났으면 그 트랜잭션이
        아직 열려 있다 — 닫지 않으면 아래 `FOR SHARE` 가 자기 요청의 잠금을 기다리다 시간을 다 쓴다. 커밋이 끊김과 겹쳐
        서버에서 아직 진행 중이면 `FOR SHARE` 가 그 트랜잭션이 끝날 때까지 기다리므로, 그 뒤에 읽는 응답 행이 확정된
        결과다."""
        try:
            await pending.db.close()
            async with self.session_factory() as session:
                room_id = await session.scalar(
                    select(ChatRoom.id).where(ChatRoom.id == pending.room_id).with_for_update(read=True)
                )
                if room_id is None:
                    return False
                saved = await session.scalar(select(ChatMessage.id).where(ChatMessage.id == pending.message_id))
                return saved is None
        except Exception as exc:
            logger.warning("끊긴 턴의 응답 저장 여부를 확인하지 못했다 — 환급하지 않는다", exc_info=True)
            capture_dependency_failure(exc, dependency="db")
            return False

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """라우트 제너레이터 본문 전체(첫 `yield` 전 구간 포함)를 감싼다. 어떤 이유로든 본문이 정산 없이 끝나면 되돌리고
        원래 예외를 다시 올린다."""
        try:
            yield
        except BaseException:
            await self.refund_if_unsettled()
            raise
