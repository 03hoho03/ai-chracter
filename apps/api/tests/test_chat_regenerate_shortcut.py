"""재생성이 원 턴의 단축어를 되살리는지. 메시지에는 단축어 칸이 없어, 어느 단축어로 보낸 턴인지는 그 응답의 턴 기록
(`chat_turns.shortcut_entity_id`)에만 남는다. 재생성은 그 기록에서 단축어를 찾아 같은 프롬프트로 다시 생성하고, 재생성
기록이 그 값을 이어받으므로 재생성을 거듭해도 단축어가 남는다.

규칙(결과를 보기 전에 적었다):
- 단축어로 보낸 턴을 재생성하면 생성 프롬프트에 그 단축어 문안이 실린다 — 원 턴의 생성 프롬프트와 바이트까지 같다.
- 그 재생성을 다시 재생성해도 실린다.
- 단축어는 바꾸는 응답의 기록에서만 온다 — 단축어 없이 보낸 턴의 재생성은 앞 턴의 단축어를 빌려오지 않는다.
- 기록이 없는 응답(기록을 쓰기 전에 보낸 턴)의 재생성은 지금처럼 단축어 없이 생성한다.
- 단축어는 방이 지금 고정한 버전에서 찾는다(프롬프트의 다른 재료와 같다). 그 버전에 그 단축어가 없으면 단축어 없이 생성한다
  — 재생성 요청은 단축어를 고르지 않았으므로 400 으로 막을 근거가 없다."""

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
from api.db.models import ChatRoom
from api.db.models.story import Shortcut
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _clear_llm_override,
    _get_genre,
    _make_published_story,
    _make_user,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
)

_SHORTCUT_PROMPT = "[SHORTCUT]플레이어가 주변을 자세히 수색하는 상황을 묘사하라"


class _PromptLLM(LLMClient):
    """생성 프롬프트를 받은 순서대로 남기고, 판정에는 아무것도 하지 않는 답을 준다."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.prompts.append(str(prompt))
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=[])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=False)
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        return MemorySummaryResult(summary="요약")


async def _post(client: httpx.AsyncClient, path: str, body: dict[str, object] | None, fake: LLMClient) -> None:
    _override_llm_client(fake)
    try:
        response = await client.post(path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    assert _parse_sse_events(response.text)[-1]["type"] == "done", response.text


async def _add_shortcut(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID:
    version_id = await db_session.scalar(sa.select(ChatRoom.content_version_id).where(ChatRoom.id == room_id))
    assert version_id is not None
    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=version_id,
        name="수색",
        description="주변을 수색한다",
        prompt=_SHORTCUT_PROMPT,
    )
    db_session.add(shortcut)
    await db_session.commit()
    return shortcut.entity_id


async def _send_with_shortcut(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[uuid.UUID, str]:
    """단축어로 한 턴 보낸 스토리 방과 그 턴의 생성 프롬프트."""
    room = await _open_room(db_client, db_session, turns=1, lane="story")
    shortcut_id = await _add_shortcut(db_session, room.room_id)
    sent = _PromptLLM()
    await _post(
        db_client, f"/chat-rooms/{room.room_id}/messages", {"content": "/수색", "shortcutId": str(shortcut_id)}, sent
    )
    [prompt] = sent.prompts
    assert _SHORTCUT_PROMPT in prompt
    return room.room_id, prompt


async def _regenerate(db_client: httpx.AsyncClient, room_id: uuid.UUID) -> str:
    fake = _PromptLLM()
    await _post(db_client, f"/chat-rooms/{room_id}/regenerate", None, fake)
    [prompt] = fake.prompts
    return prompt


async def test_regenerating_a_shortcut_turn_sends_the_original_turns_prompt_with_the_shortcut(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room_id, sent_prompt = await _send_with_shortcut(db_client, db_session)

    regenerated = await _regenerate(db_client, room_id)

    assert _SHORTCUT_PROMPT in regenerated
    assert regenerated == sent_prompt


async def test_regenerating_a_regeneration_still_sends_the_shortcut(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room_id, sent_prompt = await _send_with_shortcut(db_client, db_session)
    await _regenerate(db_client, room_id)

    regenerated_again = await _regenerate(db_client, room_id)

    assert _SHORTCUT_PROMPT in regenerated_again
    assert regenerated_again == sent_prompt


async def test_regenerating_a_plain_turn_after_a_shortcut_turn_sends_no_shortcut(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """단축어는 바꾸는 응답의 기록에서만 온다 — 앞 턴이 단축어로 보낸 턴이어도 빌려오지 않는다."""
    room_id, _sent_prompt = await _send_with_shortcut(db_client, db_session)
    await _post(db_client, f"/chat-rooms/{room_id}/messages", {"content": "계속 걷는다"}, _PromptLLM())

    regenerated = await _regenerate(db_client, room_id)

    assert _SHORTCUT_PROMPT not in regenerated


async def test_regenerating_a_reply_without_a_turn_record_sends_no_shortcut(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """심은 턴은 기록이 없다. 그 버전에 단축어가 있어도 어느 것으로 보냈는지 모르므로 싣지 않는다."""
    room = await _open_room(db_client, db_session, turns=1, lane="story")
    await _add_shortcut(db_session, room.room_id)

    regenerated = await _regenerate(db_client, room.room_id)

    assert _SHORTCUT_PROMPT not in regenerated


async def test_regenerating_after_the_shortcut_left_the_rooms_version_sends_no_shortcut(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방을 새 버전에 고정하면 원 턴의 단축어가 그 버전에 없을 수 있다(옛 버전에는 남아 있다). 재생성은 실패하지 않고
    단축어 없이 생성한다 — 옛 버전의 단축어를 집지 않는다."""
    room_id, _sent_prompt = await _send_with_shortcut(db_client, db_session)
    # 같은 단축어 행을 다른 버전으로 옮겨 "방의 버전에는 없고 다른 버전에는 있다"를 만든다.
    other_author = _make_user()
    db_session.add(other_author)
    await db_session.flush()
    other = await _make_published_story(
        db_session, creator_user_id=other_author.id, genre_id=(await _get_genre(db_session)).id
    )
    await db_session.execute(
        sa.update(Shortcut)
        .where(Shortcut.prompt == _SHORTCUT_PROMPT)
        .values(content_version_id=other.current_published_version_id)
    )
    await db_session.commit()

    regenerated = await _regenerate(db_client, room_id)

    assert _SHORTCUT_PROMPT not in regenerated
