import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, StatChangeJudgment, StatJudgmentResult
from api.db.models import (
    Asset,
    AssetKind,
    ChatRoom,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Ending,
    EndingRule,
    EndingRuleOperator,
    Genre,
    ModerationStatus,
    StartingSetup,
    StatDef,
    StoryEndingUnlock,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.main import app


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(timezone.utc),
        "privacy_agreed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_asset(db_session: AsyncSession, *, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(owner_user_id=owner_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL)
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_published_story(db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(timezone.utc), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, owner_user_id=creator_user_id)
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name="스토리",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text="세계관 설정",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


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


async def _create_story_room_via_api(
    client: httpx.AsyncClient, content_id: uuid.UUID, starting_setup_id: uuid.UUID
) -> httpx.Response:
    return await client.post(
        "/chat-rooms",
        json={"contentId": str(content_id), "contentType": "story", "startingSetupId": str(starting_setup_id)},
    )


class _FakeLLMClient(LLMClient):
    """`StatJudgmentResult`(스탯 판단)와 `EndingJudgmentResult`(엔딩 판정)가 한 턴 안에서
    순서대로 여러 번 호출될 수 있으므로, 고정된 단일 응답이 아니라 호출 순서대로 소비되는
    큐를 쓴다(test_chat_story_message_send_api.py의 단일-응답 `_FakeLLMClient`와 다른 점)."""

    def __init__(self, tokens: list[str], structured_results: list[Any]) -> None:
        self.tokens = tokens
        self._structured_results = list(structured_results)
        self.generate_structured_calls: list[Any] = []

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        for token in self.tokens:
            yield token

    async def generate_structured(self, prompt: str, response_schema: Any) -> Any:
        self.generate_structured_calls.append(response_schema)
        return self._structured_results.pop(0)


def _override_llm_client(fake: _FakeLLMClient) -> None:
    app.dependency_overrides[get_llm_client] = lambda: fake


def _clear_llm_override() -> None:
    app.dependency_overrides.pop(get_llm_client, None)


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    events = []
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


async def test_send_message_reaches_ending_when_judgment_triggers_with_no_stat_rules(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    ending = await _add_ending(db_session, setup, turn_count_gate=1)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안", "녕"],
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
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

    fake = _FakeLLMClient(tokens=["안녕"], structured_results=[StatJudgmentResult(stat_changes=[])])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    # 스탯 판단 1회만 호출되고, 엔딩 판정(턴게이트 미통과)은 호출조차 되지 않는다.
    assert fake.generate_structured_calls == [StatJudgmentResult]

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is False


async def test_send_message_ending_not_reached_when_stat_rule_fails_despite_llm_trigger(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
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
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.ending_reached is False


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
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
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
    assert fake.generate_structured_calls == [StatJudgmentResult, EndingJudgmentResult]

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
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
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
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
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
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
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
            StatJudgmentResult(stat_changes=[StatChangeJudgment(stat_id=str(stat_def.entity_id), new_value=90)]),
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
