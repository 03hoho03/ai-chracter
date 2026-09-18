import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat.prompt_builder import ImageMatchJudgmentResult
from api.core.config import settings
from api.db.models import (
    Asset,
    CharacterImageExposure,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    SituationalImage,
)
from api.llm.client import LLMClientError, LLMPolicyViolationError
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_asset,
    _make_published_character,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
    _read_golden_prompt,
)


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
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """monitoring-techspec.md MT-6: 이 흡수(에러 이벤트만 보여주고 사용자 메시지는 유지)는
    그대로 두되, Gemini 실패를 Bugsink 이벤트로도 승격해야 한다 — 안 그러면 채팅 생성이
    통째로 죽어도 로그를 직접 뒤지기 전엔 아무도 모른다."""
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

    fake = _FakeLLMClient(error=LLMClientError("network down"))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["error"]
    assert len(captured) == 1
    assert isinstance(captured[0][0], LLMClientError)
    assert captured[0][1] == "gemini"

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


async def test_send_message_image_judgment_llm_failure_still_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상황별 이미지 매칭 판단이 실패해도(429 등) 예외가 SSE 제너레이터 밖으로 새면 안 된다 —
    새면 ASGI 태스크 취소로 DB 커넥션이 망가진 채 풀로 돌아가 무관한 다음 요청이 500이 된다.
    이미 스트리밍된 응답은 정상 커밋하고 이미지 매칭만 포기한다."""
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

    fake = _FakeLLMClient(tokens=["안녕"], structured_error=LLMClientError("429 RESOURCE_EXHAUSTED"))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["content"] == "안녕"
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    assistant_messages = (
        await db_session.execute(
            sa.select(ChatMessage).where(
                ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.ASSISTANT
            )
        )
    ).scalars().all()
    # 오프닝 메시지(intro) + 이번 턴의 응답. 판정이 실패해도 응답 자체는 커밋된다.
    assert [message.content for message in assistant_messages] == ["인트로", "안녕"]

    exposures = (
        await db_session.execute(
            sa.select(CharacterImageExposure).where(CharacterImageExposure.content_id == content.id)
        )
    ).scalars().all()
    assert exposures == []


async def test_send_message_null_image_asset_id_candidate_excluded_from_judgment_prompt(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """sse-assert-goal-prompt.md SA-3/CP-3 판정① — `_match_situational_image`의 매칭 필터
    (N-2, `image_asset_id IS NOT NULL`)가 NULL 후보를 판단 프롬프트에 싣기 전에 걸러낸다
    (F-5: 발행 검증이 `situational_images.image_asset_id`를 보지 않아 NULL이 발행본까지
    간다). `image_asset_id`가 NULL인 후보만 있으면 `_match_situational_image`가 판단 호출
    자체를 생략해(`if not situational_images: return None`) 이 필터의 효과를 관측할 수
    없으므로, 정상 후보를 하나 더 둬 판단 호출이 실제로 일어나게 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version_id = content.current_published_version_id
    assert version_id is not None
    normal_image = await _make_situational_image(
        db_session, content_version_id=version_id, owner_user_id=user.id, order=0
    )
    null_image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=version_id,
        image_asset_id=None,
        trigger_condition="조건",
        order=1,
    )
    db_session.add(null_image)
    await db_session.flush()
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=ImageMatchJudgmentResult(matched_image_entity_id=None),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.generate_structured_called
    assert fake.received_judgment_prompt is not None
    # 필터 적용 전에는 이 단언이 거짓이었다(null_image.entity_id가 프롬프트에 실려 있었다) —
    # 처방 전/후로 실제로 다른 값이 나오는 판정이다.
    assert str(null_image.entity_id) not in fake.received_judgment_prompt
    assert str(normal_image.entity_id) in fake.received_judgment_prompt


async def test_send_message_presigned_url_failure_still_completes_the_turn_without_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sse-assert-goal-prompt.md SA-3/CP-3 판정② — 본문 가드(N-3)가 필터를 통과한 뒤에
    생기는 S3 presign 실패를 흡수한다. 이 케이스는 필터로는 안 막힌다(SA-3 표의 "겹치지
    않는다") — `SituationalImage.image_asset_id`는 정상적으로 채워져 있고 매칭도 성공했는데
    `generate_presigned_get_url`만 실패하는 상황이다. `done` 이벤트가 이미지 없이 정상적으로
    나가고 스트림이 정상 종료돼야 한다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    def _raise_presign(storage_key: str) -> str:
        raise RuntimeError("s3 presign boom")

    monkeypatch.setattr(chat_router, "generate_presigned_get_url", _raise_presign)

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

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image.entity_id)),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안아줘"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    assert len(captured) == 1
    assert isinstance(captured[0][0], RuntimeError)

    # F-16 스모크 — 실패가 이 요청 안에 갇혔다는 신호로만 쓴다(항진명제, 판정 근거 아님).
    # 같은 세션으로 다른 쿼리가 여전히 정상 동작한다.
    still_alive = await db_session.scalar(sa.select(sa.func.count()).select_from(Content))
    assert still_alive == 1


async def test_send_message_asset_lookup_failure_still_completes_the_turn_without_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sse-assert-goal-prompt.md SA-3/CP-3 판정③ — 본문 가드(N-3)가 `db.get(Asset, ...)`
    실패도 같은 형태로 흡수한다. `situational_images.image_asset_id` → `assets.id`에 FK가
    걸려 있어 실제로는 이 실패가 도달 불가능하지만(F-7 ②, 참조된 자산을 지우면 orphan이
    아니라 IntegrityError가 난다), 가드가 "어떤 예외든" 흡수하는지는 별도로 확인해야 한다.
    `AsyncSession.get`을 `Asset` 조회에서만 실패하도록 monkeypatch해 재현한다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    original_get = AsyncSession.get

    async def _failing_get(self: AsyncSession, entity: Any, ident: Any, **kwargs: Any) -> Any:
        if entity is Asset:
            raise RuntimeError("asset lookup boom")
        return await original_get(self, entity, ident, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", _failing_get)

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

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image.entity_id)),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안아줘"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    assert len(captured) == 1
    assert isinstance(captured[0][0], RuntimeError)


async def test_send_message_situational_image_candidate_query_failure_still_completes_the_turn_without_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sse-assert-goal-prompt.md SA-4/CP-4 판정② — `_match_situational_image`의 후보 조회
    (`db.scalars(select(SituationalImage)...)`)가 실패해도 이번 턴의 이미지 매칭만 포기하고
    스트림은 done까지 정상 종료된다. 이 호출은 CP-3의 본문 가드(`:873~907`) 밖에 있고,
    호출부(`_stream_new_turn`)의 기존 `except (LLMClientError, PromptRenderError)`는 DB
    예외를 잡지 않는다(F-6) — 함수 자신이 흡수해야 한다.

    ⚠️ **이 테스트가 재는 것과 못 재는 것**(적대적 리뷰, sse-assert-progress.md SP-127
    참고): `AsyncSession.scalars`를 몽키패치해 순수 파이썬에서 `SQLAlchemyError`를 던진다 —
    `except SQLAlchemyError`가 그 타입을 잡는지와 흡수 후 done 이벤트 모양은 재지만, 실제
    SQL이 안 나가 Postgres 트랜잭션이 진짜로 aborted되지 않는다. 그래서 가드 흡수 **직후의
    `await db.commit()`이 aborted 트랜잭션에 부딪혀 재실패하는 결함**은 이 테스트로는
    원리적으로 재현 불가능하다(초록이 착시) — 그 결함은 아래
    `test_send_message_situational_image_candidate_query_real_sql_failure_is_isolated_by_savepoint`가
    `SELECT 1/0`으로 실제 SQL을 태워 재는 별도 테스트다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    original_scalars = AsyncSession.scalars

    async def _failing_scalars(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if statement.column_descriptions[0]["entity"] is SituationalImage:
            raise sa.exc.SQLAlchemyError("situational image lookup boom")
        return await original_scalars(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalars", _failing_scalars)

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

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안아줘"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None
    # 후보 조회가 실패해 판단 호출 자체가 생략된다.
    assert not fake.generate_structured_called

    assert len(captured) == 1
    assert isinstance(captured[0][0], sa.exc.SQLAlchemyError)
    assert captured[0][1] == "db"

    # F-16 스모크 — 실패가 이 요청 안에 갇혔다는 신호로만 쓴다(항진명제, 판정 근거 아님).
    still_alive = await db_session.scalar(sa.select(sa.func.count()).select_from(Content))
    assert still_alive == 1


async def test_send_message_image_exposure_lookup_failure_still_completes_the_turn_without_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sse-assert-goal-prompt.md SA-4/CP-4 판정② — `_match_situational_image`의 노출 이력 조회
    (`db.scalar(select(CharacterImageExposure)...)`)가 실패해도 같은 형태로 흡수된다. 이
    호출은 매칭(LLM 판단)이 이미 성공한 뒤라 위 후보 조회 실패와는 다른 지점을 재는 판정이다.

    ⚠️ 위 테스트와 같은 한계 — 순수 파이썬 `SQLAlchemyError`라 진짜 Postgres aborted
    트랜잭션을 못 만든다. 그 결함은 아래
    `test_send_message_image_exposure_lookup_real_sql_failure_is_isolated_by_savepoint`가 잰다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    original_scalar = AsyncSession.scalar

    async def _failing_scalar(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if statement.column_descriptions[0]["entity"] is CharacterImageExposure:
            raise sa.exc.SQLAlchemyError("exposure lookup boom")
        return await original_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", _failing_scalar)

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

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image.entity_id)),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안아줘"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    assert len(captured) == 1
    assert isinstance(captured[0][0], sa.exc.SQLAlchemyError)
    assert captured[0][1] == "db"

    # 매칭 자체를 포기했으므로 노출 이력도 기록되지 않는다.
    exposure_count = await db_session.scalar(sa.select(sa.func.count()).select_from(CharacterImageExposure))
    assert exposure_count == 0


async def test_send_message_situational_image_candidate_query_real_sql_failure_is_isolated_by_savepoint(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sse-assert-progress.md SP-128(적대적 리뷰 결함①) — 위 판정②(합성 `SQLAlchemyError`)
    테스트가 원리적으로 못 재는 파열을 진짜 SQL로 재현한다. `_stream_new_turn`은 이 가드를
    부르기 **전에** 이미 `db.add(assistant_message)` → `await db.flush()` →
    `room.turn_count += 1`로 dirty 상태를 쌓아 둔다. `SELECT 1/0`으로 Postgres 트랜잭션을
    실제로 aborted 상태로 만들면(리뷰어 재현 선례) — 처방 전에는 가드가 예외를 삼켜도
    트랜잭션은 여전히 aborted라, 뒤따르는 `await db.commit()`이 `room`을 autoflush하려다
    그대로 부딪혀 `DBAPIError`를 던진다(가드가 파열을 한 자리 뒤로 미룰 뿐). 처방 후에는
    가드가 SAVEPOINT로 국소화돼 실패가 그 자리에 갇히고, 이미 flush된 assistant_message와
    `room.turn_count` 증가분은 그대로 커밋된다 — 아래 회귀 감시(방 재조회)가 그 증거다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    original_scalars = AsyncSession.scalars

    async def _really_failing_scalars(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if statement.column_descriptions[0]["entity"] is SituationalImage:
            # 순수 파이썬 예외가 아니라 실제 SQL을 태워 Postgres 트랜잭션을 진짜 aborted로
            # 만든다(리뷰어의 `SELECT 1/0` 재현 선례, 위 합성 테스트와 다른 지점을 잰다).
            await self.execute(sa.text("SELECT 1/0"))
        return await original_scalars(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalars", _really_failing_scalars)

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

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안아줘"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None
    assert not fake.generate_structured_called

    assert len(captured) == 1
    assert isinstance(captured[0][0], sa.exc.DBAPIError)
    assert captured[0][1] == "db"

    # SAVEPOINT 국소화의 직접 증거 — 가드 실패 이전에 이미 flush된 assistant_message와
    # room.turn_count 증가분이 뒤따르는 commit()에서 그대로 살아남는다(처방 전에는 바로 이
    # commit()이 aborted 트랜잭션에 부딪혀 DBAPIError를 던져 위 status_code 단언까지도
    # 도달하지 못했다 — 빨강 실측은 progress.md 참고). `db_session.get(ChatRoom, ...)`는 쓰지
    # 않는다 — `db_client`가 이 테스트의 `db_session`을 앱 요청과 **같은 세션 객체**로
    # 오버라이드해(conftest.py), `expire_on_commit=False`인 그 세션의 identity map에 요청 중
    # 만들어진 `room` 객체가 이미 캐시돼 있어 `.get()`이 SQL을 내지 않고 메모리 값만
    # 돌려준다 — 실제로 커밋됐는지와 무관하게 항상 통과하는 거짓 신호였다(직접 확인).
    # 컬럼 단위 `select()`는 identity map을 우회해 매번 실제 쿼리를 낸다.
    turn_count = await db_session.scalar(sa.select(ChatRoom.turn_count).where(ChatRoom.id == room_id))
    assert turn_count == 1
    message_count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    )
    assert message_count == 3  # 오프닝 + 사용자 + 어시스턴트


async def test_send_message_image_exposure_lookup_real_sql_failure_is_isolated_by_savepoint(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """위 테스트와 같은 결함을 노출 이력 조회(`db.scalar`) 지점에서 잰다 — 이 호출은 LLM
    매칭이 이미 성공한 뒤라(`matched`까지 도달) 후보 조회 실패와는 다른 코드 경로를 지난다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    original_scalar = AsyncSession.scalar

    async def _really_failing_scalar(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if statement.column_descriptions[0]["entity"] is CharacterImageExposure:
            await self.execute(sa.text("SELECT 1/0"))
        return await original_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", _really_failing_scalar)

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

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_result=ImageMatchJudgmentResult(matched_image_entity_id=str(image.entity_id)),
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안아줘"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    done_event = events[-1]
    assert done_event["finalMessage"]["imageId"] is None
    assert done_event["finalMessage"]["imageUrl"] is None

    assert len(captured) == 1
    assert isinstance(captured[0][0], sa.exc.DBAPIError)
    assert captured[0][1] == "db"

    # 위 테스트와 같은 이유로 `db_session.get()`이 아니라 컬럼 단위 `select()`를 쓴다(identity
    # map 캐시를 우회해 실제 커밋 여부를 잰다).
    turn_count = await db_session.scalar(sa.select(ChatRoom.turn_count).where(ChatRoom.id == room_id))
    assert turn_count == 1
    message_count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    )
    assert message_count == 3
    exposure_count = await db_session.scalar(sa.select(sa.func.count()).select_from(CharacterImageExposure))
    assert exposure_count == 0


async def test_send_message_does_not_dump_prompt_by_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """chat-techspec.md §3-5(D-21·D-22): `prompt_dump_path`의 기본값 None이 프로덕션 방어다 —
    설정 안 하면 지금과 동일하게 아무것도 남기지 않아야 한다."""
    monkeypatch.setattr(settings, "prompt_dump_path", None)

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
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200


async def test_send_message_dumps_prompt_when_configured(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`prompt_dump_path`가 설정되면 그 턴에 조립된 프롬프트가 JSONL 한 줄로 남는다."""
    dump_path = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump_path))
    monkeypatch.setattr(settings, "gemini_seed", 42)

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
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    lines = dump_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["roomId"] == str(room_id)
    assert record["turn"] == 1
    assert record["model"] == settings.gemini_model_name
    assert record["seed"] == 42
    # 지시문도 함께 남는다 — 이 런이 바꾸는 것이 바로 그것이라, 프롬프트만 남고 그때 어떤
    # 지시문이 실렸는지 모르면 회차를 나중에 설명할 수 없다(chat-techspec.md §3-5).
    assert record["systemInstruction"] == _read_golden_prompt("system_instruction_character.txt")
    assert record["prompt"] == fake.received_prompt
