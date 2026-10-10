"""생성 프롬프트 조립(`build_room_prompt`)에 턴 상태 묶음을 넘기면 방의 지금 값 대신 그 값으로 조립하는지.

지난 턴을 그때 상태로 다시 조립하는 측정 도구가 이 자리를 쓴다. 방의 요약·기억 노트·스탯·대화 프로필은 지금 값만
남으므로, 묶음의 값이 어느 한 자리에서라도 DB 값과 섞이면 다시 만든 프롬프트가 그 턴의 실제 프롬프트와 어긋난다.
묶음을 넘기지 않는 실제 대화 경로는 `test_chat_prompt_baseline.py`·`test_prompt_goldens.py` 가 프롬프트를 바이트로 지키고,
대화 프로필 이름 쪽은 `test_chat_room_author_names_api.py` 가 지킨다(기준선에는 대화 프로필이 있는 경우가 없다)."""

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import CurrentSummary
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.router import _resolve_starting_setup
from api.chat.turn_prompt import InjectedPersona, InjectedTurnState, build_room_prompt
from api.content.schemas import EndingRuleDraftItem
from api.core.config import settings
from api.db.models import ChatRoom, ChatRoomStat, StartingSetup, StatDef, StoryVersionDetail
from api.db.models.chat import ChatMessage
from api.db.models.story import EndingRuleOperator
from factories import (
    Room,
    _add_situation_note,
    _make_default_persona,
    _make_user,
    _open_room,
    _plant_snapshot,
    _user_text,
)

_DB_SUMMARY = "DB에 남은 지금 요약"
_DB_NOTE = "DB에 남은 지금 기억 노트"
_DB_PERSONA_NAME = "지금프로필"
_DB_PERSONA_DESCRIPTION = "지금 프로필 설명"
_INJECTED_SUMMARY = "그 턴의 요약"
_INJECTED_NOTE = "그 턴의 기억 노트"
_INJECTED_PERSONA = InjectedPersona(name="그때프로필", gender="female", description="그때 프로필 설명")
_HIGH_TRUST_NOTE = "신뢰가 높을 때만 실리는 상황"
_TRUST_GATE = 80


async def _story_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Room, uuid.UUID]:
    """세 턴짜리 스토리 방에 지금 값(요약·노트·프로필·신뢰 73)을 심는다. 작가 글에 `{{user}}` 를 두고, 신뢰가 문턱 이상일
    때만 실리는 상황 노트를 단다. 신뢰 스탯의 entity_id 를 함께 돌려준다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    persona = await _make_default_persona(db_session, user.id, _DB_PERSONA_NAME)
    persona.description = _DB_PERSONA_DESCRIPTION
    room = await _open_room(db_client, db_session, turns=3, lane="story", user=user)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None and chat_room.persona_id == persona.id
    chat_room.memory_note = _DB_NOTE
    detail = await db_session.get(StoryVersionDetail, chat_room.content_version_id)
    assert detail is not None
    detail.setting_text = "{{user}}의 옥상 이야기"
    detail.default_user_name = "작품기본이름"
    setup = await _resolve_starting_setup(db_session, chat_room)
    assert setup is not None
    trust_id = await db_session.scalar(select(StatDef.entity_id).where(StatDef.starting_setup_id == setup.id))
    assert trust_id is not None
    rule = EndingRuleDraftItem(
        id=uuid.uuid4(), stat_id=trust_id, operator=EndingRuleOperator("gte"), threshold=_TRUST_GATE, next_op=None
    )
    _add_situation_note(db_session, setup, _HIGH_TRUST_NOTE, [rule])
    await db_session.commit()
    await _plant_snapshot(db_session, room, turn=1, text=_DB_SUMMARY)
    return room, trust_id


async def _build(
    db_session: AsyncSession, room: Room, turn_state: InjectedTurnState | None
) -> tuple[str, bool, str | None]:
    """이 방의 전체 히스토리로 다음 턴 프롬프트를 조립해 (프롬프트, 프로필이 실렸는가, `{{user}}` 를 채운 프로필 이름) 을
    돌려준다."""
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup: StartingSetup | None = await _resolve_starting_setup(db_session, chat_room)
    history = list(
        (
            await db_session.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.room_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    prompt, _, persona_rendered, _, names = await build_room_prompt(
        db_session, chat_room, setup, history, "이번 메시지", None, prompt_set, sections, turn_state=turn_state
    )
    return prompt, persona_rendered, names.persona_name


def _turn_state(room: Room, trust_id: uuid.UUID, *, trust: float, summary_turn: int | None = 2) -> InjectedTurnState:
    summary = None
    if summary_turn is not None:
        cursor_message = room.turns[summary_turn][1]
        summary = CurrentSummary(cursor=(cursor_message.created_at, cursor_message.id), text=_INJECTED_SUMMARY)
    return InjectedTurnState(
        summary=summary, memory_note=_INJECTED_NOTE, stats={str(trust_id): trust}, persona=_INJECTED_PERSONA
    )


async def test_injected_turn_state_is_assembled_instead_of_room_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, trust_id = await _story_room(db_client, db_session)

    prompt, persona_rendered, persona_name = await _build(
        db_session, room, _turn_state(room, trust_id, trust=_TRUST_GATE + 10)
    )

    # 요약: 주입 커서(턴 2 응답)까지 잘리고 주입 본문이 실린다 — DB 스냅샷(턴 1)이 쓰였다면 턴 2 가 남는다.
    assert _INJECTED_SUMMARY in prompt and _DB_SUMMARY not in prompt
    assert [_user_text(turn, 20) in prompt for turn in (1, 2, 3)] == [False, False, True]
    assert _INJECTED_NOTE in prompt and _DB_NOTE not in prompt
    # 방의 신뢰는 73(문턱 아래)이라, 노트가 실렸다면 주입 값으로 조건을 본 것이다.
    assert _HIGH_TRUST_NOTE in prompt
    # 프로필 섹션·`{{user}}` 치환·이름 한 줄이 모두 주입 프로필을 본다 — 지금 프로필 이름은 어디에도 없다.
    assert _INJECTED_PERSONA.description in prompt and _DB_PERSONA_DESCRIPTION not in prompt
    assert f"{_INJECTED_PERSONA.name}의 옥상 이야기" in prompt
    assert _DB_PERSONA_NAME not in prompt
    assert (persona_rendered, persona_name) == (True, _INJECTED_PERSONA.name)
    assert not db_session.dirty and not db_session.new


async def test_injected_low_stat_drops_situation_note_the_room_would_show(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, trust_id = await _story_room(db_client, db_session)
    await db_session.execute(
        sa.update(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.room_id).values(current_value=_TRUST_GATE + 10)
    )
    await db_session.commit()
    without_injection, _, _ = await _build(db_session, room, None)
    assert _HIGH_TRUST_NOTE in without_injection

    prompt, _, _ = await _build(db_session, room, _turn_state(room, trust_id, trust=_TRUST_GATE - 1))

    assert _HIGH_TRUST_NOTE not in prompt


async def test_injected_no_summary_sends_full_history_despite_room_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, trust_id = await _story_room(db_client, db_session)

    prompt, _, _ = await _build(db_session, room, _turn_state(room, trust_id, trust=0, summary_turn=None))

    assert _DB_SUMMARY not in prompt
    assert all(_user_text(turn, 20) in prompt for turn in (1, 2, 3))


async def test_injected_summary_is_ignored_when_generation_window_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "memory_window_generation", False)
    room, trust_id = await _story_room(db_client, db_session)

    prompt, _, _ = await _build(db_session, room, _turn_state(room, trust_id, trust=0))

    assert _INJECTED_SUMMARY not in prompt and _DB_SUMMARY not in prompt
    assert all(_user_text(turn, 20) in prompt for turn in (1, 2, 3))


async def test_injected_no_persona_falls_back_to_work_default_name_despite_room_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, trust_id = await _story_room(db_client, db_session)
    turn_state = _turn_state(room, trust_id, trust=0)
    no_persona = InjectedTurnState(
        summary=turn_state.summary, memory_note=turn_state.memory_note, stats=turn_state.stats, persona=None
    )

    prompt, persona_rendered, persona_name = await _build(db_session, room, no_persona)

    assert _DB_PERSONA_NAME not in prompt and _DB_PERSONA_DESCRIPTION not in prompt
    assert "작품기본이름의 옥상 이야기" in prompt
    assert (persona_rendered, persona_name) == (False, None)


async def test_injected_name_only_persona_is_not_counted_for_the_policy_warning(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정책 안내는 프로필 설명이 실린 턴에만 프로필을 언급한다. 설명 유무도 주입 프로필을 본다 — 방의 지금 프로필에는
    설명이 있어서, 그쪽을 보면 참이 된다."""
    room, trust_id = await _story_room(db_client, db_session)
    turn_state = _turn_state(room, trust_id, trust=0)
    name_only = InjectedTurnState(
        summary=turn_state.summary,
        memory_note=turn_state.memory_note,
        stats=turn_state.stats,
        persona=InjectedPersona(name=_INJECTED_PERSONA.name, gender=None, description=""),
    )

    prompt, persona_rendered, persona_name = await _build(db_session, room, name_only)

    assert f"{_INJECTED_PERSONA.name}의 옥상 이야기" in prompt
    assert (persona_rendered, persona_name) == (False, _INJECTED_PERSONA.name)
