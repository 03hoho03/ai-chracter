"""prompt-db-goal-prompt.md §7 (2단계) — 적대적 리뷰가 잡은 구조적 결함의 회귀 테스트.

`render_prompt_channel`이 DB 값(`PromptSection.body`)을 `.format()`한다 — 플레이스홀더가
`values`에 없으면 `KeyError`, 중괄호 짝이 안 맞으면 `ValueError`다. 이 두 예외를
`PromptRenderError`로 정규화하지 않고 그대로 새게 두면, 4개 SSE 라우트(`send_message`·
`regenerate_message`·`edit_message`·`send_preview_message`) 전부에서 제너레이터 본문을
뚫고 나가 apps/api/CLAUDE.md §SSE가 실측으로 기록한 폭발 반경(태스크 취소 → 커넥션
강제종료 → 무관한 다른 요청 500)을 연다. 이 파일은 그 실패가 각 경로에서 깔끔한
`ChatErrorEvent`로 흡수되는지, 그리고 활성 세트가 아예 없을 때는 스트림이 시작되기도
전에 명시적으로 실패하는지(D-5)를 확인한다.

시드 48행을 건드리지 않는다 — 매 테스트가 `db_session`의 롤백 트랜잭션 안에서
`prompt_sections`/`prompt_sets` 행을 일시적으로 고쳤다가 테스트 종료 시 자동으로
되돌아간다.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import sqlalchemy as sa
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptSetNotFoundError, StatJudgmentResult
from api.db.models import (
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.main import app
from factories import _get_genre, _login_as, _make_asset, _make_user

_BROKEN_BODY = "{이런_플레이스홀더는_시드에_없다}"


async def _make_published_character(db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID) -> Content:
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
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()
    content.current_published_version_id = version.id
    await db_session.flush()
    return content


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
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
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
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    return setup


async def _add_stat_def(db_session: AsyncSession, setup: StartingSetup) -> StatDef:
    stat_def = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        unit=None,
        description="호감도 스탯",
        order=1,
    )
    db_session.add(stat_def)
    await db_session.flush()
    return stat_def


async def _corrupt_section_body(db_session: AsyncSession, *, channel: str, slot: str) -> None:
    await db_session.execute(
        sa.update(PromptSection)
        .where(PromptSection.channel == channel, PromptSection.slot == slot)
        .values(body=_BROKEN_BODY)
    )
    await db_session.flush()


class _FakeLLMClient(LLMClient):
    """정상 토큰을 내되, `generate_structured`가 불리면 실패한 테스트로 만든다 —
    렌더 실패는 `generate_structured` 호출 *전에* 나야 한다."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.generate_structured_calls = 0

    async def generate(
        self, prompt: str, system_instruction: str | None = None, stop_sequences: list[str] | None = None
    ) -> AsyncIterator[str]:
        for token in self.tokens:
            yield token

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None) -> Any:
        self.generate_structured_calls += 1
        if response_schema is StatJudgmentResult:
            return StatJudgmentResult(stat_changes=[])
        raise NotImplementedError


class _NeverCalledLLMClient(LLMClient):
    """렌더가 먼저 실패해야 하는 테스트용 — LLM이 조금이라도 불리면 그 자체가 실패다."""

    async def generate(
        self, prompt: str, system_instruction: str | None = None, stop_sequences: list[str] | None = None
    ) -> AsyncIterator[str]:
        raise AssertionError("렌더 실패보다 먼저 LLM 이 호출됐다")
        yield ""  # pragma: no cover

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None) -> Any:
        raise AssertionError("렌더 실패보다 먼저 LLM 이 호출됐다")


def _override_llm(fake: LLMClient) -> None:
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


async def test_send_message_with_broken_section_body_ends_the_stream_with_an_error_event(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await _corrupt_section_body(db_session, channel="generation", slot="final_frame")

    await _login_as(db_client, user.id)
    room_resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "character"}
    )
    assert room_resp.status_code == 201
    room_id = room_resp.json()["id"]

    _override_llm(_NeverCalledLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]

    # 실패가 이 요청 안에 갇혔는지 — 커넥션이 살아 있고, 어시스턴트 메시지는 추가되지 않았다.
    assistant_count = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.chat_room_id == uuid.UUID(room_id), ChatMessage.role == ChatMessageRole.ASSISTANT)
    )
    assert assistant_count == 1  # 오프닝 메시지 하나뿐, 새로 생기지 않았다


async def test_regenerate_message_with_broken_section_body_ends_the_stream_with_an_error_event(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)

    await _login_as(db_client, user.id)
    room_id = (
        await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    ).json()["id"]

    _override_llm(_FakeLLMClient(tokens=["안녕하세요"]))
    try:
        first = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
        assert first.status_code == 200
    finally:
        _clear_llm_override()

    await _corrupt_section_body(db_session, channel="generation", slot="final_frame")

    _override_llm(_NeverCalledLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]


async def test_edit_message_with_broken_section_body_ends_the_stream_with_an_error_event(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)

    await _login_as(db_client, user.id)
    room_id = (
        await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    ).json()["id"]

    _override_llm(_FakeLLMClient(tokens=["안녕하세요"]))
    try:
        first = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
        assert first.status_code == 200
    finally:
        _clear_llm_override()

    user_message_id = (
        await db_session.scalar(
            sa.select(ChatMessage.id).where(
                ChatMessage.chat_room_id == uuid.UUID(room_id), ChatMessage.role == ChatMessageRole.USER
            )
        )
    )
    assert user_message_id is not None

    await _corrupt_section_body(db_session, channel="generation", slot="final_frame")

    _override_llm(_NeverCalledLLMClient())
    try:
        resp = await db_client.patch(
            f"/chat-rooms/{room_id}/messages/{user_message_id}", json={"content": "수정된 메시지"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]


async def test_send_preview_message_with_broken_section_body_ends_the_stream_with_an_error_event(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _corrupt_section_body(db_session, channel="generation", slot="final_frame")

    await _login_as(db_client, uuid.uuid4())
    session_resp = await db_client.post(
        "/preview-sessions",
        json={
            "name": "아리아",
            "oneLiner": "한 줄 소개",
            "thumbnailAssetId": None,
            "intro": "안녕하세요",
            "exampleDialogues": [],
            "characterPrompt": "너는 아리아다.",
            "playguide": None,
            "situationalImages": [],
            "description": "상세 설명",
            "genreId": None,
            "target": None,
            "hashtags": [],
            "visibility": "private",
        },
    )
    assert session_resp.status_code == 201
    preview_session_id = session_resp.json()["previewSessionId"]

    _override_llm(_NeverCalledLLMClient())
    try:
        resp = await db_client.post(
            f"/preview-sessions/{preview_session_id}/messages", json={"content": "안녕"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]


async def test_story_chat_judgment_render_failure_is_absorbed_and_the_turn_still_completes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """생성 채널은 멀쩡하고 `stat_judgment` 채널만 깨지면 — 판정 단계 실패는 여전히
    "이번 턴의 판정만 건너뛴다"는 기존 관용대로 흡수돼야 한다(`LLMClientError`와 같은
    취급). 생성된 응답은 그대로 커밋되고 `done` 이벤트가 정상적으로 나가야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await _add_stat_def(db_session, setup)
    await _corrupt_section_body(db_session, channel="stat_judgment", slot="turn_context")

    await _login_as(db_client, user.id)
    room_id = (
        await db_client.post(
            "/chat-rooms",
            json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)},
        )
    ).json()["id"]

    fake = _FakeLLMClient(tokens=["이야기가 이어진다"])
    _override_llm(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "달려간다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "done"]
    assert events[-1]["finalMessage"]["content"] == "이야기가 이어진다"
    # 렌더 실패가 build_stat_judgment_prompt 안에서 나서 generate_structured 는 불리지 않았다.
    assert fake.generate_structured_calls == 0


async def test_send_message_without_an_active_prompt_set_fails_before_streaming_starts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """D-5: 활성 세트가 없으면 명시적으로 실패한다. `_active_prompt_set_dependency`가
    `Depends`이므로 이 실패는 SSE 제너레이터 본문이 시작되기 *전*이어야 한다 — 사용자
    메시지가 커밋되지 않고, 커넥션도 오염되지 않는 것으로 확인한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)

    await _login_as(db_client, user.id)
    room_id = (
        await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    ).json()["id"]

    await db_session.execute(sa.update(PromptSet).where(PromptSet.status == "published").values(status="archived"))
    await db_session.flush()

    with pytest.raises(PromptSetNotFoundError):
        await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})

    # 본문이 시작되지 않았다 — 사용자 메시지가 커밋되지 않았다(오프닝 메시지 하나뿐).
    message_count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMessage).where(ChatMessage.chat_room_id == uuid.UUID(room_id))
    )
    assert message_count == 1

    # 커넥션이 오염되지 않았다 — 같은 세션으로 다른 쿼리가 여전히 정상 동작한다.
    still_alive = await db_session.scalar(sa.select(sa.func.count()).select_from(Content))
    assert still_alive == 1
