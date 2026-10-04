"""긴 방의 오래된 대화를 요약 스냅샷으로 접는다.

생성 프롬프트는 요약 커서 **뒤** 메시지만 원문으로 싣는다(`memory_window`). 커서 뒤 대화가 30턴에
닿거나, 원문 글자가 24,000자를 넘고 접은 뒤에도 10턴이 남으면 가장 오래된 10턴을 요약에 접어
커서를 앞으로 민다. 커서는 여기서 스냅샷을 커밋할 때만 움직이므로, 요약이 실패하거나 늦으면 원가만
잠시 늘고 대화는 하나도 빠지지 않는다.

턴이 끝난 뒤 요청의 background로 돈다 — 요청 세션이 아니라 새 세션을 열고, 어떤 예외도 밖으로
내지 않는다(사용자에게 보이는 것은 없다). 요약 호출은 사용자가 시킨 호출이 아니라서 클로버를
깎지 않고 레이트리밋에도 세지 않는다.

이 모듈은 방의 기억 노트 컬럼을 읽지도 쓰지도 않는다. 노트는 사용자만 고치는 칸이고, 요약 입력에도
넣지 않는다(노트는 매 턴 따로 실린다) — 테스트가 이 모듈 소스에 그 컬럼 이름이 없음을 확인한다."""

import logging
import uuid
from collections.abc import Sequence
from typing import NamedTuple

from redis.exceptions import RedisError
from sqlalchemy import select, tuple_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.memory_window import MessageKey, load_current_summary, opening_message
from api.chat.prompt_builder import MemorySummaryResult, PromptNames, PromptRenderError, build_memory_summary_prompt
from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure
from api.db.models import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomMemorySnapshot, PromptSection, PromptSet
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMRateLimitError

logger = logging.getLogger(__name__)

# 한 번에 접는 턴 수. 원문은 접은 뒤 20턴, 다음 접기 직전 29턴 사이를 오간다.
FOLD_TURNS = 10
FOLD_AT_TURNS = 30
# 턴이 30에 못 미쳐도 원문이 이만큼 길면 일찍 접는다. 대신 접은 뒤 원문이 너무 짧아지지 않게
# 남는 턴이 `MIN_TURNS_AFTER_EARLY_FOLD` 미만이면 접지 않는다 — 메시지를 버리는 상한이 아니다.
FOLD_AT_CHARS = 24_000
MIN_TURNS_AFTER_EARLY_FOLD = 10
# 요약 본문의 상한. 모델 출력 길이를 호출에서 제한하지 않으므로 서버에서 자른다.
SUMMARY_MAX_LENGTH = 1_500

# 같은 입력이 안전 차단에 반복해서 걸리면 매 턴 재시도가 호출만 늘린다. 연속 실패가 이만큼 쌓이면
# 마지막 실패 턴에서 `BACKOFF_TURNS`턴 동안은 시도하지 않는다.
BACKOFF_AFTER_FAILURES = 3
BACKOFF_TURNS = 5
_BACKOFF_KEY_PREFIX = "memory_fold_backoff:"
_BACKOFF_TTL_SECONDS = 60 * 60 * 24 * 30


class FoldPlan(NamedTuple):
    turns: list[ChatMessage]
    cursor: MessageKey


def plan_fold(unsummarized: Sequence[ChatMessage]) -> FoldPlan | None:
    """`unsummarized`는 요약 커서 뒤 메시지(오프닝 제외)를 키 순으로 둔 목록이다. 접을 때가 되면
    가장 오래된 10턴(그 턴들의 사용자 메시지 포함)과 새 커서(10번째 어시스턴트 메시지의 키)를,
    아니면 None을 돌려준다. 턴은 어시스턴트 메시지 수로 센다 — 메시지를 지워 사용자·어시스턴트
    짝이 깨질 수 있어서다."""
    turn_count = sum(1 for message in unsummarized if message.role == ChatMessageRole.ASSISTANT)
    char_count = sum(len(message.content) for message in unsummarized)
    due = turn_count >= FOLD_AT_TURNS or (
        char_count >= FOLD_AT_CHARS and turn_count - FOLD_TURNS >= MIN_TURNS_AFTER_EARLY_FOLD
    )
    if not due:
        return None
    seen = 0
    for index, message in enumerate(unsummarized):
        if message.role != ChatMessageRole.ASSISTANT:
            continue
        seen += 1
        if seen == FOLD_TURNS:
            return FoldPlan(turns=list(unsummarized[: index + 1]), cursor=(message.created_at, message.id))
    return None


def backoff_allows(failures: int, last_failed_turn: int, turn: int) -> bool:
    """연속 실패가 쌓인 방에서 이번 턴에 접기를 시도할지. 턴이 되감겨 마지막 실패 턴보다 작아졌으면
    시도한다(그 사이 대화가 바뀌었다)."""
    if failures < BACKOFF_AFTER_FAILURES:
        return True
    return not last_failed_turn <= turn < last_failed_turn + BACKOFF_TURNS


async def fold_memory(
    session_factory: async_sessionmaker[AsyncSession],
    llm_client: LLMClient,
    *,
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    names: PromptNames,
) -> None:
    """접을 때가 된 방이면 요약을 만들어 스냅샷으로 커밋한다. 절대 예외를 내지 않는다.

    `names` 는 이 접기를 예약한 턴의 이름이다(작가 글의 `{{user}}` 를 바꾸고 이름 한 줄을 채운다). 백그라운드라 방
    프로필을 다시 읽지 않고 그 턴의 생성 프롬프트와 같은 값을 받는다.

    순서가 정합성의 전부다.
    1. 방의 `memory_version`을 **가장 먼저** 읽고, 그다음 현재 요약과 커서 뒤 메시지를 읽는다.
       반대 순서면 그 사이 커밋된 메시지 삭제의 버전 증가를 먼저 읽은 버전이 흡수해, 지운 메시지를
       담은 입력으로 아래 조건부 UPDATE가 성공한다.
    2. 읽기 세션을 닫고 요약을 부른다 — LLM을 기다리는 동안 커넥션을 쥐지 않는다.
    3. 새 세션에서 "버전이 1번에서 읽은 값 그대로일 때만" 버전을 올리고(행 락을 겸한다) 같은
       트랜잭션에서 스냅샷을 넣는다. 그사이 사용자 편집·되감기·다른 접기가 버전을 바꿨으면 결과를
       버린다 — 사용자의 변경이 조용히 덮이지 않게.
    """
    turn: int | None = None
    try:
        async with session_factory() as session:
            room = (
                await session.execute(
                    select(ChatRoom.memory_version, ChatRoom.turn_count).where(ChatRoom.id == room_id)
                )
            ).first()
            if room is None:
                return
            read_version, turn = room.memory_version, room.turn_count
            if not await _backoff_allows(room_id, turn):
                return
            current = await load_current_summary(session, room_id)
            unsummarized = await _load_unsummarized(session, room_id, current.cursor if current else None)

        plan = plan_fold(unsummarized)
        if plan is None:
            return

        prompt = build_memory_summary_prompt(
            prompt_set=prompt_set,
            sections=sections,
            is_story_chat=is_story_chat,
            previous_summary=current.text if current else "",
            turns=plan.turns,
            names=names,
        )
        if not prompt:
            raise PromptRenderError("요약 channel 이 비어 있다 — 활성 세트에 요약 지시문이 없다")
        result = await llm_client.generate_structured(
            prompt,
            MemorySummaryResult,
            usage=LLMCallContext(call_site="chat_memory_summary", user_id=user_id, room_id=room_id),
        )
        summary = result.summary.strip()[:SUMMARY_MAX_LENGTH]
        if not summary:
            # 빈 요약을 커밋하면 접은 10턴이 요약에도 원문에도 없게 된다.
            raise LLMClientError("요약 응답이 비었다")

        async with session_factory() as session:
            claimed = await session.scalar(
                update(ChatRoom)
                .where(ChatRoom.id == room_id, ChatRoom.memory_version == read_version)
                .values(memory_version=ChatRoom.memory_version + 1)
                .returning(ChatRoom.id)
            )
            if claimed is None:
                logger.warning("대화방 %s 요약 접기 결과를 버린다 — 그사이 기억이 바뀌었다", room_id)
                return
            session.add(
                ChatRoomMemorySnapshot(
                    chat_room_id=room_id,
                    cursor_created_at=plan.cursor[0],
                    cursor_message_id=plan.cursor[1],
                    summary_text=summary,
                    previous_text=None,
                    source="auto",
                )
            )
            await session.commit()
        await _clear_backoff(room_id)
    # `BaseException`이 아니라 `Exception` — 클라이언트가 끊어 생긴 취소까지 삼키면 요청 정리가 막힌다.
    except Exception as exc:
        logger.warning("대화방 %s 요약 접기 실패 — 다음 턴 뒤에 다시 시도한다: %s", room_id, exc)
        capture_dependency_failure(exc, dependency=_dependency_tag(exc))
        if turn is not None:
            await _record_failure(room_id, turn)


async def _load_unsummarized(
    session: AsyncSession, room_id: uuid.UUID, cursor: MessageKey | None
) -> list[ChatMessage]:
    """커서 뒤 메시지를 키 순으로, 오프닝을 빼고 읽는다. 오프닝 판별은 윈도우와 같은 규칙
    (`opening_message`)이라 방의 첫 메시지를 따로 한 줄 읽는다."""
    order = (ChatMessage.created_at.asc(), ChatMessage.id.asc())
    first = (
        await session.scalars(select(ChatMessage).where(ChatMessage.chat_room_id == room_id).order_by(*order).limit(1))
    ).all()
    opening = opening_message(first)
    query = select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    if cursor is not None:
        query = query.where(tuple_(ChatMessage.created_at, ChatMessage.id) > cursor)
    messages = (await session.scalars(query.order_by(*order))).all()
    return [message for message in messages if opening is None or message.id != opening.id]


def _backoff_key(room_id: uuid.UUID) -> str:
    return f"{_BACKOFF_KEY_PREFIX}{room_id}"


async def _backoff_allows(room_id: uuid.UUID, turn: int) -> bool:
    """Redis를 못 읽으면 시도한다 — 시도해서 잃는 것은 호출 원가뿐이고, 막아서 잃는 것은 요약이다."""
    try:
        state = await redis_client.hgetall(_backoff_key(room_id))
        if not state:
            return True
        return backoff_allows(int(state["failures"]), int(state["turn"]), turn)
    except (RedisError, KeyError, ValueError) as exc:
        logger.warning("대화방 %s 요약 백오프 상태를 못 읽었다 — 접기를 시도한다: %s", room_id, exc)
        return True


async def _record_failure(room_id: uuid.UUID, turn: int) -> None:
    key = _backoff_key(room_id)
    try:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.hincrby(key, "failures", 1)
            pipe.hset(key, "turn", str(turn))
            pipe.expire(key, _BACKOFF_TTL_SECONDS)
            await pipe.execute()
    except RedisError as exc:
        logger.warning("대화방 %s 요약 실패 횟수를 못 적었다: %s", room_id, exc)


async def _clear_backoff(room_id: uuid.UUID) -> None:
    try:
        await redis_client.delete(_backoff_key(room_id))
    except RedisError as exc:
        logger.warning("대화방 %s 요약 실패 횟수를 못 지웠다: %s", room_id, exc)


def _dependency_tag(exc: Exception) -> str:
    """`chat/router.py`의 `_llm_dependency_tag`와 같은 분류에 DB를 더한다(그 함수는 라우터에 있어
    이 모듈이 import할 수 없다 — 라우터가 이 모듈을 import한다)."""
    if isinstance(exc, PromptRenderError):
        return "prompt_render"
    if isinstance(exc, LLMRateLimitError):
        return "gemini_rate_limit"
    if isinstance(exc, LLMClientError):
        return "gemini"
    if isinstance(exc, SQLAlchemyError):
        return "db"
    return "memory_fold"
