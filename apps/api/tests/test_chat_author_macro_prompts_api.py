"""실제 방의 턴이 작가 글의 `{{user}}`·`{{char}}` 를 방의 이름으로 바꿔 모델에 보내는지 — 생성·판정·요약 호출부 전부.

이름은 방이 고른 대화 프로필, 없으면 "당신"이다. 사용자 메시지는 화면이 보내기 전에 바꿔 저장하므로 서버는 손대지
않는다 — 거기 남은 `{{user}}` 는 사용자가 친 글자다. 판정·요약 채널에는 프로필 이름이 있을 때 "대화 속 사용자의 이름"
한 줄이 실리고, 생성 채널에는 그 한 줄이 실리지 않는다(프로필 섹션이 이름을 준다).
섹션 문안은 마이그레이션이 심은 활성 세트(테스트 DB)의 것이다.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.db.models import (
    CharacterVersionDetail,
    ChatMessage,
    ChatRoom,
    Content,
    KeywordNote,
    Shortcut,
    StartingSetup,
    StatDef,
    StatRule,
    StoryVersionDetail,
)
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_default_persona,
    _make_published_character,
    _make_user,
    _open_room,
    _override_llm_client,
    _story_with_setup,
)

_OPENING = "{{user}}는 옥상 문 앞에 선다."


class _RecordingLLMClient(LLMClient):
    """생성 프롬프트와 구조화 호출(스키마, 프롬프트)을 모두 모은다. 판정은 아무것도 바꾸지 않는 결과를 준다."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.structured: list[tuple[Any, str]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.structured.append((response_schema, prompt))
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=[])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=False)
        if response_schema is MemorySummaryResult:
            return MemorySummaryResult(summary="요약")
        assert response_schema is ImageMatchJudgmentResult, response_schema
        return ImageMatchJudgmentResult(matched_image_entity_id=None)

    def judgment(self, schema: Any) -> str:
        (prompt,) = [prompt for called, prompt in self.structured if called is schema]
        return prompt


async def _post(client: httpx.AsyncClient, path: str, body: dict[str, Any] | None = None) -> _RecordingLLMClient:
    fake = _RecordingLLMClient()
    _override_llm_client(fake)
    try:
        resp = await client.post(path, json=body)
    finally:
        _clear_llm_override()
    assert resp.status_code == 200, resp.text
    assert '"type":"error"' not in resp.text.replace(" ", ""), resp.text
    return fake


async def _story_detail(db_session: AsyncSession, content: Content) -> StoryVersionDetail:
    assert content.current_published_version_id is not None
    detail = await db_session.get(StoryVersionDetail, content.current_published_version_id)
    assert detail is not None
    return detail


def _add_stat(db_session: AsyncSession, setup: StartingSetup, description: str) -> None:
    """스탯 하나와 그 규칙 하나. 규칙이 있어야 스탯 판정이 불린다."""
    stat_def_id = uuid.uuid4()
    db_session.add(
        StatDef(
            id=stat_def_id,
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="용기",
            icon="heart",
            color="#ff0000",
            min_value=0,
            max_value=10,
            initial_value=5,
            unit=None,
            description=description,
            order=1,
        )
    )
    db_session.add(StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def_id, condition="웃는다", delta=1, order=0))


async def _create_room(client: httpx.AsyncClient, content: Content, setup: StartingSetup | None) -> uuid.UUID:
    body: dict[str, Any] = {"contentId": str(content.id), "contentType": "story" if setup else "character"}
    if setup is not None:
        body["startingSetupId"] = str(setup.id)
    resp = await client.post("/chat-rooms", json=body)
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def test_story_turn_names_the_user_in_author_text_and_judgment_but_leaves_the_user_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작가 글(설정·첫 메시지·단축어 프롬프트·스탯 설명)은 방 프로필 이름으로 바뀌고, 키워드는 바뀐 첫 메시지에서
    찾는다. 프로필이 있으니 생성 채널의 이름 한 줄은 없고 판정 채널에는 있다. 사용자 메시지는 그대로다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message=_OPENING)
    (await _story_detail(db_session, content)).setting_text = "{{user}}의 옥상 이야기"
    _add_stat(db_session, setup, "{{user}}가 웃으면 오른다")
    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="둘러보기",
        description="주위를 본다",
        prompt="{{user}}가 주위를 둘러본다",
    )
    db_session.add(shortcut)
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            starting_setup_id=None,
            info_text="이름이 불렸다",
            trigger_keywords=["지훈"],
        )
    )
    await _make_default_persona(db_session, user_id, "지훈")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room_id = await _create_room(db_client, content, setup)

    fake = await _post(
        db_client,
        f"/chat-rooms/{room_id}/messages",
        {"content": "{{user}}라고 쳤다", "shortcutId": str(shortcut.entity_id)},
    )

    [prompt] = fake.prompts
    assert "지훈의 옥상 이야기" in prompt
    assert "지훈은 옥상 문 앞에 선다." in prompt
    assert "지훈이 주위를 둘러본다" in prompt
    assert "이름이 불렸다" in prompt
    assert prompt.count("{{user}}") == 1  # 이번 턴 사용자 메시지만 남는다
    assert "{{user}}라고 쳤다" in prompt
    assert "[사용자 이름]" not in prompt
    stat_prompt = fake.judgment(StatRuleJudgmentResult)
    assert "지훈이 웃으면 오른다" in stat_prompt
    assert "대화 속 사용자의 이름: 지훈" in stat_prompt
    assert "{{user}}라고 쳤다" in stat_prompt


async def test_story_room_without_persona_uses_the_fallback_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필이 없으면 "당신" 으로 바꾸되 이름 한 줄은 어디에도 없다("대화 속 사용자의 이름: 당신" 은 거짓 줄이다)."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message=_OPENING)
    _add_stat(db_session, setup, "설명")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room_id = await _create_room(db_client, content, setup)

    fake = await _post(db_client, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})

    [prompt] = fake.prompts
    stat_prompt = fake.judgment(StatRuleJudgmentResult)
    assert "당신은 옥상 문 앞에 선다." in prompt
    assert "대화 속 사용자의 이름" not in prompt + stat_prompt


async def test_regenerate_rebuilds_the_same_named_prompt_as_the_original_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재생성은 같은 방·같은 프로필로 이름을 고르므로 원 턴과 같은 프롬프트를 만든다. 칸 판정이 없는 방이라 재생성은
    판정을 부르지 않는다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message=_OPENING)
    _add_stat(db_session, setup, "{{user}}가 웃으면 오른다")
    await _make_default_persona(db_session, user_id, "지훈")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room_id = await _create_room(db_client, content, setup)

    original = await _post(db_client, f"/chat-rooms/{room_id}/messages", {"content": "{{user}}라고 쳤다"})
    regenerated = await _post(db_client, f"/chat-rooms/{room_id}/regenerate")

    assert "지훈은 옥상 문 앞에 선다." in original.prompts[0]
    assert regenerated.prompts == original.prompts


async def test_character_turn_names_the_user_and_the_character(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """캐릭터 작품은 `{{char}}` 가 그 캐릭터의 이름이다 — 캐릭터 프롬프트와 첫 메시지(인트로 복사본) 모두."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=genre.id, intro="{{char}}가 {{user}}를 반긴다."
    )
    assert content.current_published_version_id is not None
    detail = await db_session.get(CharacterVersionDetail, content.current_published_version_id)
    assert detail is not None
    detail.name = "하늘"
    detail.character_prompt = "너의 이름은 {{char}}. {{user}}를 기다린다."
    await _make_default_persona(db_session, user.id, "지훈")
    await db_session.commit()
    await _login_as(db_client, user.id)
    room_id = await _create_room(db_client, content, None)

    fake = await _post(db_client, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})

    [prompt] = fake.prompts
    assert "너의 이름은 하늘. 지훈을 기다린다." in prompt
    assert "하늘이 지훈을 반긴다." in prompt
    assert "{{" not in prompt


async def test_memory_fold_names_the_user_with_the_turns_names(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약 접기는 백그라운드라 그 턴의 이름을 받아 쓴다 — 접을 대화의 모델 응답 줄을 바꾸고 이름 한 줄을 싣는다."""
    room = await _open_room(db_client, db_session, turns=29, lane="character")
    first_reply = room.turns[1][1]
    await db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.id == first_reply.id).values(content="{{user}}가 웃었다")
    )
    user_id = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room.room_id))
    assert user_id is not None
    persona = await _make_default_persona(db_session, user_id, "모험가")
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(persona_id=persona.id))
    await db_session.commit()

    fake = await _post(db_client, f"/chat-rooms/{room.room_id}/messages", {"content": "새 메시지"})

    summary_prompt = fake.judgment(MemorySummaryResult)
    assert "모험가가 웃었다" in summary_prompt
    assert "대화 속 사용자의 이름: 모험가" in summary_prompt
    assert "{{user}}" not in summary_prompt
