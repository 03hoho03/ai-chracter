"""턴 기록의 스탯 판정 이벤트(`chat_turns.stat_events`)가 턴 경로마다 `stat_changes` 와 맞는지.

규칙(결과를 보기 전에 적었다):
- 스위치(`STAT_EVENT_LOG`)가 꺼져 있으면 어느 경로도 칸을 채우지 않는다 — DB 기본값 `[]` 그대로이고 스탯 값·`stat_changes` 는
  켠 때와 같다.
- 켜져 있으면 보내기·수정의 새 행은 그 턴의 이벤트, 재판정한 재생성은 재판정의 이벤트, 재판정하지 않은(조건 미달·재판정 실패)
  재생성은 바꾸는 응답 기록의 이벤트를 그대로 옮긴다 — `stat_changes` 를 옮기는 것과 짝이다.
- 직전 응답 되돌리기는 기록을 쓰지 않는다. 메시지 삭제·수정의 스탯 되돌림은 옛 행을 고치지 않는다.
- 행마다 일치: 판정한 스탯마다 `v` 를 원소가 있으면 `clamp(시작 + 폭)`, 없으면 시작 값으로 두면 "`v != 시작` ⇔ `stat_changes` 에
  키가 있고 그 값이 `[시작, v]`". 원소의 `clamped` 는 `시작 + 폭` 이 범위를 벗어났는지와 같다. 시작은 보내기·수정은 그 턴 전 값,
  재판정한 재생성은 원 턴의 반영 전 값이다.

방에는 판정 스탯 "신뢰"(73, 0~100, 규칙 a1 +5·a2 -2)와 카운터 "남은 날"(30, 0~30, 턴마다 -1)이 있다."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.core.config import settings
from api.db.models import ChatMessage, ChatMessageRole, ChatRoomStat, StatDef
from api.db.models.chat import ChatTurn
from api.db.models.story import StatRule
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from factories import (
    Room,
    _clear_llm_override,
    _NeverCalledLLMClient,
    _override_llm_client,
    _parse_sse_events,
    _setup_of,
    _stat_values,
    _Stats,
    _story_room,
)

Fired = list[str] | Exception

# 재판정은 파싱 실패 꼴(원인 없는 `LLMClientError`)에 한 번 더 부르므로, 끝내 실패하게 두 번 낸다.
_REJUDGE_FAILS = (LLMClientError("판정 실패"), LLMClientError("판정 실패"))


class _ScriptedLLM(LLMClient):
    """생성은 늘 같은 글을 낸다. 스탯 판정은 `script` 를 차례로 꺼내 답한다(목록이면 발동한 짧은 id, 예외면 올린다. 다 쓰면 발동
    없음). 엔딩은 발동하지 않고 그림은 고르지 않는다."""

    def __init__(self, *script: Fired) -> None:
        self._script = list(script)
        self.stat_calls = 0
        self.prompts: list[tuple[str, str]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.prompts.append((usage.call_site, prompt))
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.prompts.append((usage.call_site, prompt))
        if response_schema is StatRuleJudgmentResult:
            self.stat_calls += 1
            outcome = self._script.pop(0) if self._script else []
            if isinstance(outcome, Exception):
                raise outcome
            return StatRuleJudgmentResult(fired_rule_ids=outcome)
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=False)
        assert response_schema is ImageMatchJudgmentResult
        return ImageMatchJudgmentResult(matched_image_entity_id=None)


@pytest.fixture
def event_log_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stat_event_log", True)


async def _stream(client: httpx.AsyncClient, method: str, path: str, body: object, fake: LLMClient) -> None:
    _override_llm_client(fake)
    try:
        response = await client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    assert _parse_sse_events(response.text)[-1]["type"] == "done", response.text


async def _send(client: httpx.AsyncClient, room: Room, *script: Fired) -> _ScriptedLLM:
    fake = _ScriptedLLM(*script)
    await _stream(client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "말"}, fake)
    return fake


async def _regenerate(client: httpx.AsyncClient, room: Room, *script: Fired) -> _ScriptedLLM:
    fake = _ScriptedLLM(*script)
    await _stream(client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, fake)
    return fake


async def _replies(db_session: AsyncSession, room: Room) -> list[ChatMessage]:
    """방의 AI 응답(오프닝 포함), 일어난 순서."""
    db_session.expire_all()
    return list(
        (
            await db_session.scalars(
                sa.select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.room_id, ChatMessage.role == ChatMessageRole.ASSISTANT)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )


async def _record_of_last_reply(db_session: AsyncSession, room: Room) -> ChatTurn:
    last = (await _replies(db_session, room))[-1]
    record = await db_session.scalar(sa.select(ChatTurn).where(ChatTurn.assistant_message_id == last.id))
    assert record is not None
    return record


async def _last_columns(db_session: AsyncSession, room: Room) -> tuple[Any, Any]:
    """마지막 응답 기록의 (`stat_changes`, `stat_events`) — 다음 요청 뒤 만료되기 전에 값으로 꺼내 둔다."""
    record = await _record_of_last_reply(db_session, room)
    return record.stat_changes, record.stat_events


async def _records(db_session: AsyncSession, room: Room) -> dict[uuid.UUID, tuple[Any, Any]]:
    """방의 모든 턴 기록 — 응답 id → (`stat_changes`, `stat_events`)."""
    db_session.expire_all()
    rows = (await db_session.scalars(sa.select(ChatTurn).where(ChatTurn.chat_room_id == room.room_id))).all()
    return {row.assistant_message_id: (row.stat_changes, row.stat_events) for row in rows}


async def _defs(db_session: AsyncSession, room: Room) -> list[StatDef]:
    setup = await _setup_of(db_session, room.room_id)
    return list((await db_session.scalars(sa.select(StatDef).where(StatDef.starting_setup_id == setup.id))).all())


async def _trust_rules(db_session: AsyncSession, stats: _Stats) -> list[dict[str, str]]:
    """신뢰 규칙 a1·a2 를 이벤트가 가리키는 꼴(`{entityId, id}`)로, 작가 순서대로."""
    stat_def_id = await db_session.scalar(sa.select(StatDef.id).where(StatDef.entity_id == uuid.UUID(stats.trust)))
    rules = (
        await db_session.scalars(sa.select(StatRule).where(StatRule.stat_def_id == stat_def_id).order_by(StatRule.order))
    ).all()
    return [{"entityId": str(rule.entity_id), "id": str(rule.id)} for rule in rules]


def _assert_agrees(record: ChatTurn, start: dict[str, float], defs: list[StatDef]) -> None:
    """행마다 일치(모듈 설명) — 이벤트로 낸 값이 `stat_changes` 를 정확히 설명한다."""
    by_stat = {event["statEntityId"]: event for event in record.stat_events if "statEntityId" in event}
    explained: dict[str, list[float]] = {}
    for stat in defs:
        stat_id = str(stat.entity_id)
        base = start[stat_id]
        event = by_stat.get(stat_id)
        if event is None:
            value = base
        else:
            raw = base + event["delta"]
            value = min(max(raw, stat.min_value), stat.max_value)
            assert event["clamped"] == (raw != value), event
        if value != base:
            explained[stat_id] = [base, value]
    assert record.stat_changes == explained


# ── 보내기 ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("event_log_on")
async def test_a_send_records_what_fired_what_applied_and_the_counter_tick(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client)
    a1, a2 = await _trust_rules(db_session, stats)

    await _send(db_client, room, ["a2", "zz9", "a1"])

    record = await _record_of_last_reply(db_session, room)
    assert record.stat_events == [
        {"statEntityId": stats.trust, "firedRuleIds": [a1, a2], "appliedRuleId": a1, "delta": 5, "clamped": False},
        {"statEntityId": stats.days, "counter": True, "delta": -1, "clamped": False},
        {"unknownRuleIdCount": 1},
    ]
    _assert_agrees(record, {stats.trust: 73, stats.days: 30}, await _defs(db_session, room))


@pytest.mark.usefixtures("event_log_on")
async def test_a_rule_that_cannot_move_a_maxed_stat_is_recorded_as_clamped_without_a_change(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이미 최대인 신뢰에 +5 — `stat_changes` 에는 키가 없지만 이벤트는 적용됐고 잘렸다고 남긴다."""
    room, stats = await _story_room(db_session, db_client)
    await db_session.execute(
        sa.update(ChatRoomStat)
        .where(ChatRoomStat.chat_room_id == room.room_id, ChatRoomStat.stat_entity_id == uuid.UUID(stats.trust))
        .values(current_value=100)
    )
    await db_session.commit()

    await _send(db_client, room, ["a1"])

    record = await _record_of_last_reply(db_session, room)
    assert stats.trust not in record.stat_changes
    assert record.stat_events[0]["clamped"] is True
    _assert_agrees(record, {stats.trust: 100, stats.days: 30}, await _defs(db_session, room))


async def test_with_the_switch_off_no_path_fills_the_column_and_stats_move_the_same(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """꺼짐: 보내기·재판정 재생성·재판정 실패 재생성 모두 칸이 `[]` 이고, 값과 `stat_changes` 는 켠 때와 같은 결과다."""
    room, stats = await _story_room(db_session, db_client)

    await _send(db_client, room, ["a1"])
    sent = await _last_columns(db_session, room)
    await _regenerate(db_client, room, ["a2"])
    rejudged = await _last_columns(db_session, room)
    await _regenerate(db_client, room, *_REJUDGE_FAILS)
    kept = await _last_columns(db_session, room)

    assert sent == ({stats.trust: [73, 78], stats.days: [30, 29]}, [])
    assert rejudged == kept == ({stats.trust: [73, 71], stats.days: [30, 29]}, [])
    assert await _stat_values(db_session, room, stats) == (71, 29)


async def test_the_switch_changes_neither_the_prompts_nor_the_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 방에서 스위치만 바꿔 같은 턴(보내기·재판정 재생성·다음 보내기)을 두 번 돌리면 생성·판정 프롬프트와 스탯이 같다 —
    스위치는 기록 칸만 바꾼다. 둘째 판은 첫 판의 방을 되돌리지 않고 새 방에서 돈다(같은 공장이라 같은 글이 나온다)."""
    runs: list[tuple[list[tuple[str, str]], tuple[float, float]]] = []
    for enabled in (False, True):
        monkeypatch.setattr(settings, "stat_event_log", enabled)
        room, stats = await _story_room(db_session, db_client)
        prompts = [
            *(await _send(db_client, room, ["a1"])).prompts,
            *(await _regenerate(db_client, room, ["a2"])).prompts,
            *(await _send(db_client, room, ["a1", "zz9"])).prompts,
        ]
        runs.append((prompts, await _stat_values(db_session, room, stats)))

    assert runs[0] == runs[1]
    assert {call_site for call_site, _ in runs[0][0]} >= {"chat_stat_judgment"}


# ── 재생성 ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("event_log_on")
async def test_a_rejudged_regeneration_records_the_rejudgment_against_the_turns_starting_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client)
    _, a2 = await _trust_rules(db_session, stats)
    await _send(db_client, room, ["a1"])

    await _regenerate(db_client, room, ["a2"])

    record = await _record_of_last_reply(db_session, room)
    assert record.kind == "regenerate"
    assert record.stat_events == [
        {"statEntityId": stats.trust, "firedRuleIds": [a2], "appliedRuleId": a2, "delta": -2, "clamped": False},
        {"statEntityId": stats.days, "counter": True, "delta": -1, "clamped": False},
    ]
    _assert_agrees(record, {stats.trust: 73, stats.days: 30}, await _defs(db_session, room))


@pytest.mark.usefixtures("event_log_on")
async def test_a_regeneration_whose_rejudgment_failed_carries_the_replaced_records_events(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재판정이 끝내 실패하면 스탯도 `stat_changes` 도 옛 기록 그대로이므로 이벤트도 옛 기록의 것을 옮겨야 두 칸이 맞는다."""
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, room, ["a1"])
    original = await _last_columns(db_session, room)

    await _regenerate(db_client, room, *_REJUDGE_FAILS)

    record = await _record_of_last_reply(db_session, room)
    assert record.kind == "regenerate"
    assert (record.stat_changes, record.stat_events) == original
    assert record.stat_events != []
    _assert_agrees(record, {stats.trust: 73, stats.days: 30}, await _defs(db_session, room))


@pytest.mark.usefixtures("event_log_on")
async def test_a_regeneration_that_does_not_rejudge_carries_the_replaced_records_events(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """마지막 턴이 아닌 응답(옛 삭제가 뒤 턴을 지운 방)은 재판정 조건 밖이라 판정을 부르지 않고 옛 기록을 옮긴다."""
    room, _stats = await _story_room(db_session, db_client)
    await _send(db_client, room, ["a1"])
    original = await _last_columns(db_session, room)
    await db_session.execute(sa.text("UPDATE chat_rooms SET turn_count = 2 WHERE id = :id"), {"id": room.room_id})
    await db_session.commit()

    fake = _ScriptedLLM()
    await _stream(db_client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, fake)

    assert fake.stat_calls == 0
    record = await _record_of_last_reply(db_session, room)
    assert record.kind == "regenerate"
    assert (record.stat_changes, record.stat_events) == original
    assert record.stat_events != []


# ── 기록을 쓰지 않는 경로 ─────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("event_log_on")
async def test_restoring_the_previous_reply_writes_no_record_and_leaves_both_records_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _stats = await _story_room(db_session, db_client)
    await _send(db_client, room, ["a1"])
    await _regenerate(db_client, room, ["a2"])
    before = await _records(db_session, room)
    current = (await _replies(db_session, room))[-1]

    _override_llm_client(_NeverCalledLLMClient())
    try:
        response = await db_client.post(f"/chat-rooms/{room.room_id}/messages/{current.id}/restore-previous")
    finally:
        _clear_llm_override()

    assert response.status_code == 200, response.text
    assert await _records(db_session, room) == before


@pytest.mark.usefixtures("event_log_on")
async def test_deleting_the_last_reply_rewinds_stats_without_touching_its_record(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, room, ["a1"])
    before = await _records(db_session, room)
    last = (await _replies(db_session, room))[-1]

    response = await db_client.delete(f"/chat-rooms/{room.room_id}/messages/{last.id}")

    assert response.status_code == 200, response.text
    assert await _stat_values(db_session, room, stats) == (73, 30)
    assert await _records(db_session, room) == before


@pytest.mark.usefixtures("event_log_on")
async def test_an_edit_records_its_new_turn_and_leaves_the_removed_turns_record_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client)
    _, a2 = await _trust_rules(db_session, stats)
    await _send(db_client, room, ["a1"])
    before = await _records(db_session, room)
    user_message = await db_session.scalar(
        sa.select(ChatMessage.id).where(ChatMessage.chat_room_id == room.room_id, ChatMessage.role == ChatMessageRole.USER)
    )

    await _stream(
        db_client,
        "PATCH",
        f"/chat-rooms/{room.room_id}/messages/{user_message}",
        {"content": "고친 말"},
        _ScriptedLLM(["a2"]),
    )

    after = await _records(db_session, room)
    assert {key: after[key] for key in before} == before
    record = await _record_of_last_reply(db_session, room)
    assert record.kind == "edit"
    assert record.stat_events[0]["appliedRuleId"] == a2
    _assert_agrees(record, {stats.trust: 73, stats.days: 30}, await _defs(db_session, room))
