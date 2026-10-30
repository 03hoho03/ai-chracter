"""요약 접기가 접은 대화 구간을 관계·사실 기억으로 뽑는다.

- 언제: 스위치(`memory_facts_extract`)가 켜져 있고 생성 윈도우가 켜져 있을 때, 턴 뒤 접기·장면 추출 예약 **뒤에** 따로
  예약한다. 꺼져 있으면 예약하지 않는다(턴의 호출·트랜잭션이 스위치가 생기기 전과 같다). background 는 차례로 돌고 한 태스크가
  예외를 내면 뒤 태스크가 돌지 않으므로, 추출은 어떤 예외도 밖으로 내지 않는다.
- 무엇을: 사실 추출 기록이 끝나지 않은 스냅샷 중 커서가 가장 오래된 것 하나. 창은 직전 스냅샷 커서 다음부터 그 스냅샷
  커서까지(오프닝 제외)이고, 그 스냅샷 **앞** 스냅샷들에서 뽑은 사실을 키마다 최신 하나로 줄인 기존 키 목록(최근 40줄)을
  함께 싣는다. 줄 꼴과 "키마다 최신" 규칙은 평가 하네스와 같다 — 반증된 값은 뒤의 같은 값 주장으로 되살아나지 않는다.
- 결과: 서버가 주어·값이 빈 행을 버리고 앞 20개만 남긴 뒤 키를 만들고(종류·주어·대상 또는 속성을 NFC·casefold·공백 한 칸으로
  맞춰 `|` 로 잇는다) 칸을 DB 상한에서 자른다. 아는 사람 목록의 빈 이름은 버리고, 비면 NULL 이다.
- 실패: 호출·렌더·파싱·제약 위반·DB 오류는 실패 기록이 되고 세 번까지 다시 쥔다. 스냅샷이 그사이 지워진 것은 실패가 아니다.

추출 함수를 직접 부르는 테스트는 세션마다 SAVEPOINT 를 여는 팩토리를 쓴다(장면 추출 테스트와 같은 이유). 진짜 두 세션의
경합은 `test_chat_memory_rewind.py` 의 커밋되는 독립 커넥션 절에 있다.
"""

import json
import unicodedata
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_facts
from api.chat.memory_facts import extract_pending_facts
from api.chat.prompt_builder import (
    MemoryEpisodeResult,
    MemoryFactItem,
    MemoryFactResult,
    MemorySummaryResult,
    PromptLane,
    PromptNames,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.core.config import settings
from api.db.models import ChatMemoryFact, ChatMemoryFactExtraction, ChatRoomMemorySnapshot
from api.db.models.chat import FACT_KEY_MAX, FACT_KNOWN_BY_MAX, FACT_NAME_MAX, FACT_PER_SNAPSHOT_MAX, FACT_VALUE_MAX
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, collect_usage
from factories import (
    PRODUCTION_ENV_NAMES,
    Room,
    _clear_llm_override,
    _make_memory_fact,
    _make_memory_fact_extraction,
    _open_room,
    _open_transaction_probe,
    _override_llm_client,
    _parse_sse_events,
    _plant_snapshot,
    load_production_env,
)

FactOutcome = MemoryFactResult | Exception | Callable[[], Awaitable[MemoryFactResult]]


def _fact(**overrides: Any) -> MemoryFactItem:
    values: dict[str, Any] = {
        "kind": "relation",
        "subject": "민수",
        "object": "지아",
        "attribute": "",
        "value": "소꿉친구",
        "truth_status": "confirmed",
        "asserted_by": "user",
        "speaker": "",
        "known_by": [],
        "importance": 3,
        "start_line": 1,
        "end_line": 2,
    }
    values.update(overrides)
    return MemoryFactItem(**values)


def _result(*items: MemoryFactItem) -> MemoryFactResult:
    return MemoryFactResult(facts=list(items))


class FactLLMClient(LLMClient):
    """생성은 고정 응답, 요약은 고정 본문, 스탯 판정은 변화 없음, 장면 추출은 빈 결과. 사실 추출에는 `outcomes` 를 차례로
    준다(결과는 그대로, 예외는 raise, 콜러블은 불러서 그 결과를 — 호출 도중의 경합을 흉내 낸다). 다 쓰면 사실 하나짜리 기본
    결과다. `usage_metadata` 가 있으면 그 사용량을 호출의 `usage_sink` 에 더한다(공급자 구현이 하는 일과 같다).
    `open_sessions` 가 있으면 사실 추출 호출 순간 열린 루트 트랜잭션 수를 적는다."""

    def __init__(
        self,
        *outcomes: FactOutcome,
        usage_metadata: object | None = None,
        open_sessions: set[int] | None = None,
    ) -> None:
        self.outcomes = list(outcomes)
        self.usage_metadata = usage_metadata
        self.open_sessions = open_sessions
        self.fact_prompts: list[str] = []
        self.fact_usages: list[LLMCallContext] = []
        self.open_at_call: list[int] = []

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
        if response_schema is MemorySummaryResult:
            return MemorySummaryResult(summary="[SUMMARY] 요약")
        if response_schema is MemoryEpisodeResult:
            return MemoryEpisodeResult(episodes=[])
        assert response_schema is MemoryFactResult, response_schema
        self.fact_prompts.append(prompt)
        self.fact_usages.append(usage)
        if self.open_sessions is not None:
            self.open_at_call.append(len(self.open_sessions))
        if self.usage_metadata is not None:
            collect_usage(usage, "claude-haiku-5-5", self.usage_metadata)
        outcome = self.outcomes.pop(0) if self.outcomes else _result(_fact())
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


def _savepoint_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _extract_kwargs(db_session: AsyncSession, room: Room, *, lane: PromptLane = "character") -> dict[str, Any]:
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    return {
        "room_id": room.room_id,
        "user_id": room.user_id,
        "prompt_set": prompt_set,
        "sections": sections,
        "is_story_chat": lane == "story",
        "names": PromptNames(persona_name=None, char_name=None),
    }


async def _extract(db_session: AsyncSession, room: Room, llm: LLMClient, *, lane: PromptLane = "character") -> None:
    await extract_pending_facts(
        _savepoint_factory(db_session), llm, **await _extract_kwargs(db_session, room, lane=lane)
    )


async def _snapshot_id(db_session: AsyncSession, room: Room, turn: int) -> uuid.UUID:
    assistant = room.turns[turn][1]
    snapshot_id = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.id).where(
            ChatRoomMemorySnapshot.chat_room_id == room.room_id,
            ChatRoomMemorySnapshot.cursor_message_id == assistant.id,
        )
    )
    assert snapshot_id is not None
    return snapshot_id


async def _plant(db_session: AsyncSession, room: Room, turn: int, *, extracted: bool = False) -> uuid.UUID:
    """턴 `turn` 의 응답을 커서로 둔 스냅샷을 심는다. `extracted` 면 그 스냅샷의 사실 추출이 끝난 기록도 함께."""
    await _plant_snapshot(db_session, room, turn=turn, text=f"[S{turn}]")
    snapshot_id = await _snapshot_id(db_session, room, turn)
    if extracted:
        db_session.add(_make_memory_fact_extraction(room.room_id, snapshot_id, fact_count=0))
        await db_session.commit()
    return snapshot_id


# (종류, 주어, 대상 또는 속성, 값, 진실 상태). 이름은 이미 정규형(소문자·한 칸 공백)이라 키는 그대로 `|` 로 이은 것이다.
PriorFact = tuple[str, str, str, str, str]


async def _plant_prior_facts(
    db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID, facts: list[PriorFact]
) -> None:
    for ordinal, (kind, subject, target, value, status) in enumerate(facts):
        db_session.add(
            _make_memory_fact(
                room.room_id,
                snapshot_id,
                ordinal=ordinal,
                kind=kind,
                subject=subject,
                object=target if kind == "relation" else None,
                attribute=None if kind == "relation" else target,
                fact_key=f"{kind}|{subject}|{target}",
                value=value,
                truth_status=status,
            )
        )
    await db_session.commit()


async def _facts(db_session: AsyncSession, room: Room) -> list[Any]:
    return list(
        (
            await db_session.execute(
                sa.select(
                    ChatMemoryFact.snapshot_id,
                    ChatMemoryFact.chat_room_id,
                    ChatMemoryFact.ordinal,
                    ChatMemoryFact.kind,
                    ChatMemoryFact.subject,
                    ChatMemoryFact.object,
                    ChatMemoryFact.attribute,
                    ChatMemoryFact.fact_key,
                    ChatMemoryFact.value,
                    ChatMemoryFact.truth_status,
                    ChatMemoryFact.asserted_by,
                    ChatMemoryFact.speaker,
                    ChatMemoryFact.known_by,
                    ChatMemoryFact.importance,
                    ChatMemoryFact.start_message_id,
                    ChatMemoryFact.end_message_id,
                    ChatMemoryFact.start_turn,
                    ChatMemoryFact.end_turn,
                )
                .join(ChatRoomMemorySnapshot, ChatRoomMemorySnapshot.id == ChatMemoryFact.snapshot_id)
                .where(ChatMemoryFact.chat_room_id == room.room_id)
                .order_by(
                    ChatRoomMemorySnapshot.cursor_created_at,
                    ChatRoomMemorySnapshot.cursor_message_id,
                    ChatMemoryFact.ordinal,
                )
            )
        ).all()
    )


async def _extracted_facts(db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID) -> list[Any]:
    return [row for row in await _facts(db_session, room) if row.snapshot_id == snapshot_id]


async def _extractions(db_session: AsyncSession, room: Room) -> list[Any]:
    return list(
        (
            await db_session.execute(
                sa.select(
                    ChatMemoryFactExtraction.snapshot_id,
                    ChatMemoryFactExtraction.chat_room_id,
                    ChatMemoryFactExtraction.status,
                    ChatMemoryFactExtraction.attempts,
                    ChatMemoryFactExtraction.fact_count,
                    ChatMemoryFactExtraction.claimed_at,
                    ChatMemoryFactExtraction.finished_at,
                    ChatMemoryFactExtraction.model,
                    ChatMemoryFactExtraction.prompt_tokens,
                    ChatMemoryFactExtraction.cached_tokens,
                    ChatMemoryFactExtraction.output_tokens,
                    ChatMemoryFactExtraction.thoughts_tokens,
                ).where(ChatMemoryFactExtraction.chat_room_id == room.room_id)
            )
        ).all()
    )


def _capture_failures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(
        memory_facts, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    return captured


def _existing_lines(prompt: str) -> list[str]:
    """프롬프트의 기존 키 섹션 줄. 섹션은 `[기존 키]` 머리글 줄 다음부터 빈 줄(다음 섹션)까지다."""
    return prompt.rsplit("[기존 키]\n", 1)[1].split("\n\n", 1)[0].splitlines()


def _numbered(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("[") and line.split("]", 1)[0][1:].isdigit()]


# --- 예약 ---------------------------------------------------------------------------------


async def _send(db_client: httpx.AsyncClient, room: Room, fake: LLMClient) -> list[str]:
    _override_llm_client(fake)
    try:
        response = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    return [event["type"] for event in _parse_sse_events(response.text)]


def _record_scheduling(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    scheduled: list[str] = []
    original_add_task = BackgroundTasks.add_task

    def _recording_add_task(self: BackgroundTasks, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        scheduled.append(func.__name__)
        original_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", _recording_add_task)
    return scheduled


async def test_fact_extraction_is_not_scheduled_when_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.memory_facts_extract is False
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29, paid_turns=1)
    fake = FactLLMClient()

    assert await _send(db_client, room, fake) == ["token", "done"]

    assert scheduled == ["fold_memory"]
    assert fake.fact_prompts == []
    assert await _facts(db_session, room) == []
    assert await _extractions(db_session, room) == []


@pytest.mark.parametrize("lane", ["character", "story"])
async def test_fact_extraction_runs_after_the_fold_and_the_scene_extraction(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: str
) -> None:
    """두 추출 스위치가 다 켜져 있으면 접기 → 장면 추출 → 사실 추출 순서로 예약된다. 사실 추출은 접기가 같은 턴에 커밋한
    스냅샷을 바로 보고, LLM 을 기다리는 동안 DB 커넥션을 쥐지 않는다."""
    monkeypatch.setattr(settings, "memory_episodes_extract", True)
    monkeypatch.setattr(settings, "memory_facts_extract", True)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29, lane=lane, paid_turns=1)
    await db_session.commit()

    with _open_transaction_probe() as open_sessions:
        fake = FactLLMClient(_result(_fact(start_line=3, end_line=20)), open_sessions=open_sessions)
        events = await _send(db_client, room, fake)

    assert events[-1] == "done"
    assert scheduled == ["fold_memory", "extract_pending_episode", "extract_pending_facts"]
    assert len(fake.fact_prompts) == 1
    assert fake.open_at_call == [0]
    usage = fake.fact_usages[0]
    assert (usage.call_site, usage.room_id, usage.user_id) == ("chat_memory_fact", room.room_id, room.user_id)
    prompt = fake.fact_prompts[0]
    assert "[1] " in prompt and "[U01]" in prompt and "[A10]" in prompt
    assert "[U11]" not in prompt
    assert _existing_lines(prompt) == ["(없음)"]
    snapshot_id = await _snapshot_id(db_session, room, 10)
    facts = await _facts(db_session, room)
    assert [(row.snapshot_id, row.chat_room_id) for row in facts] == [(snapshot_id, room.room_id)]
    assert (facts[0].start_message_id, facts[0].end_message_id) == (room.turns[2][0].id, room.turns[10][1].id)
    assert (facts[0].start_turn, facts[0].end_turn) == (2, 10)
    extractions = await _extractions(db_session, room)
    assert [
        (row.snapshot_id, row.chat_room_id, row.status, row.attempts, row.fact_count) for row in extractions
    ] == [(snapshot_id, room.room_id, "done", 1, 1)]
    assert extractions[0].finished_at is not None


async def test_fact_extraction_alone_is_scheduled_right_after_the_fold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 스위치는 따로다 — 장면 추출이 꺼져 있어도 사실 추출만 켤 수 있다."""
    assert settings.memory_episodes_extract is False
    monkeypatch.setattr(settings, "memory_facts_extract", True)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29, paid_turns=1)
    fake = FactLLMClient()

    await _send(db_client, room, fake)

    assert scheduled == ["fold_memory", "extract_pending_facts"]
    assert len(fake.fact_prompts) == 1
    assert [row.status for row in await _extractions(db_session, room)] == ["done"]


async def test_fact_extraction_follows_the_generation_window_switch(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """생성 윈도우가 꺼져 있으면 접기가 없다 — 사실 추출 스위치가 켜져 있어도 추출도 예약하지 않는다."""
    monkeypatch.setattr(settings, "memory_facts_extract", True)
    monkeypatch.setattr(settings, "memory_window_generation", False)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29, paid_turns=1)

    await _send(db_client, room, FactLLMClient())

    assert scheduled == []
    assert await _extractions(db_session, room) == []


# --- 예외를 밖으로 내지 않는다 ------------------------------------------------------------------
#
# 사실 추출은 background 의 마지막 태스크지만, 뒤에 태스크가 더 붙어도 그 태스크가 돌아야 한다 — Starlette 는 태스크를 차례로
# 부르고 한 태스크가 예외를 내면 남은 태스크를 부르지 않는다.


async def test_an_unexpected_error_stays_inside_and_later_background_tasks_still_run(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    ran: list[str] = []

    async def _a_later_task() -> None:
        ran.append("later")

    tasks = BackgroundTasks()
    tasks.add_task(
        extract_pending_facts,
        _savepoint_factory(db_session),
        FactLLMClient(RuntimeError("예상하지 못한 오류")),
        **await _extract_kwargs(db_session, room),
    )
    tasks.add_task(_a_later_task)
    await tasks()

    assert ran == ["later"]
    assert captured == ["memory_fact"]
    assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("failed", 1)]


async def test_a_database_error_in_the_last_transaction_counts_as_a_failed_attempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """마지막 트랜잭션의 첫 문장이 DB 오류로 깨진다 — 함수는 그대로 돌아오고, 실패 기록은 새 세션으로 남는다."""
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)

    async def _statement_fails(session: AsyncSession, *args: Any, **kwargs: Any) -> bool:
        await session.execute(sa.text("SELECT 1/0"))
        return True

    monkeypatch.setattr(memory_facts, "_lock_snapshot", _statement_fails)
    fake = FactLLMClient()

    await _extract(db_session, room, fake)

    assert len(fake.fact_prompts) == 1
    assert captured == ["db"]
    assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("failed", 1)]
    assert await _facts(db_session, room) == []


# --- 창·입력 ----------------------------------------------------------------------------------


async def test_fact_window_starts_after_previous_snapshot_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """창은 직전 스냅샷 커서 다음부터다. 줄 번호는 1~n 으로 맞추고 뒤집혔으면 맞바꾼 뒤 메시지 키·턴으로 바꾼다."""
    room = await _open_room(db_client, db_session, turns=20)
    await _plant(db_session, room, 10, extracted=True)
    second = await _plant(db_session, room, 20)
    fake = FactLLMClient(
        _result(
            _fact(subject="가", start_line=1, end_line=20),
            _fact(subject="나", start_line=4, end_line=3),
            _fact(subject="다", start_line=0, end_line=99),
        )
    )

    await _extract(db_session, room, fake)

    numbered = _numbered(fake.fact_prompts[0])
    assert len(numbered) == 20
    assert numbered[0].startswith("[1] ") and "[U11]" in numbered[0]
    assert numbered[-1].startswith("[20] ") and "[A20]" in numbered[-1]
    assert not any("[A10]" in line or "[U10]" in line for line in fake.fact_prompts[0].splitlines())
    assert [
        (row.snapshot_id, row.start_message_id, row.end_message_id, row.start_turn, row.end_turn)
        for row in await _facts(db_session, room)
    ] == [
        (second, room.turns[11][0].id, room.turns[20][1].id, 11, 20),
        (second, room.turns[12][0].id, room.turns[12][1].id, 12, 12),
        (second, room.turns[11][0].id, room.turns[20][1].id, 11, 20),
    ]


async def test_first_window_sends_an_empty_existing_key_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    fake = FactLLMClient()

    await _extract(db_session, room, fake)

    assert _existing_lines(fake.fact_prompts[0]) == ["(없음)"]
    assert "[U01]" in fake.fact_prompts[0]


async def test_existing_keys_come_from_earlier_snapshots_only_latest_per_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기존 키 목록은 추출할 스냅샷보다 커서가 앞인 스냅샷의 사실만 싣는다 — 뒤 스냅샷의 사실은 이 구간 시점에 아직 일어나지
    않은 일이다. 같은 키는 마지막 행 하나로 줄이고, 줄은 이긴 행이 쓰인 순서다. 반증된 값을 뒤에서 같은 값으로 다시 주장해도
    반증 행이 이긴다(평가 하네스의 규칙)."""
    room = await _open_room(db_client, db_session, turns=40)
    first = await _plant(db_session, room, 10, extracted=True)
    await _plant_prior_facts(
        db_session,
        room,
        first,
        [
            ("relation", "민수", "지아", "소꿉친구", "confirmed"),
            ("fact", "민수", "생일", "3월", "claimed"),
            ("fact", "지아", "직업", "학생", "disproved"),
        ],
    )
    second = await _plant(db_session, room, 20, extracted=True)
    await _plant_prior_facts(
        db_session,
        room,
        second,
        [
            ("relation", "민수", "지아", "연인", "confirmed"),
            ("fact", "지아", "직업", "학생", "claimed"),
        ],
    )
    pending = await _plant(db_session, room, 30)
    later = await _plant(db_session, room, 40, extracted=True)
    await _plant_prior_facts(db_session, room, later, [("fact", "민수", "미래", "[LATER]", "confirmed")])
    fake = FactLLMClient()

    await _extract(db_session, room, fake)

    assert _existing_lines(fake.fact_prompts[0]) == [
        "fact|민수|생일 = 3월 (claimed)",
        "fact|지아|직업 = 학생 (disproved)",
        "relation|민수|지아 = 연인 (confirmed)",
    ]
    assert "[LATER]" not in fake.fact_prompts[0]
    assert {row.snapshot_id for row in await _extractions(db_session, room)} == {first, second, pending, later}


async def test_existing_keys_keep_the_most_recent_forty(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=40)
    counts = {10: FACT_PER_SNAPSHOT_MAX, 20: FACT_PER_SNAPSHOT_MAX, 30: 5}
    for turn, count in counts.items():
        snapshot_id = await _plant(db_session, room, turn, extracted=True)
        await _plant_prior_facts(
            db_session,
            room,
            snapshot_id,
            [("fact", f"인물{turn}-{i}", "속성", f"값{turn}-{i}", "confirmed") for i in range(count)],
        )
    await _plant(db_session, room, 40)
    fake = FactLLMClient()

    await _extract(db_session, room, fake)

    expected = [
        f"fact|인물{turn}-{i}|속성 = 값{turn}-{i} (confirmed)" for turn, count in counts.items() for i in range(count)
    ][-40:]
    assert len(expected) == 40 and expected[0] == "fact|인물10-5|속성 = 값10-5 (confirmed)"
    assert _existing_lines(fake.fact_prompts[0]) == expected


async def test_oldest_pending_snapshot_is_extracted_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    first = await _plant(db_session, room, 10)
    second = await _plant(db_session, room, 20)
    fake = FactLLMClient()

    await _extract(db_session, room, fake)
    assert [row.snapshot_id for row in await _extractions(db_session, room)] == [first]
    assert "[U01]" in fake.fact_prompts[0] and "[U11]" not in fake.fact_prompts[0]

    await _extract(db_session, room, fake)
    assert {row.snapshot_id for row in await _extractions(db_session, room)} == {first, second}
    assert "[U11]" in fake.fact_prompts[1] and "[A10]" not in fake.fact_prompts[1]

    await _extract(db_session, room, fake)
    assert len(fake.fact_prompts) == 2


def test_fact_module_never_touches_notes_stats_scenes_or_deletes_facts() -> None:
    """추출 경로는 노트·스탯·작가 정본·장면 테이블을 읽거나 쓰는 문장을 갖지 않고, 사실 행을 직접 지우지 않는다(사실은 스냅샷
    DELETE 의 CASCADE 로만 사라진다 — 추출이 따로 지우면 되감기와 교착할 순서가 생긴다). 이 모듈이 사실 테이블을 실제로
    다루는지도 함께 본다 — 빈 모듈이면 아래 부재 검사가 아무것도 말하지 못한다."""
    assert memory_facts.__file__ is not None
    source = Path(memory_facts.__file__).read_text(encoding="utf-8")
    assert "ChatMemoryFactExtraction" in source and "ChatMemoryFact(" in source
    for name in (
        "memory_note",
        "ChatRoomStat",
        "chat_room_stats",
        "VersionDetail",
        "ChatMemoryEpisode",
        "chat_memory_episodes",
        "ChatMemoryExtraction",
        "chat_memory_extractions",
    ):
        assert name not in source, name
    assert "delete(" not in source
    assert "DELETE FROM" not in source.upper()


# --- 정규화 -----------------------------------------------------------------------------------


async def _extract_one(db_session: AsyncSession, room: Room, *items: MemoryFactItem) -> list[Any]:
    snapshot_id = await _plant(db_session, room, 10)
    await _extract(db_session, room, FactLLMClient(_result(*items)))
    assert [row.status for row in await _extractions(db_session, room)] == ["done"]
    return await _extracted_facts(db_session, room, snapshot_id)


async def test_fact_keys_are_normalized_like_the_evaluation_harness(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """키 = 종류 | 주어 | (관계는 대상, 사실은 속성). 칸마다 NFC·casefold 뒤 공백을 한 칸으로 줄이고 앞뒤를 지운다. 저장 칸은
    앞뒤만 지운다. 종류에 맞지 않는 칸(관계의 속성·사실의 대상)과 빈 화자는 NULL 이다."""
    room = await _open_room(db_client, db_session, turns=10)
    nfd_name = unicodedata.normalize("NFD", "지아")

    rows = await _extract_one(
        db_session,
        room,
        _fact(kind="relation", subject="  Min   SU ", object=" JI  A", attribute="버려진다", speaker="  "),
        _fact(kind="fact", subject=nfd_name, object="버려진다", attribute=" 생일 ", value="3월", speaker=" 민수 "),
    )

    assert [(row.kind, row.fact_key, row.subject, row.object, row.attribute, row.speaker) for row in rows] == [
        ("relation", "relation|min su|ji a", "Min   SU", "JI  A", None, None),
        ("fact", "fact|지아|생일", nfd_name, None, "생일", "민수"),
    ]


_CUT_CASES = [
    pytest.param(column, limit, given, id=f"{column}-{'at-limit' if given == limit else 'one-over'}")
    for column, limit in (
        ("subject", FACT_NAME_MAX),
        ("object", FACT_NAME_MAX),
        ("attribute", FACT_NAME_MAX),
        ("speaker", FACT_NAME_MAX),
        ("value", FACT_VALUE_MAX),
    )
    for given in (limit, limit + 1)
]


@pytest.mark.parametrize(("column", "limit", "given"), _CUT_CASES)
async def test_fact_columns_are_cut_at_their_limits(
    db_client: httpx.AsyncClient, db_session: AsyncSession, column: str, limit: int, given: int
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    kind = "fact" if column == "attribute" else "relation"
    item = _fact(kind=kind, attribute="속성" if kind == "fact" else "", object="" if kind == "fact" else "지아")
    item = item.model_copy(update={column: "가" * given})

    rows = await _extract_one(db_session, room, item)

    assert [getattr(row, column) for row in rows] == ["가" * min(given, limit)]


@pytest.mark.parametrize("attribute_length", [97, 98], ids=["key-at-limit", "key-one-over"])
async def test_the_fact_key_is_cut_at_its_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, attribute_length: int
) -> None:
    """키는 자르기 전 칸으로 만든 뒤 키 상한에서 자른다 — 칸 상한만큼 자른 주어로 키를 만들면 앞부분이 같은 두 이름이 한 키로
    묶인다. 여기서 키 길이는 `fact|`(5) + 주어 97 + `|`(1) + 속성 = 200 또는 201 이다."""
    room = await _open_room(db_client, db_session, turns=10)
    subject, attribute = "가" * 97, "나" * attribute_length
    full_key = f"fact|{subject}|{attribute}"
    assert len(full_key) == FACT_KEY_MAX + attribute_length - 97

    rows = await _extract_one(db_session, room, _fact(kind="fact", subject=subject, object="", attribute=attribute))

    assert [(row.fact_key, row.subject, row.attribute) for row in rows] == [
        (full_key[:FACT_KEY_MAX], subject[:FACT_NAME_MAX], attribute[:FACT_NAME_MAX])
    ]


async def test_known_by_drops_blank_names_cuts_each_name_and_caps_the_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """빈 이름은 상한을 세기 전에 버린다 — 빈 이름이 자리를 먹으면 뒤의 진짜 이름이 잘린다. 다 비면 NULL 이다(빈 배열은
    "공개·불명"과 같은 뜻이라 쓰지 않는다)."""
    room = await _open_room(db_client, db_session, turns=10)
    many = [f"인물{i}" for i in range(FACT_KNOWN_BY_MAX + 1)]

    rows = await _extract_one(
        db_session,
        room,
        _fact(subject="가", known_by=["", "  ", " 지아 "]),
        _fact(subject="나", known_by=["", " "]),
        _fact(subject="다", known_by=["", "", *many]),
        _fact(subject="라", known_by=["가" * FACT_NAME_MAX, "나" * (FACT_NAME_MAX + 1)]),
    )

    assert [row.known_by for row in rows] == [
        ["지아"],
        None,
        many[:FACT_KNOWN_BY_MAX],
        ["가" * FACT_NAME_MAX, "나" * FACT_NAME_MAX],
    ]


async def test_blank_facts_are_dropped_before_keeping_the_first_twenty(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """주어·값이 빈 행, 대상이 빈 관계, 속성이 빈 사실은 먼저 버린다 — 넣으면 CHECK 에 걸려 구간 전체가 실패하고, 상한을 센 뒤에
    버리면 빈 행이 자리를 먹어 구간 뒤쪽 사실이 잘린다. 순번은 남은 행의 0부터다."""
    room = await _open_room(db_client, db_session, turns=10)
    items = [
        _fact(subject="  "),
        _fact(subject="가", value=" "),
        _fact(kind="relation", subject="나", object=" ", attribute="속성"),
        _fact(kind="fact", subject="다", object="지아", attribute=""),
        *(_fact(subject=f"인물{i}") for i in range(FACT_PER_SNAPSHOT_MAX + 1)),
    ]

    rows = await _extract_one(db_session, room, *items)

    assert [(row.ordinal, row.subject) for row in rows] == [(i, f"인물{i}") for i in range(FACT_PER_SNAPSHOT_MAX)]
    assert [row.fact_count for row in await _extractions(db_session, room)] == [FACT_PER_SNAPSHOT_MAX]


async def test_importance_is_clamped_to_one_through_five(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)

    rows = await _extract_one(
        db_session, room, *(_fact(subject=f"인물{given}", importance=given) for given in (0, 1, 5, 6))
    )

    assert [row.importance for row in rows] == [1, 1, 5, 5]


# --- 결과·실패 ------------------------------------------------------------------------------


async def test_empty_fact_list_marks_extraction_done(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    await _extract(db_session, room, FactLLMClient(_result()))

    assert await _facts(db_session, room) == []
    assert [(row.snapshot_id, row.status, row.fact_count) for row in await _extractions(db_session, room)] == [
        (snapshot_id, "done", 0)
    ]


async def test_failed_fact_extraction_retries_up_to_three_times(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    fake = FactLLMClient(*(LLMClientError("boom") for _ in range(3)))

    for attempt in range(1, 4):
        await _extract(db_session, room, fake)
        assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("failed", attempt)]

    await _extract(db_session, room, fake)

    assert len(fake.fact_prompts) == 3
    assert captured == ["gemini"] * 3
    assert await _facts(db_session, room) == []


async def test_check_violation_counts_as_failed_attempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정규화를 지나고도 CHECK 에 걸리면(정규화의 결함) 경합이 아니라 실패다 — 무한히 다시 쥐지 않고 시도를 센다. 그런 결함을
    흉내 내려고 이 테스트 트랜잭션 안에서만 사는 CHECK 를 하나 더 건다(테스트가 끝나면 롤백으로 사라진다)."""
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    await db_session.execute(
        sa.text("ALTER TABLE chat_memory_facts ADD CONSTRAINT ck_test_rejects_marked_value CHECK (value <> '[거부]')")
    )

    await _extract(db_session, room, FactLLMClient(_result(_fact(value="[거부]"))))

    assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("failed", 1)]
    assert captured == ["db"]
    assert await _facts(db_session, room) == []

    await _extract(db_session, room, FactLLMClient())

    assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("done", 2)]


async def test_fact_extraction_records_token_usage(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    metadata = SimpleNamespace(
        prompt_token_count=5_000, cached_content_token_count=1_200, candidates_token_count=900, thoughts_token_count=0
    )

    await _extract(db_session, room, FactLLMClient(usage_metadata=metadata))

    rows = await _extractions(db_session, room)
    assert [
        (row.model, row.prompt_tokens, row.cached_tokens, row.output_tokens, row.thoughts_tokens) for row in rows
    ] == [("claude-haiku-5-5", 5_000, 1_200, 900, 0)]


async def test_a_failed_attempt_keeps_the_tokens_it_spent(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """응답을 받고 나서 실패한 시도(파싱 실패 등)도 토큰을 썼다 — 실패 기록에 남기고, 다시 쥔 시도의 토큰은 더한다."""
    _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    metadata = SimpleNamespace(
        prompt_token_count=1_000, cached_content_token_count=100, candidates_token_count=300, thoughts_token_count=0
    )
    fake = FactLLMClient(LLMClientError("parse"), usage_metadata=metadata)

    await _extract(db_session, room, fake)

    rows = await _extractions(db_session, room)
    assert [(row.status, row.model, row.prompt_tokens, row.output_tokens) for row in rows] == [
        ("failed", "claude-haiku-5-5", 1_000, 300)
    ]

    await _extract(db_session, room, fake)

    rows = await _extractions(db_session, room)
    assert [(row.status, row.attempts, row.prompt_tokens, row.cached_tokens, row.output_tokens) for row in rows] == [
        ("done", 2, 2_000, 200, 600)
    ]


async def test_summary_edit_does_not_discard_fact_extraction(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약 편집은 스냅샷을 제자리에서 고치고 기억 버전을 올리지만 창 원문은 그대로다 — 추출은 버리지 않는다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    async def _user_edits_the_summary() -> MemoryFactResult:
        response = await db_client.put(
            f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "[EDITED]", "version": 0}
        )
        assert response.status_code == 200, response.text
        return _result(_fact())

    await _extract(db_session, room, FactLLMClient(_user_edits_the_summary))

    assert (
        await db_session.scalar(
            sa.select(ChatRoomMemorySnapshot.summary_text).where(ChatRoomMemorySnapshot.id == snapshot_id)
        )
        == "[EDITED]"
    )
    assert [row.snapshot_id for row in await _facts(db_session, room)] == [snapshot_id]
    assert [row.status for row in await _extractions(db_session, room)] == ["done"]


@pytest.mark.parametrize(
    ("status", "minutes_ago", "attempts", "retaken"),
    [
        pytest.param("running", 11, 1, True, id="stale-running"),
        pytest.param("running", 11, 2, True, id="stale-running-second-attempt"),
        pytest.param("running", 11, 3, False, id="stale-running-at-the-attempt-limit"),
        pytest.param("running", 9, 1, False, id="fresh-running"),
        pytest.param("failed", 0, 2, True, id="failed-twice"),
        pytest.param("failed", 0, 3, False, id="failed-three-times"),
        pytest.param("done", 30, 1, False, id="done"),
    ],
)
async def test_stale_running_claim_is_retaken_within_attempt_limit(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    status: str,
    minutes_ago: int,
    attempts: int,
    retaken: bool,
) -> None:
    """작업이 죽어(배포 교체) `running` 이 남으면 10분 뒤 다음 작업이 다시 쥔다. 실패도 다시 쥔다. 어느 쪽이든 시도는 세 번까지다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    db_session.add(
        _make_memory_fact_extraction(
            room.room_id,
            snapshot_id,
            status=status,
            attempts=attempts,
            claimed_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            fact_count=1 if status == "done" else None,
        )
    )
    await db_session.commit()
    fake = FactLLMClient()

    await _extract(db_session, room, fake)

    assert len(fake.fact_prompts) == (1 if retaken else 0)
    rows = await _extractions(db_session, room)
    if retaken:
        assert [(row.status, row.attempts) for row in rows] == [("done", attempts + 1)]
    else:
        assert [(row.status, row.attempts) for row in rows] == [(status, attempts)]


async def _supersede_claim(db_session: AsyncSession, snapshot_id: uuid.UUID) -> None:
    """다른 작업이 낡은 선점을 다시 쥔 상태 — 선점 시각이 새것으로 바뀌고 시도가 하나 늘었다."""
    await db_session.execute(
        sa.update(ChatMemoryFactExtraction)
        .where(ChatMemoryFactExtraction.snapshot_id == snapshot_id)
        .values(claimed_at=sa.func.clock_timestamp(), attempts=ChatMemoryFactExtraction.attempts + 1)
    )
    await db_session.commit()


async def test_late_finisher_with_superseded_claim_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """10분 넘게 걸린 작업이 그사이 다른 작업에 선점을 빼앗겼다 — 늦게 끝난 쪽은 아무것도 쓰지 않는다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    async def _another_job_retakes_the_claim() -> MemoryFactResult:
        await _supersede_claim(db_session, snapshot_id)
        return _result(_fact())

    await _extract(db_session, room, FactLLMClient(_another_job_retakes_the_claim))

    assert await _facts(db_session, room) == []
    assert [(row.status, row.attempts, row.fact_count) for row in await _extractions(db_session, room)] == [
        ("running", 2, None)
    ]


def test_production_env_extracts_facts_on_haiku_through_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영은 관계·사실 기억 추출을 켜고 그 모델을 `haiku` 로, 그 호출을 Anthropic 직결로 배정해 돈다. 뽑은 사실을 대화에
    싣는 스위치도 운영에 넣어 켜 두었다."""
    assert {"MEMORY_FACTS_EXTRACT", "MEMORY_FACT_MODEL", "MEMORY_FACTS_INJECT"} <= set(PRODUCTION_ENV_NAMES)
    loaded = load_production_env(monkeypatch)
    assert (loaded.memory_facts_extract, loaded.memory_fact_model) == (True, "haiku")
    assert loaded.llm_call_site_backends.get("chat_memory_fact") == "anthropic"
    assert loaded.memory_facts_inject


# --- 측정 서버의 프롬프트 덤프 -------------------------------------------------------------


async def test_fact_extraction_writes_its_prompt_to_the_measurement_dump(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """측정 서버는 추출 모델을 바꿔 볼 때 같은 입력을 다시 보내야 한다 — 사실 추출 프롬프트도 생성·판정 프롬프트와 같은
    파일에 한 줄로 남는다. 턴 번호 대신 추출하는 스냅샷을 적는다."""
    dump = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    fake = FactLLMClient()

    await _extract(db_session, room, fake)

    records = [json.loads(line) for line in dump.read_text(encoding="utf-8").splitlines()]
    assert records == [
        {
            "roomId": str(room.room_id),
            "kind": "background",
            "callSite": "chat_memory_fact",
            "model": settings.gemini_model_name,
            "schema": "MemoryFactResult",
            "prompt": fake.fact_prompts[0],
            "snapshotId": str(snapshot_id),
        }
    ]


async def test_failed_dump_write_does_not_change_the_fact_extraction(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """덤프는 측정용 부가 기록이다 — 쓰다 실패해도 추출은 덤프가 없을 때처럼 끝까지 가서 `done` 이 된다."""
    captured = _capture_failures(monkeypatch)
    # 디렉터리를 덤프 파일 자리로 주면 추가 모드로 열지 못해 쓰기가 실패한다.
    monkeypatch.setattr(settings, "prompt_dump_path", str(tmp_path))
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    fake = FactLLMClient()

    await _extract(db_session, room, fake)

    assert len(fake.fact_prompts) == 1
    assert captured == []
    assert [(row.snapshot_id, row.status, row.attempts) for row in await _extractions(db_session, room)] == [
        (snapshot_id, "done", 1)
    ]
