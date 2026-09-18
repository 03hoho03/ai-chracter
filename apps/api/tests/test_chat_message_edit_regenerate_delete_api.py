import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone, UTC
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import ImageMatchJudgmentResult, StatJudgmentResult
from api.db.models import (
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
    ModerationStatus,
    SituationalImage,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
)
from api.chat import router as chat_router
from api.llm.client import LLMClient, LLMClientError, LLMPolicyViolationError
from factories import (
    _clear_llm_override,
    _FakeLLMClient as _StructuredFakeLLMClient,
    _get_genre,
    _login_as,
    _make_asset,
    _make_published_story,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
)


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
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
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
            example_dialogues=[],
            character_prompt="프롬프트",
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


async def _create_room_via_api(client: httpx.AsyncClient, content_id: uuid.UUID) -> httpx.Response:
    return await client.post("/chat-rooms", json={"contentId": str(content_id), "contentType": "character"})


async def _create_story_room_via_api(
    client: httpx.AsyncClient, content_id: uuid.UUID, starting_setup_id: uuid.UUID
) -> httpx.Response:
    return await client.post(
        "/chat-rooms",
        json={"contentId": str(content_id), "contentType": "story", "startingSetupId": str(starting_setup_id)},
    )


class _FakeLLMClient(LLMClient):
    def __init__(self, tokens: list[str] | None = None, error: Exception | None = None) -> None:
        self.tokens = tokens or []
        self.error = error
        self.received_prompt: str | None = None
        self.received_system_instruction: str | None = None
        self.generate_structured_called = False

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
    ) -> AsyncIterator[str]:
        self.received_prompt = prompt
        self.received_system_instruction = system_instruction
        if self.error is not None:
            raise self.error
        for token in self.tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None
    ) -> Any:
        self.generate_structured_called = True
        raise NotImplementedError


class _QueuedFakeLLMClient(LLMClient):
    """스토리 챗처럼 한 턴 안에서 여러 번 `generate_structured`가 호출될 수 있는 경우를 위한,
    호출 순서대로 소비되는 큐 기반 fake(`test_chat_ending_pipeline_api.py`와 동일 패턴)."""

    def __init__(self, tokens: list[str], structured_results: list[Any]) -> None:
        self.tokens = tokens
        self._structured_results = list(structured_results)
        self.generate_structured_calls: list[Any] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
    ) -> AsyncIterator[str]:
        for token in self.tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None
    ) -> Any:
        self.generate_structured_calls.append(response_schema)
        return self._structured_results.pop(0)


async def _send_message(client: httpx.AsyncClient, room_id: uuid.UUID, content: str, tokens: list[str]) -> None:
    _override_llm_client(_FakeLLMClient(tokens=tokens))
    try:
        resp = await client.post(f"/chat-rooms/{room_id}/messages", json={"content": content})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200


async def _room_messages(db_session: AsyncSession, room_id: uuid.UUID) -> list[ChatMessage]:
    # created_at 은 한 트랜잭션 안에서 전부 같은 값이라 동률 정렬이 임의다 — 위치 인덱스 대신 content 로 고를 것.
    return list(
        (
            await db_session.execute(
                sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id).order_by(ChatMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


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


# ---------------------------------------------------------------------------
# regenerate
# ---------------------------------------------------------------------------


async def test_regenerate_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/regenerate")
    assert resp.status_code == 401


async def test_regenerate_unknown_room_returns_404(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/regenerate")
    finally:
        _clear_llm_override()
    assert resp.status_code == 404


async def test_regenerate_other_user_room_returns_403(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
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
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()
    assert resp.status_code == 403


async def test_regenerate_opening_only_room_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400


async def test_regenerate_last_message_not_assistant_returns_400(
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

    # LLM 실패로 사용자 메시지만 저장되고 AI 응답은 없는 상태를 만든다.
    _override_llm_client(_FakeLLMClient(error=LLMClientError("network down")))
    try:
        await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    # apps/api/CLAUDE.md §테스트 인프라: 한 트랜잭션 안의 created_at은 전부 같은 값이라
    # (오프닝 메시지와 방금 저장된 사용자 메시지가 동률) `_regeneratable_last_message_dependency`
    # 의 `ORDER BY created_at ASC`가 어느 쪽을 "마지막"으로 볼지 임의다 — 사용자 메시지를
    # 명시적으로 나중 시각으로 밀어 "마지막 메시지가 user"라는 이 테스트의 전제를 고정한다.
    user_message = next(m for m in await _room_messages(db_session, room_id) if m.content == "안녕")
    await db_session.execute(
        sa.update(ChatMessage)
        .where(ChatMessage.id == user_message.id)
        .values(created_at=user_message.created_at + timedelta(seconds=1))
    )
    await db_session.commit()

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400


async def test_regenerate_replaces_last_assistant_message_without_new_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="안녕!")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    await _send_message(db_client, room_id, "반가워", ["원래", "응답"])

    fake = _FakeLLMClient(tokens=["새로운", "응답"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    token_events = [e for e in events if e["type"] == "token"]
    assert [e["delta"] for e in token_events] == ["새로운", "응답"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["finalMessage"]["content"] == "새로운응답"

    # 이미지 매칭은 재실행되지만(situational-image-goal-prompt.md SI-4) 이 방엔 등록된 이미지가
    # 없어 `_match_situational_image`가 판정 호출 없이 반환한다 — 그래서 `generate_structured`는
    # 불리지 않아야 한다.
    assert not fake.generate_structured_called
    assert fake.received_prompt is not None
    assert "원래" not in fake.received_prompt
    assert "반가워" in fake.received_prompt

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 1  # 새 턴이 아니므로 증가하지 않는다

    messages = await _room_messages(db_session, room_id)
    assert len(messages) == 3  # 오프닝 + 사용자 메시지 + (교체된) AI 응답
    assert messages[1].role == ChatMessageRole.USER
    assert messages[1].content == "반가워"
    assert messages[2].role == ChatMessageRole.ASSISTANT
    assert messages[2].content == "새로운응답"


async def test_regenerate_story_room_selects_template_instruction(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """chat-techspec.md §4-2 — `regenerate_message`(`_build_prompt` 경유) 호출부도 `_stream_new_turn`과
    같은 `story_detail.prompt_template`을 골라야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(
        db_session, creator_user_id=user.id, genre_id=genre.id, prompt_template=StoryPromptTemplate.EMOTIONAL
    )
    setup = await _add_starting_setup(db_session, content)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    _override_llm_client(
        _QueuedFakeLLMClient(tokens=["원래", "응답"], structured_results=[StatJudgmentResult(stat_changes=[])])
    )
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    fake = _FakeLLMClient(tokens=["새로운", "응답"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_system_instruction is not None
    assert (
        "인물의 감정 변화는 장면 안의 단서로 드러난다 — 표정, 손짓, 목소리의 결. "
        "침묵도 반응이며, 그 침묵이 무엇을 뜻하는지 장면이 알려 준다." in fake.received_system_instruction
    )


async def test_regenerate_policy_violation_keeps_original_message(
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
    await _send_message(db_client, room_id, "반가워", ["원래응답"])

    _override_llm_client(_FakeLLMClient(error=LLMPolicyViolationError("blocked")))
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["policyWarning"]

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 1

    messages = await _room_messages(db_session, room_id)
    assert len(messages) == 3
    assert messages[2].role == ChatMessageRole.ASSISTANT
    assert messages[2].content == "원래응답"


async def test_regenerate_llm_error_keeps_original_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """monitoring-techspec.md MT-6: 이 흡수(원래 응답 유지)는 그대로 두되, `regenerate_message`도
    `_stream_new_turn`과 같은 `gemini` 태그로 Bugsink 이벤트에 승격돼야 한다 — 형제 경로지만
    사용자 흐름이 달라 아직 검증되지 않았다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    await _send_message(db_client, room_id, "반가워", ["원래응답"])

    _override_llm_client(_FakeLLMClient(error=LLMClientError("network down")))
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["error"]
    assert len(captured) == 1
    assert isinstance(captured[0][0], LLMClientError)
    assert captured[0][1] == "gemini"

    messages = await _room_messages(db_session, room_id)
    assert len(messages) == 3
    assert messages[2].content == "원래응답"


async def test_regenerate_reruns_image_matching_and_stores_new_image_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """situational-image-goal-prompt.md SI-4 — `regenerate_message` docstring의 "이미지 매칭도
    재실행하지 않는다" 문장이 깨진다: 재생성은 새 응답 텍스트에 맞춰 이미지 매칭을 다시 돌아
    다른 이미지가 매칭될 수 있다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version_id = content.current_published_version_id
    assert version_id is not None
    image_a = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=0
    )
    image_b = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=1
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    _override_llm_client(
        _StructuredFakeLLMClient(
            tokens=["원래", "응답"],
            structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image_a.entity_id)),
        )
    )
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    _override_llm_client(
        _StructuredFakeLLMClient(
            tokens=["새로운", "응답"],
            structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image_b.entity_id)),
        )
    )
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    done_event = _parse_sse_events(resp.text)[-1]
    assert done_event["finalMessage"]["imageId"] == str(image_b.entity_id)
    assert done_event["finalMessage"]["imageUrl"].startswith("http")

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 1  # 재생성은 새 턴이 아니다

    messages = await _room_messages(db_session, room_id)
    assert len(messages) == 3  # 오프닝 + 사용자 메시지 + (교체된) AI 응답
    assistant_message = next(m for m in messages if m.content == "새로운응답")
    assert assistant_message.image_id == image_b.entity_id
    assert not any(m.content == "원래응답" for m in messages)

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert {e.image_entity_id for e in exposures} == {image_a.entity_id, image_b.entity_id}


async def test_regenerate_image_matching_failure_replaces_message_without_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """situational-image-goal-prompt.md SI-4 — 이미지 매칭 실패는 판정 실패와 같은 흡수 경로를
    탄다: 스트림은 정상 종료되고 새 응답 텍스트는 그대로 교체되지만 image_id는 None으로
    남는다(원래 매칭된 이미지를 이월하지 않는다)."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version_id = content.current_published_version_id
    assert version_id is not None
    image_a = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=0
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    _override_llm_client(
        _StructuredFakeLLMClient(
            tokens=["원래응답"],
            structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image_a.entity_id)),
        )
    )
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    _override_llm_client(
        _StructuredFakeLLMClient(tokens=["새응답"], structured_error=LLMClientError("judgment down"))
    )
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events if e["type"] != "token"] == ["done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["content"] == "새응답"
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    assert len(captured) == 1
    assert isinstance(captured[0][0], LLMClientError)
    assert captured[0][1] == "gemini"

    messages = await _room_messages(db_session, room_id)
    assert len(messages) == 3
    assistant_message = next(m for m in messages if m.content == "새응답")
    assert assistant_message.image_id is None
    assert not any(m.content == "원래응답" for m in messages)

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert len(exposures) == 1
    assert exposures[0].image_entity_id == image_a.entity_id


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


async def test_edit_message_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(
        f"/chat-rooms/{uuid.uuid4()}/messages/{uuid.uuid4()}", json={"content": "수정"}
    )
    assert resp.status_code == 401


async def test_edit_message_unknown_message_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.patch(
            f"/chat-rooms/{room_id}/messages/{uuid.uuid4()}", json={"content": "수정"}
        )
    finally:
        _clear_llm_override()
    assert resp.status_code == 404


async def test_edit_message_on_assistant_message_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="인트로")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    messages = await _room_messages(db_session, room_id)
    opening_message_id = messages[0].id

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.patch(
            f"/chat-rooms/{room_id}/messages/{opening_message_id}", json={"content": "수정"}
        )
    finally:
        _clear_llm_override()
    assert resp.status_code == 400


async def test_edit_message_truncates_and_regenerates_from_edit_point(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="안녕!")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    await _send_message(db_client, room_id, "안녕", ["봇1"])
    await _send_message(db_client, room_id, "안녕2", ["봇2"])

    messages_before = await _room_messages(db_session, room_id)
    assert len(messages_before) == 5  # 오프닝 + (사용자+AI) * 2
    first_user_message_id = next(m.id for m in messages_before if m.content == "안녕")

    fake = _FakeLLMClient(tokens=["수정후응답"])
    _override_llm_client(fake)
    try:
        resp = await db_client.patch(
            f"/chat-rooms/{room_id}/messages/{first_user_message_id}", json={"content": "수정된 메시지"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["finalMessage"]["content"] == "수정후응답"

    assert fake.received_prompt is not None
    assert "수정된 메시지" in fake.received_prompt
    assert "봇1" not in fake.received_prompt
    assert "안녕2" not in fake.received_prompt
    assert "봇2" not in fake.received_prompt

    messages_after = await _room_messages(db_session, room_id)
    assert len(messages_after) == 3  # 오프닝 + 수정된 사용자 메시지 + 새 AI 응답
    assert messages_after[1].id == first_user_message_id
    assert messages_after[1].content == "수정된 메시지"
    assert messages_after[2].role == ChatMessageRole.ASSISTANT
    assert messages_after[2].content == "수정후응답"

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    # 원래 turn_count=2였고, 트레일링에서 AI 응답 2개(봇1, 봇2)가 삭제된 뒤 이번 턴 하나가
    # 새로 생성되어 순대 결과는 1이어야 한다(실제 남은 대화 길이와 일치).
    assert room.turn_count == 1


async def test_edit_message_reruns_image_matching_with_new_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """situational-image-goal-prompt.md SI-4/SI-5 — `edit_message`는 코드 변경 없이(`_stream_new_turn`
    을 그대로 재사용해) 편집된 사용자 메시지에 맞춰 이미지 매칭을 다시 돈다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="안녕!")
    version_id = content.current_published_version_id
    assert version_id is not None
    image_a = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=0
    )
    image_b = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=1
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    _override_llm_client(
        _StructuredFakeLLMClient(
            tokens=["원래응답"],
            structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image_a.entity_id)),
        )
    )
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    messages_before = await _room_messages(db_session, room_id)
    user_message_id = next(m.id for m in messages_before if m.content == "반가워")

    _override_llm_client(
        _StructuredFakeLLMClient(
            tokens=["수정후응답"],
            structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image_b.entity_id)),
        )
    )
    try:
        resp = await db_client.patch(
            f"/chat-rooms/{room_id}/messages/{user_message_id}", json={"content": "수정된 메시지"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    done_event = _parse_sse_events(resp.text)[-1]
    assert done_event["finalMessage"]["imageId"] == str(image_b.entity_id)
    assert done_event["finalMessage"]["imageUrl"].startswith("http")

    messages_after = await _room_messages(db_session, room_id)
    assistant_message = next(m for m in messages_after if m.content == "수정후응답")
    assert assistant_message.image_id == image_b.entity_id

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert {e.image_entity_id for e in exposures} == {image_a.entity_id, image_b.entity_id}


async def test_edit_message_on_story_room_reruns_stat_judgment_and_keeps_turn_count_consistent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await _add_stat_def(db_session, setup)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_story_room_via_api(db_client, content.id, setup.id)).json()["id"])

    for turn_text in ["행동1", "행동2"]:
        fake = _QueuedFakeLLMClient(tokens=["진행"], structured_results=[StatJudgmentResult(stat_changes=[])])
        _override_llm_client(fake)
        try:
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": turn_text})
        finally:
            _clear_llm_override()
        assert resp.status_code == 200

    messages_before = await _room_messages(db_session, room_id)
    assert len(messages_before) == 5
    first_user_message_id = next(m.id for m in messages_before if m.content == "행동1")

    fake = _QueuedFakeLLMClient(tokens=["수정후진행"], structured_results=[StatJudgmentResult(stat_changes=[])])
    _override_llm_client(fake)
    try:
        resp = await db_client.patch(
            f"/chat-rooms/{room_id}/messages/{first_user_message_id}", json={"content": "수정된 행동"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.generate_structured_calls == [StatJudgmentResult]  # 판단 단계가 새 턴에서 재실행됨

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.turn_count == 1

    messages_after = await _room_messages(db_session, room_id)
    assert len(messages_after) == 3


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


async def test_delete_message_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.delete(f"/chat-rooms/{uuid.uuid4()}/messages/{uuid.uuid4()}")
    assert resp.status_code == 401


async def test_delete_message_unknown_room_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.delete(f"/chat-rooms/{uuid.uuid4()}/messages/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_delete_message_other_user_room_returns_403(
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
    resp = await db_client.delete(f"/chat-rooms/{room_id}/messages/{uuid.uuid4()}")
    assert resp.status_code == 403


async def test_delete_message_unknown_message_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    resp = await db_client.delete(f"/chat-rooms/{room_id}/messages/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_delete_message_removes_user_and_assistant_messages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="안녕!")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    await _send_message(db_client, room_id, "안녕", ["봇 응답"])

    messages = await _room_messages(db_session, room_id)
    assert len(messages) == 3
    user_message_id = next(m.id for m in messages if m.content == "안녕")
    assistant_message_id = next(m.id for m in messages if m.content == "봇 응답")

    resp = await db_client.delete(f"/chat-rooms/{room_id}/messages/{user_message_id}")
    assert resp.status_code == 204

    resp = await db_client.delete(f"/chat-rooms/{room_id}/messages/{assistant_message_id}")
    assert resp.status_code == 204

    remaining = await _room_messages(db_session, room_id)
    assert len(remaining) == 1
    assert remaining[0].content == "안녕!"
