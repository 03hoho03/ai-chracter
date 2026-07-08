import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import StatChangeJudgment, StatJudgmentResult
from api.db.models import (
    Asset,
    AssetKind,
    CharacterVersionDetail,
    ChatRoomStat,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    KeywordNote,
    ModerationStatus,
    Shortcut,
    SituationalImage,
    StartingSetup,
    StatDef,
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


async def _make_published_story(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID, setting_text: str = "세계관 설정"
) -> Content:
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
            setting_text=setting_text,
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


async def _create_story_room_via_api(
    client: httpx.AsyncClient, content_id: uuid.UUID, starting_setup_id: uuid.UUID
) -> httpx.Response:
    return await client.post(
        "/chat-rooms",
        json={"contentId": str(content_id), "contentType": "story", "startingSetupId": str(starting_setup_id)},
    )


class _FakeLLMClient(LLMClient):
    def __init__(
        self,
        tokens: list[str] | None = None,
        structured_result: StatJudgmentResult | None = None,
    ) -> None:
        self.tokens = tokens or []
        self.structured_result = structured_result
        self.received_prompt: str | None = None
        self.received_judgment_prompt: str | None = None
        self.generate_structured_called = False
        self.generate_structured_calls: list[Any] = []

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        self.received_prompt = prompt
        for token in self.tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None
    ) -> Any:
        self.generate_structured_called = True
        self.generate_structured_calls.append(response_schema)
        self.received_judgment_prompt = prompt
        assert self.structured_result is not None
        return self.structured_result


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


async def test_send_message_story_room_emits_stat_change_and_persists_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안", "녕"],
        structured_result=StatJudgmentResult(
            stat_changes=[StatChangeJudgment(stat_id=str(stat_def.entity_id), new_value=70)]
        ),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "칭찬했다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.generate_structured_called

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "token", "statChange", "done"]
    stat_event = events[2]
    assert stat_event["statId"] == str(stat_def.entity_id)
    assert stat_event["newValue"] == 70

    # 판단용 프롬프트에는 스탯 정의와 이번 턴의 사용자/응답 메시지가 담긴다.
    assert fake.received_judgment_prompt is not None
    assert str(stat_def.entity_id) in fake.received_judgment_prompt
    assert "칭찬했다" in fake.received_judgment_prompt
    assert "안녕" in fake.received_judgment_prompt

    stat_row = await db_session.get(ChatRoomStat, (room_id, stat_def.entity_id))
    assert stat_row is not None
    assert stat_row.current_value == Decimal(70)


async def test_send_message_story_room_clamps_stat_value_to_range(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=StatJudgmentResult(
            stat_changes=[StatChangeJudgment(stat_id=str(stat_def.entity_id), new_value=9999)]
        ),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    stat_event = next(e for e in events if e["type"] == "statChange")
    assert stat_event["newValue"] == 100

    stat_row = await db_session.get(ChatRoomStat, (room_id, stat_def.entity_id))
    assert stat_row is not None
    assert stat_row.current_value == Decimal(100)


async def test_send_message_story_room_unchanged_stat_emits_no_stat_change_event(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    stat_def = await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=StatJudgmentResult(
            stat_changes=[StatChangeJudgment(stat_id=str(stat_def.entity_id), new_value=50)]
        ),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]


async def test_send_message_story_room_ignores_unknown_stat_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=StatJudgmentResult(
            stat_changes=[StatChangeJudgment(stat_id=str(uuid.uuid4()), new_value=10)]
        ),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]


async def test_send_message_story_room_builds_generation_prompt_from_story_setting(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(
        db_session, creator_user_id=user.id, genre_id=genre.id, setting_text="용과 기사단의 세계"
    )
    setup = await _add_starting_setup(db_session, content)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_result=StatJudgmentResult(stat_changes=[]))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "모험을 시작한다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "용과 기사단의 세계" in fake.received_prompt
    assert "옛날 옛적, 낯선 마을에 도착했다." in fake.received_prompt
    assert "다시 만났네요!" in fake.received_prompt
    assert "모험을 시작한다" in fake.received_prompt


async def test_send_message_story_room_injects_matched_keyword_note_hidden_from_client(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            starting_setup_id=None,
            info_text="마법사는 사실 왕자다",
            trigger_keywords=["마법사"],
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_result=StatJudgmentResult(stat_changes=[]))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "저 마법사는 누구야?"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "마법사는 사실 왕자다" in fake.received_prompt

    events = _parse_sse_events(resp.text)
    done_event = next(e for e in events if e["type"] == "done")
    assert "마법사는 사실 왕자다" not in json.dumps(done_event)


async def test_send_message_story_room_ignores_keyword_note_scoped_to_other_starting_setup(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    other_setup = await _add_starting_setup(db_session, content)
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            starting_setup_id=other_setup.id,
            info_text="다른 시작설정 전용 정보",
            trigger_keywords=["마법사"],
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_result=StatJudgmentResult(stat_changes=[]))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "저 마법사는 누구야?"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "다른 시작설정 전용 정보" not in fake.received_prompt


async def test_send_message_story_room_with_valid_shortcut_id_injects_shortcut_prompt(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="수색",
        description="주변을 수색한다",
        prompt="플레이어가 주변을 자세히 수색하는 상황을 묘사하라",
    )
    db_session.add(shortcut)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_result=StatJudgmentResult(stat_changes=[]))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(
            f"/chat-rooms/{room_id}/messages",
            json={"content": "/수색", "shortcutId": str(shortcut.entity_id)},
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "플레이어가 주변을 자세히 수색하는 상황을 묘사하라" in fake.received_prompt


async def test_send_message_story_room_with_unknown_shortcut_id_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(
            f"/chat-rooms/{room_id}/messages",
            json={"content": "/수색", "shortcutId": str(uuid.uuid4())},
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 400
    assert fake.received_prompt is None


async def test_send_message_story_room_with_shortcut_id_from_other_content_version_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    other_content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    other_shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=other_content.current_published_version_id,
        name="다른 작품 단축어",
        description="설명",
        prompt="다른 작품 전용 프롬프트",
    )
    db_session.add(other_shortcut)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(
            f"/chat-rooms/{room_id}/messages",
            json={"content": "메시지", "shortcutId": str(other_shortcut.entity_id)},
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 400


async def test_send_message_character_room_does_not_call_generate_structured(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = Content(
        creator_user_id=user.id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
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
    thumbnail = await _make_asset(db_session, owner_user_id=user.id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()
    content.current_published_version_id = version.id
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID(
        (
            await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
        ).json()["id"]
    )

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert not fake.generate_structured_called
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]

    stat_rows = (
        await db_session.execute(sa.select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room_id))
    ).scalars().all()
    assert stat_rows == []


async def test_send_message_story_room_ignores_situational_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """US-072 AC4: 스토리 챗은 상황별 이미지 매칭 판단 단계 자체가 호출되지 않는다 — 같은
    content_version_id에 SituationalImage(캐릭터 전용 개념)가 등록돼 있어도 무관하다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await _add_stat_def(db_session, setup, min_value=0, max_value=100, initial_value=50)
    assert content.current_published_version_id is not None
    image_asset = await _make_asset(db_session, owner_user_id=user.id)
    blurred_asset = await _make_asset(db_session, owner_user_id=user.id)
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            image_asset_id=image_asset.id,
            blurred_asset_id=blurred_asset.id,
            trigger_condition="조건",
            order=0,
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"], structured_result=StatJudgmentResult(stat_changes=[]))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    # 스탯 판단 한 번만 호출되고, 이미지 매칭 판단은 추가로 호출되지 않는다.
    assert fake.generate_structured_calls == [StatJudgmentResult]

    done_event = _parse_sse_events(resp.text)[-1]
    assert done_event["finalMessage"]["imageId"] is None
