"""긴 방의 요약 접기 — 턴이 끝난 뒤 background가 오래된 10턴을 요약 스냅샷으로 접는다.

- 언제 접나: 커서 뒤(오프닝 제외) 턴이 30이 되면, 또는 원문이 24,000자 이상이고 접은 뒤 10턴이
  남으면. 접기는 새 턴을 만드는 send·edit 뒤에만 돈다(재생성은 턴 수를 바꾸지 않는다).
- 무엇이 남나: 커서 = 접은 10번째 응답의 키, 본문 ≤ 1,500자, `source="auto"`, 되돌리기 버퍼 없음.
- 실패하면: 사용자에게 보이는 것 없이 흡수하고 커서는 그대로 — 다음 턴 뒤 다시 시도한다. 연속
  실패가 쌓이면 몇 턴 쉬었다 시도한다.
- 그사이 기억이 바뀌면(버전이 달라지면) 결과를 버린다.
- 노트·스탯·계정 정보는 요약 입력에 없고, 접기는 노트를 건드리지 않으며, 클로버·레이트리밋과
  무관하다.

httpx `ASGITransport`는 background까지 끝난 뒤 응답을 돌려주므로 요청 뒤 단언 시점에 접기가 이미
끝나 있다. 단언은 컬럼 단위 `select()`로 한다(요청과 같은 세션의 identity map에 속지 않게).
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold
from api.chat.memory_fold import backoff_allows, plan_fold
from api.chat.prompt_builder import MemorySummaryResult, StatJudgmentResult
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models import (
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    CloverLedger,
    User,
)
from api.db.session import get_session_factory
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
    _make_user,
    _make_user_with_clover_lot,
    _memory_version,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _plant_snapshot,
    _snapshots,
)

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
        if response_schema is StatJudgmentResult:
            return StatJudgmentResult(stat_changes=[])
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


async def test_regenerate_does_not_fold(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=30)
    fake = SummaryLLMClient()

    await _request(db_client, room, "regenerate", fake)

    assert fake.summary_prompts == []
    assert await _snapshots(db_session, room) == []


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
        start_balance - clover.CHAT_TURN_COST
    )
    ledger = (
        await db_session.execute(
            sa.select(CloverLedger.kind, CloverLedger.amount).where(CloverLedger.user_id == user.id)
        )
    ).all()
    assert [tuple(row) for row in ledger] == [("chat_spend", -clover.CHAT_TURN_COST)]
    counters = [await redis_client.get(key) for key in await redis_client.keys(f"rate_limit:*{user.id}*")]
    assert counters and all(value == "1" for value in counters)
