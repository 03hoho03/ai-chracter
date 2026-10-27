"""방 기억 보기 — 요약 접기가 뽑은 장면·사실 기억을 방 주인에게 보여 준다.

- 무엇을: 장면은 지금 요약 커서까지 접힌 스냅샷이 뽑았고 커서 이하에서 끝나는 것(회상 후보와 같은 조건)을 일어난 순서로
  페이지씩, 사실은 같은 커서까지의 행을 키마다 이긴 행 하나로 줄여(사실 섹션과 같은 규칙) 전부. 사용자가 보는 것과 모델이
  보는 것이 같아야 "지운다"가 뜻이 선다.
- 진실 상태는 사용자 말로 바꿔 싣고, 말한 사람은 꼬리표로 따로 싣는다. 아는 사람 칸은 싣지 않는다(내부 가림 장치다).
- 방마다 장면·사실이 실제로 응답에 쓰이는지(스위치 ∧ 그 방의 레인·다음 턴 모델이 기억 사용 범위에 듦)를 함께 싣는다 — 같은
  기억이라도 범위 밖 방에서는 쌓이기만 하고 응답에는 안 쓰인다.
- 스위치가 꺼져 있으면 라우트는 등록된 채 404 `MEMORY_ITEMS_DISABLED` 다. 기존 기억 응답의 기능 칸이 화면에 "꺼짐"과 "없음"을
  가르게 해 준다.
- 관계 인상은 따로 둔 화면 스위치가 켜져 있고 방의 레인·다음 턴 모델이 기억 사용 범위에 들 때만 목록(최근 묶음 먼저)이고, 아니면
  null 이라 화면이 구획을 그리지 않는다. 근거는 개수와 근거 행의 턴 범위만 싣고 근거 행 id 는 싣지 않는다 — 개수·범위는 저장된
  id 배열 길이가 아니라 지금 남아 있는 근거 행에서 센다.

깨지는 시나리오: 같은 키의 옛 값이 보여 지운 뒤에도 남은 것처럼 읽힌다, 커서 뒤 행이 보여 모델이 아직 안 보는 기억을 보인다,
남의 방 기억이 보인다, 꺼진 스위치에서 목록이 열린다, 모델을 바꿔 범위 밖이 된 방에 인상이 보인다, 지운 근거가 개수에 남는다.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import ChatMemoryEpisode, ChatMemoryFact, ChatMemoryImpression, ChatRoom, ChatRoomMemorySnapshot
from factories import (
    Room,
    _enable_chat_premium,
    _login_as,
    _make_memory_episode,
    _make_memory_fact,
    _make_user,
    _memory_scope_covers_gemini,
    _open_room,
)


@pytest.fixture
def items_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_items_visible", True)


def _items_path(room: Room) -> str:
    return f"/chat-rooms/{room.room_id}/memory/items"


async def _snapshot_at(db_session: AsyncSession, room: Room, *, turn: int) -> uuid.UUID:
    """`turn` 의 응답 메시지를 커서로 하는 요약 스냅샷 하나를 커밋하고 그 id."""
    assistant = room.turns[turn][1]
    snapshot = ChatRoomMemorySnapshot(
        chat_room_id=room.room_id,
        cursor_created_at=assistant.created_at,
        cursor_message_id=assistant.id,
        summary_text=f"{turn}턴까지의 요약",
        source="auto",
    )
    db_session.add(snapshot)
    await db_session.commit()
    return snapshot.id


def _ends_at(room: Room, turn: int) -> dict[str, object]:
    """그 턴 응답 메시지에서 시작하고 끝나는 근거 범위 칸."""
    assistant = room.turns[turn][1]
    return {
        "start_created_at": assistant.created_at,
        "start_message_id": assistant.id,
        "end_created_at": assistant.created_at,
        "end_message_id": assistant.id,
        "start_turn": turn,
        "end_turn": turn,
    }


# ---- 스위치 ----


async def test_items_are_not_found_while_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    db_session.add(_make_memory_episode(room.room_id, snapshot, **_ends_at(room, 5)))
    db_session.add(_make_memory_fact(room.room_id, snapshot, **_ends_at(room, 5)))
    await db_session.commit()

    resp = await db_client.get(_items_path(room))

    assert settings.memory_items_visible is False
    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "MEMORY_ITEMS_DISABLED"}


async def test_memory_response_tells_whether_items_are_visible_and_summaries_are_folded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _open_room(db_client, db_session, turns=0)

    off = (await db_client.get(f"/chat-rooms/{room.room_id}/memory")).json()
    monkeypatch.setattr(settings, "memory_items_visible", True)
    monkeypatch.setattr(settings, "memory_window_generation", False)
    flipped = (await db_client.get(f"/chat-rooms/{room.room_id}/memory")).json()

    assert off["features"] == {"itemsVisible": False, "summaryFolding": True}
    assert flipped["features"] == {"itemsVisible": True, "summaryFolding": False}


# ---- 주인 확인 ----


@pytest.mark.usefixtures("items_visible")
async def test_someone_elses_room_is_refused_and_a_missing_room_is_not_found(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    db_session.add(_make_memory_episode(room.room_id, snapshot, **_ends_at(room, 5)))
    await db_session.commit()
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.commit()
    await _login_as(db_client, stranger.id)

    foreign = await db_client.get(_items_path(room))
    missing = await db_client.get(f"/chat-rooms/{uuid.uuid4()}/memory/items")

    assert foreign.status_code == 403
    assert missing.status_code == 404


# ---- 목록 ----


@pytest.mark.usefixtures("items_visible")
async def test_a_room_without_a_summary_has_no_items(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=3)

    resp = await db_client.get(_items_path(room))

    assert resp.status_code == 200
    body = resp.json()
    assert (body["episodes"], body["facts"], body["nextCursor"]) == ([], [], None)


@pytest.mark.usefixtures("items_visible")
async def test_scenes_are_listed_in_story_order_without_who_knows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    later = _make_memory_episode(
        room.room_id, snapshot, ordinal=0, title="등대에 오른 밤", detail="등대 꼭대기에서 불빛을 셌다.",
        asserted_by="character", known_by=["지아"], **_ends_at(room, 8),
    )
    earlier = _make_memory_episode(
        room.room_id, snapshot, ordinal=1, title="파란 우산", detail="정류장에서 우산을 빌려주었다.", **_ends_at(room, 3)
    )
    db_session.add_all([later, earlier])
    await db_session.commit()

    body = (await db_client.get(_items_path(room))).json()

    assert body["episodes"] == [
        {
            "id": str(earlier.id),
            "title": "파란 우산",
            "detail": "정류장에서 우산을 빌려주었다.",
            "assertedBy": "user",
            "startTurn": 3,
            "endTurn": 3,
        },
        {
            "id": str(later.id),
            "title": "등대에 오른 밤",
            "detail": "등대 꼭대기에서 불빛을 셌다.",
            "assertedBy": "character",
            "startTurn": 8,
            "endTurn": 8,
        },
    ]
    assert body["nextCursor"] is None


@pytest.mark.usefixtures("items_visible")
async def test_scenes_ending_after_the_summary_cursor_are_left_out(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=15)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    inside = _make_memory_episode(room.room_id, snapshot, ordinal=0, title="커서 안", **_ends_at(room, 10))
    outside = _make_memory_episode(room.room_id, snapshot, ordinal=1, title="커서 뒤", **_ends_at(room, 11))
    db_session.add_all([inside, outside])
    await db_session.commit()

    body = (await db_client.get(_items_path(room))).json()

    assert [episode["title"] for episode in body["episodes"]] == ["커서 안"]


@pytest.mark.usefixtures("items_visible")
async def test_scenes_page_forward_with_the_next_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.chat import memory_items

    monkeypatch.setattr(memory_items, "EPISODE_PAGE_SIZE", 2)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    # 두 장면은 같은 메시지에서 끝난다 — 끝 키가 같아도 페이지 경계에서 빠지거나 겹치지 않아야 한다.
    for ordinal, turn in enumerate((2, 4, 4, 6, 8)):
        db_session.add(
            _make_memory_episode(room.room_id, snapshot, ordinal=ordinal, title=f"장면{ordinal}", **_ends_at(room, turn))
        )
    await db_session.commit()

    seen: list[str] = []
    pages = 0
    cursor: str | None = None
    while True:
        params = {"cursor": cursor} if cursor is not None else {}
        resp = await db_client.get(_items_path(room), params=params)
        assert resp.status_code == 200
        body = resp.json()
        pages += 1
        assert len(body["episodes"]) <= 2
        seen.extend(episode["title"] for episode in body["episodes"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert pages == 3
    assert sorted(seen) == [f"장면{n}" for n in range(5)]
    assert seen[0] == "장면0" and seen[-1] == "장면4"


@pytest.mark.usefixtures("items_visible")
async def test_a_broken_page_cursor_is_rejected(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=3)

    resp = await db_client.get(_items_path(room), params={"cursor": "not-a-cursor"})

    assert resp.status_code == 422
    assert resp.json()["detail"] == {"code": "MEMORY_ITEMS_CURSOR_INVALID"}


@pytest.mark.usefixtures("items_visible")
async def test_each_fact_key_shows_only_the_row_that_wins(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    first = await _snapshot_at(db_session, room, turn=10)
    second = await _snapshot_at(db_session, room, turn=20)
    # 관계 키: 앞 접기 "소꿉친구" → 뒤 접기 "연인". 지금 값은 뒤 행이다.
    db_session.add(_make_memory_fact(room.room_id, first, ordinal=0, value="소꿉친구", **_ends_at(room, 4)))
    db_session.add(_make_memory_fact(room.room_id, second, ordinal=0, value="연인", **_ends_at(room, 15)))
    # 속성 키: 반박된 값을 뒤에서 다시 주장해도 반박이 이긴다(사실 섹션과 같은 규칙).
    hair = {"kind": "fact", "subject": "지아", "object": None, "attribute": "머리색", "fact_key": "fact|지아|머리색"}
    disproved = _make_memory_fact(
        room.room_id, first, ordinal=1, value="금발", truth_status="disproved", speaker="민수", **hair,
        **_ends_at(room, 6),
    )
    db_session.add(disproved)
    db_session.add(
        _make_memory_fact(
            room.room_id, second, ordinal=1, value="금발", truth_status="claimed", speaker="민수", **hair,
            **_ends_at(room, 18),
        )
    )
    await db_session.commit()

    facts = (await db_client.get(_items_path(room))).json()["facts"]

    by_key = {fact["factKey"]: fact for fact in facts}
    assert len(facts) == 2
    assert by_key["relation|민수|지아"]["value"] == "연인"
    assert by_key["fact|지아|머리색"]["id"] == str(disproved.id)


@pytest.mark.usefixtures("items_visible")
async def test_a_fact_carries_its_truth_label_and_speaker_but_not_who_knows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    fact = _make_memory_fact(
        room.room_id, snapshot, value="비밀 약혼", truth_status="claimed", asserted_by="character", speaker="지아",
        known_by=["지아"], **_ends_at(room, 7),
    )
    db_session.add(fact)
    await db_session.commit()

    facts = (await db_client.get(_items_path(room))).json()["facts"]

    assert facts == [
        {
            "id": str(fact.id),
            "factKey": "relation|민수|지아",
            "kind": "relation",
            "subject": "민수",
            "object": "지아",
            "attribute": None,
            "value": "비밀 약혼",
            "truthStatus": "claimed",
            "truthLabel": "누군가의 말",
            "assertedBy": "character",
            "speaker": "지아",
            "startTurn": 7,
            "endTurn": 7,
        }
    ]


def test_truth_states_read_as_plain_words() -> None:
    from api.chat.memory_items import truth_label

    assert truth_label("confirmed") == "이야기 속 사실"
    assert truth_label("claimed") == "누군가의 말"
    assert truth_label("disproved") == "나중에 아니라고 밝혀진 말"


# ---- 응답에 쓰이는가 ----


async def _used(db_client: httpx.AsyncClient, room: Room) -> tuple[bool, bool]:
    body = (await db_client.get(_items_path(room))).json()
    return body["episodesUsedInReplies"], body["factsUsedInReplies"]


@pytest.mark.usefixtures("items_visible")
async def test_scenes_and_facts_are_used_only_when_their_switch_is_on_and_the_room_is_in_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _open_room(db_client, db_session, turns=3)
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    monkeypatch.setattr(settings, "memory_facts_inject", False)

    # 기본 범위는 Opus 방뿐 — Gemini 방은 스위치가 켜져 있어도 안 쓰인다.
    out_of_scope = await _used(db_client, room)
    _memory_scope_covers_gemini(monkeypatch)
    in_scope = await _used(db_client, room)
    monkeypatch.setattr(settings, "memory_facts_inject", True)
    both = await _used(db_client, room)
    monkeypatch.setattr(settings, "memory_window_generation", False)
    no_window = await _used(db_client, room)

    assert out_of_scope == (False, False)
    assert in_scope == (True, False)
    assert both == (True, True)
    assert no_window == (False, False)


@pytest.mark.usefixtures("items_visible")
async def test_usage_follows_the_model_the_next_turn_will_use(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _open_room(db_client, db_session, turns=3, lane="story")
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model="opus"))
    await db_session.commit()
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus")])

    # 상위 모델 스위치가 꺼져 있으면 Opus 를 고른 방도 다음 턴은 기본 모델로 돈다.
    premium_off = await _used(db_client, room)
    _enable_chat_premium(monkeypatch)
    premium_on = await _used(db_client, room)
    monkeypatch.setattr(settings, "memory_model_scope", [("character", "opus")])
    other_lane = await _used(db_client, room)

    assert premium_off == (False, False)
    assert premium_on == (True, False)
    assert other_lane == (False, False)


# ---- 관계 인상 ----


@pytest.fixture
def impressions_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_items_visible", True)
    monkeypatch.setattr(settings, "memory_impressions_visible", True)


async def _impression(
    db_session: AsyncSession,
    room: Room,
    snapshot_id: uuid.UUID,
    *,
    episodes: Sequence[ChatMemoryEpisode] = (),
    facts: Sequence[ChatMemoryFact] = (),
    text: str = "서로를 경계하던 두 사람이 조금씩 마음을 연다.",
) -> ChatMemoryImpression:
    """스냅샷 하나를 덮는 인상 한 행을 커밋한다. 근거 칸은 넘긴 장면·사실 행의 id 다."""
    snapshot = await db_session.get(ChatRoomMemorySnapshot, snapshot_id)
    assert snapshot is not None
    row = ChatMemoryImpression(
        chat_room_id=room.room_id,
        snapshot_id=snapshot_id,
        first_cursor_created_at=snapshot.cursor_created_at,
        first_cursor_message_id=snapshot.cursor_message_id,
        text=text,
        episode_ids=[str(episode.id) for episode in episodes],
        fact_ids=[str(fact.id) for fact in facts],
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _impressions(db_client: httpx.AsyncClient, room: Room) -> Any:
    resp = await db_client.get(_items_path(room))
    assert resp.status_code == 200
    return resp.json()["impressions"]


@pytest.mark.usefixtures("items_visible")
async def test_impressions_are_null_while_their_own_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    episode = _make_memory_episode(room.room_id, snapshot, **_ends_at(room, 5))
    db_session.add(episode)
    await db_session.commit()
    await _impression(db_session, room, snapshot, episodes=[episode])

    assert settings.memory_impressions_visible is False
    assert await _impressions(db_client, room) is None


@pytest.mark.usefixtures("impressions_visible")
async def test_impressions_are_null_once_the_room_model_leaves_the_memory_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기억 범위에 든 모델로 인상을 쌓은 뒤 방 모델을 범위 밖 모델로 바꾸면, 인상 행이 있어도 구획을 숨긴다."""
    room = await _open_room(db_client, db_session, turns=10)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model="opus"))
    await db_session.commit()
    _enable_chat_premium(monkeypatch)
    monkeypatch.setattr(settings, "memory_model_scope", [("character", "opus")])
    snapshot = await _snapshot_at(db_session, room, turn=10)
    episode = _make_memory_episode(room.room_id, snapshot, **_ends_at(room, 5))
    db_session.add(episode)
    await db_session.commit()
    impression = await _impression(db_session, room, snapshot, episodes=[episode])

    in_scope = await _impressions(db_client, room)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model=None))
    await db_session.commit()
    model_changed = await _impressions(db_client, room)

    assert [item["id"] for item in in_scope] == [str(impression.id)]
    assert model_changed is None


@pytest.mark.usefixtures("impressions_visible")
async def test_impressions_are_null_in_a_room_outside_the_memory_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    await _impression(db_session, room, snapshot)

    # 기본 범위는 Opus 방뿐이라 기본 모델 방은 범위 밖이다.
    assert await _impressions(db_client, room) is None


@pytest.mark.usefixtures("impressions_visible")
async def test_an_in_scope_room_without_impressions_has_an_empty_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _memory_scope_covers_gemini(monkeypatch)
    monkeypatch.setattr(settings, "memory_impressions_write", True)
    room = await _open_room(db_client, db_session, turns=3)

    assert await _impressions(db_client, room) == []


@pytest.mark.usefixtures("impressions_visible")
async def test_an_empty_room_hides_impressions_while_writing_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """쓰기가 꺼져 있으면 인상이 새로 생기지 않으니 "대화가 쌓이면 정리돼요" 빈 상태가 거짓이 된다 — 빈 목록 대신 구획을 숨긴다."""
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=3)

    assert settings.memory_impressions_write is False
    assert await _impressions(db_client, room) is None


@pytest.mark.usefixtures("impressions_visible")
async def test_impressions_already_made_stay_visible_while_writing_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    impression = await _impression(db_session, room, snapshot)

    assert settings.memory_impressions_write is False
    assert [item["id"] for item in await _impressions(db_client, room)] == [str(impression.id)]


@pytest.mark.usefixtures("impressions_visible")
async def test_impressions_come_newest_first_with_counts_and_turn_range_but_no_source_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=30)
    first = await _snapshot_at(db_session, room, turn=10)
    second = await _snapshot_at(db_session, room, turn=20)
    third = await _snapshot_at(db_session, room, turn=30)
    scene_a = _make_memory_episode(room.room_id, first, ordinal=0, **_ends_at(room, 3))
    scene_b = _make_memory_episode(room.room_id, first, ordinal=1, **_ends_at(room, 8))
    scene_c = _make_memory_episode(room.room_id, second, ordinal=0, **_ends_at(room, 14))
    # 같은 키의 옛 값과 새 값 두 행 + 다른 키 한 행 — 근거 사실 수는 키 수라 2 다.
    old_value = _make_memory_fact(room.room_id, first, ordinal=0, value="소꿉친구", **_ends_at(room, 2))
    new_value = _make_memory_fact(room.room_id, second, ordinal=0, value="연인", **_ends_at(room, 17))
    hair = _make_memory_fact(
        room.room_id, second, ordinal=1, kind="fact", subject="지아", object=None, attribute="머리색",
        fact_key="fact|지아|머리색", value="흑발", **_ends_at(room, 12),
    )
    db_session.add_all([scene_a, scene_b, scene_c, old_value, new_value, hair])
    await db_session.commit()
    oldest = await _impression(db_session, room, first, episodes=[scene_a, scene_b], facts=[old_value])
    middle = await _impression(db_session, room, second, episodes=[scene_c], facts=[old_value, new_value, hair])
    newest = await _impression(db_session, room, third)

    items = await _impressions(db_client, room)

    assert [item["id"] for item in items] == [str(newest.id), str(middle.id), str(oldest.id)]
    by_id = {item["id"]: item for item in items}
    assert set(by_id[str(middle.id)]) == {"id", "text", "createdAt", "turnStart", "turnEnd", "sceneCount", "factCount"}
    assert by_id[str(middle.id)]["text"] == middle.text
    assert {key: by_id[str(middle.id)][key] for key in ("turnStart", "turnEnd", "sceneCount", "factCount")} == {
        "turnStart": 2, "turnEnd": 17, "sceneCount": 1, "factCount": 2,
    }
    assert {key: by_id[str(oldest.id)][key] for key in ("turnStart", "turnEnd", "sceneCount", "factCount")} == {
        "turnStart": 2, "turnEnd": 8, "sceneCount": 2, "factCount": 1,
    }
    assert {key: by_id[str(newest.id)][key] for key in ("turnStart", "turnEnd", "sceneCount", "factCount")} == {
        "turnStart": None, "turnEnd": None, "sceneCount": 0, "factCount": 0,
    }


@pytest.mark.usefixtures("impressions_visible")
async def test_impression_counts_and_turns_come_from_the_source_rows_still_present(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """근거 행이 사라지면 개수와 턴 범위가 남은 행으로 줄고, 다 사라지면 턴 범위가 null 이다 — 저장된 id 배열의 길이가 아니다."""
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    early = _make_memory_episode(room.room_id, snapshot, ordinal=0, **_ends_at(room, 2))
    late = _make_memory_episode(room.room_id, snapshot, ordinal=1, **_ends_at(room, 9))
    db_session.add_all([early, late])
    await db_session.commit()
    await _impression(db_session, room, snapshot, episodes=[early, late])

    await db_session.execute(sa.delete(ChatMemoryEpisode).where(ChatMemoryEpisode.id == late.id))
    await db_session.commit()
    one_left = (await _impressions(db_client, room))[0]
    await db_session.execute(sa.delete(ChatMemoryEpisode).where(ChatMemoryEpisode.id == early.id))
    await db_session.commit()
    none_left = (await _impressions(db_client, room))[0]

    assert (one_left["sceneCount"], one_left["turnStart"], one_left["turnEnd"]) == (1, 2, 2)
    assert (none_left["sceneCount"], none_left["turnStart"], none_left["turnEnd"]) == (0, None, None)


@pytest.mark.usefixtures("impressions_visible")
async def test_forgetting_a_scene_drops_the_impression_built_on_it_and_keeps_the_others(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=20)
    first = await _snapshot_at(db_session, room, turn=10)
    second = await _snapshot_at(db_session, room, turn=20)
    forgotten = _make_memory_episode(room.room_id, first, ordinal=0, **_ends_at(room, 4))
    kept = _make_memory_episode(room.room_id, second, ordinal=0, **_ends_at(room, 15))
    db_session.add_all([forgotten, kept])
    await db_session.commit()
    await _impression(db_session, room, first, episodes=[forgotten])
    survivor = await _impression(db_session, room, second, episodes=[kept])

    before = await _impressions(db_client, room)
    resp = await db_client.delete(f"/chat-rooms/{room.room_id}/memory/episodes/{forgotten.id}")
    after = await _impressions(db_client, room)

    assert resp.status_code == 204
    assert len(before) == 2
    assert len(after) == 1
    after[0].pop("createdAt")
    assert after[0] == {
        "id": str(survivor.id),
        "text": survivor.text,
        "turnStart": 15,
        "turnEnd": 15,
        "sceneCount": 1,
        "factCount": 0,
    }


@pytest.mark.usefixtures("impressions_visible")
async def test_someone_elses_room_is_still_refused_with_impressions_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _memory_scope_covers_gemini(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot = await _snapshot_at(db_session, room, turn=10)
    await _impression(db_session, room, snapshot)
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.commit()
    await _login_as(db_client, stranger.id)

    resp = await db_client.get(_items_path(room))

    assert resp.status_code == 403
    assert "impressions" not in resp.json()
