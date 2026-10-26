"""긴 방의 요약 접기 — 턴이 끝난 뒤 background가 오래된 10턴을 요약 스냅샷으로 접는다.

- 언제 접나: 커서 뒤(오프닝 제외) 턴이 30이 되면, 또는 원문이 24,000자 이상이고 접은 뒤 10턴이
  남으면. 접기는 턴을 커밋하는 send·edit·재생성 뒤마다 예약된다 — 재생성은 턴 수를 바꾸지 않지만 긴 응답으로 글자
  기준을 넘길 수 있고, 앞 턴에서 실패한 접기나 재생성의 되감기가 `memory_version` 을 올려 결과를 버리게 된, 진행
  중이던 접기를 다음 보내기까지 미루지 않는다.
- 무엇이 남나: 커서 = 접은 10번째 응답의 키, 본문 ≤ 1,500자, `source="auto"`, 되돌리기 버퍼 없음.
- 실패하면: 사용자에게 보이는 것 없이 흡수하고 커서는 그대로 — 다음 턴 뒤 다시 시도한다. 연속
  실패가 쌓이면 몇 턴 쉬었다 시도한다.
- 그사이 기억이 바뀌면(버전이 달라지면) 결과를 버린다.
- 노트·스탯·계정 정보는 요약 입력에 없고, 접기는 노트를 건드리지 않으며, 클로버·레이트리밋과
  무관하다.

httpx `ASGITransport`는 background까지 끝난 뒤 응답을 돌려주므로 요청 뒤 단언 시점에 접기가 이미
끝나 있다. 단언은 컬럼 단위 `select()`로 한다(요청과 같은 세션의 identity map에 속지 않게).
"""

import builtins
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold, turn_engine
from api.chat import router as chat_router
from api.chat.memory_fold import backoff_allows, plan_fold
from api.chat.prompt_builder import (
    NO_ROOM_PEOPLE,
    MemorySummaryResult,
    PromptNames,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat.schemas import ChatStreamEvent
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models import (
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    ChatRoomStat,
    CloverLedger,
    User,
)
from api.db.models.story import MediaBookPerson
from api.db.session import get_session_factory
from api.llm.chat_models import ChatModelId, PromptSetModelId
from api.llm.claude_messages import claude_error
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
)
from api.main import app
from factories import (
    Room,
    SnapshotRow,
    _clear_llm_override,
    _make_memory_fact,
    _make_user,
    _make_user_with_clover_lot,
    _memory_scope_covers_gemini,
    _memory_version,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _plant_snapshot,
    _snapshots,
)
from replay import logs as replay_logs

SUMMARY_TEXT = "[SUMMARY] 둘은 서점에서 만났다"


class SummaryLLMClient(LLMClient):
    """생성은 고정 응답. 요약 스키마에는 `summaries`를 차례로 준다(문자열은 요약 본문, 예외는
    raise, 콜러블은 먼저 불러 경합을 흉내 낸다). 요약 호출 프롬프트를 모은다. 스탯 판정에는 변화
    없음을 준다(스토리 방)."""

    def __init__(self, *summaries: str | Exception | Callable[[], Awaitable[str]]) -> None:
        self.summaries = list(summaries)
        self.summary_prompts: list[str] = []
        self.summary_usages: list[LLMCallContext] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "새 응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=[])
        assert response_schema is MemorySummaryResult, response_schema
        self.summary_prompts.append(prompt)
        self.summary_usages.append(usage)
        outcome = self.summaries.pop(0) if self.summaries else SUMMARY_TEXT
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            outcome = await outcome()
        return MemorySummaryResult(summary=outcome)


async def _request(db_client: httpx.AsyncClient, room: Room, action: str, fake: LLMClient) -> list[str]:
    """요청 하나를 보내고 SSE 이벤트 종류를 돌려준다. 편집은 마지막 사용자 메시지를 고친다."""
    _override_llm_client(fake)
    try:
        if action == "send":
            response = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
        elif action == "regenerate":
            response = await db_client.post(f"/chat-rooms/{room.room_id}/regenerate")
        else:
            last_user = room.turns[max(room.turns)][0]
            response = await db_client.patch(
                f"/chat-rooms/{room.room_id}/messages/{last_user.id}", json={"content": "고친 메시지"}
            )
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    return [event["type"] for event in _parse_sse_events(response.text)]


# --- 접을 때인가(순수 함수) --------------------------------------------------------------

_T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _pairs(turns: int, *, length: int = 10) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for turn in range(1, turns + 1):
        messages.append(
            ChatMessage(
                id=uuid.UUID(int=2 * turn - 1),
                role=ChatMessageRole.USER,
                content="u" * length,
                created_at=_T0 + timedelta(seconds=2 * turn - 1),
            )
        )
        messages.append(
            ChatMessage(
                id=uuid.UUID(int=2 * turn),
                role=ChatMessageRole.ASSISTANT,
                content="a" * length,
                created_at=_T0 + timedelta(seconds=2 * turn),
            )
        )
    return messages


def test_plan_fold_leaves_twenty_nine_turns_alone() -> None:
    assert plan_fold(_pairs(29)) is None


def test_plan_fold_folds_the_oldest_ten_turns_at_thirty() -> None:
    messages = _pairs(30)
    plan = plan_fold(messages)
    assert plan is not None
    assert plan.turns == messages[:20]
    assert plan.cursor == (messages[19].created_at, messages[19].id)


def test_plan_fold_folds_early_when_the_text_is_long_and_ten_turns_would_remain() -> None:
    # 20턴 × 2메시지 × 600자 = 24,000자
    messages = _pairs(20, length=600)
    plan = plan_fold(messages)
    assert plan is not None
    assert plan.turns == messages[:20]


def test_plan_fold_does_not_fold_early_just_under_the_text_limit() -> None:
    messages = _pairs(20, length=600)
    messages[-1].content = messages[-1].content[:-1]
    assert plan_fold(messages) is None


def test_plan_fold_does_not_fold_early_when_fewer_than_ten_turns_would_remain() -> None:
    assert plan_fold(_pairs(19, length=5_000)) is None


def test_plan_fold_counts_assistant_messages_as_turns_and_cuts_after_the_tenth() -> None:
    """사용자 메시지를 지워 짝이 깨진 방 — 턴은 어시스턴트 메시지 수다."""
    messages = [message for message in _pairs(30) if not (message.role == ChatMessageRole.USER and message.id.int < 10)]
    plan = plan_fold(messages)
    assert plan is not None
    tenth_assistant = [message for message in messages if message.role == ChatMessageRole.ASSISTANT][9]
    assert plan.turns[-1] is tenth_assistant
    assert plan.cursor == (tenth_assistant.created_at, tenth_assistant.id)


@pytest.mark.parametrize(
    ("failures", "last_failed_turn", "turn", "allowed"),
    [
        pytest.param(2, 30, 31, True, id="two-failures"),
        pytest.param(3, 30, 31, False, id="three-failures-next-turn"),
        pytest.param(3, 30, 34, False, id="three-failures-four-turns-later"),
        pytest.param(3, 30, 35, True, id="three-failures-five-turns-later"),
        pytest.param(3, 30, 25, True, id="rewound-turn"),
    ],
)
def test_backoff_allows(failures: int, last_failed_turn: int, turn: int, allowed: bool) -> None:
    assert backoff_allows(failures, last_failed_turn, turn) is allowed


# --- 라우트에서 언제 접나 -----------------------------------------------------------------


@pytest.mark.parametrize("lane", ["character", "story"])
async def test_send_that_reaches_thirty_turns_folds_the_oldest_ten(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str
) -> None:
    room = await _open_room(db_client, db_session, turns=29, lane=lane)
    fake = SummaryLLMClient()

    events = await _request(db_client, room, "send", fake)

    assert events[-1] == "done"
    assert len(fake.summary_prompts) == 1
    assert fake.summary_usages[0].call_site == "chat_memory_summary"
    assert fake.summary_usages[0].room_id == room.room_id
    prompt = fake.summary_prompts[0]
    for turn in range(1, 11):
        assert prompt.count(f"[U{turn:02d}]") == 1
        assert prompt.count(f"[A{turn:02d}]") == 1
    assert "[U11]" not in prompt
    tenth = room.turns[10][1]
    assert await _snapshots(db_session, room) == [
        SnapshotRow(tenth.created_at, tenth.id, SUMMARY_TEXT, None, "auto")
    ]
    assert await _memory_version(db_session, room) == 1


async def test_send_at_twenty_nine_turns_does_not_fold(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """오프닝은 턴으로 세지 않는다 — 셌다면 여기서 30이 된다."""
    room = await _open_room(db_client, db_session, turns=28)
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    assert fake.summary_prompts == []
    assert await _snapshots(db_session, room) == []


@pytest.mark.parametrize(("turns", "folds"), [(30, True), (29, False)], ids=["thirty", "twenty-nine"])
async def test_edit_folds_when_the_rewritten_turn_leaves_thirty_turns(
    db_client: httpx.AsyncClient, db_session: AsyncSession, turns: int, folds: bool
) -> None:
    room = await _open_room(db_client, db_session, turns=turns)
    fake = SummaryLLMClient()

    await _request(db_client, room, "edit", fake)

    assert len(fake.summary_prompts) == (1 if folds else 0)
    assert len(await _snapshots(db_session, room)) == (1 if folds else 0)


async def test_regenerate_in_a_room_due_for_a_fold_folds_the_oldest_ten(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재생성은 턴 수를 바꾸지 않지만 커밋 뒤 접기를 예약한다 — 접을 때가 된 방이면 다음 보내기까지 미루지 않고 접는다."""
    room = await _open_room(db_client, db_session, turns=30)
    fake = SummaryLLMClient()

    events = await _request(db_client, room, "regenerate", fake)

    assert events[-1] == "done"
    assert len(fake.summary_prompts) == 1
    assert fake.summary_usages[0].call_site == "chat_memory_summary"
    tenth = room.turns[10][1]
    assert [row.cursor_message_id for row in await _snapshots(db_session, room)] == [tenth.id]


async def test_long_text_folds_before_thirty_turns(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    # 19턴 × 2메시지 × 650자 ≈ 24,700자 + 이번 턴 → 20턴, 24,000자 이상
    room = await _open_room(db_client, db_session, turns=19, message_length=650)
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    tenth = room.turns[10][1]
    assert [row.cursor_message_id for row in await _snapshots(db_session, room)] == [tenth.id]


async def test_next_fold_summarizes_the_previous_summary_with_the_next_ten_turns(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=39)
    await _plant_snapshot(db_session, room, turn=10, text="[PREV] 앞선 요약")
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    prompt = fake.summary_prompts[0]
    assert "[PREV] 앞선 요약" in prompt
    assert "[A10]" not in prompt
    assert "[U11]" in prompt and "[A20]" in prompt
    assert "[U21]" not in prompt
    twentieth = room.turns[20][1]
    assert [row.cursor_message_id for row in await _snapshots(db_session, room)] == [room.turns[10][1].id, twentieth.id]


class _StatChangingLLMClient(SummaryLLMClient):
    """스탯 판정에서 그 방 스탯의 규칙(a1)을 발동시킨다 — 턴 커밋 뒤 첫 이벤트가 `statChange`가 되게."""

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=["a1"])
        return await super().generate_structured(prompt, response_schema, images, usage=usage)


@pytest.mark.parametrize(
    ("action", "after_commit_events"),
    [
        pytest.param("send", ["statChange", "done"], id="send"),
        pytest.param("regenerate", ["done"], id="regenerate"),
    ],
)
async def test_fold_is_scheduled_before_the_first_event_after_the_turn_commits(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    after_commit_events: list[str],
) -> None:
    """클라이언트가 이벤트를 받고 끊으면 그 뒤에 예약하려던 background는 예약 자체가 사라진다(실제
    uvicorn으로 고정한 성질 — `test_sse_background_tasks.py`). 그래서 접기 예약은 턴 커밋 뒤 첫
    이벤트보다 앞이어야 한다. 턴 제너레이터가 이벤트를 내놓는 순간과 예약 호출을 한 로그에 적는다 —
    응답 본문이 나가는 순간으로는 못 본다(FastAPI가 제너레이터를 별도 태스크로 몇 개 앞서 당긴다).
    보내기는 스탯이 바뀌는 스토리 턴이라 첫 사후 이벤트가 `done`이 아니라 `statChange`다. 재생성은 스탯을 다시 판정하지
    않아 첫 사후 이벤트가 `done`이다."""
    log: list[str] = []
    original_add_task = BackgroundTasks.add_task

    def _recording_add_task(self: BackgroundTasks, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        log.append(f"schedule:{func.__name__}")
        original_add_task(self, func, *args, **kwargs)

    # 라우트는 턴 골격을 라우터에 import 된 이름으로 부른다 — 그 자리를 감싼 것으로 바꾼다.
    original_turn = turn_engine.run_turn

    async def _recording_turn(*args: Any, **kwargs: Any) -> AsyncIterator[ChatStreamEvent]:
        # 안쪽 제너레이터는 이 줄이 도는 동안 자기 `yield`에 멈춰 있다 — 기록 순서가 곧 실행 순서다.
        async for event in original_turn(*args, **kwargs):
            log.append(event.type)
            yield event

    monkeypatch.setattr(BackgroundTasks, "add_task", _recording_add_task)
    monkeypatch.setattr(chat_router, "run_turn", _recording_turn)

    room = await _open_room(db_client, db_session, turns=1, lane="story")
    events = await _request(db_client, room, action, _StatChangingLLMClient())

    assert events == ["token", *after_commit_events]
    assert log == ["token", "schedule:fold_memory", *after_commit_events]


async def test_generation_window_switched_off_does_not_fold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "memory_window_generation", False)
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    assert fake.summary_prompts == []
    assert await _snapshots(db_session, room) == []


# --- 경합·실패 ---------------------------------------------------------------------------


async def test_fold_discards_its_summary_when_the_memory_changed_meanwhile(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약을 기다리는 사이 다른 쓰기(사용자 편집·되감기·다른 접기)가 버전을 올린 상황."""
    room = await _open_room(db_client, db_session, turns=29)

    async def _someone_else_changes_the_memory() -> str:
        await db_session.execute(
            sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_version=ChatRoom.memory_version + 1)
        )
        await db_session.commit()
        return SUMMARY_TEXT

    fake = SummaryLLMClient(_someone_else_changes_the_memory)

    await _request(db_client, room, "send", fake)

    assert len(fake.summary_prompts) == 1
    assert await _snapshots(db_session, room) == []
    assert await _memory_version(db_session, room) == 1


@pytest.mark.parametrize(
    ("outcome", "tag"),
    [
        pytest.param(LLMClientError("boom"), "gemini", id="llm-error"),
        pytest.param(LLMPolicyViolationError("blocked"), "gemini", id="safety-block"),
        pytest.param(LLMRateLimitError("quota"), "gemini_rate_limit", id="quota"),
        # 요약 모델을 Claude 로 바꾸면 실패의 태그도 그 구현의 이름이다(판정·생성 실패와 같은 분류).
        pytest.param(claude_error(LLMClientError, "boom", "bedrock"), "bedrock", id="bedrock-error"),
        pytest.param(claude_error(LLMRateLimitError, "quota", "anthropic"), "anthropic_rate_limit", id="anthropic-quota"),
        pytest.param("   ", "gemini", id="blank-summary"),
    ],
)
async def test_failed_fold_is_absorbed_and_retried_after_the_next_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str | Exception,
    tag: str,
) -> None:
    captured: list[str] = []
    monkeypatch.setattr(memory_fold, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency))
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient(outcome)

    events = await _request(db_client, room, "send", fake)

    assert events == ["token", "done"]
    assert captured == [tag]
    assert await _snapshots(db_session, room) == []
    assert await _memory_version(db_session, room) == 0

    await _request(db_client, room, "send", fake)

    assert len(fake.summary_prompts) == 2
    assert len(await _snapshots(db_session, room)) == 1


async def test_fold_absorbs_a_real_database_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """접기의 쓰기 트랜잭션을 진짜 SQL 오류로 aborted 시킨다(합성 예외는 그 상태를 못 만든다).

    운영에서 접기 세션은 자기 커넥션을 쓰지만 테스트는 요청과 한 커넥션을 나눠 쓴다 — 그래서 이
    테스트만 세션마다 SAVEPOINT를 여는 팩토리를 끼워, 접기 세션의 실패가 테스트 트랜잭션까지
    망가뜨리지 않고 운영처럼 그 세션에 갇히게 한다."""
    captured: list[str] = []
    monkeypatch.setattr(memory_fold, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency))
    savepoint_factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    app.dependency_overrides[get_session_factory] = lambda: savepoint_factory

    original_scalar = AsyncSession.scalar

    async def _failing_claim(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(statement, sa.Update) and getattr(statement.table, "name", None) == "chat_rooms":
            await self.execute(sa.text("SELECT 1/0"))
        return await original_scalar(self, statement, *args, **kwargs)

    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient()
    monkeypatch.setattr(AsyncSession, "scalar", _failing_claim)

    events = await _request(db_client, room, "send", fake)

    monkeypatch.setattr(AsyncSession, "scalar", original_scalar)
    assert events == ["token", "done"]
    assert captured == ["db"]
    assert await _snapshots(db_session, room) == []
    assert await _memory_version(db_session, room) == 0

    await _request(db_client, room, "send", fake)

    assert len(await _snapshots(db_session, room)) == 1


class _BrokenRedis:
    """모든 명령이 `RedisError`인 Redis — 백오프 상태를 읽지도 쓰지도 못하는 상황."""

    def __getattr__(self, name: str) -> Any:
        async def _fail(*args: Any, **kwargs: Any) -> Any:
            raise RedisError("down")

        return _fail


async def test_fold_still_runs_when_its_failure_counter_is_unreachable(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """백오프 상태를 못 읽으면 막지 않고 시도한다 — 막으면 요약을, 시도하면 호출 원가만 잃는다."""
    monkeypatch.setattr(memory_fold, "redis_client", _BrokenRedis())
    room = await _open_room(db_client, db_session, turns=29)

    await _request(db_client, room, "send", SummaryLLMClient())

    assert len(await _snapshots(db_session, room)) == 1


async def test_repeated_failures_pause_the_fold_for_a_few_turns(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient(*(LLMPolicyViolationError("blocked") for _ in range(10)))

    for _ in range(4):
        await _request(db_client, room, "send", fake)

    assert len(fake.summary_prompts) == 3


async def test_summary_is_cut_to_fifteen_hundred_characters(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient("가" * 1_501)

    await _request(db_client, room, "send", fake)

    assert [len(row.summary_text) for row in await _snapshots(db_session, room)] == [1_500]


# --- 요약 입력·노트·원가 --------------------------------------------------------------------


async def test_summary_input_leaves_out_the_note_stats_and_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(nickname="[NICK]별")
    db_session.add(user)
    await db_session.flush()
    room = await _open_room(db_client, db_session, turns=29, lane="story", user=user)
    await db_session.execute(
        sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_note="[NOTE] 우산은 파란색")
    )
    await db_session.commit()
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    prompt = fake.summary_prompts[0]
    assert "[U01]" in prompt
    for absent in ("[NOTE]", "[STAT]", "73", "[NICK]", user.email):
        assert absent not in prompt


async def test_fold_leaves_the_note_untouched(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    note = "[NOTE] 우산은 파란색\n  앞뒤 공백도 그대로 "
    room = await _open_room(db_client, db_session, turns=29)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_note=note))
    await db_session.commit()

    await _request(db_client, room, "send", SummaryLLMClient())

    assert len(await _snapshots(db_session, room)) == 1
    assert await db_session.scalar(sa.select(ChatRoom.memory_note).where(ChatRoom.id == room.room_id)) == note


def test_fold_module_never_names_the_note_column() -> None:
    """노트는 사용자만 고치는 칸이다 — 요약 경로가 그 컬럼을 읽거나 쓰는 문장을 갖지 않는다는 것을
    구조로 지킨다."""
    source = Path(memory_fold.__file__).read_text(encoding="utf-8")
    assert "memory_note" not in source


async def test_a_folding_turn_costs_one_turn_of_clover_and_counts_once_against_rate_limits(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """요약 호출은 사용자가 시킨 호출이 아니다 — 접기가 도는 턴도 차감·카운트는 턴 하나분이다."""
    start_balance = 100
    user = await _make_user_with_clover_lot(
        db_session,
        clover_balance=start_balance,
        clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC)),
    )
    room = await _open_room(db_client, db_session, turns=29, user=user)
    # 셋업(방 생성)이 끝난 뒤 무료 창을 닫아 이번 턴을 클로버로 내게 한다.
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    await _request(db_client, room, "send", SummaryLLMClient())

    assert len(await _snapshots(db_session, room)) == 1
    assert await db_session.scalar(sa.select(User.clover_balance).where(User.id == user.id)) == (
        start_balance - clover.MODEL_PRICES["gemini"].chat_turn
    )
    ledger = (
        await db_session.execute(
            sa.select(CloverLedger.kind, CloverLedger.amount).where(CloverLedger.user_id == user.id)
        )
    ).all()
    assert [tuple(row) for row in ledger] == [("chat_spend", -clover.MODEL_PRICES["gemini"].chat_turn)]
    counters = [await redis_client.get(key) for key in await redis_client.keys(f"rate_limit:*{user.id}*")]
    assert counters and all(value == "1" for value in counters)


# --- 측정 서버의 프롬프트 덤프 -------------------------------------------------------------


def _background_dump_lines(path: Path) -> list[dict[str, Any]]:
    """덤프 파일에서 백그라운드 작업(요약 접기·기억 추출)의 줄만."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [record for record in records if record["kind"] == "background"]


async def test_fold_writes_its_summary_prompt_to_the_measurement_dump(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """측정 서버는 요약 모델을 바꿔 볼 때 같은 입력을 다시 보내야 한다 — 접기의 요약 프롬프트도 생성·판정 프롬프트와 같은
    파일에 한 줄로 남는다. 커서는 이 접기가 접는 마지막 메시지(새 스냅샷의 커서)다."""
    dump = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient()

    events = await _request(db_client, room, "send", fake)

    assert events[-1] == "done"
    assert _background_dump_lines(dump) == [
        {
            "roomId": str(room.room_id),
            "turn": 30,
            "kind": "background",
            "callSite": "chat_memory_summary",
            "model": settings.gemini_model_name,
            "schema": "MemorySummaryResult",
            "prompt": fake.summary_prompts[0],
            "cursorMessageId": str(room.turns[10][1].id),
        }
    ]


async def test_fold_dump_is_written_even_when_the_summary_call_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """덤프는 호출 앞에서 쓴다 — 실패한 요약의 입력도 남아야 그 실패를 다시 보내 볼 수 있다. 요약이 실패해도 턴은 그대로
    끝나고 스냅샷은 생기지 않는다."""
    dump = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient(LLMClientError("boom"))

    events = await _request(db_client, room, "send", fake)

    assert events == ["token", "done"]
    assert await _snapshots(db_session, room) == []
    assert [line["prompt"] for line in _background_dump_lines(dump)] == fake.summary_prompts
    assert len(fake.summary_prompts) == 1


async def test_failed_dump_write_does_not_change_the_fold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """덤프는 측정용 부가 기록이다 — 쓰다 실패해도 접기는 덤프가 없을 때와 같은 스냅샷을 남긴다."""
    # 디렉터리를 덤프 파일 자리로 주면 추가 모드로 열지 못해 쓰기가 실패한다.
    monkeypatch.setattr(settings, "prompt_dump_path", str(tmp_path))
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient()

    events = await _request(db_client, room, "send", fake)

    assert events[-1] == "done"
    assert len(fake.summary_prompts) == 1
    tenth = room.turns[10][1]
    assert await _snapshots(db_session, room) == [SnapshotRow(tenth.created_at, tenth.id, SUMMARY_TEXT, None, "auto")]
    assert await _memory_version(db_session, room) == 1


async def test_fold_opens_no_file_without_a_dump_path(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """운영은 덤프 경로가 없다 — 접기는 어떤 파일도 추가 모드로 열지 않고 지금처럼 스냅샷만 남긴다."""
    monkeypatch.setattr(settings, "prompt_dump_path", None)
    appended: list[str] = []
    real_open = builtins.open

    def spy_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if "a" in mode:
            appended.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient()

    events = await _request(db_client, room, "send", fake)

    assert events[-1] == "done"
    assert len(fake.summary_prompts) == 1
    assert len(await _snapshots(db_session, room)) == 1
    assert appended == []


async def test_replay_reader_still_picks_the_generation_line_when_a_fold_line_shares_its_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """접기 줄은 그 턴 생성 줄과 방·턴 번호가 같고 그 뒤에 남는다. 리플레이가 덤프에서 고르는 것은 여전히 그 턴의 생성 줄
    하나다 — 접기 줄을 세면 유실 턴의 재시도로 읽고, 고르면 지시문 없는 줄과 대조한다."""
    dump = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    room = await _open_room(db_client, db_session, turns=29)

    await _request(db_client, room, "send", SummaryLLMClient())

    assert [line["turn"] for line in _background_dump_lines(dump)] == [30]
    record, count = replay_logs.dump_record(dump, room.room_id, 30)
    assert (record["kind"], record["turn"], count) == ("generation", 30, 1)


# --- 요약 비밀 표기 슬롯 ------------------------------------------------------------------

_SLOT_HEAD = "[비밀 표기]\n- 이 이야기의 인물 이름: "


async def _plant_fact_snapshot(db_session: AsyncSession, room: Room, *, turn: int, facts: list[dict[str, Any]]) -> None:
    """`turn` 턴까지 접은 스냅샷 하나와 그 접기에서 뽑은 사실 행들을 심는다."""
    assistant = room.turns[turn][1]
    snapshot = ChatRoomMemorySnapshot(
        chat_room_id=room.room_id,
        cursor_created_at=assistant.created_at,
        cursor_message_id=assistant.id,
        summary_text="앞 요약",
        source="auto",
    )
    db_session.add(snapshot)
    await db_session.flush()
    for ordinal, fields in enumerate(facts):
        db_session.add(_make_memory_fact(room.room_id, snapshot.id, ordinal=ordinal, **fields))
    await db_session.commit()


async def _add_media_book_people(db_session: AsyncSession, room: Room, names: list[str]) -> None:
    version_id = await db_session.scalar(sa.select(ChatRoom.content_version_id).where(ChatRoom.id == room.room_id))
    assert version_id is not None
    for order, name in enumerate(names):
        db_session.add(MediaBookPerson(entity_id=uuid.uuid4(), content_version_id=version_id, name=name, order=order))
    await db_session.commit()


async def _story_room_with_names(db_client: httpx.AsyncClient, db_session: AsyncSession) -> Room:
    """미디어 북 인물 둘과, 앞 접기(10턴)의 사실 행이 있는 스토리 방. 커서 뒤가 29턴이라 다음 보내기가 접는다."""
    room = await _open_room(db_client, db_session, turns=39, lane="story")
    await _add_media_book_people(db_session, room, ["한서윤", "Mina"])
    await _plant_fact_snapshot(
        db_session,
        room,
        turn=10,
        facts=[
            {"kind": "relation", "subject": "오태민", "object": "한서윤"},
            {
                "kind": "fact",
                "subject": "MINA",
                "object": None,
                "attribute": "숨긴 일",
                "fact_key": "fact|mina|숨긴 일",
                "speaker": "당신",
                "known_by": ["사용자", "오태민", "지아 "],
            },
        ],
    )
    return room


async def test_secret_marking_switched_off_leaves_the_slot_out_even_with_names(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치가 꺼져 있으면 이름 출처가 있는 방에서도 요약 프롬프트에 슬롯이 없다."""
    monkeypatch.setattr(settings, "memory_summary_secret_marking", False)
    room = await _story_room_with_names(db_client, db_session)
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    (prompt,) = fake.summary_prompts
    assert "[비밀 표기]" not in prompt and "앞 요약" in prompt


async def test_secret_marking_lists_the_story_people_in_their_original_spelling(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스토리 방: 미디어 북 인물(순서대로) → 앞 접기 사실 행의 이름. 처음 나온 표기를 지키고 사용자 표기(대화 줄 라벨,
    `{{user}}` 대체어)는 뺀다. 슬롯은 지시문 바로 뒤, 직전 요약 앞이다."""
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    _memory_scope_covers_gemini(monkeypatch)
    room = await _story_room_with_names(db_client, db_session)
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    (prompt,) = fake.summary_prompts
    assert f"{_SLOT_HEAD}한서윤, Mina, 오태민, 지아. 아는 사람을" in prompt
    assert prompt.index(_SLOT_HEAD) < prompt.index("앞 요약")
    assert len(await _snapshots(db_session, room)) == 2


async def test_secret_marking_names_the_character_in_a_character_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """캐릭터 방의 첫 접기: 사실 행이 아직 없어도 작품(캐릭터) 이름이 실린다."""
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    (prompt,) = fake.summary_prompts
    assert f"{_SLOT_HEAD}캐릭터. 아는 사람을" in prompt


async def test_secret_marking_without_any_name_still_carries_the_slot_on_the_first_fold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """미디어 북 인물이 없는 스토리 방의 첫 접기는 이름이 0개다 — 고정 문구로 슬롯이 실린다."""
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29, lane="story")
    fake = SummaryLLMClient()

    await _request(db_client, room, "send", fake)

    (prompt,) = fake.summary_prompts
    assert f"{_SLOT_HEAD}{NO_ROOM_PEOPLE}. 아는 사람을" in prompt


async def test_secret_marking_name_read_failure_falls_back_and_the_fold_still_commits(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이름 출처를 읽다 DB 가 실패해도 접기는 그대로 커밋한다 — 이름은 이미 손에 있는 작품 이름만으로 채우고, 실패는 승격한다."""
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    _memory_scope_covers_gemini(monkeypatch)
    captured: list[str] = []
    monkeypatch.setattr(memory_fold, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency))

    async def _broken(*args: Any, **kwargs: Any) -> Any:
        raise SQLAlchemyError("이름 출처 읽기 실패")

    monkeypatch.setattr(memory_fold, "_load_name_sources", _broken)
    room = await _open_room(db_client, db_session, turns=29)
    fake = SummaryLLMClient()

    events = await _request(db_client, room, "send", fake)

    assert events[-1] == "done"
    (prompt,) = fake.summary_prompts
    assert f"{_SLOT_HEAD}캐릭터. 아는 사람을" in prompt
    assert captured == ["db"]
    assert len(await _snapshots(db_session, room)) == 1


# --- 비밀 표기 슬롯의 기억 사용 범위 ----------------------------------------------------------


async def _fold_directly(
    db_session: AsyncSession,
    room: Room,
    fake: SummaryLLMClient,
    *,
    summary_model: PromptSetModelId,
    writing_model: ChatModelId,
) -> str:
    """접기를 직접 한 번 부르고 그 요약 프롬프트를 돌려준다. 요약은 실패로 끝내 커서가 그대로라 같은 방을 다시 접을 수 있다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story", model=summary_model)
    await memory_fold.fold_memory(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False),
        fake,
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=True,
        names=PromptNames(persona_name=None, char_name=None),
        writing_model=writing_model,
    )
    return fake.summary_prompts[-1]


async def _named_story_room_due_to_fold(db_client: httpx.AsyncClient, db_session: AsyncSession) -> Room:
    room = await _open_room(db_client, db_session, turns=30, lane="story")
    await _add_media_book_people(db_session, room, ["한서윤", "Mina"])
    return room


async def test_secret_marking_outside_the_scope_leaves_the_summary_prompt_as_if_switched_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기본 범위(Opus 방뿐)에서 Gemini 가 쓴 턴의 접기는 스위치를 켜도 요약 프롬프트가 꺼진 것과 바이트까지 같다. 같은 방의
    Opus 턴이면 슬롯이 실린다."""
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus"), ("character", "opus")])
    room = await _named_story_room_due_to_fold(db_client, db_session)
    fake = SummaryLLMClient(*[LLMClientError("요약 실패")] * 3)

    monkeypatch.setattr(settings, "memory_summary_secret_marking", False)
    switched_off = await _fold_directly(db_session, room, fake, summary_model="gemini", writing_model="gemini")
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    outside = await _fold_directly(db_session, room, fake, summary_model="gemini", writing_model="gemini")
    inside = await _fold_directly(db_session, room, fake, summary_model="gemini", writing_model="opus")

    assert outside == switched_off
    assert _SLOT_HEAD not in outside
    assert f"{_SLOT_HEAD}한서윤, Mina. 아는 사람을" in inside


async def test_secret_marking_in_an_opus_turn_matches_a_scope_that_holds_every_writing_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """범위 제한이 없던 코드는 모든 글쓰기 모델이 범위 안인 것과 같다. Opus 가 쓴 턴의 접기는 기본 범위에서도 그 넓은 범위에서와
    요약 프롬프트가 바이트까지 같다. 스위치를 끈 접기와는 달라야 슬롯이 실제로 실린 채 비교한 것이다."""
    room = await _named_story_room_due_to_fold(db_client, db_session)
    fake = SummaryLLMClient(*[LLMClientError("요약 실패")] * 3)
    every_model = [(lane, model) for lane in ("story", "character") for model in ("gemini", "sonnet", "opus")]

    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus"), ("character", "opus")])
    scoped = await _fold_directly(db_session, room, fake, summary_model="gemini", writing_model="opus")
    monkeypatch.setattr(settings, "memory_model_scope", every_model)
    unscoped = await _fold_directly(db_session, room, fake, summary_model="gemini", writing_model="opus")
    monkeypatch.setattr(settings, "memory_summary_secret_marking", False)
    switched_off = await _fold_directly(db_session, room, fake, summary_model="gemini", writing_model="opus")

    assert scoped == unscoped
    assert scoped != switched_off
    assert f"{_SLOT_HEAD}한서윤, Mina. 아는 사람을" in scoped


@pytest.mark.parametrize(
    ("summary_model", "writing_model", "carried"),
    [
        pytest.param("haiku", "opus", True, id="summary-set-outside-writing-inside"),
        pytest.param("opus", "gemini", False, id="summary-set-inside-writing-outside"),
    ],
)
async def test_secret_marking_scope_is_judged_by_the_writing_model_not_the_summary_set_model(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    summary_model: PromptSetModelId,
    writing_model: ChatModelId,
    carried: bool,
) -> None:
    """접기가 받는 세트는 요약 모델의 것이다. 그 세트의 모델로 가르면 Opus 방의 접기가 범위 밖이 되고 Gemini 방의 접기가 요약
    모델이 Opus 라는 이유로 범위 안이 된다 — 그래서 범위는 그 턴에 응답을 쓴 모델로 가른다."""
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus"), ("character", "opus")])
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    room = await _named_story_room_due_to_fold(db_client, db_session)
    fake = SummaryLLMClient(LLMClientError("요약 실패"))

    prompt = await _fold_directly(db_session, room, fake, summary_model=summary_model, writing_model=writing_model)

    assert (_SLOT_HEAD in prompt) is carried
