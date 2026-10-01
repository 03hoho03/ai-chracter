"""키워드북 노트가 실채팅의 생성 프롬프트에 실리는지 — 라우트가 엔진에 넘기는 대화와 노트를 본다.

모델 응답은 페이크가 정한 글이라, 앞 턴 응답에 키워드가 있었는지·몇 턴이 지났는지를 테스트가 고정할 수 있다. 응답 없이
남은 사용자 메시지(생성 실패 턴)는 DB 에 직접 넣는다."""

import unicodedata
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import ImageMatchJudgmentResult, StatJudgmentResult
from api.db.models import ChatMessage, Content, KeywordNote, Shortcut, StartingSetup, StatDef
from api.db.models.chat import ChatMessageRole
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _add_named_media_cell,
    _clear_llm_override,
    _login_as,
    _override_llm_client,
    _story_with_setup,
)


class _RecordingLLMClient(LLMClient):
    """생성·판정 프롬프트를 모두 남긴다. 판정은 "바뀐 것 없음"으로 답한다. 생성 응답은 호출마다 `replies` 에서 차례로
    꺼내고, 다 쓰면 마지막 것을 되풀이한다."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or ["응답"])
        self.generation_prompts: list[str] = []
        self.judgment_prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.generation_prompts.append(prompt)
        reply = self.replies[min(len(self.generation_prompts), len(self.replies)) - 1]
        yield reply

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.judgment_prompts.append(prompt)
        if response_schema is StatJudgmentResult:
            return StatJudgmentResult(stat_changes=[])
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        raise AssertionError(f"예상하지 못한 판정 호출: {response_schema.__name__}")


def _add_note(
    db_session: AsyncSession,
    content: Content,
    info_text: str,
    trigger_keywords: list[str],
    *,
    order: int = 0,
    exclude_keywords: list[str] | None = None,
    sticky_turns: int = 0,
    always_on: bool = False,
    starting_setup_id: uuid.UUID | None = None,
) -> None:
    assert content.current_published_version_id is not None
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            starting_setup_id=starting_setup_id,
            info_text=info_text,
            trigger_keywords=trigger_keywords,
            order=order,
            exclude_keywords=exclude_keywords or [],
            sticky_turns=sticky_turns,
            always_on=always_on,
        )
    )


async def _logged_in_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user_id: uuid.UUID, content: Content, setup: StartingSetup
) -> uuid.UUID:
    await db_session.commit()
    await _login_as(db_client, user_id)
    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _append_messages(
    db_session: AsyncSession, room_id: uuid.UUID, messages: list[tuple[ChatMessageRole, str]]
) -> list[ChatMessage]:
    """한 행씩 flush 한다 — 메시지 순서는 `created_at`(문장 실행 시각) 하나로 정해진다."""
    rows = []
    for role, content in messages:
        row = ChatMessage(chat_room_id=room_id, role=role, content=content)
        db_session.add(row)
        await db_session.flush()
        rows.append(row)
    await db_session.commit()
    return rows


async def _send(db_client: httpx.AsyncClient, room_id: uuid.UUID, fake: LLMClient, content: str) -> None:
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": content})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200, resp.text


_USER = ChatMessageRole.USER
_AI = ChatMessageRole.ASSISTANT


# ── 실채팅 ─────────────────────────────────────────────────────────────────────────────────────


async def test_send_loads_note_whose_keyword_is_in_previous_ai_response_but_not_in_judgment_prompts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    # 스탯이 있어야 이 턴에 스탯 판정 호출이 난다.
    db_session.add(
        StatDef(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="호감도",
            icon="heart",
            color="#ff0000",
            min_value=0,
            max_value=100,
            initial_value=50,
            unit=None,
            description="호감도",
            order=1,
        )
    )
    _add_note(db_session, content, "표지-은빛열쇠 노트", ["은빛열쇠"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient(["바닥에 은빛열쇠가 떨어져 있다.", "응답"])

    await _send(db_client, room_id, fake, "주위를 둘러본다")
    await _send(db_client, room_id, fake, "그걸 줍는다")

    first, second = fake.generation_prompts
    assert "표지-은빛열쇠 노트" not in first
    assert "[키워드북]\n표지-은빛열쇠 노트" in second
    assert fake.judgment_prompts
    assert all("표지-은빛열쇠 노트" not in prompt for prompt in fake.judgment_prompts)


async def test_first_turn_loads_note_whose_keyword_is_in_opening(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="마법사가 문 앞에 서 있다.")
    _add_note(db_session, content, "표지-마법사 노트", ["마법사"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, "안녕")

    assert "표지-마법사 노트" in fake.generation_prompts[0]


async def test_send_after_failed_turn_scans_last_read_ai_response_and_keeps_sticky_range(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    _add_note(db_session, content, "표지-응답 키워드 노트", ["은빛열쇠"])
    _add_note(db_session, content, "표지-유지 노트", ["마법사"], sticky_turns=1)
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    # 마지막 사용자 메시지는 응답이 없다(생성 실패). 이번 전송과 한 턴으로 묶여야 직전 AI 응답이 그 앞의 응답이고,
    # 마법사가 나온 턴이 바로 한 턴 전으로 남는다.
    await _append_messages(
        db_session,
        room_id,
        [(_USER, "마법사를 봤어"), (_AI, "은빛열쇠가 빛난다."), (_USER, "음")],
    )
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, "그리고?")

    assert "표지-응답 키워드 노트" in fake.generation_prompts[0]
    assert "표지-유지 노트" in fake.generation_prompts[0]


async def test_sticky_note_stays_for_sticky_turns_then_drops(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    _add_note(db_session, content, "표지-유지 노트", ["마법사"], sticky_turns=2)
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    for text in ["마법사 이야기를 해 줘", "그래서", "그다음은", "끝이야?"]:
        await _send(db_client, room_id, fake, text)

    assert ["표지-유지 노트" in prompt for prompt in fake.generation_prompts] == [True, True, True, False]


async def test_exclude_keyword_blocks_always_on_note_only_in_that_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    _add_note(db_session, content, "표지-상시 노트", [], always_on=True, exclude_keywords=["가짜"])
    _add_note(db_session, content, "표지-유지 노트", ["마법사"], sticky_turns=2, exclude_keywords=["가짜"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    for text in ["마법사가 왔다", "가짜였어", "그렇구나"]:
        await _send(db_client, room_id, fake, text)

    first, banned, after = fake.generation_prompts
    assert "표지-상시 노트" in first and "표지-유지 노트" in first
    assert "표지-상시 노트" not in banned and "표지-유지 노트" not in banned
    assert "표지-상시 노트" in after and "표지-유지 노트" in after


async def test_only_first_five_triggered_notes_by_order_are_loaded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    # 순서의 역순으로 넣는다 — 넣은 순서가 곧 순서면 정렬이 빠져도 같은 결과가 나온다.
    for order in reversed(range(6)):
        _add_note(db_session, content, f"표지-열쇠 노트 {order}", ["열쇠"], order=order)
        await db_session.flush()
    _add_note(db_session, content, "표지-상시 노트", [], always_on=True, order=9)
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, "열쇠를 찾았다")

    prompt = fake.generation_prompts[0]
    assert "표지-열쇠 노트 5" not in prompt
    positions = [prompt.index(text) for text in ["표지-상시 노트", *(f"표지-열쇠 노트 {order}" for order in range(5))]]
    assert positions == sorted(positions)


async def test_keyword_matching_ignores_case_and_unicode_composition(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    _add_note(db_session, content, "표지-USB 노트", ["USB"])
    _add_note(db_session, content, "표지-마법사 노트", ["마법사"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, unicodedata.normalize("NFD", "usb 를 든 마법사"))

    assert "표지-USB 노트" in fake.generation_prompts[0]
    assert "표지-마법사 노트" in fake.generation_prompts[0]


async def test_note_with_blank_info_is_not_loaded(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    _add_note(db_session, content, "   ", [], always_on=True)
    _add_note(db_session, content, "\n", ["마법사"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, "마법사")

    assert "[키워드북]" not in fake.generation_prompts[0]


async def test_note_scoped_to_other_starting_setup_stays_out_even_when_always_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    assert content.current_published_version_id is not None
    other = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="다른 시작",
        prologue="다른 프롤로그",
        opening_message=None,
        order=2,
    )
    db_session.add(other)
    await db_session.flush()
    _add_note(db_session, content, "표지-다른 시작 노트", [], always_on=True, starting_setup_id=other.id)
    _add_note(db_session, content, "표지-이 시작 노트", [], always_on=True, starting_setup_id=setup.id)
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, "안녕")

    assert "표지-이 시작 노트" in fake.generation_prompts[0]
    assert "표지-다른 시작 노트" not in fake.generation_prompts[0]


async def test_cell_id_in_opening_media_tag_does_not_trigger_short_hex_keyword(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.\n\n{{img::민아/교실}}")
    assert content.current_published_version_id is not None
    # 칸 id 를 골라 키워드 조각이 반드시 들어 있게 한다. 방에 복사된 첫 메시지는 이 id 로 태그를 저장한다.
    cell_id = uuid.UUID("adadadad-b1b1-4b1b-8b1b-adadadadadad")
    await _add_named_media_cell(
        db_session, content.current_published_version_id, user_id, "민아", "교실", entity_id=cell_id
    )
    _add_note(db_session, content, "표지-AD 노트", ["AD"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    opening = await db_session.scalar(select(ChatMessage.content).where(ChatMessage.chat_room_id == room_id))
    assert opening is not None and str(cell_id) in opening
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, "안녕")

    assert "표지-AD 노트" not in fake.generation_prompts[0]


async def test_edit_scans_ai_response_before_edited_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    _add_note(db_session, content, "표지-마법사 노트", ["마법사"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    rows = await _append_messages(
        db_session, room_id, [(_USER, "안녕"), (_AI, "마법사가 왔다."), (_USER, "음"), (_AI, "응")]
    )
    fake = _RecordingLLMClient()

    _override_llm_client(fake)
    try:
        resp = await db_client.patch(f"/chat-rooms/{room_id}/messages/{rows[2].id}", json={"content": "그래서?"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    assert "표지-마법사 노트" in fake.generation_prompts[0]


async def test_regenerate_rebuilds_the_same_prompt_as_the_original_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    _add_note(db_session, content, "표지-마법사 노트", ["마법사"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    await _append_messages(db_session, room_id, [(_USER, "안녕"), (_AI, "마법사가 왔다.")])
    fake = _RecordingLLMClient()

    await _send(db_client, room_id, fake, "그래서?")
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    original, regenerated = fake.generation_prompts
    assert "표지-마법사 노트" in original
    assert regenerated == original


async def test_shortcut_turn_scans_shortcut_message(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    assert content.current_published_version_id is not None
    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="수색",
        description="주변을 뒤진다",
        prompt="마법사의 흔적을 찾는다",
    )
    db_session.add(shortcut)
    _add_note(db_session, content, "표지-마법사 노트", ["마법사"])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    _override_llm_client(fake)
    try:
        resp = await db_client.post(
            f"/chat-rooms/{room_id}/messages",
            json={"content": "마법사의 흔적을 찾는다", "shortcutId": str(shortcut.entity_id)},
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    assert "표지-마법사 노트" in fake.generation_prompts[0]
