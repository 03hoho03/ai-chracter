import logging
import uuid
from collections.abc import AsyncIterator
from datetime import timezone
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, StatRuleJudgmentResult
from api.db.models import (
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    Content,
    Ending,
    EndingRule,
    EndingRuleOperator,
    StartingSetup,
    StatDef,
    StatRule,
    StoryEndingUnlock,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError
from factories import (
    ENDING_PRIORITY_SCENARIOS,
    EndingPriorityScenario,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_published_story,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
    ending_priority_marker,
    ending_priority_stat_rules,
    judged_ending_names,
)


async def _add_starting_setup(db_session: AsyncSession, content: Content) -> StartingSetup:
    assert content.current_published_version_id is not None
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="첫 만남",
        prologue="옛날 옛적, 낯선 마을에 도착했다.",
        opening_message="다시 만났네요!",
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    return setup


async def _add_stat_def(db_session: AsyncSession, setup: StartingSetup, **overrides: object) -> StatDef:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": setup.id,
        "name": "호감도",
        "icon": "heart",
        "color": "#ff0000",
        "min_value": 0,
        "max_value": 100,
        "initial_value": 50,
        "unit": None,
        "description": "호감도 스탯",
        "order": 1,
    }
    defaults.update(overrides)
    stat_def = StatDef(**defaults)
    db_session.add(stat_def)
    await db_session.flush()
    return stat_def


async def _add_stat_rule(db_session: AsyncSession, stat_def: StatDef, delta: int, order: int = 0) -> None:
    """스탯에 「조건 → delta」 규칙 하나. 스탯 하나에 규칙 하나면 그 규칙의 짧은 id 는 a1 이다."""
    db_session.add(
        StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def.id, condition=f"조건 {order}", delta=delta, order=order)
    )
    await db_session.flush()


async def _add_ending(db_session: AsyncSession, setup: StartingSetup, **overrides: object) -> Ending:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": setup.id,
        "name": "엔딩",
        "turn_count_gate": 1,
        "judgment_prompt": "주인공이 마을을 완전히 떠났는가?",
        "epilogue": "이야기는 여기서 끝난다.",
        "order": 1,
    }
    defaults.update(overrides)
    ending = Ending(**defaults)
    db_session.add(ending)
    await db_session.flush()
    return ending


def _add_rule(db_session: AsyncSession, ending: Ending, stat_entity_id: uuid.UUID, *, threshold: float) -> None:
    """`stat >= threshold` 규칙 하나. 판정 순서 테스트는 이 모양 하나로 참·거짓을 가른다(초기값 50)."""
    db_session.add(
        EndingRule(
            entity_id=uuid.uuid4(),
            ending_id=ending.id,
            stat_def_entity_id=stat_entity_id,
            operator=EndingRuleOperator.GTE,
            threshold=threshold,
            next_op=None,
            order=1,
        )
    )


async def _create_story_room_via_api(
    client: httpx.AsyncClient, content_id: uuid.UUID, starting_setup_id: uuid.UUID
) -> httpx.Response:
    return await client.post(
        "/chat-rooms",
        json={"contentId": str(content_id), "contentType": "story", "startingSetupId": str(starting_setup_id)},
    )


class _FakeLLMClient(LLMClient):
    """`StatRuleJudgmentResult`(스탯 판단)와 `EndingJudgmentResult`(엔딩 판정)가 한 턴 안에서
    순서대로 여러 번 호출될 수 있으므로, 고정된 단일 응답이 아니라 호출 순서대로 소비되는
    큐를 쓴다(test_chat_story_message_send_api.py의 단일-응답 `_FakeLLMClient`와 다른 점)."""

    def __init__(self, tokens: list[str], structured_results: list[Any]) -> None:
        self.tokens = tokens
        self._structured_results = list(structured_results)
        self.generate_structured_calls: list[Any] = []
        self.structured_prompts: list[str] = []
        self.usages: list[LLMCallContext] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.usages.append(usage)
        for token in self.tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.usages.append(usage)
        self.generate_structured_calls.append(response_schema)
        self.structured_prompts.append(prompt)
        result = self._structured_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def test_send_message_reaches_ending_when_judgment_triggers_with_no_stat_rules(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    # 규칙 있는 스탯을 둬 스탯 판정 호출도 일어나게 한다 — 호출부 귀속(아래)을 두 판정 모두에서 본다.
    await _add_stat_rule(db_session, await _add_stat_def(db_session, setup), 3)
    ending = await _add_ending(db_session, setup, turn_count_gate=1)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안", "녕"],
        structured_results=[StatRuleJudgmentResult(fired_rule_ids=[]), EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "마을을 떠났다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "token", "endingReached", "done"]
    ending_event = events[2]
    assert ending_event["endingId"] == str(ending.entity_id)
    assert ending_event["epilogue"] == "이야기는 여기서 끝난다."

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is True
    assert room.ending_entity_id == ending.entity_id
    assert room.ending_reached_at_turn == 1

    unlock = await db_session.get(StoryEndingUnlock, (user.id, setup.entity_id, ending.entity_id))
    assert unlock is not None

    # 로그의 호출부 귀속 — stat↔ending 이 뒤바뀌거나 다른 방·유저로 찍히면 비용 집계가 틀린다.
    assert [u.call_site for u in fake.usages] == ["chat_generate", "chat_stat_judgment", "chat_ending_judgment"]
    assert {(u.user_id, u.room_id) for u in fake.usages} == {(user.id, room_id)}


async def test_send_message_skips_ending_judgment_before_turn_gate(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await _add_ending(db_session, setup, turn_count_gate=10)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_results=[])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    # 스탯이 없어 스탯 판정 호출이 없고, 엔딩 판정(턴게이트 미통과)도 호출조차 되지 않는다.
    assert fake.generate_structured_calls == []

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is False


async def test_send_message_does_not_call_ending_judgment_when_stat_rule_is_false(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """규칙은 이번 턴 반영 뒤 스탯만으로 정해지므로 먼저 평가한다 — 거짓이면 판정 모델을 부르지 않는다.
    큐에 엔딩 판정 응답을 넣지 않아, 판정을 부르면 빈 큐에서 꺼내다 턴이 깨진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
    ending = await _add_ending(db_session, setup, turn_count_gate=1)
    _add_rule(db_session, ending, stat_def.entity_id, threshold=80)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_results=[])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.generate_structured_calls == []

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is False


async def test_send_message_does_not_reach_ending_when_stat_rule_passes_but_judgment_declines(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """규칙이 참이어도 판정 모델이 거짓이면 발동하지 않는다 — 규칙을 먼저 본다고 판정을 건너뛰지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, initial_value=50)
    ending = await _add_ending(db_session, setup, turn_count_gate=1)
    _add_rule(db_session, ending, stat_def.entity_id, threshold=40)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[EndingJudgmentResult(triggered=False)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.generate_structured_calls == [EndingJudgmentResult]
    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is False


async def test_send_message_judges_due_endings_in_order_and_stops_at_first_reached(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """order 순으로 본다. 규칙이 거짓인 1순위는 판정 없이 넘어가고, 규칙은 참이나 판정이 거짓인 2순위 다음
    3순위에서 발동하면 규칙 없는 4순위는 판정하지 않는다. 행은 order 와 다른 순서로 넣는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, initial_value=50)
    await _add_ending(db_session, setup, turn_count_gate=1, order=4, name="규칙 없는 4순위")
    third = await _add_ending(db_session, setup, turn_count_gate=1, order=3, name="3순위")
    second = await _add_ending(db_session, setup, turn_count_gate=1, order=2, name="2순위")
    first = await _add_ending(db_session, setup, turn_count_gate=1, order=1, name="1순위")
    _add_rule(db_session, first, stat_def.entity_id, threshold=80)
    _add_rule(db_session, second, stat_def.entity_id, threshold=40)
    _add_rule(db_session, third, stat_def.entity_id, threshold=40)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[
            EndingJudgmentResult(triggered=False),
            EndingJudgmentResult(triggered=True),
        ],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "endingReached", "done"]
    assert events[1]["endingId"] == str(third.entity_id)
    assert fake.generate_structured_calls == [EndingJudgmentResult, EndingJudgmentResult]


async def test_send_message_treats_rule_on_missing_stat_as_false_and_completes_the_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """시작설정에 없는 스탯을 가리키는 규칙 항목은 거짓이다. 예외로 SSE 가 끊기지 않고 턴이 커밋되며,
    어느 방·엔딩·스탯인지 경고로 남긴다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await _add_stat_def(db_session, setup, initial_value=50)
    ending = await _add_ending(db_session, setup, turn_count_gate=1)
    missing_stat_id = uuid.uuid4()
    _add_rule(db_session, ending, missing_stat_id, threshold=0)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_results=[])
    _override_llm_client(fake)
    try:
        with caplog.at_level(logging.WARNING, logger="api.chat.turn_judgments"):
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.generate_structured_calls == []
    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert (room.turn_count, room.ending_reached) == (1, False)
    [warning] = [r.getMessage() for r in caplog.records if str(missing_stat_id) in r.getMessage()]
    assert str(room_id) in warning
    assert str(ending.entity_id) in warning


@pytest.mark.parametrize("scenario", ENDING_PRIORITY_SCENARIOS)
async def test_send_message_judges_priority_stat_group_by_highest_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession, scenario: EndingPriorityScenario
) -> None:
    """우선 스탯을 채운 엔딩끼리는 이번 턴 반영 뒤 그 스탯 값이 가장 높은 것만 판정한다. 같은 시나리오를 빌더
    미리보기(`test_send_preview_message_judges_priority_stat_group_by_highest_value`)에도 넣어 결과가 같은지 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    rule_deltas, fired_rule_ids = ending_priority_stat_rules(scenario)
    stat_ids: dict[str, uuid.UUID] = {}
    for index, (name, value) in enumerate(scenario.stats.items()):
        stat_def = await _add_stat_def(db_session, setup, name=name, initial_value=value, order=index)
        await _add_stat_rule(db_session, stat_def, rule_deltas[name])
        stat_ids[name] = stat_def.entity_id
    for order, (name, priority, rule) in enumerate(scenario.endings):
        ending = await _add_ending(
            db_session,
            setup,
            name=name,
            order=order,
            judgment_prompt=ending_priority_marker(name),
            priority_stat_def_entity_id=stat_ids[priority] if priority is not None else None,
        )
        if rule is not None:
            _add_rule(db_session, ending, stat_ids[rule[0]], threshold=rule[1])
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    stat_judgment = StatRuleJudgmentResult(fired_rule_ids=fired_rule_ids)
    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[stat_judgment, *(EndingJudgmentResult(triggered=v) for v in scenario.verdicts)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert judged_ending_names(fake.structured_prompts, scenario) == scenario.judged
    assert len(fake.structured_prompts) == 1 + len(scenario.judged)
    reached = [e["endingId"] for e in events if e["type"] == "endingReached"]
    ending_ids = {
        e.name: e.entity_id
        for e in (await db_session.scalars(sa.select(Ending).where(Ending.starting_setup_id == setup.id))).all()
    }
    assert reached == ([str(ending_ids[scenario.reached])] if scenario.reached is not None else [])


async def test_send_message_only_top_priority_ending_reached_when_multiple_due(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    top_ending = await _add_ending(db_session, setup, turn_count_gate=1, order=1, name="1순위 엔딩")
    await _add_ending(db_session, setup, turn_count_gate=1, order=2, name="2순위 엔딩")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    ending_events = [e for e in events if e["type"] == "endingReached"]
    assert len(ending_events) == 1
    assert ending_events[0]["endingId"] == str(top_ending.entity_id)
    # 1순위 엔딩에서 이미 발동했으므로 2순위 엔딩은 판정 자체를 호출하지 않는다(불필요한 LLM 호출 방지).
    assert fake.generate_structured_calls == [EndingJudgmentResult]

    unlocks = (
        await db_session.execute(sa.select(StoryEndingUnlock).where(StoryEndingUnlock.user_id == user.id))
    ).scalars().all()
    assert len(unlocks) == 1
    assert unlocks[0].ending_entity_id == top_ending.entity_id


async def test_send_message_skips_stat_and_ending_judgment_once_room_already_ending_reached(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await _add_ending(db_session, setup, turn_count_gate=1)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    room.ending_reached = True
    await db_session.commit()

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "여전히 대화 가능"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.generate_structured_calls == []


async def test_send_message_reaches_ending_without_epilogue_emits_null_epilogue(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    ending = await _add_ending(db_session, setup, turn_count_gate=1, epilogue=None)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    ending_event = next(e for e in events if e["type"] == "endingReached")
    assert ending_event["epilogue"] is None

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is True
    assert room.ending_entity_id == ending.entity_id


async def test_send_message_does_not_duplicate_existing_story_ending_unlock(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    ending = await _add_ending(db_session, setup, turn_count_gate=1)
    db_session.add(
        StoryEndingUnlock(
            user_id=user.id, starting_setup_entity_id=setup.entity_id, ending_entity_id=ending.entity_id
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    unlocks = (
        await db_session.execute(sa.select(StoryEndingUnlock).where(StoryEndingUnlock.user_id == user.id))
    ).scalars().all()
    assert len(unlocks) == 1


async def test_send_message_ending_judgment_uses_stat_values_updated_this_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """엔딩 규칙 평가는 이번 턴에 판단된 스탯 변경 이후의 값을 근거로 해야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
    await _add_stat_rule(db_session, stat_def, 40)
    ending = await _add_ending(db_session, setup, turn_count_gate=1)
    db_session.add(
        EndingRule(
            entity_id=uuid.uuid4(),
            ending_id=ending.id,
            stat_def_entity_id=stat_def.entity_id,
            operator=EndingRuleOperator.GTE,
            threshold=80,
            next_op=None,
            order=1,
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[
            StatRuleJudgmentResult(fired_rule_ids=["a1"]),
            EndingJudgmentResult(triggered=True),
        ],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "고백했다"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "statChange", "endingReached", "done"]

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is True
    assert room.ending_entity_id == ending.entity_id


@pytest.mark.parametrize(
    "judgment_error",
    [
        pytest.param(LLMClientError("429 RESOURCE_EXHAUSTED"), id="llm-error"),
        pytest.param(LLMPolicyViolationError("Gemini 가 안전 기준으로 판정 응답을 막았다"), id="safety-block"),
    ],
)
async def test_send_message_stat_judgment_llm_failure_still_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, judgment_error: LLMClientError
) -> None:
    """판정 LLM 실패(429 등)가 SSE 제너레이터 밖으로 새면 ASGI 태스크가 취소되며 요청 스코프 DB
    세션이 강제 종료되고, 망가진 커넥션이 풀로 돌아가 무관한 다음 요청이 500이 된다 — 그래서
    실패를 흡수하고 그 턴의 판정만 포기한다. 이미 스트리밍된 응답은 정상 커밋되어야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, initial_value=50)
    await _add_stat_rule(db_session, stat_def, 20)
    await _add_ending(db_session, setup, turn_count_gate=1)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안", "녕"], structured_results=[judgment_error])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "token", "done"]
    assert events[-1]["finalMessage"]["content"] == "안녕"

    # 스탯 판단이 실패했으니 엔딩 판정까지 통째로 건너뛴다.
    assert fake.generate_structured_calls == [StatRuleJudgmentResult]

    assistant_messages = (
        await db_session.execute(
            sa.select(ChatMessage)
            .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.ASSISTANT)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ).scalars().all()
    # 오프닝 메시지 + 이번 턴의 응답. 판정이 실패해도 응답 자체는 커밋된다.
    assert [message.content for message in assistant_messages] == ["다시 만났네요!", "안녕"]

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 1
    assert room.ending_reached is False

    stat_row = await db_session.get(ChatRoomStat, (room_id, stat_def.entity_id))
    assert stat_row is not None
    assert float(stat_row.current_value) == 50


async def test_send_message_ending_judgment_llm_failure_keeps_stat_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """스탯 판단은 성공하고 엔딩 판정만 실패한 경우 — 이미 계산된 스탯 변경은 그대로 커밋하고
    엔딩 판정만 포기한다(부분 진행 보존)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, initial_value=50)
    await _add_stat_rule(db_session, stat_def, 20)
    await _add_ending(db_session, setup, turn_count_gate=1)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[
            StatRuleJudgmentResult(fired_rule_ids=["a1"]),
            LLMClientError("429 RESOURCE_EXHAUSTED"),
        ],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "statChange", "done"]
    assert fake.generate_structured_calls == [StatRuleJudgmentResult, EndingJudgmentResult]

    stat_row = await db_session.get(ChatRoomStat, (room_id, stat_def.entity_id))
    assert stat_row is not None
    assert float(stat_row.current_value) == 70

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is False
