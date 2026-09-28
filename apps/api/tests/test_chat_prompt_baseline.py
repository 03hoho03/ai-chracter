"""긴 방·짧은 방에서 send/regenerate/edit가 LLM에 보내는 프롬프트를 기대값 파일과 바이트로 비교한다.

기대값 파일(`fixtures/chat_prompt_baseline.json`)은 히스토리 윈도우를 넣기 **전** 코드에서 같은
시나리오로 뜬 것이다. 기대값을 새 코드로 만들면 양쪽이 같은 함수를 거쳐 같은 값을 내므로 아무것도
증명하지 못한다 — 그래서 이 파일은 다시 뜨지 않는다. 프롬프트 본문 대신 sha256과 길이만 둔다(긴
방 프롬프트는 수만 자라 저장소를 불린다). 다르면 실패 메시지가 호출 위치와 길이를 보여 준다.

시나리오가 덮는 것:
- 스냅샷이 없는 방은 턴 수(36턴)·원문 글자(24,000자 초과)와 무관하게 모든 호출이 그대로다.
- 스냅샷이 있는 방에서도 판정 호출(스탯·엔딩·상황이미지)은 전체 히스토리 그대로다 — 생성
  호출만 윈도우를 쓴다. 생성 윈도우 설정을 끄면 생성 호출도 그대로다.

같은 시나리오 장치로 윈도우 자체도 본다 — 요약 커서 이하 메시지는 생성 프롬프트에서 빠지고,
오프닝은 맨 앞에 남고, 커서 뒤 메시지는 하나도 빠지지 않는다(요약이 늦거나 실패해도 대화가
사라지지 않는다는 약속). 윈도우 경계 규칙은 순수 함수 테스트가 따로 본다.
"""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import prompt_window
from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatJudgmentResult
from api.db.models import (
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    Ending,
    SituationalImage,
    StartingSetup,
    StatDef,
)
from api.core.config import settings
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_asset,
    _make_published_character,
    _make_published_story,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
)

BASELINE_PATH = Path(__file__).parent / "fixtures" / "chat_prompt_baseline.json"

# 프롬프트에 id가 실리는 행(스탯·이미지 판정)은 id를 고정해야 해시가 실행마다 같다.
_STAT_ENTITY_ID = uuid.UUID("5a1e0000-0000-4000-8000-000000000001")
_IMAGE_ENTITY_ID = uuid.UUID("5a1e0000-0000-4000-8000-000000000002")

OPENING_MARK = "[OPENING]"
SUMMARY_CURSOR_TURN = 10


def user_line(turn: int) -> str:
    return f"[U{turn:02d}] " + "봄바람이 창문을 두드렸고 우리는 오래 걸었다. " * 16


def assistant_line(turn: int) -> str:
    return f"[A{turn:02d}] " + "그녀는 조용히 웃으며 다음 골목을 가리켰다. " * 16


@dataclass(frozen=True)
class RecordedCall:
    call_site: str
    prompt: str
    system_instruction: str | None


class RecordingLLMClient(LLMClient):
    """모든 호출을 순서대로 기록한다. 판정은 아무것도 바꾸지 않는 결과를 돌려준다(스탯 변경 없음,
    엔딩 미발동, 이미지 미매칭) — 그래야 뒤따르는 호출의 입력이 판정 결과에 흔들리지 않는다."""

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append(RecordedCall(usage.call_site, prompt, system_instruction))
        yield "새 응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls.append(RecordedCall(usage.call_site, prompt, None))
        if response_schema is StatJudgmentResult:
            return StatJudgmentResult(stat_changes=[])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=False)
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        raise AssertionError(f"예상하지 못한 판정 스키마: {response_schema}")


@dataclass(frozen=True)
class SeededRoom:
    room_id: uuid.UUID
    opening_id: uuid.UUID
    # 턴 번호(1부터) → (사용자 메시지 id, 어시스턴트 메시지 id)
    turns: dict[int, tuple[uuid.UUID, uuid.UUID]]


async def _make_character_content(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user_id, genre_id=genre.id, intro=f"{OPENING_MARK} 어서 와."
    )
    assert content.current_published_version_id is not None
    image_asset = await _make_asset(db_session, owner_user_id=user_id)
    blurred_asset = await _make_asset(db_session, owner_user_id=user_id)
    db_session.add(
        SituationalImage(
            entity_id=_IMAGE_ENTITY_ID,
            content_version_id=content.current_published_version_id,
            image_asset_id=image_asset.id,
            blurred_asset_id=blurred_asset.id,
            trigger_condition="둘이 골목에서 마주칠 때",
            order=1,
        )
    )
    await db_session.flush()
    return content.id


async def _make_story_content(db_session: AsyncSession, user_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user_id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="첫 만남",
        prologue="옛날 옛적, 낯선 마을에 도착했다.",
        opening_message=f"{OPENING_MARK} 다시 만났네요!",
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    db_session.add(
        StatDef(
            entity_id=_STAT_ENTITY_ID,
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
    )
    # 게이트 1·2 두 개라 send(턴 37)와 edit(턴 36) 둘 다 엔딩 판정이 돈다.
    for order, gate in ((1, 1), (2, 2)):
        db_session.add(
            Ending(
                entity_id=uuid.uuid4(),
                starting_setup_id=setup.id,
                name=f"엔딩{order}",
                turn_count_gate=gate,
                judgment_prompt=f"주인공이 마을을 떠났는가? ({order})",
                epilogue="끝.",
                order=order,
            )
        )
    await db_session.flush()
    return content.id, setup.id


async def seed_room(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    lane: str,
    turns: int,
    summary_cursor_turn: int | None,
) -> SeededRoom:
    """방을 API로 만들고(오프닝은 앱이 넣는다) 턴을 `created_at`을 명시해 심는다. 오프닝을 하루
    전으로 옮기고 그 뒤 1초 간격으로 심어, 요청이 새로 넣는 메시지(현재 시각)가 항상 가장 뒤에
    온다. `summary_cursor_turn`이 있으면 그 턴의 어시스턴트 메시지를 커서로 하는 요약 스냅샷을
    심는다(요약 경로가 만든 것과 같은 모양)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    if lane == "character":
        content_id = await _make_character_content(db_session, user.id)
        body: dict[str, str] = {"contentId": str(content_id), "contentType": "character"}
    else:
        content_id, story_setup_id = await _make_story_content(db_session, user.id)
        body = {"contentId": str(content_id), "contentType": "story", "startingSetupId": str(story_setup_id)}
    await db_session.commit()

    await _login_as(db_client, user.id)
    created = await db_client.post("/chat-rooms", json=body)
    assert created.status_code == 201, created.text
    room_id = uuid.UUID(created.json()["id"])

    opening = (await db_session.scalars(sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id))).one()
    base = datetime.now(UTC) - timedelta(days=1)
    await db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.id == opening.id).values(created_at=base)
    )
    seeded: dict[int, tuple[uuid.UUID, uuid.UUID]] = {}
    for turn in range(1, turns + 1):
        user_message = ChatMessage(
            id=uuid.uuid4(),
            chat_room_id=room_id,
            role=ChatMessageRole.USER,
            content=user_line(turn),
            created_at=base + timedelta(seconds=2 * turn - 1),
        )
        assistant_message = ChatMessage(
            id=uuid.uuid4(),
            chat_room_id=room_id,
            role=ChatMessageRole.ASSISTANT,
            content=assistant_line(turn),
            created_at=base + timedelta(seconds=2 * turn),
        )
        db_session.add_all([user_message, assistant_message])
        seeded[turn] = (user_message.id, assistant_message.id)
    await db_session.flush()
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room_id).values(turn_count=turns))
    if summary_cursor_turn is not None:
        db_session.add(
            ChatRoomMemorySnapshot(
                chat_room_id=room_id,
                cursor_created_at=base + timedelta(seconds=2 * summary_cursor_turn),
                cursor_message_id=seeded[summary_cursor_turn][1],
                summary_text="요약",
                source="auto",
            )
        )
    await db_session.commit()
    return SeededRoom(room_id=room_id, opening_id=opening.id, turns=seeded)


async def run_action(
    db_client: httpx.AsyncClient, room: SeededRoom, action: str, turns: int
) -> list[RecordedCall]:
    """요청 하나를 보내고 LLM이 받은 호출 전부를 돌려준다. 편집은 마지막 사용자 메시지를 고친다
    (커서보다 뒤라 윈도우와 되감기가 얽히지 않는다)."""
    fake = RecordingLLMClient()
    _override_llm_client(fake)
    try:
        if action == "send":
            response = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
        elif action == "regenerate":
            response = await db_client.post(f"/chat-rooms/{room.room_id}/regenerate")
        else:
            last_user_id = room.turns[turns][0]
            response = await db_client.patch(
                f"/chat-rooms/{room.room_id}/messages/{last_user_id}", json={"content": "고친 메시지"}
            )
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    assert [event["type"] for event in _parse_sse_events(response.text)][-1] == "done"
    return fake.calls


LANES = ("character", "story")
SHAPES: dict[str, tuple[int, int | None]] = {
    "short": (3, None),
    "long": (36, None),
    "long-summarized": (36, SUMMARY_CURSOR_TURN),
}
ACTIONS = ("send", "regenerate", "edit")
CASES = [f"{lane}-{shape}-{action}" for lane in LANES for shape in SHAPES for action in ACTIONS]


def fingerprint(calls: list[RecordedCall]) -> list[dict[str, object]]:
    return [
        {
            "callSite": call.call_site,
            "chars": len(call.prompt),
            "sha256": hashlib.sha256(call.prompt.encode("utf-8")).hexdigest(),
            "systemSha256": (
                hashlib.sha256(call.system_instruction.encode("utf-8")).hexdigest()
                if call.system_instruction is not None
                else None
            ),
        }
        for call in calls
    ]


async def run_case(db_client: httpx.AsyncClient, db_session: AsyncSession, case: str) -> list[RecordedCall]:
    lane, rest = case.split("-", 1)
    shape, action = rest.rsplit("-", 1)
    turns, cursor_turn = SHAPES[shape]
    room = await seed_room(db_client, db_session, lane=lane, turns=turns, summary_cursor_turn=cursor_turn)
    return await run_action(db_client, room, action, turns)


def _load_baseline() -> dict[str, list[dict[str, object]]]:
    data: dict[str, list[dict[str, object]]] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("case", [c for c in CASES if "-summarized-" not in c])
async def test_room_without_summary_sends_the_same_prompts_as_before_the_window(
    db_client: httpx.AsyncClient, db_session: AsyncSession, case: str
) -> None:
    calls = await run_case(db_client, db_session, case)
    assert fingerprint(calls) == _load_baseline()[case]


@pytest.mark.parametrize("case", [c for c in CASES if "-summarized-" in c])
async def test_room_with_summary_still_sends_full_history_to_judgment_calls(
    db_client: httpx.AsyncClient, db_session: AsyncSession, case: str
) -> None:
    calls = await run_case(db_client, db_session, case)
    judgments = [call for call in fingerprint(calls) if call["callSite"] != "chat_generate"]
    expected = [call for call in _load_baseline()[case] if call["callSite"] != "chat_generate"]
    assert judgments == expected


@pytest.mark.parametrize("case", [c for c in CASES if "-summarized-" in c])
async def test_generation_window_switched_off_sends_full_history_even_with_summary(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    monkeypatch.setattr(settings, "memory_window_generation", False)
    calls = await run_case(db_client, db_session, case)
    assert fingerprint(calls) == _load_baseline()[case]


def _generation_prompt(calls: list[RecordedCall]) -> str:
    prompts = [call.prompt for call in calls if call.call_site == "chat_generate"]
    assert len(prompts) == 1
    return prompts[0]


# 요청마다 이전 턴으로 실리는 범위: send는 전부, regenerate는 마지막 응답을 뺀 것, edit(마지막
# 사용자 메시지)은 그 사용자 메시지와 뒤 응답을 뺀 것.
_LAST_TURN_SHOWN = {"send": (36, 36), "regenerate": (36, 35), "edit": (35, 35)}


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("lane", LANES)
async def test_summarized_room_drops_messages_up_to_the_cursor_and_keeps_every_later_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, action: str
) -> None:
    room = await seed_room(db_client, db_session, lane=lane, turns=36, summary_cursor_turn=SUMMARY_CURSOR_TURN)

    prompt = _generation_prompt(await run_action(db_client, room, action, 36))

    for turn in range(1, SUMMARY_CURSOR_TURN + 1):
        assert f"[U{turn:02d}]" not in prompt
        assert f"[A{turn:02d}]" not in prompt
    last_user, last_assistant = _LAST_TURN_SHOWN[action]
    for turn in range(SUMMARY_CURSOR_TURN + 1, last_user + 1):
        assert prompt.count(f"[U{turn:02d}]") == 1
    for turn in range(SUMMARY_CURSOR_TURN + 1, last_assistant + 1):
        assert prompt.count(f"[A{turn:02d}]") == 1


@pytest.mark.parametrize("lane", LANES)
async def test_summarized_room_keeps_the_opening_ahead_of_the_window(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str
) -> None:
    room = await seed_room(db_client, db_session, lane=lane, turns=36, summary_cursor_turn=SUMMARY_CURSOR_TURN)

    prompt = _generation_prompt(await run_action(db_client, room, "send", 36))

    assert prompt.count(OPENING_MARK) == 1
    assert prompt.index(OPENING_MARK) < prompt.index(f"[U{SUMMARY_CURSOR_TURN + 1:02d}]")


async def test_room_whose_later_turns_were_never_summarized_keeps_all_of_them_in_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """커서 뒤로 30턴이 쌓였는데 다음 요약이 커밋되지 않은 방(요약 실패·지연)이다. 윈도우는 턴
    수를 세지 않는다 — 요약이 덮지 않은 메시지는 전부 실려야 한다."""
    room = await seed_room(db_client, db_session, lane="character", turns=40, summary_cursor_turn=SUMMARY_CURSOR_TURN)

    prompt = _generation_prompt(await run_action(db_client, room, "send", 40))

    markers = [f"[{side}{turn:02d}]" for turn in range(SUMMARY_CURSOR_TURN + 1, 41) for side in ("U", "A")]
    positions = [prompt.find(marker) for marker in markers]
    assert -1 not in positions
    assert positions == sorted(positions)
    assert prompt.find("새 메시지") > positions[-1]


_T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _message(role: ChatMessageRole, content: str, seconds: int, message_id: int) -> ChatMessage:
    return ChatMessage(
        id=uuid.UUID(int=message_id),
        role=role,
        content=content,
        created_at=_T0 + timedelta(seconds=seconds),
    )


def _contents(messages: list[ChatMessage]) -> list[str]:
    return [message.content for message in messages]


_OPENED_ROOM = [
    _message(ChatMessageRole.ASSISTANT, "오프닝", 0, 1),
    _message(ChatMessageRole.USER, "u1", 1, 2),
    _message(ChatMessageRole.ASSISTANT, "a1", 2, 3),
    _message(ChatMessageRole.USER, "u2", 3, 4),
    _message(ChatMessageRole.ASSISTANT, "a2", 4, 5),
]


def test_prompt_window_without_cursor_returns_every_message() -> None:
    assert _contents(prompt_window(_OPENED_ROOM, None)) == ["오프닝", "u1", "a1", "u2", "a2"]


def test_prompt_window_excludes_the_cursor_message_itself() -> None:
    cursor = (_OPENED_ROOM[2].created_at, _OPENED_ROOM[2].id)
    assert _contents(prompt_window(_OPENED_ROOM, cursor)) == ["오프닝", "u2", "a2"]


def test_prompt_window_pins_an_opening_even_when_it_is_under_the_cursor() -> None:
    cursor = (_OPENED_ROOM[4].created_at, _OPENED_ROOM[4].id)
    assert _contents(prompt_window(_OPENED_ROOM, cursor)) == ["오프닝"]


def test_prompt_window_does_not_pin_a_first_message_that_is_a_user_message() -> None:
    """오프닝을 지운 방은 첫 메시지가 사용자 메시지다 — 고정할 것이 없다."""
    room = _OPENED_ROOM[1:]
    cursor = (room[1].created_at, room[1].id)
    assert _contents(prompt_window(room, cursor)) == ["u2", "a2"]


def test_prompt_window_breaks_created_at_ties_by_message_id() -> None:
    tied = [
        _message(ChatMessageRole.ASSISTANT, "오프닝", 0, 1),
        _message(ChatMessageRole.ASSISTANT, "같은 시각 앞", 5, 10),
        _message(ChatMessageRole.USER, "같은 시각 뒤", 5, 11),
    ]
    cursor = (tied[1].created_at, tied[1].id)
    assert _contents(prompt_window(tied, cursor)) == ["오프닝", "같은 시각 뒤"]


NOTE_MARK = "[NOTE] 우산은 파란색이다"
SUMMARY_MARK = "[SUMMARY] 둘은 골목 끝 서점에서 처음 만났다"


async def _write_memory(db_session: AsyncSession, room: SeededRoom, *, note: str, summary: str) -> None:
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_note=note))
    await db_session.execute(
        sa.update(ChatRoomMemorySnapshot)
        .where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
        .values(summary_text=summary)
    )
    await db_session.commit()


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("lane", LANES)
async def test_generation_prompt_carries_the_room_note_then_the_current_summary_before_the_window(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, action: str
) -> None:
    room = await seed_room(db_client, db_session, lane=lane, turns=36, summary_cursor_turn=SUMMARY_CURSOR_TURN)
    await _write_memory(db_session, room, note=NOTE_MARK, summary=SUMMARY_MARK)

    prompt = _generation_prompt(await run_action(db_client, room, action, 36))

    assert prompt.count(NOTE_MARK) == 1
    assert prompt.count(SUMMARY_MARK) == 1
    assert prompt.index(NOTE_MARK) < prompt.index(SUMMARY_MARK) < prompt.index(f"[U{SUMMARY_CURSOR_TURN + 1:02d}]")


@pytest.mark.parametrize("lane", LANES)
async def test_generation_window_switched_off_drops_the_summary_but_keeps_the_note(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: str
) -> None:
    """윈도우를 끄면 전체 히스토리가 실리므로 요약까지 실으면 같은 대화가 두 번 들어간다. 노트는
    대화와 겹치지 않는 사용자 메모라 그대로 싣는다."""
    monkeypatch.setattr(settings, "memory_window_generation", False)
    room = await seed_room(db_client, db_session, lane=lane, turns=36, summary_cursor_turn=SUMMARY_CURSOR_TURN)
    await _write_memory(db_session, room, note=NOTE_MARK, summary=SUMMARY_MARK)

    prompt = _generation_prompt(await run_action(db_client, room, "send", 36))

    assert SUMMARY_MARK not in prompt
    assert prompt.count(NOTE_MARK) == 1
    assert "[U01]" in prompt
