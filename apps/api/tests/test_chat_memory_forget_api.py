"""방 기억 잊게 하기 — 방 주인이 고른 장면 하나나 사실 키 하나를 실제로 지운다.

- 장면 하나를 잊으면 그 행과 임베딩이 사라진다. 사실 키 하나를 잊으면 그 방의 같은 키 행 전부(옛 값 포함)와 임베딩이 사라진다 —
  최신 행만 지우면 바로 앞 값이 키의 값으로 올라와 지운 것이 그대로 보인다.
- 비밀 사실(키마다 이긴 행의 아는 사람이 정해진 키)을 잊으면 그 키의 어느 행과든 근거 범위가 겹치는 장면도 함께 잊는다 — 회상이
  그 장면을 그 키로 가리고 있었으므로, 사실만 지우면 가림이 풀려 잊은 비밀이 장면으로 다시 실린다. 확인 대화가 개수를 미리 보인다.
  키의 이긴 행이 공개면 회상이 그 키로 아무것도 가리지 않으므로 장면을 함께 지우지 않는다.
- 잊은 뒤 다음 턴 생성 프롬프트(회상·사실 섹션·벡터 회상)와 턴 기록에 그 행의 id·글이 없다 — 스위치를 켠 조건으로 본다.
- 키는 경로가 아니라 질의로 받는다(키에 `/`·`?` 가 들어갈 수 있다). 자기 데이터 삭제라 재동의 게이트가 없다.
- 기억 보기 스위치가 꺼져 있으면 라우트는 등록된 채 404 `MEMORY_ITEMS_DISABLED` 다. 스위치를 다시 꺼도 잊은 행은 돌아오지 않는다.

깨지는 시나리오: 옛 값이 남아 "지웠는데 그대로", 임베딩이 남아 벡터 회상에 다시 걸림, 비밀 사실을 지웠더니 가려졌던 장면이 회상에
실림, 남의 방 기억이 지워짐, 꺼진 스위치에서 지우기가 열림.
"""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_facts import fact_key
from api.chat.memory_nouns import episode_nouns
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.router import _resolve_starting_setup
from api.chat.turn_prompt import GenerationPrompt, build_room_prompt
from api.core.config import settings
from api.db.models import ChatMemoryEmbedding, ChatMemoryEpisode, ChatMemoryFact, ChatRoom, ChatRoomMemorySnapshot
from api.llm.voyage import VoyageEmbeddingClient
from factories import (
    Room,
    VoyageStub,
    _login_as,
    _make_memory_embedding,
    _make_memory_episode,
    _make_memory_fact,
    _make_user,
    _memory_scope_covers_gemini,
    _open_room,
    _room_messages,
)

FACT_HEADER = "[관계와 사실]\n"
_EMBED_MODEL = "voyage-test"
# 스텁의 질의 벡터는 늘 `[1, 0.5, 0.5]` 다 — 같은 방향이면 거리 0.
_NEAR = [1.0, 0.5, 0.5]
_PLAIN = "오늘 날씨 좋다"

_BAKERY_TITLE = "밀알당에 간 날"
_BAKERY_DETAIL = "태민이랑 밀알당에서 소금빵을 먹었다."
_FRIENDS_KEY = fact_key("relation", "민수", "지아")


@pytest.fixture
def items_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_items_visible", True)


def _episode_path(room: Room, episode_id: uuid.UUID) -> str:
    return f"/chat-rooms/{room.room_id}/memory/episodes/{episode_id}"


def _facts_path(room: Room) -> str:
    return f"/chat-rooms/{room.room_id}/memory/facts"


def _preview_path(room: Room) -> str:
    return f"/chat-rooms/{room.room_id}/memory/facts/forget-preview"


async def _room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Room, dict[int, uuid.UUID]]:
    """8턴짜리 스토리 방에 스냅샷 셋(턴 2·4·6 응답까지 접힘)을 심고 (방, 턴 → 스냅샷 id)."""
    room = await _open_room(db_client, db_session, turns=8, lane="story")
    snapshots: dict[int, uuid.UUID] = {}
    for turn in (2, 4, 6):
        assistant = room.turns[turn][1]
        snapshot = ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=assistant.created_at,
            cursor_message_id=assistant.id,
            summary_text=f"턴 {turn} 까지의 요약",
            source="auto",
        )
        db_session.add(snapshot)
        await db_session.flush()
        snapshots[turn] = snapshot.id
    await db_session.commit()
    return room, snapshots


def _span(room: Room, first: int, last: int) -> dict[str, Any]:
    """`first` 턴 사용자 메시지에서 `last` 턴 응답까지의 근거 범위 칸."""
    start, end = room.turns[first][0], room.turns[last][1]
    return {
        "start_created_at": start.created_at,
        "start_message_id": start.id,
        "end_created_at": end.created_at,
        "end_message_id": end.id,
        "start_turn": first,
        "end_turn": last,
    }


async def _scene(
    db_session: AsyncSession,
    room: Room,
    snapshot_id: uuid.UUID,
    *,
    title: str,
    detail: str,
    nouns: list[str],
    turn: int,
    ordinal: int,
) -> uuid.UUID:
    row = _make_memory_episode(
        room.room_id,
        snapshot_id,
        ordinal=ordinal,
        title=title,
        detail=detail,
        nouns=episode_nouns(nouns, title, detail),
        asserted_by="narration",
        **_span(room, turn, turn),
    )
    db_session.add(row)
    await db_session.commit()
    return row.id


async def _fillers(db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID, *, turn: int) -> None:
    """회상에 걸리지 않는 잡담 장면 다섯 — 회상의 장면 수 하한(5)을 잊은 뒤에도 채운다."""
    for i in range(5):
        await _scene(
            db_session,
            room,
            snapshot_id,
            title=f"잡담 {i}",
            detail=f"평범한 하루 {i}번째.",
            nouns=[f"일상{i}"],
            turn=turn,
            ordinal=10 + i,
        )


async def _bakery(db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID, *, turn: int = 1) -> uuid.UUID:
    return await _scene(
        db_session,
        room,
        snapshot_id,
        title=_BAKERY_TITLE,
        detail=_BAKERY_DETAIL,
        nouns=["밀알당", "소금빵"],
        turn=turn,
        ordinal=0,
    )


async def _fact(
    db_session: AsyncSession,
    room: Room,
    snapshot_id: uuid.UUID,
    *,
    value: str,
    first: int,
    last: int,
    ordinal: int = 0,
    key: str = _FRIENDS_KEY,
    known_by: list[str] | None = None,
) -> uuid.UUID:
    row = _make_memory_fact(
        room.room_id,
        snapshot_id,
        ordinal=ordinal,
        fact_key=key,
        value=value,
        known_by=known_by,
        asserted_by="narration",
        **_span(room, first, last),
    )
    db_session.add(row)
    await db_session.commit()
    return row.id


async def _embed(db_session: AsyncSession, room: Room, **target: uuid.UUID) -> None:
    db_session.add(_make_memory_embedding(room.room_id, model=_EMBED_MODEL, dims=3, embedding=_NEAR, **target))
    await db_session.commit()


async def _count(db_session: AsyncSession, model: Any, *where: Any) -> int:
    return int(await db_session.scalar(sa.select(sa.func.count()).select_from(model).where(*where)) or 0)


async def _room_row(db_session: AsyncSession, room: Room) -> ChatRoom:
    row = await db_session.scalar(
        sa.select(ChatRoom).where(ChatRoom.id == room.room_id).execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _build(
    db_session: AsyncSession, room: Room, user_content: str, *, embedding_client: VoyageEmbeddingClient | None = None
) -> GenerationPrompt:
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    history = await _room_messages(db_session, room.room_id)
    return await build_room_prompt(
        db_session,
        chat_room,
        setup,
        history,
        user_content,
        None,
        prompt_set,
        sections,
        embedding_client=embedding_client,
    )


def _embed_client() -> VoyageEmbeddingClient:
    stub = VoyageStub()
    return VoyageEmbeddingClient(
        api_key="test-key", model=_EMBED_MODEL, dims=stub.dims, transport=stub.transport(), retry_delays=(0.0, 0.0)
    )


# ---- 스위치 ----


async def test_forget_routes_are_not_found_while_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, snapshots = await _room(db_client, db_session)
    episode_id = await _bakery(db_session, room, snapshots[2])
    await _fact(db_session, room, snapshots[2], value="소꿉친구", first=1, last=1)

    responses = [
        await db_client.delete(_episode_path(room, episode_id)),
        await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY}),
        await db_client.get(_preview_path(room), params={"key": _FRIENDS_KEY}),
    ]

    assert settings.memory_items_visible is False
    assert [(resp.status_code, resp.json()["detail"]) for resp in responses] == [
        (404, {"code": "MEMORY_ITEMS_DISABLED"})
    ] * 3
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.chat_room_id == room.room_id) == 1
    assert await _count(db_session, ChatMemoryFact, ChatMemoryFact.chat_room_id == room.room_id) == 1


async def test_forgotten_rows_stay_gone_after_the_switch_is_turned_off_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치를 끄는 것이 되돌리기다 — 라우트는 다시 닫히지만 이미 잊은 행은 실제로 지워졌으므로 돌아오지 않는다."""
    room, snapshots = await _room(db_client, db_session)
    episode_id = await _bakery(db_session, room, snapshots[2])
    monkeypatch.setattr(settings, "memory_items_visible", True)
    assert (await db_client.delete(_episode_path(room, episode_id))).status_code == 204

    monkeypatch.setattr(settings, "memory_items_visible", False)
    closed = await db_client.get(f"/chat-rooms/{room.room_id}/memory/items")

    assert closed.status_code == 404
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.id == episode_id) == 0


# ---- 주인 확인·없는 대상 ----


@pytest.mark.usefixtures("items_visible")
async def test_someone_elses_room_is_refused_and_nothing_is_forgotten(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, snapshots = await _room(db_client, db_session)
    episode_id = await _bakery(db_session, room, snapshots[2])
    await _fact(db_session, room, snapshots[2], value="소꿉친구", first=1, last=1)
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.commit()
    await _login_as(db_client, stranger.id)

    scene = await db_client.delete(_episode_path(room, episode_id))
    key = await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})
    preview = await db_client.get(_preview_path(room), params={"key": _FRIENDS_KEY})
    missing_room = await db_client.delete(f"/chat-rooms/{uuid.uuid4()}/memory/episodes/{episode_id}")

    assert (scene.status_code, key.status_code, preview.status_code, missing_room.status_code) == (403, 403, 403, 404)
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.chat_room_id == room.room_id) == 1
    assert await _count(db_session, ChatMemoryFact, ChatMemoryFact.chat_room_id == room.room_id) == 1


@pytest.mark.usefixtures("items_visible")
async def test_a_scene_or_key_not_in_the_room_is_not_found(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """다른 방(같은 주인)의 장면 id 로 지우면 그 장면을 건드리지 않고 404, 방에 없는 키도 404 다."""
    room, _ = await _room(db_client, db_session)
    other, other_snapshots = await _room(db_client, db_session)
    await _login_as(db_client, room.user_id)
    foreign_episode = await _bakery(db_session, other, other_snapshots[2])

    scene = await db_client.delete(_episode_path(room, foreign_episode))
    unknown = await db_client.delete(_episode_path(room, uuid.uuid4()))
    key = await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})
    preview = await db_client.get(_preview_path(room), params={"key": _FRIENDS_KEY})

    for resp in (scene, unknown, key, preview):
        assert resp.status_code == 404
        assert resp.json()["detail"] == {"code": "MEMORY_ITEM_NOT_FOUND"}
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.id == foreign_episode) == 1


@pytest.mark.usefixtures("items_visible")
@pytest.mark.parametrize("key", ["", "fact|유나|a\x00b", "가" * 301])
async def test_an_empty_nul_or_overlong_key_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession, key: str
) -> None:
    room, _ = await _room(db_client, db_session)

    deleted = await db_client.delete(_facts_path(room), params={"key": key})
    preview = await db_client.get(_preview_path(room), params={"key": key})

    assert (deleted.status_code, preview.status_code) == (422, 422)


# ---- 지우는 범위 ----


@pytest.mark.usefixtures("items_visible")
async def test_forgetting_a_scene_leaves_no_scene_or_embedding_row_and_keeps_the_rest(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약 버전은 그대로다(요약이 바뀌지 않아 열려 있던 요약 편집을 충돌로 만들지 않는다). 사실 쪽 잊기 세대도 그대로다."""
    room, snapshots = await _room(db_client, db_session)
    episode_id = await _bakery(db_session, room, snapshots[2])
    await _fillers(db_session, room, snapshots[4], turn=3)
    await _embed(db_session, room, episode_id=episode_id)
    before = await _room_row(db_session, room)
    version, generation = before.memory_version, before.memory_forget_generation

    resp = await db_client.delete(_episode_path(room, episode_id))

    assert resp.status_code == 204
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.id == episode_id) == 0
    assert await _count(db_session, ChatMemoryEmbedding, ChatMemoryEmbedding.episode_id == episode_id) == 0
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.chat_room_id == room.room_id) == 5
    after = await _room_row(db_session, room)
    assert (after.memory_version, after.memory_forget_generation) == (version, generation)


@pytest.mark.usefixtures("items_visible")
async def test_forgetting_a_key_removes_every_row_of_that_key_with_their_embeddings(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 키의 행이 세 스냅샷에 걸쳐 있다(값이 바뀐 옛 행 포함). 키 하나를 잊으면 셋 다, 그 임베딩까지 사라지고 다른 키는
    남는다. 공개 키라 장면은 함께 지우지 않는다. 방의 잊기 세대가 하나 오른다(진행 중인 사실 추출이 결과를 버리는 신호)."""
    room, snapshots = await _room(db_client, db_session)
    await _fillers(db_session, room, snapshots[2], turn=1)
    old = await _fact(db_session, room, snapshots[2], value="이웃", first=1, last=1)
    middle = await _fact(db_session, room, snapshots[4], value="친구", first=3, last=3)
    latest = await _fact(db_session, room, snapshots[6], value="소꿉친구", first=5, last=5)
    other_key = fact_key("fact", "유나", "오디션")
    kept = await _fact(db_session, room, snapshots[6], value="겨울", first=5, last=5, ordinal=1, key=other_key)
    for fact_id in (old, latest, kept):
        await _embed(db_session, room, fact_id=fact_id)
    generation = (await _room_row(db_session, room)).memory_forget_generation

    preview = await db_client.get(_preview_path(room), params={"key": _FRIENDS_KEY})
    resp = await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})

    assert preview.status_code == 200
    assert preview.json() == {"episodeCount": 0}
    assert resp.status_code == 204
    assert await _count(db_session, ChatMemoryFact, ChatMemoryFact.id.in_([old, middle, latest])) == 0
    assert await _count(db_session, ChatMemoryEmbedding, ChatMemoryEmbedding.fact_id.in_([old, latest])) == 0
    assert await _count(db_session, ChatMemoryFact, ChatMemoryFact.id == kept) == 1
    assert await _count(db_session, ChatMemoryEmbedding, ChatMemoryEmbedding.fact_id == kept) == 1
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.chat_room_id == room.room_id) == 5
    assert (await _room_row(db_session, room)).memory_forget_generation == generation + 1


@pytest.mark.usefixtures("items_visible")
async def test_forgetting_a_secret_key_also_forgets_scenes_overlapping_any_of_its_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """키의 이긴 행이 아는 사람을 정했다(비밀). 옛 행 범위(턴 1)와 겹치는 장면, 이긴 행 범위(턴 3~4) 안에 든 장면(턴 4)이 함께
    지워지고, 어느 행과도 겹치지 않는 장면(턴 5)과 그 임베딩은 남는다. 미리 보기가 지울 장면 수를 같게 센다. 메시지 하나만
    겹치는 경계는 아래 테스트가 잡는다."""
    room, snapshots = await _room(db_client, db_session)
    early = await _scene(
        db_session, room, snapshots[2], title="첫 장면", detail="처음.", nouns=["처음"], turn=1, ordinal=0
    )
    await _scene(db_session, room, snapshots[4], title="끝 장면", detail="경계.", nouns=["경계"], turn=4, ordinal=0)
    apart = await _scene(
        db_session, room, snapshots[6], title="먼 장면", detail="멀다.", nouns=["멀다"], turn=5, ordinal=0
    )
    await _embed(db_session, room, episode_id=early)
    await _embed(db_session, room, episode_id=apart)
    await _fact(db_session, room, snapshots[2], value="이웃", first=1, last=1)
    await _fact(db_session, room, snapshots[4], value="몰래 사귐", first=3, last=4, known_by=["지아"])

    preview = await db_client.get(_preview_path(room), params={"key": _FRIENDS_KEY})
    resp = await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})

    assert preview.json() == {"episodeCount": 2}
    assert resp.status_code == 204
    remaining = (
        await db_session.scalars(sa.select(ChatMemoryEpisode.id).where(ChatMemoryEpisode.chat_room_id == room.room_id))
    ).all()
    assert remaining == [apart]
    assert await _count(db_session, ChatMemoryEmbedding, ChatMemoryEmbedding.episode_id == early) == 0
    assert await _count(db_session, ChatMemoryEmbedding, ChatMemoryEmbedding.episode_id == apart) == 1
    assert await _count(db_session, ChatMemoryFact, ChatMemoryFact.chat_room_id == room.room_id) == 0


@pytest.mark.usefixtures("items_visible")
async def test_a_scene_sharing_exactly_one_message_with_a_secret_row_is_forgotten(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """겹침은 양 끝을 포함한다. 비밀 행 범위가 턴 3 사용자 메시지에서 시작하고, 한 장면은 바로 그 메시지에서 끝나(메시지 하나만
    공유) 함께 지워진다. 그 바로 앞 메시지(턴 2 응답)에서 끝나는 장면은 한 메시지도 겹치지 않아 남는다."""
    room, snapshots = await _room(db_client, db_session)
    touching = _make_memory_episode(
        room.room_id,
        snapshots[4],
        ordinal=0,
        title="맞닿은 장면",
        detail="맞닿음.",
        nouns=episode_nouns(["맞닿음"], "맞닿은 장면", "맞닿음."),
        asserted_by="narration",
        **{**_span(room, 2, 3), "end_created_at": room.turns[3][0].created_at, "end_message_id": room.turns[3][0].id},
    )
    db_session.add(touching)
    await db_session.commit()
    before = await _scene(
        db_session, room, snapshots[2], title="앞 장면", detail="바로 앞.", nouns=["바로앞"], turn=2, ordinal=0
    )
    await _fact(db_session, room, snapshots[4], value="몰래 사귐", first=3, last=4, known_by=["지아"])

    preview = await db_client.get(_preview_path(room), params={"key": _FRIENDS_KEY})
    resp = await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})

    assert preview.json() == {"episodeCount": 1}
    assert resp.status_code == 204
    remaining = (
        await db_session.scalars(sa.select(ChatMemoryEpisode.id).where(ChatMemoryEpisode.chat_room_id == room.room_id))
    ).all()
    assert remaining == [before]


@pytest.mark.usefixtures("items_visible")
async def test_a_key_whose_winning_row_is_public_forgets_no_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """옛 행은 비밀이었지만 키의 이긴 행은 공개다 — 회상은 이 키로 아무 장면도 가리지 않으므로 사실만 지운다."""
    room, snapshots = await _room(db_client, db_session)
    scene = await _scene(
        db_session, room, snapshots[2], title="첫 장면", detail="처음.", nouns=["처음"], turn=1, ordinal=0
    )
    await _fact(db_session, room, snapshots[2], value="몰래 사귐", first=1, last=1, known_by=["지아"])
    await _fact(db_session, room, snapshots[4], value="공개 연인", first=3, last=3)

    preview = await db_client.get(_preview_path(room), params={"key": _FRIENDS_KEY})
    resp = await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})

    assert preview.json() == {"episodeCount": 0}
    assert resp.status_code == 204
    assert await _count(db_session, ChatMemoryEpisode, ChatMemoryEpisode.id == scene) == 1
    assert await _count(db_session, ChatMemoryFact, ChatMemoryFact.chat_room_id == room.room_id) == 0


@pytest.mark.usefixtures("items_visible")
async def test_a_key_with_slash_and_query_characters_is_forgotten_through_the_query(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, snapshots = await _room(db_client, db_session)
    key = fact_key("fact", "유나", "a/b?c=d&e")
    fact_id = await _fact(db_session, room, snapshots[2], value="값", first=1, last=1, key=key)

    resp = await db_client.delete(_facts_path(room), params={"key": key})

    assert resp.status_code == 204
    assert await _count(db_session, ChatMemoryFact, ChatMemoryFact.id == fact_id) == 0


# ---- 다음 턴 프롬프트 ----


@pytest.mark.usefixtures("items_visible")
async def test_the_next_turn_prompt_carries_no_forgotten_scene_or_fact(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """회상·사실 주입·임베딩 회상을 모두 켠 방. 잊기 전에는 장면이 명사 회상(밀알당을 묻는 턴)과 벡터 회상(명사가 겹치지 않는
    턴)에, 사실이 사실 섹션에 실린다. 장면과 키를 잊은 뒤 같은 두 턴의 프롬프트와 턴 기록 칸 어디에도 그 id·글이 없다."""
    room, snapshots = await _room(db_client, db_session)
    episode_id = await _bakery(db_session, room, snapshots[2])
    await _fillers(db_session, room, snapshots[4], turn=3)
    await _embed(db_session, room, episode_id=episode_id)
    fact_id = await _fact(db_session, room, snapshots[2], value="소꿉친구", first=1, last=1)
    await _embed(db_session, room, fact_id=fact_id)
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    monkeypatch.setattr(settings, "memory_facts_inject", True)
    monkeypatch.setattr(settings, "memory_embed_recall", True)
    _memory_scope_covers_gemini(monkeypatch)

    def _carries(built: GenerationPrompt) -> dict[str, bool]:
        return {
            "scene_text": _BAKERY_DETAIL in built.prompt,
            "fact_text": "소꿉친구" in built.prompt,
            "scene_id": str(episode_id) in [entry["episodeId"] for entry in built.memory_recall],
            "fact_id": str(fact_id) in [entry["factId"] for entry in built.memory_facts],
        }

    noun_before = await _build(db_session, room, "밀알당 기억나?")
    vector_before = await _build(db_session, room, _PLAIN, embedding_client=_embed_client())
    assert _carries(noun_before) == {"scene_text": True, "fact_text": True, "scene_id": True, "fact_id": True}
    assert _carries(vector_before)["scene_id"] is True
    assert vector_before.memory_recall[0]["vectorRank"] == 1

    assert (await db_client.delete(_episode_path(room, episode_id))).status_code == 204
    assert (await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})).status_code == 204
    noun_after = await _build(db_session, room, "밀알당 기억나?")
    vector_after = await _build(db_session, room, _PLAIN, embedding_client=_embed_client())

    nothing = {"scene_text": False, "fact_text": False, "scene_id": False, "fact_id": False}
    assert _carries(noun_after) == nothing
    assert _carries(vector_after) == nothing
    assert _BAKERY_TITLE not in noun_after.prompt and _BAKERY_TITLE not in vector_after.prompt


@pytest.mark.usefixtures("items_visible")
async def test_forgetting_a_secret_fact_does_not_unmask_its_scene_in_recall(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """회상이 켜진 방. 지아만 아는 사실이 밀알당 장면과 같은 구간에 있어, 지아가 없는 턴의 회상은 그 장면을 가린다. 사실 행만
    지우면(비교용) 가림이 풀려 장면이 실린다. 잊게 하기로 그 키를 잊으면 겹치는 장면도 함께 잊으므로 같은 턴에 장면이 없다."""
    room, snapshots = await _room(db_client, db_session)
    await _bakery(db_session, room, snapshots[2])
    await _fillers(db_session, room, snapshots[4], turn=3)
    await _fact(db_session, room, snapshots[2], value="몰래 사귐", first=1, last=1, known_by=["지아"])
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    _memory_scope_covers_gemini(monkeypatch)

    masked = await _build(db_session, room, "밀알당 기억나?")
    savepoint = await db_session.begin_nested()
    await db_session.execute(sa.delete(ChatMemoryFact).where(ChatMemoryFact.chat_room_id == room.room_id))
    unmasked = await _build(db_session, room, "밀알당 기억나?")
    await savepoint.rollback()
    resp = await db_client.delete(_facts_path(room), params={"key": _FRIENDS_KEY})
    forgotten = await _build(db_session, room, "밀알당 기억나?")

    assert _BAKERY_DETAIL not in masked.prompt
    assert _BAKERY_DETAIL in unmasked.prompt
    assert resp.status_code == 204
    assert _BAKERY_DETAIL not in forgotten.prompt
    assert FACT_HEADER not in forgotten.prompt
