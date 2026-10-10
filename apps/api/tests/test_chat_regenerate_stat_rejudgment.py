"""재생성이 스탯을 되돌리고 새 응답으로 다시 판정하는지.

규칙(결과를 보기 전에 적었다):
- 되돌림·재판정은 바꾸는 응답의 턴 기록이 있고, 그 기록에 엔딩이 없고, 방이 아직 엔딩 전이고, 그 기록의 턴이 방의 마지막 턴
  (`turn_number == turn_count`)일 때만 한다. 하나라도 아니면 지금처럼 스탯을 건드리지 않고 새 기록은 옛 기록을 이어받는다.
- 판정 입력은 기록의 반영 전 값이다(메모리에서만). 되돌림과 새 값은 쓰기 구간에서 함께 쓰고, 카운터는 반영 전 값에서 한 번만
  구른다. 새 기록의 스탯 변화는 반영 전 값 대비 새 결과다. `statChange` 는 화면이 들고 있는 값(지금 DB 값)과 달라진 스탯에만 나간다.
- 재생성에서 엔딩 판정은 하지 않는다.
- 재판정은 일시적인 서버·연결 오류(5xx — 504 제외 — 와 타임아웃이 아닌 연결 끊김)와 파싱 실패에만 곧바로 한 번 다시 부른다.
  끝내 실패하면 되돌리지 않는다 — 스탯 값과 `statChange` 는 그대로이고 새 기록은 옛 기록을 이어받는다. 보내기·수정의 스탯 판정은
  다시 부르지 않는다.
- 응답을 받은 호출(파싱 실패 포함)의 사용량은 턴 기록의 LLM 호출에 남는다. 응답 없이 끝난 호출(5xx·연결 끊김)은 공급자 구현이
  사용량을 남기지 않으므로 기록에도 없다.

스탯 판정은 SDK 경계만 가짜로 둔 실제 Gemini 구현을 지난다 — 실패의 원인이 실제 정규화를 거쳐 판정 쪽 분류에 닿아야 해서다.
방에는 판정 스탯 "신뢰"(73, 규칙 a1 +5·a2 -2)와 카운터 "남은 날"(30, 턴마다 -1)이 있다."""

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from google.genai import errors as genai_errors
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.db.models import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomStat, Ending, StartingSetup, StatDef
from api.db.models.chat import ChatTurn
from api.db.models.story import StatRule
from api.llm import gemini as gemini_module
from api.llm.client import CallUsage, LLMCallContext, LLMClient
from api.llm.gemini import GeminiLLMClient
from factories import Room, _clear_llm_override, _open_room, _override_llm_client, _parse_sse_events

_REQUEST = httpx.Request("POST", "https://example.invalid")
_USAGE = SimpleNamespace(
    prompt_token_count=40, cached_content_token_count=None, candidates_token_count=5, thoughts_token_count=None
)


def _fired(*rule_ids: str) -> SimpleNamespace:
    return SimpleNamespace(
        parsed=StatRuleJudgmentResult(fired_rule_ids=list(rule_ids)),
        prompt_feedback=None,
        candidates=[],
        text="",
        usage_metadata=_USAGE,
    )


def _unparsable() -> SimpleNamespace:
    return SimpleNamespace(parsed=None, prompt_feedback=None, candidates=[], text="{", usage_metadata=_USAGE)


def _blocked() -> SimpleNamespace:
    return SimpleNamespace(
        parsed=None,
        prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
        candidates=[],
        text="",
        usage_metadata=_USAGE,
    )


def _server_error(code: int) -> genai_errors.APIError:
    if code < 500:
        return genai_errors.ClientError(code, {"error": {"message": "fail"}})
    return genai_errors.ServerError(code, {"error": {"message": "fail"}})


class _TurnLLM(LLMClient):
    """생성은 `reply` 를 낸다. 스탯 판정은 `stat_script` 를 차례로 꺼내 SDK 가 낸 것처럼 실제 Gemini 구현에 넘긴다(응답이면
    돌려주고 예외면 올린다). 엔딩은 `ending` 대로, 그림 판정은 고르지 않는다. 부른 호출 위치를 순서대로 남긴다."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, reply: str, stat_script: list[Any], *, ending: bool = False
    ) -> None:
        self._reply = reply
        self._stat_script = list(stat_script)
        self._ending = ending
        self.call_sites: list[str] = []

        async def _no_record(*_: Any, **__: Any) -> None:
            return None

        async def _generate_content(**_: Any) -> Any:
            outcome = self._stat_script.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(gemini_module, "record_usage", _no_record)
        self._gemini = GeminiLLMClient(api_key="test-key")
        monkeypatch.setattr(
            self._gemini,
            "_client",
            SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=_generate_content))),
        )

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.call_sites.append(usage.call_site)
        yield self._reply
        if usage.usage_sink is not None:
            usage.usage_sink.append(CallUsage(usage.call_site, "fake-model", 1, None, None, 1, None))

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.call_sites.append(usage.call_site)
        if response_schema is StatRuleJudgmentResult:
            return await self._gemini.generate_structured(prompt, response_schema, images, usage=usage)
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=self._ending)
        assert response_schema is ImageMatchJudgmentResult
        return ImageMatchJudgmentResult(matched_image_entity_id=None)

    def stat_calls(self) -> int:
        return self.call_sites.count("chat_stat_judgment")


class _Stats:
    """방의 두 스탯 entity_id(문자열)."""

    def __init__(self, trust: str, days: str) -> None:
        self.trust = trust
        self.days = days


async def _story_room(db_session: AsyncSession, db_client: httpx.AsyncClient, *, turns: int = 0) -> tuple[Room, _Stats]:
    room = await _open_room(db_client, db_session, turns=turns, lane="story")
    setup = await _setup_of(db_session, room.room_id)
    trust = await db_session.scalar(sa.select(StatDef).where(StatDef.starting_setup_id == setup.id))
    assert trust is not None
    db_session.add(
        StatRule(entity_id=uuid.uuid4(), stat_def_id=trust.id, condition="[RULE]약속을 어긴다", delta=-2, order=1)
    )
    days = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="남은 날",
        icon="clock",
        color="#00ff00",
        min_value=0,
        max_value=30,
        initial_value=30,
        per_turn_delta=-1,
        unit=None,
        description="남은 날",
        order=2,
    )
    db_session.add(days)
    await db_session.commit()
    return room, _Stats(str(trust.entity_id), str(days.entity_id))


async def _setup_of(db_session: AsyncSession, room_id: uuid.UUID) -> StartingSetup:
    version_id, setup_entity_id = (
        await db_session.execute(
            sa.select(ChatRoom.content_version_id, ChatRoom.starting_setup_entity_id).where(ChatRoom.id == room_id)
        )
    ).one()
    setup = await db_session.scalar(
        sa.select(StartingSetup).where(
            StartingSetup.content_version_id == version_id, StartingSetup.entity_id == setup_entity_id
        )
    )
    assert setup is not None
    return setup


async def _turn(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, object] | None, fake: _TurnLLM
) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        response = await client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    events = _parse_sse_events(response.text)
    assert events[-1]["type"] == "done", response.text
    return events


async def _send(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, room: Room, content: str, *rule_ids: str
) -> None:
    await _turn(
        client,
        "POST",
        f"/chat-rooms/{room.room_id}/messages",
        {"content": content},
        _TurnLLM(monkeypatch, f"{content} 응답", [_fired(*rule_ids)]),
    )


async def _regenerate(client: httpx.AsyncClient, room: Room, fake: _TurnLLM) -> list[dict[str, Any]]:
    return await _turn(client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, fake)


async def _values(db_session: AsyncSession, room: Room, stats: _Stats) -> tuple[float, float]:
    db_session.expire_all()
    rows = {
        str(row.stat_entity_id): float(row.current_value)
        for row in (
            await db_session.scalars(sa.select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.room_id))
        ).all()
    }
    return rows[stats.trust], rows[stats.days]


def _stat_events(events: list[dict[str, Any]]) -> dict[str, float]:
    return {event["statId"]: event["newValue"] for event in events if event["type"] == "statChange"}


async def _last_reply(db_session: AsyncSession, room: Room) -> ChatMessage:
    db_session.expire_all()
    message = await db_session.scalar(
        sa.select(ChatMessage)
        .where(ChatMessage.chat_room_id == room.room_id, ChatMessage.role == ChatMessageRole.ASSISTANT)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    assert message is not None
    return message


async def _record_of_last_reply(db_session: AsyncSession, room: Room) -> ChatTurn:
    reply = await _last_reply(db_session, room)
    record = await db_session.scalar(sa.select(ChatTurn).where(ChatTurn.assistant_message_id == reply.id))
    assert record is not None
    return record


def _inherited(record: ChatTurn) -> tuple[Any, ...]:
    return (record.turn_number, record.stat_changes, record.ending_entity_id, record.shortcut_entity_id)


# ── 되돌림·재판정 ────────────────────────────────────────────────────────────────────────


async def test_regenerating_the_last_turn_reverts_its_stat_changes_and_rejudges_against_the_new_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    assert await _values(db_session, room, stats) == (78, 29)

    fake = _TurnLLM(monkeypatch, "약속을 어긴 응답", [_fired("a2")])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 1
    # 신뢰는 반영 전 73 에서 -2, 카운터는 반영 전 30 에서 한 번만 구른다.
    assert await _values(db_session, room, stats) == (71, 29)
    # 화면의 값(78, 29)과 달라진 신뢰만 알린다.
    assert _stat_events(events) == {stats.trust: 71}
    record = await _record_of_last_reply(db_session, room)
    assert (record.kind, record.turn_number) == ("regenerate", 1)
    assert record.stat_changes == {stats.trust: [73, 71], stats.days: [30, 29]}
    assert (await _last_reply(db_session, room)).content == "약속을 어긴 응답"


async def test_rejudging_rolls_the_counter_once_from_the_turns_starting_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "첫 턴", "a1")
    await _send(db_client, monkeypatch, room, "둘째 턴")
    assert await _values(db_session, room, stats) == (78, 28)

    events = await _regenerate(db_client, room, _TurnLLM(monkeypatch, "다시", [_fired()]))

    # 둘째 턴은 29 에서 28 로 굴렀다 — 되돌려 29 에서 다시 한 번 굴러 28 이다(27 이 아니다).
    assert await _values(db_session, room, stats) == (78, 28)
    assert _stat_events(events) == {}
    assert (await _record_of_last_reply(db_session, room)).stat_changes == {stats.days: [29, 28]}


async def test_regenerating_a_regeneration_reverts_only_the_previous_regenerations_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    await _regenerate(db_client, room, _TurnLLM(monkeypatch, "어긴다", [_fired("a2")]))
    assert await _values(db_session, room, stats) == (71, 29)

    fake = _TurnLLM(monkeypatch, "아무 일 없다", [_fired()])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 1
    assert await _values(db_session, room, stats) == (73, 29)
    assert _stat_events(events) == {stats.trust: 73}
    record = await _record_of_last_reply(db_session, room)
    assert (record.kind, record.stat_changes) == ("regenerate", {stats.days: [30, 29]})


async def test_a_regeneration_that_kept_the_old_effect_is_reverted_to_the_original_turns_starting_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """재판정 없이 옛 효과를 이어받은 재생성 기록(재판정이 생기기 전에 쓰인 재생성 기록과 같은 모양)을 다시 재생성하면 원 보내기의
    반영 전 값으로 되돌린 뒤 판정한다 — 원 효과와 새 효과가 겹치지 않는다."""
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    # 다시 부르지 않는 실패라 이 재생성은 옛 효과를 그대로 이어받는다.
    await _regenerate(db_client, room, _TurnLLM(monkeypatch, "첫 재생성", [_server_error(400)]))
    kept = await _record_of_last_reply(db_session, room)
    assert (kept.kind, kept.stat_changes) == ("regenerate", {stats.trust: [73, 78], stats.days: [30, 29]})

    await _regenerate(db_client, room, _TurnLLM(monkeypatch, "둘째 재생성", [_fired("a2")]))

    assert await _values(db_session, room, stats) == (71, 29)


async def test_a_record_whose_before_value_is_empty_reverts_that_stat_to_its_initial_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기록의 반영 전 값이 비어 있으면 그 스탯의 시작값에서 다시 판정한다 — 방 스탯을 읽을 때 행이 없는 스탯을 시작값으로 보는
    것과 같은 뜻이다. 규칙이 발동하지 않아도 원 턴의 값이 남지 않고 시작값으로 돌아온다."""
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    assert await _values(db_session, room, stats) == (78, 29)
    record = await _record_of_last_reply(db_session, room)
    record.stat_changes = {stats.trust: [None, 78], stats.days: [30, 29]}
    await db_session.commit()

    events = await _regenerate(db_client, room, _TurnLLM(monkeypatch, "아무 일 없다", [_fired()]))

    # 신뢰의 시작값은 73 이다.
    assert await _values(db_session, room, stats) == (73, 29)
    assert _stat_events(events) == {stats.trust: 73}
    assert (await _record_of_last_reply(db_session, room)).stat_changes == {stats.days: [30, 29]}


# ── 지금 동작 그대로인 경우 ──────────────────────────────────────────────────────────────


async def test_regenerating_a_turn_whose_record_reached_an_ending_does_not_rejudge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    record = await _record_of_last_reply(db_session, room)
    record.ending_entity_id = uuid.uuid4()
    await db_session.commit()
    ended = _inherited(record)

    fake = _TurnLLM(monkeypatch, "다시", [])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 0
    assert await _values(db_session, room, stats) == (78, 29)
    assert _stat_events(events) == {}
    assert _inherited(await _record_of_last_reply(db_session, room)) == ended


async def test_regenerating_a_reply_without_a_record_does_not_rejudge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client, turns=1)
    # 기록을 쓰기 전에 보낸 턴들이 남긴 값.
    await db_session.execute(
        sa.update(ChatRoomStat)
        .where(ChatRoomStat.chat_room_id == room.room_id, ChatRoomStat.stat_entity_id == uuid.UUID(stats.trust))
        .values(current_value=50)
    )
    db_session.add(ChatRoomStat(chat_room_id=room.room_id, stat_entity_id=uuid.UUID(stats.days), current_value=20))
    await db_session.commit()

    fake = _TurnLLM(monkeypatch, "다시", [])
    events = await _regenerate(db_client, room, fake)
    fake_again = _TurnLLM(monkeypatch, "또 다시", [])
    await _regenerate(db_client, room, fake_again)

    assert (fake.stat_calls(), fake_again.stat_calls()) == (0, 0)
    assert await _values(db_session, room, stats) == (50, 20)
    assert _stat_events(events) == {}
    assert await db_session.scalar(sa.select(sa.func.count()).where(ChatTurn.chat_room_id == room.room_id)) == 0


async def test_regenerating_after_the_room_reached_an_ending_does_not_rejudge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(ending_reached=True))
    await db_session.commit()

    fake = _TurnLLM(monkeypatch, "다시", [])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 0
    assert await _values(db_session, room, stats) == (78, 29)
    assert _stat_events(events) == {}


async def test_regenerating_does_not_judge_endings(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    setup = await _setup_of(db_session, room.room_id)
    db_session.add(
        Ending(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="떠남",
            turn_count_gate=1,
            judgment_prompt="떠났는가?",
            epilogue="떠났다.",
            order=1,
        )
    )
    await db_session.commit()

    fake = _TurnLLM(monkeypatch, "떠난다", [_fired("a2")], ending=True)
    events = await _regenerate(db_client, room, fake)

    assert "chat_ending_judgment" not in fake.call_sites
    assert [event["type"] for event in events if event["type"] == "endingReached"] == []
    db_session.expire_all()
    assert await db_session.scalar(sa.select(ChatRoom.ending_reached).where(ChatRoom.id == room.room_id)) is False


async def _send_two_and_delete_the_second(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, room: Room
) -> None:
    await _send(db_client, monkeypatch, room, "첫 턴", "a1")
    await _send(db_client, monkeypatch, room, "둘째 턴", "a1")
    second_reply = await _last_reply(db_session, room)
    second_user = await db_session.scalar(
        sa.select(ChatMessage).where(ChatMessage.chat_room_id == room.room_id, ChatMessage.content == "둘째 턴")
    )
    assert second_user is not None
    for message in (second_reply, second_user):
        deleted = await db_client.delete(f"/chat-rooms/{room.room_id}/messages/{message.id}")
        assert deleted.status_code == 204, deleted.text


async def test_regenerating_an_earlier_reply_after_deleting_later_turns_does_not_revert(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """뒤 턴을 지워 앞 응답이 마지막이 되면 그 기록의 반영 전 값은 지운 턴의 효과까지 지운다 — 되돌리지 않는다. 메시지
    삭제는 지운 턴의 효과를 남기므로 값은 둘째 턴 뒤 그대로다."""
    room, stats = await _story_room(db_session, db_client)
    await _send_two_and_delete_the_second(db_client, db_session, monkeypatch, room)
    first_record = _inherited(await _record_of_last_reply(db_session, room))
    assert await _values(db_session, room, stats) == (83, 28)

    fake = _TurnLLM(monkeypatch, "다시", [])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 0
    assert await _values(db_session, room, stats) == (83, 28)
    assert _stat_events(events) == {}
    assert _inherited(await _record_of_last_reply(db_session, room)) == first_record


async def test_regenerating_that_regeneration_again_still_does_not_revert(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send_two_and_delete_the_second(db_client, db_session, monkeypatch, room)
    first_record = _inherited(await _record_of_last_reply(db_session, room))
    await _regenerate(db_client, room, _TurnLLM(monkeypatch, "다시", []))

    fake = _TurnLLM(monkeypatch, "또 다시", [])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 0
    assert await _values(db_session, room, stats) == (83, 28)
    assert _stat_events(events) == {}
    assert _inherited(await _record_of_last_reply(db_session, room)) == first_record


async def test_regenerating_a_turn_sent_after_deleting_later_turns_reverts_only_to_that_turns_start(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send_two_and_delete_the_second(db_client, db_session, monkeypatch, room)
    await _send(db_client, monkeypatch, room, "셋째 턴", "a1")
    assert await _values(db_session, room, stats) == (88, 27)

    fake = _TurnLLM(monkeypatch, "어긴다", [_fired("a2")])
    await _regenerate(db_client, room, fake)

    # 셋째 턴의 반영 전 값(83, 28)으로 되돌린다 — 지운 둘째 턴의 효과(78→83, 29→28)는 남는다.
    assert fake.stat_calls() == 1
    assert await _values(db_session, room, stats) == (81, 27)


# ── 재판정 실패와 재시도 ─────────────────────────────────────────────────────────────────

_RETRIED: dict[str, Any] = {
    "server-error-503": _server_error(503),
    "connect-error": httpx.ConnectError("refused", request=_REQUEST),
    "unparsable-response": _unparsable(),
}


@pytest.mark.parametrize("failure", list(_RETRIED))
async def test_a_transient_server_connection_or_parse_failure_is_rejudged_once_more_and_the_second_result_applies(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")

    fake = _TurnLLM(monkeypatch, "어긴다", [_RETRIED[failure], _fired("a2")])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 2
    assert await _values(db_session, room, stats) == (71, 29)
    assert _stat_events(events) == {stats.trust: 71}
    record = await _record_of_last_reply(db_session, room)
    assert record.stat_changes == {stats.trust: [73, 71], stats.days: [30, 29]}
    # 응답을 받은 호출만 사용량이 있다 — 파싱 실패는 응답을 받았고, 5xx·연결 끊김은 응답이 없었다.
    judged = [call for call in record.llm_calls if call["callSite"] == "chat_stat_judgment"]
    assert len(judged) == (2 if failure == "unparsable-response" else 1)


_NOT_RETRIED: dict[str, Any] = {
    "read-timeout": httpx.ReadTimeout("slow", request=_REQUEST),
    "timeout-error": TimeoutError(),
    "gateway-timeout-504": _server_error(504),
    "quota-429": _server_error(429),
    "blocked": _blocked(),
    "bad-request-400": _server_error(400),
}


@pytest.mark.parametrize("failure", list(_NOT_RETRIED))
async def test_a_timeout_quota_block_or_client_error_is_not_retried_and_keeps_the_old_effect(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    old = _inherited(await _record_of_last_reply(db_session, room))

    fake = _TurnLLM(monkeypatch, "어긴다", [_NOT_RETRIED[failure], _fired("a2")])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 1
    assert await _values(db_session, room, stats) == (78, 29)
    assert _stat_events(events) == {}
    assert _inherited(await _record_of_last_reply(db_session, room)) == old


async def test_when_rejudging_finally_fails_nothing_is_reverted_and_the_new_record_inherits(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    old = _inherited(await _record_of_last_reply(db_session, room))

    fake = _TurnLLM(monkeypatch, "새 응답", [_server_error(503), _server_error(503)])
    events = await _regenerate(db_client, room, fake)

    assert fake.stat_calls() == 2
    assert await _values(db_session, room, stats) == (78, 29)
    assert _stat_events(events) == {}
    assert [event["type"] for event in events][-1] == "done"
    assert (await _last_reply(db_session, room)).content == "새 응답"
    new = await _record_of_last_reply(db_session, room)
    assert new.kind == "regenerate"
    assert _inherited(new) == old


@pytest.mark.parametrize("kind", ["send", "edit"])
async def test_a_new_turns_stat_judgment_is_not_retried_on_a_transient_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, monkeypatch, room, "약속을 지킨다", "a1")
    fake = _TurnLLM(monkeypatch, "응답", [_server_error(503), _fired("a1")])

    if kind == "send":
        await _turn(db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "또"}, fake)
    else:
        edited = await db_session.scalar(
            sa.select(ChatMessage.id).where(
                ChatMessage.chat_room_id == room.room_id, ChatMessage.content == "약속을 지킨다"
            )
        )
        await _turn(
            db_client, "PATCH", f"/chat-rooms/{room.room_id}/messages/{edited}", {"content": "고쳐 말한다"}, fake
        )

    assert fake.stat_calls() == 1
    # 판정이 실패한 턴은 카운터도 굴리지 않는다.
    assert await _values(db_session, room, stats) == (78, 29)
