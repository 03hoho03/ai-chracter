"""방 고정값 — 측정 드라이버가 방을 만들 때 DB 에서 읽어 기록하고, 리플레이가 실행 때 DB 지금 값과 대조하는 값.
대조는 작품 버전·시작 설정·생성 모델·대화 프로필 id·`{{user}}` 이름만 본다. 프로필 성별·설명은 기록만 하고 조립에 쓴다
— 측정 뒤 프로필을 고쳐도 리플레이가 되고, 본문까지 대조하면 기록을 쓰는지 DB 를 읽는지 구분되지 않는다."""

import dataclasses
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.turn_prompt import InjectedPersona
from api.db.models.chat import ChatRoom
from api.db.models.persona import UserPersona
from factories import _story_with_setup
from replay.logs import ReplayRefusedError
from replay.room_fixed import RoomFixed, diff_fixed, load_room_fixed


async def _room(db_session: AsyncSession, *, persona: UserPersona | None) -> tuple[ChatRoom, uuid.UUID]:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와")
    assert content.current_published_version_id is not None
    if persona is not None:
        persona.user_id = user_id
        db_session.add(persona)
        await db_session.flush()
    room = ChatRoom(
        user_id=user_id,
        content_id=content.id,
        content_version_id=content.current_published_version_id,
        starting_setup_entity_id=setup.entity_id,
        persona_id=persona.id if persona is not None else None,
        chat_model="sonnet",
    )
    db_session.add(room)
    await db_session.flush()
    return room, setup.id


async def test_load_reads_the_fixed_values_and_the_full_persona(db_session: AsyncSession) -> None:
    persona = UserPersona(user_id=uuid.uuid4(), name="하늘", gender="female", description="밤에만 글을 쓴다")
    room, setup_row_id = await _room(db_session, persona=persona)

    fixed = await load_room_fixed(db_session, room.id)

    assert fixed == RoomFixed(
        content_version_id=room.content_version_id,
        starting_setup_entity_id=room.starting_setup_entity_id,
        pinned_starting_setup_id=setup_row_id,
        chat_model="sonnet",
        persona_id=persona.id,
        persona_name="하늘",
        persona=InjectedPersona(name="하늘", gender="female", description="밤에만 글을 쓴다"),
    )
    assert fixed.user_name == "하늘"


async def test_load_without_persona_uses_the_fallback_name(db_session: AsyncSession) -> None:
    # 서버의 `{{user}}` 치환과 같은 규칙 — 프로필이 없으면 "당신".
    room, _ = await _room(db_session, persona=None)

    fixed = await load_room_fixed(db_session, room.id)

    assert fixed is not None
    assert (fixed.persona_id, fixed.persona, fixed.user_name) == (None, None, "당신")


async def test_load_of_a_missing_room_is_none(db_session: AsyncSession) -> None:
    assert await load_room_fixed(db_session, uuid.uuid4()) is None


def _fixed(**changes: Any) -> RoomFixed:
    base = RoomFixed(
        content_version_id=uuid.UUID(int=1),
        starting_setup_entity_id=uuid.UUID(int=2),
        pinned_starting_setup_id=uuid.UUID(int=3),
        chat_model=None,
        persona_id=uuid.UUID(int=4),
        persona_name="하늘",
        persona=InjectedPersona(name="하늘", gender=None, description="첫 설명"),
    )
    return dataclasses.replace(base, **changes)


def test_diff_names_each_compared_value_that_changed() -> None:
    recorded = _fixed()
    current = _fixed(
        content_version_id=uuid.UUID(int=9),
        starting_setup_entity_id=uuid.UUID(int=8),
        chat_model="opus",
        persona_id=uuid.UUID(int=7),
        persona_name="바다",
        persona=InjectedPersona(name="바다", gender=None, description="첫 설명"),
    )

    diffs = diff_fixed(recorded, current)

    assert [d.split(":")[0] for d in diffs] == [
        "contentVersionId",
        "startingSetupEntityId",
        "chatModel",
        "personaId",
        "userName",
    ]
    assert "하늘" in diffs[-1] and "바다" in diffs[-1]


def test_diff_ignores_the_persona_body_and_the_physical_setup_row() -> None:
    # 성별·설명은 기록값으로 조립하므로 바뀌어도 거부하지 않는다. 시작 설정은 버전을 넘어 안정적인 entity_id 로 본다.
    recorded = _fixed()
    current = _fixed(
        pinned_starting_setup_id=uuid.UUID(int=99),
        persona=InjectedPersona(name="하늘", gender="male", description="고친 설명"),
    )

    assert diff_fixed(recorded, current) == []


def test_record_round_trip_keeps_every_value_and_old_records_have_none() -> None:
    fixed = _fixed(chat_model="sonnet")

    record = fixed.as_record()

    assert record["persona"] == {"name": "하늘", "gender": None, "description": "첫 설명"}
    assert record["userName"] == "하늘"
    assert set(record) == set(RoomFixed.RECORD_KEYS)
    assert RoomFixed.from_record(record) == fixed
    # 이 값들을 기록하기 전의 옛 로그(방 고정값 없음)는 None 이다 — 리플레이가 "고정값 기록 없음"을 남긴다.
    assert RoomFixed.from_record({"kind": "roomStatic", "stats": [], "names": {}}) is None


@pytest.mark.parametrize("old_value", [pytest.param("", id="empty"), pytest.param(None, id="null")])
def test_old_record_with_an_empty_default_user_name_still_reads(old_value: str | None) -> None:
    # 작품 기본 이름 단계를 지우기 전의 기록에는 이 키가 있다. 값이 비어 있으면 그 기록의 이름 조건은 지금과 같다.
    fixed = _fixed()

    assert RoomFixed.from_record({**fixed.as_record(), "defaultUserName": old_value}) == fixed


def test_old_record_with_a_default_user_name_is_refused() -> None:
    # 값이 든 옛 기록은 지금 코드가 재현할 수 없는 이름으로 조립됐다 — 다른 이름으로 조용히 재현하지 않고 거부한다.
    record = {**_fixed(persona_id=None, persona_name=None, persona=None).as_record(), "defaultUserName": "여행자"}

    with pytest.raises(ReplayRefusedError, match="작품 기본 이름"):
        RoomFixed.from_record(record)
