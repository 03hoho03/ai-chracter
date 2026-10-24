"""메시지 수정·삭제가 지우는 턴의 스탯과 턴 수를 "그 턴이 없던 상태"로 되돌리는지.

규칙(결과를 보기 전에 적었다):
- 수정은 편집 지점 뒤를 전부 지운다. 지운 AI 응답들의 턴 기록을 늦은 턴부터 이른 턴 순으로 접어 각 기록의 반영 전 값을 덮으면,
  스탯마다 그 스탯을 바꾼 가장 이른 지운 턴의 반영 전 값이 된다. 재생성 체인의 옛 행은 이미 지워진 응답의 것이라 지금 보이는
  응답의 기록 하나만 잡힌다. 지운 응답 중 기록 없는 옛 턴이 섞이면 기록 있는 턴만 되돌리고 그렇다고 알린다.
- 메시지 삭제는 그 메시지 하나만 지운다. 방의 마지막 AI 응답을 지울 때만 그 기록의 반영 전 값으로 되돌리고 `turn_count` 를
  하나 줄인다. 중간 응답을 지우면 스탯·턴 수 그대로 두고 그렇다고 알린다(반영 전 값은 절대값이라 덮으면 뒤 턴 효과까지
  사라진다). 사용자 메시지 삭제는 아무것도 바꾸지 않는다.
- 엔딩 상태와 해금 기록은 되돌리지 않는다 — 스탯만 되돌린다.
- 되돌린 값은 기록에 남은 절대값이라, 범위 끝에서 잘린 턴도 정확히 그 턴 전 값으로 돌아간다.

방에는 판정 스탯 "신뢰"(73, 0~100, 규칙 a1 +5·a2 -2)와 카운터 "남은 날"(30, 0~30, 턴마다 -1)이 있다."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.content.schemas import EndingRuleDraftItem
from api.db.models import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomStat, Ending, StatDef
from api.db.models.chat import ChatTurn, StoryEndingUnlock
from api.db.models.story import EndingRuleOperator
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    Room,
    _add_situation_note,
    _clear_llm_override,
    _override_llm_client,
    _parse_sse_events,
    _setup_of,
    _stat_values,
    _Stats,
    _story_room,
)


class _ScriptedLLM(LLMClient):
    """생성은 늘 같은 글을 내고 생성 프롬프트를 남긴다. 스탯 판정은 `fired` 의 규칙 id 목록을 차례로 꺼내 답한다(다 쓰면 발동한
    규칙 없음). 엔딩 판정은 `ending` 대로, 그림 판정은 고르지 않는다."""

    def __init__(self, fired: list[list[str]] | None = None, *, ending: bool = False) -> None:
        self._fired = list(fired or [])
        self._ending = ending
        self.generation_prompts: list[str] = []
        self.stat_calls = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.generation_prompts.append(prompt)
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            self.stat_calls += 1
            return StatRuleJudgmentResult(fired_rule_ids=self._fired.pop(0) if self._fired else [])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=self._ending)
        assert response_schema is ImageMatchJudgmentResult
        return ImageMatchJudgmentResult(matched_image_entity_id=None)


async def _stream(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, object] | None, fake: LLMClient
) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        response = await client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    events = _parse_sse_events(response.text)
    assert events[-1]["type"] == "done", response.text
    return events


async def _send(client: httpx.AsyncClient, room: Room, content: str, *rule_ids: str, ending: bool = False) -> None:
    await _stream(
        client,
        "POST",
        f"/chat-rooms/{room.room_id}/messages",
        {"content": content},
        _ScriptedLLM([list(rule_ids)], ending=ending),
    )


async def _regenerate(client: httpx.AsyncClient, room: Room, *rule_ids: str) -> _ScriptedLLM:
    fake = _ScriptedLLM([list(rule_ids)])
    await _stream(client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, fake)
    return fake


async def _edit(
    client: httpx.AsyncClient, room: Room, message_id: uuid.UUID, content: str, fake: _ScriptedLLM | None = None
) -> dict[str, Any]:
    """수정 스트림의 done 이벤트."""
    events = await _stream(
        client,
        "PATCH",
        f"/chat-rooms/{room.room_id}/messages/{message_id}",
        {"content": content},
        fake if fake is not None else _ScriptedLLM(),
    )
    return events[-1]


async def _delete(client: httpx.AsyncClient, room: Room, message_id: uuid.UUID) -> dict[str, Any]:
    response = await client.delete(f"/chat-rooms/{room.room_id}/messages/{message_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _user_message(db_session: AsyncSession, room: Room, content: str) -> uuid.UUID:
    message_id = await db_session.scalar(
        sa.select(ChatMessage.id).where(
            ChatMessage.chat_room_id == room.room_id,
            ChatMessage.role == ChatMessageRole.USER,
            ChatMessage.content == content,
        )
    )
    assert message_id is not None
    return message_id


async def _replies(db_session: AsyncSession, room: Room) -> list[uuid.UUID]:
    """방의 AI 응답 id(오프닝 포함), 일어난 순서."""
    return list(
        (
            await db_session.scalars(
                sa.select(ChatMessage.id)
                .where(ChatMessage.chat_room_id == room.room_id, ChatMessage.role == ChatMessageRole.ASSISTANT)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )


async def _turn_count(db_session: AsyncSession, room: Room) -> int:
    db_session.expire_all()
    value = await db_session.scalar(sa.select(ChatRoom.turn_count).where(ChatRoom.id == room.room_id))
    assert value is not None
    return value


async def _state(db_session: AsyncSession, room: Room) -> tuple[float, float, int]:
    """(신뢰, 남은 날, turn_count). 두 스탯은 방 시작설정의 순서(1·2)로 찾는다 — 쌍둥이 방끼리 비교하려고 방마다 다시 찾는다.
    방에 행이 없는 스탯(턴이 아직 쓰지 않은 카운터)은 시작값이다."""
    db_session.expire_all()
    setup = await _setup_of(db_session, room.room_id)
    defs = {
        row.order: row
        for row in (await db_session.scalars(sa.select(StatDef).where(StatDef.starting_setup_id == setup.id))).all()
    }
    rows = {
        row.stat_entity_id: float(row.current_value)
        for row in (
            await db_session.scalars(sa.select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.room_id))
        ).all()
    }
    trust, days = (rows.get(defs[order].entity_id, float(defs[order].initial_value)) for order in (1, 2))
    return trust, days, await _turn_count(db_session, room)


async def _set_stat(db_session: AsyncSession, room: Room, stat_id: str, value: float) -> None:
    """기록 없이 방 스탯을 정한다(기록을 쓰기 전 턴이 남긴 값과 같은 꼴). 행이 없으면 만든다."""
    updated = await db_session.execute(
        sa.update(ChatRoomStat)
        .where(ChatRoomStat.chat_room_id == room.room_id, ChatRoomStat.stat_entity_id == uuid.UUID(stat_id))
        .values(current_value=value)
        .returning(ChatRoomStat.chat_room_id)
    )
    if updated.first() is None:
        db_session.add(ChatRoomStat(chat_room_id=room.room_id, stat_entity_id=uuid.UUID(stat_id), current_value=value))
    await db_session.commit()


# ── 수정 ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("with_regenerate_chain", [False, True], ids=["plain", "regenerate-chain"])
async def test_editing_an_earlier_message_leaves_the_room_as_if_the_removed_turns_never_happened(
    db_client: httpx.AsyncClient, db_session: AsyncSession, with_regenerate_chain: bool
) -> None:
    edited, _ = await _story_room(db_session, db_client)
    await _send(db_client, edited, "첫 턴", "a1")
    await _send(db_client, edited, "둘째 턴", "a2")
    if with_regenerate_chain:
        await _regenerate(db_client, edited, "a1")
    await _send(db_client, edited, "셋째 턴", "a1")

    done = await _edit(db_client, edited, await _user_message(db_session, edited, "둘째 턴"), "고친 둘째 턴")

    # 쌍둥이 방은 지운 턴 없이 같은 대화를 한다. 방마다 주인으로 로그인하므로 앞 방의 요청이 끝난 뒤 만든다.
    twin, _ = await _story_room(db_session, db_client)
    await _send(db_client, twin, "첫 턴", "a1")
    await _send(db_client, twin, "고친 둘째 턴")
    assert await _state(db_session, edited) == await _state(db_session, twin) == (78, 28, 2)
    assert done["statRewind"] == "rewound"


async def test_editing_the_first_message_returns_the_stats_to_their_starting_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    await _regenerate(db_client, room, "a2")
    await _send(db_client, room, "둘째 턴", "a1")

    await _edit(db_client, room, await _user_message(db_session, room, "첫 턴"), "다시 첫 턴")

    # 시작값(73, 30)에서 새 첫 턴이 카운터만 굴렸다.
    assert await _state(db_session, room) == (73, 29, 1)


async def test_editing_with_no_reply_after_the_edit_point_has_nothing_to_rewind(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """마지막 사용자 메시지 뒤에 응답이 없으면(생성이 실패한 턴) 지울 턴이 없다."""
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    last_reply = (await _replies(db_session, room))[-1]
    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == last_reply))
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(turn_count=0))
    await db_session.commit()

    done = await _edit(db_client, room, await _user_message(db_session, room, "첫 턴"), "고친 첫 턴")

    assert "statRewind" not in done
    assert await _state(db_session, room) == (78, 28, 1)


async def test_editing_over_old_turns_without_records_rewinds_only_the_recorded_turns_and_says_so(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client, turns=2)
    second_user_id = room.turns[2][0].id
    # 기록을 쓰기 전에 보낸 두 턴이 남긴 값.
    await _set_stat(db_session, room, stats.trust, 60)
    await _set_stat(db_session, room, stats.days, 20)
    await _send(db_client, room, "셋째 턴", "a1")
    assert await _state(db_session, room) == (65, 19, 3)

    done = await _edit(db_client, room, second_user_id, "고친 둘째 턴")

    # 기록 있는 셋째 턴만 되돌린다(60, 20) — 기록 없는 둘째 턴의 효과는 모른다. 그 뒤 새 턴이 카운터를 굴렸다.
    assert await _state(db_session, room) == (60, 19, 2)
    assert done["statRewind"] == "partial"


async def test_editing_a_room_whose_removed_replies_all_lack_records_changes_no_stat(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client, turns=2)
    second_user_id = room.turns[2][0].id
    await _set_stat(db_session, room, stats.trust, 60)
    await _set_stat(db_session, room, stats.days, 20)

    done = await _edit(db_client, room, second_user_id, "고친 둘째 턴")

    assert await _state(db_session, room) == (60, 19, 2)
    assert done["statRewind"] == "partial"


async def test_rewinding_on_edit_brings_back_the_exact_value_before_a_turn_that_hit_the_ceiling(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """98 에서 +5 는 100 에서 잘린다. 되돌린 값은 기록의 반영 전 값(98)이다 — 변화량을 빼면 95 가 된다."""
    room, stats = await _story_room(db_session, db_client)
    await _set_stat(db_session, room, stats.trust, 98)
    await _send(db_client, room, "첫 턴", "a1")
    assert await _state(db_session, room) == (100, 29, 1)

    await _edit(db_client, room, await _user_message(db_session, room, "첫 턴"), "고친 첫 턴")

    assert await _state(db_session, room) == (98, 29, 1)


async def test_edit_generation_prompt_matches_the_original_turns_prompt_when_the_rewound_values_match(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """신뢰 75 이상에서만 실리는 상황 노트가 있는 방. 첫 턴은 73 에서 생성하고 78 로 올린다. 같은 글로 고치면 73 으로 되돌린 뒤
    생성하므로 노트가 빠진 같은 프롬프트다 — 되돌리지 않으면 78 이라 노트가 실려 달라진다."""
    room, stats = await _story_room(db_session, db_client)
    setup = await _setup_of(db_session, room.room_id)
    _add_situation_note(
        db_session,
        setup,
        "표지-가까워짐",
        [
            EndingRuleDraftItem(
                id=uuid.uuid4(),
                stat_id=uuid.UUID(stats.trust),
                operator=EndingRuleOperator("gte"),
                threshold=75,
                next_op=None,
            )
        ],
    )
    await db_session.commit()
    original = _ScriptedLLM([["a1"]])
    await _stream(db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "약속을 지킨다"}, original)
    assert await _state(db_session, room) == (78, 29, 1)

    edited = _ScriptedLLM()
    await _edit(db_client, room, await _user_message(db_session, room, "약속을 지킨다"), "약속을 지킨다", edited)

    assert edited.generation_prompts == original.generation_prompts
    assert "표지-가까워짐" not in original.generation_prompts[0]


# ── 삭제 ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("with_regenerate_chain", [False, True], ids=["plain", "regenerate-chain"])
async def test_deleting_the_last_reply_leaves_the_room_as_if_that_turn_never_happened(
    db_client: httpx.AsyncClient, db_session: AsyncSession, with_regenerate_chain: bool
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    await _send(db_client, room, "둘째 턴", "a2")
    if with_regenerate_chain:
        await _regenerate(db_client, room, "a1")
        await _regenerate(db_client, room, "a2")

    body = await _delete(db_client, room, (await _replies(db_session, room))[-1])

    twin, _ = await _story_room(db_session, db_client)
    await _send(db_client, twin, "첫 턴", "a1")
    assert await _state(db_session, room) == await _state(db_session, twin) == (78, 29, 1)
    assert body == {"statRewind": "rewound"}


async def test_deleting_turns_from_the_end_one_by_one_returns_to_the_opening_state(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    await _regenerate(db_client, room, "a2")
    await _send(db_client, room, "둘째 턴", "a1")
    await _send(db_client, room, "셋째 턴", "a1")
    assert await _state(db_session, room) == (81, 27, 3)

    outcomes = []
    for content in ("셋째 턴", "둘째 턴"):
        outcomes.append((await _delete(db_client, room, (await _replies(db_session, room))[-1]))["statRewind"])
        outcomes.append((await _delete(db_client, room, await _user_message(db_session, room, content)))["statRewind"])
    assert await _state(db_session, room) == (71, 29, 1)
    outcomes.append((await _delete(db_client, room, (await _replies(db_session, room))[-1]))["statRewind"])

    assert await _state(db_session, room) == (73, 30, 0)
    # 사용자 메시지 삭제는 아무것도 바꾸지 않아 알릴 것이 없다.
    assert outcomes == ["rewound", None, "rewound", None, "rewound"]


async def test_deleting_a_middle_reply_keeps_stats_and_turn_count_and_says_so(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    await _send(db_client, room, "둘째 턴", "a2")
    await _send(db_client, room, "셋째 턴", "a1")
    middle = (await _replies(db_session, room))[2]

    body = await _delete(db_client, room, middle)

    assert body == {"statRewind": "kept"}
    assert await _state(db_session, room) == (81, 27, 3)


async def test_after_a_middle_reply_is_deleted_the_last_reply_is_still_rejudged_on_regenerate(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """중간 삭제가 턴 수를 줄이면 남은 마지막 응답의 기록 번호(3)가 방 턴 수와 어긋나 재생성이 그 턴을 되돌려 다시 판정하지
    못한다."""
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    await _send(db_client, room, "둘째 턴", "a2")
    await _send(db_client, room, "셋째 턴", "a1")
    await _delete(db_client, room, (await _replies(db_session, room))[2])

    fake = await _regenerate(db_client, room, "a2")

    assert fake.stat_calls == 1
    # 셋째 턴의 반영 전 값(76, 28)에서 다시 판정했다.
    assert await _state(db_session, room) == (74, 27, 3)


async def test_after_the_last_reply_is_deleted_the_previous_reply_can_be_rejudged_and_the_next_turn_takes_its_number(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    await _send(db_client, room, "둘째 턴", "a1")
    await _delete(db_client, room, (await _replies(db_session, room))[-1])
    await _delete(db_client, room, await _user_message(db_session, room, "둘째 턴"))

    fake = await _regenerate(db_client, room, "a2")
    assert fake.stat_calls == 1
    assert await _state(db_session, room) == (71, 29, 1)

    await _send(db_client, room, "새 둘째 턴")
    last_reply = (await _replies(db_session, room))[-1]
    record = await db_session.scalar(sa.select(ChatTurn).where(ChatTurn.assistant_message_id == last_reply))
    assert record is not None
    assert record.turn_number == 2
    assert await _state(db_session, room) == (71, 28, 2)


async def test_deleting_the_last_reply_of_an_old_turn_without_a_record_changes_nothing_and_says_so(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client, turns=2)
    second_reply_id = room.turns[2][1].id
    await _set_stat(db_session, room, stats.trust, 60)

    body = await _delete(db_client, room, second_reply_id)

    assert body == {"statRewind": "partial"}
    assert await _state(db_session, room) == (60, 30, 2)


async def test_deleting_the_opening_of_a_room_without_turns_changes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _ = await _story_room(db_session, db_client)
    [opening] = await _replies(db_session, room)

    body = await _delete(db_client, room, opening)

    assert body == {"statRewind": None}
    assert await _state(db_session, room) == (73, 30, 0)


async def test_deleting_the_last_reply_whose_turn_is_not_the_rooms_last_turn_keeps_everything(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """옛 이미지의 메시지 삭제는 턴 수를 줄이지 않았다 — 그 방에서 마지막 응답의 기록 번호(2)는 방 턴 수(3)보다 작고, 그 기록의
    반영 전 값은 옛 삭제가 남긴 효과까지 지운다. 재생성·되돌리기와 같은 조건이라 되돌리지 않는다."""
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")
    await _send(db_client, room, "둘째 턴", "a2")
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(turn_count=3))
    await db_session.commit()

    body = await _delete(db_client, room, (await _replies(db_session, room))[-1])

    assert body == {"statRewind": "kept"}
    assert await _state(db_session, room) == (76, 28, 3)


async def test_rewinding_on_delete_respects_both_ends_of_the_range(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """신뢰 98 → 100(위에서 잘림), 남은 날 1 → 0 → 0(아래에서 잘림). 지울 때마다 그 턴 전 값으로 정확히 돌아간다."""
    room, stats = await _story_room(db_session, db_client)
    await _set_stat(db_session, room, stats.trust, 98)
    await _set_stat(db_session, room, stats.days, 1)
    await _send(db_client, room, "첫 턴", "a1")
    await _send(db_client, room, "둘째 턴", "a1")
    assert await _state(db_session, room) == (100, 0, 2)

    await _delete(db_client, room, (await _replies(db_session, room))[-1])
    assert await _state(db_session, room) == (100, 0, 1)
    await _delete(db_client, room, await _user_message(db_session, room, "둘째 턴"))
    await _delete(db_client, room, (await _replies(db_session, room))[-1])
    assert await _state(db_session, room) == (98, 1, 0)


async def test_deleting_a_user_message_changes_nothing(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, "첫 턴", "a1")

    body = await _delete(db_client, room, await _user_message(db_session, room, "첫 턴"))

    assert body == {"statRewind": None}
    assert await _state(db_session, room) == (78, 29, 1)


# ── 엔딩 ──────────────────────────────────────────────────────────────────────────────────


async def _ended_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Room, uuid.UUID]:
    """첫 턴에 엔딩이 난 방(신뢰 78, 남은 날 29)과 그 엔딩 entity_id."""
    room, _ = await _story_room(db_session, db_client)
    setup = await _setup_of(db_session, room.room_id)
    ending_id = uuid.uuid4()
    ending = Ending(
        entity_id=ending_id,
        starting_setup_id=setup.id,
        name="떠남",
        turn_count_gate=1,
        judgment_prompt="떠났는가?",
        epilogue="떠났다.",
        order=1,
    )
    db_session.add(ending)
    await db_session.commit()
    await _send(db_client, room, "약속을 지킨다", "a1", ending=True)
    assert await _ending_of(db_session, room) == (True, ending_id, 1)
    assert await _state(db_session, room) == (78, 29, 1)
    return room, ending_id


async def _ending_of(db_session: AsyncSession, room: Room) -> tuple[Any, ...]:
    db_session.expire_all()
    row = (
        await db_session.execute(
            sa.select(ChatRoom.ending_reached, ChatRoom.ending_entity_id, ChatRoom.ending_reached_at_turn).where(
                ChatRoom.id == room.room_id
            )
        )
    ).one()
    return tuple(row)


async def _unlocks(db_session: AsyncSession, room: Room) -> list[uuid.UUID]:
    return list(
        (
            await db_session.scalars(
                sa.select(StoryEndingUnlock.ending_entity_id).where(StoryEndingUnlock.user_id == room.user_id)
            )
        ).all()
    )


async def test_editing_away_the_ending_turn_rewinds_the_stats_but_keeps_the_ending(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, ending_id = await _ended_room(db_client, db_session)

    done = await _edit(db_client, room, await _user_message(db_session, room, "약속을 지킨다"), "다시")

    # 엔딩 뒤라 새 턴은 판정하지 않는다 — 되돌린 시작값 그대로다.
    assert await _state(db_session, room) == (73, 30, 1)
    assert await _ending_of(db_session, room) == (True, ending_id, 1)
    assert await _unlocks(db_session, room) == [ending_id]
    assert done["statRewind"] == "rewound"


async def test_deleting_the_ending_reply_rewinds_the_stats_but_keeps_the_ending(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, ending_id = await _ended_room(db_client, db_session)

    body = await _delete(db_client, room, (await _replies(db_session, room))[-1])

    assert body == {"statRewind": "rewound"}
    assert await _state(db_session, room) == (73, 30, 0)
    assert await _ending_of(db_session, room) == (True, ending_id, 1)
    assert await _unlocks(db_session, room) == [ending_id]
