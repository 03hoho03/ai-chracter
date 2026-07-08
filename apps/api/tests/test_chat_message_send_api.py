import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import ImageMatchJudgmentResult
from api.db.models import (
    Asset,
    AssetKind,
    CharacterImageExposure,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    SituationalImage,
    User,
)
from api.llm.client import LLMClient, LLMClientError, LLMPolicyViolationError
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


async def _make_published_character(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID, intro: str = "인트로"
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
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
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro=intro,
            example_dialogues=[{"userLine": "밥 먹었어?", "characterLine": "아직이야옹"}],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _create_room_via_api(client: httpx.AsyncClient, content_id: uuid.UUID) -> httpx.Response:
    return await client.post("/chat-rooms", json={"contentId": str(content_id), "contentType": "character"})


async def _make_situational_image(
    db_session: AsyncSession,
    *,
    content_version_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    order: int,
    trigger_condition: str = "조건",
) -> SituationalImage:
    image_asset = await _make_asset(db_session, owner_user_id=owner_user_id)
    blurred_asset = await _make_asset(db_session, owner_user_id=owner_user_id)
    situational_image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=content_version_id,
        image_asset_id=image_asset.id,
        blurred_asset_id=blurred_asset.id,
        trigger_condition=trigger_condition,
        order=order,
    )
    db_session.add(situational_image)
    await db_session.flush()
    return situational_image


class _FakeLLMClient(LLMClient):
    def __init__(
        self,
        tokens: list[str] | None = None,
        error: Exception | None = None,
        structured_result: ImageMatchJudgmentResult | None = None,
    ) -> None:
        self.tokens = tokens or []
        self.error = error
        self.structured_result = structured_result
        self.received_prompt: str | None = None
        self.received_judgment_prompt: str | None = None
        self.generate_structured_called = False

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        self.received_prompt = prompt
        if self.error is not None:
            raise self.error
        for token in self.tokens:
            yield token

    async def generate_structured(self, prompt: str, response_schema: Any) -> Any:
        self.generate_structured_called = True
        self.received_judgment_prompt = prompt
        if self.structured_result is None:
            raise NotImplementedError
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


async def test_send_message_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/messages", json={"content": "안녕"})
    assert resp.status_code == 401


async def test_send_message_unknown_room_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    # FastAPI resolves every Depends() (including get_llm_client) before the route
    # body runs, even though this request never reaches the LLM call.
    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 404


async def test_send_message_other_user_room_returns_403(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=owner.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    await _login_as(db_client, other.id)
    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 403


async def test_send_message_streams_tokens_and_saves_final_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=genre.id, intro="안녕!"
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안", "녕", "하세요"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(resp.text)
    token_events = [e for e in events if e["type"] == "token"]
    assert [e["delta"] for e in token_events] == ["안", "녕", "하세요"]

    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    final_message = done_events[0]["finalMessage"]
    assert final_message["role"] == "assistant"
    assert final_message["content"] == "안녕하세요"

    # 캐릭터 프롬프트 + 예시 대화 + 오프닝 메시지(히스토리) + 방금 보낸 사용자 메시지가 프롬프트에 포함된다.
    assert fake.received_prompt is not None
    assert "프롬프트" in fake.received_prompt
    assert "밥 먹었어?" in fake.received_prompt
    assert "안녕!" in fake.received_prompt
    assert "반가워" in fake.received_prompt

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 1

    messages = (
        await db_session.execute(
            sa.select(ChatMessage)
            .where(ChatMessage.chat_room_id == room_id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    # 오프닝 메시지 + 사용자 메시지 + AI 응답
    assert len(messages) == 3
    assert messages[1].role == ChatMessageRole.USER
    assert messages[1].content == "반가워"
    assert messages[2].role == ChatMessageRole.ASSISTANT
    assert messages[2].content == "안녕하세요"


async def test_send_message_policy_violation_emits_policy_warning_and_skips_save(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(error=LLMPolicyViolationError("blocked"))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "부적절한 메시지"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["policyWarning"]

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 0

    messages = (
        await db_session.execute(sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id))
    ).scalars().all()
    # 오프닝 메시지 + 사용자 메시지만 저장되고, AI 응답은 저장되지 않는다.
    assert len(messages) == 2
    assert {m.role for m in messages} == {ChatMessageRole.ASSISTANT, ChatMessageRole.USER}


async def test_send_message_llm_error_emits_error_event_and_keeps_user_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(error=LLMClientError("network down"))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["error"]

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 0

    messages = (
        await db_session.execute(
            sa.select(ChatMessage)
            .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER)
        )
    ).scalars().all()
    assert len(messages) == 1
    assert messages[0].content == "안녕"


async def test_send_message_no_situational_images_skips_judgment_call(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert not fake.generate_structured_called
    done_event = _parse_sse_events(resp.text)[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None


async def test_send_message_matched_situational_image_included_in_done_event_and_records_exposure(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version_id = content.current_published_version_id
    assert version_id is not None
    low_priority = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=1
    )
    high_priority = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=0
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(high_priority.entity_id)),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안아줘"})
    finally:
        _clear_llm_override()

    assert fake.generate_structured_called
    # 우선순위(order)가 낮은(=높은 우선순위) 이미지가 먼저 나열되어야 한다(동시 매칭 시
    # 최상위 하나만 고르도록 유도하는 프롬프트 지시, techspec-chat-character.md §1.1).
    assert fake.received_judgment_prompt is not None
    assert fake.received_judgment_prompt.index(str(high_priority.entity_id)) < fake.received_judgment_prompt.index(
        str(low_priority.entity_id)
    )

    done_event = _parse_sse_events(resp.text)[-1]
    assert done_event["finalMessage"]["imageId"] == str(high_priority.entity_id)
    assert done_event["finalMessage"]["imageUrl"].startswith("http")

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert len(exposures) == 1
    assert exposures[0].user_id == user.id
    assert exposures[0].image_entity_id == high_priority.entity_id


async def test_send_message_no_matched_image_returns_null_imageid_and_no_exposure(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version_id = content.current_published_version_id
    assert version_id is not None
    await _make_situational_image(db_session, content_version_id=version_id, owner_user_id=user.id, order=0)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"], structured_result=ImageMatchJudgmentResult(matched_image_entity_id=None)
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert fake.generate_structured_called
    done_event = _parse_sse_events(resp.text)[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert exposures == []


async def test_send_message_hallucinated_image_entity_id_is_ignored(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version_id = content.current_published_version_id
    assert version_id is not None
    await _make_situational_image(db_session, content_version_id=version_id, owner_user_id=user.id, order=0)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(uuid.uuid4())),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    done_event = _parse_sse_events(resp.text)[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert exposures == []


async def test_send_message_repeated_match_does_not_duplicate_exposure_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version_id = content.current_published_version_id
    assert version_id is not None
    image = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=0
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    for _ in range(2):
        fake = _FakeLLMClient(
            tokens=["안녕"],
            structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image.entity_id)),
        )
        _override_llm_client(fake)
        try:
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "또 안아줘"})
        finally:
            _clear_llm_override()
        assert resp.status_code == 200

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert len(exposures) == 1
    assert exposures[0].image_entity_id == image.entity_id
